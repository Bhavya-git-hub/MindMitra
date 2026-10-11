# MindMitra Security Audit (October 2026)

- **Date:** 2026-10-11
- **Scope:** the API (`services/api`), the ML and companion service (`services/ml`) and the web
  app (`apps/web`) on `main` at `b709563`.
- **Method:** code review plus attacks run as tests against the real app and PostgreSQL. Every
  vulnerability found was fixed, unless listed in section 5, and each fix has a regression test
  that failed before the fix and passes after it.
- **Decisions that changed a contract:** [ADR 0015](adr/0015-security-audit-2026-10.md).

## 1. Summary

| Severity | Found | Fixed | Left open (section 5) |
|----------|-------|-------|-----------------------|
| Critical | 0 | 0 | 0 |
| High | 1 | 1 | 0 |
| Medium | 10 | 9 | 1 (per-IP auth rate limit, needs deployment work) |
| Low | 14 | 8 | 6 |

The authorization model held up well. Every privilege-escalation path the owner listed was
attempted (section 3), and none gave a student, teacher or administrator access to another
person's private records or to therapy notes. The real problems were:

- **Registration:** a stranger could take over a student's account before the student verified
  it.
- **Ended care links:** three places still worked after a care link ended.
- **Administrator audit view:** it showed care relationships and safety events.
- **Crisis rules:** they could be dodged with invisible characters.
- **Secondary paths:** secrets in startup errors, a timing leak, a WebSocket that outlived its
  session, and no request size limit.

There are no file upload endpoints anywhere in the product, so file-upload attacks do not apply.

## 2. Findings and fixes

### High

| # | Finding | Where | Fix | Regression test |
|---|---------|-------|-----|-----------------|
| H1 | **Account takeover before verification.** Anyone could register a student's address with their own password. When the real student registered, nothing was sent. The only link in the student's inbox was the stranger's, and clicking it activated the account with the stranger's password. The stranger could then, for example, withdraw the safety-scanning consent. Bulk pre-registration also locked students out of self-registration. | `application/auth/service.py` `register_student`, `verify_email` | Verifying needs the e-mailed token and the password chosen at registration. A wrong password answers like a bad link and leaves the link usable. Re-registering a never-verified, self-registered address replaces the pending password and sends a fresh link, and older links stop working. The web verification page asks for the password. | `test_security_auth.py::test_a_link_sent_because_a_stranger_registered_cannot_activate_their_password`, `::test_the_real_student_registering_later_gets_their_own_link_and_password`, `::test_registering_an_active_or_invited_account_changes_nothing`; `auth-pages.test.tsx` VerifyEmailView |

### Medium

| # | Finding | Where | Fix | Regression test |
|---|---------|-------|-----|-----------------|
| M1 | **The administrator audit view revealed care relationships and safety events.** `subject_student_id` on `student.read`, `therapy_note.read`, `safety_event.create` and `risk_alert` rows let an administrator list which students a therapist sees, and who raised a safety event. ADR 0008 says they cannot. | `application/admin_audit.py`, `api/schemas/admin.py` | On care records the view and the CSV export leave out the student, the record id and the details. A student's own actions on care records are not listed. | `test_security_escalation.py::test_admin_audit_log_does_not_reveal_care_relationships_or_safety_events` |
| M2 | **The therapist's conversation list leaked after a care link ended.** It still showed the student's name, a 90-character preview of the last message and the unread count, and the dashboard kept counting those messages. | `application/messaging.py`, `application/therapist_dashboard.py` | Ended-link conversations are listed for the student only. The dashboard counts active students only. | `test_security_escalation.py::test_therapist_conversation_list_hides_an_ended_care_link` |
| M3 | **An administrator could claim another institution's e-mail domains.** Setting a domain such as `edu` or `example`, or another tenant's domain, blocked that tenant's self-registration or captured sign-ups. | `application/admin.py` `update_institution` | Domains are normalised and must be real domains (422). An overlap with another institution, including a subdomain in either direction, is refused (409). | `test_security_escalation.py::test_admin_cannot_claim_another_institutions_email_domain` |
| M4 | **Crisis phrases could be hidden from the safety rules.** A direction mark, an invisible operator, a tag character, a combining accent, a variation selector or a Cyrillic look-alike letter turned "I want to kill myself" from HIGH into LOW. The message then went to the model with no contacts and no alert. RTL and Cyrillic keyboards can do this by accident. | `domain/safety/crisis_rules.py` and its copy in `services/ml/safety` | `normalise()` drops format characters, combining marks and variation selectors, and folds look-alike letters before matching. This only adds matches. | `test_security_input.py::test_shaped_crisis_text_is_still_a_crisis` (8 cases) |
| M5 | **A revoked session's WebSocket stayed open while events kept arriving.** The session re-check only ran after 60 seconds without an event. | `api/realtime.py` | The re-check runs on a fixed schedule whatever the traffic. | `test_security_realtime.py::test_a_steady_event_stream_does_not_keep_a_signed_out_socket_open` |
| M6 | **Refused companion messages reached the model one turn later.** Prompt-injection, diagnosis and medication requests got a fixed reply, but stayed in the history sent with the next message. | `services/ml/app/companion/context.py` | Refused turns, and the fixed replies to them, are dropped from the context. | `services/ml/tests/test_security_companion.py` |
| M7 | **Startup configuration errors printed secrets.** Pydantic echoed the rejected database URL with its password, the encryption key and the ML service token. | `core/config.py`, `services/ml/app/config.py` | `hide_input_in_errors=True` in both settings classes. | `test_security_auth.py::test_settings_errors_never_echo_secret_values`, `ml/tests/test_security_service_auth.py` |
| M8 | **Registration revealed whether an e-mail was registered, by timing.** A known address answered in about 6 ms and a new one in about 150 ms. | `application/auth/service.py` | Every path pays the same Argon2 cost. | `test_security_auth.py::test_registering_a_known_email_costs_the_same_password_hashing` |
| M9 | **No request size limit.** A 50 MB anonymous body was buffered and parsed before the 401. | `api/main.py`, new `api/body_limit.py` | An outermost middleware refuses a declared or streamed body over 512 KiB with 413, before anything reads it. | `test_security_input.py::test_an_oversized_body_is_refused_before_anything_reads_it`, `::test_an_oversized_chunked_body_is_refused_too` |

