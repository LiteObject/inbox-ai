# AI Features — Improvement Plan

> **Date:** 2026-03-27
> **Branch:** `feature/implement-oauth2`
> **Status:** Draft

---

## Current State

The `intelligence/` package provides six AI capabilities backed by Ollama
(local LLM) with deterministic fallbacks:

| Service | File | LLM? | Fallback? |
|---------|------|------|-----------|
| Summarization | `summarizer.py` | Yes | Heuristic (first lines + keywords) |
| Draft replies | `drafter.py` | Yes | Template with placeholders |
| Priority scoring | `priority.py` | No | Keyword + sender heuristics only |
| Categorization | `category.py` | Optional | Keyword rule matching |
| Follow-up planning | `follow_up.py` | No | Keyword date parsing |
| Composite analysis | `email_analysis_service.py` | Yes | Generic fallback |

During sync, emails flow through individual services sequentially:
`summarizer → categorizer → drafter → follow_up planner`, each making its own
LLM call. The composite `OptimizedEmailAnalyzer` exists but is not wired into
any code path.

---

## Improvements

### 1. Wire User Preferences Into Prompts

**Problem:** `INBOX_AI_USER__PREFERENCES` is stored in settings and exposed in
the UI, but no prompt in `prompts.py` includes it. The user writes guidance like
"flag security alerts as urgent; ignore Facebook notifications" and the LLM
never sees it.

**Impact:** High · **Effort:** Low

**Plan:**

1. Add a `user_preferences: str` parameter to `build_insight_prompt()` and
   `build_draft_prompt()` in `prompts.py`.
2. Inject the text as a `User context:` block between the system instructions
   and the email body.
3. Pass `settings.user.preferences` from `SummarizationService` and
   `DraftingService` (thread it through their constructors or method args).
4. Guard with `if user_preferences.strip():` so the prompt stays clean when
   empty.

**Files to change:**

- `src/inbox_ai/intelligence/prompts.py`
- `src/inbox_ai/intelligence/summarizer.py`
- `src/inbox_ai/intelligence/drafter.py`
- `src/inbox_ai/web/app.py` (pass preferences when constructing services)

---

### 2. LLM-Assisted Priority Scoring

**Problem:** `priority.py` uses a small static keyword/sender dictionary. The
LLM summary is scanned for literal words like "urgent" or "asap", but nuanced
urgency (e.g., a polite but deadline-critical request) scores low.

**Impact:** High · **Effort:** Low

**Plan:**

1. Extend the insight prompt JSON schema in `build_insight_prompt()` to include
   a `"priority"` field (integer 0–10) with guidance on the scale.
2. Parse the returned priority in `_parse_llm_output()`.
3. In `SummarizationService.generate_insight()`, prefer the LLM-returned
   priority when available; fall back to the heuristic `score_priority()` when
   the LLM omits it or when running in deterministic mode.

**Files to change:**

- `src/inbox_ai/intelligence/prompts.py`
- `src/inbox_ai/intelligence/summarizer.py`

---

### 3. Adopt the Composite Analyzer in the Sync Pipeline

**Problem:** `OptimizedEmailAnalyzer` in `email_analysis_service.py` performs
summary + priority + categories + action items + follow-ups + draft in a single
LLM call. It already has caching, batch async, and metrics. But nothing calls
it — the sync pipeline still makes multiple sequential LLM requests per email.

**Impact:** High · **Effort:** Medium

**Plan:**

1. **Fix the signature mismatch first** (see item 10) — `OllamaClient.generate()`
   only accepts `prompt: str`, but the analyzer calls it with `temperature` and
   `max_tokens` kwargs. This would raise `TypeError` at runtime.
2. Refactor `_run_sync_cycle()` in `app.py` to optionally use
   `OptimizedEmailAnalyzer` as the primary path.
3. Map the composite `EmailAnalysis` result back into the existing data models
   (`EmailInsight`, `DraftRecord`, `FollowUpTask`, `EmailCategory`) so
   downstream storage and UI remain unchanged.
4. Keep the individual-service path as a fallback or behind a feature flag.
5. Add integration tests comparing composite vs sequential output shapes.

**Files to change:**

- `src/inbox_ai/intelligence/llm.py` (extend `generate()` signature)
- `src/inbox_ai/intelligence/email_analysis_service.py` (use client correctly)
- `src/inbox_ai/web/app.py` (`_run_sync_cycle`)

---

### 4. Thread-Aware Prompts

**Problem:** Each email is analyzed in isolation. For threaded conversations
(`thread_id` is stored on `EmailEnvelope`) the summary may repeat information
and the draft reply misses the conversation arc.

**Impact:** Medium · **Effort:** Medium

**Plan:**

1. When generating an insight for an email with a `thread_id`, query the
   repository for prior emails in the same thread.
2. Include their subjects and summaries (not full bodies — to stay within token
   limits) in the prompt as a `Conversation history:` section.
3. Instruct the LLM: "This email is part of a thread. Summarize only new
   information."
4. Apply the same context when drafting replies so the LLM can maintain
   conversational continuity.

**Files to change:**

- `src/inbox_ai/intelligence/prompts.py`
- `src/inbox_ai/intelligence/summarizer.py`
- `src/inbox_ai/intelligence/drafter.py`
- `src/inbox_ai/storage/sqlite.py` (add `list_thread_emails(thread_id)` query)

---

### 5. Configurable Reply Tone

**Problem:** The draft prompt hard-codes "concise, polite". There is no way for
users to request a formal, casual, brief, or detailed tone.

**Impact:** Medium · **Effort:** Low

**Plan:**

1. Add a `reply_tone` field to `UserSettings` (or reuse the free-form
   `preferences` field and parse for tone keywords).
