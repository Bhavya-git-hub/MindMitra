"""Institution settings an administrator can change: notifications and safety.

Pure validation, no database. Each group has defaults, so an institution that has never saved
anything behaves as it did before settings existed. What an administrator can *not* change is
listed in ``NOTIFICATION_INVARIANTS`` and ``SAFETY_INVARIANTS`` and returned with the settings,
so the interface can say so rather than hide a switch that does nothing.
"""

from typing import Final

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_REMINDERS = 3

NOTIFICATION_INVARIANTS: Final[tuple[str, ...]] = (
    "Safety alerts, appointment changes, messages and system notices are always shown in the app.",
    "Notifications never contain what a student wrote, a therapist's notes or any clinical detail.",
)

SAFETY_INVARIANTS: Final[tuple[str, ...]] = (
    "The Get help button and the emergency page are always shown to students.",
    "A teacher's safety concern always raises an alert for a person to review.",
    "Alerts are reviewed by people. Nothing here lets a system act on a student automatically.",
    "At least one emergency contact must stay active.",
    "The AI companion never diagnoses, never discusses medication, and hands every crisis to "
    "a person; a crisis message always gets crisis contacts, even over the daily limit.",
)


class NotificationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reminders_enabled: bool = True
    # Hours before an appointment, largest first, at most MAX_REMINDERS.
    appointment_reminder_hours: list[int] = Field(default_factory=lambda: [24, 2])
    recommendation_notifications: bool = True
    goal_reminders: bool = True
    # Takes effect once e-mail delivery of notifications is switched on in deployment.
    email_enabled: bool = False

    @field_validator("appointment_reminder_hours")
    @classmethod
    def _reminders(cls, hours: list[int]) -> list[int]:
        if len(hours) > MAX_REMINDERS:
            raise ValueError(f"at most {MAX_REMINDERS} reminders")
        if any(h < 1 or h > 168 for h in hours):
            raise ValueError("reminders are between 1 and 168 hours before")
        return sorted(set(hours), reverse=True)


class SafetySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # How long a therapist has to acknowledge an alert raised by a student's request for
    # a person to reach out, a teacher's safety referral, or the AI companion.
    alert_ack_minutes: int = Field(default=15, ge=5, le=1440)
    # The AI companion for students. Off hides it; crisis contacts and Get help stay.
    companion_enabled: bool = True
    # Messages one student may send the companion per day (crisis messages always get through).
    companion_daily_messages: int = Field(default=100, ge=10, le=500)


def merged[T: BaseModel](model: type[T], stored: dict[str, object] | None) -> T:
    """Stored values over the defaults. Unknown or invalid stored keys fall back to defaults."""
    try:
        return model.model_validate(stored or {})
    except ValueError:
        return model()
