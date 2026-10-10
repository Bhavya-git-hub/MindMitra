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
| `POST /me/check-ins?tz=` | `wellness:write:own` | One-step daily check-in: mood (required) plus optional energy, emotions, private note, daily stress and last night's sleep. Returns the saved entries and `support` (an information-only message, never an alert) when the mood is low |
| `POST /me/wellness/mood-entries` | `wellness:write:own` | A mood entry on its own |
| `GET`, `POST /me/wellness/stress-entries` | `wellness:read:own` / `wellness:write:own` | Own stress entries (scale `daily_stress_check`) |
| `GET`, `PUT /me/wellness/sleep-entries` | `wellness:read:own` / `wellness:write:own` | Own sleep entries; `PUT` upserts one entry per wake date |
| `GET /me/wellness/summary?tz=` | `wellness:read:own` | Today's mood, stress and sleep with plain-language indicators and week-on-week direction; check-in streak |
| `GET /me/wellness/trends?days=&tz=` | `wellness:read:own` | Daily points for 7 to 90 days (days with nothing logged are `null`) |
| `GET /me/dashboard?tz=` | `wellness:read:own` | Summary + next appointment + last 7 days + current recommendations in one call |
| `GET /me/wellness/assessment`, `GET`, `POST /me/wellness/assessments` | `wellness:read:own` / `wellness:write:own` | The WHO-5 well-being instrument, own results, and submitting answers (scored on the server; wording is "Doing well / Mixed / Lower lately", never diagnostic) |
| `GET`, `POST /me/goals`, `PATCH /me/goals/{id}` | `goal:manage:own` | Own wellness goals: progress, pause, complete, let go |
| `GET /me/recommendations`, `POST /me/recommendations/refresh`, `PATCH /me/recommendations/{id}` | `recommendation:manage:own` | Rule-based suggestions with a stated reason; mark viewed, done or dismissed |
| `GET /resources`, `GET /resources/{id}` | `resource:read` | Published resources of the institution |
| `GET /therapists`, `GET /therapists/{id}`, `GET /therapists/{id}/slots` | `therapist_directory:read` | Therapist directory (name, focus areas, languages, bio, next opening) and bookable slots; no clinical data |
| `POST /me/appointments`, `PATCH /me/appointments/{id}` | `appointment:book:own` | Request a slot (`requested`, max 3 upcoming, at least 2 hours ahead, reason is encrypted); cancel up to 2 hours before |
| `GET /me/conversations`, `GET`, `POST /me/conversations/{therapist_id}/messages`, `POST /me/conversations/{therapist_id}/read` | `message:participate:own` | One-to-one messages with a care-team therapist; `client_msg_id` makes retries idempotent |
| `GET /me/consents`, `PUT /me/consents/{scope}` | `consent:manage:own` | Consent state per scope, in plain language; the required scope cannot be withdrawn; takes effect immediately |
| `GET /me/privacy/access-history`, `GET /me/privacy/export` | `privacy:read:own` | Role-level list of others' successful reads of the student's data; full data export (excludes therapy notes) |
| `POST /me/support-requests` | `support_request:create` | "Please have a person reach out": creates a human-handled alert, rate limited to one open request |
| `GET /me/safety/resources` | `privacy:read:own` | Crisis contacts (national and campus) for the student's institution |
| `GET /me/ai-conversations` | `ai_conversation:read:own` | Own companion conversations (metadata only) |
| `GET /students` | `student:read:assigned` | Therapist's current care-team students (older route, kept; requires a verified therapist) |
| `GET /students/{id}/mood-entries` | `wellness:read:assigned` | Consented mood entries of an assigned student, without the private note; audited |
| `GET /students/{id}/therapy-notes` | `therapy_note:read` | Notes this therapist wrote about an assigned student; audited |
| `GET /therapist/dashboard?tz=` | `therapist_profile:manage` | Verification status, caseload, today's appointments, waiting requests, open alerts by severity, follow-ups due, unread messages. Works for an unverified therapist (counts are zero) |
| `GET`, `PATCH /therapist/profile` | `therapist_profile:manage` | Own profile (bio, focus areas, languages, accepting new students, caseload cap) and verification status |
| `POST /therapist/verification` | `therapist_profile:manage` | Submit licence number, body and expiry; sets the status back to `pending`. A therapist cannot verify themself |
| `GET`, `POST /therapist/availability`, `DELETE /therapist/availability/{id}` | `therapist_profile:manage` | Own bookable times (optional weekly repeat); a booked time cannot be removed |
| `GET /therapist/appointments?scope=requests\|upcoming\|past\|all` | `appointment:manage` | Own appointments with `can_start` and `session_id` |
| `PATCH /appointments/{id}` | `appointment:manage` | Confirm, cancel, complete or mark no-show. Confirming a first appointment creates the care-team link; the student is notified (ids-only payload) |
| `GET /therapist/students`, `GET /therapist/students/{id}` | `student:read:assigned` | Caseload and the authorized profile. **Verified therapist and active care link required** (`404` otherwise). The profile reports which consents are active |
| `GET /therapist/students/{id}/trends?days=&tz=` | `wellness:read:assigned` | Mood, stress and sleep points; needs the `share_mood_with_care_team` consent (`403` without it); no private notes |
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
| `GET /admin/users`, `POST /admin/users` | `user:manage` | List / create (invited, any role) users of the admin's institution |
| `PATCH /admin/users/{id}` | `user:manage` | `{status: active, suspended, deactivated}`; non-active revokes sessions |
| `GET /admin/config`, `PATCH /admin/config` | `config:manage` | Institution name and e-mail domains |
| `GET /admin/audit?action=&before_seq=&limit=` | `audit:read` | Audit metadata for the institution, newest first |

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
| Institution settings | `/admin/institution` | `/admin/config` |
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

