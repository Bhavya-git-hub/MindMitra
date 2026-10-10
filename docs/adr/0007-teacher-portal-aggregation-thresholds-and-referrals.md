# ADR 0007: Teacher portal, aggregation thresholds and referrals

- Status: Accepted
- Date: 2026-10-10

## Context

Teachers are the people closest to students' daily academic life and the people with the least
reason to see their mental-health data. The portal had to give them useful, group-level signals
(is stress rising before exams?) and a safe way to ask for help for one student, without
becoming a route to anyone's private records. The main risk is inference: a "class average"
from three students is nearly a personal record.

## Decision

1. **Opt-in.** A student counts toward any group figure only while they hold an active
   `anonymous_aggregate_research` consent and their account is active. Withdrawing consent
   removes their past entries from the next request, not only future ones. The older
   `/insights/mood-summary` follows the same rule.
2. **Thresholds live in one pure module** (`domain/wellness/cohort.py`) and every number a
   teacher sees passes through it.
   - A figure needs at least **10 different consenting students** (`MIN_COHORT`); below that the
     API answers with a `too_small` state and no numbers.
   - A **share** also needs **5 students on each side** (`MIN_GROUP`). Otherwise it says "a few"
     or "most", never a percentage, so a group of ten cannot reveal that exactly one student is
     struggling. Percentages are rounded to the nearest 5, averages to one decimal.
   - Group sizes are bands ("10 to 19", "20 to 49", "50 to 99", "100 or more"), not counts.
   - WHO-5 bands are hidden when fewer than 10 students have a check in the window.
3. **Fixed, completed windows.** Only 4, 8 or 12 *completed* calendar weeks (UTC Mondays) can be
   requested; anything else is `422`. The week in progress is never included: its averages move
   with every check-in, so a teacher who looked twice could work out one student's answer from the
   change. Arbitrary date ranges would let a caller subtract two overlapping windows to isolate a
   week or a student. The legacy `/insights/mood-summary` follows the same rule.
4. **"Strain" is a pattern, not burnout or a diagnosis.** It counts students whose two-week
   average shows at least two of low energy (≤ 2.0), high stress (≥ 4.0) and short sleep
   (< 6 h). The interface and reports say so. Supportive suggestions are rule-based, describe
   the group, and never name a person or a condition.
5. **Teachers address groups they belong to.** A class must be one the teacher teaches (`404`
   otherwise); a department view needs the teacher to belong to it (`403`). Administrators can
   read any department of their institution.
6. **Class rosters carry no wellbeing data.** A teacher already knows who is in their class; the
   roster is names only and exists to pick a student for a referral.
7. **Referrals are narrow and one-way.** A teacher can refer only a student enrolled in a class
   they teach (policy plus composite foreign keys). They choose a category, urgency and an
   optional short note (encrypted at rest). One live referral per teacher and student (`409`),
   10 a day. The teacher later sees only category, urgency, their note and status. They do not
   see who picked it up or the outcome.
8. **Verified therapists triage.** The queue holds referrals for care-team students plus students
   with no care team. Claiming one hides it from other therapists, sends the student a neutral,
   content-free notification (payload `{}`), and closing needs a fixed outcome. A `safety_concern`
   referral also creates a high-severity `RiskAlert` (source `faculty_referral`, no excerpt) for
   humans to act on. Nothing is automated.
9. **Student-initiated requests are the only way a teacher learns about an individual.** A
   student picks their own class, teacher and what would help. The teacher can acknowledge or
   close it and sees only that. Teachers cannot see check-ins, journals, AI conversations,
   messages, therapy notes or diagnoses, and there is no route that returns them (the
   allow-list test fails if one is added without a decision).
10. **Faculty resources** carry a `faculty` tag. Teachers and administrators see only
    faculty-tagged resources; students and therapists never see them.
11. **Retention.** Referral foreign keys are `RESTRICT` so a course cannot be deleted away from a
    referral that may matter later. Support-request foreign keys `CASCADE`.
12. **Anonymous reports** (text and CSV) contain only numbers and fixed words, and are produced
    from the same already-thresholded figures.

## Consequences

- `test_teacher_portal_privacy.py` proves the claim from the other side: it lists every route a
  teacher may call, refuses all others, plants sentinel text in journals, messages, AI
  conversations and therapy notes and crawls every teacher response for it, and checks the
  responses for diagnostic or clinical keys. `test_teacher_portal_authz.py` runs a role matrix
  over the teacher routes. `test_cohort_rules.py` tests the thresholds directly, and the
  analytics and referral tests cover consent withdrawal, small groups and cross-teacher access.
- **Residual risk: overlapping groups.** A class and its department, or two classes sharing
  students, can be compared. A teacher in a department of 12 who also teaches a class of 11 of
  those students could subtract the two and reason about one student. Fixed windows, rounding
  and shares limit how much this reveals, but do not remove it. A production deployment should
  add a rule that suppresses a group when its complement is under the threshold, once real
  institution structures are known.
- **Residual risk: the shared referral queue.** Unassigned referrals are visible to every
  verified therapist in the institution until one claims it. This keeps students without a
  care team from being invisible, at the cost of some therapists seeing referrals about
  students they will not treat.
- The default window is 8 completed weeks and seed history is about 6 weeks, so the oldest weeks
  of a default view are empty in the demo.
- **Residual risk: changes to completed weeks.** A late edit to a past sleep entry, or a student
  granting or withdrawing consent, changes a completed week's figures. A teacher who polls can
  see the change, though not choose it. Freezing each week when it closes would remove this, at
  the cost of a delayed, batch-computed report. Not done yet; flagged for a decision.
- Consent coverage affects usefulness: with 80% opt-in in the seed data most classes pass the
  threshold; in real use many may not, and the interface says "not enough students yet" rather
  than guessing.
