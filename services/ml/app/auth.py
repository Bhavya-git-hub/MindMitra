"""Service-to-service authentication.

The API signs a short-lived token (HS256, ``aud=mindmitra-ml``, at most five minutes) with the
shared ``ML_SERVICE_TOKEN`` for every call. A missing, expired, wrongly signed or long-lived
token is refused with 401. Browsers never reach this service.
"""

import datetime as dt
from typing import Final

import jwt

AUDIENCE: Final = "mindmitra-ml"
ISSUER: Final = "mindmitra-api"
MAX_LIFETIME = dt.timedelta(minutes=5)


class Unauthorized(Exception):
    pass


def verify_service_token(token: str, secret: str) -> None:
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "aud", "iss"]},
            leeway=10,
        )
    except jwt.PyJWTError as exc:
        raise Unauthorized from exc
    if int(claims["exp"]) - int(claims["iat"]) > MAX_LIFETIME.total_seconds():
        raise Unauthorized


def sign_service_token(secret: str, now: dt.datetime | None = None) -> str:
    """How a caller makes a token (the API has its own copy of these few lines)."""
    issued = now or dt.datetime.now(dt.UTC)
    return jwt.encode(
        {"aud": AUDIENCE, "iss": ISSUER, "iat": issued, "exp": issued + MAX_LIFETIME},
        secret,
        algorithm="HS256",
    )
