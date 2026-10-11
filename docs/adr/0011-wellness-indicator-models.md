# ADR 0011: Wellness indicator models, and who sees them

- Status: Accepted
- Date: 2026-10-10

## Context

Students already log mood, energy, stress, sleep, emotions and stressors, with an optional note.
The project owner asked for a machine-learning pipeline that turns these into six wellness
indicators: stress level, academic burnout risk, sentiment, social isolation, sleep and
lifestyle risk, and career anxiety. The pipeline needed preprocessing, feature engineering,
training, validation, evaluation, serialisation and an inference API, comparing logistic
regression, random forest and XGBoost, and evaluating transformer approaches for text.

There is no real data, and there must not be any in development. The indicators touch the most
sensitive things a student shares, so who sees them, and what they may trigger, had to be
decided before any model was trained.

## Decision

1. **Wellness indicators, never diagnoses.** Every result is a band (low, moderate, elevated) or
   a level, with the model's version and a fixed disclaimer: "These are wellness indicators
   based on what you shared in check-ins. They are not a diagnosis or a clinical assessment,
   and they can be wrong." Raw scores stay inside the services. With fewer than 7 check-in days
   (or 3 notes for tone) the answer is "not enough data".
2. **Synthetic data only, trained in `services/ml`.** A seeded generator makes 4,000 fictional
   students with hidden traits, noisy daily check-ins and label noise. A second generator makes
   10,200 notes from 60 sentence patterns. Both are versioned, and every model records the
   data fingerprint. Feature code (`preprocessing/`) is shared by training and inference.
3. **Comparison by cross-validation, one look at the test set.** Five-fold stratified CV picks
   among logistic regression, random forest and XGBoost (ROC-AUC for binary indicators, macro F1
   for stress level). Sentiment compares TF-IDF with logistic regression or naive Bayes, holding
   out whole sentence patterns, plus a small transformer trained from scratch. Every run writes
   accuracy, precision, recall, F1, confusion matrices, ROC-AUC, baselines and feature importance
   to `services/ml/evaluation/reports/`, which is committed.
4. **Model files are build output, verified before loading.** `python -m training.train`
   writes joblib files and a `manifest.json` with SHA-256 hashes and library versions to
   `services/ml/models/` (ignored by git). The service loads only files in the manifest, inside
   the model directory, with matching hashes and the same scikit-learn and XGBoost minor
   versions. If anything is missing or wrong, the indicator endpoints answer 503 and the
   companion keeps working.
5. **One boundary: API, then AI service.** The browser calls the API only.
   - `GET /api/v1/me/wellness/indicators`: the student's own indicators, including the tone of
     their own notes.
   - `GET /api/v1/therapist/students/{id}/indicators`: only for a verified therapist with a live
     care link **and** the student's `share_ai_signals_with_care_team` consent (missing link:
     404; missing consent: 403). Notes are not read or sent, so the tone indicator is left out.
     Every read is audited with counts only.
   - Teachers and administrators have no route to individual indicators.
   - The API sends 28 days of per-day records to `POST /internal/v1/indicators` with the
     ADR 0010 service token. Indicator calls have their own circuit breaker, so missing models
     never switch the companion off.
6. **Indicators never act.** No alert, notification, recommendation or flag comes from an
   indicator. Crisis detection stays rule-based (ADR 0010) and does not depend on these models.
7. **The consent copy says what is shared.** `share_ai_signals_with_care_team` is now "Share AI
   wellness indicators with my therapist", listing the indicators and saying notes, journal and
   companion conversations are never shared.
8. **Pretrained transformers are a documented gap.** The development environment cannot
   download pretrained weights, so none was evaluated. The from-scratch encoder did worse than
   TF-IDF and is reported, not served.

## Consequences

- A student can see patterns in their own check-ins, and choose to share them with their
  therapist.
- The reported metrics only show the pipeline works on data shaped like the generator's. No
  claim of real-world or clinical accuracy can be made. The limitations are in
  `services/ml/model_cards/wellness-indicators.md` and `services/ml/model_cards/sentiment.md`.
- Before real use: ethics approval, labels from validated instruments or clinicians,
  calibration of the bands to real prevalence, a fairness study and a pretrained text model.
- Anyone running the stack must train the models first (about two minutes, or seconds with
  `--quick`). Without them the indicator endpoints answer 503.
- There is no web page for indicators yet.
