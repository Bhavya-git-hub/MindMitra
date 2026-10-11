# MindMitra Database Design

- Status: **Partially implemented.** The database layer (models, migrations `0001`-`0005`, seed) exists in
  `services/api`; section 0 below states exactly what was built and where it differs from the
  original design in sections 1-10. Where they disagree, **section 0 is authoritative**.
- Engine: PostgreSQL 16 (AWS RDS Multi-AZ). Implemented extension: `btree_gist`. Designed but not
  yet used: `pg_trgm`, `pgvector`.
- Related: [ARCHITECTURE.md §4](ARCHITECTURE.md#4-database-architecture), [SECURITY_ARCHITECTURE.md](SECURITY_ARCHITECTURE.md)

## 0. Implementation status (database layer, as built)

Code: `services/api/app/infrastructure/db/` (models, session, audit helper, seed),
`services/api/alembic/versions/` (`0001_initial_schema.py`, `0002_tenant_safe_foreign_keys.py`,
`0003_auth_sessions.py`, `0004_crisis_contacts.py`, `0005_therapist_portal.py`, `0006_teacher_portal.py`, `0007_group_snapshots.py`, `0008_institution_settings.py`), tests in `services/api/tests/`. Migration `0003` (authentication phase)
adds the three `iam` session and token tables; see [SECURITY_ARCHITECTURE.md §0](SECURITY_ARCHITECTURE.md#0-implementation-status-authentication-and-authorization-as-built).
Verified against PostgreSQL 16: migration up/down/up, `alembic check` (models == migration),
107 tests, `ruff`, `mypy --strict`, `pip-audit`. Migration `0002` was also checked against a seeded database (backfill) and downgraded/upgraded again; schemas from `0001 -> 0002`, from scratch, and `0002 -> 0001` are identical to the expected ones. See 0.6 for the review that produced `0002`.

### 0.1 What exists

36 tables in 10 PostgreSQL schemas. Confidential therapy data lives in its own `therapy` schema
(plus `comm` and `safety`), apart from general wellness data in `wellness`, so grants, backups and
row-level security can be applied per schema. A test proves a role with access to `wellness` only
gets `permission denied` on `therapy`, `comm` and `safety`.

| Schema | Tables |
|--------|--------|
| `iam` | `users`, `credentials`, `auth_sessions`, `refresh_tokens`, `one_time_tokens` |
| `org` | `institutions`, `departments`, `courses`, `students`, `teachers`, `therapists`, `administrators`, `course_enrollments`, `course_teachers`, `care_team_members` |
| `wellness` | `mood_entries`, `wellness_assessments`, `stress_assessments`, `sleep_entries`, `journal_entries`, `journal_shares`, `wellness_goals`, `resources` |
| `therapy` (confidential) | `therapist_availability`, `appointments`, `therapy_sessions`, `therapy_notes`, `follow_ups` |
| `comm` | `messages` |
| `ai` | `ai_conversations`, `ai_messages`, `recommendations`, `recommendation_feedback`, `recommendation_preferences` |
| `safety` | `risk_alerts`, `crisis_contacts` |
| `consent` | `consents` |
| `notify` | `notifications` |
| `audit` | `audit_logs` |

```mermaid
erDiagram
    INSTITUTION ||--o{ USER : has
    USER ||--o| CREDENTIAL : "argon2id hash only"
    USER ||--o| STUDENT : "role=student"
    USER ||--o| THERAPIST : "role=therapist"
    USER ||--o| TEACHER : "role=teacher"
    USER ||--o| ADMINISTRATOR : "role=administrator"
    DEPARTMENT ||--o{ COURSE : offers
    STUDENT }o--o{ COURSE : "course_enrollments"
    TEACHER }o--o{ COURSE : "course_teachers"
    STUDENT ||--o{ CARE_TEAM_MEMBER : receives
    THERAPIST ||--o{ CARE_TEAM_MEMBER : serves
    STUDENT ||--o{ MOOD_ENTRY : logs
    STUDENT ||--o{ SLEEP_ENTRY : logs
    STUDENT ||--o{ WELLNESS_ASSESSMENT : completes
    STUDENT ||--o{ STRESS_ASSESSMENT : completes
    STUDENT ||--o{ JOURNAL_ENTRY : writes
    JOURNAL_ENTRY ||--o{ JOURNAL_SHARE : "shared via"
    STUDENT ||--o{ WELLNESS_GOAL : sets
    STUDENT ||--o{ AI_CONVERSATION : opens
    AI_CONVERSATION ||--o{ AI_MESSAGE : contains
    STUDENT ||--o{ RECOMMENDATION : receives
    RESOURCE ||--o{ RECOMMENDATION : "suggested as"
    THERAPIST ||--o{ THERAPIST_AVAILABILITY : offers
    THERAPIST_AVAILABILITY ||--o| APPOINTMENT : "booked as"
    STUDENT ||--o{ APPOINTMENT : books
    APPOINTMENT ||--o| THERAPY_SESSION : "delivered as"
    THERAPY_SESSION ||--o{ THERAPY_NOTE : "versions"
    STUDENT ||--o{ MESSAGE : "conversation with therapist"
    STUDENT ||--o{ RISK_ALERT : "may need support"
    USER ||--o{ CONSENT : grants
    USER ||--o{ NOTIFICATION : receives
```

### 0.1a Therapist portal additions (migration `0005`)

- `org.therapists`: `verification_status` (`pending` default, `verified`, `rejected`), `verified_at`,
  `verified_by`, `licence_body`, `licence_expires_on`, `verification_note`. A CHECK ties
  `verified_at` to the `verified` status. "Expired" is **derived** (`licence_expires_on` in the
  past) rather than stored, so it cannot go stale. Only verified therapists can reach student data.
- `therapy.follow_ups`: a therapist's private reminder about one care-team student (`kind`, `status`
  `open`/`done`/`cancelled`, `due_on`, encrypted `note`). `session_id` is a composite foreign key
  `(session_id, therapist_id, institution_id)`, so a follow-up can only point at its own therapist's
  session in its own tenant.
- `ai.recommendations.authored_by`: set when a therapist made the suggestion (`source = therapist`).
- Seed data: every therapist is verified except the last one (when there are three or more), who
  is left waiting for verification so the unverified experience can be seen and tested.

### 0.1b Teacher portal additions (migration `0006`)

- `safety.referrals`: a teacher's referral of one student from one course (`category`, `urgency`,
  encrypted optional `note`, `status` `received`/`in_progress`/`closed`, `claimed_by`, `claimed_at`,
  `closed_at`, fixed `outcome`). The course link is a composite foreign key
  `(course_id, teacher_id, institution_id)` to `org.course_teachers` and
  `(course_id, student_id, institution_id)` to `org.course_enrollments`, so a referral can only
  exist for a real teaching and enrolment link in one tenant. Those two tables gain unique
  constraints that include `institution_id` to support this. Referral foreign keys are
  `RESTRICT`: a course cannot be deleted away from a referral (retention).