| Method & path | Who | Purpose |
|---------------|-----|---------|
| `POST /companion/conversations` | S | Start a conversation |
| `POST /companion/conversations/{id}/messages` | S own | Send message; streams assistant reply via SSE; runs crisis detection first |
| `GET /companion/conversations` / `/{id}` | S own | History (subject to retention) |
| `DELETE /companion/conversations/{id}` | S own | Delete immediately |
| `POST /companion/messages/{id}/report` | S own | Report a bad response |

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
| `POST /admin/ai/kill-switch` | A | Disable companion for institution |

### 2.14 Health (`/health`)

| Method & path | Who | Purpose |
|---------------|-----|---------|
| `GET /health/live`, `GET /health/ready` **PUBLIC** | infra | Probes, no sensitive info |

### 2.15 Internal ML API (service-to-service only, not exposed publicly)

| Method & path | Caller | Purpose |
|---------------|--------|---------|
| `POST /internal/v1/crisis/detect` | api | Text → `{crisis, category, confidence, requires_human, rules_hit}` |
| `POST /internal/v1/signals/support-need` | worker | Feature vector → band + factors |
| `POST /internal/v1/sentiment` | worker | Text → score |
| `POST /internal/v1/companion/respond` | api | Guardrailed generation (streamed) |
| `GET /internal/v1/models` | api | Loaded model versions |

Auth: signed service token (JWT with `aud=ml`, 5 min) + private network only. The ML service
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

`GET /api/v1/ws` (cookie auth; origin checked; ticket from `POST /ws/ticket` valid 30 s).

| Direction | Event | Payload (IDs only) |
|-----------|-------|--------------------|
| server → client | `message.created` | `thread_id`, `message_id` |
| server → client | `message.read` | `thread_id`, `message_id`, `by_role` |
| server → client | `notification.created` | `notification_id`, `priority` |
| server → client | `escalation.assigned` / `escalation.reescalated` | `escalation_id`, `severity` (therapists only) |
| server → client | `appointment.updated` | `appointment_id` |
| client → server | `typing` | `thread_id` (rate-limited) |
| client → server | `ack` | `escalation_id` (also available via REST) |

Message bodies are never pushed over WebSocket; clients fetch via REST. Every subscription is
re-authorized on connect and when care-team membership changes. Critical alerts are also
delivered by SMS and push, never WebSocket alone.

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
