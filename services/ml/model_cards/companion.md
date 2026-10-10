# Model card: wellness companion (`companion-prompt-2026.10.1`)

## Purpose

A supportive conversation partner for everyday student pressures: academic stress, career
anxiety, homesickness, loneliness, peer comparison, imposter feelings, time management, sleep
and lifestyle, relationship stress, financial stress and settling in. It listens, helps a
student reflect, suggests small coping ideas and points to people who can help.

**It is not a therapist.** It does not diagnose, label conditions, discuss medication or give
medical, legal or financial advice. It does not handle emergencies: a crisis is answered with
a fixed reply and crisis contacts, and a person is alerted, without calling the model.

## System

- **Model:** chosen by `LLM_PROVIDER`. `anthropic` uses the Messages API with `ANTHROPIC_MODEL`
  (default `claude-sonnet-5-5`), up to 400 output tokens and a 20 s timeout. `fake` gives fixed
  offline replies for development and tests, and is refused in staging and production.
- **Prompt:** `app/companion/prompts.py` has nine fixed rules plus guidance for the detected
  topic. Every tenth turn, and after repeated distress, it adds a suggestion to talk to a
  person.
- **Context:** this conversation only, the last 12 turns within 8,000 characters. Crisis and
  failure turns are left out.
- **Input guard:** messages over 2,000 characters are refused. Emails, links, phone numbers and
  ID-like numbers are replaced with placeholders. Diagnosis requests, medication requests and
  prompt injection get fixed replies.
- **Output guard:** diagnosis, medication, harm methods, claims to be human or a therapist,
  dependency framing, substance coping, contact details, crisis language and empty drafts are
  replaced with a fixed safe reply.
- `model_version` on every reply records model, prompt and crisis-rules versions.

## Evaluation (synthetic data only)

| Suite | Cases | Requirement | Result |
|-------|-------|-------------|--------|
| `tests/suites/redteam.yaml` | 17 | Diagnosis and medication requests, method seeking, jailbreaks, prompt injection, dependency and impersonation are refused or redirected | 17/17 |
| `tests/suites/output_guard.yaml` | 33 | Unsafe drafts are caught; safe drafts pass | 33/33 |
| `tests/suites/normal_conversations.yaml` | 12 | Each supported topic gets a normal reply with no crisis and no escalation | 12/12 |

These suites test the guards around the model (with scripted drafts), not the quality of a
real model's replies. Before production, a sample of real-model replies on the normal suite
should be rubric-graded and reviewed by a clinician.

## Limitations

- The guards are pattern-based. A harmful reply phrased in an unexpected way could pass the
  output guard, and some harmless replies are replaced with the fallback.
- Replies are not streamed, so a student waits for the whole reply.
- It does not suggest resources from the library yet, and students cannot report a reply yet.
- The provider's data-processing terms must rule out training on, and retention of, student
  text before production use.

## Owners and review

Safety lead and clinical advisor. Re-run all suites on any change to the prompt, the guards,
the provider or the model. Bump `PROMPT_VERSION` whenever the prompt changes.
