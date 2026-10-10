"""Roles, permissions and the role -> permission table (RBAC layer).

Permissions answer "may this *kind* of user call this kind of operation at all?". Whether a
particular record is visible (own data, care-team relationship, consent, tenant) is decided by
the resource policies in ``policies.py``. Both checks run on every protected request.
"""

import enum
from collections.abc import Mapping


class Role(enum.StrEnum):
    """Values match ``iam.users.role``. ``ADMIN`` is stored as ``administrator``."""

    STUDENT = "student"
    THERAPIST = "therapist"
    TEACHER = "teacher"
    ADMIN = "administrator"


class Permission(enum.StrEnum):
    # every authenticated user
    PROFILE_READ_OWN = "profile:read:own"
    # student: their own records only
    WELLNESS_READ_OWN = "wellness:read:own"
    APPOINTMENT_READ_OWN = "appointment:read:own"
    AI_CONVERSATION_READ_OWN = "ai_conversation:read:own"
    WELLNESS_WRITE_OWN = "wellness:write:own"
    GOAL_MANAGE_OWN = "goal:manage:own"
    RECOMMENDATION_MANAGE_OWN = "recommendation:manage:own"
    APPOINTMENT_BOOK_OWN = "appointment:book:own"
    MESSAGE_PARTICIPATE_OWN = "message:participate:own"
    CONSENT_MANAGE_OWN = "consent:manage:own"
    PRIVACY_READ_OWN = "privacy:read:own"
    SUPPORT_REQUEST_CREATE = "support_request:create"
    # students and therapists: vetted content and the (public-profile) therapist directory
    RESOURCE_READ = "resource:read"
    THERAPIST_DIRECTORY_READ = "therapist_directory:read"
    # therapist: students on their care team (plus consent / authorship, see policies)
    STUDENT_READ_ASSIGNED = "student:read:assigned"
    WELLNESS_READ_ASSIGNED = "wellness:read:assigned"
    THERAPY_NOTE_READ = "therapy_note:read"
    APPOINTMENT_MANAGE = "appointment:manage"
    THERAPIST_PROFILE_MANAGE = "therapist_profile:manage"  # own profile, availability, status
    SESSION_MANAGE = "session:manage"
    THERAPY_NOTE_WRITE = "therapy_note:write"
    RISK_ALERT_MANAGE = "risk_alert:manage:assigned"
    FOLLOW_UP_MANAGE = "follow_up:manage"
    RECOMMENDATION_CREATE_ASSIGNED = "recommendation:create:assigned"
    # teacher / admin: aggregated, de-identified data only
    INSIGHTS_READ_AGGREGATE = "insights:read:aggregate"
    # admin: accounts, configuration and audit metadata, never clinical content
    USER_MANAGE = "user:manage"
    THERAPIST_VERIFY = "therapist:verify"
    CONFIG_MANAGE = "config:manage"
    AUDIT_READ = "audit:read"


P = Permission

ROLE_PERMISSIONS: Mapping[Role, frozenset[Permission]] = {
    Role.STUDENT: frozenset(
        {
            P.PROFILE_READ_OWN,
            P.WELLNESS_READ_OWN,
            P.APPOINTMENT_READ_OWN,
            P.AI_CONVERSATION_READ_OWN,
            P.WELLNESS_WRITE_OWN,
            P.GOAL_MANAGE_OWN,
            P.RECOMMENDATION_MANAGE_OWN,
            P.APPOINTMENT_BOOK_OWN,
            P.MESSAGE_PARTICIPATE_OWN,
            P.CONSENT_MANAGE_OWN,
            P.PRIVACY_READ_OWN,
            P.SUPPORT_REQUEST_CREATE,
            P.RESOURCE_READ,
            P.THERAPIST_DIRECTORY_READ,
        }
    ),
    Role.THERAPIST: frozenset(
        {
            P.PROFILE_READ_OWN,
            P.STUDENT_READ_ASSIGNED,
            P.WELLNESS_READ_ASSIGNED,
            P.THERAPY_NOTE_READ,
            P.APPOINTMENT_MANAGE,
            P.THERAPIST_PROFILE_MANAGE,
            P.SESSION_MANAGE,
            P.THERAPY_NOTE_WRITE,
            P.RISK_ALERT_MANAGE,
            P.FOLLOW_UP_MANAGE,
            P.RECOMMENDATION_CREATE_ASSIGNED,
            P.MESSAGE_PARTICIPATE_OWN,
            P.RESOURCE_READ,
        }
    ),
    Role.TEACHER: frozenset({P.PROFILE_READ_OWN, P.INSIGHTS_READ_AGGREGATE}),
    Role.ADMIN: frozenset(
        {
            P.PROFILE_READ_OWN,
            P.INSIGHTS_READ_AGGREGATE,
            P.USER_MANAGE,
            P.THERAPIST_VERIFY,
            P.CONFIG_MANAGE,
            P.AUDIT_READ,
        }
    ),
}

# Permissions that expose individual clinical, wellness or AI-companion content. Teachers and
# admins must never hold any of them (CLAUDE.md rules 3-4; SECURITY_ARCHITECTURE.md INV-1/2/8).
CONTENT_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        P.WELLNESS_READ_OWN,
        P.WELLNESS_READ_ASSIGNED,
        P.THERAPY_NOTE_READ,
        P.THERAPY_NOTE_WRITE,
        P.SESSION_MANAGE,
        P.RISK_ALERT_MANAGE,
        P.FOLLOW_UP_MANAGE,
        P.RECOMMENDATION_CREATE_ASSIGNED,
        P.AI_CONVERSATION_READ_OWN,
        P.STUDENT_READ_ASSIGNED,
        P.WELLNESS_WRITE_OWN,
        P.GOAL_MANAGE_OWN,
        P.RECOMMENDATION_MANAGE_OWN,
        P.MESSAGE_PARTICIPATE_OWN,
        P.PRIVACY_READ_OWN,
        P.SUPPORT_REQUEST_CREATE,
    }
)


def permissions_for(role: Role) -> frozenset[Permission]:
    return ROLE_PERMISSIONS.get(role, frozenset())


def has_permission(role: Role, permission: Permission) -> bool:
    return permission in permissions_for(role)
