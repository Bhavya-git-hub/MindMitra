"""The safety classifier, policy, guidance and resources on their own (no database).

The corpus is synthetic and grouped by what must happen:

- **False negatives** (must be caught): IMMEDIATE, HIGH and MODERATE phrasings, including
  obfuscation (stretched letters, leetspeak, full-width characters, curly apostrophes, odd
  case), Hinglish and Hindi, ambivalent negations and third-person concern.
- **False positives** (must stay LOW): everyday idioms about killing, dying, cutting and
  shooting that students write all the time.
- **Accepted false positives**: phrasings the rules flag on purpose because recall comes first
  (a person reviews and can dismiss every alert). They are pinned so a change is deliberate.
- **Closed gaps**: phrasings the rules used to miss, now caught by lexicon version 2026.10.2.
  They are must-catch cases, so a regression fails the build. Clinical review of the lexicon
  (``crisis_lexicon.json``) is still pending.
"""

import dataclasses

import pytest

from app.domain.safety.classifier import (
    CLASSIFIER,
    IMMEDIATE_RULES,
    BehaviourSnapshot,
    SafetyAssessment,
    SafetyClassifier,
)
from app.domain.safety.guidance import DISCLAIMER, guidance_for
from app.domain.safety.policy import DEFAULT_POLICY, EscalationBasis, SafetyPolicy
from app.domain.safety.resources import FALLBACK, EmergencyResource, arrange
from app.domain.safety.risk import Concern, Detector, RiskLevel, Source
from app.domain.wellness.support_prompt import show_support_prompt

IMMEDIATE = RiskLevel.IMMEDIATE
HIGH = RiskLevel.HIGH
MODERATE = RiskLevel.MODERATE
LOW = RiskLevel.LOW


def level(text: str) -> RiskLevel:
    return CLASSIFIER.assess_text(text).level


# ---- false negatives: immediate danger ------------------------------------------------------

MUST_BE_IMMEDIATE = [
    # a plan, a time, means or a note, with suicidal language
    ("I have a plan to kill myself tonight", Concern.SUICIDAL_LANGUAGE),
    ("I wrote a note. I want to die", Concern.SUICIDAL_LANGUAGE),
    ("I'm going to jump off the hostel roof tonight", Concern.SUICIDAL_LANGUAGE),
    ("kms tonight", Concern.SUICIDAL_LANGUAGE),
    ("going to end my life after everyone sleeps", Concern.SUICIDAL_LANGUAGE),
    ("I bought a rope, I'm going to hang myself", Concern.SUICIDAL_LANGUAGE),
    ("I've stockpiled tablets and I'm ready to die", Concern.SUICIDAL_LANGUAGE),
    (
        "this is my last message, goodbye everyone, I don't want to live",
        Concern.SUICIDAL_LANGUAGE,
    ),
    ("k1ll mys3lf t0night", Concern.SUICIDAL_LANGUAGE),
    ("i'm going to take all my sleeping pills tonight", Concern.SELF_HARM_LANGUAGE),
    ("im gonna od tonight", Concern.SELF_HARM_LANGUAGE),
    # an explicit emergency, without any imminence word
    ("please call an ambulance", Concern.ACUTE_DISTRESS),
    ("this is an emergency", Concern.ACUTE_DISTRESS),
    ("I need help right now", Concern.ACUTE_DISTRESS),
    # a weapon on campus
    ("I'm bringing a knife to class tomorrow", Concern.HARM_TO_OTHERS),
]


@pytest.mark.parametrize(("text", "concern"), MUST_BE_IMMEDIATE)
def test_immediate_danger_is_immediate(text: str, concern: Concern) -> None:
    found = CLASSIFIER.assess_text(text)
    assert found.level is IMMEDIATE, found
    assert found.concern is concern
    assert found.alert_severity == "imminent"
    assert found.detector is Detector.RULES


# ---- false negatives: high concern ----------------------------------------------------------

