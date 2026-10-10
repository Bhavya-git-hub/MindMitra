"""Domain enumerations persisted as VARCHAR + CHECK constraints."""

import enum


class UserRole(enum.StrEnum):
    STUDENT = "student"
    THERAPIST = "therapist"
    TEACHER = "teacher"
    ADMINISTRATOR = "administrator"


class UserStatus(enum.StrEnum):
    INVITED = "invited"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"


class SessionRevokeReason(enum.StrEnum):
    LOGOUT = "logout"
    REFRESH_REUSE = "refresh_reuse"  # a rotated refresh token was replayed: family revoked
    PASSWORD_CHANGED = "password_changed"  # noqa: S105 - an enum label
    ACCOUNT_DISABLED = "account_disabled"


class OneTimeTokenPurpose(enum.StrEnum):
    PASSWORD_RESET = "password_reset"  # noqa: S105 - an enum label
    ACCOUNT_SETUP = "account_setup"  # admin-created account: user sets the first password
    EMAIL_VERIFICATION = "email_verification"  # student self-registration


class AdminLevel(enum.StrEnum):
    INSTITUTION_ADMIN = "institution_admin"
    PLATFORM_ADMIN = "platform_admin"


class VerificationStatus(enum.StrEnum):
    """Professional verification of a therapist. Only ``verified`` therapists appear to students
    or reach student data; ``expired`` is derived from the licence expiry date, not stored."""

    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


class FollowUpKind(enum.StrEnum):
    CHECK_IN = "check_in"
    BOOK_SESSION = "book_session"
    REFERRAL = "referral"
    PAPERWORK = "paperwork"
    OTHER = "other"


class FollowUpStatus(enum.StrEnum):
    OPEN = "open"
    DONE = "done"
    CANCELLED = "cancelled"