- `safety.teacher_support_requests`: a student's explicit request to one of their own teachers
  (`topic`, encrypted optional `message`, `status` `open`/`acknowledged`/`closed`/`withdrawn`, `acknowledged_at`, `closed_at`). Same
  composite foreign keys, but `CASCADE`: if the link is removed, so is the request.
- Indexes on every new foreign key column, `set_updated_at` triggers on both tables, partial
  unique indexes allow one live referral per teacher and student, and one live request per
  student, teacher and course.
- Seed data: about 80% of students hold an `anonymous_aggregate_research` consent (deterministic),
  faculty-tagged resources, three demo referrals and two demo support requests (marked synthetic).

### 0.1c Stored group windows (migration `0007`)

- `wellness.group_snapshots`: a class, department or institution figure for one closed window,
  stored by the first read after its last week closes. Columns: `view` (`figures` or
  `mood_summary`), `group_kind`, `group_id` (not a foreign key, since it points at a course,
  department or institution), `last_week`, `weeks` and a JSON `payload` that holds only what the
  API returns. A unique key on `(group_id, institution_id, view, group_kind, last_week, weeks)`
  makes concurrent first reads store one row. Rows are deleted when a student's consent or
  account status changes, and cascade is not needed because nothing references them.
- `set_updated_at` trigger; a `CHECK` on `view`, `group_kind` and `weeks > 0`.

### 0.1d Institution settings (migration `0008`)

- `org.institution_settings`: one row per institution (`uq_institution_settings_institution`),
  holding the settings an administrator changed as two JSONB objects, `notifications` and
  `safety` (both `CHECK jsonb_typeof = 'object'`), plus `updated_by` (`SET NULL` when the user
  goes). A missing row or key means the default in `app/domain/settings.py`, so a new setting needs
  no data migration. Values are validated (and the invariants enforced) in the application, not
  by the database. `set_updated_at` trigger; index on `updated_by`.

### 0.1e Communication (migration `0009`)

- `therapy.appointments` gains `cancel_reason` (enum `cancellation_reason`, only when cancelled:
  `cancel_reason_only_when_cancelled`), `rescheduled_at` and `reschedule_count` (`>= 0`), and a
  unique `(id, institution_id)` for tenant-safe references. A move updates the row in place, so
  the existing exclusion constraints (`ex_appointments_therapist_no_overlap`,
  `ex_appointments_student_no_overlap`) and `uq_appointments_live_slot` still prevent double
  booking.
- `notify.deliveries`: one row per notification and channel (`unique (notification_id, channel)`)
  for delivery outside the app: `status` (`pending`, `sent`, `failed`, `skipped`), `attempts`,
  `next_attempt_at`, `sent_at` (set exactly when sent, by check), `last_error` (a short code, never
  an address or text). Composite FK to `(notifications.id, institution_id)`, cascading; partial
  index on `next_attempt_at` where pending; index on `user_id`.
- `notify.appointment_reminders`: one row per reminder sent, `unique (appointment_id, starts_at,
  offset_hours)`, offset 1 to 168. The scheduler claims a row before notifying, so a reminder is
  sent at most once even with several schedulers; a moved appointment has a new `starts_at`, so
  it gets its own reminders. Composite FK to the appointment, cascading.
- `set_updated_at` triggers on both new tables.

### 0.1f AI companion (migration `0010`)

- `ai.ai_conversations` gains `last_message_at` (backfilled from the newest message). Retention
  runs from it: `expires_at` is one day after the last message, or 90 days with the
  `AI_COMPANION_HISTORY` consent. Expired rows are hidden at once and deleted by the scheduler.
- `ai.ai_messages` gains `reply_kind` (`reply`, `crisis`, `redirect`, `fallback`,
  `unavailable`), set only on assistant messages (`ck_ai_messages_reply_kind_on_assistant`).
  Content stays encrypted (`EncryptedText("ai.ai_messages.content")`).
- Institution settings (`safety`) gain `companion_enabled` and `companion_daily_messages`
  (10 to 500), validated in code like the other settings.
- See [ADR 0010](adr/0010-ai-wellness-companion-and-safety-layer.md).

### 0.1g Recommendation engine (migration `0011`)

- `ai.recommendations` gains `intervention_key`, `problem_area` (one of seven, checked),
  `relevance` (0 to 1), `resource_format`, `tags`, `reasons` (JSON of signal names and numbers,
  never text a student wrote) and `engine_version`. All empty on older and therapist-made rows.
  It also gains `unique (id, student_id, institution_id)` as the target of feedback's foreign
  key, and an index on `(student_id, created_at)` for history.
- `ai.recommendation_feedback`: one row per suggestion (`unique (recommendation_id)`), `rating`
  `helpful`/`not_helpful`, an optional `reason` from a fixed list that is only allowed with
  `not_helpful`. Composite FK `(recommendation_id, student_id, institution_id)`, cascading.
