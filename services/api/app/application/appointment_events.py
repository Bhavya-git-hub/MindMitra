"""Real-time hints that an appointment changed, for the two people in it and nobody else."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db import models as m
from app.infrastructure.events import queue_event


def appointment_changed(db: AsyncSession, appt: m.Appointment, event: str) -> None:
    """``event`` is a fixed word (requested, confirmed, cancelled, rescheduled, ...)."""
    payload = {"type": "appointment", "appointment_id": str(appt.id), "event": event}
    queue_event(db, appt.student_id, payload)
    queue_event(db, appt.therapist_id, payload)