MUST_BE_HIGH = [
    ("I want to kill myself", Concern.SUICIDAL_LANGUAGE),
    ("I've been thinking about suicide a lot", Concern.SUICIDAL_LANGUAGE),
    ("I feel suicidal", Concern.SUICIDAL_LANGUAGE),
    ("I don't want to be alive anymore", Concern.SUICIDAL_LANGUAGE),
    ("I don't want to wake up tomorrow", Concern.SUICIDAL_LANGUAGE),
    ("everyone would be better off without me", Concern.SUICIDAL_LANGUAGE),
    ("I wish I was dead", Concern.SUICIDAL_LANGUAGE),
    ("there's no point in living", Concern.SUICIDAL_LANGUAGE),
    ("I want to end it all", Concern.SUICIDAL_LANGUAGE),
    ("I want to stop existing", Concern.SUICIDAL_LANGUAGE),
    ("I'm thinking about taking my own life", Concern.SUICIDAL_LANGUAGE),
    ("i want to kms", Concern.SUICIDAL_LANGUAGE),
    ("I wanna unalive myself", Concern.SUICIDAL_LANGUAGE),
    ("I keep hurting myself when I'm stressed", Concern.SELF_HARM_LANGUAGE),
    ("I started cutting again", Concern.SELF_HARM_LANGUAGE),
    ("I want to hurt myself", Concern.SELF_HARM_LANGUAGE),
    ("I took too many pills", Concern.SELF_HARM_LANGUAGE),
    ("I'm going to overdose", Concern.SELF_HARM_LANGUAGE),
    ("selfharm", Concern.SELF_HARM_LANGUAGE),
    ("I can't go on like this", Concern.ACUTE_DISTRESS),
    ("I'm having a panic attack and I can't breathe", Concern.ACUTE_DISTRESS),
    ("my uncle hits me", Concern.UNSAFE_SITUATION),
    ("he raped me", Concern.UNSAFE_SITUATION),
    ("I'm being abused at home", Concern.UNSAFE_SITUATION),
    ("I'm being blackmailed with my photos", Concern.UNSAFE_SITUATION),
    ("I don't feel safe at home", Concern.UNSAFE_SITUATION),
    ("he threatened to kill me", Concern.UNSAFE_SITUATION),
    ("I'm scared he'll hurt me", Concern.UNSAFE_SITUATION),
    ("I want to kill my roommate", Concern.HARM_TO_OTHERS),
    ("I'm going to hurt him", Concern.HARM_TO_OTHERS),
]


@pytest.mark.parametrize(("text", "concern"), MUST_BE_HIGH)
def test_crisis_language_is_high(text: str, concern: Concern) -> None:
    found = CLASSIFIER.assess_text(text)
    assert found.level is HIGH, found
    assert found.concern is concern
    assert found.alert_severity in ("moderate", "high")
    assert not found.about_someone_else


OBFUSCATED = [
    "I want to diiiiie",  # stretched letters
    "I want to d1e",  # leetspeak
    "Kill MySelf",  # odd case
    "I want to kill myself!!!!",  # punctuation
    "I’m going to kill myself",  # curly apostrophe
    "Ｉ ｗａｎｔ ｔｏ ｄｉｅ",  # full-width characters
    "khudkushi kar lunga",  # Hinglish
    "mujhe jeena nahi hai",  # Hinglish
    "जीना नहीं चाहता",  # Hindi
]


@pytest.mark.parametrize("text", OBFUSCATED)
def test_obfuscated_and_other_language_crisis_is_still_caught(text: str) -> None:
    assert level(text).at_least(HIGH), text


def test_an_ambivalent_negation_still_counts() -> None:
    found = CLASSIFIER.assess_text("I'd never hurt myself but sometimes I want to die")
    assert found.level is HIGH
    assert found.concern is Concern.SUICIDAL_LANGUAGE


def test_imminence_needs_crisis_language_and_lifts_it_to_immediate() -> None:
    assert level("I want to kill myself") is HIGH
    assert level("I want to kill myself tonight") is IMMEDIATE
    assert level("see you tonight after class") is LOW  # a time on its own is nothing


def test_every_immediate_rule_is_a_real_lexicon_rule() -> None:
    from app.domain.safety import crisis_rules

    ids = {r.id for r in crisis_rules.lexicon().rules}
    assert IMMEDIATE_RULES <= ids


