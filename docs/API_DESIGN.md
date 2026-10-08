# MindMitra API Design

- Status: **Proposed** (design only, no code yet)
- Style: REST over HTTPS + one WebSocket gateway; OpenAPI 3.1 is the contract
  (exported to `packages/contracts/openapi.json`)
- Related: [ARCHITECTURE.md §3](ARCHITECTURE.md#3-backend-architecture), [SECURITY_ARCHITECTURE.md](SECURITY_ARCHITECTURE.md)

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
