# MindMitra Safety and Escalation System

> **MindMitra is not an emergency service and is not a replacement for emergency services,
> doctors or qualified counsellors.** It cannot diagnose anyone, cannot provide emergency
> treatment and cannot guarantee that a person in danger is noticed. It looks for words and
> patterns that may mean a student needs support, puts help in front of them, and asks a
> person to reach out where the rules below allow. Anyone in immediate danger should call
> their local emergency number.

This document describes the safety system as built. The decisions behind it are in
[ADR 0013](adr/0013-safety-and-escalation-system.md), which builds on
[ADR 0005](adr/0005-student-portal-data-access-and-wellness-rules.md) and
[ADR 0010](adr/0010-ai-wellness-companion-and-safety-layer.md).

## 1. What it is, and what it is not

The safety system is separate from wellness recommendations. A recommendation is an idea a
student can take or leave. A safety concern changes what the product does: suggestions stop,
support comes first and, where allowed, a person is asked to reach out.

It **does**:

- look at check-in notes, a student's messages to their therapist and companion messages for
  language that may signal risk, and at check-in numbers for patterns of low mood or high stress;
- give the student fixed, reviewed guidance, the institution's crisis contacts and a way to
  reach a counsellor;
- pause ordinary suggestions while a serious concern is open;
- ask a person (the student's therapist, or the institution's counselling team) to reach out,
  according to the consent rules in section 4;
- keep a minimal, text-free record that it did so.

It **does not**:

- diagnose, label, assess clinical risk or say anything about a condition;
- give medication, treatment or emergency medical advice;
- contact emergency services, family or anyone outside the institution's counselling team;
- read journals, therapy notes or anything a student has not just written or reported;
- promise that someone will respond within a set time.

## 2. Components

| Component | Where | What it does |
|-----------|-------|--------------|
| `RiskLevel` | `app/domain/safety/risk.py` | `LOW`, `MODERATE`, `HIGH`, `IMMEDIATE`, ordered |
| `SafetyClassifier` | `app/domain/safety/classifier.py` | Turns text and behaviour into a `SafetyAssessment`: a level, a concern category, the detector and whether it is about someone else. Never keeps the text |
| `SafetyPolicy` | `app/domain/safety/policy.py` | Decides what each level does: resources, the suggestion pause, and whether a person is asked, with the basis for asking |
| `EmergencyResource` | `app/domain/safety/resources.py` | A contact, ordered for the level. Never an empty list: a built-in "local emergency services" entry is added when nothing is configured |
| Guidance | `app/domain/safety/guidance.py` | Fixed wording for each level and concern, plus the disclaimer |
| `EscalationWorkflow` | `app/application/safety_workflow.py` | Runs the policy: raises or reuses an alert, records a `SafetyEvent`, builds the student's response, and fails safe |
| `HumanEscalation` | `app/application/safety_workflow.py` | What happened about asking a person: `requested`, `already_open`, `not_requested` or `failed`, with the basis |
| `SafetyEvent` | `safety.safety_events` | The minimal record of a HIGH or IMMEDIATE concern (section 5) |
| `SafetyPanel` | `apps/web/src/components/student/safety-panel.tsx` | Shows the guidance, contacts, counsellor links and disclaimer |

Detection reuses the crisis rules that already guard the companion (`safety/crisis_lexicon.json`
with `crisis_rules.py`), so there is one lexicon for the whole product.

## 3. Risk levels

| Level | Comes from | Student sees | Suggestions | A person is asked |
|-------|------------|--------------|-------------|-------------------|
| `LOW` | Nothing found | Nothing extra. "Get help now" is always in the navigation | As usual | No |
| `MODERATE` | Softer distress language ("I can't cope"), concern about someone else, or behaviour: lowest mood today, highest stress today, or 4 of the last 7 days at mood 2 or below | Kind words, contacts, counsellor links and a one-tap "Ask someone to reach out" | As usual | No |
| `HIGH` | Crisis language about self-harm, suicide, harm to others or an unsafe situation | Guidance, contacts with emergency first, counsellor links | Paused | Depends on the basis (section 4) |
| `IMMEDIATE` | Crisis language with imminence ("tonight", "a plan", "a note"), an explicit "I need help now", or a weapon | "Call your local emergency number now" first, then guidance, contacts and counsellor links | Paused | Yes |

Rules for combining signals:

- The more urgent of words and behaviour wins. On a tie, the words name the concern.
- **Behaviour alone never goes above `MODERATE`.** Numbers can mean many things, so they offer
  help but never alert anyone.
- Concern about another person ("my friend wants to hurt herself") gets guidance for helping
  them, and is never treated as the student's own risk.
- If the classifier fails, the result is `MODERATE` (resources shown) rather than `LOW`.

## 4. Who is asked to reach out, and on what basis

Decided by the project owner (ADR 0013): consent, except in immediate danger.

