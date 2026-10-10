"""Therapy notes are Clinical-Confidential: every route that could leak or alter one is tried
by every kind of caller who must not succeed, and the note text must appear nowhere else.

Who may read or write a note: the therapist who delivered the session, verified, while the
student is still on their care team. Everyone else gets 401/403/404 and never the text.
"""

import dataclasses
import datetime as dt
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db import models as m
from app.infrastructure.db.enums import CareRole, VerificationStatus
from tests.api_helpers import call, token_for
from tests.api_world import World
from tests.student_helpers import new_student
from tests.therapist_helpers import (
    Pair,
    care_pair,
    end_care_link,
    fresh_admin,
    fresh_therapist,
    started_session,
)

pytestmark = pytest.mark.asyncio

SECRET = "CONFIDENTIAL-NOTE-TEXT-5f3a9c"
DENIED = {401, 403, 404}


@dataclasses.dataclass
class Scene:
    pair: Pair
    session_id: uuid.UUID
    note_path: str
    secret: str = SECRET


@pytest_asyncio.fixture
async def scene(client: httpx.AsyncClient, api_db: AsyncSession, world: World) -> Scene:
    pair = await care_pair(client, api_db, world, assessments=True)
    await pair.student.post("/me/check-ins", {"mood_score": 3})
    sid = await started_session(api_db, pair)
    path = f"/therapist/sessions/{sid}/note"
    saved = await pair.therapist.put(path, {"body": f"Opening. {SECRET}. Closing."})
    assert saved.status_code == 200, saved.text
    await pair.therapist.put(path, {"body": f"Revised. {SECRET}-v2."})
    return Scene(pair, sid, path)


def _note_routes(scene: Scene) -> list[tuple[str, str, dict[str, str] | None]]:
    sid, student = scene.session_id, scene.pair.student.id
    body = {"body": "attacker wrote this"}
    return [
        ("GET", scene.note_path, None),
        ("GET", scene.note_path + "?version=1", None),
        ("GET", scene.note_path + "?version=2", None),
        ("PUT", scene.note_path, body),
        ("GET", f"/students/{student}/therapy-notes", None),
        ("PATCH", f"/therapist/sessions/{sid}", {"status": "completed"}),
        ("DELETE", scene.note_path, None),
        ("PATCH", scene.note_path, body),
        ("POST", scene.note_path, body),
    ]


async def _attempt_all(client: httpx.AsyncClient, token: str | None, scene: Scene) -> None:
    for method, path, body in _note_routes(scene):
        r = await call(client, method, path, token=token, json=body)
        if r.status_code == 200:
            # the one list route that is scoped to the caller's *own* notes: empty for others
            assert path.endswith("/therapy-notes") and r.json() == [], (method, path, r.text)
        else:
            assert r.status_code in DENIED | {405}, (method, path, r.status_code, r.text)
        assert scene.secret not in r.text, (method, path)
        assert "attacker wrote this" not in r.text


async def _assert_untouched(api_db: AsyncSession, scene: Scene) -> None:
    rows = list(
        await api_db.scalars(
            select(m.TherapyNote)
            .where(m.TherapyNote.session_id == scene.session_id)
            .order_by(m.TherapyNote.version)
        )
    )
    await api_db.rollback()
    for r in rows:
        await api_db.refresh(r)
    assert [r.version for r in rows] == [1, 2]
    assert all("attacker" not in r.body for r in rows)
    assert rows[0].body.startswith("Opening.")  # superseded versions are never edited
    session = await api_db.get(m.TherapySession, scene.session_id)
    await api_db.refresh(session)
    assert session is not None and session.status.value == "in_progress"


# ---- the people who must never read or change a note ---------------------------------------


async def test_the_student_the_note_is_about_cannot_reach_it(
    client: httpx.AsyncClient, api_db: AsyncSession, scene: Scene
) -> None:
    await _attempt_all(client, scene.pair.student.token, scene)
    await _assert_untouched(api_db, scene)


async def test_another_student_cannot_reach_it(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, scene: Scene
) -> None:
    other = await new_student(client, api_db, world)
    await _attempt_all(client, other.token, scene)
    await _assert_untouched(api_db, scene)


async def test_teachers_cannot_reach_it(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, scene: Scene
) -> None:
    for teacher in (world.teacher, world.b_teacher):
        await _attempt_all(client, await token_for(client, teacher, world.password), scene)
    await _assert_untouched(api_db, scene)


