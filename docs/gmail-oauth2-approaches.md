# Gmail OAuth2 Approaches

> **Date:** 2026-03-28
> **Branch:** `feature/calendar-account-linking`
> **Status:** Draft

---

## Purpose

This note captures the main approaches for moving Inbox AI toward a single
Google OAuth2-based authentication model for both email access and Google
Calendar integration.

It is intended as a future reference when deciding whether to:

- keep the current IMAP/SMTP transport model and retrofit OAuth2 onto it
- move mail access onto the Gmail API and unify mail and calendar under one
  Google API model

---

## Current State In This Repo

The current codebase uses a mixed model:

- Google Calendar already uses OAuth 2.0 via the Calendar REST API.
- IMAP still assumes username plus app password login.
- SMTP still assumes username plus password login.

Relevant implementation points:

- `src/inbox_ai/calendar/google_calendar_client.py`
- `src/inbox_ai/web/app.py`
- `src/inbox_ai/transport/imap_client.py`
- `src/inbox_ai/transport/smtp_client.py`

Current mail transport assumptions that matter:

- IMAP calls `connection.login(username, password)`.
- SMTP calls `self._connection.login(username, password)`.
- Sync logic and mailbox semantics are built around IMAP concepts such as UIDs,
  mailboxes, and MOVE-to-trash behavior.

This means "single Google OAuth2 for everything" is not a UI-only change. It
affects transport, token lifecycle, identity checks, and sync semantics.

---

## Approach 1: Gmail API + Calendar API

### Summary

Use one Google OAuth2 consent flow and talk to both Gmail and Google Calendar
through Google REST APIs.

### What Changes

- Replace IMAP inbox reads with Gmail API calls.
- Replace SMTP sends with Gmail API send operations.
- Reuse the same Google OAuth2 token set for Gmail and Calendar scopes.
- Store one account-bound Google identity and one refresh token set per inbox
  account.

### Benefits

- Cleaner long-term architecture because both mail and calendar use the same
  auth model.
- Better fit for OAuth2 than retrofitting legacy mail protocols.
- Easier identity validation because the authenticated Google account is part
  of the API model.
- Fewer protocol-specific edge cases than IMAP/SMTP XOAUTH2.

### Main Risks

1. Larger implementation change.
2. Gmail API semantics differ from IMAP semantics.
3. Existing sync assumptions would need refactoring.
4. Delete, archive, trash, threading, labels, and incremental sync all behave
   differently from IMAP.

### Repo-Specific Concerns

The current pipeline depends on IMAP-specific ideas:

- `uid` is a core identifier in stored email models.
- mailbox checkpointing is based on IMAP UIDs.
- delete and trash flows assume IMAP mailbox operations.

If Gmail API is adopted, the app will likely need a translation layer or a
migration of persistence assumptions from IMAP UIDs to Gmail message/history
identifiers.

### When This Is The Better Choice

- When long-term maintainability matters more than short-term implementation
  speed.
- When Google-first account integration is the product direction.
- When unified consent and identity handling are more important than preserving
  legacy transport behavior.

---

## Approach 2: IMAP/SMTP XOAUTH2 + Calendar API

### Summary

Keep the existing IMAP and SMTP transport model, but replace password login
with Gmail XOAUTH2 for mail access while continuing to use the Calendar API for
calendar integration.

### What Changes

- Keep the existing mail sync structure largely intact.
- Replace IMAP `login()` with XOAUTH2 authentication.
- Replace SMTP `login()` with XOAUTH2 authentication.
- Reuse Google OAuth2 tokens for Gmail mail scope and Calendar scope.

### Benefits

- Smaller change to the current sync and storage model.
- Preserves more of the existing code path.
- Lower migration cost in the short term.

### Main Risks

1. More awkward protocol integration.
2. More moving parts across IMAP, SMTP, and Calendar.
3. More runtime edge cases when tokens expire during sync or send.
4. Harder debugging because the system spans legacy protocols plus modern API
   auth.

### Repo-Specific Concerns

The transport layer is currently password-shaped, not OAuth-shaped:

- `src/inbox_ai/transport/imap_client.py` would need XOAUTH2 support via
  `authenticate`, not `login`.
- `src/inbox_ai/transport/smtp_client.py` would need XOAUTH2 support instead of
  standard username/password login.
- Error handling, reconnect behavior, and token refresh would need to be added
  to mail operations that currently assume stable credentials.

This approach preserves the existing sync model, but it leaves the architecture
split between:

- Gmail OAuth2 credentials
- IMAP protocol behavior
- SMTP protocol behavior
- Calendar REST API behavior

That is workable, but less clean.

### When This Is The Better Choice

- When minimizing short-term refactor cost is the priority.
- When preserving the existing IMAP-based sync pipeline matters.
- When the project needs an incremental path before a larger mail API rewrite.

---

## Cross-Cutting Risks For Either OAuth2 Path

### 1. Google Scope Friction

Mail access is more sensitive than calendar-only access.

Potential issues:

- broader consent screen
- reduced user trust because requested permissions are heavier
- stricter Google verification requirements for wider distribution

### 2. Refresh Token Lifecycle

Potential issues:

- refresh tokens not returned on every consent flow
- revoked or expired tokens breaking background sync
- token rotation handling becoming mandatory
- reconnect UX needing to be reliable

### 3. Identity Mismatch

Potential issue:

- the Google account used for OAuth2 may not match the inbox account the app is
  configured to sync

Mitigation:

- always fetch and persist the authenticated Google account email
- compare it against the configured inbox account before enabling sync/send

### 4. Multi-Account Complexity

Potential issues:

- each inbox account needs separate tokens
- each inbox account needs its own selected calendar
- checkpointing and background sync must remain account-bound

### 5. Background Sync Stability

Calendar actions are occasional. Mail access is continuous.

Potential issues:

- token expiry during long sync cycles
- partial failures during send or fetch
- refresh behavior needing to work during background operations, not only during
  interactive settings flows

---

## Recommendation

### Preferred Long-Term Direction

If the product direction is truly Google-first, prefer:

- Gmail API for mail
- Calendar API for calendar
- one Google OAuth2 consent flow

Reason:

- cleaner architecture
- cleaner identity model
- less protocol mismatch over time

### Preferred Short-Term Direction

If the immediate goal is to move off app passwords with minimum disruption,
prefer:

- XOAUTH2 for IMAP/SMTP
- existing Calendar API integration
- incremental account-scoped token storage

Reason:

- lower short-term code churn
- less disruption to sync and persistence assumptions

---

## Decision Rule

Choose Gmail API + Calendar API if the team is willing to change the mail
transport model now.

Choose IMAP/SMTP XOAUTH2 + Calendar API if the team wants the smallest initial
auth migration and accepts higher protocol complexity later.

---

## Suggested Next Steps

1. Decide whether the product should remain transport-agnostic or become
   explicitly Google-first.
2. If staying incremental, prototype XOAUTH2 in IMAP and SMTP first.
3. If going Google-first, design the Gmail API identity and sync model before
   implementing auth.
4. In either case, persist Google account identity and tokens per inbox account.