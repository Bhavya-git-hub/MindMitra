# ADR 0005: Student portal data access, consent and wellness rules

- Status: Accepted
- Date: 2026-10-10

## Context

The student portal is the first feature that handles real wellbeing data: mood, stress, sleep,
private notes, appointments and messages. Four questions needed a decision that later portals
(therapist, teacher, administrator) will inherit: how a student's own data is addressed, when
someone else may see it, what the software may say about a student's state, and what happens
when a check-in suggests the student is struggling.

## Decision

1. **A student addresses only their own data, and never by id.** Every student endpoint is under
   `/me/...`. There is no student id in a path, query or body, so there is nothing to tamper with.
   Every query still filters by `student_id` and `institution_id` taken from the verified token,
   and resource policies (`can_use_own_student_record`, `can_book_with_therapist`,
   `can_cancel_appointment_as_student`, `can_message_in_conversation`) check again. Anything that
   would reveal another student's record answers `404`, not `403`. The few ids that do appear
   (a therapist, a slot, an appointment) are checked against the caller's institution and
   relationship. Route ids in the web app must be UUIDs before they are put in an API path.
2. **Someone else sees a student's data only through a care-team link plus a live consent.** A
   therapist can read mood entries only while a care-team link is active **and** the student's
   `share_mood_with_care_team` consent is active; withdrawing it takes effect on the next
   request. Private notes on check-ins, journals and therapy notes are never part of that share.
   Teachers and administrators have no route to individual wellbeing data. The data export
   leaves out therapy notes because they belong to the therapist.
3. **The access history shows roles, not people.** `GET /me/privacy/access-history` lists
   successful reads by others with a role and an action only (no names, ids, or content), so
   it informs the student without exposing staff.
4. **A care relationship starts when a therapist confirms the first appointment.** Confirming
   creates the care-team link; until then messaging is closed and the therapist sees nothing.
   Booking is a request (`requested`), limited to 3 upcoming appointments and a 2-hour lead time,
   and the database's exclusion constraints prevent double bookings.
5. **Numbers come with plain words and never a diagnosis.** Indicators ("Feeling good",
   "Mostly calm") and the WHO-5 bands ("Doing well", "Mixed", "Lower lately") are produced on the
   server by pure functions in `domain/wellness`, with the wording tested. Nothing the portal
   says is a clinical conclusion, and every score-bearing screen carries a disclaimer.
6. **Suggestions are rules, not a model.** Recommendations are produced by transparent rules
   (`source = rule`), each with a stated reason, a 14-day lifetime, and de-duplication. The
   student can mark one done or set it aside.
7. **The "support prompt" is information, not detection.** After a low-mood check-in or a
   message with certain phrases, the API may return a `support` object (kind words and a link to
   the urgent-support page). It does not create an alert, notify anyone or store a flag. The
   only way a person is alerted is the student asking: `POST /me/support-requests`, which
   creates a high-priority, human-handled alert (one open request at a time).
   Automated detection and escalation belong to the safety phase and need clinical review.
8. **"Today" is the student's today.** The browser sends its IANA time zone as `?tz=`; the API
   validates it and falls back to UTC. Sleep is stored as two exact instants plus the wake date.
9. **Crisis contacts are data, not code.** They live in `safety.crisis_contacts`, per institution
   or global, and the seeded entries are synthetic demo values. They must be replaced with
   verified contacts before any real use.
10. **The web client loads data through one small hook.** `useQuery` (stale-while-revalidate,
    external store, zod-validated responses) is enough for this portal; TanStack Query can
    replace it later without touching the views' contracts.

## Consequences

- Adding the therapist portal means new permissions and routes, not new rules: the consent and
  care-link checks above are reused, and tests that a teacher or another therapist cannot read
  therapy notes or unshared mood data come with it.
- Because the support prompt is informational, a student in distress who does not reach out
  will not be noticed by the software. This is a known limitation and is stated in the product
  copy and README, not hidden.
- Suggestions are limited by the rules we wrote; they are explainable and cheap to test, and a
  learned model can be added behind the same endpoint later.
- Demo crisis contacts mean the urgent-support page is not safe for real users until an
  institution configures real ones.
