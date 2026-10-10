"""Pure rules: role permissions, resource policies, password policy, token codec."""

import datetime as dt
import uuid

import pytest

from app.core.access_tokens import (
    AccessTokenCodec,
    InvalidAccessToken,
    generate_private_key_pem,
    load_private_key,
)
from app.domain.auth.password_policy import password_problems
from app.domain.auth.permissions import (
    CONTENT_PERMISSIONS,
    Permission,
    Role,
    has_permission,
    permissions_for,
)
from app.domain.auth.policies import (
    Principal,
    can_manage_appointment,
    can_manage_user,
    can_read_ai_conversation,
    can_read_student_wellness,
    can_read_therapy_note,
)
from app.infrastructure.db.enums import UserRole

INST = uuid.uuid4()
OTHER_INST = uuid.uuid4()


def principal(role: Role, inst: uuid.UUID = INST) -> Principal:
    return Principal(uuid.uuid4(), inst, role, uuid.uuid4())


# ---- role permissions ------------------------------------------------------------------------


def test_roles_match_database_roles() -> None:
    assert {r.value for r in Role} == {r.value for r in UserRole}


@pytest.mark.parametrize("role", [Role.TEACHER, Role.ADMIN])
def test_teachers_and_admins_hold_no_content_permission(role: Role) -> None:
    assert not permissions_for(role) & CONTENT_PERMISSIONS


def test_only_therapists_read_therapy_notes() -> None:
    assert [r for r in Role if has_permission(r, Permission.THERAPY_NOTE_READ)] == [Role.THERAPIST]


def test_only_students_read_ai_conversations() -> None:
    holders = [r for r in Role if has_permission(r, Permission.AI_CONVERSATION_READ_OWN)]
    assert holders == [Role.STUDENT]


def test_only_admins_manage_users_config_and_audit() -> None:
    for perm in (Permission.USER_MANAGE, Permission.CONFIG_MANAGE, Permission.AUDIT_READ):
        assert [r for r in Role if has_permission(r, perm)] == [Role.ADMIN]


def test_every_permission_is_granted_to_someone() -> None:
    granted = set().union(*(permissions_for(r) for r in Role))
    assert granted == set(Permission)


# ---- resource policies -----------------------------------------------------------------------


def test_wellness_policy() -> None:
    student = principal(Role.STUDENT)
    therapist = principal(Role.THERAPIST)

    def check(
        actor: Principal,
        sid: uuid.UUID,
        inst: uuid.UUID = INST,
        link: bool = True,
        consent: bool = True,
    ) -> tuple[bool, bool]:
        d = can_read_student_wellness(
            actor,
            student_id=sid,
            student_institution_id=inst,
            has_active_care_link=link,
            has_sharing_consent=consent,
        )
        return d.allowed, d.hide

    assert check(student, student.user_id) == (True, False)
    assert check(student, uuid.uuid4()) == (False, True)
    assert check(therapist, uuid.uuid4()) == (True, False)
    assert check(therapist, uuid.uuid4(), consent=False) == (False, False)
    assert check(therapist, uuid.uuid4(), link=False) == (False, True)
    assert check(therapist, uuid.uuid4(), inst=OTHER_INST) == (False, True)
    for role in (Role.TEACHER, Role.ADMIN):
        assert check(principal(role), uuid.uuid4())[0] is False


def test_therapy_note_policy() -> None:
    author = principal(Role.THERAPIST)

    def ok(
        actor: Principal,
        *,
        inst: uuid.UUID = INST,
        link: bool = True,
        author_id: uuid.UUID = author.user_id,
    ) -> bool:
        return can_read_therapy_note(
            actor, note_institution_id=inst, note_author_id=author_id, has_active_care_link=link
        ).allowed

    assert ok(author)
    assert not ok(author, link=False)
    assert not ok(author, inst=OTHER_INST)
    assert not ok(principal(Role.THERAPIST))  # another therapist, even on the care team
    for role in (Role.STUDENT, Role.TEACHER, Role.ADMIN):
        assert not ok(principal(role), author_id=author.user_id)