| Where it was written | `HIGH` | `IMMEDIATE` |
|----------------------|--------|-------------|
| Check-in note, with the "Check my journal and check-in notes for safety concerns" consent | Asked (`consent`) | Asked (`consent`) |
| Check-in note, without that consent | Not asked (`no_consent`). The student is told nobody was told and can ask with one tap | Asked (`vital_interest`) |
| A student's message to their own therapist | Asked (`care_team_message`) | Asked (`care_team_message`) |
| The AI companion | Asked (`companion_notice`) | Asked (`companion_notice`) |

- The consent text says plainly that immediate danger is the exception.
- Students are told before using the companion that a crisis there asks the counselling team
  to reach out (ADR 0010).
- An alert goes to the student's care-team therapist when there is a live care link, otherwise
  to the institution's counselling team (ADR 0010, item 8).
- **The person asked never sees what was written.** An alert carries the category and urgency
  only, and notifications say only that a student may need support.
- An open alert from the same place within 24 hours is reused, and a more urgent concern raises
  its severity, rather than creating a second alert.
- The student is always told the outcome honestly. If raising the alert failed, the product
  says it could not reach anyone and points to the contacts. It never claims someone was told
  when they were not.

## 5. What is logged (minimum necessary)

Only `HIGH` and `IMMEDIATE` concerns are recorded. `MODERATE` and `LOW` leave no record.

`safety.safety_events` holds: the student, the institution, the time, the source (`check_in`,
`message`, `companion`), the level, the concern category, the detector, the rules version,
whether a person was asked and the basis, the alert it raised or reused, whether suggestions
were paused and until when.

It holds **no** text, no excerpt, no matched rule or phrase and no link back to the check-in or
message. The audit entry (`safety_event.create`) holds the same enums and no content.

- Events are deleted after 90 days by the scheduler.
- They are in the student's data export (`safety_events`) and are erased with the student.
- The alert itself follows the existing alert rules (ADR 0010).

## 6. The suggestion pause

At `HIGH` and above, ordinary suggestions stop for 72 hours:

- the recommendation engine does not create new ones, and the list shows only suggestions a
  therapist made;
- the dashboard and suggestions page show the safety panel instead;
- the pause ends early when a therapist resolves or dismisses the alert;
- `GET /me/safety/status` tells the web app whether a pause is active.

## 7. Failing safe

Every step runs in its own savepoint. If raising the alert, reading the contacts, recording
the event or anything else fails, the student still gets guidance and the built-in emergency
entry. At `HIGH` and above the escalation is reported as `failed`, and the student is told to
contact someone directly. A safety failure never blocks saving a check-in or sending a message.

## 8. False positives and false negatives

The rules are a high-recall lexicon. Missing a real crisis costs more than a person dismissing
a false alarm, so the system is tuned to over-flag. Tests in
`services/api/tests/test_safety_classifier.py` pin both directions:

- **Must catch:** immediate, high and moderate phrases, including Hinglish, Hindi,
  stretched letters, leetspeak and ambivalent negations ("I'd never... but sometimes I want to
  die").
- **Must stay low:** everyday idioms ("this assignment is killing me", "I'm dying to see that
  movie", "dead tired"), ordinary words the rules also use ("I have a plan for the weekend",
  "I need help with my assignment now", "I took my medicine today"), and empty input.
- **Accepted false positives (flagged on purpose):** a topic rather than a feeling ("we watched
  Suicide Squad", "our lecture was about suicide prevention"), hyperbole and jokes ("this
  weather makes me want to die lol"), and word collisions ("I want to die my hair blue",
  "starving myself until dinner"). A counsellor dismissing these is the expected cost.
- **False negatives closed in lexicon 2026.10.2 (clinical review pending):** the owner asked for
  these to be fixed before clinical review. They are now must-catch cases in
  `test_safety_classifier.py`, so a regression fails the build.
  - Indirect method or plan: "I've been saving pills and I'm going to take them all" (IMMEDIATE),
    "I have a gun at home and I'm thinking about using it on myself" (IMMEDIATE).
  - Euphemisms: "thinking of ending things", "I want to sleep forever", "I'll be gone soon".
  - Hopelessness and burden (MODERATE): "I'm a burden to everyone", "I don't see a future for
    myself".
  - Obfuscation: "killmyself" with no space, a zero-width joiner between words, every letter
    spaced out.
  - Third person: "my friend said she wants to kill herself", "she wants to end her life"
    (MODERATE, about someone else).
  - Unsafe situations: "someone is stalking me".
- **Still open:** phrasings outside these lists are still not guaranteed. The lexicon is a
  word list, not an understanding of meaning.

Lexicon changes normally need clinical sign-off. These were made on the project owner's
instruction, and the clinical review is still pending. The web tests
(`apps/web/tests/unit/student-safety.test.tsx`) check that every message the student sees
avoids diagnostic and medication words, and never claims someone was told when they were not.

## 9. Before real use

- Replace the demo crisis contacts with verified local ones for each institution.
- Have a qualified clinician review the lexicon, the guidance wording, the known gaps above and
  the 72-hour pause.
- Agree response times and an out-of-hours plan with the counselling team. MindMitra does not
  provide one.
- Make sure students see, before they rely on it, that MindMitra is not an emergency service.