2. Inject a `Tone: {tone}` line into `build_draft_prompt()`.
3. Update the settings UI to expose a tone selector (dropdown with predefined
   options: Professional, Casual, Concise, Detailed).

**Files to change:**

- `src/inbox_ai/core/config.py`
- `src/inbox_ai/intelligence/prompts.py`
- `src/inbox_ai/intelligence/drafter.py`
- `src/inbox_ai/web/app.py` (config section + settings page)

---

### 6. Quality Feedback Loop

**Problem:** The LLM returns a `confidence` field for drafts, but users cannot
rate or reject AI outputs. There is no mechanism to track quality over time or
adjust behavior based on feedback.

**Impact:** Low · **Effort:** Medium

**Plan:**

1. Add `user_rating` and `user_edited` columns to the drafts table.
2. Track when a user manually edits a draft (compare saved body to generated
   body) and when they send vs delete it.
3. Expose a simple thumbs-up/thumbs-down UI on summaries and drafts.
4. Surface aggregate quality metrics on the settings page.
5. Long-term: use low-rated outputs to refine prompts or adjust
   `fallback_enabled` thresholds automatically.

**Files to change:**

- `src/inbox_ai/storage/schema/` (new migration)
- `src/inbox_ai/storage/sqlite.py`
- `src/inbox_ai/core/models.py`
- `src/inbox_ai/web/app.py`
- `src/inbox_ai/web/templates/` (UI elements)

---

### 7. Better HTML-to-Text Conversion

**Problem:** `summarizer.py` strips HTML by removing characters between `<` and
`>` one-by-one, losing structural cues (headings, lists, link text). This
degrades LLM comprehension for HTML-only emails.

**Impact:** Medium · **Effort:** Low

**Plan:**

1. Replace the manual `_strip_html()` with `html2text` (already a common
   lightweight dependency) or at minimum Python's `html.parser.HTMLParser`.
2. Preserve list items as bullet points, headings as bold lines, and link text
   with URLs.
3. Add unit tests comparing old vs new output for sample HTML emails.

**Files to change:**

- `src/inbox_ai/intelligence/summarizer.py`
- `pyproject.toml` (add `html2text` dependency if chosen)
- `tests/` (new test cases)

---

### 8. Smarter Follow-Up Due Dates

**Problem:** `follow_up.py` matches literal strings ("today", "tomorrow",
"next week"). It misses relative dates like "by Friday", "end of Q2", or
"within 48 hours".

**Impact:** Low · **Effort:** Medium

**Plan:**

**Option A — Date-parsing library:**

1. Add `dateparser` as an optional dependency.
2. Attempt to parse the action text for a date before falling back to the
   keyword heuristic.

**Option B — LLM-returned dates:**

1. Adopt `OptimizedEmailAnalyzer` (item 3), which already asks the LLM for
   `due_date` in ISO format on each follow-up.
2. Parse the returned dates and use them directly.

**Files to change:**

- `src/inbox_ai/intelligence/follow_up.py`
- `pyproject.toml` (if adding `dateparser`)

---

### 9. LLM Error Handling — Fail Fast + Circuit Breaker

**Problem:** `llm.py` retries 3 times with backoff but treats all HTTP errors
identically. A 401 or 404 wastes time retrying. There is no circuit breaker to
stop hammering a dead Ollama server during batch sync.

**Impact:** Medium · **Effort:** Low

**Plan:**

1. In `OllamaClient.generate()`, check the HTTP status code: fail immediately
   on 4xx (non-retryable) errors; only retry on 5xx and connection errors.
2. Add a simple circuit breaker: after N consecutive failures (e.g., 3), switch
   the client into "open" state and return a sentinel or raise immediately for
   the remainder of the sync batch.
3. Reset the circuit breaker at the start of each sync cycle.

**Files to change:**

- `src/inbox_ai/intelligence/llm.py`

---

### 10. Fix `OllamaClient.generate()` Signature Mismatch

**Problem:** `OptimizedEmailAnalyzer` calls
`self.llm.generate(prompt=..., temperature=0.3, max_tokens=1500)`, but
`OllamaClient.generate()` only accepts `prompt: str`. This is a runtime
`TypeError` proving the composite analyzer has never been exercised.

**Impact:** High (blocks item 3) · **Effort:** Low

**Plan:**

1. Extend `OllamaClient.generate()` to accept optional `temperature: float |
   None = None` and `max_tokens: int | None = None` kwargs.
2. When provided, override the instance-level settings for that single call.
3. Update the `LLMClient` protocol to match.
4. Add a unit test confirming the extended signature works.

**Files to change:**

- `src/inbox_ai/intelligence/llm.py`
- `tests/` (new or updated test)

---

## Implementation Order

```
Phase 1 — Quick wins (Low effort, High/Medium impact)
  ├── #1  Wire user preferences into prompts
  ├── #2  LLM-assisted priority scoring
  ├── #10 Fix OllamaClient.generate() signature
  └── #9  Fail-fast + circuit breaker

Phase 2 — Core uplift (Medium effort, High impact)
  ├── #3  Adopt composite analyzer in sync pipeline
  ├── #7  Better HTML-to-text conversion
  └── #5  Configurable reply tone

Phase 3 — Advanced features (Medium effort)
  ├── #4  Thread-aware prompts
  ├── #8  Smarter follow-up due dates
  └── #6  Quality feedback loop
```

---

## Testing Strategy

- Each improvement gets unit tests for the changed functions.
- Items touching prompts (#1, #2, #4, #5) should include snapshot tests of the
  generated prompt text to catch regressions.
- Item #3 (composite analyzer) needs an integration test that mocks the LLM
  response and verifies all six outputs are correctly mapped to existing models.
- Item #9 (circuit breaker) needs tests for the state transitions: closed →
  open → half-open → closed.
