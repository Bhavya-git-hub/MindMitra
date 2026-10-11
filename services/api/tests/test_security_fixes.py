"""Regression tests for the smaller fixes from the 2026-10 security audit.

* A risk alert is never assigned to a care-team therapist who can no longer open it (suspended,
  or verification lapsed); it goes to the whole counselling team instead.
* An answer from the AI service with an unknown kind or crisis action is a bad response (the
  companion then fails safe) rather than something passed on.
* ``%`` and ``_`` in a resource search are literal characters, not wildcards.
"""

import httpx
import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db import models as m
from app.infrastructure.db.enums import UserStatus, VerificationStatus
from app.infrastructure.ml_client import CompanionUnavailable, HttpCompanionClient
from tests.api_world import World
from tests.student_helpers import sign_in
from tests.test_companion_api import (  # noqa: F401 - fixtures
    _alert_notifications,
    _alerts,
    _say,
    _start,
    cc,
    fake,
)
from tests.test_companion_unit import OK_BODY, SECRET
from tests.therapist_helpers import care_pair, fresh_therapist

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("lapse", ["suspended", "verification_pending"])
async def test_an_alert_skips_a_care_team_therapist_who_cannot_open_it(
    cc: httpx.AsyncClient,  # noqa: F811
    api_db: AsyncSession,
    world: World,
    lapse: str,
) -> None:
    pair = await care_pair(cc, api_db, world)
    on_team = await fresh_therapist(cc, api_db, world)
    if lapse == "suspended":
        await api_db.execute(
            update(m.User).where(m.User.id == pair.therapist.id).values(status=UserStatus.SUSPENDED)
        )
    else:
        await api_db.execute(
            update(m.Therapist)
            .where(m.Therapist.user_id == pair.therapist.id)
            .values(verification_status=VerificationStatus.PENDING, verified_at=None)
        )
    await api_db.commit()

    s = await sign_in(cc, pair.student.actor, world.password)
    conv = await _start(s)
    r = await _say(s, conv, "I'm going to kill myself tonight")
    assert r.status_code == 200, r.text

    [alert] = await _alerts(api_db, s.id)
    assert alert.assigned_to is None  # the counselling team's, not the lapsed therapist's
    assert len(await _alert_notifications(api_db, on_team.id)) == 1


CRISIS: dict[str, object] = dict(OK_BODY["crisis"])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "something-new"},
        {"crisis": {**CRISIS, "action": "ignore"}},
        {"crisis": {**CRISIS, "severity": "none-at-all"}},
    ],
)
async def test_an_unknown_answer_from_the_ai_service_is_a_bad_response(
    change: dict[str, object],
) -> None:
    body = {**OK_BODY, **change}
    client = HttpCompanionClient(
        "http://ml", SECRET, transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    )
    with pytest.raises(CompanionUnavailable):
        await client.respond("hello", [])
    await client.aclose()


async def test_resource_search_treats_wildcards_as_text(
    client: httpx.AsyncClient, world: World
) -> None:
    s = await sign_in(client, world.student, world.password)
    everything = (await s.get("/resources?limit=100")).json()
    assert everything, "the world has published resources to search"
    for wildcard in ("%", "_"):
        found = (await s.get(f"/resources?q={wildcard}&limit=100")).json()
        literal = [
            x for x in everything if wildcard in x["title"] or wildcard in (x["summary"] or "")
        ]
        assert [x["id"] for x in found] == [x["id"] for x in literal]