- `ai.recommendation_preferences`: one row per student: `preferred_formats`, `max_minutes` (1 to
  180), `muted_areas`, `use_indicators`. No row means the defaults. Composite FK to the student,
  cascading.
- `set_updated_at` triggers on both new tables. Both are erased with the student and are in the
  data export. See [ADR 0012](adr/0012-personalised-recommendation-engine.md).

### 0.2 Requirements checklist

| Requirement | How it is met |
|-------------|---------------|
| Foreign keys | 70 FKs. **Every FK between tenant-scoped tables is composite and includes `institution_id`** (enforced by a catch-all test), so a child row can never point at a parent in another institution. Profile tables use `(user_id, role, institution_id)`; departments, courses, enrolments, care teams, wellness data, appointments, sessions, notes, messages, alerts, consents, notifications and journal shares all carry the tenant in their FK; a note's author must be the session's therapist; a slot belongs to the appointment's therapist; a session's parties and tenant equal its appointment's |
| Indexes | 131 indexes (including primary-key and unique indexes). Every FK column leads a full index (partial indexes do not count; tested), no index is a redundant prefix of another (tested), `institution_id` leads an index on every tenant table (tested), plus time-descending indexes on student/therapist timelines, partial indexes for open alerts / unread items / active care teams, a GIN index on resource tags |
| `created_at` / `updated_at` | On every table except `audit_logs`, which is append-only and has `occurred_at` |
| UUIDs | UUIDv7 primary keys generated in the application (`ids.uuid7`), with `gen_random_uuid()` as the server default. `audit_logs.seq` is an identity column used only for chain ordering |
| Confidential vs general data | Separate schemas (above); no FK from `wellness` to `therapy` (tested) |
| No plaintext passwords | Only `credentials.password_hash`; a CHECK requires the `$argon2id$` prefix; hashing in `app/core/security.py`; the seed hashes every password; no password column exists anywhere else (tested) |
| Constraints | 123 CHECK / UNIQUE / EXCLUDE constraints (95 / 25 / 3) besides primary keys: value ranges, enum membership, lowercase unique email per institution, no overlapping availability slots, no double-booked therapist or student, one live appointment per slot, one active primary therapist per student, one active consent per scope, state consistency (`resolved_at` iff resolved/dismissed, `cancelled_at` iff cancelled, ...), `risk_alerts.requires_human` always true, sleep duration agrees with bedtime/wake time |
| Cascade behaviour | See 0.3 |
| Migrations | `0001_initial_schema` creates extensions, schemas, tables, indexes, audit triggers; `0002_tenant_safe_foreign_keys` is the review hardening (0.6). Both are reversible; `alembic check` is a test |
| Synthetic data | `python -m app.infrastructure.db.seed` (about 15,000 rows for 120 students in about 10 s); fictional, `.example` emails, clearly marked therapy notes and alert excerpts; only runs when `APP_ENV` is `development` or `test` (refuses staging, production and an unset value) and refuses if already seeded |

### 0.3 Delete behaviour

| Relationship | Policy | Why |
|--------------|--------|-----|
| User to credentials, profiles, wellness data, AI conversations/messages, recommendations, consents, notifications, journal shares | `CASCADE` | Right to erasure of self-tracked data |
| Anything to `institutions`, `departments` | `RESTRICT` | A tenant is never deleted by accident |
| Therapy appointments, sessions, notes; messages; risk alerts, to student/therapist | `RESTRICT` | Clinical and safety records follow the retention policy; a user with clinical history cannot be hard-deleted, only deactivated or removed by the retention job |
| `recommendations.resource_id`, `resources.reviewed_by`, `appointments.cancelled_by` | `SET NULL` | Keep the record when the referenced item goes away |
| `risk_alerts.assigned_to` to therapist | `RESTRICT` | Composite tenant FKs cannot `SET NULL` (it would null `institution_id`); a therapist with assigned alerts is offboarded through the retention flow anyway |
| Course to enrollments / teaching links | `CASCADE` | Pure association rows |
| Audit rows to users, students, resources | none (soft references) | Audit must outlive the people it describes; a FK `SET NULL` would also require an `UPDATE`, which the append-only trigger forbids |

### 0.4 Differences from the original design (sections 1-10)

