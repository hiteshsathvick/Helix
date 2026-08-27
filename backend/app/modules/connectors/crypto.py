"""OAuth token encryption at rest (SPEC.md §26). Wraps `cryptography`'s
Fernet so the raw key/cipher handling lives in one place, never scattered
across connector implementations. Fernet gives authenticated (tamper-
evident) symmetric encryption -- the boring, correct choice over hand-
rolling AES-GCM for a value that must be decrypted (not just verified) to
actually use, unlike everything in core/security.py, which is one-way.
"""

from cryptography.fernet import Fernet

from app.core.config import get_settings


def _fernet() -> Fernet:
    return Fernet(get_settings().connector_encryption_key.encode())


def encrypt_token(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str, ttl_seconds: int | None = None) -> str:
    """`ttl_seconds` rejects a token older than that (Fernet embeds its own
    encryption timestamp) -- used for the OAuth `state` param (see
    connectors/service.py), which should only be valid for a short window,
    not for the OAuth tokens themselves, which have no such requirement."""
    return _fernet().decrypt(ciphertext.encode(), ttl=ttl_seconds).decode()
