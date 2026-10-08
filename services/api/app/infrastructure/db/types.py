"""Custom column types."""

from typing import Any

from sqlalchemy import LargeBinary
from sqlalchemy.types import TypeDecorator

from app.core.config import get_settings
from app.core.crypto import FieldCipher

_cipher: FieldCipher | None = None


def _get_cipher() -> FieldCipher:
    global _cipher
    if _cipher is None:
        _cipher = FieldCipher(get_settings().field_encryption_key.get_secret_value())
    return _cipher


def reset_cipher() -> None:
    """Drop the cached cipher (tests that swap keys)."""
    global _cipher
    _cipher = None


class EncryptedText(TypeDecorator[str]):
    """Transparently encrypts text to BYTEA (AES-256-GCM) on write and decrypts on read.

    ``context`` is bound as AAD, so a ciphertext cannot be moved to another column.
    Encrypted columns cannot be searched, filtered or indexed by plaintext.
    """

    impl = LargeBinary
    cache_ok = True

    def __init__(self, context: str) -> None:
        super().__init__()
        self.context = context

    def process_bind_param(self, value: str | None, dialect: Any) -> bytes | None:
        if value is None:
            return None
        return _get_cipher().encrypt(value, self.context)

    def process_result_value(self, value: bytes | None, dialect: Any) -> str | None:
        if value is None:
            return None
        return _get_cipher().decrypt(bytes(value), self.context)
