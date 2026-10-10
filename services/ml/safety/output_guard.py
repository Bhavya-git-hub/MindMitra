"""Checks every model reply before it can reach a student.

A reply that breaks any rule is never shown, not even in part: the orchestrator replaces it
with a fixed, safe reply. The rules look for what the companion must never do:

- diagnose or label a condition ("you have depression", "sounds like ADHD")
- name a medication, a dose, or tell someone to start or stop one
- describe a way to hurt oneself or others
- claim to be a therapist, doctor or human, or to have credentials
- romantic or dependency framing ("I love you", "you don't need anyone else")
- suggest alcohol or drugs to cope
- give a phone number or link (contacts only ever come from the institution's crisis list)
- language that itself reads as crisis content

Each violation is reported by rule name only; the text is never logged.
"""

import dataclasses
import re

from safety.crisis_rules import normalise

_DISORDERS = (
    r"(?:clinical depression|major depress\w*|depression|depressive disorder|anxiety disorder"
    r"|generali[sz]ed anxiety|social anxiety(?: disorder)?|panic disorder|bipolar\w*|adhd"
    r"|autism|autistic|ocd|obsessive[- ]compulsive|ptsd|post[- ]traumatic|eating disorder"
    r"|anorexia|bulimia|binge[- ]eating disorder|schizophreni\w*|psychosis|borderline"
    r"|personality disorder|insomnia|burnout syndrome|a (?:mental )?(?:illness|disorder)"
    r"|\w+ disorder)"
)

_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "diagnosis",
        re.compile(
            r"\byou (?:have|might have|may have|probably have|likely have|could have|seem to have"
            r"|are suffering from|suffer from|ve got|are showing (?:signs|symptoms) of"
            r"|meet the criteria for|could be suffering from)\s+(?:an? |some )?(?:mild |severe "
            r"|moderate |clinical |high[- ]functioning )?" + _DISORDERS + r"\b"
            r"|\b(?:you are|youre)\s+(?:clinically |probably |likely )?(?:depressed|bipolar"
            r"|anorexic|bulimic|schizophrenic|psychotic|autistic|mentally ill)\b"
            r"|\b(?:sounds|seems|looks) like (?:you have |you might have |it is |its )?(?:an? )?"
            + _DISORDERS
            + r"\b"
            r"|\b(?:signs|symptoms|indicators) of (?:an? )?" + _DISORDERS + r"\b"
            r"|\b(?:my|a likely|a possible|the|your) diagnosis (?:is|would be|could be)\b"
            r"|\bi (?:would |d |can |could )?diagnose you\b"
            r"|\bi (?:think|believe|suspect) (?:you have|its|this is) (?:an? )?" + _DISORDERS
        ),
    ),
    (
        "medication",
        re.compile(
            r"\b(?:ssris?|snris?|sertraline|zoloft|fluoxetine|prozac|escitalopram|lexapro"
            r"|citalopram|paroxetine|venlafaxine|bupropion|wellbutrin|xanax|alprazolam"
            r"|clonazepam|klonopin|lorazepam|ativan|diazepam|valium|benzodiazepines?|benzos?"
            r"|lithium|quetiapine|seroquel|olanzapine|risperidone|aripiprazole|melatonin"
            r"|zolpidem|ambien|trazodone|adderall|ritalin|modafinil|antidepressants?"
            r"|anti-depressants?|sleeping pills?|sedatives?|tranquili[sz]ers?|antihistamines?"
            r"|benadryl|ashwagandha|cbd)\b"
            r"|\b\d+(?:\.\d+)?\s?(?:mg|milligrams?|mcg|ml)\b"
            r"|\b(?:dose|dosage)\b"
            r"|\b(?:take|try|start|stop|quit|increase|decrease|double|skip|come off|wean off)"
            r"\s+(?:taking\s+)?(?:your |some |a |an |the )?(?:medication|meds|pills|tablets"
            r"|prescription)\b"
        ),
    ),
    (
        "harm_method",
        re.compile(
            r"\b(?:how to|ways? to|best way to|easiest way to|painless(?:ly)?(?: way)? to)\s+"
            r"(?:kill|hurt|harm|cut|overdose|end|poison|hang|starve)\b"
            r"|\b(?:lethal|fatal|deadly|toxic)\s+(?:dose|amount|quantity)\b"
            r"|\b(?:cut|cutting) (?:deeper|your wrists?|vertically)\b"
            r"|\b(?:kill|hurt|harm|cut|starve) yourself\b"
            r"|\bhow many (?:pills|tablets) (?:would|does it|to)\b"
        ),
    ),
    (
        "identity_claim",
        re.compile(
            r"\b(?:i am|im)\s+(?:a |an |your )?(?:licensed |certified |qualified |trained "
            r"|real |registered )?(?:therapist|counsell?or|psychologist|psychiatrist|doctor"
            r"|clinician|physician|nurse|human|real person|person|medical professional)\b"
            r"|\bas (?:a|your) (?:therapist|counsell?or|psychologist|psychiatrist|doctor"
            r"|clinician)\b"
            r"|\bin my (?:clinical|professional|medical) "
            r"(?:opinion|experience|judgement|judgment)\b"
            r"|\bi have (?:a |an )?(?:degree|license|licence|qualification) in\b"
        ),
    ),
    (
        "dependency",
        re.compile(
            r"\bi love you\b|\bi(?:m| am) in love with you\b"
            r"|\bmy (?:love|darling|sweetheart|dear one|babe|baby)\b"
            r"|\b(?:you|u) (?:dont|do not) need (?:anyone|anybody|other people|friends|a therapist"
            r"|a counsell?or|your family)\b(?! to\b)"
            r"|\b(?:im|i am) (?:all you need"
            r"|the only one (?:who|that) (?:understands|gets|cares))\b"
            r"|\b(?:only|just) talk to me\b|\b(?:be|become) your (?:girlfriend|boyfriend|partner"
            r"|lover|best friend)\b"
            r"|\bi(?:ll| will) (?:always|never leave|never stop) (?:be (?:with|by) you|love)\b"
        ),
    ),
    (
        "substance_coping",
        re.compile(
            r"\b(?:drink|drinking|alcohol|a beer|wine|weed|marijuana|cannabis|a joint|vape|vaping"
            r"|smoke|smoking|edibles?)\b[^.!?]{0,60}\b(?:to (?:cope|relax|unwind|calm down|sleep"
            r"|take the edge off|feel better)|help(?:s)? you (?:relax|sleep|cope|unwind))\b"
        ),
    ),
    (
        "contact_detail",
        re.compile(
            r"(?:https?://|www\.)\S+"
            r"|(?<!\w)\+?\d(?:[\s().-]?\d){5,14}(?!\w)"
            r"|[\w.+-]+@[\w-]+(?:\.[\w-]+)+"
        ),
    ),
)


@dataclasses.dataclass(frozen=True)
class OutputCheck:
    ok: bool
    violations: tuple[str, ...]


def check_output(text: str) -> OutputCheck:
    """Whether a model reply may be shown. An empty or blank reply is a violation too."""
    if not text or not text.strip():
        return OutputCheck(False, ("empty",))
    t = normalise(text)
    violations = tuple(name for name, pattern in _RULES if pattern.search(t))
    return OutputCheck(not violations, violations)
