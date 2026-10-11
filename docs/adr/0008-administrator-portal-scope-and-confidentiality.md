# ADR 0008: Administrator portal, scope and confidentiality

- Status: Accepted
- Date: 2026-10-10

## Context

Administrators run the institution: they create accounts, check that therapists are registered
professionals, set up departments and courses, curate the self-help library and decide how the
platform behaves. They are also the role most likely to be handed more access "because they are in
charge". In a mental-health product that is the wrong default. An administrator who can read
therapy notes, journals or companion chats turns every compromised or curious admin account into a
breach of the most sensitive data the product holds.

## Decision

1. **Administrators manage the institution, not the people's content.** The administrator role
   holds fourteen permissions (`ADMIN_ONLY_PERMISSIONS`): account, therapist verification,
   institution configuration, audit, student/teacher/therapist records, departments, courses,
   appointment oversight, resources, platform analytics, notification configuration and safety
   configuration. It holds none of `CONTENT_PERMISSIONS` (wellness, therapy notes, sessions, risk
   alerts, follow-ups, recommendations, messages, AI conversations). A test fails if any of those
   is ever added to the role, and the route guard test fails if an `/admin` route has no
   permission marker.
2. **Not holding a permission is not enough, so the data is never selected either.** Admin
   queries return identity and administrative fields only. A student's admin record carries name,
   email, number, department, year and status. A therapist's carries licence, verification and a
   **head count** of the caseload, never which students. Care-team membership, appointment
   participants and consent state are not returned to administrators anywhere. The test suite
   asserts this on the response bodies, not only on the status codes.
3. **Every route is institution-scoped.** A record from another institution is a `404`, the same
   as a missing one. Administrators of one institution cannot see, change or count another's.
4. **Account safety rules live in policy, not in the UI.** An administrator cannot change their own
   status (`can_manage_user` denies self) or be the subject of a therapist verification.
   Suspending or deactivating
   someone revokes their sessions in the same transaction. "Sign out everywhere" uses the existing
   `LOGOUT` revoke reason; there is no separate reason yet.
5. **Therapist verification gates student access.** An unverified, rejected or expired therapist
   is refused on every student-data route (ADR 0006). The administrator's decision (`verified` or
   `rejected`, an optional licence expiry, a note the therapist can read) is audited. Rejection
   requires a reason in the interface and the note is length-limited. It is for the registration
   only.
6. **Analytics are the teacher rules, applied institution-wide.** Wellbeing figures reuse
   `domain/wellness/cohort.py` (consenting students only, at least 10 contributors, 5 on each side
   of a share, completed 4/8/12-week windows, size bands, rounding), and the institution view is
   stored in `wellness.group_snapshots` like any other closed window (ADR 0007). The remaining
   administrative counts (appointments booked, alerts raised, appointments by outcome, weekly
   schedule) show **"fewer than 5"** when a cell is 1 to 4, and zero as zero, so a small cell can
   never identify one student's appointment. Safety-alert counts on the dashboard are not
   suppressed: they exist to tell the institution that a human response is overdue, and they carry
   no identity. Appointment oversight is counts plus a per-therapist workload table (upcoming,
   completed, no-shows, cancelled). It never names a student.
7. **Resources: administrators curate; shipped content is read only.** Resources shipped with the
   product (`source = global`) can be read but not edited or deleted. Institution resources are
   drafts until published, and publishing records the reviewing administrator and time (the
   database refuses a published item without a review). Links must be `https://`. A `faculty` tag
   keeps an item in the staff library.
8. **The audit log is readable by administrators and records that it was read.** (Amended by
   [ADR 0015](0015-security-audit-2026-10.md): on care records the administrator's view leaves
   out the student, the record id and details.) `GET /admin/audit`
   and its CSV export are themselves audited. Events hold actions and identifiers, never text:
   the audit helper rejects forbidden detail keys (body, content, note, message, journal, email,
   name and similar) and values over 200 characters. Verification of the hash chain is available
   on demand. Filters accept at most a 366-day range, pages are capped at 200 rows and an export
   at 5 000. Entries from other institutions are never returned.
9. **Settings are narrow and some are fixed.**
   - Notification settings: reminders on or off, one to three reminder hours (1 to 168), whether
     therapist suggestions notify students, goal reminders, and email. Notifications never carry
     what someone wrote. Safety alerts in the app cannot be switched off.
   - Safety settings: the number of minutes (5 to 1 440) before an unacknowledged alert counts as
     late. Alerts are always raised for people to handle; no setting automates a response.
   - Crisis contacts: administrators add, change, hide or remove their own. Contacts shipped with
     the product are read only, and **at least one emergency contact must stay active**; the API
     refuses a change that would leave none.
   - Stored in `org.institution_settings` (migration `0008`), one row per institution, validated
     against defaults and invariants in `domain/settings.py`; a missing key means the default.
10. **What is live, and what is only stored.** `alert_ack_minutes` (the response time given to
    each new alert when it is raised, which the dashboard's "past the response time" count uses) and `recommendation_notifications` are
    read by the code that acts on them. The **goal-reminder switch is validated and stored, but
    nothing consumes it yet.** (Updated by [ADR 0009](0009-therapist-communication-real-time-and-notifications.md):
    the appointment-reminder switch and hours are now used by the scheduler, and the email switch
    creates deliveries that are sent once an email provider is configured.) The interface says
    which is which, so an administrator is not led to believe something is sent when it is not.
11. **The interface is a convenience, never the control.** Role guards in the web app only hide
    what a role cannot use. The API decides. The administrator UI avoids showing a button the API
    would refuse where it can (no actions on the signed-in administrator's own row, no edit for
    shipped resources and contacts) and shows the API's reason when it is refused anyway.

## Consequences

- An administrator account that is phished or misused can lock people out, change structure and
  read metadata, but cannot read what any student wrote or any therapist recorded. That remains
  true after a permission refactor because the content permissions are asserted absent.
- Administrators cannot answer "which students does this therapist see?" or "who cancelled?".
  That is deliberate. Institutions that need those answers use the break-glass process designed in
  SECURITY_ARCHITECTURE.md §4.4, which is not built yet.
- Weekly activity counts under five are hidden, so a very small institution sees little. That is
  the intended trade-off.
- Reminder, goal-reminder and email settings do nothing until scheduled delivery exists.
- Safety-alert counts are exact. With very few alerts an administrator can know that "one alert
  is waiting", not whose it is.
- Deactivation keeps the person's records (no hard delete) so care history and the audit log stay
  intact. A retention and deletion workflow is later work.

## Alternatives considered

- **Give administrators read-only access to everything for support.** Rejected: the product's
  promise to students depends on administrators not holding it, and support rarely needs content.
- **Let administrators resolve safety alerts.** Rejected: alerts go to clinicians; the
  administrator sees only that one is late.
- **Hide small numbers only in the interface.** Rejected: the API must not send the number.
- **A free-text "reason" on suspension.** Rejected for now: the audit log forbids free text, and
  the account owner would see it nowhere.
