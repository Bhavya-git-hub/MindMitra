"""A provider that calls no model, for development, tests and end-to-end runs.

Replies are fixed, supportive sentences chosen by topic, so a conversation behaves like the
real thing without any text leaving the machine. Never used in production (the settings refuse
it there).
"""

from typing import Final

from app.companion.topics import Topic
from app.providers.base import GenerationRequest

_OPENERS: Final = (
    "That sounds like a lot to carry.",
    "Thank you for sharing that with me.",
    "It makes sense that this is weighing on you.",
)

_IDEAS: Final[dict[Topic, str]] = {
    Topic.ACADEMIC_STRESS: (
        "When the workload feels huge, it can help to pick just one small next step, like "
        "twenty-five focused minutes on one topic, then a proper break. Asking a professor or a "
        "study group for help early is a strength, not a weakness."
    ),
    Topic.CAREER_ANXIETY: (
        "Career questions can feel enormous because so much is unknown. It can help to split "
        "what you can do this week, such as one application or a chat with the careers office, "
        "from the far-off questions that don't need answers yet."
    ),
    Topic.HOMESICKNESS: (
        "Missing home is really common, especially early on, and it usually eases with time. A "
        "regular call with family and a small weekly routine here can make this place feel a "
        "bit more like yours."
    ),
    Topic.LONELINESS: (
        "Feeling alone is hard, and lots of students feel it even when it doesn't show. One "
        "small, low-pressure step, like a club meeting or saying yes to one invitation, can be "
        "a gentle place to start."
    ),
    Topic.PEER_COMPARISON: (
        "It's easy to compare our insides with everyone else's highlights. It might help to "
        "look at how far you've come compared with yourself a year ago, rather than with "
        "anyone else."
    ),
    Topic.IMPOSTER_FEELINGS: (
        "A lot of capable people feel like they don't belong, especially somewhere new. It "
        "can help to write down a few things you've done well, as evidence for the days that "
        "voice gets loud."
    ),
    Topic.TIME_MANAGEMENT: (
        "When everything feels urgent, writing it all down and choosing just the top one or "
        "two can bring some calm. Starting with only five minutes is often enough to get "
        "going."
    ),
    Topic.SLEEP_LIFESTYLE: (
        "Sleep and energy affect everything else. A steady wake-up time, some daylight during "
        "the day and a screen-free wind-down before bed can help. If sleep stays difficult, a "
        "doctor is the right person to talk to."
    ),
    Topic.RELATIONSHIP_STRESS: (
        "Tension with people we care about can be really draining. It can help to get clear on "
        "what you need first, then find a calm moment to say it, starting with how you feel."
    ),
    Topic.FINANCIAL_STRESS: (
        "Money worries can sit in the background of everything. The campus financial aid "
        "office can explain options like scholarships, instalments or emergency funds, and "
        "writing down essential costs can make it feel more manageable."
    ),
    Topic.TRANSITION_ADJUSTMENT: (
        "Settling into something new takes time, and ups and downs are a normal part of it. "
        "A small routine and one or two campus groups can help it start to feel familiar."
    ),
    Topic.GENERAL: ("I'm here to listen and help you think things through, whenever you'd like."),
}

_QUESTIONS: Final = (
    "What feels most pressing for you right now?",
    "What do you think might help a little, even just today?",
    "How have you been looking after yourself through this?",
)

_NUDGE: Final = (
    "A counsellor could also help with this, and you can book one from Talk to a therapist "
    "whenever you're ready."
)


class FakeProvider:
    model_id = "fake-companion-1"

    async def generate(self, request: GenerationRequest) -> str:
        turn = sum(1 for m in request.messages if m.role == "user")
        parts = [
            _OPENERS[turn % len(_OPENERS)],
            _IDEAS[request.topic],
        ]
        if "suggest talking to a counsellor" in request.system:
            parts.append(_NUDGE)
        parts.append(_QUESTIONS[turn % len(_QUESTIONS)])
        return " ".join(parts)

    async def aclose(self) -> None:
        return None
