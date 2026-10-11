"""Writing trained models and their metadata in the layout ``inference.registry`` loads.

The manifest is written last and atomically, so a half-finished run never replaces a working
set: files that changed without a new manifest fail the hash check and are refused.
"""

import json
import os
from pathlib import Path
from typing import Any

import joblib

from inference.registry import FORMAT, MANIFEST, library_versions, sha256


def _write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def save_model(out_dir: Path, name: str, model: Any, meta: dict[str, Any]) -> dict[str, str]:
    """Save one model; returns its manifest entry."""
    folder = out_dir / name
    folder.mkdir(parents=True, exist_ok=True)
    model_path = folder / "model.joblib"
    tmp = folder / "model.joblib.tmp"
    joblib.dump(model, tmp, compress=3)
    os.replace(tmp, model_path)
    meta_path = folder / "metadata.json"
    _write_json(meta_path, meta)
    return {
        "algorithm": str(meta["algorithm"]),
        "version": str(meta["version"]),
        "file": f"{name}/model.joblib",
        "sha256": sha256(model_path),
        "metadata": f"{name}/metadata.json",
        "metadata_sha256": sha256(meta_path),
        "bytes": str(model_path.stat().st_size),
    }


def write_manifest(
    out_dir: Path, entries: dict[str, dict[str, str]], *, trained_at: str, data: dict[str, Any]
) -> None:
    _write_json(
        out_dir / MANIFEST,
        {
            "format": FORMAT,
            "trained_at": trained_at,
            "libraries": library_versions(),
            "data": data,
            "models": entries,
        },
    )
