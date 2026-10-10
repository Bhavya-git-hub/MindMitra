# Model card: wellness indicators from check-ins

Five models, one per indicator, trained by `training/train.py` on synthetic data. Versions look
like `burnout_risk-logistic_regression-20261010-1a2b3c4d` (indicator, algorithm, training date,
data fingerprint) and are returned with every result.

> **These are wellness indicators, not diagnoses.** None of these models is a clinical,
> diagnostic or screening tool. None has been validated with real students. Their scores mean
> "the check-ins look like the synthetic students the generator labelled this way", and nothing
> more.

## Purpose

To help a student notice patterns in their own check-ins over the last 28 days, and, if the
student chooses to share them, to give their care-team therapist a starting point for a
conversation. They never raise an alert, notify anyone or change anything on their own
([ADR 0011](../../../docs/adr/0011-wellness-indicator-models.md)).

| Indicator | Kind | Meaning shown to the student |
|-----------|------|------------------------------|
| `stress_level` | low / moderate / high | How much pressure your check-ins suggest |
| `burnout_risk` | binary, banded | Signs of running low on energy while under academic load |
| `social_isolation` | binary, banded | Signs of feeling disconnected or alone |
| `sleep_lifestyle_risk` | binary, banded | Signs that sleep is short, late or irregular |
| `career_anxiety` | binary, banded | Signs of worry about career and the future |

Binary indicators are shown as a band, never as a number. "Elevated" starts at the cut-off with
the best F1 on out-of-fold training predictions; "moderate" starts where 80% of synthetic
students with the label are still caught. The API returns bands and the model's level only.

## Inputs

One record per day the student checked in (`preprocessing/records.py`): mood, energy and
stress (1 to 5), sleep minutes, sleep quality, bedtime, and the emotion and stressor words the
app offers. Free text is never a feature. `preprocessing/features.py` turns 28 days into 31
numbers: check-in days, the longest gap, means, spreads, a mood slope, shares of short sleep
and late bedtimes, and the share of days each emotion or stressor was picked. Values outside
the app's ranges are dropped, not clipped. With fewer than 7 check-in days every indicator says
"not enough data".

## Training data

`data/synthetic.py` (`synthetic-cohort-2026.10.1`): 4,000 fictional students, each with six
hidden traits (academic load, social connection, sleep regularity, career worry, money strain,
coping). Labels are thresholds on combinations of those traits, with 5% of binary labels and
7% of stress levels flipped. Check-ins are noisy, partly missing daily observations of the same
traits, with random engagement (some students check in most days, some rarely). Students with
fewer than 7 check-in days are left out (388 of 4,000). No real student data was used.

## Method

1. Stratified 80/20 split; the 20% test set is used once.
2. Five-fold stratified cross-validation compares logistic regression (median imputation with
   missing-value flags, scaling), random forest (300 trees) and XGBoost (300 shallow trees, which
   handles missing values itself). Binary indicators are compared on ROC-AUC, stress level on
   macro F1.
3. The best is refitted on all training data and scored on the test set.
4. Permutation importance on the test set shows which features the model leans on.

## Results on held-out synthetic data

From `evaluation/reports/REPORT.md` (seed 20261010). Every model beats its baseline, but the
three algorithms are within one standard deviation of each other on every indicator, so the
choice between them is not meaningful on this data.

| Indicator | Selected | Accuracy | Precision | Recall | F1 | ROC-AUC | Baseline accuracy |
|-----------|----------|----------|-----------|--------|----|---------|-------------------|
| stress_level | XGBoost | 0.838 | 0.842 (macro) | 0.842 (macro) | 0.842 (macro) | 0.944 (OvR) | 0.436 (always moderate) |
| burnout_risk | logistic regression | 0.865 | 0.743 | 0.710 | 0.726 | 0.865 | 0.747 |
| social_isolation | logistic regression | 0.888 | 0.761 | 0.728 | 0.745 | 0.874 | 0.776 |
| sleep_lifestyle_risk | logistic regression | 0.899 | 0.849 | 0.734 | 0.787 | 0.912 | 0.746 |
| career_anxiety | logistic regression | 0.871 | 0.733 | 0.702 | 0.717 | 0.849 | 0.768 |

Confusion matrices, cross-validation spreads, band shares and feature importances are in the
report and in `evaluation/reports/<indicator>.json`.

## Limitations

- **Synthetic data only.** The models learn the rules written into the generator. The scores
  above show the pipeline works; they say nothing about accuracy with real students. Real data
  would be messier, differently distributed and labelled by people, not by a formula.
- **No clinical accuracy is claimed.** Labels are not clinical constructs. "Burnout risk" here
  is a generator threshold, not a validated burnout measure, and no indicator corresponds to a
  diagnosis or a screening instrument.
- **One feature can dominate.** Stress level leans almost entirely on the mean stress answer,
  social isolation on mood and "lonely", career worry on the "career" stressor. A student who
  never picks those words, or uses them differently, will be scored very differently.
- **Self-report only.** Indicators reflect what a student chose to log. Students who check in
  rarely, skip questions or answer optimistically are hard to read, and silence is not
  evidence of wellbeing.
- **Bands are not calibrated to real prevalence.** About 22-25% of synthetic students are in
  each positive class; real prevalence is unknown. With the 80% recall target the moderate band
  is narrow (3-8% of test students). The cut-offs would need to be set again on real data.
- **No fairness evaluation.** The synthetic data has no demographic attributes, so performance
  across groups (gender, culture, language, disability, international students) is unknown.
  Expressing feelings differs between groups; this is a real risk with real data.
- **Extrapolation.** Combinations the generator never produces (for example, very short sleep
  with very high mood) give scores with no basis.
- **28-day window, fixed vocabulary.** Changes within a window are averaged out, and emotion or
  stressor words outside the app's list are ignored.
- **Model files are pickles.** joblib files can run code when loaded. The service loads only
  files listed in `models/manifest.json` with matching SHA-256 hashes, from inside the model
  directory, trained with the same library versions. Never load a model file from elsewhere.

## Before any real use

Ethics approval, informed consent for research use, labels from validated instruments or
clinicians, a calibration and fairness study, threshold review with counsellors, and a
clinical-safety assessment. Until then, these indicators are a development feature.