### Low

| # | Finding | Where | Fix | Regression test |
|---|---------|-------|-----|-----------------|
| L1 | A follow-up could still be edited and read after the care link ended. | `application/follow_ups.py` | `require_care_link` after the ownership check. | `test_security_escalation.py::test_therapist_cannot_change_or_read_a_follow_up_after_the_care_link_ends` |
| L2 | A session could still be started or closed after the care link ended. Starting one also notified the student. | `application/therapy_sessions.py` | `require_care_link` in both. | `test_security_escalation.py::test_therapist_cannot_start_or_close_a_session_after_the_care_link_ends` |
| L3 | An old reset or account set-up link still worked after a password change. | `application/auth/service.py` | A successful reset or set-up marks every other unused link as used. | `test_security_auth.py::test_password_change_invalidates_every_other_reset_or_setup_link` |
| L4 | Another institution's administrator could block someone's password reset by creating an account with the same address. | `application/auth/service.py` | Every active account with that address gets its own link. | `test_security_auth.py::test_another_institution_cannot_block_a_password_reset` |
| L5 | A 500 error was sent without the security headers (CSP, HSTS, nosniff, no-store) and without the request id. | `api/main.py` | The request middleware answers unhandled errors itself, so the headers are applied. | `test_security_auth.py::test_unhandled_errors_keep_security_headers_and_request_id` |
| L6 | A risk alert could be assigned to a care-team therapist who could not open it (suspended, or verification lapsed), so nobody saw it. | `application/escalation.py` | Only an active, verified therapist is chosen. Otherwise the whole counselling team gets the alert. | `test_security_fixes.py::test_an_alert_skips_a_care_team_therapist_who_cannot_open_it` |
| L7 | An unknown `kind` or crisis action from the ML service caused a 500 after the student's message was stored. | `infrastructure/ml_client.py` | Unknown values are a bad response, and the companion fails safe. | `test_security_fixes.py::test_an_unknown_answer_from_the_ai_service_is_a_bad_response` |
| L8 | `%` and `_` acted as wildcards in the student resource search. This only reached resources that were already visible. | `application/directory.py` | The shared `like()` helper with escaping. | `test_security_fixes.py::test_resource_search_treats_wildcards_as_text` |

## 3. Privilege-escalation attempts

All tests named here are in `services/api/tests/test_security_escalation.py` unless another file
is given. "Blocked" means the attempt got 401, 403 or 404, or the data was absent from the
response.

