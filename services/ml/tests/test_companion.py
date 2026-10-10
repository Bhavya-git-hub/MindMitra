"""The companion orchestrator: everyday conversations across every supported topic, the
red-team suite, unsafe model output, provider failure, and what the model is (and is not)
shown."""

from typing import Any

import pytest

from app.companion.context import MAX_CONTEXT_CHARS, Turn, build_context
from app.companion.orchestrator import ReplyKind, respond
from app.companion.prompts import SYSTEM_PROMPT, build_system_prompt
from app.companion.topics import Topic, detect_topic
from app.providers.fake import FakeProvider
from safety import templates
from safety.crisis_rules import Action
from safety.output_guard import check_output
from tests.conftest import load_suite
from tests.providers_for_tests import BrokenProvider, ScriptedProvider

NORMAL = load_suite("normal_conversations.yaml")
REDTEAM = load_suite("redteam.yaml")
UNSAFE_OUTPUTS = [c["text"] for c in load_suite("output_guard.yaml") if c["blocked"]]


# ---- normal conversations -------------------------------------------------------------------


@pytest.mark.parametrize("case", NORMAL, ids=[c["topic"] for c in NORMAL])
async def test_everyday_messages_get_a_checked_supportive_reply(case: dict[str, Any]) -> None:
    result = await respond(FakeProvider(), case["text"], [], max_tokens=300)
    assert result.kind is ReplyKind.REPLY
    assert result.topic.value == case["topic"]
    assert result.crisis.action is Action.NONE
    assert result.reply and check_output(result.reply).ok
    assert result.model_id == "fake-companion-1"
    assert not any(f.startswith("output_guard") for f in result.flags)


async def test_a_multi_turn_conversation_keeps_its_topic() -> None:
    history = [
        Turn("user", "I have a huge exam on Friday"),
        Turn("assistant", "That sounds stressful. What's worrying you most?"),
    ]
    result = await respond(
        FakeProvider(), "yeah I just can't seem to start", history, max_tokens=300
    )
    assert result.kind is ReplyKind.REPLY
    assert result.topic is Topic.ACADEMIC_STRESS


def test_topic_falls_back_to_general() -> None:
    assert detect_topic("hello there") is Topic.GENERAL
    assert detect_topic("I'm broke and can't pay rent") is Topic.FINANCIAL_STRESS
    assert detect_topic("we broke up last week") is Topic.RELATIONSHIP_STRESS


# ---- red team -------------------------------------------------------------------------------


@pytest.mark.parametrize("case", REDTEAM, ids=[c["text"][:40] for c in REDTEAM])
async def test_red_team_messages_never_reach_the_model(case: dict[str, Any]) -> None:
    provider = ScriptedProvider("I love you. You have depression. Take 20 mg of Xanax.")
    result = await respond(provider, case["text"], [], max_tokens=300)
    assert result.kind.value == case["kind"]
    assert case["flag"] in result.flags
    assert provider.requests == []  # the model was never asked
    if result.kind is ReplyKind.CRISIS:
        assert result.reply is None  # the API answers a crisis, with resources
        assert result.crisis.crisis
    else:
        assert result.reply in (
            templates.DIAGNOSIS_REQUEST,
            templates.MEDICATION_REQUEST,
            templates.PROMPT_INJECTION,
        )


async def test_a_crisis_in_the_middle_of_a_normal_conversation_still_escalates() -> None:
    provider = ScriptedProvider("ok")
    history = [Turn("user", "exams are stressing me"), Turn("assistant", "That sounds hard.")]
    result = await respond(provider, "honestly I just want to die", history, max_tokens=300)
    assert result.kind is ReplyKind.CRISIS
    assert result.crisis.crisis
    assert provider.requests == []


# ---- unsafe model output --------------------------------------------------------------------


@pytest.mark.parametrize("unsafe", UNSAFE_OUTPUTS, ids=[t[:40] or "empty" for t in UNSAFE_OUTPUTS])
async def test_an_unsafe_model_reply_is_replaced_not_shown(unsafe: str) -> None:
    provider = ScriptedProvider(unsafe)
    result = await respond(provider, "I'm stressed about my exams", [], max_tokens=300)
    assert result.kind is ReplyKind.FALLBACK
    assert result.reply == templates.SAFE_FALLBACK
    assert any(f.startswith("output_guard:") for f in result.flags)
    if unsafe:
        assert unsafe not in (result.reply or "")