class CareRole(enum.StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"


class EnrollmentStatus(enum.StrEnum):
    ENROLLED = "enrolled"
    DROPPED = "dropped"
    COMPLETED = "completed"


class GoalCategory(enum.StrEnum):
    SLEEP = "sleep"
    MOVEMENT = "movement"
    MINDFULNESS = "mindfulness"
    SOCIAL = "social"
    ACADEMIC_BALANCE = "academic_balance"
    NUTRITION = "nutrition"
    OTHER = "other"


class GoalStatus(enum.StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    PAUSED = "paused"
    ABANDONED = "abandoned"


class ResourceType(enum.StrEnum):
    ARTICLE = "article"
    VIDEO = "video"
    EXERCISE = "exercise"
    AUDIO = "audio"
    SERVICE = "service"


class SessionMode(enum.StrEnum):
    VIDEO = "video"
    IN_PERSON = "in_person"
    PHONE = "phone"


class AppointmentStatus(enum.StrEnum):
    REQUESTED = "requested"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class TherapySessionStatus(enum.StrEnum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class AIMessageRole(enum.StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class AIReplyKind(enum.StrEnum):
    """How an assistant message was produced (ADR 0010)."""

    REPLY = "reply"  # a model reply that passed the output checks
    CRISIS = "crisis"  # a fixed crisis reply with contacts; a person was alerted
    REDIRECT = "redirect"  # a fixed reply to a request the companion must not answer
    FALLBACK = "fallback"  # a fixed reply that replaced a model reply failing a check
    UNAVAILABLE = "unavailable"  # the AI service could not be reached


class AIConversationStatus(enum.StrEnum):
    ACTIVE = "active"
    ENDED = "ended"
    CRISIS_HANDOFF = "crisis_handoff"


class RecommendationSource(enum.StrEnum):
    RULE = "rule"
    MODEL = "model"
    THERAPIST = "therapist"


class RecommendationStatus(enum.StrEnum):
    PENDING = "pending"
    VIEWED = "viewed"
    DISMISSED = "dismissed"
    COMPLETED = "completed"


class AlertSource(enum.StrEnum):
    MOOD_ENTRY = "mood_entry"
    JOURNAL = "journal"
    AI_CHAT = "ai_chat"
    MESSAGE = "message"
    HELP_BUTTON = "help_button"
    FACULTY_REFERRAL = "faculty_referral"
    MODEL = "model"
    THERAPIST = "therapist"


class ReferralCategory(enum.StrEnum):
    """Why a member of staff asks for a person to reach out. Observable concerns, not labels."""

    ACADEMIC_DISTRESS = "academic_distress"
    BEHAVIOUR_CHANGE = "behaviour_change"
    WELLBEING_CONCERN = "wellbeing_concern"
    SAFETY_CONCERN = "safety_concern"


class ReferralUrgency(enum.StrEnum):
    ROUTINE = "routine"
    SOON = "soon"
    URGENT = "urgent"


class ReferralStatus(enum.StrEnum):
    """The only part of a referral's life a teacher ever sees."""

    RECEIVED = "received"
    IN_PROGRESS = "in_progress"
    CLOSED = "closed"


class ReferralOutcome(enum.StrEnum):
    """How a therapist closed a referral. Never shown to the teacher who raised it."""

    CONTACTED_STUDENT = "contacted_student"
    STUDENT_DECLINED = "student_declined"
    ALREADY_SUPPORTED = "already_supported"
    REFERRED_ELSEWHERE = "referred_elsewhere"
    NO_ACTION_NEEDED = "no_action_needed"


class TeacherSupportTopic(enum.StrEnum):
    ACADEMIC_SUPPORT = "academic_support"
    WORKLOAD = "workload"
    EXTENSION = "extension"
    WELLBEING_CHAT = "wellbeing_chat"
    OTHER = "other"


class TeacherSupportStatus(enum.StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    CLOSED = "closed"
    WITHDRAWN = "withdrawn"


class AlertDetector(enum.StrEnum):
    RULES = "rules"
    CLASSIFIER = "classifier"
    HUMAN = "human"


class AlertCategory(enum.StrEnum):
    """Support-need categories. Deliberately contains no diagnostic labels."""

    SELF_HARM_LANGUAGE = "self_harm_language"
    SUICIDAL_LANGUAGE = "suicidal_language"
    HARM_TO_OTHERS = "harm_to_others"
    UNSAFE_SITUATION = "unsafe_situation"
    ACUTE_DISTRESS = "acute_distress"
    SUSTAINED_LOW_WELLBEING = "sustained_low_wellbeing"
    ENGAGEMENT_DROP = "engagement_drop"


class AlertSeverity(enum.StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    IMMINENT = "imminent"


class AlertStatus(enum.StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    ESCALATED = "escalated"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class CrisisContactKind(enum.StrEnum):
    EMERGENCY = "emergency"
    HELPLINE = "helpline"
    CAMPUS = "campus"


class ConsentScope(enum.StrEnum):
    TERMS_AND_PRIVACY = "terms_and_privacy"
    SHARE_MOOD_WITH_CARE_TEAM = "share_mood_with_care_team"
    SHARE_ASSESSMENTS_WITH_CARE_TEAM = "share_assessments_with_care_team"
    SHARE_AI_SIGNALS_WITH_CARE_TEAM = "share_ai_signals_with_care_team"
    JOURNAL_SAFETY_SCANNING = "journal_safety_scanning"
    AI_COMPANION_HISTORY = "ai_companion_history"
    ANONYMOUS_AGGREGATE_RESEARCH = "anonymous_aggregate_research"
    EMAIL_NOTIFICATIONS = "email_notifications"
    SMS_NOTIFICATIONS = "sms_notifications"


class NotificationType(enum.StrEnum):
    APPOINTMENT_REMINDER = "appointment_reminder"
    APPOINTMENT_UPDATE = "appointment_update"
    NEW_MESSAGE = "new_message"
    RISK_ALERT = "risk_alert"
    RECOMMENDATION = "recommendation"
    GOAL_REMINDER = "goal_reminder"
    SYSTEM = "system"


class NotificationPriority(enum.StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class NotificationChannel(enum.StrEnum):
    IN_APP = "in_app"
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"


class DeliveryStatus(enum.StrEnum):
    """An external delivery (email, push) of one in-app notification."""

    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"  # gave up after the retry limit
    SKIPPED = "skipped"  # nothing to send it with, or the recipient can no longer receive it


class CancellationReason(enum.StrEnum):
    """Why an appointment was cancelled: a fixed list, never free text."""

    SCHEDULE_CONFLICT = "schedule_conflict"
    FEELING_BETTER = "feeling_better"
    UNWELL = "unwell"
    THERAPIST_UNAVAILABLE = "therapist_unavailable"
    OTHER = "other"


class AuditOutcome(enum.StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"
    ERROR = "error"
