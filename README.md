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

The FastAPI dashboard provides a modern, responsive interface for browsing and managing your email insights:

**Core Features:**
- Launch with `uvicorn inbox_ai.web:app --reload` to access synced data through a clean, unified view
- Material Design 3 UI with theme support (Default, Plant, Dark, High Contrast, Vibrant, Teal, Lavender)
- Consistent header navigation across all pages with user account display
- Service worker integration for offline-first caching and background sync capabilities

**Email Insights:**
- Browse recent insights with inline UID labels and visible/total counters
- Advanced search box for instant filtering with field queries (e.g., `from:alice`, `priority:>=7`, `is:followups`)
- Priority-based filtering (Urgent, High, Normal, Low, All)
- Category-based filtering with dynamic category management
- Follow-up status filtering (Open, Completed, All)
- Sortable columns with friendly timestamps and action-item summaries
- Lazy-loaded detail view for email content to optimize performance

**Email Management:**
- Delete individual emails or bulk delete with IMAP trash integration
- Email deletion preserves scroll position and shows toast notifications
- Comprehensive CSRF protection for all POST operations
- Cache invalidation strategy ensures fresh data after modifications

**Draft Management:**
- Generate AI-powered reply drafts with inline editing
- Save, regenerate, or delete drafts directly from the insight detail view
- Fallback draft generation when LLM is unavailable
- Manual draft editing with provider tracking

**Follow-up Tasks:**
- View and manage follow-up tasks with inline status toggles
- Mark tasks as complete or reopen them as needed
- Due date tracking with human-readable formatting
- Filter insights by follow-up status or show only items with follow-ups

**Sync & Configuration:**
- Manual sync trigger with real-time progress updates via Server-Sent Events
- Rate limiting protection (2 syncs per 60 seconds)
- Settings page for in-place configuration editing
- IMAP, LLM, storage, and sync settings grouped by domain
- Configuration changes write to `.env` file with validation
- Category regeneration and database clearing maintenance tools

**UI/UX Enhancements:**
- Responsive design optimized for desktop and mobile
- Toast notifications for all operations (success, error, info)
- Loading spinners with descriptive messages during async operations
- Scroll position restoration after page navigation
- Empty states with helpful guidance
- Themed Material Icons throughout

**Caching & Performance:**
- Response caching with 5-minute TTL for dashboard data
- Cache invalidation on data modifications (sync, delete, category updates)
- Gzip compression for responses over 1KB
- Optimized SQL queries with proper indexing

The dashboard maintains consistency with the `/api/dashboard` endpoint, ensuring the UI and API share the same data layer and business logic.

## License

This project is licensed under the [Creative Commons Attribution-NonCommercial 4.0 International License](LICENSE). You are free to share and adapt the material for non-commercial purposes, provided you give appropriate credit.

