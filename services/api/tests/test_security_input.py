"""Security regression tests for input handling (security audit 2026-10).

Links that administrators enter are rendered as ``<a href>`` for students, so anything but an
``https://`` address (``javascript:``, ``data:``, ...) must be refused on every write path.
Search text is always a bound parameter. Malformed bodies get a problem response that reveals
nothing about the server.
"""

from collections.abc import AsyncIterator
from urllib.parse import quote

import httpx
import pytest
import pytest_asyncio

from app.domain.safety.classifier import CLASSIFIER
from app.domain.safety.risk import RiskLevel
from tests.api_helpers import API
from tests.api_world import World
from tests.student_helpers import Session, sign_in

pytestmark = pytest.mark.asyncio

DANGEROUS_LINKS = [
    "javascript:alert(document.cookie)",
    "JaVaScRiPt:alert(1)",
    " javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "vbscript:msgbox(1)",
    "//evil.example/x",
    "https:javascript:alert(1)",
]


@pytest_asyncio.fixture
async def admin(client: httpx.AsyncClient, world: World) -> Session:
    return await sign_in(client, world.admin, world.password)


def _resource(url: str) -> dict[str, object]:
    return {
        "title": "Grounding exercise",
        "summary": "A short grounding exercise.",
        "resource_type": "exercise",
        "body": None,
        "url": url,
        "tags": ["calm"],
        "duration_minutes": 5,
    }


@pytest.mark.parametrize("url", DANGEROUS_LINKS)
async def test_resource_links_must_be_https(admin: Session, url: str) -> None:
    r = await admin.post("/admin/resources", _resource(url))
    assert r.status_code == 422, r.text
    assert "script" not in r.text.lower()  # the input is not echoed back


@pytest.mark.parametrize("url", DANGEROUS_LINKS)
async def test_crisis_contact_links_must_be_https_on_create_and_update(
    admin: Session, url: str
) -> None:
    base = {"label": "Counselling desk", "kind": "campus", "phone": "0000 000 000"}
    made = await admin.post("/admin/settings/crisis-contacts", base)
    assert made.status_code == 201, made.text
    cid = made.json()["id"]
    try:
        bad = await admin.post("/admin/settings/crisis-contacts", base | {"url": url})
        assert bad.status_code == 422, bad.text
        changed = await admin.patch(f"/admin/settings/crisis-contacts/{cid}", {"url": url})
        assert changed.status_code == 422, changed.text
        listed = (await admin.get("/admin/settings/crisis-contacts")).json()
        assert all(c["url"] is None or c["url"].startswith("https://") for c in listed)
    finally:
        await admin.delete(f"/admin/settings/crisis-contacts/{cid}")


@pytest.mark.parametrize(
    "term",
    ["' OR '1'='1", "'; DROP TABLE iam.users; --", "\\", "%' OR 1=1 --", "_"],
)
async def test_search_text_is_a_bound_parameter(admin: Session, term: str) -> None:
    r = await admin.get(f"/admin/users?q={quote(term)}")
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 0
    assert (await admin.get("/admin/users?limit=1")).json()["total"] > 0  # table intact


async def test_deeply_nested_or_malformed_json_gets_a_plain_problem(admin: Session) -> None:
    for raw in ("[" * 100_000, '{"content":' * 50_000, '{"content": "unterminated'):
        r = await admin.client.post(
            f"{API}/admin/resources",
            content=raw,
            headers={"Authorization": f"Bearer {admin.token}", "content-type": "application/json"},
        )
        assert r.status_code in (400, 413, 422), r.text  # 413: over the body size cap
        assert r.headers["content-type"].startswith("application/problem+json")
        assert "Traceback" not in r.text and 'File "' not in r.text


# ---- crisis rules and input shaping -------------------------------------------------------------

# Invisible format characters, variation selectors, combining marks and look-alike letters used
# to hide a crisis phrase from the rules, so the message went to the model instead of getting
# crisis contacts and an alert. ``crisis_rules.normalise`` now strips and folds them.
SHAPED_CRISIS = {
    "left-to-right mark": "I want to k‎ill myself",
    "right-to-left override": "I want to k‮ill myself",
    "invisible times": "I want to k⁢ill myself",
    "tag space": "I want to k\U000e0020ill myself",
    "combining grapheme joiner": "I want to k͏ill myself",
    "variation selector": "I want to k️ill myself",
    "combining accent": "I want to kíll myself",
    "cyrillic i": "I want to kіll myself",
}


@pytest.mark.parametrize("text", SHAPED_CRISIS.values(), ids=SHAPED_CRISIS.keys())
async def test_shaped_crisis_text_is_still_a_crisis(text: str) -> None:
    assert CLASSIFIER.assess_text(text).level.at_least(RiskLevel.HIGH)


# ---- request size ---------------------------------------------------------------------------


async def test_an_oversized_body_is_refused_before_anything_reads_it(
    client: httpx.AsyncClient,
) -> None:
    """Before the cap, a 50 MB anonymous body was buffered and parsed before the 401."""
    big = b'{"email":"x@y.example","password":"' + b"a" * (600 * 1024) + b'"}'
    r = await client.post(
        f"{API}/auth/login", content=big, headers={"content-type": "application/json"}
    )
    assert r.status_code == 413
    assert r.headers["content-type"].startswith("application/problem+json")


async def test_an_oversized_chunked_body_is_refused_too(client: httpx.AsyncClient) -> None:
    async def chunks() -> AsyncIterator[bytes]:
        yield b'{"email":"x@y.example","password":"'
        for _ in range(80):
            yield b"a" * 8192
        yield b'"}'

    r = await client.post(
        f"{API}/auth/login", content=chunks(), headers={"content-type": "application/json"}
    )
    assert r.status_code == 413, r.text


async def test_an_ordinary_body_is_unaffected(client: httpx.AsyncClient) -> None:
    r = await client.post(
        f"{API}/auth/login", json={"email": "nobody@test.example", "password": "x" * 1000}
    )
    assert r.status_code == 401