def test_ai_conversations_are_private_to_the_student() -> None:
    owner = principal(Role.STUDENT)
    assert can_read_ai_conversation(
        owner, owner_student_id=owner.user_id, institution_id=INST
    ).allowed
    for actor in (
        principal(Role.STUDENT),
        principal(Role.THERAPIST),
        principal(Role.TEACHER),
        principal(Role.ADMIN),
    ):
        assert not can_read_ai_conversation(
            actor, owner_student_id=owner.user_id, institution_id=INST
        ).allowed


def test_appointment_and_user_management_policies() -> None:
    t = principal(Role.THERAPIST)
    assert can_manage_appointment(
        t, appointment_institution_id=INST, therapist_id=t.user_id
    ).allowed
    assert not can_manage_appointment(
        t, appointment_institution_id=INST, therapist_id=uuid.uuid4()
    ).allowed
    assert not can_manage_appointment(
        principal(Role.ADMIN), appointment_institution_id=INST, therapist_id=t.user_id
    ).allowed

    admin = principal(Role.ADMIN)
    assert can_manage_user(admin, target_user_id=uuid.uuid4(), target_institution_id=INST).allowed
    assert not can_manage_user(
        admin, target_user_id=admin.user_id, target_institution_id=INST
    ).allowed
    other = can_manage_user(admin, target_user_id=uuid.uuid4(), target_institution_id=OTHER_INST)
    assert not other.allowed and other.hide
    assert not can_manage_user(
        principal(Role.TEACHER), target_user_id=uuid.uuid4(), target_institution_id=INST
    ).allowed


# ---- password policy -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("password", "ok"),
    [
        ("correct horse battery", True),
        ("short", False),
        ("password1234", False),
        ("aaaaaaaaaaaaaaaa", False),
        ("x" * 129, False),
        ("asha.verma-likes-tea", False),  # contains the e-mail local part
    ],
)
def test_password_policy(password: str, ok: bool) -> None:
    assert (password_problems(password, email="asha.verma@test.example") == []) is ok


# ---- access-token codec ----------------------------------------------------------------------


def _codec(audience: str = "mindmitra") -> AccessTokenCodec:
    return AccessTokenCodec(
        load_private_key(generate_private_key_pem()),
        issuer="mindmitra-api",
        audience=audience,
        ttl=dt.timedelta(minutes=10),
    )


def test_codec_round_trip_and_rejections() -> None:
    codec = _codec()
    now = dt.datetime.now(dt.UTC)
    ids = {"user_id": uuid.uuid4(), "institution_id": uuid.uuid4(), "session_id": uuid.uuid4()}
    token, expires = codec.issue(**ids, role="therapist", now=now)
    claims = codec.decode(token)
    assert (claims.user_id, claims.institution_id, claims.session_id, claims.role) == (
        ids["user_id"],
        ids["institution_id"],
        ids["session_id"],
        "therapist",
    )
    assert expires - now == dt.timedelta(minutes=10)

    with pytest.raises(InvalidAccessToken):
        _codec().decode(token)  # different key
    with pytest.raises(InvalidAccessToken):
        codec.decode(codec.issue(**ids, role="therapist", now=now - dt.timedelta(hours=1))[0])


def test_private_key_must_be_ed25519() -> None:
    with pytest.raises(ValueError):
        load_private_key("change-me")


# ---- administrator policies ------------------------------------------------------------------


def test_only_an_administrator_of_the_same_institution_may_administer() -> None:
    from app.domain.auth.policies import can_administer, can_edit_resource

    admin = principal(Role.ADMIN)
    assert can_administer(admin, institution_id=INST).allowed
    other = can_administer(admin, institution_id=OTHER_INST)
    assert not other.allowed and other.hide  # another institution's records look absent
    for role in (Role.STUDENT, Role.THERAPIST, Role.TEACHER):
        assert not can_administer(principal(role), institution_id=INST).allowed

    assert can_edit_resource(admin, resource_institution_id=INST).allowed
    shipped = can_edit_resource(admin, resource_institution_id=None)
    assert not shipped.allowed and shipped.reason == "global_resource_read_only"
    assert not can_edit_resource(admin, resource_institution_id=OTHER_INST).allowed
    assert not can_edit_resource(principal(Role.TEACHER), resource_institution_id=INST).allowed
