# ADR 0010: AI wellness companion, its safety layer and who is alerted

- Status: Accepted
- Date: 2026-10-10

## Context

Students asked for somewhere to talk things through between appointments: exam pressure, career
worries, homesickness, loneliness, comparing themselves with others, feeling like an imposter,
time, sleep, relationships, money and settling in. A generative model can help with that, but
it is the riskiest feature in the product. It might sound like a clinician, diagnose, talk
about medication, encourage dependence, or miss someone in danger. The student portal already
had an entry page that said the companion was not available, and the consent screen already
offered "Keep my AI companion history".

While wiring escalation we also found a gap. An alert for a student with no care-team therapist
was created unassigned, but only therapists on that student's care team could see unassigned
alerts. So nobody saw it, while the student was told "a member of your institution's support
team has been asked to reach out".

## Decision

1. **One path: web, then API, then AI service, then safety layer.** The browser only talks to
   `/api/v1/companion/*`. The API calls the internal AI service (`services/ml`,
   `POST /internal/v1/companion/respond`) with a fresh HS256 service token (`aud=mindmitra-ml`,
   `iss=mindmitra-api`, five minutes) signed with `ML_SERVICE_TOKEN`. Only the AI service talks to
   a model. No model key reaches the API or the browser. The AI service is stateless: it stores,
   logs and measures no text, and its validation errors do not echo input.
2. **The API checks for a crisis before anything else, and the model never handles one.** The
   API runs the crisis rules on every message before switches, limits or the AI service. A
   crisis gets a fixed, reviewed reply, the institution's crisis contacts and an alert, even
   when the companion is switched off, the student is over a limit or the AI service is down.
   The AI service runs the same rules again (on the message, and on the model's draft) and
   reports a crisis instead of replying. Both copies are the same file
   (`safety/crisis_lexicon.json` with `crisis_rules.py`), and a test fails if they differ.
   - The rules allow for stretched letters ("diiie"), leetspeak, Hinglish and Hindi, and
     explicit negations ("I'd never kill myself"). A negation is overridden when the message
     sounds ambivalent ("but sometimes I want to die").
   - Imminence words (tonight, a plan, a note) raise the severity. A crisis about someone else
     gets guidance for helping them.
   - Softer signals, such as hopelessness, get gentle support with contacts and no alert.
3. **Guards around the model.**
   - Before the model: emails, links, phone numbers and ID-like numbers are replaced with
     placeholders. Requests for a diagnosis, for medication advice, or attempts to change the
     companion's instructions get fixed replies without calling the model.
   - The system prompt says it is an AI, not a therapist, never diagnoses, labels or names
     medication, and encourages human support. Every tenth turn, and after repeated distress,
     it suggests talking to a person.
   - Context is the last 12 turns within 8,000 characters of this conversation only. It never
     includes journals, notes or anything about other people. Crisis and failure turns are left
     out.
   - After the model: diagnosis, medication, harm methods, claims to be human or a therapist,
     dependency framing, substance coping, contact details, crisis language and empty drafts
     all fall back to a fixed safe reply.
4. **Provider behind an interface.** `LLMProvider` (`model_id`, `generate`, `aclose`).
   - `AnthropicProvider` calls the Messages API over HTTPS. The key comes only from
     `ANTHROPIC_API_KEY` and is sent only in the request header. The model comes from
     `ANTHROPIC_MODEL`.
   - `FakeProvider` gives fixed supportive replies by topic and is used for development, tests
     and end-to-end runs. Settings refuse it in staging and production.
   - Amazon Bedrock, which `AI_ML_ARCHITECTURE.md` prefers for data residency, fits the same
     interface and can replace the default without touching the safety layer. Before
     production, the provider's data-processing terms must rule out training on, and retention
     of, student text.
5. **Replies are not streamed.** The output guard has to see the whole draft before a student
   does, so the API waits for the complete reply (25 s timeout). On failure it tries once more
   after a dropped connection. After three failures in a row it stops calling for 30 s.
   Whenever the service fails, the student gets a fixed "I'm having trouble replying" message
   that points to Get help now.
6. **Limits and switches.**
   - 8 messages a minute per student (in process).
   - A daily allowance per student: institution setting `companion_daily_messages`, 10 to 500,
     default 100.
   - `companion_enabled` per institution, and `COMPANION_ENABLED` for the whole deployment.
   - A second message while a reply is pending is refused (409).
   - Messages that suggest a crisis are never limited or switched off.
7. **Retention the student controls.** Messages are encrypted at rest (`EncryptedText`).
   - A conversation expires a day after the last message, or 90 days after it with the
     `AI_COMPANION_HISTORY` consent.
   - Expired conversations are hidden at once, and the scheduler deletes them.
   - Deleting a conversation removes it immediately.
   - Teachers, therapists and administrators have no companion route.
8. **Alerts go to the counselling team when there is no care team.** One function
   (`application/escalation.py`) raises every alert from Get help, a teacher's safety referral
   and the companion.
   - It goes to the student's primary care-team therapist when there is a live care link.
   - Otherwise it stays unassigned, and every verified, active therapist at the institution is
     notified and can see it. The first to acknowledge it takes it.
   - Notifications say only that a student may need support, never what was written. A
     companion alert carries no excerpt.
   - A companion alert is reused for 24 hours, and a more urgent message raises its severity
     and tells the same people again.
   - Imminent alerts are due within five minutes.
   - This amends item 5 of [ADR 0006](0006-therapist-portal-access-verification-and-note-confidentiality.md).
9. **The disclaimer is part of every reply.** The status endpoint, every exchange and the chat
   page carry "I'm an AI wellness companion, not a therapist. I can't diagnose or give medical
   advice, and I can make mistakes. If you're in danger, use Get help now."

## Consequences

- A student can talk to the companion. Someone in danger is shown contacts at once, and a
  person is asked to reach out, whether or not the model is working.
- Any verified therapist at an institution may see that a student without a care team needs
  support (name and category, never text). This is the trade-off the project owner chose so
  that no request for help goes unseen.
- The per-minute limit is per API process. Several instances need a shared limiter. The daily
  allowance is counted in the database, so it already holds across instances.
- The crisis rules are a high-recall lexicon. They will flag some messages that are not
  crises, and they cannot understand meaning. A trained classifier can add to them later (the
  API already records a classifier detector when the AI service reports one), but it will never
  replace them.
- Replies arrive all at once rather than word by word.
- Reporting a reply and suggesting resources from the library (retrieval) are not built yet.
