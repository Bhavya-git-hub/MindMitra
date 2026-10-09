"""JWT access tokens (EdDSA / Ed25519) and opaque random tokens.

Access tokens are short-lived and carry only identifiers: ``sub`` (user id), ``inst``
(institution id), ``role``, ``sid`` (session id), ``jti``, ``typ=access``. They are a hint,
not the authority: every request re-checks the session and the user's current role and
status in the database (see ``app/api/deps.py``).

Refresh, CSRF and one-time tokens are opaque 256-bit random strings; only their SHA-256
hashes are stored.
"""

import base64
import binascii
import dataclasses
import datetime as dt
import hashlib
import hmac
import secrets
import uuid
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

ALGORITHM = "EdDSA"
TOKEN_TYPE = "access"  # noqa: S105 - a claim value, not a secret
_REQUIRED_CLAIMS = ["exp", "iat", "nbf", "iss", "aud", "sub", "jti"]


class InvalidAccessToken(Exception):
    """Signature, expiry, issuer, audience, type or claim shape is wrong."""


def new_opaque_token() -> str:
    return secrets.token_urlsafe(32)  # 256 bits


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def generate_private_key_pem() -> str:
    """A new Ed25519 private key (PKCS#8 PEM). For local setup and tests only."""
    return (
        Ed25519PrivateKey.generate()
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode()
    )


def load_private_key(value: str) -> Ed25519PrivateKey:
    """Accept a PEM string or base64 of a PEM (convenient in single-line env vars)."""
    text = value.strip()
    if not text.startswith("-----BEGIN"):
        try:
            text = base64.b64decode(text, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise ValueError("JWT_PRIVATE_KEY must be a PEM or base64 of a PEM") from exc
    try:
        key = serialization.load_pem_private_key(text.encode("utf-8"), password=None)
    except (ValueError, TypeError) as exc:
        raise ValueError("JWT_PRIVATE_KEY is not a valid PEM private key") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("JWT_PRIVATE_KEY must be an Ed25519 key")
    return key


@dataclasses.dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    institution_id: uuid.UUID
    role: str
    session_id: uuid.UUID
    expires_at: dt.datetime


class AccessTokenCodec:
    def __init__(
        self, private_key: Ed25519PrivateKey, *, issuer: str, audience: str, ttl: dt.timedelta
    ) -> None:
        self._private = private_key
        self._public: Ed25519PublicKey = private_key.public_key()
        raw = self._public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.key_id = hashlib.sha256(raw).hexdigest()[:16]
        self._issuer = issuer
        self._audience = audience
        self.ttl = ttl

    def issue(
        self,
        *,
        user_id: uuid.UUID,
        institution_id: uuid.UUID,
        role: str,
        session_id: uuid.UUID,
        now: dt.datetime,
    ) -> tuple[str, dt.datetime]:
        expires = now + self.ttl
        claims: dict[str, Any] = {
            "iss": self._issuer,
            "aud": self._audience,
            "sub": str(user_id),
            "inst": str(institution_id),
            "role": role,
            "sid": str(session_id),
            "typ": TOKEN_TYPE,
            "jti": uuid.uuid4().hex,
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int(expires.timestamp()),
        }
        token = jwt.encode(claims, self._private, algorithm=ALGORITHM, headers={"kid": self.key_id})
        return token, expires

    def decode(self, token: str) -> AccessClaims:
        try:
            claims = jwt.decode(
                token,
                self._public,
                algorithms=[ALGORITHM],  # never trust the header's "alg"
                audience=self._audience,
                issuer=self._issuer,
                leeway=5,
                options={"require": _REQUIRED_CLAIMS},
            )
            if claims.get("typ") != TOKEN_TYPE:
                raise InvalidAccessToken("wrong token type")
            return AccessClaims(
                user_id=uuid.UUID(claims["sub"]),
                institution_id=uuid.UUID(claims["inst"]),
                role=str(claims["role"]),
                session_id=uuid.UUID(claims["sid"]),
                expires_at=dt.datetime.fromtimestamp(claims["exp"], dt.UTC),
            )
        except (jwt.PyJWTError, KeyError, ValueError, TypeError) as exc:
            raise InvalidAccessToken(str(exc)) from exc
