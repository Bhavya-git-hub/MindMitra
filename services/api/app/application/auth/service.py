"""Authentication use cases: register, verify e-mail, login, refresh, logout, password reset.

Each public method is one unit of work and commits its own transaction, because some
failures must still persist state (a failed-login counter, a refresh-reuse revocation) before
the caller turns them into an HTTP error.

Security properties (SECURITY_ARCHITECTURE.md section 3):

* Passwords: Argon2id, length-based policy, rehash on login when parameters change.
* Enumeration resistance: login, registration and reset requests answer the same way whether
  or not the account exists; unknown e-mails still pay for one Argon2 verification.
* Lockout: after ``login_lockout_threshold`` failures the account is locked for a short,
  growing period (1, 2, 4 ... capped at 15 minutes). Never a permanent lock.
* Sessions: refresh tokens are opaque, stored hashed, single use and rotated; replaying a used
  one revokes the whole session. Sessions have an absolute lifetime (shorter for staff).
* Every outcome is written to the hash-chained audit log (metadata only).
"""

import dataclasses
import datetime as dt
import functools
import re
import secrets
import uuid
from collections.abc import Callable

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.auth.delivery import TokenDelivery
from app.application.auth.errors import (
    Conflict,
    CsrfFailed,
    InvalidCredentials,
    InvalidToken,
    PasswordRejected,
    RegistrationRejected,
)
from app.core.access_tokens import (
    AccessTokenCodec,
    constant_time_equals,
    new_opaque_token,
    sha256_hex,
)
from app.core.config import Settings
from app.core.crypto import keyed_hash
from app.core.security import hash_password, needs_rehash, verify_password
from app.domain.auth.password_policy import password_problems
from app.infrastructure.db import models as m
from app.infrastructure.db.audit import append_audit_event
from app.infrastructure.db.enums import (
    AuditOutcome,
    ConsentScope,
    OneTimeTokenPurpose,
    SessionRevokeReason,
    UserRole,
    UserStatus,
)
from app.infrastructure.db.ids import uuid7

EMAIL_RE = re.compile(r"^[a-z0-9._%+\-]{1,64}@[a-z0-9.\-]{1,253}\.[a-z]{2,63}$")
MAX_LOCK = dt.timedelta(minutes=15)


def normalise_email(email: str) -> str:
    return email.strip().lower()


@functools.cache
def _dummy_hash() -> str:
    """A real Argon2id hash of a random secret, so unknown accounts cost the same to reject."""
    return hash_password(secrets.token_urlsafe(24))


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


@dataclasses.dataclass(frozen=True)
class IssuedSession:
    user_id: uuid.UUID
    institution_id: uuid.UUID
    role: UserRole
    session_id: uuid.UUID
    access_token: str
    access_expires_at: dt.datetime
    refresh_token: str
    refresh_expires_at: dt.datetime
    csrf_token: str


@dataclasses.dataclass(frozen=True)
class StudentRegistration:
    email: str
    password: str
    full_name: str
    department_code: str
    student_number: str
    enrollment_year: int
    year_of_study: int