# ---- false negatives: moderate (support shown, nobody alerted) ------------------------------

MUST_BE_MODERATE = [
    ("I feel hopeless", Concern.DISTRESS_LANGUAGE, False),
    ("I feel worthless and empty inside", Concern.DISTRESS_LANGUAGE, False),
    ("nobody would even notice if I disappeared", Concern.DISTRESS_LANGUAGE, False),
    ("nobody would miss me", Concern.DISTRESS_LANGUAGE, False),
    ("what's the point of anything", Concern.DISTRESS_LANGUAGE, False),
    ("I want to disappear forever", Concern.DISTRESS_LANGUAGE, False),
    ("I can't do this anymore", Concern.DISTRESS_LANGUAGE, False),
    ("I don't want to be here", Concern.DISTRESS_LANGUAGE, False),
    # an explicit negation keeps support on screen but asks nobody
    ("I would never kill myself", Concern.DISTRESS_LANGUAGE, False),
    ("I'm not suicidal, just tired", Concern.DISTRESS_LANGUAGE, False),
    ("I don't want to kill myself, I just want the pain to stop", Concern.DISTRESS_LANGUAGE, False),
    # worry about someone else: guidance for helping them
    ("my roommate is talking about suicide", Concern.CONCERN_FOR_OTHER, True),
    ("my brother keeps saying he wants to die", Concern.CONCERN_FOR_OTHER, True),
]


@pytest.mark.parametrize(("text", "concern", "other"), MUST_BE_MODERATE)
def test_distress_language_is_moderate(text: str, concern: Concern, other: bool) -> None:
    found = CLASSIFIER.assess_text(text)
    assert found.level is MODERATE, found
    assert found.concern is concern
    assert found.about_someone_else is other


# ---- false positives: everyday words that must stay LOW -------------------------------------

MUST_STAY_LOW = [
    "this assignment is killing me",
    "the deadline is going to kill me",
    "I could kill for a coffee right now",
    "I killed it in the presentation",
    "the professor killed the curve",
    "that joke killed me",
    "I'm going to murder this exam",
    "I'm dead tired after the lab",
    "my laptop died during the exam",
    "my phone battery is dead",
    "over my dead body",
    "I'm dying to see that movie",
    "shoot me a text later",
    "I cut my hair today",
    "cutting down on caffeine",
    "I hurt my knee playing football",
    "I need help with my assignment now",
    "I panicked a bit during the quiz",
    "I'm so done with this semester",
    "I took my medicine today",
    "I ended up taking all my notes home",
    "see you tonight after class",
    "I have a plan for the weekend",
    "I wrote a note to my professor",
    "Feeling good, slept well, exams went fine",
    "",
    "   ",
    "😊👍",
]


@pytest.mark.parametrize("text", MUST_STAY_LOW)
def test_everyday_idioms_are_not_flagged(text: str) -> None:
    found = CLASSIFIER.assess_text(text)
    assert found.level is LOW, found
    assert found.concern is None


# ---- accepted false positives: recall first, a person dismisses ------------------------------

ACCEPTED_FALSE_POSITIVES = [
    # The rules cannot tell a topic from a feeling.
    ("we watched Suicide Squad", HIGH),
    ("our psychology lecture was about suicide prevention", HIGH),
    ("I'm reading a book about self-harm awareness for my project", HIGH),
    # Hyperbole and jokes look the same as the real thing in a few words.
    ("this weather makes me want to die lol", HIGH),
    ("I want to die. Just kidding, exams are fine", HIGH),
    # Words that collide with the patterns.
    ("I want to die my hair blue", HIGH),
    ("I'm starving myself until dinner because the mess food is bad", HIGH),
]


@pytest.mark.parametrize(("text", "expected"), ACCEPTED_FALSE_POSITIVES)
def test_accepted_false_positives_are_pinned(text: str, expected: RiskLevel) -> None:
    """Flagged on purpose: missing a real crisis costs more than a person dismissing a false
    alarm. If one of these changes, update this list and ADR 0013 together."""
    assert level(text) is expected


