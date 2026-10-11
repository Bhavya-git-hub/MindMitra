# ADR 0012: Personalised recommendation engine, feedback and preferences

- Status: Accepted
- Date: 2026-10-11
- Amends: [ADR 0011](0011-wellness-indicator-models.md), item 6

## Context

Students already received a few fixed rules ("stress is high, so suggest breathing"). The
project owner asked for a recommendation engine that uses wellness indicators, recent
check-ins, stressors, goals, sleep trends, academic workload, student preferences and earlier
recommendations to match problems with non-medical help: study planning, breaks and workload
planning for academic burnout; placement resources, mock interviews and mentoring for career
worries; clubs, peer activities and social resources for isolation; sleep hygiene, schedule
planning and relaxation for sleep disruption; and counselling for each. Students must be able
to say "helpful" or "not helpful", and that has to improve later suggestions. Nothing may read
as a medical prescription.

## Decision

1. **A transparent scoring engine, not a trained model.** It lives in the API
   (`app/domain/wellness/recommender`), as pure functions with no database or network. There
   is no real outcome data to train on, and a student has to be able to be told why something
   was suggested. For every idea in a fixed catalog (21 ideas in 7 areas):

   `score = need in the area x idea weight x resource fit x what feedback says x goal fit (1.15)`

   Each area's need blends a few weighted signals from the last 14 days: stress and its high
   days, energy, how often academic, career, sleep or relationship stressors are named,
   loneliness and anxiety, sleep length and regularity, mood and its trend, course load,
   year of study, the latest wellbeing check and, when allowed, the indicator bands. Signals
   with no data are left out and the rest re-weighted. An area scores 0 when under half of its
   weight has data, and every area scores 0 with fewer than 3 check-in days in the last 14: the
   engine says nothing rather than guess. Every signal that raises a need carries a plain
   phrase, which becomes the "Lately, ..." reason shown to the student. The weights are
   judgement calls written in code for review, not learned values or clinical thresholds.
2. **Non-medical by construction.** The catalog holds things a student can do or open:
   resources, campus services, a small goal, a check-in. No entry names a condition, treatment,
   medication or dose, and a test fails if catalog wording or any generated reason strays into
   medical language. Counselling is the "next step up", not the first: it appears only when the
   need is at least 0.6 and backed by more than one signal, a lower wellbeing check or one
   overwhelming signal, it moves to the top of the list only at very high need, and at most one counselling idea
   is open at a time.
3. **Short, varied lists.** At most 6 open suggestions, 3 ideas per area, a minimum score of
   0.4. An idea is held back while an earlier suggestion of it is open, for 21 days after it is
   completed, 14 after it is dismissed, and after "not helpful" for 30 days (7 for "not now", 45
   for "already doing this" and for counselling). An idea with no vetted, published resource is
   not offered (counselling and the check-in and goal nudges excepted).
4. **Feedback improves that student's own suggestions, only.** "Helpful" and "not helpful"
   (with an optional reason from a fixed list: not relevant, wrong format, too long, already
   doing this, not now) are stored per suggestion, replaceable and withdrawable. Each idea,
   format, resource and topic gets a multiplier `2(h+1)/(h+n+2)` from that student's own
   responses, clamped to 0.15 to 1.8, with a 60-day half-life. Finishing or dismissing a
   suggestion counts a quarter as much as a rating, and not at all when the student rated it.
   The reason decides what is blamed: "wrong format" counts against the format only, "too long"
   against that resource only, and "already doing this" and "not now" against nothing. Nothing
   is pooled across students and nothing is used to train a shared model.
5. **Preferences.** Preferred resource formats, a longest time per resource, topics (or
   counselling) to switch off, and whether indicators may be used. One row per student; no row
   means the defaults. Muted topics and counselling are never suggested.
6. **Indicators become an input, and still never act.** This amends ADR 0011 item 6, which said
   no recommendation comes from an indicator. When a student allows it (on by default,
   `use_indicators`) and has at least 3 check-in days in the last 14, the API sends the last 28
   days of per-day records to the AI service, without any note, so the tone indicator is not
   used. If the service is down, slow or unconfigured, the engine carries on without indicators.
   Indicators raise a need alongside other evidence; one indicator alone is not enough for
   burnout, stress, sleep or career worries, because each has other signals sharing its weight
   (the social isolation indicator is half of that area's weight, so it can raise it alone).
   Indicators still raise no alert and send no notification, and crisis detection (ADR 0010) is
   unchanged.
7. **Private to the student.** Feedback, reasons and preferences are readable only by the
   student. No therapist, teacher or administrator route returns them, they feed no group
   figure, and they are in the student's data export and erased with the student. A reason is
   a fixed value, never free text. What was recorded about a suggestion (idea, area, format,
   tags, score, signal names and values) is kept on the suggestion itself, so feedback still
   teaches the engine after a resource is edited or removed. Nothing the student wrote is stored
   in it or logged.
8. **One refresh at a time.** A refresh runs after each check-in, stress or sleep entry, and
   wellbeing check, and on request. It takes a per-student advisory lock before reading what
   was suggested, so two quick check-ins cannot add the same idea twice.
9. **Wording.** Titles and reasons use "you could try" language and the disclaimer stays: "An
   optional idea based on what you reported. It is not advice." Each suggestion row records
   the engine version that made it (`recommender-2026.10.1`).

## Consequences

- Students see why each idea appears, can say whether it helped, and see the list adapt to
  their own answers and settings.
- The engine's thresholds are untested against real students. Before real use: review of the
  catalog and the weights by the counselling team, per-institution course-load scales (the
  current 15 to 24 credits is a development default), fairness checks, and an evaluation with
  informed students.
- Learning is deliberately slow and simple: a few answers shift a ranking, none can hide the
  whole catalog. A student who dislikes everything gets fewer suggestions, not different ones.
- Counselling suggestions point at the booking page and the campus counselling resource; they
  do not book anything for the student.
- The old rule set (`domain/wellness/recommendations.py`) is removed. Existing suggestions keep
  working: their new fields are empty and they can still be rated.
- `institution_id` is on every new table, with composite foreign keys, like the rest of the
  student data.
