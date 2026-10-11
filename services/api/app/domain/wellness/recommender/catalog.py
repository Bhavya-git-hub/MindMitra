"""What the recommendation engine may suggest: non-medical ideas, grouped by the area of
student life they help with.

Every entry is something a student can do or look at themselves: a resource, a campus service,
a small goal or a check-in. There is deliberately nothing here about treatment, medication,
supplements or dosage, and no entry names a condition. ``tests/test_recommender_catalog.py``
fails if any wording here (or any rationale built from it) strays into medical territory.
"""

import dataclasses
from typing import Final, Literal

Area = Literal[
    "academic_burnout",
    "career_anxiety",
    "social_isolation",
    "sleep_disruption",
    "stress",
    "mood",
    "engagement",
]
AREAS: Final[tuple[Area, ...]] = (
    "academic_burnout",
    "career_anxiety",
    "social_isolation",
    "sleep_disruption",
    "stress",
    "mood",
    "engagement",
)
# Areas a student may switch off. Engagement nudges (check in, set a goal) are always allowed.
MUTABLE_AREAS: Final[tuple[str, ...]] = (
    "academic_burnout",
    "career_anxiety",
    "social_isolation",
    "sleep_disruption",
    "stress",
    "mood",
    "counselling",
)

Action = Literal["resource", "book_counselling", "set_goal", "check_in"]
COUNSELLING: Final = "counselling"
ENGINE_VERSION: Final = "recommender-2026.10.1"


@dataclasses.dataclass(frozen=True)
class Intervention:
    key: str
    area: Area
    title: str
    why: str  # what it is and why it can help, in a sentence, with no condition names
    tags: tuple[str, ...] = ()  # a resource with any of these tags can be offered for it
    action: Action = "resource"
    family: str | None = None  # at most one open suggestion per family (counselling)
    weight: float = 1.0  # order within an area
    needs_resource: bool = True  # not offered when no vetted resource exists to point to
    goal_categories: tuple[str, ...] = ()  # an active goal in one of these makes it a better fit


