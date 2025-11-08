"""Transport adapters for external mailbox providers."""

from .imap_client import ImapClient, ImapError
from .smtp_client import EmailMessage, SmtpClient, SmtpError

__all__ = ["ImapClient", "ImapError", "SmtpClient", "SmtpError", "EmailMessage"]
