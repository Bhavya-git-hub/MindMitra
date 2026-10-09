"""Password hashing. Plaintext passwords are never stored or logged."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

# Argon2id with the library's current recommended defaults (RFC 9106 low-memory profile).
_hasher = PasswordHasher()

ARGON2ID_PREFIX = "$argon2id$"


def needs_rehash(password_hash: str) -> bool:
    """True when the stored hash uses older Argon2 parameters than the current defaults."""
    return _hasher.check_needs_rehash(password_hash)


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("password must be at least 12 characters")
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False
