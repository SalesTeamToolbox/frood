"""
Symmetric encryption for secrets at rest — uses Fernet (AES-128-CBC + HMAC-SHA256).

The encryption key is derived from JWT_SECRET via PBKDF2-HMAC-SHA256 so no
additional key management is needed.  ``cryptography`` is already a transitive
dependency via ``python-jose[cryptography]``.

Stored format: ``fernet:1:<base64-ciphertext>``
Legacy plaintext values (no prefix) pass through ``decrypt_value()`` unchanged,
enabling zero-downtime migration — values are encrypted on next persist.
"""

import base64
import logging
from functools import lru_cache

logger = logging.getLogger("frood.encryption")

_PREFIX = "fernet:1:"


def is_encrypted(value: str) -> bool:
    """Return True if *value* carries the Fernet envelope prefix."""
    return value.startswith(_PREFIX)


@lru_cache(maxsize=4)
def _get_fernet(secret: str):
    """Derive a Fernet instance from *secret* via PBKDF2.

    Cached per unique secret so repeated encrypt/decrypt calls are fast.
    Returns ``None`` if ``cryptography`` is not installed.
    """
    try:
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    except ImportError:
        logger.warning("cryptography not installed — encryption unavailable")
        return None

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"agent42-fernet-v1",  # static salt is fine — secret is already high-entropy
        iterations=480_000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(secret.encode()))
    return Fernet(key)


def encrypt_value(plaintext: str, secret: str) -> str:
    """Encrypt *plaintext* and return a prefixed envelope string.

    If ``cryptography`` is unavailable or *secret* is empty, returns
    *plaintext* unchanged (graceful degradation).
    """
    if not secret:
        return plaintext
    fernet = _get_fernet(secret)
    if fernet is None:
        return plaintext
    token = fernet.encrypt(plaintext.encode())
    return _PREFIX + token.decode()


def decrypt_value(stored: str, secret: str) -> str:
    """Decrypt a previously encrypted value.

    If *stored* lacks the envelope prefix it is returned as-is — this
    provides a transparent migration path for legacy plaintext values.
    """
    if not is_encrypted(stored):
        return stored
    if not secret:
        logger.warning("Cannot decrypt: no secret provided")
        return stored
    fernet = _get_fernet(secret)
    if fernet is None:
        logger.warning("Cannot decrypt: cryptography not installed")
        return stored
    try:
        ciphertext = stored[len(_PREFIX) :]
        return fernet.decrypt(ciphertext.encode()).decode()
    except Exception:
        logger.error("Decryption failed — returning raw value")
        return stored
