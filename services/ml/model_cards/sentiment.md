# Model card: tone of check-in notes (`sentiment`)

A three-way classifier (negative, neutral, positive) for the short notes students add to a
check-in. It is trained by `training/sentiment.py` on synthetic notes. Versions look like
`sentiment-tfidf_naive_bayes-20261010-1a2b3c4d`.

> **Tone is not mood, and neither is a diagnosis.** This model guesses the tone of a sentence.
> It does not understand context, sarcasm or mixed feelings well, and it has never seen a real
> student's note.

## Purpose

The "tone of your notes" indicator shows the student the share of their last notes that read
as negative (at least 3 notes needed; moderate from 25% negative, elevated from 50%). It is
shown **only to the student**. A therapist's view leaves it out and the API does not even send
the notes for it ([ADR 0011](../../../docs/adr/0011-wellness-indicator-models.md)). It never
triggers anything. Crisis detection is a separate, rule-based layer (`safety/`) and does not
depend on this model.

## Model

TF-IDF on word 1-2-grams and character 2-5-grams (within words), then complement naive Bayes
(alpha 0.3). Logistic regression on the same features was compared. Text is cleaned the same
way in training and inference (`preprocessing/text.py`: whitespace collapsed, at most 2,000
characters). The model runs in-process; nothing is sent anywhere and no text is logged.

## Training data

`data/text_corpus.py` (`synthetic-notes-2026.10.1`): 60 sentence patterns (20 per tone), each
filled with slot words (subjects, places, people, times and feeling words) to make 10,200
notes. Feeling words are shared across patterns of the same tone. 24 hand-written hard
sentences (mixed feelings, sarcasm, negation) are kept apart as an extra check.

## Method and results (synthetic data only)

Whole patterns are held out: the test set uses 4 patterns per tone that training never saw,
and cross-validation groups by pattern. This measures generalisation to new sentence shapes,
which a random split hides.

| Model | Grouped CV macro F1 | Test accuracy | Test macro F1 | Test ROC-AUC (OvR) | Hard cases |
|-------|---------------------|---------------|---------------|--------------------|------------|
| TF-IDF + naive Bayes (selected) | 0.657 ± 0.117 | 0.817 | 0.820 | 0.958 | 11/24 (0.458) |
| TF-IDF + logistic regression | 0.636 ± 0.149 | 0.800 | 0.806 | 0.930 | 12/24 (0.500) |
| Transformer trained from scratch | n/a | 0.551 | 0.505 | 0.701 | 13/24 (0.542) |
| Majority class | | 0.333 | | 0.5 | |

On a random split, where test sentences share patterns with training, both TF-IDF models score
macro F1 1.000. The gap between 1.000 and about 0.82 is how much depends on memorised sentence
shapes. Most errors on new patterns are neutral notes read as positive (170 of 680).

### Transformer approaches

- **Pretrained transformers (DistilBERT, RoBERTa sentiment models) were not evaluated.** The
  development environment cannot reach the Hugging Face hub or the PyTorch download index, so
  no pretrained weights could be fetched. A pretrained model is likely to do better on real,
  varied language, and evaluating one is the first next step when downloads are possible.
- **A small transformer encoder trained from scratch** (`training/sentiment_transformer.py`:
  2 layers, 64 dimensions, 4 heads, about 82,000 parameters, 8 epochs) was evaluated on the same
  split when PyTorch is installed (`uv run --group nlp`). It does worse than TF-IDF on unseen
  patterns: 10,200 synthetic sentences are far too few to learn language from scratch. It is
  reported, not served.

## Limitations

- **Synthetic sentences only.** Real notes are shorter, messier, multilingual, full of slang,
  typos and in-jokes. Performance on them is unknown and probably lower.
- **Bag of n-grams.** The model sees words and fragments, not meaning. Negation ("not bad"),
  sarcasm ("great, another all-nighter") and mixed feelings are often wrong: less than half the
  hard cases are right.
- **Neutral is the weakest class.** Plain factual notes are often read as positive.
- **English only.** Notes in other languages, or mixing languages, are not supported.
- **No fairness evaluation.** Dialects and ways of expressing feelings differ between groups;
  this has not been measured.
- **Not a safety tool.** It must never be used to decide whether a student is at risk.
- **Pickle trust** as for the other indicator models: only files in `models/manifest.json` with
  matching hashes are loaded.
