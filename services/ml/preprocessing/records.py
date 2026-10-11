"""The input to every wellness indicator: one record per day a student checked in.

The API builds these from the student's own check-ins (mood, energy, stress, sleep, the
emotions and stressors they picked). Every field is optional because students log what they
choose. The same records drive training (from the synthetic generator) and inference, so the
features are always computed by the same code.
"""

import dataclasses
import datetime as dt
from typing import Final

# The words students can pick in the app (see services/api seed content). Anything else is
# ignored, so free text never becomes a feature.
EMOTIONS: Final = (
    "calm",
    "hopeful",
    "tired",
    "anxious",
    "motivated",
    "overwhelmed",
    "content",
    "restless",
    "lonely",
    "grateful",
    "irritable",
    "focused",
    "sad",
    "energised",
)
NEGATIVE_EMOTIONS: Final = frozenset(
    {"tired", "anxious", "overwhelmed", "restless", "lonely", "irritable", "sad"}
)
STRESSORS: Final = (
    "exams",
    "deadlines",
    "finances",
    "sleep",
    "relationships",
    "housing",
    "workload",
    "career",
)


@dataclasses.dataclass(frozen=True)
class DailyRecord:
    day: dt.date
    mood: int | None = None  # 1 (very low) to 5 (very good)
    energy: int | None = None  # 1 to 5
    stress: int | None = None  # 1 (none) to 5 (very high), perceived
    sleep_minutes: int | None = None
    sleep_quality: int | None = None  # 1 to 5
    bedtime_hour: float | None = None  # local clock hour, 0 to 24
    emotions: tuple[str, ...] = ()
    stressors: tuple[str, ...] = ()
