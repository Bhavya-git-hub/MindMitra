"""Synthetic check-in notes for the sentiment model, written for this project.

Sentences come from template families (60 of them, 20 per label) with slots for everyday
student contexts, plus light noise: casing, filler words, a little Hinglish. The test set holds
out whole families, so a model is scored on sentence patterns it never saw in training, not on
new fillings of the same pattern.

Real notes are messier, more mixed and more personal than anything here. A model that does
well on this corpus is only shown to work on clear-cut sentences; see
``model_cards/sentiment.md``.
"""

import dataclasses
from typing import Final

import numpy as np

CORPUS_VERSION: Final = "synthetic-notes-2026.10.1"
SENTIMENTS: Final = ("negative", "neutral", "positive")

_SLOTS: Final[dict[str, tuple[str, ...]]] = {
    "thing": (
        "exam",
        "viva",
        "lab report",
        "assignment",
        "internship interview",
        "placement test",
        "group project",
        "presentation",
        "mid-sem",
        "quiz",
    ),
    "place": ("hostel", "library", "canteen", "mess", "lab", "reading room"),
    "person": ("roommate", "friends", "mentor", "professor", "parents", "batchmates"),
    "time": ("today", "this week", "tonight", "this morning", "yesterday"),
    # Feeling words are shared across sentence patterns, as they are in real language.
    "pos": (
        "great",
        "happy",
        "relieved",
        "proud",
        "calm",
        "hopeful",
        "excited",
        "good",
        "confident",
        "grateful",
        "light",
        "motivated",
    ),
    "neg": (
        "stressed",
        "anxious",
        "lonely",
        "terrible",
        "exhausted",
        "overwhelmed",
        "sad",
        "awful",
        "worried",
        "scared",
        "drained",
        "low",
    ),
}

_FAMILIES: Final[dict[str, tuple[str, ...]]] = {
    "positive": (
        "{time} went really well, I feel {pos} after the {thing}.",
        "Had a {pos} time with my {person} at the {place}.",
        "Feeling {pos}, the {thing} turned out better than I expected.",
        "I'm actually {pos} about the {thing} now.",
        "Slept well and felt {pos} {time}.",
        "Got good feedback from my {person} on the {thing}, so {pos}.",
        "Things are looking up, I feel {pos}.",
        "The {thing} wasn't as bad as I feared, I feel {pos}.",
        "Aaj ka din accha tha, {thing} done, feeling {pos}!",
        "So {pos}, I cleared the {thing}.",
        "Studying with my {person} {time} left me {pos}.",
        "Not worried about the {thing} anymore, just {pos}.",
        "Didn't expect it, but I'm {pos} about the {thing}.",
        "No stress {time}, feeling {pos}.",
        "Finally some rest, I feel {pos} and ready.",
        "My {person} helped a lot, I'm {pos}.",
        "The {place} was quiet and I felt {pos}.",
        "I'm not {neg} anymore, actually {pos}.",
        "Best day in a while, so {pos}!",
        "Small win {time}: the {thing} is done and I'm {pos}.",
    ),
    "negative": (
        "I'm so {neg} about the {thing}, I can't focus.",
        "Feeling really {neg} in the {place} {time}.",
        "I messed up the {thing} and feel {neg}.",
        "Couldn't sleep again, {neg} {time}.",
        "My {person} don't get it, I feel {neg} and left out.",
        "Everything is piling up and I'm {neg}.",
        "I don't feel good about the {thing}, just {neg}.",
        "Worried about money for the {place} fees, feeling {neg}.",
        "Bahut tension hai {thing} ki, feeling {neg}.",
        "Nobody replied to my messages {time}, I feel {neg}.",
        "Scared about placements after the {thing}, so {neg}.",
        "Not happy with how the {thing} went, {neg}.",
        "I wish I felt {pos}, but honestly I'm {neg}.",
        "Not {pos} at all {time}, just {neg}.",
        "Can't stop thinking about the {thing}, so {neg}.",
        "Skipped meals again, feeling {neg}.",
        "My {person} are busy and I'm {neg} in the {place}.",
        "Nothing is going right, {neg} {time}.",
        "Kuch accha nahi lag raha, {neg} hoon.",
        "Barely slept before the {thing}, {neg}.",
    ),
    "neutral": (
        "Had the {thing} {time}.",
        "Went to the {place} and then back to my room.",
        "Studied for a few hours at the {place}.",
        "The {thing} is scheduled for next week.",
        "Talked to my {person} about the timetable.",
        "Normal day, classes and then dinner at the {place}.",
        "Need to submit the {thing} by Friday.",
        "Called my {person} {time}.",
        "Aaj {place} gaya, phir class.",
        "Updated my notes for the {thing}.",
        "Not much happened {time}.",
        "Reading about the {thing} format.",
        "Moved my desk in the {place}.",
        "Bought stationery for the {thing}.",
        "Class got shifted to the afternoon {time}.",
        "My {person} asked about the syllabus.",
        "Checked the notice board at the {place}.",
        "Printed the {thing} slides.",
        "Kal {thing} hai, notes ready kar raha hoon.",
        "Took the bus to the {place} {time}.",
    ),
}
_PREFIXES: Final = ("", "", "", "ok so ", "honestly ", "hmm ", "tbh ")
_SUFFIXES: Final = ("", "", "", " lol", "...", " idk", " :)")
# Held out of training: four families per label, scored only at test time.
HELD_OUT_PER_LABEL: Final = 4


