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


def can_use_own_student_record(
    actor: Principal, *, student_id: uuid.UUID, institution_id: uuid.UUID
) -> Decision:
    """Create, change or read a private student record (goal, recommendation, consent ...).

    Only the student it belongs to, in their own institution. Nobody else, whatever their role,
    including a therapist on the care team: sharing is read-only and consent-gated elsewhere.
    """
    if actor.role is not Role.STUDENT:
        return deny("role_not_permitted")
    if not same_tenant(actor, institution_id) or actor.user_id != student_id:
        return deny("not_owner", hide=True)
    return allow("own_record")


def can_book_with_therapist(
    actor: Principal,
    *,
    therapist_institution_id: uuid.UUID,
    accepting_new_students: bool,
    has_active_care_link: bool,
) -> Decision:
    """Students book with therapists of their own institution who are taking new students
    (or who already work with them)."""
    if actor.role is not Role.STUDENT:
        return deny("role_not_permitted")
    if not same_tenant(actor, therapist_institution_id):
        return deny("other_tenant", hide=True)
    if not accepting_new_students and not has_active_care_link:
        return deny("not_accepting_new_students")
    return allow("student_booking")


def can_cancel_appointment_as_student(
    actor: Principal, *, appointment_institution_id: uuid.UUID, student_id: uuid.UUID
) -> Decision:
    if actor.role is not Role.STUDENT:
        return deny("role_not_permitted")
    if not same_tenant(actor, appointment_institution_id) or actor.user_id != student_id:
        return deny("not_appointment_student", hide=True)
    return allow("appointment_student")


def can_message_in_conversation(
    actor: Principal,
    *,
    conversation_institution_id: uuid.UUID,
    student_id: uuid.UUID,
    therapist_id: uuid.UUID,
    has_active_care_link: bool,
) -> Decision:
    """A conversation is private to its student and therapist, and open only while they are on
    the same care team."""
    if actor.role not in (Role.STUDENT, Role.THERAPIST):
        return deny("role_not_permitted")
    if not same_tenant(actor, conversation_institution_id):
        return deny("other_tenant", hide=True)
    if actor.user_id not in (student_id, therapist_id):
        return deny("not_a_participant", hide=True)
    if not has_active_care_link:
        return deny("no_care_team_link", hide=True)
    return allow("conversation_participant")


def can_read_conversation_history(
    actor: Principal,
    *,
    conversation_institution_id: uuid.UUID,
    student_id: uuid.UUID,
    therapist_id: uuid.UUID,
    has_active_care_link: bool,
    has_history: bool,
) -> Decision:
    """Reading is like writing, with one difference: the student keeps the messages they already
    exchanged after the care team ends. The therapist's access still ends with the link (ADR
    0006), and with no link and no history there is nothing to read (it looks missing)."""
    if (
        actor.role is Role.STUDENT
        and actor.user_id == student_id
        and has_history
        and same_tenant(actor, conversation_institution_id)
    ):
        return allow("own_history")
    return can_message_in_conversation(
        actor,
        conversation_institution_id=conversation_institution_id,
        student_id=student_id,
        therapist_id=therapist_id,
        has_active_care_link=has_active_care_link,
    )


# ---- therapist portal --------------------------------------------------------------------


def can_access_assigned_student(
    actor: Principal, *, student_institution_id: uuid.UUID, has_active_care_link: bool
) -> Decision:
    """A therapist may work with a student only while the student is on their care team.
    Anything else looks like a missing student."""
    if actor.role is not Role.THERAPIST:
        return deny("role_not_permitted")
    if not same_tenant(actor, student_institution_id):
        return deny("other_tenant", hide=True)
    if not has_active_care_link:
        return deny("no_care_team_link", hide=True)
    return allow("care_team")


def can_manage_own_therapist_record(
    actor: Principal, *, institution_id: uuid.UUID, therapist_id: uuid.UUID
) -> Decision:
    """Availability, follow-ups and sessions belong to the therapist who owns them."""
    if actor.role is not Role.THERAPIST:
        return deny("role_not_permitted")
    if not same_tenant(actor, institution_id) or actor.user_id != therapist_id:
        return deny("not_owner", hide=True)
    return allow("owning_therapist")


def can_write_therapy_note(
    actor: Principal,
    *,
    session_institution_id: uuid.UUID,
    session_therapist_id: uuid.UUID,
    has_active_care_link: bool,
) -> Decision:
    """Only the therapist who delivered the session writes its notes, while the student is
    still on their care team. Nobody else, whatever their role, may add to or amend a note."""
    if actor.role is not Role.THERAPIST:
        return deny("role_not_permitted")
    if not same_tenant(actor, session_institution_id) or actor.user_id != session_therapist_id:
        return deny("not_session_therapist", hide=True)
    if not has_active_care_link:
        return deny("no_care_team_link", hide=True)
    return allow("session_therapist")


