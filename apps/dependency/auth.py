import base64
import traceback
from typing import Optional
from fastapi import Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from log import logging
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


CENTRALIZED_PUBLIC_KEY: Optional[str] = base64.b64decode(JWT_PUBLIC_KEY).decode("utf-8") if JWT_PUBLIC_KEY else None

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
    try:
        if CENTRALIZED_PUBLIC_KEY is None:
            raise AuthenticationError(message="auth_not_configured")

        if not credential or not credential.credentials:
            raise AuthenticationError(message="auth_unauthenticated")

        _assert_canonical_jwt(credential.credentials)

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
            logging.warning(f"Centralized token rejected: {e}")
            raise AuthenticationError()

        user_id = claims.get("sub")
        if not user_id:
            raise AuthenticationError()

        user = {
            "user_id": user_id,
            "roles": claims.get("roles", []),
            "permissions": claims.get("permissions", []),
        }
        request.state.user = user
        return user

    except BaseError:
        raise
    except Exception:
        logging.error(traceback.format_exc())
        raise ServiceError()
