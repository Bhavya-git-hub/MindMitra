"""The wellness indicators: what each one means, in words a student could read.

These are indicators of how things seem to be going, from a student's own check-ins. None of
them is a diagnosis, a screening result or a clinical measure.
"""

import dataclasses
from typing import Final, Literal

from data.synthetic import STRESS_LEVELS


@dataclasses.dataclass(frozen=True)
class IndicatorSpec:
    name: str
    title: str
    kind: Literal["binary", "multiclass"]
    classes: tuple[str, ...]
    meaning: str


TABULAR_INDICATORS: Final = (
    IndicatorSpec(
        "stress_level",
        "Stress level",
        "multiclass",
        STRESS_LEVELS,
        "How stressed your recent check-ins suggest you have been: low, moderate or high.",
    ),
    IndicatorSpec(
        "burnout_risk",
        "Academic burnout risk",
        "binary",
        ("not elevated", "elevated"),
        "Signs of sustained strain: high stress with low energy, heavy workload and poor rest.",
    ),
    IndicatorSpec(
        "social_isolation",
        "Social isolation",
        "binary",
        ("not elevated", "elevated"),
        "Signs you may be feeling cut off: loneliness, low mood and gaps between check-ins.",
    ),
    IndicatorSpec(
        "sleep_lifestyle_risk",
        "Sleep and lifestyle",
        "binary",
        ("not elevated", "elevated"),
        "Signs of short, irregular or poor-quality sleep and late nights.",
    ),
    IndicatorSpec(
        "career_anxiety",
        "Career worries",
        "binary",
        ("not elevated", "elevated"),
        "How often worries about careers and placements come up alongside anxiety.",
    ),
)

SENTIMENT_TITLE: Final = "Tone of your notes"
SENTIMENT_MEANING: Final = (
    "Whether the notes you wrote with your check-ins read mostly positive, neutral or negative."
)

DISCLAIMER: Final = (
    "These are wellness indicators based on what you shared in check-ins. They are not a "
    "diagnosis or a clinical assessment, and they can be wrong."
)
