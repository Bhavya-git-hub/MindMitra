# MindMitra API Design

- Status: **Partially implemented.** Authentication, account administration and the first
  protected read endpoints exist in `services/api`; section 0 lists them and where they differ
  from this design. Where they disagree, **section 0 is authoritative**.
- Style: REST over HTTPS + one WebSocket gateway; OpenAPI 3.1 is the contract
  (exported to `packages/contracts/openapi.json`)
- Related: [ARCHITECTURE.md §3](ARCHITECTURE.md#3-backend-architecture), [SECURITY_ARCHITECTURE.md](SECURITY_ARCHITECTURE.md)

## 0. Implemented endpoints (as built)

All under `/api/v1`. "Guard" is the route-level check; resource policies then decide per record
(see [SECURITY_ARCHITECTURE.md §0.2](SECURITY_ARCHITECTURE.md#02-roles-permissions-and-policies)).
Interactive docs at `/docs` in development and test only.

| Method & path | Guard | Purpose |
|---------------|-------|---------|
| `GET /health/live` **PUBLIC** | none | Liveness probe |
| `POST /auth/register` **PUBLIC** | rate limit | Student self-registration (institutional e-mail, `accept_terms: true`); always `202` |
| `POST /auth/verify-email` **PUBLIC** (token) | rate limit | Activates a registered account |
| `POST /auth/login` **PUBLIC** | rate limit | Returns `{access_token, token_type, expires_in, csrf_token, user}` and sets the refresh cookie |
| `POST /auth/refresh` **PUBLIC** (refresh cookie + `X-CSRF-Token`) | rate limit | Rotates the refresh token, returns a new token pair |
| `POST /auth/logout` | `authenticated` | Revokes this session, clears the cookie; `204` |
| `POST /auth/password/forgot` **PUBLIC** | rate limit | Always `202` |
| `POST /auth/password/reset` **PUBLIC** (token) | rate limit | Completes a reset or first-time account setup; signs out every session |
| `GET /me` | `profile:read:own` | Own profile, role and permission list |
| `GET /me/wellness/mood-entries` | `wellness:read:own` | Own mood entries (with own private note) |
| `GET /me/appointments?upcoming=` | `appointment:read:own` | Own appointments (`upcoming=true`: live and in the future; `false`: already started) |
| `POST /me/check-ins?tz=` | `wellness:write:own` | One-step daily check-in: mood (required) plus optional energy, emotions, private note, daily stress and last night's sleep. Returns the saved entries, `support` (kind words) and `safety` when the safety system found a concern in the note or the numbers: level, guidance, ordered contacts, counsellor links, what happened about asking a person and whether suggestions are paused. A `HIGH` or `IMMEDIATE` note can alert a person within the consent rules ([SAFETY_SYSTEM.md](SAFETY_SYSTEM.md)) |
| `POST /me/wellness/mood-entries` | `wellness:write:own` | A mood entry on its own |
| `GET`, `POST /me/wellness/stress-entries` | `wellness:read:own` / `wellness:write:own` | Own stress entries (scale `daily_stress_check`) |
| `GET`, `PUT /me/wellness/sleep-entries` | `wellness:read:own` / `wellness:write:own` | Own sleep entries; `PUT` upserts one entry per wake date |
| `GET /me/wellness/summary?tz=` | `wellness:read:own` | Today's mood, stress and sleep with plain-language indicators and week-on-week direction; check-in streak |
| `GET /me/wellness/trends?days=&tz=` | `wellness:read:own` | Daily points for 7 to 90 days (days with nothing logged are `null`) |
| `GET /me/wellness/indicators?tz=` | `wellness:read:own` | AI wellness indicators from the last 28 days of check-ins: stress level, burnout risk, social isolation, sleep and lifestyle, career worry and the tone of own notes. Each is a band (`low`/`moderate`/`elevated`) or `not_enough_data`, with `model_version` and a disclaimer; no raw scores. `503` when the AI service or its models are unavailable. Models trained on synthetic data, not a diagnosis ([ADR 0011](adr/0011-wellness-indicator-models.md)) |
| `GET /me/dashboard?tz=` | `wellness:read:own` | Summary + next appointment + last 7 days + current recommendations in one call, plus `safety` while suggestions are paused |
| `GET /me/wellness/assessment`, `GET`, `POST /me/wellness/assessments` | `wellness:read:own` / `wellness:write:own` | The WHO-5 well-being instrument, own results, and submitting answers (scored on the server; wording is "Doing well / Mixed / Lower lately", never diagnostic) |
| `GET`, `POST /me/goals`, `PATCH /me/goals/{id}` | `goal:manage:own` | Own wellness goals: progress, pause, complete, let go |
| `GET /me/recommendations?include_closed=`, `POST /me/recommendations/refresh?tz=`, `PATCH /me/recommendations/{id}` | `recommendation:manage:own` | Personalised, non-medical suggestions with a stated reason, problem area and next step (`resource`, `book_counselling`, `set_goal`, `check_in`); mark viewed, done or dismissed ([ADR 0012](adr/0012-personalised-recommendation-engine.md)). While a safety concern pauses suggestions, only a therapist's suggestions are listed and refresh creates none |
| `GET /me/recommendations/history?limit=&offset=` | `recommendation:manage:own` | Every suggestion so far, newest first, with the student's own rating |
| `PUT`, `DELETE /me/recommendations/{id}/feedback` | `recommendation:manage:own` | Say `helpful` or `not_helpful` (optional `reason` from a fixed list, only with `not_helpful`); saying it again replaces it, DELETE takes it back. Student only: no other role can read it |
| `GET`, `PATCH /me/recommendations/preferences` | `recommendation:manage:own` | Preferred formats, longest time, topics to switch off, and whether indicators may be used |
| `GET /resources`, `GET /resources/{id}` | `resource:read` | Published resources of the institution |
| `GET /therapists`, `GET /therapists/{id}`, `GET /therapists/{id}/slots` | `therapist_directory:read` | Therapist directory (name, focus areas, languages, bio, next opening) and bookable slots; no clinical data |
| `POST /me/appointments`, `PATCH /me/appointments/{id}` | `appointment:book:own` | Request a slot (`requested`, max 3 upcoming, at least 2 hours ahead, reason is encrypted); cancel before it starts, with an optional `reason` from a fixed list. Appointments carry `can_reschedule`, `reschedule_count`, `rescheduled_at`, `cancel_reason` and `session_status` (the delivered session once the therapist starts it) |
| `POST /me/appointments/{id}/reschedule` | `appointment:book:own` | `{availability_id}`: move to another open time of the same therapist, at least 2 hours ahead, at most 3 times; it goes back to `requested`. `409` for a taken time or the limit, `404` for another therapist's time ([ADR 0009](adr/0009-therapist-communication-real-time-and-notifications.md)) |
| `GET /me/conversations`, `GET`, `POST /me/conversations/{therapist_id}/messages`, `POST /me/conversations/{therapist_id}/read` | `message:participate:own` | One-to-one messages with a care-team therapist; `client_msg_id` makes retries idempotent. Writing needs an active care link; a student can still read their own history after it ends (the therapist cannot). A student's sent message returns `safety` when it raises a concern, and `HIGH` or above alerts their care team. Teachers and administrators get `403` |
| `GET /me/notifications?unread=&before=&limit=`, `GET /me/notifications/unread-count`, `POST /me/notifications/{id}/read`, `POST /me/notifications/read-all` | `profile:read_own` | Every role's own notifications (`{items, unread}`; limit up to 100). Titles are fixed phrases, payloads ids and fixed event names only. Someone else's notification is `404` |
| `WS /ws` | First frame `{"type":"auth","token"}` | Real-time hints for the signed-in user: `notification`, `notifications_read`, `message`, `message_read`, `appointment` (ids only). See section 4 |
| `GET /me/consents`, `PUT /me/consents/{scope}` | `consent:manage:own` | Consent state per scope, in plain language; the required scope cannot be withdrawn; takes effect immediately |
| `GET /me/privacy/access-history`, `GET /me/privacy/export` | `privacy:read:own` | Role-level list of others' successful reads of the student's data; full data export (excludes therapy notes) |
| `POST /me/support-requests` | `support_request:create` | "Please have a person reach out": creates a human-handled alert, rate limited to one open request |
| `GET /me/safety/resources` | `privacy:read:own` | Crisis contacts (national and campus) for the student's institution |
| `GET /me/safety/status` | `support_request:create` | Whether ordinary suggestions are paused after a `HIGH` or `IMMEDIATE` concern, the support to show meanwhile, and the disclaimer. Students only ([ADR 0013](adr/0013-safety-and-escalation-system.md)) |
| `GET /me/ai-conversations` | `ai_conversation:read:own` | Own companion conversations (metadata only) |
| `GET /students` | `student:read:assigned` | Therapist's current care-team students (older route, kept; requires a verified therapist) |
| `GET /students/{id}/mood-entries` | `wellness:read:assigned` | Consented mood entries of an assigned student, without the private note; audited |
| `GET /students/{id}/therapy-notes` | `therapy_note:read` | Notes this therapist wrote about an assigned student; audited |
| `GET /therapist/dashboard?tz=` | `therapist_profile:manage` | Verification status, caseload, today's appointments, waiting requests, open alerts by severity, follow-ups due, unread messages. Works for an unverified therapist (counts are zero) |
| `GET`, `PATCH /therapist/profile` | `therapist_profile:manage` | Own profile (bio, focus areas, languages, accepting new students, caseload cap) and verification status |
| `POST /therapist/verification` | `therapist_profile:manage` | Submit licence number, body and expiry; sets the status back to `pending`. A therapist cannot verify themself |
| `GET`, `POST /therapist/availability`, `DELETE /therapist/availability/{id}` | `therapist_profile:manage` | Own bookable times (optional weekly repeat); a booked time cannot be removed |
| `GET /therapist/appointments?scope=requests\|upcoming\|past\|all` | `appointment:manage` | Own appointments with `can_start`, `session_id`, `can_reschedule`, `reschedule_count`, `rescheduled_at` and `cancel_reason` |
| `POST /therapist/appointments/{id}/reschedule` | `appointment:manage` | `{availability_id}` of the therapist's own open times; keeps the status and notifies the student. Same limits as the student's |
| `PATCH /appointments/{id}` | `appointment:manage` | Confirm, cancel (optional `cancel_reason`, only with `cancelled`, `422` otherwise), complete or mark no-show. Confirming a first appointment creates the care-team link; the student is notified (ids-only payload). Starting a session notifies the student too |
| `GET /therapist/students`, `GET /therapist/students/{id}` | `student:read:assigned` | Caseload and the authorized profile. **Verified therapist and active care link required** (`404` otherwise). The profile reports which consents are active |
| `GET /therapist/students/{id}/trends?days=&tz=` | `wellness:read:assigned` | Mood, stress and sleep points; needs the `share_mood_with_care_team` consent (`403` without it); no private notes |
| `GET /therapist/students/{id}/indicators?tz=` | `wellness:read:assigned` | The same indicators without the tone of notes (notes are not read or sent); needs a care link (`404`) and the `share_ai_signals_with_care_team` consent (`403`); audited with counts only; `503` when the AI service is unavailable |
| `GET /therapist/students/{id}/assessments` | `wellness:read:assigned` | WHO-5 results; needs the `share_assessments_with_care_team` consent |
| `GET`, `POST /therapist/students/{id}/recommendations` | `recommendation:create:assigned` | Suggestions this therapist made; creating one shows it to the student as "From your therapist" and notifies them |
| `GET /therapist/sessions?status=` | `session:manage` | Own sessions (only for students currently on the care team) |
| `POST /therapist/appointments/{id}/session`, `PATCH /therapist/sessions/{id}` | `session:manage` | Start (from 15 minutes before until a day after the end; idempotent) and complete or abandon a session |
| `GET`, `PUT /therapist/sessions/{id}/note` | `therapy_note:read` / `therapy_note:write` | The therapy note: **author only**, versioned (`PUT` adds a version, earlier ones are locked, `?version=` reads one), `Cache-Control: no-store, private`, audited by version number only |
| `GET /therapist/alerts?closed=`, `PATCH /therapist/alerts/{id}` | `risk_alert:manage:assigned` | Alerts assigned to me, or unassigned for students on my care team; acknowledge (claims an unassigned one), start, resolve with a fixed outcome. Free text is never stored |
| `GET`, `POST /therapist/follow-ups`, `PATCH /therapist/follow-ups/{id}` | `follow_up:manage` | Private reminders (kind, due date, encrypted note) about care-team students |
| `GET /admin/therapists?status=`, `PATCH /admin/therapists/{id}/verification` | `therapist:verify` | Administrators review and set `verified` or `rejected` (with a short note) within their own institution; an administrator cannot be the subject |
| `GET /insights/mood-summary?department_id=` | `insights:read:aggregate` | Department cohort size and average mood over the last 4 completed calendar weeks (the week in progress is excluded); suppressed under 10 consenting students; average to one decimal |
| `GET /teacher/dashboard` | `class_insights:read:own` | Teacher's classes, department figures (when authorized), open student requests and referral counts. Group figures are suppressed below 10 consenting students |
| `GET /teacher/classes`, `GET /teacher/classes/{id}`, `GET /teacher/classes/{id}/students` | `class_insights:read:own` | Own classes only (`404` otherwise). The roster is names the teacher already has from teaching the class; it carries **no** wellbeing data |
| `GET /teacher/classes/{id}/analytics?weeks=4\|8\|12`, `GET /teacher/departments/{id}/analytics?weeks=` | `class_insights:read:own` | Aggregated wellness, energy, stress, sleep, check-in participation, academic-stress and strain shares, stressor mix and group-level supportive actions, for the last 4, 8 or 12 **completed** calendar weeks (the week in progress is never included). Only consenting students count; thresholds in [ADR 0007](adr/0007-teacher-portal-aggregation-thresholds-and-referrals.md). Department views need the teacher to belong to that department (`403`) |
| `GET /teacher/classes/{id}/report`, `/report.csv`, `GET /teacher/departments/{id}/report`, `/report.csv` | `class_insights:read:own` | Anonymous wellness report for the same figures: text and CSV made only of numbers and fixed words |
| `GET`, `POST /teacher/referrals`, `GET /teacher/referrals/{id}` | `referral:manage:own` | A teacher refers a student they teach (category, urgency, optional note). One live referral per teacher and student (`409`), 10 per day. The teacher reads back only category, urgency, own note and status |
| `GET /teacher/support-requests`, `POST /teacher/support-requests/{id}/acknowledge`, `.../close` | `teacher_support:manage:own` | Requests students explicitly sent to this teacher |
| `GET /teacher/resources`, `GET /teacher/resources/{id}` | `faculty_resource:read` | Resources tagged `faculty` (teachers and administrators only) |
| `GET /me/teacher-support/options`, `GET`, `POST /me/teacher-support`, `POST /me/teacher-support/{id}/withdraw` | `teacher_support:request` | A student asks one of their own teachers for support: picks the class and teacher, and what would help. Five a day, one live request per teacher and class; withdraw any time |
| `GET /therapist/referrals?status=`, `GET /therapist/referrals/{id}`, `POST .../claim`, `POST .../close` | `referral:triage` | Verified therapists triage teacher referrals about care-team students or students with no care team; a claimed referral is visible to its claimer only. Claiming sends the student a content-free notification; `safety_concern` also raises a high-severity alert for humans |
| `GET /admin/dashboard` | `platform_analytics:read` | Account counts by role and status, therapists waiting for verification, licences expiring within 30 days, draft resources, safety alerts waiting or past the response time, and refused requests in the last 7 days. Counts only |
| `GET /admin/users?role=&status=&q=`, `POST /admin/users` | `user:manage` | Page (`{items, total}`) / create (invited, any role) users of the admin's institution. Creating a student, teacher or therapist also creates their profile |
| `GET`, `PATCH /admin/users/{id}` | `user:manage` | `{status: active, suspended, deactivated}`; non-active revokes sessions. An administrator cannot change their own status (`403`) |
| `POST /admin/users/{id}/resend-invite`, `POST /admin/users/{id}/sign-out` | `user:manage` | Send an account-setup link again to someone who has not set up; revoke all of a user's sessions |
| `GET /admin/students`, `GET`, `PATCH /admin/students/{id}` | `student_record:manage` | Student **administrative** record: department, student number, year, status. No wellbeing, consent, care-team or appointment data is returned |
| `GET /admin/teachers`, `PATCH /admin/teachers/{id}` | `teacher_record:manage` | Teacher record: department, title, employee number, number of courses |
| `GET /admin/therapist-accounts`, `PATCH /admin/therapist-accounts/{id}` | `therapist_record:manage` | Therapist record: licence number, caseload limit, verification state and a **head count** of students (never which) |
| `GET`, `POST /admin/departments`, `PATCH`, `DELETE /admin/departments/{id}` | `department:manage` | Departments with member counts. Deleting needs an empty department (`409` otherwise) |
| `GET`, `POST /admin/courses`, `GET`, `PATCH`, `DELETE /admin/courses/{id}` | `course:manage` | Courses (`409` for a duplicate code and term, or deleting one with enrolment history) |
| `PUT`, `DELETE /admin/courses/{id}/teachers/{tid}`, `PUT`, `DELETE /admin/courses/{id}/students/{sid}` | `course:manage` | Assign or remove a teacher; enrol or drop a student (idempotent). Both change a class's anonymous figures straight away |
| `GET /admin/analytics?weeks=4\|8\|12` | `platform_analytics:read` | Institution wellbeing figures (the teacher privacy rules, [ADR 0007](adr/0007-teacher-portal-aggregation-thresholds-and-referrals.md)), weekly appointments and alerts, accounts by role. Weekly counts of 1 to 4 are returned as `null` ("fewer than 5") |
| `GET /admin/appointments/oversight?weeks=` | `appointment:oversee` | Appointments by outcome, scheduled per week, confirmed in the next 7 days, requests waiting over 2 days, and per-therapist workload. Counts only; no student, time slot or content |
| `GET`, `POST /admin/resources`, `GET`, `PUT`, `DELETE /admin/resources/{id}`, `PATCH .../publication` | `resource:manage` | The self-help library. Shipped (`global`) resources are readable but not editable (`403`). Publishing records the reviewing administrator and time; links must be `https://` |
| `GET /admin/config`, `PATCH /admin/config` | `config:manage` | Institution name and e-mail domains |
| `GET`, `PATCH /admin/settings/notifications` | `notification_config:manage` | Reminder switch and hours (1 to 3 values of 1 to 168), therapist-suggestion notifications, goal reminders, email. Also returns the `fixed_rules` that cannot be changed. Appointment reminders are sent by the scheduler when it runs (`SCHEDULER_ENABLED`); email deliveries are created when switched on and sent once a provider is configured (`skipped` until then); goal reminders are stored but not yet used |
| `GET`, `PATCH /admin/settings/safety` | `safety_config:manage` | `alert_ack_minutes` (5 to 1 440): the response time given to new alerts. Used when an alert is raised |
| `GET`, `POST /admin/settings/crisis-contacts`, `PATCH`, `DELETE .../{id}` | `safety_config:manage` | The institution's crisis contacts. Shipped contacts are read only; the last active emergency contact cannot be hidden or removed (`409`) |
| `GET /admin/audit?action=&outcome=&actor_id=&resource_type=&since=&until=&before_seq=&limit=` | `audit:read` | Audit metadata for the institution, newest first. A range is at most 366 days. Reading the log is audited |
| `GET /admin/audit/actions`, `POST /admin/audit/verify`, `GET /admin/audit/export` | `audit:read` | Distinct action names; verify the hash chain; CSV of the filtered log (at most 5 000 rows, metadata only) |

Status codes as built: `401` missing, invalid, expired or revoked token (with
`WWW-Authenticate: Bearer`) and every failed login; `403` the role lacks the permission, or a
policy denies a record the caller may know exists (for example a therapist without consent);
`404` the record is missing, belongs to another institution, or the caller has no relationship to
it; `409` invalid transition or duplicate; `422` validation, weak password, unknown e-mail domain;
`429` rate limited.

| Area | Design said | Implemented |
|------|-------------|-------------|
| Auth transport | Session cookies, CSRF header on all unsafe methods | Bearer access token; refresh cookie and CSRF header on `/auth/refresh` only ([ADR 0003](adr/0003-access-token-transport-and-session-checks.md)) |
| Locked account | `423` | `401`, identical to other login failures |
| Invitations | `POST /users/invitations`, `POST /auth/invitations/accept` | `POST /admin/users` sends an account-setup link; the user completes it with `POST /auth/password/reset` |
| User admin paths | `/users`, `/users/{id}/deactivate` | `/admin/users`, `PATCH /admin/users/{id}` with a status |
| Institution settings | `/admin/institution` | `/admin/config`; notification, safety and crisis-contact settings under `/admin/settings/...` |
| Administrator portal | `/admin/health`, `/admin/settings/safety` (companion switch) | Everything an administrator does is under `/admin/...`, guarded by one permission per area. No admin route returns individual wellbeing, therapy, message or companion content ([ADR 0008](adr/0008-administrator-portal-scope-and-confidentiality.md)) |
| Therapist views | Nested under `/checkins`, `/session-notes` | Everything a therapist does is under `/therapist/...`; the older `/students*` routes remain for now. Student data needs a **verified** therapist, an **active care link**, and (for check-ins and wellbeing checks) the student's **consent**. Conversations reuse `/me/conversations` |
| Teacher portal | `/referrals` for faculty, `/analytics` | Everything a teacher does is under `/teacher/...`; referral triage is under `/therapist/referrals`. Group figures use fixed 4/8/12 completed-week windows, size bands and rounded shares ([ADR 0007](adr/0007-teacher-portal-aggregation-thresholds-and-referrals.md)). The legacy `GET /insights/mood-summary` uses the same completed-week window and rounding, and counts only students who consented |
| Student portal | `/checkins`, `/journal`, `/threads`, `/consent`, `/privacy`, `/safety` | Everything a student does is under `/me/...` with no student id in the path, so the caller can only ever address their own data (`403/404` tests cover other students' ids on the staff routes). Check-in is `POST /me/check-ins`; messages are keyed by the other person; consent is `/me/consents`. Time zone comes from `?tz=` (IANA) per request |
| Pagination | Cursor | `limit` (max 200); audit uses `before_seq` as its cursor |
| Not built yet | MFA, step-up, `/auth/sessions`, `/health/ready`, idempotency keys, ETags, everything outside the table above | Later phases |

## 1. Conventions

| Topic | Convention |
|-------|-----------|
| Base path | `/api/v1` (additive changes only within a version) |
| Format | JSON, `snake_case` fields, ISO 8601 UTC timestamps, UUID ids |
| Auth | httpOnly cookie session (browser) or `Authorization: Bearer` for service clients; CSRF header `X-CSRF-Token` on unsafe methods |
| Authorization | Every route declares `require_permission(...)` plus a resource policy. Routes marked **PUBLIC** are listed explicitly and tested |
| Pagination | Cursor-based: `?limit=50&cursor=...` → `{ "items": [], "next_cursor": null }` |
| Filtering/sorting | Allow-listed query params per route |
| Idempotency | `Idempotency-Key` header required on `POST` that creates checkins, messages, appointments, escalations, referrals |
| Errors | RFC 9457 `application/problem+json`: `type`, `title`, `status`, `detail`, `request_id`, optional `errors[]` |
| Rate limits | `429` with `Retry-After`; classes: auth (strict), ai (strict), write (moderate), read (lenient) |
| Concurrency | `ETag` / `If-Match` on mutable resources (session notes, profile) |
| Tracing | `X-Request-ID` echoed on every response |
| Content safety | Responses never include free text of users the caller may not read; fields are omitted, not nulled, when not permitted |
| Disclaimers | AI-derived payloads include `disclaimer` and `model_version` fields |

### 1.1 Standard error codes

| Status | Meaning |
|--------|---------|
| 400/422 | Validation error |
| 401 | Missing/expired authentication |
| 403 | Authenticated but not permitted (also audited for sensitive resources) |
| 404 | Not found **or** not visible to caller (avoids existence leaks) |
| 409 | Conflict (slot already booked, version mismatch) |
| 423 | Account locked / step-up authentication required (`type: step_up_required`) |
| 429 | Rate limited |
| 503 | Dependency unavailable; crisis endpoints never return this for the resources payload |

## 2. Endpoint catalogue

Legend for **Who**: `S` student, `T` therapist, `F` faculty, `A` institution admin,
`PA` platform admin, `own` own resource, `ct` care team relationship, `cons` consent required.

### 2.1 Auth and session (`/auth`)

| Method & path | Who | Purpose |
|---------------|-----|---------|
| `POST /auth/login` **PUBLIC** | any | Email + password; returns `mfa_required` or sets session cookies |
| `POST /auth/mfa/verify` **PUBLIC** (mfa_token) | any | Complete login with TOTP/WebAuthn |
| `POST /auth/refresh` **PUBLIC** (refresh cookie) | any | Rotate refresh token |
| `POST /auth/logout` | any | Revoke current session |
| `POST /auth/password/forgot` **PUBLIC** | any | Always returns 202 (no account enumeration) |
| `POST /auth/password/reset` **PUBLIC** (token) | any | Complete reset |
| `POST /auth/invitations/accept` **PUBLIC** (token) | invited | Set password and activate |
| `POST /auth/register` **PUBLIC** | student | Self-registration with verified institutional email |
| `GET /auth/sessions` / `DELETE /auth/sessions/{id}` | own | List/revoke devices |
| `POST /auth/mfa/enroll`, `POST /auth/mfa/disable` | own | Manage MFA (step-up) |
| `POST /auth/step-up` | any | Re-authenticate for sensitive actions |

### 2.2 Users and profiles (`/users`, `/me`)

| Method & path | Who | Purpose |
|---------------|-----|---------|
| `GET /me` | any | Own profile, role, permissions, consent summary |
| `PATCH /me` | own | Update profile and preferences |
| `GET /users` | A | List/filter institution users (no clinical fields) |
| `POST /users/invitations` | A | Invite therapist/faculty/admin or bulk-invite students |
| `PATCH /users/{id}` | A | Change role/status; step-up required |
| `POST /users/{id}/deactivate` | A | Deactivate account |
| `GET/POST/DELETE /care-team` | A | Manage therapist-student assignments |
| `GET /therapists` | S | Browse therapists accepting students (public profile fields) |

### 2.3 Wellbeing (`/checkins`, `/journal`)

| Method & path | Who | Purpose |
|---------------|-----|---------|
| `POST /checkins` | S own | Submit check-in; response includes `crisis_resources` when flagged |
| `GET /checkins` | S own; T ct+cons | List with date range |
| `GET /checkins/summary` | S own; T ct+cons | Trend summary (mood, stress, sleep) |
| `GET /journal` / `POST /journal` | S own | List/create entries |
| `GET/PATCH/DELETE /journal/{id}` | S own | Read/edit/delete |
| `POST /journal/{id}/shares` / `DELETE /journal/{id}/shares/{share_id}` | S own | Share a single entry with a care-team therapist, or revoke |
| `GET /journal/shared` | T ct | Entries the student explicitly shared |

### 2.4 AI companion (`/companion`)

Built in Phase 6 ([ADR 0010](adr/0010-ai-wellness-companion-and-safety-layer.md)).

| Method & path | Who | Purpose |
|---------------|-----|---------|
| `GET /companion/status` | S | Whether the companion is on, today's allowance, retention and the disclaimer |
| `POST /companion/conversations` | S | Start a conversation (`ai_companion:use:own`) |
| `POST /companion/conversations/{id}/messages` | S own | Send a message (at most 2,000 characters) and get the whole reply back (not streamed). Crisis rules run first; a crisis returns a fixed reply, `support.level="crisis"` with contacts, and raises an alert. 429 with `Retry-After` over a limit, 503 when switched off or not configured, 409 while a reply is pending |
| `GET /companion/conversations` / `/{id}` | S own | Conversations and messages that have not expired |
| `DELETE /companion/conversations/{id}` | S own | Delete immediately (204) |
| `POST /companion/messages/{id}/report` | S own | Report a bad response (not built yet) |

Teachers, therapists and admins have **no** companion access.

### 2.5 Insights (`/insights`)

| Method & path | Who | Purpose |
|---------------|-----|---------|
| `GET /insights/me` | S | Own plain-language insights with factors and disclaimers |
| `GET /insights/students/{id}` | T ct+cons | Support-need band, factors, confidence, model version, disclaimer |
| `GET /insights/students/{id}/prep` | T ct+cons | Session-prep summary of consented data |
| `GET /resources` / `/resources/recommended` | S | Vetted resource library and recommendations |

### 2.6 Appointments and notes (`/appointments`, `/availability`, `/session-notes`)

| Method & path | Who | Purpose |
|---------------|-----|---------|
| `GET/PUT /availability` | T own | Manage availability |
| `GET /therapists/{id}/slots` | S | Open slots |
| `POST /appointments` | S | Book a slot (idempotent; 409 if taken) |
| `GET /appointments` | S own; T own; A metadata | List |
| `PATCH /appointments/{id}` | S own; T own | Reschedule/cancel/confirm/complete |
| `POST /appointments/{id}/video-token` | S, T participants | Short-lived join token (≤ 15 min) |
| `PUT /appointments/{id}/note` | T author | Create/update note (ETag, versioned) |
| `GET /appointments/{id}/note` | T author; supervisor with grant | Read note (**audited**, step-up for bulk access) |
| `GET /session-notes` | T author | List own notes metadata |

### 2.7 Messaging (`/threads`)

| Method & path | Who | Purpose |
|---------------|-----|---------|
| `GET /threads` | S own; T ct | List threads |
| `GET /threads/{id}/messages` | participants | Paginated messages (**audited**) |
| `POST /threads/{id}/messages` | participants | Send (idempotent; crisis-checked if sender is a student) |
| `POST /threads/{id}/read` | participants | Mark read |
| `POST /threads/{id}/attachments` | participants | Get pre-signed upload URL; scanned before delivery |

### 2.8 Referrals (`/referrals`)

| Method & path | Who | Purpose |
|---------------|-----|---------|
| `POST /referrals` | F, T | Create concern referral (urgent safety concern auto-creates escalation) |
| `GET /referrals` | F own (status only); T triage team (full); A metadata | List |
| `GET /referrals/{id}` | as above | Faculty receive `status` and `updated_at` only |
| `PATCH /referrals/{id}` | T triage | Triage, assign, close |

### 2.9 Safety and escalations (`/safety`, `/escalations`)

| Method & path | Who | Purpose |
|---------------|-----|---------|
| `GET /safety/resources` **PUBLIC** | anyone | Crisis resources for institution (by `institution` param or domain); cacheable; mirrored in static `/help` |
| `POST /safety/help-requests` | S (also **PUBLIC** fallback with rate limit) | "Get help now": creates escalation and returns resources immediately |
| `GET /escalations` | T on-call/ct | Queue with SLA timers |
| `GET /escalations/{id}` | T ct/on-call; A metadata | Detail (**audited**) |
| `POST /escalations/{id}/acknowledge` | T | Acknowledge (stops SLA timer) |
| `POST /escalations/{id}/events` | T | Add contact attempt/note |
| `POST /escalations/{id}/resolve` | T | Record outcome |
| `POST /escalations/{id}/break-glass` | T supervisor | Time-boxed extra visibility with reason |
| `GET/PUT /on-call/rotas` / `/shifts` | A | Manage rota and escalation policy |
| `GET/PUT /safety/resources/admin` | A | Manage helplines |

### 2.10 Notifications (`/notifications`)

| Method & path | Who | Purpose |
|---------------|-----|---------|
| `GET /notifications` | own | Inbox |
| `POST /notifications/{id}/read` | own | Mark read |
| `GET/PUT /notifications/preferences` | own | Channels, quiet hours |
| `POST /notifications/push-subscriptions` | own | Register web push |

### 2.11 Consent and privacy (`/consent`, `/privacy`)

| Method & path | Who | Purpose |
|---------------|-----|---------|
| `GET /consent` | own | Current consent state and policy versions |
| `PUT /consent/{scope}` | own | Grant or revoke (append-only record) |
| `GET /privacy/access-history` | own | Who accessed my data (role-level) |
| `POST /privacy/exports` / `GET /privacy/exports/{id}` | own | Async data export |
| `POST /privacy/erasure-requests` | own | Request deletion |

### 2.12 Analytics (`/analytics`)

| Method & path | Who | Purpose |
|---------------|-----|---------|
| `GET /analytics/cohorts` | F own cohorts, A | Aggregates; suppressed cells returned as `null` with `suppressed: true` |
| `GET /analytics/caseload` | T | Aggregates over own caseload (no cross-patient drill-down beyond care team) |
| `GET /analytics/operations` | A | Response times, usage |

### 2.13 Admin and audit (`/admin`)

| Method & path | Who | Purpose |
|---------------|-----|---------|
| `GET /admin/audit` | A | Search audit events (metadata, never content) |
| `GET/PATCH /admin/institution` | A | Institution settings |
| `GET /admin/health` | A, PA | Queue depth, notification failures, ML status |
| `PATCH /admin/settings/safety` | A | Includes `companion_enabled` (the institution's switch) and `companion_daily_messages` (10 to 500) |

### 2.14 Health (`/health`)

| Method & path | Who | Purpose |
|---------------|-----|---------|
| `GET /health/live`, `GET /health/ready` **PUBLIC** | infra | Probes, no sensitive info |

### 2.15 Internal ML API (service-to-service only, not exposed publicly)

| Method & path | Caller | Purpose |
|---------------|--------|---------|
| `POST /internal/v1/crisis/detect` | api | Text → `{crisis, category, confidence, requires_human, rules_hit}` |
| `POST /internal/v1/signals/support-need` | worker | Feature vector → band + factors |
| `POST /internal/v1/indicators` | api | **Built.** `{window_end, days[], notes[]}` → five check-in indicators plus note tone, each `{indicator, title, meaning, status, band, level, probabilities, model_version}`, with `checkin_days`, `notes_considered` and the disclaimer. `503` when models are missing or fail verification |
| `POST /internal/v1/sentiment` | api | **Built.** `{texts[]}` (1 to 50, 2,000 characters each) → `{label, probabilities}` per text, `model_version`, disclaimer |
| `POST /internal/v1/companion/respond` | api | **Built.** `{message, history}` → `{kind, reply, crisis, topic, flags, model_version}`; `kind` is `reply`, `crisis` (no reply: the API answers), `redirect`, `fallback` or `unavailable`. Not streamed |
| `GET /internal/v1/models` | api | **Built.** Model, prompt and crisis-rules versions, and indicator model versions (or why they are unavailable) |
| `GET /internal/v1/health` | infra | **Built.** Liveness, no authentication, no details |

Auth: signed service token (HS256 JWT with `aud=mindmitra-ml`, `iss=mindmitra-api`, 5 min, secret `ML_SERVICE_TOKEN`) + private network only. The ML service
**does not persist request text**.

## 3. Representative payloads

### 3.1 Submit check-in

```http
POST /api/v1/checkins
Idempotency-Key: 7f0c...
{
  "mood": 2, "stress": 4, "sleep_quality": 2, "energy": 2,
  "note": "Exams are overwhelming and I can't sleep"
}
```

```json
{
  "id": "0192...",
  "created_at": "2026-10-08T17:50:00Z",
  "acknowledgement": "Thanks for checking in. It sounds like things are heavy right now.",
  "suggested_resources": [{ "id": "…", "title": "Winding down before sleep" }],
  "crisis": null
}
```

When crisis indicators fire:

```json
{
  "id": "0192...",
  "acknowledgement": "Thank you for sharing this. You do not have to handle this alone.",
  "crisis": {
    "resources": [
      { "kind": "helpline", "name": "…", "contact": "…", "hours": "24/7" },
      { "kind": "campus_emergency", "name": "Campus security", "contact": "…" }
    ],
    "message": "A member of our care team has been notified and may reach out.",
    "escalation_id": null
  }
}
```

`escalation_id` is intentionally not returned to students; it is for therapists.

### 3.2 Therapist view of an AI signal

```json
{
  "student_id": "0191...",
  "signal_type": "support_need",
  "band": "elevated",
  "confidence": 0.71,
  "factors": [
    { "name": "sleep_quality_trend", "direction": "declining", "window_days": 14 },
    { "name": "check_in_gap", "direction": "increasing" }
  ],
  "model_version": "support-need-gbm-0.3.0",
  "disclaimer": "This is a statistical wellness signal, not a diagnosis. It can be wrong. Use your professional judgement."
}
```

### 3.3 Faculty referral status (what a teacher can see)

```json
{ "id": "0193...", "status": "in_progress", "updated_at": "2026-10-09T08:00:00Z" }
```

No student name beyond what the teacher submitted, no clinician identity, no outcome detail.

### 3.4 Problem response

```json
{
  "type": "https://mindmitra.example/problems/forbidden",
  "title": "Forbidden",
  "status": 403,
  "detail": "You do not have access to this resource.",
  "request_id": "req_01J..."
}
```

## 4. Real-time interface (WebSocket)

As built ([ADR 0009](adr/0009-therapist-communication-real-time-and-notifications.md)):
`/api/v1/ws`, one socket per tab, server-to-client events only.

1. Connect; the `Origin` must be an allowed web origin (close `4403`).
2. Within 10 seconds send `{"type":"auth","token":"<access token>"}` (close `4401` otherwise).
   The token never goes in the URL. At most five sockets per person (close `4429`).
3. The server answers `{"type":"ready"}`, then sends this user's events. `{"type":"ping"}` gets
   `{"type":"pong"}`. The session is re-checked every minute (close `4401` when it has ended); a
   client that falls 100 events behind is closed with `1013`.

| Event | Payload (ids and fixed words only) | Sent to |
|-------|------------------------------------|---------|
| `notification` | `id`, `notification_type`, `title` (a fixed phrase) | the recipient |
| `notifications_read` | none | the reader's other tabs |
| `message` | `with` (the other person's user id), `message_id` | the recipient and the sender's other tabs |
| `message_read` | `with` | the sender (read receipt) and the reader's other tabs |
| `appointment` | `appointment_id`, `event` (`requested`, `confirmed`, `cancelled`, `cancelled_by_student`, `rescheduled_by_student`, `rescheduled_by_therapist`, `completed`, `no_show`, `session_started`, `session_completed`, `session_abandoned`) | the student and the therapist |

Events are published only after the transaction commits. Message bodies, names and times are
never pushed; clients fetch through REST, which applies the usual checks. The hub is in-process:
several API instances need a shared broker behind `EventBroker`.

## 5. Authorization mapping

Each route is declared in code with explicit metadata, which also generates the test matrix:

```python
# illustrative only, not final code
@router.get("/checkins", dependencies=[require_permission("checkin:read")])
async def list_checkins(...): ...
```

CI checks:

1. Every route has `require_permission(...)` or is in the explicit `PUBLIC_ROUTES` allow-list.
2. The authorization test matrix runs every route × every role (incl. unauthenticated, other
   tenant, unassigned therapist) and compares with the expected table above.
3. OpenAPI diff check fails on breaking changes inside `/v1`.

## 6. Versioning and compatibility

- `/api/v1` additive-only; breaking changes ship as `/api/v2` with a deprecation window.
- Generated TypeScript client in `packages/contracts` is rebuilt in CI; the web app fails to
  compile if it drifts from the spec.

## 7. Webhooks and third parties

Inbound: SES/SNS delivery receipts (signature-verified, allow-listed IPs). Outbound webhooks
to institutions (e.g. SIS integration) are out of scope for v1 and require an ADR.