CATALOG: Final[tuple[Intervention, ...]] = (
    # -- academic burnout --------------------------------------------------------------------
    Intervention(
        "study_planning",
        "academic_burnout",
        "Plan your study weeks",
        "Setting out what needs doing, a little at a time, can make a heavy stretch feel more "
        "manageable.",
        ("study-planning", "planning"),
        weight=1.0,
        goal_categories=("academic_balance",),
    ),
    Intervention(
        "workload_planning",
        "academic_burnout",
        "Map out your workload",
        "Seeing all your deadlines in one place makes it easier to tell what can wait and what "
        "can't.",
        ("workload-planning", "deadlines", "workload"),
        weight=0.95,
        goal_categories=("academic_balance",),
    ),
    Intervention(
        "scheduled_breaks",
        "academic_burnout",
        "Build short breaks into study days",
        "Short breaks between study blocks help you keep going without running yourself down.",
        ("breaks", "movement"),
        weight=0.9,
        goal_categories=("movement", "academic_balance"),
    ),
    Intervention(
        "counselling_academic",
        "academic_burnout",
        "Talk through the pressure with a counsellor",
        "Campus counselling is there for exactly this, and you don't need to wait for a crisis "
        "to use it.",
        ("counselling", "support", "campus"),
        action="book_counselling",
        family=COUNSELLING,
        needs_resource=False,
    ),
    # -- career anxiety ----------------------------------------------------------------------
    Intervention(
        "placement_resources",
        "career_anxiety",
        "Explore placement resources",
        "Knowing what is on offer, and when, can turn a vague worry into a few concrete next "
        "steps.",
        ("placement", "career-prep"),
        weight=1.0,
    ),
    Intervention(
        "mock_interviews",
        "career_anxiety",
        "Try a mock interview",
        "Practising in a low-stakes setting builds confidence before the real thing.",
        ("interview-prep", "mock-interview"),
        weight=0.95,
    ),
    Intervention(
        "career_mentoring",
        "career_anxiety",
        "Talk with a career mentor",
        "Someone who has been through it can help you see your options more clearly.",
        ("career-mentoring", "mentoring"),
        weight=0.9,
    ),
    Intervention(
        "counselling_career",
        "career_anxiety",
        "Talk through career worries with someone",
        "Worries about what comes next are common, and talking them through with a counsellor "
        "can lighten them.",
        ("counselling", "support", "campus"),
        action="book_counselling",
        family=COUNSELLING,
        needs_resource=False,
    ),
    # -- social isolation --------------------------------------------------------------------
    Intervention(
        "join_a_club",
        "social_isolation",
        "Look at clubs and societies",
        "Shared interests make it easier to meet people without it feeling forced.",
        ("clubs", "societies"),
        weight=1.0,
        goal_categories=("social",),
    ),
    Intervention(
        "peer_activities",
        "social_isolation",
        "Try a peer activity",
        "Low-pressure group activities are an easy way to spend time with other students.",
        ("peer-activities", "social-events"),
        weight=0.95,
        goal_categories=("social",),
    ),
    Intervention(
        "social_resources",
        "social_isolation",
        "Ideas for staying connected",
        "Small, regular contact with people you trust often helps more than a big effort now "
        "and then.",
        ("social", "support"),
        weight=0.9,
        goal_categories=("social",),
    ),
    Intervention(
        "counselling_social",
        "social_isolation",
        "Talk with someone about feeling disconnected",
        "Feeling cut off is more common than it looks, and a counsellor can help you find a "
        "way back toward people.",
        ("counselling", "support", "campus"),
        action="book_counselling",
        family=COUNSELLING,
        needs_resource=False,
    ),
    # -- sleep disruption --------------------------------------------------------------------
    Intervention(
        "sleep_hygiene",
        "sleep_disruption",
        "Ease into a better wind-down",
        "A steadier evening routine can help your sleep settle.",
        ("sleep-hygiene", "sleep", "routine"),
        weight=1.0,
        goal_categories=("sleep",),
    ),
    Intervention(
        "sleep_schedule",
        "sleep_disruption",
        "Plan a steadier sleep schedule",
        "Going to bed and getting up at around the same times gives your body a rhythm to follow.",
        ("schedule-planning", "sleep-schedule"),
        weight=0.95,
        goal_categories=("sleep",),
    ),
    Intervention(
        "relaxation_wind_down",
        "sleep_disruption",
        "Try a relaxation exercise before bed",
        "A few quiet minutes of slow breathing or a guided practice can help you switch off.",
        ("relaxation", "mindfulness"),
        weight=0.9,
        goal_categories=("sleep", "mindfulness"),
    ),
    # -- stress ------------------------------------------------------------------------------
    Intervention(
        "stress_skills",
        "stress",
        "Try a short exercise to settle your stress",
        "A few minutes of breathing or grounding can take the edge off.",
        ("breathing", "grounding", "stress"),
        weight=1.0,
        goal_categories=("mindfulness",),
    ),
    Intervention(
        "counselling_stress",
        "stress",
        "Talk with someone about the stress you're carrying",
        "You don't have to carry it alone, and a counsellor can help you sort out what to do "
        "first.",
        ("counselling", "support", "campus"),
        action="book_counselling",
        family=COUNSELLING,
        needs_resource=False,
    ),
    # -- mood --------------------------------------------------------------------------------
    Intervention(
        "counselling_general",
        "mood",
        "Consider talking with someone",
        "You don't need to wait for a crisis: the campus counselling team is there for exactly "
        "this.",
        ("counselling", "support", "campus"),
        action="book_counselling",
        family=COUNSELLING,
        needs_resource=False,
    ),
    Intervention(
        "gentle_mindfulness",
        "mood",
        "Give yourself a gentle pause",
        "A short guided practice can be a kind way to reset on a heavy day.",
        ("mindfulness", "relaxation"),
        weight=0.9,
        goal_categories=("mindfulness",),
    ),
    # -- engagement --------------------------------------------------------------------------
    Intervention(
        "check_in_nudge",
        "engagement",
        "Take a minute to check in",
        "A quick check-in helps you spot patterns, and it only takes a minute.",
        action="check_in",
        needs_resource=False,
    ),
    Intervention(
        "set_a_goal",
        "engagement",
        "Set one small wellness goal",
        "Small, specific goals are easier to keep. Pick one thing you'd like to do more of.",
        action="set_goal",
        needs_resource=False,
    ),
)

BY_KEY: Final = {i.key: i for i in CATALOG}
assert len(BY_KEY) == len(CATALOG), "duplicate intervention key"

# Every tag any intervention can look for, for a single resource query.
ALL_TAGS: Final[tuple[str, ...]] = tuple(sorted({t for i in CATALOG for t in i.tags}))

# The goal category suggested to someone who has no goal yet, by their most pressing area.
GOAL_FOR_AREA: Final[dict[str, str]] = {
    "academic_burnout": "academic_balance",
    "career_anxiety": "other",
    "social_isolation": "social",
    "sleep_disruption": "sleep",
    "stress": "mindfulness",
    "mood": "mindfulness",
}
