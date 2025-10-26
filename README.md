# Inbox AI

Inbox AI is a local-first assistant that connects to your Gmail inbox via IMAP and delegates
summarisation, triage, and drafting tasks to a local LLM served by Ollama. The project is designed
with clear boundaries between email transport, storage, and intelligent services so components can
be swapped or extended without touching the whole stack.

## Status

This repository is currently under active development. The initial milestones focus on laying down
project scaffolding, configuration management, and instrumentation so subsequent features can be
implemented incrementally and safely.

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

## Configuration

Configuration is managed with Pydantic settings and can be injected from environment variables or an
`.env` file. All variables are namespaced with the `INBOX_AI_` prefix. For example:

```env
INBOX_AI_IMAP__HOST=imap.gmail.com
INBOX_AI_IMAP__USERNAME=your_username
INBOX_AI_IMAP__APP_PASSWORD=application_specific_password
```

## Linting & Formatting

- **Ruff** provides fast linting and autofixes.
- **Pylint** is configured to run clean; please keep it warning-free.
- **Mypy** enforces static typing on the `inbox_ai` package.

Run the full quality gate with:

```bash
ruff check src && pylint src/inbox_ai && mypy src/inbox_ai && pytest
```

## Roadmap

Planned milestones include:

1. Project foundation (configuration, logging, testing harness).
2. IMAP ingestion and persistence. ✅
3. LLM-backed intelligence services (summaries, prioritisation).
4. Draft generation and follow-up tracking.
5. User-facing CLI/TUI enhancements.