| Area | Design said | Implemented | Reason / next step |
|------|-------------|-------------|--------------------|
| Schema names | `wellbeing`, `care`, `insights`, `referral`, `analytics` | `wellness`, `therapy`, plus a new `ai` schema; `insights`, `referral`, `analytics` not created yet | Matches the requested entity list; remaining schemas arrive with their features |
| Roles | `faculty`, `institution_admin`, `platform_admin`, `clinical_supervisor` as roles | `user_role` = `student`, `therapist`, `teacher`, `administrator`; `administrators.admin_level` distinguishes institution vs platform admin | Requested entity names; supervisor role comes with break-glass work |
| Role tables | RBAC tables (`role`, `permission`, `role_permission`, `user_role`) | Not created. One role per user, enforced by composite FKs; the role-to-permission map is code (`app/domain/auth/permissions.py`), reviewed and tested like the policies | A table adds nothing while roles are fixed; revisit if institutions need custom roles |
| Auth tables | `mfa_factor`, `auth_session`, `refresh_token`, `invitation`, `password_reset` | `0003`: `auth_sessions` (absolute expiry, revocation reason, hashed IP), `refresh_tokens` (SHA-256 token and CSRF hashes, single use), `one_time_tokens` (hashed; purpose `password_reset`, `account_setup` or `email_verification`, which also replaces `invitation`). All tenant-scoped with composite FKs and `updated_at` triggers | `mfa_factor` comes with MFA |
| Check-ins | One `checkin` table | Split into `mood_entries`, `sleep_entries`, `wellness_assessments`, `stress_assessments` | Requested entities; each has its own constraints and timeline index |
| Messaging | `message_thread`, `message`, `message_read`, `attachment` | Single `messages` table keyed by (student, therapist) pair, with `read_at`, `client_msg_id` (idempotent retries) and `crisis_checked_at`; sender must be one of the pair | Simpler for a one-to-one care relationship; threads/attachments can be added without breaking it |
| Crisis workflow | `crisis_signal`, `escalation`, `escalation_event`, `on_call_rota`, `on_call_shift`, `break_glass_grant`, `crisis_resource` | One `risk_alerts` table (source, detector, category, severity, SLA deadline, status, minimal encrypted excerpt) | Requested entity; timeline, rota and break-glass tables are deferred to the safety phase. Categories contain no diagnostic labels (tested) |
| Crisis contacts | `crisis_resource` | `0004`: `safety.crisis_contacts` (kind `emergency`/`helpline`/`campus`, phone, URL, description, hours, sort order, active flag). `institution_id` NULL means "every institution"; a CHECK requires at least a phone, URL or description. Seeded with **synthetic demo contacts** | Shown to students at `/student/emergency`. Real numbers must be entered and verified per institution before go-live |
| Consent | Append-only rows with `status` | One row per grant; `revoked_at` ends it; re-granting inserts a new row; partial unique index allows one active grant per (user, scope) | History is preserved and the "one active consent" rule is a database constraint |
| Appointments | `appointment` + `session_note` | `appointments`, `therapy_sessions` (delivered session), `therapy_notes` (versioned, one row per edit) | Separates scheduling from the clinical session record |
| Encryption | KMS envelope encryption, per-user/per-note data keys, AAD bound to row | Interim: AES-256-GCM, one key from `FIELD_ENCRYPTION_KEY`, AAD bound to the **column** (`EncryptedText(context)`), versioned ciphertext format | KMS and per-record keys need AWS wiring (deployment phase). Ciphertext moved to another column fails to decrypt (tested) |
| Row-level security | Policies on tenant tables | **Not yet.** `institution_id` is on all tenant tables and `session.set_rls_context()` sets `app.user_id`, `app.institution_id`, `app.role` per transaction | Policies need the authorization model; they ship with it |
| Enum storage | Not specified | `VARCHAR(32)` + named CHECK constraint instead of native PostgreSQL enums | Values can be added by a normal migration without `ALTER TYPE` |
| Audit | Append-only, hash-chained | Implemented: BEFORE UPDATE/DELETE/TRUNCATE triggers reject changes; `hash = SHA256(prev_hash + canonical fields)` per institution; advisory lock serialises appends; `verify_chain()` finds the first altered row | As designed; S3 Object Lock checkpoints are a deployment task |
| Retention | Sweep jobs | Companion conversations are swept by the scheduler once `expires_at` passes (migration `0010`); other soft-delete columns have no job yet | The rest belongs to the background-worker phase |
| Not yet built | `resource_interaction`, `video_session`, `referral*`, `notification_preference`, `delivery_log`, `outbox_event`, `push_subscription`, `analytics.*`, resource embeddings | Deferred | Each belongs to a later feature phase |

### 0.5 Running it

```bash
cd services/api
cp ../../.env.example .env            # then set real local values; never commit .env
uv sync                               # install dependencies
alembic upgrade head                  # create schemas and tables
python -m app.infrastructure.db.seed  # synthetic data (prints a one-time password if SEED_USER_PASSWORD is unset)
TEST_DATABASE_URL=postgresql+asyncpg://USER:PASS@localhost:5432/postgres pytest
```

### 0.6 Review of the database layer (migration `0002`)

A full review (tests, migrations, foreign keys, indexes, security and privacy) found the
following. All were fixed in `0002` or in code; no features were added.

| # | Finding | Severity | Fix |
|---|---------|----------|-----|
| A | Child rows carried their own `institution_id` but nothing tied it to the parent's. A bug (or a missing check in future code) could attach institution A's mood entry, message, appointment or alert to a student of institution B. | High (tenant isolation) | Composite `(id, institution_id)` foreign keys everywhere; four join tables (`care_team_members`, `course_enrollments`, `course_teachers`, `journal_shares`) gained `institution_id`, backfilled from their parent. Test: `test_tenant_isolation.py`, including a catch-all that fails if a new tenant-scoped FK omits `institution_id`. |
| B | `risk_alerts` check `acknowledged_before_progress` forbade the `escalated` status without an acknowledgement, so automatic escalation of an unacknowledged alert would have been rejected. | Medium (safety workflow) | `escalated` is allowed without acknowledgement; `acknowledged`, `in_progress` and `resolved` still require it. |
| C | `risk_alerts.assigned_to` was `SET NULL`; with a composite tenant FK that would try to null `institution_id`. | Medium | `RESTRICT` (see 0.3). |
| D | Foreign keys backed only by partial indexes (`care_team_members` student/therapist, `messages.therapist_id`, `appointments.availability_id`) would scan on every parent delete. The old index test accepted partial indexes. | Medium (performance) | Full indexes added; the test now rejects partial indexes unless the predicate is `col IS NOT NULL`. |
| E | Redundant single-column `institution_id` indexes on `users`, `departments`, `audit_logs` (each already leads a composite or unique index). | Low | Dropped; new test `test_no_redundant_indexes`. |
| F | Profile tables had both a plain `user_id -> users` FK and the stronger composite one. | Low | Plain FK dropped. |
| G | `sleep_entries.duration_minutes` could disagree with bedtime/wake time. | Low (data quality) | CHECK `duration_matches_times` (1 minute tolerance). |
| H | `updated_at` was maintained only by the ORM; raw SQL left it stale. | Low | `public.set_updated_at()` BEFORE UPDATE trigger on every table with `updated_at`; test checks all of them. |
| I | `APP_ENV` defaulted to `development`: a missing variable silently allowed seeding synthetic data. | Medium (privacy) | `APP_ENV` is required. Seeding is allowed only for `development` and `test` (an allow-list, not a production deny-list). |
| J | Staging/production could connect to the database without TLS; a malformed `FIELD_ENCRYPTION_KEY` only failed on first write. | Medium | Settings validation: TLS (`ssl=require` or stronger) required for staging/production; key must be base64 of 32 bytes at startup. |
| K | Failing SQL statements echo bound parameters in exception text and logs, which can contain journal or message text. | Medium (privacy) | Engine created with `hide_parameters=True` (tested with a deliberately failing statement). |
| L | Nothing stopped a caller from writing message bodies, notes, e-mail addresses or secrets into the append-only audit `details`. | Medium (privacy, irreversible) | `append_audit_event` rejects forbidden keys (body, content, note, email, password, token, ...) at any depth and values over 200 characters. |
| M | `docker-compose.yml` published Postgres and Redis on all interfaces. | Medium (dev hygiene) | Bound to `127.0.0.1`. |
| N | `app/infrastructure/db/types.py` shadowed the standard library `types` module when run from that directory. | Low | Renamed `column_types.py`. |