# ---- closed gaps: false negatives fixed in lexicon 2026.10.2 (now must-catch) ---------------

CLOSED_GAPS = [
    ("I've been saving pills and I'm going to take them all", IMMEDIATE),
    ("I have a gun at home and I'm thinking about using it on myself", IMMEDIATE),
    ("I've been thinking of ending things", HIGH),
    ("I want to sleep forever", HIGH),
    ("I'll be gone soon", HIGH),
    ("I'm a burden to everyone", MODERATE),
    ("I don't see a future for myself", MODERATE),
    ("killmyself", HIGH),  # no space between the words
    ("kill‍myself", HIGH),  # a zero-width joiner instead of a space
    ("i w a n t t o d i e", HIGH),  # every letter spaced out, words run together
    ("my friend said she wants to kill herself", MODERATE),
    ("she wants to end her life", MODERATE),
    ("someone is stalking me", HIGH),
]


@pytest.mark.parametrize(("text", "expected"), CLOSED_GAPS)
def test_closed_gaps_are_caught(text: str, expected: RiskLevel) -> None:
    assert level(text).at_least(expected)


# ---- behaviour: numbers offer help, never alert ---------------------------------------------


@pytest.mark.parametrize(
    ("snapshot", "concern"),
    [
        (BehaviourSnapshot(mood_today=1), Concern.LOW_MOOD_TODAY),
        (BehaviourSnapshot(mood_today=3, stress_today=5), Concern.HIGH_STRESS_TODAY),
        (BehaviourSnapshot(mood_today=3, low_mood_days=4), Concern.SUSTAINED_LOW_MOOD),
        (BehaviourSnapshot(mood_today=1, stress_today=5, low_mood_days=7), Concern.LOW_MOOD_TODAY),
    ],
)
def test_concerning_numbers_are_moderate_at_most(
    snapshot: BehaviourSnapshot, concern: Concern
) -> None:
    found = CLASSIFIER.assess_behaviour(snapshot)
    assert found.level is MODERATE
    assert found.concern is concern
    assert found.detector is Detector.BEHAVIOUR
    assert not DEFAULT_POLICY.decide(found, source=Source.CHECK_IN, scanning_consent=True).escalate


@pytest.mark.parametrize(
    "snapshot",
    [
        BehaviourSnapshot(),
        BehaviourSnapshot(mood_today=2),
        BehaviourSnapshot(mood_today=3, stress_today=4),
        BehaviourSnapshot(mood_today=4, low_mood_days=3),
        None,
    ],
)
def test_ordinary_numbers_are_low(snapshot: BehaviourSnapshot | None) -> None:
    assert CLASSIFIER.assess_behaviour(snapshot).level is LOW


def test_words_and_numbers_together_take_the_more_urgent() -> None:
    both = CLASSIFIER.assess(
        text="I want to kill myself", behaviour=BehaviourSnapshot(mood_today=1)
    )
    assert both.level is HIGH
    assert both.concern is Concern.SUICIDAL_LANGUAGE
    assert "BH-LOWEST-MOOD" in both.signals
    numbers_only = CLASSIFIER.assess(
        text="exams went fine", behaviour=BehaviourSnapshot(mood_today=1)
    )
    assert numbers_only.level is MODERATE
    assert numbers_only.concern is Concern.LOW_MOOD_TODAY
    tie = CLASSIFIER.assess(text="I feel hopeless", behaviour=BehaviourSnapshot(mood_today=1))
    assert tie.concern is Concern.DISTRESS_LANGUAGE  # words name the concern on a tie


def test_distress_words_and_a_low_fortnight_still_do_not_alert() -> None:
    found = CLASSIFIER.assess(
        text="I feel hopeless",
        behaviour=BehaviourSnapshot(mood_today=1, stress_today=5, low_mood_days=7),
    )
    assert found.level is MODERATE


def test_the_support_prompt_follows_the_classifier() -> None:
    assert show_support_prompt(mood_score=1, stress_level=None, note=None)
    assert show_support_prompt(mood_score=3, stress_level=5, note=None)
    assert show_support_prompt(mood_score=3, stress_level=None, note="I feel hopeless")
    assert show_support_prompt(mood_score=4, stress_level=2, note="I want to die")
    assert not show_support_prompt(mood_score=3, stress_level=3, note="this exam is killing me")


