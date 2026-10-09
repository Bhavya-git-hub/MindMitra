"""Resource policies (ABAC layer): may *this* actor touch *this* record?

Every function is pure: callers load the facts (tenant, care-team link, consent, authorship)
and the policy decides. A ``Decision`` carries a machine-readable reason that goes to the
audit log; ``hide`` tells the API to answer 404 instead of 403 so the caller cannot learn
that the record exists (API_DESIGN.md section 1.1).
"""

import dataclasses
import uuid

from app.domain.auth.permissions import Role


@dataclasses.dataclass(frozen=True)
class Principal:
    """The authenticated caller, as re-validated against the database on every request."""

    user_id: uuid.UUID
    institution_id: uuid.UUID
    role: Role
    session_id: uuid.UUID


@dataclasses.dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    hide: bool = False  # deny as "not found" rather than "forbidden"


def allow(reason: str) -> Decision:
    return Decision(True, reason)


def deny(reason: str, *, hide: bool = False) -> Decision:
    return Decision(False, reason, hide)


def same_tenant(actor: Principal, institution_id: uuid.UUID) -> bool:
    return actor.institution_id == institution_id


def can_read_student_wellness(
    actor: Principal,
    *,
    student_id: uuid.UUID,
    student_institution_id: uuid.UUID,
    has_active_care_link: bool,
    has_sharing_consent: bool,
) -> Decision:
    """Students read their own records; a therapist needs a care-team link *and* consent."""
    if not same_tenant(actor, student_institution_id):
        return deny("other_tenant", hide=True)
    if actor.role is Role.STUDENT:
        return allow("own_record") if actor.user_id == student_id else deny("not_owner", hide=True)
    if actor.role is Role.THERAPIST:
        if not has_active_care_link:
            return deny("no_care_team_link", hide=True)
        if not has_sharing_consent:
            return deny("no_sharing_consent")
        return allow("care_team_with_consent")
    return deny("role_not_permitted")


def can_read_therapy_note(
    actor: Principal,
    *,
    note_institution_id: uuid.UUID,
    note_author_id: uuid.UUID,
    has_active_care_link: bool,
) -> Decision:
    """Only the authoring therapist, while still on the student's care team."""
    if actor.role is not Role.THERAPIST:
        return deny("role_not_permitted")
    if not same_tenant(actor, note_institution_id):
        return deny("other_tenant", hide=True)
    if not has_active_care_link:
        return deny("no_care_team_link", hide=True)
    if actor.user_id != note_author_id:
        return deny("not_author", hide=True)
    return allow("authoring_therapist")


def can_read_ai_conversation(
    actor: Principal, *, owner_student_id: uuid.UUID, institution_id: uuid.UUID
) -> Decision:
    """Companion conversations are visible to the owning student and nobody else (INV-8)."""
    if (
        actor.role is Role.STUDENT
        and actor.user_id == owner_student_id
        and same_tenant(actor, institution_id)
    ):
        return allow("own_conversation")
    return deny("private_to_student", hide=True)


def can_manage_appointment(
    actor: Principal, *, appointment_institution_id: uuid.UUID, therapist_id: uuid.UUID
) -> Decision:
    if actor.role is not Role.THERAPIST:
        return deny("role_not_permitted")
    if not same_tenant(actor, appointment_institution_id) or actor.user_id != therapist_id:
        return deny("not_appointment_therapist", hide=True)
    return allow("appointment_therapist")


def can_manage_user(
    actor: Principal, *, target_user_id: uuid.UUID, target_institution_id: uuid.UUID
) -> Decision:
    """Admins manage accounts in their own institution, and never their own status."""
    if actor.role is not Role.ADMIN:
        return deny("role_not_permitted")
    if not same_tenant(actor, target_institution_id):
        return deny("other_tenant", hide=True)
    if actor.user_id == target_user_id:
        return deny("cannot_manage_self")
    return allow("institution_admin")
