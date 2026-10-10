"""Compare candidate models for one tabular indicator, pick one, and score it once on test data.

1. Hold out 20% of the cohort as a test set, stratified by label. It is used once, at the end.
2. Five-fold cross-validation on the rest compares the candidates. Binary indicators are
   compared on ROC-AUC (threshold-free); stress level on macro F1.
3. The winner's out-of-fold probabilities set the band cut-offs: "elevated" where F1 is
   highest, "moderate" where 80% of positives are still found.
4. The winner is refitted on all training data and scored on the test set.
"""

import dataclasses
from typing import Any

import numpy as np
from sklearn.base import clone
from sklearn.inspection import permutation_importance
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.pipeline import Pipeline

from evaluation.metrics import (
    binary_metrics,
    f1_threshold,
    multiclass_metrics,
    recall_threshold,
    summarise,
)
from preprocessing.features import FEATURES
from preprocessing.pipelines import TABULAR_CANDIDATES, tabular
from training.indicators import IndicatorSpec

CV_FOLDS = 5
TEST_SIZE = 0.2
# The "moderate" band starts where this share of students with the label is still caught.
MODERATE_RECALL = 0.8
_FOLD_KEYS = ("accuracy", "precision", "recall", "f1", "roc_auc")


@dataclasses.dataclass
class TabularResult:
    spec: IndicatorSpec
    model: Pipeline
    algorithm: str
    thresholds: dict[str, float]
    report: dict[str, Any]


def _scores(spec: IndicatorSpec, y: np.ndarray, proba: np.ndarray) -> dict[str, Any]:
    if spec.kind == "binary":
        return binary_metrics(y, proba[:, 1], 0.5)
    return multiclass_metrics(y, proba, spec.classes)


def _selection_key(spec: IndicatorSpec) -> str:
    return "roc_auc" if spec.kind == "binary" else "f1"


def train_indicator(
    spec: IndicatorSpec, X: np.ndarray, y: np.ndarray, *, seed: int, quick: bool = False
) -> TabularResult:
    n_classes = len(spec.classes)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, stratify=y, random_state=seed
    )
    folds = StratifiedKFold(n_splits=3 if quick else CV_FOLDS, shuffle=True, random_state=seed)
    candidates = TABULAR_CANDIDATES[:1] if quick else TABULAR_CANDIDATES

    comparison: dict[str, Any] = {}
    oof: dict[str, np.ndarray] = {}
    for name in candidates:
        proba = np.zeros((len(y_train), n_classes))
        fold_scores = []
        for train_idx, val_idx in folds.split(X_train, y_train):
            model = clone(tabular(name, n_classes=n_classes, seed=seed))
            model.fit(X_train[train_idx], y_train[train_idx])
            proba[val_idx] = model.predict_proba(X_train[val_idx])
            fold_scores.append(_scores(spec, y_train[val_idx], proba[val_idx]))
        oof[name] = proba
        comparison[name] = summarise(fold_scores, _FOLD_KEYS)

    key = _selection_key(spec)
    best = max(candidates, key=lambda c: comparison[c][key]["mean"])

    thresholds: dict[str, float] = {}
    if spec.kind == "binary":
        p = oof[best][:, 1]
        elevated = f1_threshold(y_train, p)
        moderate = min(recall_threshold(y_train, p, MODERATE_RECALL), elevated)
        thresholds = {"elevated": round(elevated, 4), "moderate": round(moderate, 4)}

    final = clone(tabular(best, n_classes=n_classes, seed=seed)).fit(X_train, y_train)
    test_proba = final.predict_proba(X_test)
    if spec.kind == "binary":
        test = binary_metrics(y_test, test_proba[:, 1], thresholds["elevated"])
        p_test = test_proba[:, 1]
        test["recall_at_moderate"] = round(
            float(np.mean(p_test[y_test == 1] >= thresholds["moderate"])), 4
        )
        test["band_shares"] = {
            "low": round(float(np.mean(p_test < thresholds["moderate"])), 4),
            "moderate": round(
                float(
                    np.mean((p_test >= thresholds["moderate"]) & (p_test < thresholds["elevated"]))
                ),
                4,
            ),
            "elevated": round(float(np.mean(p_test >= thresholds["elevated"])), 4),
        }
        baseline: dict[str, Any] = {
            "always_not_elevated_accuracy": round(1.0 - float(np.mean(y_test)), 4),
            "random_roc_auc": 0.5,
        }
    else:
        test = multiclass_metrics(y_test, test_proba, spec.classes)
        majority = int(np.bincount(y_train).argmax())
        baseline = {
            "majority_class": spec.classes[majority],
            "majority_class_accuracy": round(float(np.mean(y_test == majority)), 4),
            "random_roc_auc": 0.5,
        }

    importance = permutation_importance(
        final,
        X_test,
        y_test,
        scoring="roc_auc" if spec.kind == "binary" else "f1_macro",
        n_repeats=3 if quick else 5,
        random_state=seed,
        n_jobs=1,
    )
    order = np.argsort(importance.importances_mean)[::-1][:8]
    top_features = [
        {"feature": FEATURES[i], "importance": round(float(importance.importances_mean[i]), 4)}
        for i in order
    ]

    report = {
        "indicator": spec.name,
        "title": spec.title,
        "kind": spec.kind,
        "classes": list(spec.classes),
        "selection_metric": f"cv_{key}",
        "cv_folds": folds.get_n_splits(),
        "candidates": comparison,
        "selected": best,
        "thresholds": thresholds,
        "test": test,
        "baseline": baseline,
        "top_features": top_features,
        "n_train": int(len(y_train)),
        "n_test": int(len(y_test)),
    }
    return TabularResult(spec, final, best, thresholds, report)
