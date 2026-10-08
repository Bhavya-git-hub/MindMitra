"""Field-level encryption (AES-256-GCM) for Sensitive / Clinical-Confidential text.

Ciphertext layout: ``version(1) | nonce(12) | ciphertext+tag``.
The ``context`` (for example ``"therapy.therapy_notes.body"``) is bound as AAD so a value
copied into a different column fails authentication.

Phase note: this is the interim key scheme (one key from the environment). The design in
docs/DATABASE_DESIGN.md section 5 (KMS envelope encryption, per-record data keys, row-bound
AAD) replaces the key source later without changing the stored layout version semantics.
"""

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_VERSION = b"\x01"
_NONCE_LEN = 12


class DecryptionError(Exception):
    """Raised when ciphertext cannot be authenticated (wrong key, context or tampering)."""


def _load_key(b64_key: str) -> bytes:
    key = base64.b64decode(b64_key, validate=True)
    if len(key) != 32:
        raise ValueError("FIELD_ENCRYPTION_KEY must decode to exactly 32 bytes")
    return key


def generate_key() -> str:
    """Generate a new random key (base64). Used for local setup and tests only."""
    return base64.b64encode(os.urandom(32)).decode()


class FieldCipher:
    def __init__(self, b64_key: str) -> None:
        self._aead = AESGCM(_load_key(b64_key))

    def encrypt(self, plaintext: str, context: str) -> bytes:
        nonce = os.urandom(_NONCE_LEN)
        ct = self._aead.encrypt(nonce, plaintext.encode("utf-8"), context.encode("utf-8"))
        return _VERSION + nonce + ct

    def decrypt(self, blob: bytes, context: str) -> str:
        if len(blob) < 1 + _NONCE_LEN + 16 or blob[:1] != _VERSION:
            raise DecryptionError("unrecognised ciphertext format")
        nonce = blob[1 : 1 + _NONCE_LEN]
        try:
            pt = self._aead.decrypt(nonce, blob[1 + _NONCE_LEN :], context.encode("utf-8"))
        except InvalidTag as exc:
            raise DecryptionError("authentication failed") from exc
        return pt.decode("utf-8")
