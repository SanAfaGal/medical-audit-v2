"""Fernet-based encryption/decryption for secrets stored in the database."""
import base64

from cryptography.fernet import Fernet

from app.config import settings

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = settings.secret_key.encode()
        # Pad/truncate to 32 bytes then base64url-encode for Fernet
        raw = key[:32].ljust(32, b"=")
        _fernet = Fernet(base64.urlsafe_b64encode(raw))
    return _fernet


def encrypt(plaintext: str) -> str:
    """Encrypt plaintext using Fernet symmetric encryption."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt a Fernet token back to plaintext."""
    return _get_fernet().decrypt(token.encode()).decode()
