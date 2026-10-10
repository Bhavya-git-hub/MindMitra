"""What a conversation is about, from simple word lists.

The topic only chooses which coping ideas the prompt offers the model; it is never shown to
anyone, stored as a label about the student, or used to decide anything else. "general" is a
perfectly good answer.
"""

import enum
import re
from collections.abc import Sequence

from safety.crisis_rules import normalise


class Topic(enum.StrEnum):
    ACADEMIC_STRESS = "academic_stress"
    CAREER_ANXIETY = "career_anxiety"
    HOMESICKNESS = "homesickness"
    LONELINESS = "loneliness"
    PEER_COMPARISON = "peer_comparison"
    IMPOSTER_FEELINGS = "imposter_feelings"
    TIME_MANAGEMENT = "time_management"
    SLEEP_LIFESTYLE = "sleep_lifestyle"
    RELATIONSHIP_STRESS = "relationship_stress"
    FINANCIAL_STRESS = "financial_stress"
    TRANSITION_ADJUSTMENT = "transition_adjustment"
    GENERAL = "general"


_WORDS: dict[Topic, tuple[str, ...]] = {
    Topic.ACADEMIC_STRESS: (
        "exam",
        "exams",
        "test",
        "tests",
        "midterm",
        "midterms",
        "finals",
        "assignment",
        "assignments",
        "grades",
        "grade",
        "gpa",
        "cgpa",
        "marks",
        "failing",
        "fail",
        "failed",
        "backlog",
        "backlogs",
        "professor",
        "prof",
        "studying",
        "study",
        "coursework",
        "viva",
        "semester",
        "attendance",
        "lab report",
        "thesis",
        "dissertation",
        "quiz",
        "syllabus",
    ),
    Topic.CAREER_ANXIETY: (
        "career",
        "job",
        "jobs",
        "internship",
        "internships",
        "placement",
        "placements",
        "interview",
        "interviews",
        "resume",
        "cv",
        "recruiter",
        "hired",
        "unemployed",
        "job offer",
        "my future",
        "after graduation",
        "career path",
        "rejection email",
    ),
    Topic.HOMESICKNESS: (
        "homesick",
        "miss home",
        "missing home",
        "miss my family",
        "miss my parents",
        "miss my mom",
        "miss my mum",
        "miss my dad",
        "back home",
        "hometown",
        "home food",
        "far from home",
        "away from home",
        "my family is far",
    ),
    Topic.LONELINESS: (
        "lonely",
        "loneliness",
        "alone",
        "no friends",
        "isolated",
        "left out",
        "nobody to talk",
        "no one to talk",
        "by myself",
        "friendless",
        "no one gets me",
        "invisible",
    ),
    Topic.PEER_COMPARISON: (
        "everyone else",
        "compared to",
        "comparing",
        "compare myself",
        "better than me",
        "ahead of me",
        "behind everyone",
        "everyone is",
        "my friends all",
        "linkedin",
        "instagram",
        "jealous",
        "envious",
        "topper",
        "toppers",
    ),
    Topic.IMPOSTER_FEELINGS: (
        "imposter",
        "impostor",
        "fraud",
        "dont belong",
        "do not belong",
        "not good enough",
        "not smart enough",
        "got lucky",
        "find out",
        "undeserving",
        "dont deserve",
        "faking it",
        "out of my depth",
    ),
    Topic.TIME_MANAGEMENT: (
        "procrastinate",
        "procrastinating",
        "procrastination",
        "time management",
        "too much to do",
        "no time",
        "schedule",
        "cant focus",
        "distracted",
        "last minute",
        "behind on",
        "to-do",
        "todo",
        "prioritise",
        "prioritize",
        "deadlines",
        "deadline",
        "overwhelmed with work",
        "juggling",
    ),
    Topic.SLEEP_LIFESTYLE: (
        "sleep",
        "sleeping",
        "cant sleep",
        "tired",
        "exhausted",
        "all-nighter",
        "all nighter",
        "awake",
        "nap",
        "caffeine",
        "coffee",
        "energy drink",
        "energy drinks",
        "exercise",
        "eating",
        "diet",
        "screen time",
        "phone at night",
        "routine",
        "insomnia",
        "fatigue",
    ),
    Topic.RELATIONSHIP_STRESS: (
        "boyfriend",
        "girlfriend",
        "partner",
        "breakup",
        "break up",
        "broke up",
        "relationship",
        "crush",
        "roommate",
        "fight with",
        "argument",
        "friendship",
        "my parents",
        "family",
        "ex",
        "cheated",
        "toxic",
    ),
    Topic.FINANCIAL_STRESS: (
        "money",
        "fees",
        "fee",
        "tuition",
        "loan",
        "loans",
        "rent",
        "afford",
        "scholarship",
        "debt",
        "part-time job",
        "part time job",
        "expenses",
        "financial",
        "finances",
        "budget",
        "cant pay",
        "pocket money",
    ),
    Topic.TRANSITION_ADJUSTMENT: (
        "new city",
        "first year",
        "fresher",
        "freshers",
        "freshman",
        "moved",
        "moving",
        "new college",
        "adjusting",
        "adjust",
        "settle in",
        "settling",
        "culture",
        "hostel life",
        "new place",
        "transfer",
        "starting college",
        "language barrier",
        "new campus",
    ),
}

_PATTERNS: dict[Topic, re.Pattern[str]] = {
    topic: re.compile(r"\b(?:" + "|".join(re.escape(w) for w in words) + r")\b")
    for topic, words in _WORDS.items()
}
_BROKE_NOT_UP = re.compile(r"\bbroke\b(?!\s+up)")


def _scores(text: str) -> dict[Topic, int]:
    t = normalise(text)
    scores = {topic: len(p.findall(t)) for topic, p in _PATTERNS.items()}
    scores[Topic.FINANCIAL_STRESS] += len(_BROKE_NOT_UP.findall(t))
    return scores


def detect_topic(message: str, earlier_user_messages: Sequence[str] = ()) -> Topic:
    """The topic of the latest message; if it has none, the most recent earlier one that did."""
    for text in (message, *reversed(earlier_user_messages)):
        scores = _scores(text)
        best = max(scores.values())
        if best > 0:
            # Ties go to the order topics are listed in.
            return next(t for t in _WORDS if scores[t] == best)
    return Topic.GENERAL
