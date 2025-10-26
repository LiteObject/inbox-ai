"""Command-line entry point for Inbox AI."""

from __future__ import annotations

import argparse
from pathlib import Path

from inbox_ai.core import AppSettings, configure_logging, load_app_settings
from inbox_ai.ingestion import EmailParser, MailFetcher
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
        choices=["info", "sync"],
        help="Operation to execute.",
    )
    return parser


def execute(command: str, settings: AppSettings) -> None:
    """Execute the requested CLI command."""
    if command == "info":
        print("Inbox AI is ready. Configure IMAP and LLM settings to get started.")
        print(f"IMAP host: {settings.imap.host}")
        print(f"Database path: {settings.storage.db_path}")
    elif command == "sync":
        _run_sync(settings)


def main() -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()

    settings = load_app_settings(env_file=args.env_file)
    configure_logging(settings.logging)
    execute(args.command, settings)


def _run_sync(settings: AppSettings) -> None:
    """Run a synchronization cycle and report the outcome."""
    email_parser = EmailParser()
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
            )
            result = fetcher.run()
    except ImapError as exc:
        print(f"Sync failed: {exc}")
        return

    processed = result.processed
    last_uid = result.new_last_uid
    print(f"Processed {processed} message(s). Last UID stored: {last_uid}")


if __name__ == "__main__":
    main()
