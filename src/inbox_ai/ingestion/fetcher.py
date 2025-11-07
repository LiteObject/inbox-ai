"""Mail fetching orchestration logic."""

from __future__ import annotations

import logging
from typing import Callable, Protocol

from ..core.interfaces import (
    CategoryService,
    DraftingService,
    EmailRepository,
    FollowUpPlanner,
    InsightError,
    InsightService,
    MailboxProvider,
)
from ..core.models import EmailEnvelope, EmailInsight, FetchReport, SyncCheckpoint

LOGGER = logging.getLogger(__name__)

MailFetcherResult = FetchReport


class EmailParserProtocol(Protocol):
    """Minimal protocol implemented by email parsers."""

    def parse(self, uid: int, payload: bytes, mailbox: str) -> EmailEnvelope:
        """Convert raw RFC822 payload into an envelope."""
        raise NotImplementedError


class MailFetcher:
    """Pull messages from a mailbox provider, parse, and store them."""

    def __init__(
        self,
        mailbox: MailboxProvider,
        repository: EmailRepository,
        parser: EmailParserProtocol,
        *,
        batch_size: int = 50,
        max_messages: int | None = None,
        insight_service: InsightService | None = None,
        drafting_service: DraftingService | None = None,
        follow_up_planner: FollowUpPlanner | None = None,
        category_service: CategoryService | None = None,
        progress_callback: Callable[[str], None] | None = None,
        user_email: str | None = None,
    ) -> None:
        # pylint: disable=too-many-arguments
        """Initialise the fetcher with mailbox, storage, and parser."""
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self._mailbox = mailbox
        self._repository = repository
        self._parser = parser
        self._batch_size = batch_size
        self._max_messages = max_messages
        self._insight_service = insight_service
        self._drafting_service = drafting_service
        self._follow_up_planner = follow_up_planner
        self._category_service = category_service
        self._progress_callback = progress_callback
        self._user_email = user_email

    def run(self) -> MailFetcherResult:
        """Execute a synchronization cycle and return a summary."""
        mailbox_name = self._mailbox.mailbox
        checkpoint = self._repository.get_checkpoint(mailbox_name)
        last_uid = checkpoint.last_uid if checkpoint else None
        LOGGER.info(
            "Starting fetch for mailbox %s (last UID %s)", mailbox_name, last_uid
        )

        processed = 0
        failed = 0
        new_last_uid = last_uid

        for chunk in self._mailbox.fetch_since(last_uid, self._batch_size):
            envelope = self._parser.parse(chunk.uid, chunk.raw, mailbox_name)

            # Persist email FIRST - if this fails, skip all processing for this email
            try:
                self._repository.persist_email(envelope)
                LOGGER.debug("Successfully persisted email UID %s", envelope.uid)
            except Exception as persist_error:  # pylint: disable=broad-except
                LOGGER.error(
                    "Failed to persist email UID %s: %s",
                    envelope.uid,
                    persist_error,
                    exc_info=True,
                )
                LOGGER.info(
                    "Skipping processing for UID %s due to persistence failure",
                    envelope.uid,
                )
                failed += 1
                # Update checkpoint even for failed emails to avoid reprocessing
                self._repository.upsert_checkpoint(
                    SyncCheckpoint(mailbox=mailbox_name, last_uid=chunk.uid)
                )
                new_last_uid = chunk.uid
                continue  # Skip to next email

            if self._progress_callback:
                self._progress_callback(
                    f"Processing message {processed + 1}: UID {envelope.uid}, Subject: {envelope.subject}"
                )

            insight: EmailInsight | None = None
            if self._insight_service is not None:
                try:
                    insight = self._insight_service.generate_insight(envelope)
                    if insight is not None:
                        self._repository.persist_insight(insight)
                    else:
                        LOGGER.warning(
                            "Insight generation returned None for UID %s",
                            envelope.uid,
                        )
                except InsightError as exc:
                    LOGGER.warning(
                        "Failed to generate insight for UID %s: %s",
                        envelope.uid,
                        exc,
                    )
                    insight = None
                except Exception as exc:  # pylint: disable=broad-except
                    LOGGER.error(
                        "Unexpected error generating insight for UID %s: %s",
                        envelope.uid,
                        exc,
                        exc_info=True,
                    )
                    insight = None

            if insight is None:
                insight = self._repository.fetch_insight(envelope.uid)

            categories = ()
            if self._category_service is not None:
                try:
                    categories = tuple(
                        self._category_service.categorize(envelope, insight)
                    )
                    self._repository.replace_categories(envelope.uid, categories)
                except Exception as exc:  # pylint: disable=broad-except
                    LOGGER.warning(
                        "Failed to assign categories for UID %s: %s",
                        envelope.uid,
                        exc,
                    )

            # Regenerate insight with categories to filter spam actions
            if insight is not None and self._insight_service is not None:
                try:
                    updated_insight = self._insight_service.generate_insight(
                        envelope, categories
                    )
                    if updated_insight is not None:
                        self._repository.persist_insight(updated_insight)
                        insight = updated_insight
                    else:
                        LOGGER.warning(
                            "Updated insight generation returned None for UID %s",
                            envelope.uid,
                        )
                except InsightError as exc:
                    LOGGER.warning(
                        "Failed to update insight for UID %s: %s",
                        envelope.uid,
                        exc,
                    )
                except Exception as exc:  # pylint: disable=broad-except
                    LOGGER.error(
                        "Unexpected error updating insight for UID %s: %s",
                        envelope.uid,
                        exc,
                        exc_info=True,
                    )

            # Check if draft should be skipped
            excluded_categories = {"marketing", "notification", "spam"}
            is_personal = False
            if self._user_email:
                is_personal = (
                    self._user_email in envelope.to or self._user_email in envelope.cc
                )
                if not is_personal:
                    is_personal = self._user_email in envelope.bcc
            skip_draft = any(cat.key in excluded_categories for cat in categories)
            if self._user_email is not None:
                skip_draft = skip_draft or not is_personal

            if (
                self._drafting_service is not None
                and insight is not None
                and not skip_draft
            ):
                try:
                    draft = self._drafting_service.generate_draft(envelope, insight)
                    if draft is not None:
                        self._repository.persist_draft(draft)
                    else:
                        LOGGER.warning(
                            "Draft generation returned None for UID %s",
                            envelope.uid,
                        )
                except Exception as exc:  # pylint: disable=broad-except
                    LOGGER.error(
                        "Failed to generate draft for UID %s: %s",
                        envelope.uid,
                        exc,
                        exc_info=True,
                    )

            if self._follow_up_planner is not None and insight is not None:
                # Skip follow-ups for spam emails
                excluded_categories = {"marketing", "notification", "spam"}
                skip_follow_ups = any(
                    cat.key in excluded_categories for cat in categories
                )

                if not skip_follow_ups:
                    try:
                        tasks = self._follow_up_planner.plan_follow_ups(
                            envelope, insight
                        )
                        if tasks is not None:
                            self._repository.replace_follow_ups(envelope.uid, tasks)
                        else:
                            LOGGER.warning(
                                "Follow-up planning returned None for UID %s",
                                envelope.uid,
                            )
                    except Exception as exc:  # pylint: disable=broad-except
                        LOGGER.error(
                            "Failed to derive follow-ups for UID %s: %s",
                            envelope.uid,
                            exc,
                            exc_info=True,
                        )

            new_last_uid = chunk.uid
            self._repository.upsert_checkpoint(
                SyncCheckpoint(mailbox=mailbox_name, last_uid=new_last_uid)
            )
            processed += 1
            LOGGER.debug("Processed message UID %s", chunk.uid)
            if self._max_messages is not None and processed >= self._max_messages:
                LOGGER.info("Reached max_messages limit (%s)", self._max_messages)
                break

        LOGGER.info(
            "Fetch completed: processed=%s, failed=%s, new_last_uid=%s",
            processed,
            failed,
            new_last_uid,
        )
        return MailFetcherResult(processed=processed, new_last_uid=new_last_uid)


__all__ = ["EmailParserProtocol", "MailFetcher", "MailFetcherResult"]
