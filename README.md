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

## Roadmap

Planned milestones include:

1. Project foundation (configuration, logging, testing harness). ✅
2. IMAP ingestion and persistence. ✅
3. LLM-backed intelligence services (summaries, prioritisation). ✅
4. Draft generation and follow-up tracking. ✅
5. User-facing CLI/TUI enhancements.
