"""Command-line entry point for Inbox AI."""

from __future__ import annotations

import argparse
from pathlib import Path

from inbox_ai.core import AppSettings, configure_logging, load_app_settings


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
        choices=["info"],
        help="Operation to execute.",
    )
    return parser


def execute(command: str, settings: AppSettings) -> None:
    """Execute the requested CLI command."""

    if command == "info":
        print("Inbox AI is ready. Configure IMAP and LLM settings to get started.")
        print(f"IMAP host: {settings.imap.host}")
        print(f"Database path: {settings.storage.db_path}")


def main() -> None:
    """CLI entry point."""

    parser = build_parser()
    args = parser.parse_args()

    settings = load_app_settings(env_file=args.env_file)
    configure_logging(settings.logging)
    execute(args.command, settings)


if __name__ == "__main__":
    main()
