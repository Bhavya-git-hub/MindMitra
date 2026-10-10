"""Input guard (personal details, requests the companion must not answer) and output guard
(what a model reply must never contain)."""

from typing import Any

import pytest

from safety.input_guard import Intent, classify_intent, guard_input, scrub
from safety.output_guard import check_output
from tests.conftest import load_suite

OUTPUTS = load_suite("output_guard.yaml")
NORMAL = load_suite("normal_conversations.yaml")


@pytest.mark.parametrize("case", OUTPUTS, ids=[c["text"][:40] or "empty" for c in OUTPUTS])
def test_output_guard(case: dict[str, Any]) -> None:
    result = check_output(case["text"])
    expected = set(case["blocked"])
    if expected:
        assert not result.ok
        assert expected <= set(result.violations)
    else:
        assert result.ok, result.violations


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("mail me at riya.k@example.com", "mail me at [email]"),
        ("my number is +91 98765 43210", "my number is [phone number]"),
        ("see https://example.org/page?id=1", "see [link]"),
        ("roll no 21CS10045 failed", "roll no [number] failed"),
        ("call me on 020-7946-0018 tonight", "call me on [phone number] tonight"),
    ],
)
def test_personal_details_are_scrubbed(text: str, expected: str) -> None:
    out, changed = scrub(text)
    assert out == expected
    assert changed


def test_ordinary_numbers_are_left_alone() -> None:
    out, changed = scrub("I slept 4 hours and have 3 exams in 2 days")
    assert not changed
    assert out == "I slept 4 hours and have 3 exams in 2 days"


def test_guard_input_trims_and_caps_length() -> None:
    g = guard_input("  " + "a" * 5000 + "  ")
    assert len(g.text) == 2000
    assert g.intent is Intent.CHAT


@pytest.mark.parametrize("case", NORMAL, ids=[c["topic"] for c in NORMAL])
def test_everyday_messages_are_plain_chat(case: dict[str, Any]) -> None:
    assert classify_intent(case["text"]) is Intent.CHAT


@pytest.mark.parametrize(
    "text",
    [
        "I feel depressed about my grades",  # a feeling, not a request for a diagnosis
        "can you help me take a break from studying",
        "I'm worried about the test",
        "you are now my favourite app",
    ],
)
def test_near_misses_are_not_redirected(text: str) -> None:
    assert classify_intent(text) is Intent.CHAT