async def test_administrators_cannot_reach_it_in_any_institution(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, scene: Scene
) -> None:
    admin = await fresh_admin(client, api_db, world)
    b_admin = await fresh_admin(client, api_db, world, other_tenant=True)
    for token in (admin.token, b_admin.token, await token_for(client, world.admin, world.password)):
        await _attempt_all(client, token, scene)
    await _assert_untouched(api_db, scene)


async def test_an_unrelated_therapist_in_the_same_institution_cannot_reach_it(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, scene: Scene
) -> None:
    stranger = await fresh_therapist(client, api_db, world)
    await _attempt_all(client, stranger.token, scene)
    # the seeded cast's therapists too
    for who in (world.therapist, world.other_therapist):
        await _attempt_all(client, await token_for(client, who, world.password), scene)
    await _assert_untouched(api_db, scene)


async def test_a_colleague_on_the_same_care_team_cannot_read_the_authors_note(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, scene: Scene
) -> None:
    """Being on the student's care team is not enough: notes belong to their author."""
    colleague = await fresh_therapist(client, api_db, world)
    api_db.add(
        m.CareTeamMember(
            institution_id=world.inst_a,
            student_id=scene.pair.student.id,
            therapist_id=colleague.id,
            role=CareRole.SECONDARY,
            starts_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=1),
        )
    )
    await api_db.commit()
    assert [s["student_id"] for s in (await colleague.get("/therapist/students")).json()] == [
        str(scene.pair.student.id)
    ]  # they do have the student on their caseload ...
    await _attempt_all(client, colleague.token, scene)  # ... but not the author's notes
    listing = await colleague.get(f"/students/{scene.pair.student.id}/therapy-notes")
    assert listing.status_code == 200 and listing.json() == []  # scoped to their own notes
    profile = await colleague.get(f"/therapist/students/{scene.pair.student.id}")
    assert scene.secret not in profile.text
    assert all(s["has_note"] is False for s in profile.json()["recent_sessions"])
    await _assert_untouched(api_db, scene)


async def test_a_therapist_in_another_institution_cannot_reach_it(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, scene: Scene
) -> None:
    outsider = await fresh_therapist(client, api_db, world, other_tenant=True)
    await _attempt_all(client, outsider.token, scene)
    await _attempt_all(client, await token_for(client, world.b_therapist, world.password), scene)
    await _assert_untouched(api_db, scene)


async def test_anonymous_and_tampered_tokens_cannot_reach_it(
    client: httpx.AsyncClient, scene: Scene
) -> None:
    await _attempt_all(client, None, scene)
    forged = scene.pair.therapist.token[:-4] + "AAAA"
    await _attempt_all(client, forged, scene)
    for method, path, body in _note_routes(scene):
        if method in ("GET", "PUT"):
            r = await call(client, method, path, json=body)
            assert r.status_code == 401


# ---- the author loses access when their standing changes -----------------------------------


async def test_the_author_loses_the_notes_when_the_care_link_ends(
    client: httpx.AsyncClient, api_db: AsyncSession, scene: Scene
) -> None:
    assert (await scene.pair.therapist.get(scene.note_path)).status_code == 200
    await end_care_link(api_db, scene.pair)
    for method, path, body in _note_routes(scene)[:5]:
        r = await call(client, method, path, token=scene.pair.therapist.token, json=body)
        if method == "GET" and path.startswith("/students/"):
            assert r.status_code in DENIED, (path, r.status_code)
        else:
            assert r.status_code in DENIED, (method, path, r.status_code)
        assert scene.secret not in r.text
    await _assert_untouched(api_db, scene)


async def test_the_author_loses_the_notes_when_verification_is_withdrawn(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, scene: Scene
) -> None:
    row = await api_db.get(m.Therapist, scene.pair.therapist.id)
    assert row is not None
    row.verification_status = VerificationStatus.REJECTED
    row.verified_at = None
    await api_db.commit()
    for method, path, body in _note_routes(scene)[:5]:
        r = await call(client, method, path, token=scene.pair.therapist.token, json=body)
        assert r.status_code == 403, (method, path, r.status_code)
        assert scene.secret not in r.text
    await _assert_untouched(api_db, scene)


async def test_the_author_loses_the_notes_when_the_account_is_deactivated(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, scene: Scene
) -> None:
    admin = await fresh_admin(client, api_db, world)
    r = await admin.patch(f"/admin/users/{scene.pair.therapist.id}", {"status": "suspended"})
    assert r.status_code == 200, r.text
    got = await scene.pair.therapist.get(scene.note_path)
    assert got.status_code == 401 and scene.secret not in got.text


