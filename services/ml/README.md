# services/ml — ML inference service

Internal-only service (called by `services/api`, never by browsers).
Python, scikit-learn, PyTorch, Hugging Face Transformers.

```
app/          FastAPI inference endpoints (internal auth token)
safety/       crisis detection fallback rules, output wording guards, disclaimers
training/     training & evaluation pipelines (synthetic / consented de-identified data only)
model_cards/  one model card per model: purpose, data, metrics, limitations, fairness
tests/        unit tests + safety regression tests
```

No model output is a diagnosis. Every response passes through `safety/` first.
