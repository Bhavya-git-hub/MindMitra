# Trained models (not committed)

Build them with `uv run python -m training.train` from `services/ml`. The run writes one folder
per indicator (`model.joblib` and `metadata.json`) and `manifest.json` with each file's SHA-256
and the library versions used.

The service loads a model only when it is listed in the manifest, its hash matches, it is
inside this directory, and it was trained with the same scikit-learn and XGBoost minor versions.
joblib files can run code when loaded, so never copy model files here from anywhere you do not
trust. All models are trained on synthetic data; see `../model_cards/`.
