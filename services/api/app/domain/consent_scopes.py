"""What each consent scope means, in plain language (shown to students; scopes are enforced
elsewhere by the policies that check for an active grant)."""

import dataclasses

from app.infrastructure.db.enums import ConsentScope


@dataclasses.dataclass(frozen=True)
class ScopeInfo:
    scope: ConsentScope
    title: str
    description: str
    required: bool = False  # cannot be withdrawn here: it is the basis for using the service
    effective_note: str = "Takes effect immediately."


SCOPES: tuple[ScopeInfo, ...] = (
    ScopeInfo(
        ConsentScope.TERMS_AND_PRIVACY,
        "Terms and privacy notice",
        "You agreed to how MindMitra works and how your information is handled. To withdraw "
        "this, you would close your account, which you can ask the privacy team to do.",
        required=True,
    ),
    ScopeInfo(
        ConsentScope.SHARE_MOOD_WITH_CARE_TEAM,
        "Share my mood check-ins with my therapist",
        "Lets a verified therapist on your care team see your mood, energy, stress and sleep "
        "from check-ins, and their trends over time. They never see the private notes you "
        "write in a check-in.",
    ),
    ScopeInfo(
        ConsentScope.SHARE_ASSESSMENTS_WITH_CARE_TEAM,
        "Share my wellbeing assessments with my therapist",
        "Lets a therapist on your care team see the results of the wellbeing checks you take.",
    ),
    ScopeInfo(
        ConsentScope.SHARE_AI_SIGNALS_WITH_CARE_TEAM,
        "Share AI wellness indicators with my therapist",
        "Lets a verified therapist on your care team see the wellness indicators MindMitra "
        "estimates from your last 28 days of check-ins: stress level, burnout risk, social "
        "isolation, sleep and lifestyle, and career worry. They are estimates, not a "
        "diagnosis, and they never raise an alert on their own. Your notes, journal and "
        "companion conversations are never shared, and the tone of your notes is left out. "
        "Whatever you choose, if a message suggests you may not be safe, your counselling team "
        "is asked to reach out, without seeing what you wrote.",
    ),
    ScopeInfo(
        ConsentScope.JOURNAL_SAFETY_SCANNING,
        "Check my journal for safety concerns",
        "Allows a safety check of journal text so a person can reach out if you may be in "
        "danger. Journals stay private to you either way.",
    ),
    ScopeInfo(
        ConsentScope.AI_COMPANION_HISTORY,
        "Keep my AI companion history",
        "Keeps your companion conversations for 90 days after your last message. Turn it off "
        "and each conversation is deleted a day after your last message. You can delete a "
        "conversation yourself at any time.",
    ),
    ScopeInfo(
        ConsentScope.ANONYMOUS_AGGREGATE_RESEARCH,
        "Include me in anonymous, combined statistics",
        "Your data may count toward combined figures that help your institution understand "
        "wellbeing. Groups smaller than 10 are never shown and you are never identifiable.",
    ),
    ScopeInfo(
        ConsentScope.EMAIL_NOTIFICATIONS,
        "Email me reminders",
        "Sends short, content-free emails such as appointment reminders.",
    ),
    ScopeInfo(
        ConsentScope.SMS_NOTIFICATIONS,
        "Text me reminders",
        "Sends short, content-free text messages such as appointment reminders.",
    ),
)

BY_SCOPE = {s.scope: s for s in SCOPES}
