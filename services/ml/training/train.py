"""Train, compare, evaluate and save every wellness indicator model.

    uv run python -m training.train                  # full run, models to ./models
    uv run --group nlp python -m training.train      # also scores the transformer approach
    uv run python -m training.train --quick --out /tmp/m --reports /tmp/r   # fast smoke run

Synthetic data only. The run is deterministic for a given seed and library versions.
"""

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

import numpy as np

from data import synthetic, text_corpus
from evaluation.report import render
from inference.registry import SENTIMENT, library_versions
from preprocessing.features import FEATURES, MIN_CHECKIN_DAYS, engineer, to_matrix
from training.artifacts import save_model, write_manifest
from training.indicators import TABULAR_INDICATORS
from training.sentiment import train_sentiment
from training.tabular import train_indicator

ROOT = Path(__file__).resolve().parent.parent


def run(
    *,
    out_dir: Path,
    reports_dir: Path,
    students: int = 4000,
    seed: int = 20261010,
    quick: bool = False,
    with_transformer: bool = True,
) -> list[dict[str, Any]]:
    trained_at = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
    stamp = trained_at[:10].replace("-", "")
    out_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    cohort = synthetic.generate(students, seed=seed)
    X_all = to_matrix([engineer(r, window_end=cohort.window_end) for r in cohort.records])
    # Indicators are never given with fewer than MIN_CHECKIN_DAYS, so train only on those.
    keep = X_all[:, FEATURES.index("checkin_days")] >= MIN_CHECKIN_DAYS
    X = X_all[keep]
    fingerprint = cohort.fingerprint()

    entries: dict[str, dict[str, str]] = {}
    reports: list[dict[str, Any]] = []
    for spec in TABULAR_INDICATORS:
        result = train_indicator(spec, X, cohort.labels[spec.name][keep], seed=seed, quick=quick)
        version = f"{spec.name}-{result.algorithm}-{stamp}-{fingerprint[:8]}"
        meta = {
            "indicator": spec.name,
            "title": spec.title,
            "kind": spec.kind,
            "classes": list(spec.classes),
            "features": list(FEATURES),
            "algorithm": result.algorithm,
            "version": version,
            "thresholds": result.thresholds,
            "test_metrics": {
                k: result.report["test"][k]
                for k in ("accuracy", "precision", "recall", "f1", "roc_auc")
            },
            "trained_at": trained_at,
            "data": {"generator": synthetic.GENERATOR_VERSION, "fingerprint": fingerprint},
            "synthetic_only": True,
        }
        entries[spec.name] = save_model(out_dir, spec.name, result.model, meta)
        reports.append({**result.report, "version": version})

    corpus = text_corpus.generate(60 if quick else 170, seed=seed + 1)
    sentiment = train_sentiment(corpus, seed=seed, quick=quick, with_transformer=with_transformer)
    version = f"sentiment-{sentiment.algorithm}-{stamp}-{text_corpus.CORPUS_VERSION[-8:]}"
    entries[SENTIMENT] = save_model(
        out_dir,
        SENTIMENT,
        sentiment.model,
        {
            "indicator": SENTIMENT,
            "title": "Sentiment of check-in notes",
            "kind": "multiclass",
            "classes": list(text_corpus.SENTIMENTS),
            "algorithm": sentiment.algorithm,
            "version": version,
            "thresholds": {},
            "test_metrics": {
                k: sentiment.report["test"][k]
                for k in ("accuracy", "precision", "recall", "f1", "roc_auc")
            },
            "trained_at": trained_at,
            "data": {"corpus": text_corpus.CORPUS_VERSION},
            "synthetic_only": True,
        },
    )
    reports.append({**sentiment.report, "version": version})

    run_info = {
        "trained_at": trained_at,
        "generator": synthetic.GENERATOR_VERSION,
        "corpus": text_corpus.CORPUS_VERSION,
        "seed": seed,
        "students": students,
        "excluded_low_data": int((~keep).sum()),
        "min_checkin_days": MIN_CHECKIN_DAYS,
        "libraries": library_versions(),
        "quick": quick,
    }
    write_manifest(
        out_dir,
        entries,
        trained_at=trained_at,
        data={"generator": synthetic.GENERATOR_VERSION, "fingerprint": fingerprint, "seed": seed},
    )
    for r in reports:
        (reports_dir / f"{r['indicator']}.json").write_text(
            json.dumps({**r, "run": run_info}, indent=2, sort_keys=True) + "\n"
        )
    (reports_dir / "REPORT.md").write_text(render(reports, run=run_info))
    return reports


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "models")
    parser.add_argument("--reports", type=Path, default=ROOT / "evaluation" / "reports")
    parser.add_argument("--students", type=int, default=4000)
    parser.add_argument("--seed", type=int, default=20261010)
    parser.add_argument("--quick", action="store_true", help="fewer folds and candidates")
    parser.add_argument("--no-transformer", action="store_true")
    args = parser.parse_args()
    np.seterr(all="ignore")
    reports = run(
        out_dir=args.out,
        reports_dir=args.reports,
        students=args.students,
        seed=args.seed,
        quick=args.quick,
        with_transformer=not args.no_transformer,
    )
    for r in reports:
        t = r["test"]
        print(
            f"{r['indicator']:<22} {r['selected']:<26} "
            f"f1={t['f1']:.3f} roc_auc={t['roc_auc']:.3f} acc={t['accuracy']:.3f}"
        )


if __name__ == "__main__":
    main()
