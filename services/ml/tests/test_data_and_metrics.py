"""Synthetic data is reproducible and sensible; metrics are computed the way the reports say."""

import numpy as np

from data import synthetic, text_corpus
from evaluation.metrics import binary_metrics, f1_threshold, multiclass_metrics, recall_threshold


def test_the_cohort_is_reproducible_from_its_seed() -> None:
    a = synthetic.generate(200, seed=7)
    b = synthetic.generate(200, seed=7)
    c = synthetic.generate(200, seed=8)
    assert a.fingerprint() == b.fingerprint() != c.fingerprint()


def test_labels_are_neither_rare_nor_universal() -> None:
    cohort = synthetic.generate(1500)
    for name in synthetic.TABULAR_LABELS[1:]:
        assert 0.1 < cohort.labels[name].mean() < 0.4, name
    assert set(np.unique(cohort.labels["stress_level"])) == {0, 1, 2}


def test_the_note_test_set_holds_out_whole_sentence_patterns() -> None:
    corpus = text_corpus.generate(20)
    train, test = corpus.split()
    assert not set(corpus.families[train]) & set(corpus.families[test])
    assert len(corpus.test_families) == 3 * text_corpus.HELD_OUT_PER_LABEL
    assert set(corpus.labels[test]) == {0, 1, 2}  # every label is tested


def test_binary_metrics_on_a_known_example() -> None:
    y = np.array([0, 0, 1, 1])
    p = np.array([0.1, 0.6, 0.4, 0.9])
    m = binary_metrics(y, p, 0.5)
    assert m["accuracy"] == 0.5
    assert m["precision"] == 0.5
    assert m["recall"] == 0.5
    assert m["roc_auc"] == 0.75
    assert m["confusion_matrix"] == [[1, 1], [1, 1]]


def test_multiclass_metrics_include_a_full_confusion_matrix() -> None:
    y = np.array([0, 1, 2, 2])
    proba = np.eye(3)[[0, 1, 2, 1]]
    m = multiclass_metrics(y, proba, ("low", "moderate", "high"))
    assert m["accuracy"] == 0.75
    assert m["confusion_matrix"] == [[1, 0, 0], [0, 1, 0], [0, 1, 1]]
    assert m["per_class"]["high"]["recall"] == 0.5


def test_band_thresholds_trade_precision_for_recall() -> None:
    rng = np.random.default_rng(0)
    y = rng.integers(0, 2, 500)
    p = np.clip(y * 0.4 + rng.normal(0.3, 0.2, 500), 0, 1)
    for target in (0.8, 0.9):
        assert np.mean(p[y == 1] >= recall_threshold(y, p, target)) >= target
    assert recall_threshold(y, p, 0.9) <= recall_threshold(y, p, 0.8)
    assert 0.0 < f1_threshold(y, p) < 1.0
