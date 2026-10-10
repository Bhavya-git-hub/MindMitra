# ADR 0006: Therapist portal access, professional verification and note confidentiality

- Status: Accepted
- Date: 2026-10-10

## Context

The therapist portal is where the most sensitive data in MindMitra is read and written: a
student's check-ins, risk alerts and the therapist's own clinical notes. The student portal
(ADR 0005) already decided that a care-team link plus the student's consent opens student data.
The therapist portal needed four more decisions: who counts as a therapist, who may read a
therapy note, how alerts are claimed and closed, and what the interface may hide.

## Decision

1. **Only a verified therapist reaches student data.** `org.therapists.verification_status` is
   `pending` until an administrator of the same institution sets `verified` (never for
   themself). "Expired" is derived from `licence_expires_on`, not stored. Pending, rejected and
   expired therapists can use their profile, availability, dashboard and verification form, but
   every route that touches a student answers `403` (`require_verified`), including messaging
   and the older `/students*` routes. Students can neither see nor book an unverified
   therapist. A therapist who loses verification loses access on the next request.
2. **A care link is required for any student data; consent narrows it further.** No active
   link answers `404`, so a therapist cannot learn which students exist. Check-in trends need
   `share_mood_with_care_team` and WHO-5 results need `share_assessments_with_care_team`;
   without them the API answers `403` and the profile reports which shares are active so the
   interface can say so. Private notes on a student's check-ins are never returned. Ending the
   link ends access immediately, for notes too.
3. **A therapy note can be read only by the therapist who wrote it.** Not the student, teachers,
   administrators (of any institution), another therapist, a colleague on the same care team, or
   a therapist in another institution. The rule is enforced in three places: the route needs
   `therapy_note:read` (students, teachers and admins do not have it), the policy checks
   authorship and a live care link, and every query filters by `therapist_id` and
   `institution_id`. Denials are audited and the response message is generic.
4. **Notes are versioned and never overwritten.** Each save writes a new row; the previous one
   gets `locked_at`. Earlier versions can be read, none can be changed. Text is encrypted at rest
   (`EncryptedText`), responses carry `Cache-Control: no-store, private`, and the audit log
   records the action and version number, never content. Note text is never sent in a URL, query
   string, log line, notification or `localStorage`.
5. **Alerts are claimed, not broadcast.** A therapist sees alerts assigned to them, plus
   unassigned ones for students on their care team; acknowledging an unassigned alert assigns it.
   Resolving needs one of a fixed set of outcomes. No free text is stored, so the alert trail
   cannot become a second place for clinical content. The interface calls an alert "a prompt for
   care, never a conclusion". Nothing in this phase detects risk automatically (see ADR 0005,
   item 7).
6. **Follow-ups and recommendations are scoped to the care team.** A follow-up is private to the
   therapist (encrypted note) and may link only to that therapist's own session. A recommendation
   a therapist makes for a student appears to the student as "From your therapist" with the
   therapist's stated reason, and can be dismissed like any other.
7. **The interface only explains; the API decides.** Pages that touch students are wrapped in a
   `RequireVerified` component so a pending therapist sees why a page is closed rather than an
   error. Tests prove the API refuses the same requests directly, so removing the component
   would not expose anything.
8. **Sessions start when they are due.** A confirmed appointment can be started from 15 minutes
   before until a day after it ends; the server computes `can_start` so the browser never has to
   compare clocks.

## Consequences

- Authorization is tested from the other side: `test_therapy_note_confidentiality.py` attempts to
  read and write notes as a student, another student, a teacher, an administrator in both
  institutions, an unrelated therapist, a colleague on the same care team, a therapist from
  another institution, an anonymous and a tampered caller, and after the care link ends, the
  verification is withdrawn or the account is deactivated. It also checks that note text appears
  in no other response, in no audit row, and not in plaintext in the database.
  `test_therapist_portal_authz.py` runs a role matrix across every therapist route.
- Verification is a manual administrator step, and there is no administrator screen for it yet
  (API only). Until that exists, seeded demo data is the only way to see a verified therapist
  without using the API directly.
- A therapist who is the only member of a care team and loses verification leaves their students
  without a visible clinician until an administrator acts. Escalation for that case belongs to
  the administrator portal.
- Messaging still lives under `/me/conversations`, shared with students, which keeps one set of
  rules but means the therapist interface borrows the student client wrapper.