| Attempt | Result | Evidence |
|---------|--------|----------|
| Unauthenticated → every API route | Blocked: more than 150 non-public routes, enumerated from OpenAPI, all return 401 with no token or a garbage token | `test_unauthenticated_every_non_public_route_returns_401` |
| Student → another student's data | Blocked | `test_student_cannot_touch_another_students_records_by_id`, `test_student_lists_and_export_never_include_another_students_records`, `test_student_cannot_read_another_students_wellness_through_staff_routes`, `test_student_cannot_message_another_student_or_another_students_therapist` |
| Student → therapist data | Blocked: only the public profile and open times are visible | `test_student_cannot_reach_therapist_notes_caseload_follow_ups_or_alerts`, `test_student_sees_only_a_therapists_public_profile_and_open_times` |
| Student → teacher data | Blocked | `test_student_cannot_reach_teacher_referrals_rosters_or_class_analytics` |
| Teacher → student private data | Blocked: groups under 10 students are suppressed | `test_teacher_cannot_read_private_data_of_a_student_they_teach`, `test_teacher_small_class_figures_are_suppressed`, `test_analytics_privacy.py` |
| Teacher → therapy notes | Blocked | `test_teacher_views_carry_no_clinical_content_or_individual_wellbeing`, `test_teacher_portal_privacy.py` |
| Therapist → unauthorised student | Blocked for students not on the caseload, revoked consent, ended links (after fixes M2, L1 and L2), other institutions, and unverified therapists | `test_therapist_cannot_reach_a_student_not_on_their_caseload`, `test_therapist_loses_wellbeing_access_when_the_student_revokes_consent`, `test_therapist_loses_student_data_when_the_care_link_ends`, `test_therapist_cannot_reach_another_institutions_student`, `test_unverified_therapist_with_a_care_link_is_refused_every_student_route` |
| Therapist → another therapist's notes | Blocked | `test_therapist_cannot_use_another_therapists_notes_sessions_or_appointments`, `test_therapy_note_confidentiality.py` |
| Admin → therapy notes, messages, companion chats, journals | Blocked. The audit-log side channel is closed by fix M1 | `test_admin_cannot_read_therapy_notes_messages_companion_chats_or_wellbeing`, `test_admin_audit_log_does_not_reveal_care_relationships_or_safety_events` |
| Admin → own role or verification | Blocked | `test_admin_cannot_verify_themselves_or_change_their_own_status` |
| Any role → another institution | Blocked for student, therapist, teacher and administrator | `test_cross_institution_actor_cannot_reach_institution_a_records` |
| Mass assignment | Blocked: only `role` on `POST /admin/users` accepts a privileged field (checked statically over every body model) | `test_no_request_body_accepts_a_privileged_field` and six targeted tests |
| Suspended, deactivated, re-roled or deleted account with an old token | Blocked: every request re-checks the session, status and role | `test_suspended_or_deactivated_account_cannot_keep_using_its_token`, `test_role_change_or_deletion_invalidates_existing_tokens` |
| Probing for existence | Blocked: hidden records answer exactly like missing ones (more than 40 comparisons) | `test_hidden_records_answer_exactly_like_missing_ones` |

## 4. Checked and found sound

- **Authentication and JWT.** Only EdDSA (Ed25519) is accepted, so there is no `none` or HMAC
  confusion. `iss`, `aud`, `exp`, `nbf`, `iat`, `sub`, `jti` and `typ=access` are required. Access
  tokens live in memory only. Refresh tokens are opaque, hashed, single use and rotated, and a
  replay revokes the session. The refresh cookie is `HttpOnly`, `Secure`, `SameSite=Strict` and
  path-scoped. Passwords use Argon2id with rehash. Login gives the same 401 in every failure case,
  with equal timing. Lockout is capped. One-time tokens are hashed, purpose-bound and expire.
- **CSRF.** The refresh cookie is the only cookie credential. Refresh needs an `X-CSRF-Token`
  compared in constant time, plus `SameSite=Strict`. Every other call uses a bearer token.
- **CORS.** An explicit allow-list with no wildcard. Credentials are allowed only for listed
  origins (`test_cors_allows_only_configured_origins`).
- **Rate limiting.** Keyed on the socket address, so forwarding headers cannot dodge it
  (`test_auth_rate_limit_ignores_spoofed_forwarding_headers`). The companion has its own limit.
- **Secrets.** Every secret is required, with no default. The app refuses to start in production
  without a real e-mail sender. No secrets are committed.
- **Error pages.** API docs and OpenAPI are served only in development and test. Errors are
  generic, with no stack traces, and validation errors do not echo input.
- **SQL injection.** Every `text()` call is static with bound parameters. No `ORDER BY` is built
  from input. Admin searches escape wildcards.
- **Input bounds.** Every string, list and page size in request bodies and query parameters is
  bounded. Deeply nested JSON gets a 400.
- **XSS.** No `dangerouslySetInnerHTML` and no markdown rendering. Companion replies render as
  plain text. Links entered by administrators must be `https://` on the server and use
  `rel="noopener noreferrer"`. The login redirect cannot leave the site.
