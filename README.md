# Inbox AI

Inbox AI is a local-first assistant that connects to your Gmail inbox via IMAP and delegates
summarisation, triage, and drafting tasks to a local LLM served by Ollama. The project is designed
with clear boundaries between email transport, storage, and intelligent services so components can
be swapped or extended without touching the whole stack.

## Status

This repository is currently under active development. The initial milestones focus on laying down
project scaffolding, configuration management, and instrumentation so subsequent features can be
implemented incrementally and safely.

The current build includes the intelligence core: each synced message is summarised, key action
items are extracted, and a heuristic priority score is stored alongside the raw email for downstream
workflows. Reply drafts and follow-up tasks are generated automatically and persisted for later
review. The system defaults to deterministic fallbacks if the local LLM is unavailable.

## Getting Started

1. Create and activate a Python 3.11 environment.
2. Install dependencies:

   ```bash
   pip install -e .[dev]
   ```

3. Copy `.env.example` to `.env` and fill in the required values.
4. Run the smoke tests:

   ```bash
   pytest
   ```

5. Perform a mailbox sync once IMAP credentials are configured:

   ```bash
   python -m inbox_ai.cli sync
   ```

6. Review open follow-up tasks and mark them complete as actions are taken:

   ```bash
   python -m inbox_ai.cli follow-ups --follow-limit 10
   ```

7. Launch the optional web dashboard to browse insights, drafts, and follow-ups:

   ```bash
   uvicorn inbox_ai.web:app --reload
   ```

## Configuration

Configuration is managed with Pydantic settings and can be injected from environment variables or an
`.env` file. All variables are namespaced with the `INBOX_AI_` prefix. For example:

```env
INBOX_AI_IMAP__HOST=imap.gmail.com
INBOX_AI_IMAP__USERNAME=your_username
INBOX_AI_IMAP__APP_PASSWORD=application_specific_password
INBOX_AI_FOLLOW_UP__DEFAULT_DUE_DAYS=2
```

Follow-up scheduling is controlled via the `INBOX_AI_FOLLOW_UP__*` settings, which influence the
heuristics used to compute due dates for planned actions.

## Linting & Formatting

- **Ruff** provides fast linting and autofixes.
- **Pylint** is configured to run clean; please keep it warning-free.
- **Mypy** enforces static typing on the `inbox_ai` package.

Run the full quality gate with:

```bash
ruff check src && pylint src/inbox_ai && mypy src/inbox_ai && pytest
```

## Intelligence Services

- The Ollama-backed LLM client generates structured JSON summaries per message.
- Deterministic heuristics provide a fallback summary/action list when the LLM is unreachable.
- A priority score (0–10) is derived from sender hints, tone, and actionable content.
- Reply drafts and follow-up tasks are persisted alongside insights, enabling quick responses and
   task tracking directly from the CLI.

## Web Dashboard

- Launch the FastAPI dashboard with ``uvicorn inbox_ai.web:app --reload`` to browse synced data in a
   single view. The page consumes the same repository methods as ``/api/dashboard`` so the UI and
   API remain consistent.
- A prominent Sync card triggers manual mailbox refreshes; a spinner overlays the page while the
   request runs and results surface through auto-dismissing toast notifications that appear in the
   bottom-right corner.
- Configuration fields are grouped by domain and editable in place. Saving updates writes to the
   ``.env`` file while preserving blank entries, and success/error states also appear as toasts.
- Recent Insights now show inline UID labels, a running ``visible / total`` counter, friendly
   timestamps, action-item summaries, and an inline search box that filters rows instantly in
   the browser.
- Delete buttons beside each insight remove the underlying email from both IMAP and storage. Upon
   completion a toast confirms success (or failure) and the table preserves scroll position.
- Draft and follow-up panels mirror repository data; follow-up status toggles remain available via
   inline forms without leaving the dashboard.


