"""Command-line entry point for Inbox AI."""

from __future__ import annotations

import argparse
from pathlib import Path

from inbox_ai.core import AppSettings, configure_logging, load_app_settings
from inbox_ai.core.models import FollowUpTask
from inbox_ai.ingestion import EmailParser, MailFetcher
from inbox_ai.intelligence import (
    DraftingService,
    FollowUpPlannerService,
    KeywordCategoryService,
    OllamaClient,
    SummarizationService,
)
from inbox_ai.storage import SqliteEmailRepository
from inbox_ai.transport import ImapClient, ImapError


def build_parser() -> argparse.ArgumentParser:
    """Create and configure the CLI argument parser."""
    parser = argparse.ArgumentParser(description="Inbox AI local assistant")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Path to a .env file containing configuration overrides.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="info",
        choices=["info", "sync", "follow-ups"],
        help="Operation to execute.",
    )
    parser.add_argument(
        "--follow-status",
        dest="follow_status",
        choices=["open", "done", "all"],
        default="open",
        help="Status filter for the follow-ups command (default: open).",
    )
    parser.add_argument(
        "--follow-limit",
        dest="follow_limit",
        type=int,
        default=20,
        help="Limit for follow-ups listing; set to 0 for no limit (default: 20).",
    )
    parser.add_argument(
        "--complete-follow-up",
        dest="complete_follow_up",
        type=int,
        default=None,
        help="Mark a follow-up task as done before listing results.",
    )
    parser.add_argument(
        "--reopen-follow-up",
        dest="reopen_follow_up",
        type=int,
        default=None,
        help="Reopen a follow-up task before listing results.",
    )
    return parser


def execute(args: argparse.Namespace, settings: AppSettings) -> None:
    """Execute the requested CLI command."""
    command = args.command
    if command == "info":
        print("Inbox AI is ready. Configure IMAP and LLM settings to get started.")
        print(f"IMAP host: {settings.imap.host}")
        print(f"Database path: {settings.storage.db_path}")
    elif command == "sync":
        _run_sync(settings)
    elif command == "follow-ups":
        _run_follow_ups(
            settings,
            status=args.follow_status,
            limit=args.follow_limit,
            complete_id=args.complete_follow_up,
            reopen_id=args.reopen_follow_up,
        )


def main() -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()

    settings = load_app_settings(env_file=args.env_file)
    configure_logging(settings.logging)
    execute(args, settings)


def _run_sync(settings: AppSettings) -> None:
    """Run a synchronization cycle and report the outcome."""
    email_parser = EmailParser()
    llm_client = (
        OllamaClient(settings.llm)
        if settings.llm.base_url and settings.llm.model
        else None
    )
    drafting_service = DraftingService(
        llm_client,
        fallback_enabled=settings.llm.fallback_enabled,
    )
    follow_up_planner = FollowUpPlannerService(settings.follow_up)
    insight_service = SummarizationService(
        llm_client,
        fallback_enabled=settings.llm.fallback_enabled,
    )
    category_service = KeywordCategoryService()
    try:
        with (
            ImapClient(settings.imap) as mailbox,
            SqliteEmailRepository(settings.storage) as repository,
        ):
            fetcher = MailFetcher(
                mailbox=mailbox,
                repository=repository,
                parser=email_parser,
                batch_size=settings.sync.batch_size,
                max_messages=settings.sync.max_messages,
                insight_service=insight_service,
                drafting_service=drafting_service,
                follow_up_planner=follow_up_planner,
                category_service=category_service,
            )
            result = fetcher.run()
    except ImapError as exc:
        print(f"Sync failed: {exc}")
        return

    processed = result.processed
    last_uid = result.new_last_uid
    print(f"Processed {processed} message(s). Last UID stored: {last_uid}")


def _run_follow_ups(
    settings: AppSettings,
    *,
    status: str,
    limit: int,
    complete_id: int | None,
    reopen_id: int | None,
) -> None:
    """List and optionally update follow-up tasks from storage."""
    limit_value = None if limit is not None and limit <= 0 else limit
    status_filter = None if status == "all" else status

    with SqliteEmailRepository(settings.storage) as repository:
        if complete_id is not None:
            repository.update_follow_up_status(complete_id, "done")
            print(f"Marked follow-up {complete_id} as done.")
        if reopen_id is not None:
            repository.update_follow_up_status(reopen_id, "open")
            print(f"Reopened follow-up {reopen_id}.")

        tasks = repository.list_follow_ups(status=status_filter, limit=limit_value)
        annotated: list[tuple[FollowUpTask, str]] = []
        for task in tasks:
            envelope = repository.fetch_email(task.email_uid)
            subject = (envelope.subject if envelope else None) or "(no subject)"
            annotated.append((task, subject))

    if not annotated:
        print("No follow-up tasks found.")
        return

    print(f"Showing {len(annotated)} follow-up task(s):")
    header = f"{'ID':>4}  {'Status':<6}  {'Due':<20}  {'Email UID':>8}  Subject"
    print(header)
    print("-" * len(header))
    for task, subject in annotated:
        task_id = task.id if task.id is not None else "-"
        due_text = "-"
        if task.due_at is not None:
            try:
                due_text = task.due_at.isoformat(timespec="minutes")
            except TypeError:
                due_text = task.due_at.isoformat()
        print(
            f"{str(task_id):>4}  {task.status:<6}  {due_text:<20}  {task.email_uid:>8}  {subject}"
        )


if __name__ == "__main__":
    main()
