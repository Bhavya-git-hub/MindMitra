# ADR 0015: Decisions from the October 2026 security audit

- Status: Accepted
- Date: 2026-10-11
- Amends: [ADR 0008](0008-administrator-portal-scope-and-confidentiality.md), item 8
- Details: [SECURITY_AUDIT.md](../SECURITY_AUDIT.md)

## Context

The project owner asked for a full application security audit with the vulnerabilities fixed.
Most fixes were local. Four changed a documented contract or the shape of a flow, so they are
recorded here.

## Decision

1. **Verifying an e-mail needs the password chosen at registration.** The link proves the
   mailbox and the password proves the person who registered, so someone who registers a
   student's address cannot have the student's click activate the stranger's password. A wrong
   password answers like a bad link and leaves the link usable. Registering an address that has a
   self-registered, never-verified account replaces the pending password and sends a fresh link
   (older links stop working), so the first person to register an address no longer keeps it.
   Active accounts and accounts invited by an administrator are untouched and nothing is sent.
2. **The administrator's audit view hides care relationships.** Identifiers alone tell a story:
   "therapist T read student S" is a care relationship and "student S created a safety event" is a
   crisis, both of which ADR 0008 says an administrator cannot learn. On care records
   (`CARE_RECORDS` in `app/application/admin_audit.py`) the view and the CSV export leave out the
   student, the record id and the details, and a student's own actions on care records are not
   listed. Staff actions stay visible with who and when, so access can still be reviewed. The full
   rows stay in the hash-chained log for an investigation outside the product.
3. **Request bodies are capped at 512 KiB** by an outermost ASGI middleware, which refuses a
   declared or streamed body over the cap with 413 before anything parses it. The largest
   legitimate body is a few tens of kilobytes.
4. **Crisis-rule normalisation folds disguised text.** Invisible format characters, combining
   accents, variation selectors and Cyrillic or Greek look-alike letters are removed or folded
   before matching, in both copies of the rules. This only adds matches; it is in line with the
   over-flag policy of [ADR 0013](0013-safety-and-escalation-system.md).

## Consequences

- The verification page now asks for the password. A student who forgot it can register again,
  which sends a new link.
- An administrator can no longer see from the audit log which student a staff member's action was
  about on care records. Investigations needing that go to the database owner under the incident
  process.
- Text in other scripts is folded towards Latin for crisis matching only. Russian or Greek text
  may raise more false alarms, which a counsellor dismisses, as with other accepted false
  positives.