Checked and found sound: Argon2id-only password storage (CHECK + tests); AES-256-GCM with the column
as AAD (a ciphertext copied to another column fails to authenticate); audit triggers and hash
chain; no FK between `wellness` and `therapy`; every FK has an explicit delete policy; seed data is
fictional and marked as such; no secrets in the repository; `pip-audit` reports no known
vulnerabilities.

**Known gaps (deliberately not addressed here; each belongs to a later phase):**

- No row-level-security policies and no separate database roles or grants yet. Today the application
  role could read every schema; the schema split makes least-privilege grants possible (a test
  proves a wellness-only role cannot read `therapy`), but the roles are not created.
- Field encryption uses a single environment key (interim). KMS envelope encryption and key
  rotation are a deployment task.
- The audit trigger stops application roles, not a database owner or superuser; S3 Object Lock
  checkpoints and restricted ownership close this later.
- Rules that need a *relationship* rather than a *tenant* are enforced by the application, not the
  database: that a message sender has a care-team link, that a journal share targets a therapist on
  the student's care team, and that a recommendation's resource is visible to the student's
  institution. `appointments.cancelled_by`, `messages.sender_id` and `resources.reviewed_by` are
  plain user references (tenant is implied by the other tenant-checked columns or global).
- `0002` downgrade restores the old foreign keys and drops the new tenant columns; downgrading
  production is not a supported operation, and `0001` downgrade removes all data.
- There is no CI workflow yet running the tests on every push.

---

## 1. Design principles

1. **Tenant isolation**: every tenant-owned row carries `institution_id`; row-level security
   (RLS) enforces it even if application code has a bug.
2. **Classification-driven storage**: each column is classed Public / Internal / Personal /
   Sensitive / Clinical-Confidential; free text in the last two is field-encrypted.
3. **Bounded contexts own schemas**: no cross-schema writes; reads across contexts go through
   application services.
4. **Append-only where it matters**: audit, consent history, escalation timeline.
5. **UUIDv7 keys**, `timestamptz` everywhere (UTC), `created_at` / `updated_at` on all tables.
6. **Soft delete first, crypto-shred to erase**: per-record or per-user data keys can be
   destroyed to make ciphertext unrecoverable.
7. **Migrations** with Alembic, reviewed, backwards-compatible (expand/contract).

## 2. Schema map

```mermaid
flowchart LR
    iam --- org
    org --- wellbeing
    org --- care
    org --- comm
    org --- safety
    wellbeing --- insights
    care --- comm
    safety --- notify
    wellbeing --- consent
    care --- consent
    iam -.events.-> audit
    wellbeing -.aggregates.-> analytics
    safety -.aggregates.-> analytics
```

| Schema | Owner context | Class |
|--------|--------------|-------|
| `iam` | identity & access | Personal / secret |
| `org` | institution structure and profiles | Personal |
| `consent` | consent and policy versions | Personal |
| `wellbeing` | check-ins, journal, companion | Sensitive |
| `insights` | ML signals and model versions | Sensitive |
| `care` | appointments, session notes, care team | Clinical-Confidential |
| `comm` | threads, messages, video sessions | Sensitive |
| `safety` | crisis signals, escalations, on-call, resources | Sensitive / Clinical |
| `referral` | faculty referrals | Sensitive |
| `notify` | notifications, outbox, preferences | Internal |
| `audit` | audit events | Restricted |
| `analytics` | aggregate tables only | Internal |

## 3. Entity-relationship diagrams

### 3.1 Identity, organisation and assignments

```mermaid
erDiagram
    INSTITUTION ||--o{ DEPARTMENT : has
    INSTITUTION ||--o{ USER : employs_or_enrols
    DEPARTMENT ||--o{ COHORT : has
    USER ||--o| STUDENT_PROFILE : is
    USER ||--o| THERAPIST_PROFILE : is
    USER ||--o| FACULTY_PROFILE : is
    USER ||--o{ USER_ROLE : holds
    ROLE ||--o{ USER_ROLE : granted
    ROLE ||--o{ ROLE_PERMISSION : includes
    PERMISSION ||--o{ ROLE_PERMISSION : in
    STUDENT_PROFILE }o--|| COHORT : belongs_to
    FACULTY_PROFILE }o--o{ COHORT : teaches
    THERAPIST_PROFILE ||--o{ CARE_TEAM_MEMBER : serves
    STUDENT_PROFILE ||--o{ CARE_TEAM_MEMBER : receives
    USER ||--o{ AUTH_SESSION : has
    AUTH_SESSION ||--o{ REFRESH_TOKEN : rotates
    USER ||--o{ MFA_FACTOR : registers

    USER {
        uuid id PK
        uuid institution_id FK
        citext email
        string status
        timestamptz last_login_at
    }
    CARE_TEAM_MEMBER {
        uuid id PK
        uuid student_id FK
        uuid therapist_id FK
        string role "primary or secondary"
        timestamptz starts_at
        timestamptz ends_at
    }
```

### 3.2 Wellbeing, insights and consent