# ---- the text appears nowhere it should not ------------------------------------------------


def _leak_paths(scene: Scene) -> dict[str, list[str]]:
    student = scene.pair.student.id
    return {
        "student": [
            "/me",
            "/me/dashboard",
            "/me/privacy/export",
            "/me/privacy/access-history",
            "/me/appointments",
            "/me/recommendations?include_closed=true",
            "/me/conversations",
            "/me/consents",
            "/me/wellness/summary",
        ],
        "teacher": ["/insights/mood-summary", "/me"],
        "admin": [
            "/admin/users",
            "/admin/audit?limit=200",
            "/admin/therapists",
            "/admin/config",
            "/admin/audit?action=therapy_note.write&limit=200",
        ],
        "therapist": [
            f"/therapist/students/{student}",
            "/therapist/students",
            "/therapist/sessions",
            "/therapist/dashboard",
            "/therapist/appointments",
            "/therapist/follow-ups",
            "/therapist/alerts",
            f"/therapist/students/{student}/trends",
            f"/therapist/students/{student}/assessments",
            f"/therapist/students/{student}/recommendations",
            f"/students/{student}/mood-entries",
            "/me/conversations",
            f"/me/conversations/{student}/messages",
        ],
    }


async def test_note_text_is_not_in_any_other_response(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, scene: Scene
) -> None:
    admin = await fresh_admin(client, api_db, world)
    teacher_token = await token_for(client, world.teacher, world.password)
    tokens = {
        "student": scene.pair.student.token,
        "teacher": teacher_token,
        "admin": admin.token,
        "therapist": scene.pair.therapist.token,
    }
    checked = 0
    for role, paths in _leak_paths(scene).items():
        for path in paths:
            r = await call(client, "GET", path, token=tokens[role])
            assert scene.secret not in r.text, (role, path)
            checked += 1
    assert checked >= 25


async def test_note_text_is_encrypted_at_rest_and_absent_from_the_audit_log(
    client: httpx.AsyncClient, api_db: AsyncSession, scene: Scene
) -> None:
    raw = (
        (
            await api_db.execute(
                text("SELECT body FROM therapy.therapy_notes WHERE session_id = :s"),
                {"s": scene.session_id},
            )
        )
        .scalars()
        .all()
    )
    assert len(raw) == 2 and all(isinstance(b, bytes) for b in raw)
    assert not any(scene.secret.encode() in b for b in raw)

    events = list(await api_db.scalars(select(m.AuditLog)))
    assert not any(scene.secret in str((e.details, e.reason, e.action)) for e in events)
    # and the writes and reads that did happen were recorded, as metadata
    mine = [e for e in events if e.resource_id == scene.session_id]
    assert {"therapy_note.write"} <= {e.action for e in mine}
    assert all(set(e.details) <= {"version"} for e in mine if e.action.startswith("therapy_note"))


async def test_refused_attempts_are_audited_with_a_generic_reason_and_no_content(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, scene: Scene
) -> None:
    stranger = await fresh_therapist(client, api_db, world)
    await stranger.get(scene.note_path)
    await stranger.put(scene.note_path, {"body": "attacker wrote this"})
    r = await scene.pair.student.get(scene.note_path)
    assert r.status_code == 403 and "do not have access" in r.text.lower()

    denied = list(
        await api_db.scalars(
            select(m.AuditLog).where(
                m.AuditLog.actor_id.in_([stranger.id, scene.pair.student.id]),
                m.AuditLog.outcome != "allowed",
            )
        )
    )
    assert {e.action for e in denied} >= {"therapy_note.read", "therapy_note.write"}
    assert not any(scene.secret in str(e.details) for e in denied)
    assert not any("attacker" in str(e.details) for e in denied)


async def test_hidden_and_forbidden_answers_do_not_reveal_whether_a_note_exists(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, scene: Scene
) -> None:
    """A stranger gets the same answer for a real session id and one that does not exist."""
    stranger = await fresh_therapist(client, api_db, world)
    real = await stranger.get(scene.note_path)
    missing = await stranger.get(f"/therapist/sessions/{uuid.uuid4()}/note")
    assert real.status_code == missing.status_code == 404
    assert real.json()["detail"] == missing.json()["detail"]
    assert scene.secret not in real.text
