"""Optimized mail fetching with batched LLM analysis and caching."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import UTC, datetime
from typing import Callable

from ..core.config import FollowUpSettings
from ..core.interfaces import EmailRepository, MailboxProvider
from ..core.models import (
    DraftRecord,
    EmailEnvelope,
    EmailInsight,
    FetchReport,
    SyncCheckpoint,
    EmailCategory,
    FollowUpTask as CoreFollowUpTask,
)
from ..intelligence import EmailAnalysis, get_default_categories
from ..intelligence.email_analysis_service import OptimizedEmailAnalyzer, LLMMetrics
from .fetcher import EmailParserProtocol

LOGGER = logging.getLogger(__name__)


class OptimizedMailFetcher:
    """
    Pull messages from a mailbox provider with optimized LLM analysis.

    Features:
    - Single composite LLM call per email (6 calls → 1)
    - Batch processing of multiple emails concurrently
    - Content-based caching to avoid re-analysis
    - Comprehensive metrics tracking
    """

    def __init__(
        self,
        mailbox: MailboxProvider,
        repository: EmailRepository,
        parser: EmailParserProtocol,
        analyzer: OptimizedEmailAnalyzer,
        *,
        batch_size: int = 50,
        max_messages: int | None = None,
        analysis_batch_size: int = 5,
        follow_up_settings: FollowUpSettings | None = None,
        progress_callback: Callable[[str], None] | None = None,
        user_email: str | None = None,
    ) -> None:
        """
        Initialize the optimized fetcher.

        Args:
            mailbox: IMAP mailbox provider
            repository: Email storage repository
            parser: Email parser for raw RFC822 messages
            analyzer: Optimized email analyzer with LLM
            batch_size: Number of emails to fetch per IMAP batch
            max_messages: Optional limit on total messages to process
            analysis_batch_size: Number of emails to analyze concurrently
            progress_callback: Optional callback for progress updates
            user_email: User's email address for draft personalization
        """
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if analysis_batch_size <= 0:
            raise ValueError("analysis_batch_size must be positive")

        self._mailbox = mailbox
        self._repository = repository
        self._parser = parser
        self._analyzer = analyzer
        self._batch_size = batch_size
        self._max_messages = max_messages
        self._analysis_batch_size = analysis_batch_size
        self._follow_up_settings = follow_up_settings or FollowUpSettings()
        self._progress_callback = progress_callback
        self._user_email = user_email
        self._metrics = LLMMetrics()
        self._default_categories = {
            category.key: category for category in get_default_categories()
        }

    def run(self) -> tuple[FetchReport, LLMMetrics]:
        """
        Execute a synchronization cycle and return summary with metrics.

        Returns:
            Tuple of (FetchReport with processed count, LLM metrics)
        """
        mailbox_name = self._mailbox.mailbox
        checkpoint = self._repository.get_checkpoint(mailbox_name)
        last_uid = checkpoint.last_uid if checkpoint else None
        LOGGER.info(
            "Starting optimized fetch for mailbox %s (last UID %s)",
            mailbox_name,
            last_uid,
        )

        processed = 0
        new_last_uid = last_uid
        pending_envelopes: list[EmailEnvelope] = []

        for chunk in self._mailbox.fetch_since(last_uid, self._batch_size):
            envelope = self._parser.parse(chunk.uid, chunk.raw, mailbox_name)
            self._repository.persist_email(envelope)

            if self._progress_callback:
                self._progress_callback(
                    f"Processing message {processed + 1}: UID {envelope.uid}, "
                    f"Subject: {envelope.subject}"
                )

            pending_envelopes.append(envelope)

            # Process batch when full
            if len(pending_envelopes) >= self._analysis_batch_size:
                self._process_batch(pending_envelopes)
                pending_envelopes.clear()

            new_last_uid = chunk.uid
            self._repository.upsert_checkpoint(
                SyncCheckpoint(mailbox=mailbox_name, last_uid=new_last_uid)
            )
            processed += 1
            LOGGER.debug("Processed message UID %s", chunk.uid)

            if self._max_messages is not None and processed >= self._max_messages:
                LOGGER.info("Reached max_messages limit (%s)", self._max_messages)
                break

        # Process remaining emails in final batch
        if pending_envelopes:
            self._process_batch(pending_envelopes)

        LOGGER.info(
            "Optimized fetch completed: processed=%s new_last_uid=%s, metrics=%s",
            processed,
            new_last_uid,
            self._metrics.get_summary(),
        )
        return (
            FetchReport(processed=processed, new_last_uid=new_last_uid),
            self._metrics,
        )

    def _process_batch(self, envelopes: list[EmailEnvelope]) -> None:
        """
        Process a batch of emails with parallel LLM analysis.

        Args:
            envelopes: List of email envelopes to analyze
        """
        if not envelopes:
            return

        LOGGER.debug("Processing batch of %d emails", len(envelopes))

        # Check cache for each email
        analyses_needed: list[EmailEnvelope] = []
        cached_results: dict[int, EmailInsight] = {}

        for envelope in envelopes:
            content_hash = self._compute_content_hash(envelope)
            self._repository.update_content_hash(envelope.uid, content_hash)

            # Try to find cached analysis
            cached_analysis = self._repository.find_cached_analysis(content_hash)
            if cached_analysis:
                LOGGER.debug(
                    "Cache hit for UID %s (hash %s)", envelope.uid, content_hash[:8]
                )
                self._metrics.record_cache_hit()
                cached_results[envelope.uid] = cached_analysis
            else:
                LOGGER.debug(
                    "Cache miss for UID %s (hash %s)", envelope.uid, content_hash[:8]
                )
                self._metrics.record_cache_miss()
                analyses_needed.append(envelope)

        # Analyze uncached emails in parallel
        if analyses_needed:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                results = loop.run_until_complete(
                    self._analyzer.analyze_batch(analyses_needed)
                )
            finally:
                loop.close()

            # Store analysis results
            for envelope, analysis in zip(analyses_needed, results):
                self._store_analysis(envelope, analysis)

        # Use cached results
        for uid, cached_analysis in cached_results.items():
            envelope = next(item for item in envelopes if item.uid == uid)
            self._copy_cached_results(envelope, cached_analysis)

        analyzer_metrics = self._analyzer.get_metrics()
        self._metrics.total_calls = analyzer_metrics.total_calls
        self._metrics.total_tokens_input = analyzer_metrics.total_tokens_input
        self._metrics.total_tokens_output = analyzer_metrics.total_tokens_output

    def _store_analysis(self, envelope: EmailEnvelope, analysis: EmailAnalysis) -> None:
        """
        Store comprehensive analysis results in repository.

        Args:
            envelope: Email envelope being analyzed
            analysis: EmailAnalysis result from analyzer
        """
        generated_at = datetime.now(tz=UTC)
        insight = EmailInsight(
            email_uid=envelope.uid,
            summary=analysis.summary,
            action_items=tuple(analysis.action_items),
            priority=analysis.priority,
            provider=f"{self._analyzer.llm.provider_id}:composite",
            generated_at=generated_at,
            used_fallback=False,
        )
        self._repository.persist_insight(insight)

        categories = self._map_categories(analysis.categories)
        self._repository.replace_categories(envelope.uid, categories)

        follow_ups = tuple(
            CoreFollowUpTask(
                id=None,
                email_uid=envelope.uid,
                action=task.action,
                due_at=_parse_due_date(task.due_date),
                status="open",
                created_at=generated_at,
                completed_at=None,
            )
            for task in analysis.follow_ups
            if task.action.strip()
        )
        self._repository.replace_follow_ups(envelope.uid, follow_ups)

        if (
            not self._should_skip_draft(envelope, categories)
            and analysis.suggested_reply.strip()
        ):
            draft = DraftRecord(
                id=None,
                email_uid=envelope.uid,
                body=analysis.suggested_reply.strip(),
                provider=f"{self._analyzer.llm.provider_id}:composite",
                generated_at=generated_at,
                confidence=None,
                used_fallback=False,
            )
            self._repository.persist_draft(draft)

    def _copy_cached_results(
        self, envelope: EmailEnvelope, cached_analysis: EmailInsight
    ) -> None:
        generated_at = datetime.now(tz=UTC)
        source_uid = cached_analysis.email_uid
        self._repository.persist_insight(
            EmailInsight(
                email_uid=envelope.uid,
                summary=cached_analysis.summary,
                action_items=cached_analysis.action_items,
                priority=cached_analysis.priority,
                provider=f"{cached_analysis.provider} (cached)",
                generated_at=generated_at,
                used_fallback=cached_analysis.used_fallback,
            )
        )

        source_categories = self._repository.get_categories_for_uids([source_uid]).get(
            source_uid, ()
        )
        categories = tuple(
            EmailCategory(key=category.key, label=category.label)
            for category in source_categories
        )
        self._repository.replace_categories(envelope.uid, categories)

        source_follow_ups = self._repository.fetch_follow_ups_for_uids(
            [source_uid]
        ).get(source_uid, ())
        self._repository.replace_follow_ups(
            envelope.uid,
            tuple(
                CoreFollowUpTask(
                    id=None,
                    email_uid=envelope.uid,
                    action=task.action,
                    due_at=task.due_at,
                    status="open",
                    created_at=generated_at,
                    completed_at=None,
                )
                for task in source_follow_ups
            ),
        )

        draft = self._repository.fetch_latest_drafts([source_uid]).get(source_uid)
        if draft is not None and not self._should_skip_draft(envelope, categories):
            self._repository.persist_draft(
                DraftRecord(
                    id=None,
                    email_uid=envelope.uid,
                    body=draft.body,
                    provider=f"{draft.provider} (cached)",
                    generated_at=generated_at,
                    confidence=draft.confidence,
                    used_fallback=draft.used_fallback,
                )
            )

    def _map_categories(self, raw_categories: list[str]) -> tuple[EmailCategory, ...]:
        categories: list[EmailCategory] = []
        seen: set[str] = set()
        for raw_category in raw_categories:
            key = _normalize_category_key(raw_category)
            if not key or key in seen:
                continue
            seen.add(key)
            category = self._default_categories.get(key)
            if category is not None:
                categories.append(category)
        if not categories:
            return (EmailCategory(key="general", label="General"),)
        return tuple(categories)

    def _should_skip_draft(
        self, envelope: EmailEnvelope, categories: tuple[EmailCategory, ...]
    ) -> bool:
        excluded_categories = set(self._follow_up_settings.exclude_categories)
        skip_draft = any(category.key in excluded_categories for category in categories)
        if self._user_email is None:
            return skip_draft

        is_personal = self._user_email in envelope.to or self._user_email in envelope.cc
        if not is_personal:
            is_personal = self._user_email in envelope.bcc
        return skip_draft or not is_personal

    @staticmethod
    def _compute_content_hash(envelope: EmailEnvelope) -> str:
        """
        Compute SHA-256 hash of email content for caching.

        Args:
            envelope: Email envelope to hash

        Returns:
            Hex-encoded SHA-256 hash
        """
        content = (
            f"{envelope.subject or ''}\n"
            f"{envelope.sender or ''}\n"
            f"{envelope.body.text or envelope.body.html or ''}"
        )
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _normalize_category_key(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    if normalized == "uncategorized":
        return "general"
    return normalized


def _parse_due_date(value: str | None) -> datetime | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    try:
        parsed = datetime.fromisoformat(stripped)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(f"{stripped}T00:00:00")
        except ValueError:
            LOGGER.debug("Ignoring invalid follow-up due date from analyzer: %s", value)
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


__all__ = ["OptimizedMailFetcher"]
