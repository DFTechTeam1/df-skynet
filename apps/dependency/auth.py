import base64
import traceback
from typing import Optional
from fastapi import Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from log import logging
from utils import get_project_root
from apps.secret import JWT_PUBLIC_KEY, JWT_ISSUER, JWT_AUDIENCE
from error import (
    AuthenticationError,
    BaseError,
    ServiceError,
)


def _assert_canonical_jwt(token: str) -> None:
    """
    Reject tokens where any base64url segment is not in canonical form.

    A base64url string is canonical when decode→re-encode produces the exact
    same string. Padding bits that are supposed to be zero must actually be
    zero. This catches tampering that only touches padding bits and would
    otherwise decode to identical bytes (e.g. last-char A→B on a 256-byte sig).
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise AuthenticationError()
    for part in parts:
        padded = part + "=" * (-len(part) % 4)
        try:
            decoded = base64.urlsafe_b64decode(padded)
        except Exception:
            raise AuthenticationError()
        reencoded = base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=")
        if reencoded != part:
            raise AuthenticationError()


# Centralized RS256 public key: base64-encoded PEM from the JWT_PUBLIC_KEY env,
# or the raw PEM file installed by `make oauth-keys` (secrets/oauth/public.key).
_PUBLIC_KEY_FILE = get_project_root() / "secrets" / "oauth" / "public.key"


def _load_centralized_public_key() -> Optional[str]:
    if JWT_PUBLIC_KEY:
        try:
            return base64.b64decode(JWT_PUBLIC_KEY).decode("utf-8")
        except Exception:
            logging.error("auth: JWT_PUBLIC_KEY is set but is not valid base64 — ignoring it")
    if _PUBLIC_KEY_FILE.exists():
        return _PUBLIC_KEY_FILE.read_text()
    return None


CENTRALIZED_PUBLIC_KEY: Optional[str] = _load_centralized_public_key()

bearer_scheme = HTTPBearer(auto_error=False)


async def get_user(
    request: Request,
    credential: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    """
    Validate a centralized RS256 access token and return its identity claims.

    Returns a dict shaped `{user_id, roles, permissions}` derived from the token
    (`sub`, `roles`, `permissions`). No DB lookup — the signed token is trusted.

    Raises:
        AuthenticationError: missing/invalid/expired token, or key not configured.
    """
    route = f"{request.method} {request.url.path}"
    client_ip = request.client.host if request.client else "unknown"
    try:
        if CENTRALIZED_PUBLIC_KEY is None:
            logging.error(f"auth: JWT public key not configured — rejecting {route} from {client_ip}")
            raise AuthenticationError(message="auth_not_configured")

        if not JWT_ISSUER or not JWT_AUDIENCE:
            missing = "JWT_ISSUER" if not JWT_ISSUER else "JWT_AUDIENCE"
            logging.error(f"auth: {missing} not configured — rejecting {route} from {client_ip}")
            raise AuthenticationError(message="auth_not_configured")

        if not credential or not credential.credentials:
            logging.info(f"auth: no bearer token on {route} from {client_ip}")
            raise AuthenticationError(message="auth_unauthenticated")

        try:
            _assert_canonical_jwt(credential.credentials)
        except AuthenticationError:
            logging.warning(f"auth: non-canonical JWT encoding on {route} from {client_ip}")
            raise

        try:
            claims = jwt.decode(
                credential.credentials,
                CENTRALIZED_PUBLIC_KEY,
                algorithms=["RS256"],
                audience=JWT_AUDIENCE,
                issuer=JWT_ISSUER,
                options={"require_exp": True, "require_iat": True},
            )
        except JWTError as e:
            logging.warning(f"auth: token rejected on {route} from {client_ip}: {e}")
            raise AuthenticationError()

        user_id = claims.get("sub")
        if not user_id:
            logging.warning(f"auth: valid token with no 'sub' claim on {route} from {client_ip}")
            raise AuthenticationError()

        user = {
            "user_id": user_id,
            "roles": claims.get("roles", []),
            "permissions": claims.get("permissions", []),
        }
        request.state.user = user
        logging.info(f"auth: user={user_id} authenticated on {route} from {client_ip}")
        return user

    except BaseError:
        raise
    except Exception:
        logging.error(f"auth: unexpected failure on {route} from {client_ip}\n{traceback.format_exc()}")
        raise ServiceError()