- **Web headers.** A per-request nonce CSP with `strict-dynamic` and `frame-ancestors 'none'`,
  plus HSTS, nosniff, `no-referrer` and `Permissions-Policy`.
- **CSV.** The audit export neutralises formula prefixes. The teacher CSV holds numbers and fixed
  words only. Download filenames are fixed.
- **WebSockets.** The token is sent in the first frame, never in the URL. Events are routed per
  user and clients cannot subscribe to anything. Each user has at most 5 sockets. Frames over
  4 KB are closed.
- **AI conversations.** Only the owner can read a conversation (others get 404). Messages are
  encrypted at rest and expire after 24 hours, or 90 days with consent. Only scrubbed text
  reaches the provider. The model has no tools and no data access. Crisis checks run on input and
  on drafts, and fail safe.
- **Therapy notes.** Encrypted at rest and readable by the authoring therapist only. Access is
  audited.
- **Teacher privacy.** Groups of fewer than 10 consenting students show no figures. Sizes are
  bands and shares are rounded. Payloads carry no student identifiers.
- **ML endpoints.** Every route except health needs a 5-minute HS256 service token with a secret
  of at least 32 characters (`test_service_token_shapes_are_refused`). The client requires https
  outside development and follows no redirects.
- **Logging and audit.** Logs carry ids and event types only, and SQL logging hides parameters.
  Audit details reject content-bearing keys. The audit table is append-only (database triggers)
  and hash-chained per institution.

## 5. Not fixed, with reasons

| Severity | Item | Why it is open | What to do |
|----------|------|----------------|------------|
| Medium | The auth rate limit is per IP, in memory and shared between login and refresh. A campus behind one NAT address shares one bucket. | Needs the planned Redis limiter and a trusted-proxy setting at deployment. | Limit per account and per IP, put refresh in its own bucket, and set uvicorn `FORWARDED_ALLOW_IPS` to the load balancer only. |
| Low | Free text stored in plain text: a therapist's recommendation `rationale` and a student's goal title and description. | Needs a migration to `EncryptedText` with a re-encryption step. | Migrate both columns. |
| Low | WebSocket frames are read up to uvicorn's 16 MiB default before the 4 KB check. Unauthenticated sockets get 10 seconds with no global cap, and pings have no rate limit. | Server flags, not application code. | Run uvicorn with `--ws-max-size 16384` and cap connections at the load balancer. |
| Low | "Forgot password" answers in about 4 ms for an unknown address and about 12 ms for a known one. Registration returns 409 for a student number already in use. | Small enumeration signals. | Queue e-mail sending (never await it in the request), and treat a duplicate student number like a duplicate e-mail. |
| Low | An administrator can create a therapist account and verify it. An administrator-created account is not limited to the institution's own domains. | Product governance (the institution is trusted with its staff list). | Consider two-person verification and a domain check for student accounts. |
| Low | After a care link ends, the therapist's appointment list still shows the student's name and booking reason. | It is the therapist's own appointment history. | Decide with the clinical lead whether past appointments should be anonymised. |
| Info | Field encryption authenticates the column, not the row, so someone with database write access could swap ciphertexts between rows. The audit chain cannot detect deletion of its newest rows until external checkpoints exist. | Documented interim design (DATABASE_DESIGN). | Bind the row id as associated data, and publish chain checkpoints. |
| Info | The CSRF token is stored in `localStorage`. | Deliberate trade-off (ADR 0004). An XSS could read it, but the CSP makes XSS hard. | Keep the CSP strict. |
| Info | Phrasings outside the lexicon (for example "ki ll" split at an odd place) are still missed. | The lexicon is a word list. | Clinical review of the lexicon (SAFETY_SYSTEM.md, section 9). |

## 6. Test results after the fixes

- **API (`services/api`):** 2074 passed. `ruff check`, `ruff format --check` and `mypy --strict`
  on `app` and `tests` are clean.
- **ML service (`services/ml`):** 268 passed, and `ruff` and `mypy` are clean.
- **Web (`apps/web`):** `npm run check` passes: typecheck, lint, format and 484 unit tests.
- **Browser e2e (fresh database):** 148 of 149 passed on the first run. The administrator test
  "writes a resource as a draft, publishes it" failed once, even though the publish request
  itself returned 200: the list reloaded without the search filter. The administrator spec then
  passed in full (18 of 18) on a second fresh database. This looks like a timing issue in that
  page, not something this audit changed.
- **New security tests:**
  - API: `test_security_auth.py`, `test_security_escalation.py`, `test_security_input.py`,
    `test_security_realtime.py`, `test_security_fixes.py`.
  - ML: `test_security_companion.py`, `test_security_service_auth.py`.
  - Web: the verification tests in `auth-pages.test.tsx`.