class AuthService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        codec: AccessTokenCodec,
        delivery: TokenDelivery,
        now: Callable[[], dt.datetime] = _utcnow,
    ) -> None:
        self.db = session
        self.settings = settings
        self.codec = codec
        self.delivery = delivery
        self.now = now

    # ---- helpers -----------------------------------------------------------------------

    def _ip_hash(self, client_ip: str | None) -> str | None:
        if not client_ip:
            return None
        return keyed_hash(self.settings.field_encryption_key.get_secret_value(), "ip", client_ip)

    async def _audit(
        self,
        user: m.User,
        action: str,
        outcome: AuditOutcome,
        *,
        reason: str | None = None,
        client_ip: str | None = None,
    ) -> None:
        await append_audit_event(
            self.db,
            institution_id=user.institution_id,
            actor_id=user.id,
            actor_role=user.role,
            action=action,
            outcome=outcome,
            resource_type="user",
            resource_id=user.id,
            reason=reason,
            ip_hash=self._ip_hash(client_ip),
        )

    def _session_lifetime(self, role: UserRole) -> dt.timedelta:
        seconds = (
            self.settings.student_session_max_seconds
            if role is UserRole.STUDENT
            else self.settings.staff_session_max_seconds
        )
        return dt.timedelta(seconds=seconds)

    async def _new_refresh_token(
        self, auth_session: m.AuthSession, now: dt.datetime
    ) -> tuple[str, str, dt.datetime]:
        refresh, csrf = new_opaque_token(), new_opaque_token()
        expires = min(
            now + dt.timedelta(seconds=self.settings.refresh_token_ttl_seconds),
            auth_session.absolute_expires_at,
        )
        self.db.add(
            m.RefreshToken(
                id=uuid7(),
                session_id=auth_session.id,
                token_hash=sha256_hex(refresh),
                csrf_hash=sha256_hex(csrf),
                expires_at=expires,
            )
        )
        return refresh, csrf, expires

    def _issue_access(
        self, user: m.User, session_id: uuid.UUID, now: dt.datetime
    ) -> tuple[str, dt.datetime]:
        return self.codec.issue(
            user_id=user.id,
            institution_id=user.institution_id,
            role=user.role.value,
            session_id=session_id,
            now=now,
        )

    async def revoke_user_sessions(self, user_id: uuid.UUID, reason: SessionRevokeReason) -> None:
        await self.db.execute(
            update(m.AuthSession)
            .where(m.AuthSession.user_id == user_id, m.AuthSession.revoked_at.is_(None))
            .values(revoked_at=self.now(), revoked_reason=reason)
        )

    async def _issue_one_time_token(
        self, user: m.User, purpose: OneTimeTokenPurpose, ttl_seconds: int
    ) -> str:
        now = self.now()
        # A new link supersedes any earlier unused link for the same purpose.
        await self.db.execute(
            update(m.OneTimeToken)
            .where(
                m.OneTimeToken.user_id == user.id,
                m.OneTimeToken.purpose == purpose,
                m.OneTimeToken.used_at.is_(None),
            )
            .values(used_at=now)
        )
        token = new_opaque_token()
        self.db.add(
            m.OneTimeToken(
                id=uuid7(),
                institution_id=user.institution_id,
                user_id=user.id,
                purpose=purpose,
                token_hash=sha256_hex(token),
                expires_at=now + dt.timedelta(seconds=ttl_seconds),
            )
        )
        return token

    async def _consume_one_time_token(
        self, token: str, purposes: tuple[OneTimeTokenPurpose, ...]
    ) -> tuple[m.OneTimeToken, m.User]:
        row = (
            await self.db.execute(
                select(m.OneTimeToken, m.User)
                .join(m.User, m.User.id == m.OneTimeToken.user_id)
                .where(m.OneTimeToken.token_hash == sha256_hex(token))
                .with_for_update(of=m.OneTimeToken)
            )
        ).first()
        if row is None:
            raise InvalidToken
        ott, user = row
        if (
            ott.purpose not in purposes
            or ott.used_at is not None
            or ott.expires_at <= self.now()
            or user.deleted_at is not None
        ):
            raise InvalidToken
        ott.used_at = self.now()
        return ott, user

    # ---- registration --------------------------------------------------------------------

    async def register_student(self, data: StudentRegistration, *, client_ip: str | None) -> None:
        """Self-registration for students with an institutional e-mail address.

        The account starts as ``invited`` and becomes ``active`` once the e-mailed
        verification link is used. Whether the e-mail was already registered is not revealed.
        """
        email = normalise_email(data.email)
        if not EMAIL_RE.match(email):
            raise RegistrationRejected("email address is not valid")
        problems = password_problems(data.password, email=email)
        if problems:
            raise PasswordRejected(problems)

        domain = email.rsplit("@", 1)[1]
        institutions = (await self.db.execute(select(m.Institution))).scalars().all()
        matches = [
            i
            for i in institutions
            if any(domain == d or domain.endswith("." + d) for d in i.email_domains)
        ]
        if len(matches) != 1:
            raise RegistrationRejected("this email domain is not registered with MindMitra")
        inst = matches[0]

        dept = (
            await self.db.execute(
                select(m.Department).where(
                    m.Department.institution_id == inst.id,
                    m.Department.code == data.department_code.strip().upper(),
                )
            )
        ).scalar_one_or_none()
        if dept is None:
            raise RegistrationRejected("unknown department code")

        existing = (
            await self.db.execute(
                select(m.User.id).where(m.User.institution_id == inst.id, m.User.email == email)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return  # same response as a new registration: no account enumeration

        user = m.User(
            id=uuid7(),
            institution_id=inst.id,
            email=email,
            full_name=data.full_name.strip(),
            role=UserRole.STUDENT,
            status=UserStatus.INVITED,
        )
        user.credential = m.Credential(password_hash=hash_password(data.password))
        self.db.add(user)
        await self.db.flush()
        self.db.add(
            m.Student(
                user_id=user.id,
                institution_id=inst.id,
                department_id=dept.id,
                student_number=data.student_number.strip(),
                enrollment_year=data.enrollment_year,
                year_of_study=data.year_of_study,
            )
        )
        self.db.add(
            m.Consent(
                institution_id=inst.id,
                user_id=user.id,
                scope=ConsentScope.TERMS_AND_PRIVACY,
                policy_version=self.settings.terms_policy_version,
                source="registration",
            )
        )
        try:
            await self.db.flush()
        except IntegrityError as exc:
            await self.db.rollback()
            raise Conflict("this student number is already registered") from exc
        token = await self._issue_one_time_token(
            user,
            OneTimeTokenPurpose.EMAIL_VERIFICATION,
            self.settings.email_verification_ttl_seconds,
        )
        await self._audit(user, "auth.register", AuditOutcome.ALLOWED, client_ip=client_ip)
        await self.db.commit()
        await self.delivery.send(
            user_id=user.id,
            email=email,
            purpose=OneTimeTokenPurpose.EMAIL_VERIFICATION,
            token=token,
        )

    async def verify_email(self, token: str) -> None:
        try:
            _ott, user = await self._consume_one_time_token(
                token, (OneTimeTokenPurpose.EMAIL_VERIFICATION,)
            )
        except InvalidToken:
            await self.db.rollback()
            raise
        if user.status is UserStatus.INVITED:
            user.status = UserStatus.ACTIVE
        await self._audit(user, "auth.email_verified", AuditOutcome.ALLOWED)
        await self.db.commit()

    # ---- login / refresh / logout ----------------------------------------------------------

    async def login(
        self,
        email: str,
        password: str,
        *,
        institution_slug: str | None = None,
        client_ip: str | None = None,
    ) -> IssuedSession:
        now = self.now()
        email = normalise_email(email)
        stmt = (
            select(m.User, m.Credential)
            .join(m.Credential, m.Credential.user_id == m.User.id)
            .where(m.User.email == email, m.User.deleted_at.is_(None))
            .with_for_update(of=m.Credential)
        )
        if institution_slug:
            stmt = stmt.join(m.Institution, m.Institution.id == m.User.institution_id).where(
                m.Institution.slug == institution_slug
            )
        rows = (await self.db.execute(stmt)).all()
        if len(rows) != 1:
            # Unknown e-mail, or the same e-mail in several institutions without a slug.
            verify_password(_dummy_hash(), password)
            await self.db.rollback()
            raise InvalidCredentials
        user, cred = rows[0]

        if cred.locked_until is not None and cred.locked_until > now:
            verify_password(_dummy_hash(), password)
            await self._audit(
                user, "auth.login", AuditOutcome.DENIED, reason="locked", client_ip=client_ip
            )
            await self.db.commit()
            raise InvalidCredentials

        if not verify_password(cred.password_hash, password):
            cred.failed_attempts = min(cred.failed_attempts + 1, 1000)
            reason = "bad_password"
            over = cred.failed_attempts - self.settings.login_lockout_threshold
            if over >= 0:
                cred.locked_until = now + min(dt.timedelta(minutes=2 ** min(over, 4)), MAX_LOCK)
                reason = "locked_after_failures"
            await self._audit(
                user, "auth.login", AuditOutcome.DENIED, reason=reason, client_ip=client_ip
            )
            await self.db.commit()
            raise InvalidCredentials

        if user.status is not UserStatus.ACTIVE:
            # Correct password but the account is invited/suspended/deactivated: same answer.
            await self._audit(
                user,
                "auth.login",
                AuditOutcome.DENIED,
                reason=f"status_{user.status.value}",
                client_ip=client_ip,
            )
            await self.db.commit()
            raise InvalidCredentials

        cred.failed_attempts = 0
        cred.locked_until = None
        if needs_rehash(cred.password_hash):
            cred.password_hash = hash_password(password)
        user.last_login_at = now

        auth_session = m.AuthSession(
            id=uuid7(),
            institution_id=user.institution_id,
            user_id=user.id,
            absolute_expires_at=now + self._session_lifetime(user.role),
            last_seen_at=now,
            ip_hash=self._ip_hash(client_ip),
        )
        self.db.add(auth_session)
        await self.db.flush()
        refresh, csrf, refresh_expires = await self._new_refresh_token(auth_session, now)
        access, access_expires = self._issue_access(user, auth_session.id, now)
        await self._audit(user, "auth.login", AuditOutcome.ALLOWED, client_ip=client_ip)
        await self.db.commit()
        return IssuedSession(
            user_id=user.id,
            institution_id=user.institution_id,
            role=user.role,
            session_id=auth_session.id,
            access_token=access,
            access_expires_at=access_expires,
            refresh_token=refresh,
            refresh_expires_at=refresh_expires,
            csrf_token=csrf,
        )

    async def refresh(
        self, refresh_token: str, csrf_token: str | None, *, client_ip: str | None = None
    ) -> IssuedSession:
        now = self.now()
        row = (
            await self.db.execute(
                select(m.RefreshToken, m.AuthSession, m.User)
                .join(m.AuthSession, m.AuthSession.id == m.RefreshToken.session_id)
                .join(m.User, m.User.id == m.AuthSession.user_id)
                .where(m.RefreshToken.token_hash == sha256_hex(refresh_token))
                .with_for_update(of=[m.RefreshToken, m.AuthSession])
            )
        ).first()
        if row is None:
            await self.db.rollback()
            raise InvalidToken
        token_row, auth_session, user = row

        # CSRF first: a cross-site request must not be able to trigger reuse revocation.
        if not csrf_token or not constant_time_equals(sha256_hex(csrf_token), token_row.csrf_hash):
            await self.db.rollback()
            raise CsrfFailed

        if token_row.used_at is not None:
            # Replay of a rotated token: assume theft, revoke the whole family.
            if auth_session.revoked_at is None:
                auth_session.revoked_at = now
                auth_session.revoked_reason = SessionRevokeReason.REFRESH_REUSE
            await self._audit(
                user,
                "auth.refresh",
                AuditOutcome.DENIED,
                reason="refresh_token_reuse",
                client_ip=client_ip,
            )
            await self.db.commit()
            raise InvalidToken

        if (
            token_row.expires_at <= now
            or auth_session.revoked_at is not None
            or auth_session.absolute_expires_at <= now
            or user.status is not UserStatus.ACTIVE
            or user.deleted_at is not None
        ):
            await self.db.rollback()
            raise InvalidToken

        token_row.used_at = now
        auth_session.last_seen_at = now
        refresh, csrf, refresh_expires = await self._new_refresh_token(auth_session, now)
        access, access_expires = self._issue_access(user, auth_session.id, now)
        await self.db.commit()
        return IssuedSession(
            user_id=user.id,
            institution_id=user.institution_id,
            role=user.role,
            session_id=auth_session.id,
            access_token=access,
            access_expires_at=access_expires,
            refresh_token=refresh,
            refresh_expires_at=refresh_expires,
            csrf_token=csrf,
        )

    async def logout(self, session_id: uuid.UUID, user_id: uuid.UUID) -> None:
        await self.db.execute(
            update(m.AuthSession)
            .where(
                m.AuthSession.id == session_id,
                m.AuthSession.user_id == user_id,
                m.AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=self.now(), revoked_reason=SessionRevokeReason.LOGOUT)
        )
        user = await self.db.get(m.User, user_id)
        if user is not None:
            await self._audit(user, "auth.logout", AuditOutcome.ALLOWED)
        await self.db.commit()

    # ---- password reset -----------------------------------------------------------------

    async def request_password_reset(
        self, email: str, *, institution_slug: str | None = None
    ) -> None:
        """Always succeeds from the caller's point of view (no account enumeration)."""
        email = normalise_email(email)
        stmt = select(m.User).where(m.User.email == email, m.User.deleted_at.is_(None))
        if institution_slug:
            stmt = stmt.join(m.Institution, m.Institution.id == m.User.institution_id).where(
                m.Institution.slug == institution_slug
            )
        users = (await self.db.execute(stmt)).scalars().all()
        if len(users) != 1 or users[0].status is not UserStatus.ACTIVE:
            await self.db.rollback()
            return
        user = users[0]
        token = await self._issue_one_time_token(
            user, OneTimeTokenPurpose.PASSWORD_RESET, self.settings.password_reset_ttl_seconds
        )
        await self._audit(user, "auth.password_reset_requested", AuditOutcome.ALLOWED)
        await self.db.commit()
        await self.delivery.send(
            user_id=user.id, email=email, purpose=OneTimeTokenPurpose.PASSWORD_RESET, token=token
        )

    async def reset_password(self, token: str, new_password: str) -> None:
        """Complete a reset or first-time account setup. Signs the user out everywhere."""
        try:
            ott, user = await self._consume_one_time_token(
                token, (OneTimeTokenPurpose.PASSWORD_RESET, OneTimeTokenPurpose.ACCOUNT_SETUP)
            )
            problems = password_problems(new_password, email=user.email)
            if problems:
                raise PasswordRejected(problems)
        except (InvalidToken, PasswordRejected):
            await self.db.rollback()  # a rejected password does not burn the token
            raise
        now = self.now()
        cred = await self.db.get(m.Credential, user.id, with_for_update=True)
        new_hash = hash_password(new_password)
        if cred is None:
            self.db.add(m.Credential(user_id=user.id, password_hash=new_hash))
        else:
            cred.password_hash = new_hash
            cred.password_changed_at = now
            cred.failed_attempts = 0
            cred.locked_until = None
        if ott.purpose is OneTimeTokenPurpose.ACCOUNT_SETUP and user.status is UserStatus.INVITED:
            user.status = UserStatus.ACTIVE
        await self.revoke_user_sessions(user.id, SessionRevokeReason.PASSWORD_CHANGED)
        await self._audit(user, f"auth.{ott.purpose.value}_completed", AuditOutcome.ALLOWED)
        await self.db.commit()

    async def issue_account_setup(self, user: m.User) -> str:
        """For admin-created accounts: the user chooses their own first password."""
        return await self._issue_one_time_token(
            user, OneTimeTokenPurpose.ACCOUNT_SETUP, self.settings.account_setup_ttl_seconds
        )
