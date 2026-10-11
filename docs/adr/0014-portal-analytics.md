# ADR 0014: Analytics for every portal

- Status: Accepted
- Date: 2026-10-11
- Builds on: [ADR 0007](0007-teacher-portal-aggregation-thresholds-and-referrals.md),
  [ADR 0008](0008-administrator-portal-scope-and-confidentiality.md),
  [ADR 0011](0011-wellness-indicator-models.md)

## Context

The project owner asked for analytics in all four portals, built with privacy-preserving
aggregation and the frontend charting library, with tests for aggregation and privacy
thresholds. Teacher analytics (class and department stress, burnout-style strain and wellness
trends) and the administrator's institution-wide figures already existed under the cohort rules
of ADR 0007 and 0008, so they are reused unchanged and only re-verified. Students already had
daily trends but no weekly view or goal progress. Therapists and administrators had no trends,
utilisation or engagement figures.

## Decision

1. **Computed live from the existing tables. No `analytics` schema and no migration.** Each
   figure is a query over completed calendar weeks (4, 8 or 12, Monday to Sunday UTC), so there
   is no second copy of student data to protect. The `analytics.*` tables in
   [DATABASE_DESIGN.md](../DATABASE_DESIGN.md) stay unbuilt until volume needs them.
2. **No new permissions and no new chart library.** Student analytics uses `wellness:read:own`,
   therapist analytics `therapist_profile:manage` (as the dashboard does), administrator
   analytics `platform_analytics:read`. Charts use the existing `recharts` wrappers in
   `apps/web/src/components/charts`, each with an accessible data table.
3. **Student** (`GET /me/wellness/analytics`): the caller's own weekly mood, stress, sleep and
   a *wellness index*, their last 12 WHO-5 results, and goal progress (counts, average progress,
   by category, completed per week). The wellness index is the plain average of mood, inverted
   stress and sleep quality on a 0 to 100 scale, needing at least two of the three. It is a
   self-report summary, not a clinical measure, and the endpoint says so.
4. **Therapist** (`GET /therapist/analytics`): weekly caseload averages, the therapist's own
   appointment statistics, intervention progress and risk alerts. Caseload averages include only
   students with a live care link *and* an active `share_mood_with_care_team` consent, taking
   each student's weekly mean first so a heavy logger does not outweigh others. No student,
   name, note, title or alert excerpt is read or returned. *Intervention progress* means the
   therapist's own recommendations (by status and completion rate) and follow-ups (by status,
   overdue, done on time). Alerts are the ones the therapist can already list: assigned to them,
   or unassigned and so the counselling team's.
5. **Teacher** (existing endpoints): unchanged. Groups need 10 students who agreed to
   anonymous aggregate research, sizes are bands, shares round to 5 and hide small groups. No
   individual is identifiable; a test now sweeps the payloads for ids, emails, notes and
   per-student keys.
6. **Administrator** (`GET /admin/analytics/services`, beside the existing `/admin/analytics`
   and appointment oversight): platform usage (check-ins, active students, companion and
   therapist message counts, sign-ins), counselling utilisation (hours booked over hours offered,
   by week and mode, rounded to 5 percent) and intervention engagement (system suggestions by
   source and problem area). Counts of 1 to 4 are returned as `null`, a booked-hours cell with
   fewer than 5 bookings is `null`, and an engagement group is shown only when 5 different
   students are in it. Message bodies are never read, only roles and timestamps.
7. **Helpfulness feedback is aggregated for administrators.** `ai.recommendation_feedback` is
   otherwise the student's own. Administrators see only group counts of helpful and not-helpful
   (groups of at least 5 students, shares needing at least 10), never who answered.
8. **Wording stays non-diagnostic.** Every payload carries a disclaimer that figures describe
   what people reported and are not a diagnosis or clinical assessment.

## Consequences

- Live queries are fine at the current scale. A large institution may need the pre-aggregated
  `analytics` tables later; the response shapes would not change.
- With one consenting student, a therapist's caseload average equals that student's value. This
  discloses nothing beyond the per-student trends the therapist can already read with consent.
- Administrator figures are cautious: a small institution will see many `null` cells, by design.
- Differential-privacy noise (ARCHITECTURE decision D7) is still off; k-anonymity thresholds
  and rounding are the protection.
