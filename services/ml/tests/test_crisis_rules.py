"""The crisis rules: phrases that must always escalate, everyday phrases that must not, and the
gentler "show resources" tier for negated or third-person mentions."""

import json
import re
from typing import Any

import pytest

from safety.crisis_rules import (
    LEXICON_PATH,
    Action,
    Severity,
    detect,
    lexicon,
    normalise,
    variants,
)
from tests.conftest import load_suite

RANK = {"low": 0, "moderate": 1, "high": 2, "imminent": 3}
NEVER_MISS = load_suite("crisis_never_miss.yaml")
NOT_ESCALATED = load_suite("crisis_not_escalated.yaml")


@pytest.mark.parametrize("case", NEVER_MISS, ids=[c["text"][:40] for c in NEVER_MISS])
def test_crisis_phrases_always_escalate(case: dict[str, Any]) -> None:
    result = detect(case["text"])
    assert result.action is Action.ESCALATE
    assert result.crisis and result.show_resources
    assert result.category == case["category"]
    assert result.severity is not None
    assert RANK[result.severity.value] >= RANK[case["severity"]]


@pytest.mark.parametrize("case", NOT_ESCALATED, ids=[c["text"][:40] for c in NOT_ESCALATED])
def test_everyday_and_negated_phrases_do_not_raise_an_alert(case: dict[str, Any]) -> None:
    result = detect(case["text"])
    assert not result.crisis
    expected = Action.REVIEW if case["review"] else Action.NONE
    assert result.action is expected


def test_someone_else_in_danger_is_marked_as_third_person() -> None:
    result = detect("my roommate keeps saying she wants to die")
    assert result.action is Action.REVIEW
    assert result.category == "concern_for_other"
    assert result.third_person


def test_the_most_urgent_category_and_severity_win() -> None:
    result = detect("I can't go on. I'm going to kill myself tonight")
    assert result.category == "suicidal_ideation"
    assert result.severity is Severity.IMMINENT
    assert "IM-TIME" in result.rules


def test_imminence_does_not_apply_to_a_help_request() -> None:
    result = detect("I need help right now")
    assert result.severity is Severity.HIGH


def test_the_result_holds_rule_ids_never_text() -> None:
    result = detect("I want to kill myself")
    assert result.rules == ("SI-KILL-SELF",)
    assert all(re.fullmatch(r"[A-Z]{2}-[A-Z-]+", r) for r in result.rules)


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_blank_text_is_no_crisis(text: str) -> None:
    assert detect(text).action is Action.NONE


@pytest.mark.parametrize(
    "text",
    [
        "I want to k​ill myself",  # zero-width space
        "I WANT TO KILL MYSELF!!!",
        "i want to k-i-l-l myself",
        "i want to kiiiill myself",
        "1 w4nt t0 k1ll mys3lf",
    ],
)
def test_obfuscated_spellings_are_caught(text: str) -> None:
    assert detect(text).crisis


def test_normalisation() -> None:
    assert normalise("  Don’t   STOP​  ") == "dont stop"
    assert normalise("soooo") == "soo"
    assert "die" in variants("diiiie")


def test_a_very_long_message_is_handled_quickly() -> None:
    text = ("I had a long day at the library and " * 400) + "i want to die"
    assert detect(text).crisis


def test_every_rule_compiles_and_has_a_known_category() -> None:
    raw = json.loads(LEXICON_PATH.read_text(encoding="utf-8"))
    ids = [r["id"] for r in raw["rules"]]
    assert len(ids) == len(set(ids))
    lex = lexicon()
    assert lex.version.startswith("crisis-rules-")
    for rule in lex.rules:
        assert rule.category in {
            "suicidal_ideation",
            "self_harm",
            "harm_to_others",
            "abuse_or_unsafe_situation",
            "acute_distress",
            "distress_signal",
        }
        # Only the review tier may be "low"; anything that escalates is moderate or above.
        assert (rule.action is Action.REVIEW) == (rule.severity is Severity.LOW)