```mermaid
erDiagram
    STUDENT_PROFILE ||--o{ CHECKIN : submits
    STUDENT_PROFILE ||--o{ JOURNAL_ENTRY : writes
    STUDENT_PROFILE ||--o{ COMPANION_CONVERSATION : opens
    COMPANION_CONVERSATION ||--o{ COMPANION_MESSAGE : contains
    STUDENT_PROFILE ||--o{ ML_SIGNAL : has
    ML_MODEL_VERSION ||--o{ ML_SIGNAL : produced_by
    STUDENT_PROFILE ||--o{ CONSENT_RECORD : grants
    JOURNAL_ENTRY ||--o{ JOURNAL_SHARE : shared_via
    JOURNAL_SHARE }o--|| THERAPIST_PROFILE : with

    CHECKIN {
        uuid id PK
        uuid student_id FK
        uuid institution_id
        smallint mood
        smallint stress
        smallint sleep_quality
        smallint energy
        bytea note_ciphertext
        timestamptz created_at
    }
    ML_SIGNAL {
        uuid id PK
        uuid student_id FK
        string signal_type
        string band
        jsonb factors
        real confidence
        uuid model_version_id FK
        timestamptz created_at
    }
```

### 3.3 Care, communication and safety

```mermaid
erDiagram
    THERAPIST_PROFILE ||--o{ AVAILABILITY_SLOT : offers
    AVAILABILITY_SLOT ||--o| APPOINTMENT : booked_as
    STUDENT_PROFILE ||--o{ APPOINTMENT : books
    APPOINTMENT ||--o| SESSION_NOTE : documented_by
    APPOINTMENT ||--o| VIDEO_SESSION : uses
    STUDENT_PROFILE ||--o{ MESSAGE_THREAD : participates
    MESSAGE_THREAD ||--o{ MESSAGE : contains
    MESSAGE ||--o{ ATTACHMENT : has
    STUDENT_PROFILE ||--o{ ESCALATION : subject_of
    ESCALATION ||--o{ ESCALATION_EVENT : timeline
    ESCALATION }o--o| CRISIS_SIGNAL : triggered_by
    ON_CALL_ROTA ||--o{ ON_CALL_SHIFT : schedules
    THERAPIST_PROFILE ||--o{ ON_CALL_SHIFT : covers
    FACULTY_PROFILE ||--o{ REFERRAL : raises
    REFERRAL }o--|| STUDENT_PROFILE : about
    REFERRAL ||--o{ REFERRAL_EVENT : timeline
    REFERRAL }o--o| ESCALATION : may_create

    SESSION_NOTE {
        uuid id PK
        uuid appointment_id FK
        uuid author_id FK
        bytea body_ciphertext
        bytea dek_wrapped
        int version
        timestamptz created_at
    }
    ESCALATION {
        uuid id PK
        uuid student_id FK
        string source
        string severity
        string status
        uuid assigned_to
        bytea excerpt_ciphertext
        timestamptz sla_ack_due_at
        timestamptz created_at
    }
```

## 4. Table catalogue

> This catalogue is the original design. For what is built, and the names it uses, see section 0.

Notation: **PK** primary key, **FK** foreign key, 🔒 field-encrypted, ⚑ indexed for hot path.
All tables also have `created_at`, `updated_at`; tenant tables have `institution_id` (omitted
below for brevity).

### 4.1 `iam`

| Table | Key columns | Notes |
|-------|-------------|-------|
| `user` | id PK, email (citext, unique per institution), status (`invited`,`active`,`suspended`,`deactivated`), display_name, last_login_at | No password here |
| `credential` | user_id PK/FK, password_hash (Argon2id), password_changed_at, failed_attempts, locked_until | Separate table, separate DB grants |
| `mfa_factor` | id, user_id, type (`totp`,`webauthn`), secret_ciphertext 🔒, verified_at | |
| `auth_session` | id, user_id, device_label, ip_hash, user_agent_hash, created_at, last_seen_at, revoked_at | |
| `refresh_token` | id, session_id, family_id, token_hash, rotated_at, expires_at, reuse_detected | Opaque tokens stored hashed |
| `role` | id, key (`student`,`therapist`,`faculty`,`institution_admin`,`platform_admin`,`clinical_supervisor`) | |
| `permission` | id, key (`checkin:read`, ...) | |
| `role_permission` | role_id, permission_id | |
| `user_role` | user_id, role_id, scope_type, scope_id | e.g. faculty scoped to cohort |
| `invitation` | id, email, role_id, token_hash, expires_at, accepted_at, invited_by | |
| `password_reset` | id, user_id, token_hash, expires_at, used_at | |

### 4.2 `org`

| Table | Key columns | Notes |
|-------|-------------|-------|
| `institution` | id, name, region, domain_allowlist[], settings jsonb, status | Tenant root |
| `department` | id, institution_id, name | |
| `cohort` | id, department_id, name, academic_year | Unit for faculty aggregates |
| `student_profile` | user_id PK, cohort_id, enrolment_year, preferred_name, pronouns, locale | Minimal; no DOB/address |
| `therapist_profile` | user_id PK, licence_number 🔒, specialties[], languages[], bio, accepting_new | |
| `faculty_profile` | user_id PK, department_id, title | |
| `faculty_cohort` | faculty_id, cohort_id | Cohorts a teacher may see aggregates for |
| `care_team_member` | id, student_id, therapist_id, role, starts_at, ends_at | Relationship backbone for authorization |

### 4.3 `consent`

| Table | Key columns | Notes |
|-------|-------------|-------|
| `policy_version` | id, kind (`terms`,`privacy`,`ai_notice`), version, effective_at, content_ref | |
| `consent_record` | id, user_id, scope, status (`granted`,`revoked`), policy_version_id, granted_at, revoked_at, source | **Append-only**; current state via view `consent.current` |
| `data_request` | id, user_id, type (`export`,`erasure`), status, requested_at, completed_at | Data subject requests |

### 4.4 `wellbeing`