async def test_a_model_reply_with_crisis_language_is_replaced() -> None:
    provider = ScriptedProvider("Some people just want to end it all, and that's okay.")
    result = await respond(provider, "rough week", [], max_tokens=300)
    assert result.kind is ReplyKind.FALLBACK
    assert "output_guard:crisis_language" in result.flags


# ---- failures -------------------------------------------------------------------------------


async def test_a_provider_failure_gives_a_fixed_reply() -> None:
    provider = BrokenProvider()
    result = await respond(provider, "I'm worried about placements", [], max_tokens=300)
    assert result.kind is ReplyKind.UNAVAILABLE
    assert result.reply == templates.UNAVAILABLE
    assert "provider_error" in result.flags
    assert provider.calls == 1


async def test_a_provider_failure_never_hides_a_crisis() -> None:
    provider = BrokenProvider()
    result = await respond(provider, "I'm going to kill myself", [], max_tokens=300)
    assert result.kind is ReplyKind.CRISIS
    assert provider.calls == 0


async def test_soft_signals_still_get_a_reply_and_are_flagged_for_resources() -> None:
    result = await respond(FakeProvider(), "I feel so hopeless about my grades", [], max_tokens=300)
    assert result.kind is ReplyKind.REPLY
    assert result.crisis.action is Action.REVIEW
    assert "support_resources" in result.flags


# ---- what the model sees --------------------------------------------------------------------


async def test_the_model_never_sees_personal_details() -> None:
    provider = ScriptedProvider("That sounds hard. What feels most pressing?")
    history = [
        Turn("user", "my email is aarav.k@example.com and my roll no is 21CS10045"),
        Turn("assistant", "Thanks for sharing."),
    ]
    await respond(provider, "call me on 98765 43210 please", history, max_tokens=300)
    sent = " ".join(m.content for m in provider.requests[0].messages)
    assert "example.com" not in sent and "21CS10045" not in sent and "98765" not in sent
    assert "[email]" in sent and "[number]" in sent and "[phone number]" in sent


async def test_the_system_prompt_carries_the_rules_and_topic_guidance() -> None:
    provider = ScriptedProvider("That sounds hard. What feels most pressing?")
    await respond(provider, "I'm so homesick", [], max_tokens=300)
    system = provider.requests[0].system
    assert system.startswith(SYSTEM_PROMPT)
    assert "Never diagnose" in system and "Never mention medication" in system
    assert "Homesickness" in system


def test_context_keeps_recent_turns_within_budget_and_alternates() -> None:
    history: list[Turn] = []
    for i in range(30):
        history.append(Turn("user", f"message {i} " + "x" * 900))
        history.append(Turn("assistant", f"reply {i}"))
    ctx = build_context(history, "latest")
    assert ctx.trimmed
    assert sum(len(t.content) for t in ctx.messages) <= MAX_CONTEXT_CHARS + 100
    assert ctx.messages[0].role == "user"
    assert ctx.messages[-1] == Turn("user", "latest")
    roles = [t.role for t in ctx.messages]
    assert all(a != b for a, b in zip(roles, roles[1:], strict=False))


def test_context_merges_consecutive_turns_from_one_side() -> None:
    history = [Turn("assistant", "orphan"), Turn("user", "a"), Turn("user", "b")]
    ctx = build_context(history, "c")
    assert [t.role for t in ctx.messages] == ["user"]
    assert ctx.messages[0].content == "a\n\nb\n\nc"


def test_a_long_conversation_suggests_a_person() -> None:
    history: list[Turn] = []
    for i in range(9):
        history += [Turn("user", f"exam worry {i}"), Turn("assistant", "I hear you.")]
    assert build_context(history, "another worry").suggest_human_support
    assert not build_context(history[:-2], "another worry").suggest_human_support


def test_repeated_low_moments_suggest_a_person() -> None:
    history = [Turn("user", "I feel worthless"), Turn("assistant", "That sounds painful.")]
    assert build_context(history, "everything feels hopeless").suggest_human_support
    assert "suggest talking to a counsellor" in build_system_prompt(
        Topic.GENERAL, suggest_human_support=True
    )
