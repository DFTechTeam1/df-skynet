import base64

import apps.dependency.auth as auth


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
