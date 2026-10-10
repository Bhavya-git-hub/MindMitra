"""The model directory: what training writes and what the service is willing to load.

    models/manifest.json            format, library versions, one entry per model with its hash
    models/<name>/model.joblib      the fitted pipeline (preprocessing included)
    models/<name>/metadata.json     classes, features, band thresholds, test metrics, version

Model files are pickles, and loading a pickle runs code. So the service only loads files from
its own configured directory, only when the manifest's SHA-256 matches each file, and only when
the scikit-learn, XGBoost and NumPy versions match the ones the models were trained with.
Anything else means "indicators unavailable", never a guess.
"""

import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Any, Final

import joblib
import numpy as np
import sklearn
import xgboost

from preprocessing.features import FEATURES

MANIFEST: Final = "manifest.json"
FORMAT: Final = 1
SENTIMENT: Final = "sentiment"


class ModelsUnavailable(Exception):
    """The models are missing or failed a check. Safe to log: holds no student data."""


def library_versions() -> dict[str, str]:
    return {
        "scikit-learn": sklearn.__version__,
        "xgboost": xgboost.__version__,
        "numpy": np.__version__,
    }


def _same_release(a: str, b: str) -> bool:
    return a.split(".")[:2] == b.split(".")[:2]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclasses.dataclass(frozen=True)
class LoadedModel:
    name: str
    model: Any  # a fitted scikit-learn Pipeline
    meta: dict[str, Any]

    @property
    def version(self) -> str:
        return str(self.meta["version"])

    @property
    def classes(self) -> list[str]:
        return [str(c) for c in self.meta["classes"]]


@dataclasses.dataclass(frozen=True)
class Registry:
    tabular: dict[str, LoadedModel]
    sentiment: LoadedModel
    trained_at: str

    def versions(self) -> dict[str, str]:
        out = {name: m.version for name, m in self.tabular.items()}
        out[SENTIMENT] = self.sentiment.version
        return out


def load(model_dir: Path, expected: tuple[str, ...]) -> Registry:
    """Load and verify every model in ``expected`` plus sentiment, or raise ModelsUnavailable."""
    path = model_dir / MANIFEST
    if not path.is_file():
        raise ModelsUnavailable("no trained models (run: python -m training.train)")
    try:
        manifest = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ModelsUnavailable("manifest unreadable") from exc
    if manifest.get("format") != FORMAT:
        raise ModelsUnavailable("unsupported manifest format")
    trained_with = manifest.get("libraries", {})
    for lib, version in library_versions().items():
        if not _same_release(str(trained_with.get(lib, "")), version):
            raise ModelsUnavailable(f"trained with a different {lib}; retrain the models")

    root = model_dir.resolve()
    loaded: dict[str, LoadedModel] = {}
    for name in (*expected, SENTIMENT):
        entry = manifest.get("models", {}).get(name)
        if entry is None:
            raise ModelsUnavailable(f"model missing: {name}")
        file = (root / str(entry["file"])).resolve()
        meta_file = (root / str(entry["metadata"])).resolve()
        if root not in file.parents or root not in meta_file.parents:
            raise ModelsUnavailable("model path outside the model directory")
        if not file.is_file() or sha256(file) != entry["sha256"]:
            raise ModelsUnavailable(f"model file does not match its manifest: {name}")
        if not meta_file.is_file() or sha256(meta_file) != entry["metadata_sha256"]:
            raise ModelsUnavailable(f"metadata does not match its manifest: {name}")
        meta = json.loads(meta_file.read_text())
        if name != SENTIMENT and tuple(meta.get("features", ())) != FEATURES:
            raise ModelsUnavailable(f"model expects different features: {name}")
        loaded[name] = LoadedModel(name, joblib.load(file), meta)  # noqa: S301 - verified above

    sentiment = loaded.pop(SENTIMENT)
    return Registry(loaded, sentiment, str(manifest.get("trained_at", "")))