@dataclasses.dataclass(frozen=True)
class Corpus:
    texts: list[str]
    labels: np.ndarray  # index into SENTIMENTS
    families: np.ndarray  # template family id, for the grouped split
    test_families: frozenset[int]

    def split(self) -> tuple[np.ndarray, np.ndarray]:
        """Boolean masks (train, test); test holds whole unseen families."""
        test = np.isin(self.families, sorted(self.test_families))
        return ~test, test


def _fill(template: str, rng: np.random.Generator) -> str:
    values = {k: str(rng.choice(v)) for k, v in _SLOTS.items()}
    text = template.format(**values)
    text = str(rng.choice(_PREFIXES)) + text + str(rng.choice(_SUFFIXES))
    roll = rng.random()
    if roll < 0.15:
        text = text.lower()
    elif roll < 0.2:
        text = text.upper()
    return text


def generate(per_family: int = 170, *, seed: int = 20261011) -> Corpus:
    rng = np.random.default_rng(seed)
    texts: list[str] = []
    labels: list[int] = []
    families: list[int] = []
    test_families: set[int] = set()
    family_id = 0
    for label_index, sentiment in enumerate(SENTIMENTS):
        templates = _FAMILIES[sentiment]
        held = rng.choice(len(templates), size=HELD_OUT_PER_LABEL, replace=False)
        for i, template in enumerate(templates):
            if i in held:
                test_families.add(family_id)
            for _ in range(per_family):
                texts.append(_fill(template, rng))
                labels.append(label_index)
                families.append(family_id)
            family_id += 1
    return Corpus(
        texts=texts,
        labels=np.asarray(labels, dtype=np.int64),
        families=np.asarray(families, dtype=np.int64),
        test_families=frozenset(test_families),
    )


# Hand-written sentences unlike any template: mixed feelings, sarcasm, indirect wording. Scored
# separately to show where the models break, not to tune them. Labels are the team's reading.
HARD_CASES: Final[tuple[tuple[str, str], ...]] = (
    ("Great, another surprise quiz. Just what I needed.", "negative"),
    ("The exam was tough but I think I did okay.", "positive"),
    ("I passed, but everyone else did better than me.", "negative"),
    ("Mess food was terrible but my friends made it fun.", "positive"),
    ("I guess things are fine.", "neutral"),
    ("Can't tell if I'm tired or just bored.", "neutral"),
    ("Not the worst week I've had.", "positive"),
    ("I keep smiling in class so nobody asks.", "negative"),
    ("My internship offer came through!!", "positive"),
    ("Everyone went home for the festival except me.", "negative"),
    ("Submitted the form for the hostel transfer.", "neutral"),
    ("Woke up at 3pm again, whatever.", "negative"),
    ("Mom sent snacks, best day.", "positive"),
    ("Placement list is out tomorrow.", "neutral"),
    ("Kal se padhai shuru, abhi chill.", "neutral"),
    ("Yaar sab theek hai, bas thoda thak gaya.", "neutral"),
    ("I don't hate the new timetable.", "positive"),
    ("Honestly proud of myself for going to the gym.", "positive"),
    ("Sat alone at lunch, it's fine I guess.", "negative"),
    ("The lab report deadline moved to next week.", "neutral"),
    ("Feeling like a fraud in this course.", "negative"),
    ("Finally understood recursion, took long enough lol.", "positive"),
    ("Dad lost his job so fees might be a problem.", "negative"),
    ("Nothing to report.", "neutral"),
)
