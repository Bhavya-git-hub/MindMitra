# ADR 0009: Therapist communication, real-time events and notifications

- Status: Accepted
- Date: 2026-10-10

## Context

Students and therapists already could book, confirm and cancel appointments and exchange
messages, but nothing told anyone what had happened until they reloaded a page. Notifications were
written to the database with no way to read them. There was no way to move an appointment, no
reminder before one, and a conversation disappeared from the student's view once the care link
ended. The communication between a student and their therapist is among the most sensitive data
the product holds, so every new channel (a socket, an inbox, an e-mail) is another place it could
leak.

## Decision

1. **Events are hints, never content.** The API pushes events over one WebSocket per tab
   (`/api/v1/ws`): `notification`, `notifications_read`, `message`, `message_read` and
   `appointment`. They carry ids and fixed words only, for example
   `{"type":"message","with":"<user id>","message_id":"<id>"}`. A view that hears one reloads
   through the normal REST API, so the same permission, policy and consent checks decide what
   anyone sees. Nothing that was written by a
   person, and no name or time, ever travels on the socket.
2. **The token goes in the first frame, not the URL.** The client sends
   `{"type":"auth","token":...}` within 10 seconds of connecting; a URL would end up in proxy and
   server logs. The server checks the `Origin` against the allowed web origins (4403 otherwise),
   allows at most five sockets per person (4429), re-checks the session every minute so signing
   out, suspension or a role change closes the socket (4401), and drops a client that falls 100
   events behind (1013) rather than buffering without limit.
3. **Events are sent only after the transaction commits.** Use cases queue events on the database
   session; a SQLAlchemy `after_commit` hook publishes them and `after_rollback` drops them. A
   client is never told about a message or a booking that was rolled back. A failing broker is
   logged and never fails the request.
4. **One process, one hub, for now.** The broker is an in-memory hub behind an `EventBroker`
   interface. Several API instances need a shared broker (for example Redis pub/sub) behind the
   same interface. Until then the client reconnects with capped, jittered backoff and refreshes
   on reconnect and whenever the tab comes back into view, so a missed event costs freshness,
   not data. Conversations also refresh every two minutes as a safety net.
5. **Notifications are content-free and pluggable.** `notify()` is the one way to tell someone
   something: it writes the in-app notification, queues the real-time event and, when the
   institution has switched e-mail on, a `notify.deliveries` row. Titles are fixed phrases and
   payload keys come from a short allowlist whose values must be UUIDs or a short fixed slug
   (checked in code, tested). Delivery goes through `NotificationProvider` (`channel`, `send`);
   adding push or SMS means writing a provider and registering it in `build_providers`. Every
   message uses one template that says only that there is something new. Retries back off 1, 5,
   30 and 120 minutes and stop after five attempts or a permanent error. A channel with no
   provider is recorded as `skipped`, not silently dropped, and a suspended or deleted recipient
   is skipped.
6. **Reminders once, to both people.** A scheduler (in the API when `SCHEDULER_ENABLED=true`, or
   `python -m app.workers.scheduler [--once]`) sends appointment reminders at the institution's
   chosen hours to the student and the therapist. Each (appointment, start time, offset) is
   claimed with a unique row before anyone is notified, so several schedulers never remind twice.
   An appointment confirmed after two offsets have passed gets one reminder, not two. Moving an
   appointment gives the new time its own reminders.
7. **Moving an appointment.** Either person can move a live appointment that has not started to
   another open time of the same therapist, at least two hours ahead, up to three times. The row
   is updated in place (history, messages and reminders stay attached), and the database's
   exclusion constraints still refuse a time that either person already has. When the student
   moves it, it goes back to `requested` for the therapist to confirm. When the therapist moves
   it, it stays confirmed and the student is told.
8. **Cancellation reasons are a fixed list** (`schedule_conflict`, `feeling_better`, `unwell`,
   `therapist_unavailable`, `other`), optional, and only allowed with a cancellation (database
   check). Free text would invite more than the person meant to share. The reason never appears
   in a notification.
9. **Conversation history.** Writing still needs an active care link. Reading is the same, with
   one exception: a student keeps the messages they already exchanged after the care team ends.
   The therapist's access still ends with the link ([ADR 0006](0006-therapist-portal-access-verification-and-note-confidentiality.md)).
   With no link and no history there is nothing to read, and it looks missing (404).
10. **Teachers and administrators have no path in.** They hold neither
    `message:participate:own` nor the appointment-booking or managing permissions, so every
    conversation, message, move and cancel route refuses them (403). The notification inbox is
    strictly the caller's own (another person's notification is a 404), and events are addressed
    to one user id. Administrators see appointment counts only, as before
    ([ADR 0008](0008-administrator-portal-scope-and-confidentiality.md)).

## Consequences

- Students and therapists see messages, requests, moves, confirmations, cancellations and a
  starting session as they happen, and a bell shows what is new in every portal.
- The API process needs a WebSocket implementation (`websockets`) and the web app's
  Content-Security-Policy allows the API's `ws(s)` origin.
- Running more than one API instance needs a shared broker before live updates reach every tab;
  until then they arrive on refresh, reconnect or focus.
- E-mail is ready but sends nothing until a provider is configured; deliveries are recorded as
  `skipped` meanwhile. `NOTIFICATION_EMAIL_PROVIDER=log` is for development only.
- Goal reminders are still stored but not sent.
