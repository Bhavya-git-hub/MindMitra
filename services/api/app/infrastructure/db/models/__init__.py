"""Importing this package registers every model on ``Base.metadata``."""

from app.infrastructure.db.models.ai import AIConversation, AIMessage, Recommendation
from app.infrastructure.db.models.audit import AuditLog
from app.infrastructure.db.models.comm import Message
from app.infrastructure.db.models.consent import Consent
from app.infrastructure.db.models.iam import (
    AuthSession,
    Credential,
    OneTimeToken,
    RefreshToken,
    User,
)
from app.infrastructure.db.models.notify import AppointmentReminder, Delivery, Notification
from app.infrastructure.db.models.org import (
    Administrator,
    CareTeamMember,
    Course,
    CourseEnrollment,
    CourseTeacher,
    Department,
    Institution,
    InstitutionSettings,
    Student,
    Teacher,
    Therapist,
)
from app.infrastructure.db.models.safety import (
    CrisisContact,
    Referral,
    RiskAlert,
    TeacherSupportRequest,
)
from app.infrastructure.db.models.therapy import (
    Appointment,
    FollowUp,
    TherapistAvailability,
    TherapyNote,
    TherapySession,
)
from app.infrastructure.db.models.wellness import (
    GroupSnapshot,
    JournalEntry,
    JournalShare,
    MoodEntry,
    Resource,
    SleepEntry,
    StressAssessment,
    WellnessAssessment,
    WellnessGoal,
)

__all__ = [
    "AIConversation",
    "AIMessage",
    "Administrator",
    "Appointment",
    "AuditLog",
    "AuthSession",
    "CareTeamMember",
    "Consent",
    "Course",
    "CrisisContact",
    "CourseEnrollment",
    "CourseTeacher",
    "Credential",
    "Department",
    "FollowUp",
    "Institution",
    "JournalEntry",
    "GroupSnapshot",
    "InstitutionSettings",
    "JournalShare",
    "Message",
    "MoodEntry",
    "AppointmentReminder",
    "Delivery",
    "Notification",
    "OneTimeToken",
    "Recommendation",
    "RefreshToken",
    "Resource",
    "Referral",
    "RiskAlert",
    "SleepEntry",
    "Student",
    "StressAssessment",
    "Teacher",
    "TeacherSupportRequest",
    "Therapist",
    "TherapistAvailability",
    "TherapyNote",
    "TherapySession",
    "User",
    "WellnessAssessment",
    "WellnessGoal",
]
