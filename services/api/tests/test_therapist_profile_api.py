"""Therapist profile, professional verification and availability management."""

import datetime as dt

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db import models as m
from tests.api_world import World
from tests.student_helpers import new_student, new_therapist
from tests.therapist_helpers import care_pair, fresh_admin, fresh_therapist

pytestmark = pytest.mark.asyncio


def _later(days: int, hour: int = 10) -> dt.datetime:
    base = dt.datetime.now(dt.UTC) + dt.timedelta(days=days)
    return base.replace(hour=hour, minute=0, second=0, microsecond=0)


# ---- profile -------------------------------------------------------------------------------


async def test_profile_is_readable_and_editable_by_its_owner(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    t = await fresh_therapist(client, api_db, world)
    profile = (await t.get("/therapist/profile")).json()
    assert profile["id"] == str(t.id) and profile["verification_status"] == "verified"
    assert profile["can_see_students"] is True

    r = await t.patch(
        "/therapist/profile",
        {
            "bio": "I work with exam stress.",
            "specialties": ["exam stress", "sleep"],
            "languages": ["English", "Hindi"],
            "accepting_new_students": False,
            "max_caseload": 12,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["bio"] == "I work with exam stress." and body["max_caseload"] == 12
    assert body["accepting_new_students"] is False
    assert body["specialties"] == ["exam stress", "sleep"]


@pytest.mark.parametrize(
    "patch",
    [
        {"max_caseload": 0},
        {"max_caseload": 501},
        {"bio": "x" * 2001},
        {"specialties": ["a"] * 9},
        {"specialties": [""]},
    ],
)
async def test_profile_rejects_out_of_range_values(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, patch: dict[str, object]
) -> None:
    t = await fresh_therapist(client, api_db, world)
    assert (await t.patch("/therapist/profile", patch)).status_code == 422


async def test_profile_cannot_set_verification_or_licence_through_the_edit_route(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    t = await fresh_therapist(client, api_db, world, verified=False)
    r = await t.patch(
        "/therapist/profile",
        {"verification_status": "verified", "licence_number": "FORGED-1", "bio": "hi"},
    )
    assert r.status_code == 200  # unknown fields are ignored, never applied
    row = await api_db.get(m.Therapist, t.id)
    await api_db.refresh(row)
    assert row is not None and row.verification_status.value == "pending"
    assert row.licence_number != "FORGED-1"


# ---- verification --------------------------------------------------------------------------


async def test_unverified_therapist_sees_status_but_no_students(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    t = await fresh_therapist(client, api_db, world, verified=False)
    profile = (await t.get("/therapist/profile")).json()
    assert profile["verification_status"] == "pending"
    assert profile["verification_label"] == "Waiting for verification"
    assert profile["can_see_students"] is False
    dash = (await t.get("/therapist/dashboard")).json()
    assert dash["can_see_students"] is False and dash["caseload"] == 0

    for path in (
        "/therapist/students",
        "/therapist/appointments",
        "/therapist/sessions",
        "/therapist/alerts",
        "/therapist/follow-ups",
        "/me/conversations",
        "/students",
    ):
        r = await t.get(path)
        assert r.status_code == 403, path


async def test_submitting_licence_details_resets_to_pending_and_never_self_verifies(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    t = await fresh_therapist(client, api_db, world)  # verified
    r = await t.post(
        "/therapist/verification",
        {
            "licence_number": "SYN-REG-9001",
            "licence_body": "Synthetic Council",
            "licence_expires_on": str(dt.date.today() + dt.timedelta(days=400)),
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["verification_status"] == "pending" and body["can_see_students"] is False
    assert body["licence_number"] == "SYN-REG-9001"
    assert (await t.get("/therapist/students")).status_code == 403


async def test_an_expired_licence_cannot_be_submitted(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    t = await fresh_therapist(client, api_db, world, verified=False)
    r = await t.post(
        "/therapist/verification",
        {
            "licence_number": "SYN-REG-9002",
            "licence_expires_on": str(dt.date.today() - dt.timedelta(days=1)),
        },
    )
    assert r.status_code == 422


async def test_duplicate_licence_number_in_one_institution_is_a_conflict(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    a = await fresh_therapist(client, api_db, world)
    b = await fresh_therapist(client, api_db, world)
    assert (
        await a.post("/therapist/verification", {"licence_number": "SYN-DUP-1"})
    ).status_code == 200
    r = await b.post("/therapist/verification", {"licence_number": "SYN-DUP-1"})
    assert r.status_code == 409


async def test_admin_verifies_and_the_therapist_gains_access(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    t = await fresh_therapist(client, api_db, world, verified=False)
    admin = await fresh_admin(client, api_db, world)
    queue = (await admin.get("/admin/therapists?status=pending")).json()
    assert str(t.id) in {x["id"] for x in queue}

    r = await admin.patch(
        f"/admin/therapists/{t.id}/verification", {"status": "verified", "note": "Checked."}
    )
    assert r.status_code == 200, r.text
    assert r.json()["verification_status"] == "verified" and r.json()["verified_at"]
    assert (await t.get("/therapist/students")).status_code == 200

    # and can be withdrawn again, which takes effect on the very next request
    r = await admin.patch(
        f"/admin/therapists/{t.id}/verification", {"status": "rejected", "note": "Lapsed."}
    )
    assert r.json()["verification_status"] == "rejected"
    assert (await t.get("/therapist/students")).status_code == 403
    assert (await t.get("/therapist/profile")).json()["verification_label"] == "Not verified"

    event = await api_db.scalar(
        select(m.AuditLog)
        .where(m.AuditLog.action == "therapist.verify", m.AuditLog.resource_id == t.id)
        .order_by(m.AuditLog.seq.desc())
        .limit(1)
    )
    assert event is not None and event.details == {"status": "rejected"}


async def test_only_an_institution_admin_can_verify_and_never_themselves_or_across_tenants(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    t = await fresh_therapist(client, api_db, world, verified=False)
    body = {"status": "verified"}
    path = f"/admin/therapists/{t.id}/verification"

    s = await new_student(client, api_db, world)
    other_t = await fresh_therapist(client, api_db, world)
    assert (await s.patch(path, body)).status_code == 403
    assert (await other_t.patch(path, body)).status_code == 403
    assert (await t.patch(path, body)).status_code == 403  # nobody verifies themselves
    assert (await s.get("/admin/therapists")).status_code == 403
    assert (await t.get("/admin/therapists")).status_code == 403

    b_admin = await fresh_admin(client, api_db, world, other_tenant=True)
    assert (await b_admin.patch(path, body)).status_code == 404
    assert str(t.id) not in {x["id"] for x in (await b_admin.get("/admin/therapists")).json()}

    row = await api_db.get(m.Therapist, t.id)
    await api_db.refresh(row)
    assert row is not None and row.verification_status.value == "pending"


async def test_a_lapsed_licence_closes_access_without_any_job_running(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    t = await fresh_therapist(client, api_db, world)
    assert (await t.get("/therapist/students")).status_code == 200
    row = await api_db.get(m.Therapist, t.id)
    assert row is not None
    row.licence_expires_on = dt.date.today() - dt.timedelta(days=1)
    await api_db.commit()
    assert (await t.get("/therapist/students")).status_code == 403
    assert (await t.get("/therapist/profile")).json()["verification_status"] == "expired"


async def test_a_therapist_cannot_reach_a_students_data_before_verification(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    """Even with a care-team link and consent, an unverified therapist gets nothing."""
    pair = await care_pair(client, api_db, world)
    await pair.student.post("/me/check-ins", {"mood_score": 2, "note": "private"})
    row = await api_db.get(m.Therapist, pair.therapist.id)
    assert row is not None
    row.verification_status = row.verification_status.PENDING
    row.verified_at = None
    await api_db.commit()
    for path in (
        f"/therapist/students/{pair.student.id}",
        f"/therapist/students/{pair.student.id}/trends",
        f"/students/{pair.student.id}/mood-entries",
        f"/students/{pair.student.id}/therapy-notes",
        f"/me/conversations/{pair.student.id}/messages",
    ):
        assert (await pair.therapist.get(path)).status_code == 403, path


# ---- students only see verified therapists --------------------------------------------------


async def test_unverified_therapists_are_hidden_from_students_and_cannot_be_booked(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    t, slots = await new_therapist(client, api_db, world, verified=False)
    # The directory returns at most 50 names by default; ask for more so a long list can't hide t.
    listed = {x["id"] for x in (await s.get("/therapists?limit=100")).json()}
    assert str(t.id) not in listed
    assert (await s.get(f"/therapists/{t.id}")).status_code == 404
    assert (await s.get(f"/therapists/{t.id}/slots")).status_code == 404
    assert (await s.post("/me/appointments", {"availability_id": str(slots[0])})).status_code == 404

    admin = await fresh_admin(client, api_db, world)
    await admin.patch(f"/admin/therapists/{t.id}/verification", {"status": "verified"})
    listed = (await s.get("/therapists?limit=100")).json()
    assert str(t.id) in {x["id"] for x in listed}
    assert (await s.post("/me/appointments", {"availability_id": str(slots[0])})).status_code == 201


# ---- availability --------------------------------------------------------------------------


async def test_availability_can_be_added_listed_and_removed(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    t = await fresh_therapist(client, api_db, world)
    start = _later(5)
    r = await t.post(
        "/therapist/availability",
        {"starts_at": start.isoformat(), "ends_at": (start + dt.timedelta(minutes=50)).isoformat()},
    )
    assert r.status_code == 201, r.text
    slot = r.json()[0]
    assert slot["mode"] == "video" and slot["booked"] is False

    listed = (await t.get("/therapist/availability")).json()
    assert [x["id"] for x in listed] == [slot["id"]]
    assert (await t.delete(f"/therapist/availability/{slot['id']}")).status_code == 204
    assert (await t.get("/therapist/availability")).json() == []


async def test_weekly_repeat_is_all_or_nothing(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    t = await fresh_therapist(client, api_db, world)
    start = _later(10)
    body = {
        "starts_at": start.isoformat(),
        "ends_at": (start + dt.timedelta(hours=1)).isoformat(),
        "repeat_weeks": 3,
        "mode": "in_person",
    }
    r = await t.post("/therapist/availability", body)
    assert r.status_code == 201 and len(r.json()) == 4
    # the first copy is free, the second lands inside an existing slot: nothing is saved
    first = start - dt.timedelta(days=7) + dt.timedelta(minutes=30)
    r = await t.post(
        "/therapist/availability",
        {
            "starts_at": first.isoformat(),
            "ends_at": (first + dt.timedelta(hours=1)).isoformat(),
            "repeat_weeks": 2,
        },
    )
    assert r.status_code == 409
    window = f"?from={_iso(-1)}&to={_iso(90)}"
    assert len((await t.get("/therapist/availability" + window)).json()) == 4


def _iso(days: int) -> str:
    return (dt.datetime.now(dt.UTC) + dt.timedelta(days=days)).isoformat().replace("+00:00", "Z")


@pytest.mark.parametrize(
    ("delta_start", "minutes", "repeat"),
    [(-1, 50, 0), (3, 10, 0), (3, 300, 0), (3, 50, 12), (400, 50, 0)],
)
async def test_availability_validation(
    client: httpx.AsyncClient,
    api_db: AsyncSession,
    world: World,
    delta_start: int,
    minutes: int,
    repeat: int,
) -> None:
    t = await fresh_therapist(client, api_db, world)
    start = _later(delta_start)
    r = await t.post(
        "/therapist/availability",
        {
            "starts_at": start.isoformat(),
            "ends_at": (start + dt.timedelta(minutes=minutes)).isoformat(),
            "repeat_weeks": repeat,
        },
    )
    assert r.status_code == 422, r.text


async def test_overlapping_slot_is_a_conflict_and_naive_times_are_refused(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    t = await fresh_therapist(client, api_db, world)
    start = _later(7)
    ok = {"starts_at": start.isoformat(), "ends_at": (start + dt.timedelta(hours=1)).isoformat()}
    assert (await t.post("/therapist/availability", ok)).status_code == 201
    overlap = {
        "starts_at": (start + dt.timedelta(minutes=30)).isoformat(),
        "ends_at": (start + dt.timedelta(minutes=90)).isoformat(),
    }
    assert (await t.post("/therapist/availability", overlap)).status_code == 409
    naive = {"starts_at": "2030-01-01T10:00:00", "ends_at": "2030-01-01T11:00:00"}
    assert (await t.post("/therapist/availability", naive)).status_code == 422


async def test_a_requested_slot_cannot_be_removed_and_another_therapists_slot_is_not_theirs(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    t, slots = await new_therapist(client, api_db, world)
    other = await fresh_therapist(client, api_db, world)
    await s.post("/me/appointments", {"availability_id": str(slots[0])})
    r = await t.delete(f"/therapist/availability/{slots[0]}")
    assert r.status_code == 409
    listed = {x["id"]: x for x in (await t.get("/therapist/availability")).json()}
    assert listed[str(slots[0])]["booked"] is True
    assert listed[str(slots[0])]["appointment_status"] == "requested"
    # someone else's slot looks like it does not exist
    r = await other.delete(f"/therapist/availability/{slots[1]}")
    assert r.status_code in (403, 404)
    assert str(slots[1]) in {x["id"] for x in (await t.get("/therapist/availability")).json()}


async def test_only_therapists_use_the_profile_and_availability_routes(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world)
    start = _later(8)
    for who in (pair.student,):
        for method, path, body in (
            ("get", "/therapist/profile", None),
            ("patch", "/therapist/profile", {"bio": "x"}),
            ("get", "/therapist/dashboard", None),
            ("post", "/therapist/verification", {"licence_number": "ABC-123"}),
            ("get", "/therapist/availability", None),
            (
                "post",
                "/therapist/availability",
                {
                    "starts_at": start.isoformat(),
                    "ends_at": (start + dt.timedelta(hours=1)).isoformat(),
                },
            ),
        ):
            r = await getattr(who, method)(path, *([body] if body is not None else []))
            assert r.status_code == 403, (method, path)