def can_handle_risk_alert(
    actor: Principal,
    *,
    alert_institution_id: uuid.UUID,
    assigned_to: uuid.UUID | None,
    has_active_care_link: bool,
) -> Decision:
    """An alert is handled by the therapist it is assigned to, or (while unassigned) by a
    therapist on the student's care team."""
    if actor.role is not Role.THERAPIST:
        return deny("role_not_permitted")
    if not same_tenant(actor, alert_institution_id):
        return deny("other_tenant", hide=True)
    if assigned_to is not None:
        return (
            allow("assigned_therapist")
            if assigned_to == actor.user_id
            else deny("assigned_to_someone_else", hide=True)
        )
    if not has_active_care_link:
        return deny("no_care_team_link", hide=True)
    return allow("care_team_unassigned")


def can_verify_therapist(
    actor: Principal, *, therapist_institution_id: uuid.UUID, therapist_id: uuid.UUID
) -> Decision:
    """Administrators verify the therapists of their own institution, never themselves."""
    if actor.role is not Role.ADMIN:
        return deny("role_not_permitted")
    if not same_tenant(actor, therapist_institution_id):
        return deny("other_tenant", hide=True)
    if actor.user_id == therapist_id:
        return deny("cannot_verify_self")
    return allow("institution_admin")


def can_view_class_analytics(
    actor: Principal, *, course_institution_id: uuid.UUID, teaches_course: bool
) -> Decision:
    """A teacher sees figures for the classes they teach. Not other teachers' classes."""
    if actor.role is not Role.TEACHER:
        return deny("role_not_permitted")
    if not same_tenant(actor, course_institution_id):
        return deny("other_tenant", hide=True)
    return allow("teaches_course") if teaches_course else deny("not_your_class", hide=True)


def can_raise_referral(
    actor: Principal,
    *,
    student_institution_id: uuid.UUID,
    teaches_course: bool,
    student_enrolled: bool,
) -> Decision:
    """A teacher can raise a referral only for a student enrolled in a class they teach."""
    if actor.role is not Role.TEACHER:
        return deny("role_not_permitted")
    if not same_tenant(actor, student_institution_id):
        return deny("other_tenant", hide=True)
    if not teaches_course:
        return deny("not_your_class", hide=True)
    return allow("enrolled_in_your_class") if student_enrolled else deny("not_in_class", hide=True)


def can_manage_own_teacher_record(
    actor: Principal, *, record_institution_id: uuid.UUID, record_teacher_id: uuid.UUID
) -> Decision:
    """A teacher reads and answers only referrals and requests that are their own."""
    if actor.role is not Role.TEACHER:
        return deny("role_not_permitted")
    if not same_tenant(actor, record_institution_id):
        return deny("other_tenant", hide=True)
    return (
        allow("own_record") if record_teacher_id == actor.user_id else deny("not_owner", hide=True)
    )


def can_triage_referral(
    actor: Principal,
    *,
    referral_institution_id: uuid.UUID,
    is_verified: bool,
    on_care_team: bool,
    student_has_care_team: bool,
) -> Decision:
    """A verified therapist triages referrals for their own students, or for students nobody
    is looking after yet. Not referrals about another therapist's students."""
    if actor.role is not Role.THERAPIST:
        return deny("role_not_permitted")
    if not same_tenant(actor, referral_institution_id):
        return deny("other_tenant", hide=True)
    if not is_verified:
        return deny("not_verified")
    if on_care_team:
        return allow("on_care_team")
    if not student_has_care_team:
        return allow("unassigned_queue")
    return deny("another_therapists_student", hide=True)


def can_view_department_analytics(
    actor: Principal,
    *,
    department_institution_id: uuid.UUID,
    department_id: uuid.UUID,
    teacher_department_id: uuid.UUID,
) -> Decision:
    """A teacher sees figures for their own department only. Another department is refused."""
    if actor.role is not Role.TEACHER:
        return deny("role_not_permitted")
    if not same_tenant(actor, department_institution_id):
        return deny("other_tenant", hide=True)
    if department_id != teacher_department_id:
        return deny("other_department")
    return allow("own_department")


def can_administer(actor: Principal, *, institution_id: uuid.UUID) -> Decision:
    """Administrators change structure and settings in their own institution only.

    A record from another institution is indistinguishable from a missing one. Who the record
    is *about* never matters here: this decides who may change it, not what may be read from it.
    """
    if actor.role is not Role.ADMIN:
        return deny("role_not_permitted")
    if not same_tenant(actor, institution_id):
        return deny("other_tenant", hide=True)
    return allow("institution_admin")


def can_edit_resource(actor: Principal, *, resource_institution_id: uuid.UUID | None) -> Decision:
    """Global resources (no institution) can be read by everyone but edited by no administrator."""
    if actor.role is not Role.ADMIN:
        return deny("role_not_permitted")
    if resource_institution_id is None:
        return deny("global_resource_read_only")
    if not same_tenant(actor, resource_institution_id):
        return deny("other_tenant", hide=True)
    return allow("institution_admin")