| Table | Key columns | Notes |
|-------|-------------|-------|
| `checkin` | id, student_id ⚑, mood 1-5, stress 1-5, sleep_quality 1-5, energy 1-5, note_ciphertext 🔒, created_at ⚑ | Index `(student_id, created_at desc)` |
| `journal_entry` | id, student_id, title_ciphertext 🔒, body_ciphertext 🔒, mood_tag, created_at, deleted_at | Private by default |
| `journal_share` | id, entry_id, therapist_id, shared_at, revoked_at | Explicit per-entry sharing |
| `companion_conversation` | id, student_id, started_at, expires_at, deleted_at | `expires_at` from retention setting |
| `companion_message` | id, conversation_id, role (`user`,`assistant`), body_ciphertext 🔒, safety_flags, model_version | |
| `resource` | id, institution_id nullable, title, body, tags[], language, embedding vector(768), reviewed_by, reviewed_at | Vetted library, searched via pgvector |
| `resource_interaction` | id, student_id, resource_id, kind, created_at | |

### 4.5 `insights`

| Table | Key columns | Notes |
|-------|-------------|-------|
| `ml_model_version` | id, name, version, task, card_url, promoted_at, promoted_by | |
| `ml_signal` | id, student_id, signal_type (`support_need`,`engagement`,`sentiment`), band, score, factors jsonb, confidence, model_version_id, source_window | **Never contains diagnosis labels**; `band` is `low`/`moderate`/`elevated` |

### 4.6 `care`

| Table | Key columns | Notes |
|-------|-------------|-------|
| `availability_slot` | id, therapist_id, starts_at, ends_at, mode (`video`,`in_person`), status | |
| `appointment` | id, student_id, therapist_id, slot_id, status (`booked`,`confirmed`,`completed`,`cancelled`,`no_show`), reason_ciphertext 🔒, created_at | |
| `session_note` | id, appointment_id, author_id, body_ciphertext 🔒, dek_wrapped, version, locked_at | **Clinical-Confidential**; versioned (new row per edit, previous retained) |
| `session_note_access` | note_id, user_id, granted_by, reason, expires_at | Supervisor/break-glass access, audited |
| `video_session` | id, appointment_id, provider_meeting_id, started_at, ended_at | No recordings by default |

### 4.7 `comm`

| Table | Key columns | Notes |
|-------|-------------|-------|
| `message_thread` | id, student_id, care_team_id, status, last_message_at | One per student-care team |
| `message` | id, thread_id, sender_id, body_ciphertext 🔒, client_msg_id (idempotency), crisis_checked_at, created_at | |
| `message_read` | message_id, user_id, read_at | |
| `attachment` | id, message_id, s3_key, size, mime, scan_status | Scanned before availability |

### 4.8 `safety`

| Table | Key columns | Notes |
|-------|-------------|-------|
| `crisis_signal` | id, student_id, source (`checkin`,`companion`,`message`,`journal`,`help_button`,`referral`,`therapist`), detector (`rules`,`classifier`,`human`), category, confidence, excerpt_ciphertext 🔒, created_at | Minimal excerpt only |
| `escalation` | id, student_id, signal_id, severity (`moderate`,`high`,`imminent`), status (`open`,`acknowledged`,`reescalated`,`in_progress`,`emergency_contacted`,`referred_external`,`resolved`), assigned_to, sla_ack_due_at, resolved_at, outcome | Index `(institution_id, status, sla_ack_due_at)` |
| `escalation_event` | id, escalation_id, actor_id, type, note_ciphertext 🔒, created_at | Append-only timeline |
| `on_call_rota` | id, institution_id, name, escalation_policy jsonb | Levels, SLAs |
| `on_call_shift` | id, rota_id, therapist_id, level, starts_at, ends_at | |
| `crisis_resource` | id, institution_id nullable, kind (`helpline`,`campus_emergency`,`text_line`), name, contact, hours, language, sort | Also exported to static `/help` page |
| `break_glass_grant` | id, escalation_id, user_id, scope, granted_at, expires_at, reason | Time-boxed extra visibility |

### 4.9 `referral`

| Table | Key columns | Notes |
|-------|-------------|-------|
| `referral` | id, student_id, raised_by, category (`academic_distress`,`behaviour_change`,`wellbeing_concern`,`safety_concern`), urgency, note_ciphertext 🔒, status (`received`,`triaged`,`in_progress`,`closed`), created_at | |
| `referral_event` | id, referral_id, actor_id, type, created_at | Faculty sees only status-level events |

### 4.10 `notify`

| Table | Key columns | Notes |
|-------|-------------|-------|
| `outbox_event` | id, aggregate_type, aggregate_id, type, payload jsonb (IDs only), created_at, published_at | Transactional outbox |
| `notification` | id, user_id, type, priority, payload (IDs only), read_at, created_at | In-app inbox |
| `notification_preference` | user_id, channel, enabled, quiet_hours | |
| `delivery_log` | id, notification_id, channel, status, provider_msg_id, attempts, last_error | |
| `push_subscription` | id, user_id, endpoint_hash, keys_ciphertext | |

### 4.11 `audit`

| Table | Key columns | Notes |
|-------|-------------|-------|
| `audit_event` | id, institution_id, actor_id, actor_role, action, resource_type, resource_id, subject_student_id, outcome, reason, request_id, ip_hash, occurred_at, prev_hash, hash | Append-only, hash-chained per institution |

### 4.12 `analytics`

| Table | Key columns | Notes |
|-------|-------------|-------|
| `cohort_weekly` | institution_id, cohort_id, week, n_students, avg_mood, avg_stress, avg_sleep, checkin_rate, suppressed | Row published only if `n_students >= 10`; no individual IDs |
| `service_usage_daily` | institution_id, day, appointments_booked, messages_sent, companion_sessions | Counts only |
| `escalation_stats_weekly` | institution_id, week, count, median_ack_seconds, p95_ack_seconds | Counts only |
| `product_event` | day, event, count | No user IDs |

## 5. Encryption design

### 5.1 Envelope encryption

