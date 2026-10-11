"""Classification metrics in one place, so every model is scored the same way.

Binary indicators are scored at a chosen threshold (the "elevated" cut-off) and also without a
threshold (ROC-AUC, average precision). Multi-class models are scored on the most likely class,
with macro averages and one-vs-rest ROC-AUC.
"""

import math
from collections.abc import Sequence
from typing import Any

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)


def _r(x: float) -> float:
    return round(float(x), 4)


def binary_metrics(y: np.ndarray, p: np.ndarray, threshold: float) -> dict[str, Any]:
    """``p`` is the probability of the positive class (1)."""
    pred = (p >= threshold).astype(int)
    return {
        "threshold": _r(threshold),
        "accuracy": _r(accuracy_score(y, pred)),
        "precision": _r(precision_score(y, pred, zero_division=0)),
        "recall": _r(recall_score(y, pred, zero_division=0)),
        "f1": _r(f1_score(y, pred, zero_division=0)),
        "roc_auc": _r(roc_auc_score(y, p)) if len(set(y.tolist())) == 2 else None,
        "average_precision": _r(average_precision_score(y, p)),
        "brier": _r(brier_score_loss(y, p)),
        "prevalence": _r(float(np.mean(y))),
        "confusion_matrix": confusion_matrix(y, pred, labels=[0, 1]).tolist(),
        "confusion_matrix_labels": ["not elevated", "elevated"],
        "n": int(len(y)),
    }


def multiclass_metrics(y: np.ndarray, proba: np.ndarray, labels: Sequence[str]) -> dict[str, Any]:
    pred = proba.argmax(axis=1)
    k = list(range(len(labels)))
    per_class = {
        name: {
            "precision": _r(precision_score(y, pred, labels=[i], average="macro", zero_division=0)),
            "recall": _r(recall_score(y, pred, labels=[i], average="macro", zero_division=0)),
            "f1": _r(f1_score(y, pred, labels=[i], average="macro", zero_division=0)),
        }
        for i, name in enumerate(labels)
    }
    return {
        "accuracy": _r(accuracy_score(y, pred)),
        "precision": _r(precision_score(y, pred, labels=k, average="macro", zero_division=0)),
        "recall": _r(recall_score(y, pred, labels=k, average="macro", zero_division=0)),
        "f1": _r(f1_score(y, pred, labels=k, average="macro", zero_division=0)),
        "roc_auc": _r(roc_auc_score(y, proba, multi_class="ovr", average="macro", labels=k)),
        "per_class": per_class,
        "confusion_matrix": confusion_matrix(y, pred, labels=k).tolist(),
        "confusion_matrix_labels": list(labels),
        "n": int(len(y)),
    }


def f1_threshold(y: np.ndarray, p: np.ndarray) -> float:
    """The cut-off that maximises F1 (used for the "elevated" band)."""
    precision, recall, thresholds = precision_recall_curve(y, p)
    f1 = 2 * precision * recall / np.maximum(precision + recall, 1e-12)
    best = int(np.argmax(f1[:-1])) if len(thresholds) else 0
    return float(thresholds[best]) if len(thresholds) else 0.5


def recall_threshold(y: np.ndarray, p: np.ndarray, target: float = 0.9) -> float:
    """The highest cut-off that still finds ``target`` of the positives (the "moderate" band)."""
    positives = np.sort(p[y == 1])
    if len(positives) == 0:
        return 0.5
    index = int(math.floor((1.0 - target) * len(positives)))
    return float(positives[min(index, len(positives) - 1)])


def summarise(folds: Sequence[dict[str, Any]], keys: Sequence[str]) -> dict[str, dict[str, float]]:
    """Mean and standard deviation of each metric across cross-validation folds."""
    out: dict[str, dict[str, float]] = {}
    for key in keys:
        values = [float(f[key]) for f in folds if f.get(key) is not None]
        if values:
            out[key] = {"mean": _r(float(np.mean(values))), "sd": _r(float(np.std(values)))}
    return out
