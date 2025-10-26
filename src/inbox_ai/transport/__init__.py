"""Transport adapters for external mailbox providers."""

from .imap_client import ImapClient, ImapError

__all__ = ["ImapClient", "ImapError"]
