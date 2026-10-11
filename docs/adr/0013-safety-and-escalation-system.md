# ADR 0013: A dedicated safety and escalation system

- Status: Accepted
- Date: 2026-10-11
- Amends: [ADR 0005](0005-student-portal-data-access-and-wellness-rules.md), item 7
- Builds on: [ADR 0010](0010-ai-wellness-companion-and-safety-layer.md)

## Context

Until now only the AI companion looked for crisis language. A check-in note or a message to a
therapist could only show a "support prompt" (ADR 0005, item 7): kind words and a link, with no
alert and no record. The project owner asked for a dedicated safety and escalation system,
explicitly not a kind of recommendation, with four risk levels, immediate-support guidance,
crisis resources, counsellor access, minimal logging, consent rules and extensive tests for
false positives and false negatives. It must not diagnose or try to provide emergency
treatment, and must say that it is not a replacement for emergency services or qualified
professionals.

## Decision

1. **Safety is its own layer, run before anything else and separate from suggestions.**
   `SafetyClassifier`, `SafetyPolicy`, `EmergencyResource` and the guidance live in
   `app/domain/safety` as pure code. `EscalationWorkflow` (`app/application/safety_workflow.py`)
   runs them for check-ins, a student's messages and the companion. The recommendation engine
   only reads one thing from it: whether suggestions are paused.
2. **Four levels: `LOW`, `MODERATE`, `HIGH`, `IMMEDIATE`.** Words come from the existing crisis
   rules (one lexicon for the product). `IMMEDIATE` comes from imminence words, an explicit
   request for help now, or a weapon. Behaviour (lowest mood today, highest stress today, or 4
   low days in 7) reaches `MODERATE` at most and never alerts anyone.
3. **What each level does.** `MODERATE` and above show guidance, contacts and counsellor
   access. `HIGH` and above pause ordinary suggestions for 72 hours (ending early when the
   alert is resolved or dismissed) and may ask a person to reach out. `IMMEDIATE` leads with
   the emergency number.
4. **Consent, except in immediate danger** (the project owner's choice). A check-in note at
   `HIGH` alerts someone only with the `journal_safety_scanning` consent. At `IMMEDIATE` it
   always does, as a vital-interest exception that the consent text now states. A student's
   message to their own therapist and the companion always alert, because the student wrote to
   their care team, or was told in advance. A student who was not escalated is told that nobody
   was told, and can ask with one tap (`POST /me/support-requests`).
5. **Minimal logging.** A `SafetyEvent` is written only at `HIGH` and `IMMEDIATE`. It stores
   enums, a rules version, the basis and the alert id: no text, no matched rule and no link to
   the source. Events are deleted after 90 days, exported and erased with the student. The
   alert itself shows category and urgency only (ADR 0010, item 8).
6. **Fail safe and honest.** Each step runs in a savepoint. If any step fails, the student
   still gets guidance and the built-in emergency entry, and is told that nobody could be
   reached. The product never says someone was told when they were not.
7. **Known gaps are tested, not hidden.** False positives are pinned at their current level,
   and false negatives the lexicon misses are strict expected failures that wait for clinical
   review. See [SAFETY_SYSTEM.md](../SAFETY_SYSTEM.md), section 8.

This replaces ADR 0005, item 7: the "support prompt" is now the `MODERATE` response, and
automated escalation exists, within the consent rules above.

## Consequences

- A student who writes about being in immediate danger in a check-in note is noticed by a
  person even without consent. This is a deliberate exception and the consent text says so.
- A student who writes about being at high risk without consent is not escalated
  automatically. They see everything else, and the product says that nobody was told.
- The lexicon flags some messages that are not crises and misses some that are. A counsellor
  dismissing a false alarm is the accepted cost; the documented misses need clinical review
  before real use.
- MindMitra still does not contact emergency services or anyone outside the counselling team,
  and does not guarantee response times. It is not a replacement for emergency services or
  qualified professionals.
