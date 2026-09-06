import base64
import hashlib
from cryptography.fernet import Fernet
from app.core.settings import settings


def _get_fernet() -> Fernet:
    """Derive a deterministic 32-byte URL-safe base64 key from SESSION_SECRET for Fernet encryption."""
    raw_secret = settings.SESSION_SECRET or "default-session-secret-key-at-least-32-chars!"
    key = base64.urlsafe_b64encode(hashlib.sha256(raw_secret.encode()).digest())
    return Fernet(key)


def encrypt_token(token: str | None) -> str | None:
    """Encrypt a plaintext token string with AES-128-CBC + HMAC-SHA256 (Fernet)."""
    if not token or not str(token).strip():
        return None
    try:
        f = _get_fernet()
        return f.encrypt(str(token).encode()).decode()
    except Exception:
        return str(token)


def decrypt_token(token: str | None) -> str | None:
    """Decrypt a token string. If decryption fails (e.g. legacy unencrypted token), returns token as-is."""
    if not token or not str(token).strip():
        return None
    try:
        f = _get_fernet()
        return f.decrypt(str(token).encode()).decode()
    except Exception:
        # Fallback to returning token directly if it was not encrypted
        return str(token)
