import base64
from types import SimpleNamespace

import pytest

import apps.dependency.auth as auth
from error import AuthenticationError


def test_env_key_wins_and_is_base64_decoded(monkeypatch):
    """A base64-encoded JWT_PUBLIC_KEY is decoded to raw PEM and preferred over the file."""
    pem = "-----BEGIN PUBLIC KEY-----\nabc\n-----END PUBLIC KEY-----\n"
    monkeypatch.setattr(auth, "JWT_PUBLIC_KEY", base64.b64encode(pem.encode()).decode())
    assert auth._load_centralized_public_key() == pem


def test_falls_back_to_public_key_file(monkeypatch, tmp_path):
    """With no env key, the raw PEM file installed by `make oauth-keys` is used."""
    key_file = tmp_path / "public.key"
    key_file.write_text("file-pem")
    monkeypatch.setattr(auth, "JWT_PUBLIC_KEY", "")
    monkeypatch.setattr(auth, "_PUBLIC_KEY_FILE", key_file)
    assert auth._load_centralized_public_key() == "file-pem"


def test_returns_none_when_neither_configured(monkeypatch, tmp_path):
    """No env key and no file → None (auth then rejects every request)."""
    monkeypatch.setattr(auth, "JWT_PUBLIC_KEY", "")
    monkeypatch.setattr(auth, "_PUBLIC_KEY_FILE", tmp_path / "missing.key")
    assert auth._load_centralized_public_key() is None


def test_non_base64_env_key_does_not_raise(monkeypatch, tmp_path):
    """A garbage JWT_PUBLIC_KEY is logged and ignored, not raised as binascii.Error."""
    monkeypatch.setattr(auth, "JWT_PUBLIC_KEY", "not-valid-base64!!!")
    monkeypatch.setattr(auth, "_PUBLIC_KEY_FILE", tmp_path / "missing.key")
    assert auth._load_centralized_public_key() is None


def _fake_request():
    return SimpleNamespace(
        method="GET",
        url=SimpleNamespace(path="/api/test"),
        client=SimpleNamespace(host="127.0.0.1"),
        state=SimpleNamespace(),
    )


@pytest.mark.parametrize("missing", ["JWT_ISSUER", "JWT_AUDIENCE"])
async def test_empty_issuer_or_audience_is_auth_not_configured(monkeypatch, missing):
    """Blank JWT_ISSUER/JWT_AUDIENCE → a clear auth_not_configured, never a
    misleading 'Invalid issuer' from jwt.decode."""
    monkeypatch.setattr(auth, "CENTRALIZED_PUBLIC_KEY", "-----BEGIN PUBLIC KEY-----\nx\n-----END PUBLIC KEY-----\n")
    monkeypatch.setattr(auth, "JWT_ISSUER", "" if missing == "JWT_ISSUER" else "http://backend.localhost:8080")
    monkeypatch.setattr(auth, "JWT_AUDIENCE", "" if missing == "JWT_AUDIENCE" else "erp")

    with pytest.raises(AuthenticationError) as exc:
        await auth.get_user(_fake_request(), credential=None)
    assert exc.value.message == "auth_not_configured"
