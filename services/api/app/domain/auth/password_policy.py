"""Password rules (SECURITY_ARCHITECTURE.md 3.1): length over composition rules."""

MIN_LENGTH = 12
MAX_LENGTH = 128  # bounds hashing cost; long passphrases are still allowed

# A tiny local deny-list. A breached-password (k-anonymity) check is a later phase.
_COMMON = frozenset(
    {
        "password1234",
        "password12345",
        "123456789012",
        "qwertyuiopas",
        "letmein12345",
        "iloveyou1234",
        "mindmitra123",
        "welcome12345",
        "changeme1234",
    }
)


def password_problems(password: str, *, email: str | None = None) -> list[str]:
    """Return human-readable reasons the password is unacceptable (empty list = OK)."""
    problems: list[str] = []
    if len(password) < MIN_LENGTH:
        problems.append(f"must be at least {MIN_LENGTH} characters")
    if len(password) > MAX_LENGTH:
        problems.append(f"must be at most {MAX_LENGTH} characters")
    lowered = password.lower()
    if lowered in _COMMON or len(set(password)) < 4:
        problems.append("is too common or too repetitive")
    if email:
        local = email.split("@", 1)[0].lower()
        if len(local) >= 4 and local in lowered:
            problems.append("must not contain your email address")
    return problems
