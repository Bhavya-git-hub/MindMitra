"""Errors raised by the auth use cases. The API maps them to HTTP problems."""


class AuthError(Exception):
    """Base class."""


class InvalidCredentials(AuthError):
    """Login failed. Deliberately says nothing about *why* (no account enumeration)."""


class InvalidToken(AuthError):
    """A refresh, reset, setup or verification token is unknown, used, expired or revoked."""


class CsrfFailed(AuthError):
    """The CSRF token sent with a cookie-authenticated request does not match."""


class PasswordRejected(AuthError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


class RegistrationRejected(AuthError):
    """Registration input is invalid (unknown email domain, department, ...)."""


class Conflict(AuthError):
    """The request conflicts with existing data that the caller may know about."""
