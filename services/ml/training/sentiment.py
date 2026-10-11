"""Sentiment of check-in notes: compare text models and score them on unseen sentence patterns.

Candidates are TF-IDF (words and character n-grams) with logistic regression or naive Bayes,
compared by grouped cross-validation (whole template families held out per fold). When PyTorch
is installed (``uv sync --group nlp``), a small transformer encoder trained from scratch is
scored on the same held-out families for comparison. A pretrained transformer could not be
evaluated in this environment (model downloads are blocked); see the model card.
"""

import dataclasses
import importlib.util
import time
from typing import Any

import numpy as np
from sklearn.base import clone
from sklearn.model_selection import GroupKFold, StratifiedKFold
from sklearn.pipeline import Pipeline

from data.text_corpus import HARD_CASES, SENTIMENTS, Corpus
from evaluation.metrics import multiclass_metrics, summarise
from preprocessing.pipelines import TEXT_CANDIDATES, text
from preprocessing.text import clean

_FOLD_KEYS = ("accuracy", "precision", "recall", "f1", "roc_auc")


@dataclasses.dataclass
class SentimentResult:
    model: Pipeline
    algorithm: str
    report: dict[str, Any]


def _hard_case_accuracy(predict: Any) -> float:
    texts = [t for t, _ in HARD_CASES]
    gold = np.array([SENTIMENTS.index(label) for _, label in HARD_CASES])
    pred = np.asarray(predict(texts)).argmax(axis=1)
    return round(float(np.mean(pred == gold)), 4)


def transformer_available() -> bool:
    return importlib.util.find_spec("torch") is not None


def train_sentiment(
    corpus: Corpus, *, seed: int, quick: bool = False, with_transformer: bool = True
) -> SentimentResult:
    train_mask, test_mask = corpus.split()
    texts = np.array([clean(t) for t in corpus.texts], dtype=object)
    X_train, y_train, g_train = (
        texts[train_mask],
        corpus.labels[train_mask],
        corpus.families[train_mask],
    )
    X_test, y_test = texts[test_mask], corpus.labels[test_mask]
    candidates = TEXT_CANDIDATES[:1] if quick else TEXT_CANDIDATES
    folds = GroupKFold(n_splits=3 if quick else 5)

    comparison: dict[str, Any] = {}
    for name in candidates:
        fold_scores = []
        for train_idx, val_idx in folds.split(X_train, y_train, groups=g_train):
            model = clone(text(name, seed=seed)).fit(list(X_train[train_idx]), y_train[train_idx])
            proba = model.predict_proba(list(X_train[val_idx]))
            fold_scores.append(multiclass_metrics(y_train[val_idx], proba, SENTIMENTS))
        comparison[name] = summarise(fold_scores, _FOLD_KEYS)
        # The same model on a plain random split (patterns it has seen, new fillings), to show
        # how much of the score is memorised sentence shapes.
        seen = []
        random_folds = StratifiedKFold(
            n_splits=folds.get_n_splits(), shuffle=True, random_state=seed
        )
        for train_idx, val_idx in random_folds.split(X_train, y_train):
            model = clone(text(name, seed=seed)).fit(list(X_train[train_idx]), y_train[train_idx])
            proba = model.predict_proba(list(X_train[val_idx]))
            seen.append(multiclass_metrics(y_train[val_idx], proba, SENTIMENTS))
        comparison[name]["seen_patterns_f1"] = summarise(seen, ("f1",))["f1"]

    best = max(candidates, key=lambda c: comparison[c]["f1"]["mean"])
    final = clone(text(best, seed=seed)).fit(list(X_train), y_train)
    test = multiclass_metrics(y_test, final.predict_proba(list(X_test)), SENTIMENTS)

    others: dict[str, Any] = {}
    for name in candidates:
        if name == best:
            continue
        other = clone(text(name, seed=seed)).fit(list(X_train), y_train)
        others[name] = {
            "test": multiclass_metrics(y_test, other.predict_proba(list(X_test)), SENTIMENTS),
            "hard_case_accuracy": _hard_case_accuracy(other.predict_proba),
        }

    if with_transformer and not quick and transformer_available():
        from training.sentiment_transformer import train_and_score

        started = time.perf_counter()
        scored = train_and_score(
            list(X_train), y_train, list(X_test), [t for t, _ in HARD_CASES], seed=seed
        )
        others["transformer_from_scratch"] = {
            "test": multiclass_metrics(y_test, scored.test_proba, SENTIMENTS),
            "hard_case_accuracy": _hard_case_accuracy(lambda _: scored.extra_proba),
            "parameters": scored.parameters,
            "train_seconds": round(time.perf_counter() - started, 1),
            "note": "2-layer encoder trained from scratch on this corpus; not served.",
        }
    elif with_transformer and not quick:
        others["transformer_from_scratch"] = {"skipped": "PyTorch not installed (nlp group)"}

    report = {
        "indicator": "sentiment",
        "title": "Sentiment of check-in notes",
        "kind": "multiclass",
        "classes": list(SENTIMENTS),
        "selection_metric": "grouped_cv_f1",
        "cv_folds": folds.get_n_splits(),
        "candidates": comparison,
        "selected": best,
        "thresholds": {},
        "test": test,
        "hard_case_accuracy": _hard_case_accuracy(final.predict_proba),
        "hard_cases": len(HARD_CASES),
        "other_models_on_test": others,
        "baseline": {"majority_class_accuracy": round(1 / len(SENTIMENTS), 4)},
        "n_train": int(train_mask.sum()),
        "n_test": int(test_mask.sum()),
        "held_out_families": len(corpus.test_families),
    }
    return SentimentResult(final, best, report)