# ---- fail safe ------------------------------------------------------------------------------


def test_a_failing_rule_engine_still_shows_support(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.domain.safety import crisis_rules

    def boom(_: str) -> None:
        raise RuntimeError("lexicon unreadable")

    monkeypatch.setattr(crisis_rules, "detect", boom)
    found = SafetyClassifier().assess_text("anything at all")
    assert found.level is MODERATE
    assert "classifier_error" in found.signals
    decision = DEFAULT_POLICY.decide(found, source=Source.CHECK_IN)
    assert decision.show_resources and not decision.escalate


def test_the_ai_service_report_is_mapped() -> None:
    hit = CLASSIFIER.from_ai_service(
        action="escalate", category="self_harm", severity="imminent", classifier=True
    )
    assert (hit.level, hit.concern, hit.detector) == (
        IMMEDIATE,
        Concern.SELF_HARM_LANGUAGE,
        Detector.CLASSIFIER,
    )
    review = CLASSIFIER.from_ai_service(
        action="review", category="concern_for_other", severity=None, classifier=False
    )
    assert review.level is MODERATE and review.about_someone_else
    assert (
        CLASSIFIER.from_ai_service(
            action="none", category=None, severity=None, classifier=False
        ).level
        is LOW
    )


def test_the_assessment_never_holds_the_text() -> None:
    text = "I have a plan to kill myself tonight"
    found = CLASSIFIER.assess_text(text)
    for value in dataclasses.asdict(found).values():
        assert text not in str(value)


# ---- the policy ------------------------------------------------------------------------------


def a(lvl: RiskLevel) -> SafetyAssessment:
    return SafetyAssessment(lvl, Concern.SUICIDAL_LANGUAGE, Detector.RULES)


@pytest.mark.parametrize(
    ("lvl", "source", "consent", "basis"),
    [
        (LOW, Source.CHECK_IN, True, EscalationBasis.NOT_NEEDED),
        (MODERATE, Source.CHECK_IN, True, EscalationBasis.NOT_NEEDED),
        (MODERATE, Source.COMPANION, False, EscalationBasis.NOT_NEEDED),
        (MODERATE, Source.MESSAGE, False, EscalationBasis.NOT_NEEDED),
        (HIGH, Source.CHECK_IN, True, EscalationBasis.CONSENT),
        (HIGH, Source.CHECK_IN, False, EscalationBasis.NO_CONSENT),
        (IMMEDIATE, Source.CHECK_IN, False, EscalationBasis.VITAL_INTEREST),
        (IMMEDIATE, Source.CHECK_IN, True, EscalationBasis.CONSENT),
        (HIGH, Source.COMPANION, False, EscalationBasis.COMPANION_NOTICE),
        (IMMEDIATE, Source.COMPANION, False, EscalationBasis.COMPANION_NOTICE),
        (HIGH, Source.MESSAGE, False, EscalationBasis.CARE_TEAM_MESSAGE),
        (IMMEDIATE, Source.MESSAGE, False, EscalationBasis.CARE_TEAM_MESSAGE),
    ],
)
def test_who_is_asked_and_why(
    lvl: RiskLevel, source: Source, consent: bool, basis: EscalationBasis
) -> None:
    decision = DEFAULT_POLICY.decide(a(lvl), source=source, scanning_consent=consent)
    assert decision.basis is basis
    assert decision.escalate is basis.escalates
    assert decision.show_resources is lvl.at_least(MODERATE)
    assert decision.pause_recommendations is lvl.at_least(HIGH)
    assert decision.emergency_first is (lvl is IMMEDIATE)
    # whoever was not asked automatically can ask in one tap
    assert decision.offer_outreach is (lvl.at_least(MODERATE) and not decision.escalate)


def test_consent_is_only_read_when_it_can_change_the_answer() -> None:
    assert DEFAULT_POLICY.needs_consent(a(HIGH), Source.CHECK_IN)
    assert DEFAULT_POLICY.needs_consent(a(IMMEDIATE), Source.CHECK_IN)
    assert not DEFAULT_POLICY.needs_consent(a(MODERATE), Source.CHECK_IN)
    assert not DEFAULT_POLICY.needs_consent(a(HIGH), Source.COMPANION)
    assert not DEFAULT_POLICY.needs_consent(a(HIGH), Source.MESSAGE)


def test_the_policy_thresholds_are_configurable() -> None:
    strict = SafetyPolicy(escalate_at=MODERATE, pause_at=MODERATE)
    decision = strict.decide(a(MODERATE), source=Source.MESSAGE)
    assert decision.escalate and decision.pause_recommendations


# ---- guidance --------------------------------------------------------------------------------

FORBIDDEN = (
    "diagnos",
    "disorder",
    "depression",
    "bipolar",
    "ptsd",
    "illness",
    "symptom",
    "medicat",
    "prescri",
    "dose",
    "dosage",
    " mg",
    "tablet",
    "pill",
    "treatment",
    "therapy will",
    "you have ",
)
ALL_CONCERNS = [*Concern, None]


@pytest.mark.parametrize("lvl", [MODERATE, HIGH, IMMEDIATE])
@pytest.mark.parametrize("concern", ALL_CONCERNS)
@pytest.mark.parametrize("other", [False, True])
def test_guidance_never_diagnoses_or_treats(
    lvl: RiskLevel, concern: Concern | None, other: bool
) -> None:
    g = guidance_for(lvl, concern, about_someone_else=other)
    text = " ".join((g.title, g.message, *g.steps)).lower()
    assert not [w for w in FORBIDDEN if w in text], text
    assert g.steps


@pytest.mark.parametrize("concern", ALL_CONCERNS)
def test_immediate_guidance_leads_with_the_emergency_number(concern: Concern | None) -> None:
    g = guidance_for(IMMEDIATE, concern)
    assert "emergency number" in g.steps[0]


@pytest.mark.parametrize("lvl", [HIGH, IMMEDIATE])
@pytest.mark.parametrize("concern", ALL_CONCERNS)
def test_serious_guidance_points_to_people(lvl: RiskLevel, concern: Concern | None) -> None:
    text = " ".join(guidance_for(lvl, concern).steps).lower()
    assert "emergency number" in text
    assert "counsellor" in text or "someone you trust" in text


def test_guidance_for_someone_else_is_about_helping_them() -> None:
    g = guidance_for(MODERATE, Concern.CONCERN_FOR_OTHER, about_someone_else=True)
    assert "worried about" in g.title.lower()
    assert any("emergency services" in s for s in g.steps)


def test_the_disclaimer_says_what_this_is_not() -> None:
    lowered = DISCLAIMER.lower()
    assert "not an emergency service" in lowered
    assert "does not replace" in lowered
    assert "qualified counsellors" in lowered
    assert "cannot diagnose or treat" in lowered
    assert "emergency number" in lowered


# ---- resources -------------------------------------------------------------------------------


def r(kind: str, label: str) -> EmergencyResource:
    return EmergencyResource(label=label, kind=kind, phone="000")


def test_emergency_contacts_come_first_when_it_is_serious() -> None:
    rows = [r("campus", "C1"), r("helpline", "H1"), r("emergency", "E1"), r("helpline", "H2")]
    assert [x.label for x in arrange(rows, IMMEDIATE)] == ["E1", "H1", "H2", "C1"]
    assert [x.label for x in arrange(rows, HIGH)] == ["E1", "H1", "H2", "C1"]
    assert [x.label for x in arrange(rows, MODERATE)] == ["H1", "H2", "C1", "E1"]


def test_there_is_always_somewhere_to_turn() -> None:
    assert arrange([], MODERATE) == [FALLBACK]
    assert arrange([], IMMEDIATE) == [FALLBACK]
    no_emergency = arrange([r("helpline", "H1")], HIGH)
    assert no_emergency[0] is FALLBACK and no_emergency[1].label == "H1"
    assert arrange([r("helpline", "H1")], MODERATE)[0].label == "H1"
    assert "emergency number" in (FALLBACK.description or "")
