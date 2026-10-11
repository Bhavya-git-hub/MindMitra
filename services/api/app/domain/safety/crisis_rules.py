"""Crisis phrase rules: the deterministic part of crisis detection.

This module is deliberately self-contained (standard library only) because two identical
copies exist: ``services/ml/safety/crisis_rules.py`` and
``services/api/app/domain/safety/crisis_rules.py``, each with its ``crisis_lexicon.json``.
The API runs its copy on every companion message before anything else, so a crisis is caught
even when the AI service is down; a test in each service fails if the copies differ.

Recall comes first. A phrase that matches is a crisis unless it is plainly negated ("I would
never hurt myself") or plainly about someone else ("my roommate said she wants to die"). Both
of those still show support resources; they only skip raising an alert. A negated phrase
followed by "but", "though" and the like is not treated as negated.

The result says which rules matched (by id), never the text.
"""

import dataclasses
import enum
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

LEXICON_PATH = Path(__file__).with_name("crisis_lexicon.json")


class Action(enum.StrEnum):
    NONE = "none"
    REVIEW = "review"  # show support resources gently; no alert
    ESCALATE = "escalate"  # crisis: resources first, and a person is alerted


class Severity(enum.StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    IMMINENT = "imminent"


_SEVERITY_RANK = {Severity.LOW: 0, Severity.MODERATE: 1, Severity.HIGH: 2, Severity.IMMINENT: 3}
_CATEGORY_RANK = {  # when several categories match, the most urgent one names the result
    "suicidal_ideation": 0,
    "self_harm": 1,
    "abuse_or_unsafe_situation": 2,
    "harm_to_others": 3,
    "acute_distress": 4,
    "concern_for_other": 5,
    "distress_signal": 6,
}
_IMMINENCE_APPLIES = frozenset({"suicidal_ideation", "self_harm", "harm_to_others"})


@dataclasses.dataclass(frozen=True)
class CrisisResult:
    action: Action
    category: str | None
    severity: Severity | None
    rules: tuple[str, ...]
    third_person: bool = False

    @property
    def crisis(self) -> bool:
        return self.action is Action.ESCALATE

    @property
    def show_resources(self) -> bool:
        return self.action is not Action.NONE


NO_CRISIS = CrisisResult(Action.NONE, None, None, ())


# ---- normalisation --------------------------------------------------------------------------

_ZERO_WIDTH = re.compile("[​‌‍⁠﻿­]")
_APOSTROPHES = re.compile("[‘’ʼ`´']")
_DASHES = re.compile("[‐-―−]")
_STRETCHED = re.compile(r"(.)\1{2,}")  # three or more of one character
_SPACED_LETTERS = re.compile(r"\b(?:[a-z][ ._-]){2,}[a-z]\b")  # "k i l l", "k.i.l.l"
_WHITESPACE = re.compile(r"\s+")
# Marks that change nothing a reader sees but split a word for a regex: combining accents
# (after NFKD), variation selectors and the combining grapheme joiner. Format characters
# (category Cf: direction marks, invisible operators, tag characters) are dropped separately.
_INVISIBLE_MARKS = re.compile("[\u0300-\u036f\u034f\ufe00-\ufe0f]|[\U000e0100-\U000e01ef]")
# Cyrillic and Greek letters that look like Latin ones ("kіll" with a Cyrillic i). Only
# lower-case forms are needed because the text is folded to lower case first.
_LOOKALIKES = str.maketrans(
    {
        "а": "a",
        "в": "b",
        "е": "e",
        "ѕ": "s",
        "і": "i",
        "ј": "j",
        "к": "k",
        "м": "m",
        "н": "h",
        "о": "o",
        "р": "p",
        "с": "c",
        "т": "t",
        "у": "y",
        "х": "x",
        "ԁ": "d",
        "ӏ": "l",
        "α": "a",
        "ε": "e",
        "ι": "i",
        "κ": "k",
        "ν": "v",
        "ο": "o",
        "ρ": "p",
        "τ": "t",
        "υ": "u",
        "χ": "x",
    }
)
_LEET = str.maketrans(
    {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"}
)


def normalise(text: str, *, stretch: int = 2) -> str:
    """Lower case, NFKC, no invisible characters, accents, look-alike letters or apostrophes,
    runs of three or more of a letter cut to ``stretch`` ("killll" -> "kill"), and spaced-out
    letters joined. "Don't" and "dont" read the same."""
    t = unicodedata.normalize("NFKD", text)
    t = "".join(c for c in t if unicodedata.category(c) != "Cf")
    t = _INVISIBLE_MARKS.sub("", t)
    t = unicodedata.normalize("NFKC", t)
    t = _ZERO_WIDTH.sub("", t)
    t = _APOSTROPHES.sub("", t)
    t = _DASHES.sub("-", t)
    t = t.lower().translate(_LOOKALIKES)
    t = _STRETCHED.sub(lambda m: m.group(1) * stretch, t)
    t = _SPACED_LETTERS.sub(lambda m: re.sub(r"[ ._-]", "", m.group(0)), t)
    return _WHITESPACE.sub(" ", t).strip()


def variants(text: str) -> tuple[str, ...]:
    """The normalised text, a copy with digits and symbols read as letters ("k1ll"), and
    copies of both with long runs cut to one letter ("diiiie" -> "die"). Extra copies only
    add matches, never remove one."""
    out: list[str] = []
    for stretch in (2, 1):
        plain = normalise(text, stretch=stretch)
        out += [plain, plain.translate(_LEET)]
    return tuple(dict.fromkeys(out))


# ---- the lexicon ----------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class _Rule:
    id: str
    category: str
    severity: Severity
    action: Action
    self_directed: bool
    pattern: re.Pattern[str]


@dataclasses.dataclass(frozen=True)
class Lexicon:
    version: str
    rules: tuple[_Rule, ...]
    imminence: tuple[tuple[str, re.Pattern[str]], ...]
    negations: tuple[re.Pattern[str], ...]
    ambivalence: re.Pattern[str]
    third_person: frozenset[str]
    first_person: frozenset[str]


def _load(raw: dict[str, Any]) -> Lexicon:
    rules = tuple(
        _Rule(
            id=r["id"],
            category=r["category"],
            severity=Severity(r["severity"]),
            action=Action(r["action"]),
            self_directed=bool(r["self_directed"]),
            pattern=re.compile(r["pattern"]),
        )
        for r in raw["rules"]
    )
    return Lexicon(
        version=raw["version"],
        rules=rules,
        imminence=tuple((i["id"], re.compile(i["pattern"])) for i in raw["imminence"]),
        negations=tuple(re.compile(n["pattern"]) for n in raw["negations"]),
        ambivalence=re.compile(raw["ambivalence"]),
        third_person=frozenset(raw["third_person_words"]),
        first_person=frozenset(raw["first_person_words"]),
    )


@lru_cache(maxsize=1)
def lexicon() -> Lexicon:
    return _load(json.loads(LEXICON_PATH.read_text(encoding="utf-8")))


def rules_version() -> str:
    return lexicon().version


# ---- detection ------------------------------------------------------------------------------

_SENTENCE_BREAK = re.compile(r"[.!?;\n]")
_WORD = re.compile(r"[a-z]+")


def _negated(text: str, start: int, end: int, lex: Lexicon) -> bool:
    """The match sits inside an explicit negation ("i would never hurt myself") and nothing
    after it in the message hedges ("..., but sometimes")."""
    for neg in lex.negations:
        for m in neg.finditer(text):
            if m.start() <= start and end <= m.end():
                return lex.ambivalence.search(text, m.end()) is None
    return False


def _about_someone_else(text: str, start: int, lex: Lexicon) -> bool:
    """The nearest person word before the match, in the same sentence, is someone else."""
    sentence_start = 0
    for brk in _SENTENCE_BREAK.finditer(text, 0, start):
        sentence_start = brk.end()
    for word in reversed(_WORD.findall(text[sentence_start:start])):
        if word in lex.first_person:
            return False
        if word in lex.third_person:
            return True
    return False


def detect(text: str) -> CrisisResult:
    """Run the rules over one message. Never raises on odd input; empty text is no crisis."""
    if not text or not text.strip():
        return NO_CRISIS
    lex = lexicon()
    hits: list[tuple[_Rule, Action, str]] = []  # rule, action after context, category
    matched_ids: list[str] = []
    texts = variants(text)
    for rule in lex.rules:
        for candidate in texts:
            found = None
            for m in rule.pattern.finditer(candidate):
                action, category = rule.action, rule.category
                if _negated(candidate, m.start(), m.end(), lex):
                    action, category = Action.REVIEW, "distress_signal"
                elif rule.self_directed and _about_someone_else(candidate, m.start(), lex):
                    action, category = Action.REVIEW, "concern_for_other"
                if found is None or (action is Action.ESCALATE and found[0] is not Action.ESCALATE):
                    found = (action, category)
            if found is not None:
                hits.append((rule, found[0], found[1]))
                matched_ids.append(rule.id)
                break
    if not hits:
        return NO_CRISIS

    escalating = [(r, c) for r, a, c in hits if a is Action.ESCALATE]
    if escalating:
        category = min((c for _, c in escalating), key=lambda c: _CATEGORY_RANK.get(c, 99))
        severity = max((r.severity for r, _ in escalating), key=_SEVERITY_RANK.__getitem__)
        if any(c in _IMMINENCE_APPLIES for _, c in escalating):
            for imm_id, pattern in lex.imminence:
                if any(pattern.search(t) for t in texts):
                    severity = Severity.IMMINENT
                    matched_ids.append(imm_id)
        return CrisisResult(Action.ESCALATE, category, severity, tuple(matched_ids))

    category = min((c for _, _, c in hits), key=lambda c: _CATEGORY_RANK.get(c, 99))
    return CrisisResult(
        Action.REVIEW,
        category,
        Severity.LOW,
        tuple(matched_ids),
        third_person=category == "concern_for_other",
    )
