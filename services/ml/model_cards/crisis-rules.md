# Model card: crisis rules (`crisis-rules-2026.10.1`)

## Purpose

Finds messages that suggest a student may not be safe, so that a **person** is asked to reach
out and crisis contacts are shown at once. It never diagnoses, scores a person or acts on a
student. It runs in the API on every companion message (before limits, switches or the AI
service) and again in the AI service on the message and on the model's draft.

## What it is

A deterministic lexicon (`safety/crisis_lexicon.json`, 25 rules) with a small matcher
(`safety/crisis_rules.py`, standard library only). It is not a trained model. The API keeps a
byte-identical copy, and a test fails if the two differ.

- **Categories:** suicidal ideation, self-harm, harm to others, abuse or an unsafe situation,
  acute distress (escalate), and distress signals such as hopelessness (review only: gentle
  support, no alert).
- **Severity:** high by default. Imminence words (tonight, a plan, saved pills, a note,
  goodbye) raise suicidal, self-harm and harm-to-others matches to imminent.
- **Robustness:** case and curly quotes, stretched letters ("diiiie"), spaced letters,
  leetspeak ("k1ll"), common slang ("kms", "unalive"), Hinglish and Hindi.
- **Negation:** explicit patterns ("I would never kill myself") stand down a match unless the
  message also sounds ambivalent ("but", "though", "sometimes").
- **About someone else:** a self-directed rule written about another person ("my roommate
  wants to die") is still escalated, with guidance on helping them.

## Evaluation (synthetic data only)

| Suite | Cases | Requirement | Result |
|-------|-------|-------------|--------|
| `tests/suites/crisis_never_miss.yaml` | 47 | Every case escalates, with the expected category and at least the expected severity | 47/47 |
| `tests/suites/crisis_not_escalated.yaml` | 19 | Hyperbole, idioms, negations and everyday stress do not escalate | 19/19 |

Adding a never-miss phrase is always welcome. Removing one needs clinical sign-off.

## Limitations

- It matches wording, not meaning. Indirect or novel phrasing can be missed, and some idioms
  will be flagged. It is tuned for recall: a false alert costs a person's time, while a missed
  crisis can cost far more.
- It covers English, Hinglish and some Hindi only.
- The cases are written by the team, not drawn from real students, so performance on real
  messages is unknown. Missed-crisis reviews must feed new cases back into the suite.
- A trained classifier may be added alongside it later. It will never replace it.

## Owners and review

Safety lead and clinical advisor. Review the lexicon and both suites at least each term, and
after any missed-crisis review.