```mermaid
flowchart LR
    CMK["KMS CMK per institution per class"] -->|wraps| DEK["Data key (DEK) per user or per record"]
    DEK -->|AES-256-GCM| CT["Ciphertext in column (bytea)"]
    DEKW["Wrapped DEK stored with row or in iam.user_key"] --- CT
    APP[api service] -->|KMS Decrypt via IAM role + encryption context| DEK
```

- Algorithm: **AES-256-GCM**, 96-bit random nonce, AAD = `table | column | row_id | institution_id`
  (binds ciphertext to its row and tenant).
- Key hierarchy: KMS CMK (per environment, per institution, per class: `sensitive`,
  `clinical`) → per-user DEK (`iam.user_key`, wrapped) for Sensitive data; per-note DEK for
  session notes. Unwrapped DEKs are cached briefly in memory only.
- **Crypto-shredding**: deleting a user's wrapped DEK (after retention checks) makes their
  Sensitive ciphertext unrecoverable, including in backups.
- **Searchability**: encrypted columns are not searchable; where lookup is needed (for
  example by email) a keyed HMAC "blind index" column is used. No full-text search over
  clinical text in v1.
- KMS encryption context includes `institution_id` and class, so a service cannot decrypt
  across tenants.

### 5.2 Column classification (examples)

| Column | Class | Protection |
|--------|-------|-----------|
| `user.email` | Personal | RBAC, TLS, disk encryption |
| `checkin.mood` etc. | Sensitive (structured) | RBAC + consent; disk encryption |
| `checkin.note_ciphertext` | Sensitive (free text) | Field encryption |
| `journal_entry.*_ciphertext` | Sensitive | Field encryption, owner-only |
| `session_note.body_ciphertext` | Clinical-Confidential | Field encryption, per-note DEK, author-only, audited |
| `escalation.excerpt_ciphertext` | Clinical-Confidential | Field encryption, care-team only |

## 6. Row-level security

Application connects as role `app_user`; each transaction sets:

```sql
SELECT set_config('app.user_id', :uid, true);
SELECT set_config('app.institution_id', :iid, true);
SELECT set_config('app.role', :role, true);
```

Example policies (illustrative, not final):

```sql
ALTER TABLE wellbeing.checkin ENABLE ROW LEVEL SECURITY;
ALTER TABLE wellbeing.checkin FORCE ROW LEVEL SECURITY;

-- Tenant isolation for all roles
CREATE POLICY tenant_isolation ON wellbeing.checkin
  USING (institution_id = current_setting('app.institution_id')::uuid);

-- Student sees own rows
CREATE POLICY student_own ON wellbeing.checkin FOR SELECT
  USING (student_id = current_setting('app.user_id')::uuid);

-- Therapist sees rows of students in active care team WITH consent
CREATE POLICY therapist_care_team ON wellbeing.checkin FOR SELECT
  USING (
    current_setting('app.role') = 'therapist'
    AND EXISTS (
      SELECT 1 FROM org.care_team_member c
      WHERE c.student_id = checkin.student_id
        AND c.therapist_id = current_setting('app.user_id')::uuid
        AND now() BETWEEN c.starts_at AND coalesce(c.ends_at, 'infinity')
    )
    AND consent.has_active('share_checkins_with_care_team', checkin.student_id)
  );
```

- **No policy** exists for `faculty` or `institution_admin` on `wellbeing`, `care`, `comm`,
  `insights`: default deny.
- Separate DB roles: `app_user` (OLTP), `analytics_reader` (only `analytics` schema),
  `audit_writer` (INSERT only on `audit`), `migrator` (DDL, not used at runtime),
  `readonly_support` (no access to ciphertext columns).
- Policy tests run in CI against a real Postgres (each role × table × operation).

## 7. Indexing and performance

| Table | Index | Purpose |
|-------|-------|---------|
| `checkin` | `(student_id, created_at DESC)` | Trend queries |
| `message` | `(thread_id, created_at)`; unique `(thread_id, client_msg_id)` | Pagination, idempotency |
| `appointment` | `(therapist_id, starts_at)`, `(student_id, starts_at)` | Calendars |
| `escalation` | partial `(institution_id, sla_ack_due_at) WHERE status IN ('open','reescalated')` | SLA timer scans |
| `care_team_member` | `(therapist_id, student_id) WHERE ends_at IS NULL` | Authorization joins |
| `audit_event` | `(institution_id, occurred_at)`, `(subject_student_id, occurred_at)` | Admin search, student access history |
| `resource` | HNSW on `embedding` | RAG retrieval |

Partitioning: `audit_event`, `message`, `checkin`, `delivery_log` partitioned monthly by
`created_at` once volume warrants it. Connection pooling via RDS Proxy / PgBouncer
(transaction mode; RLS settings use `set_config(..., true)` so they are transaction-local).

## 8. Retention and deletion

| Data | Mechanism |
|------|-----------|
| Companion messages | `expires_at` from consent setting; nightly `retention_sweep` hard-deletes |
| Check-ins / journal | Soft delete on request, crypto-shred after 30-day undo window |
| Messages, session notes, escalations | Retained per clinical records policy; erased after expiry; legal hold flag blocks deletion |
| Audit events | 7 years; immutable; partitions archived to S3 Glacier (Object Lock) |
| Outbox events | Deleted 7 days after publish |
| Backups | 35-day PITR; crypto-shredded keys render deleted data unreadable in older backups |

## 9. Backup and recovery

- Automated daily snapshots + PITR (RPO ≤ 5 min), Multi-AZ failover, cross-region encrypted
  snapshot copy, quarterly restore drills documented in runbooks.
- Redis is treated as ephemeral (rebuildable); the durable queue state is the outbox table.

## 10. Synthetic data and migrations

- `data/synthetic` provides generators for institutions, users, check-ins, appointments,
  messages and crisis scenarios; seeds are deterministic (fixed random seeds).
- Alembic migrations: one logical change each, expand → migrate → contract, tested up and
  down on a database populated with synthetic data. RLS policies are part of migrations and
  covered by tests.
