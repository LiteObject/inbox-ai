"""SMTP client for sending emails with proper error handling and security."""

from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from inbox_ai.core import SmtpSettings

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EmailMessage:
    """Outgoing email message representation.

    Attributes:
        to: Recipient email address
        subject: Email subject line
        body: Email body content
        in_reply_to: Message-ID of the original email (for threading)
        references: Space-separated Message-IDs for thread context
        html: Whether body contains HTML content
    """

    to: str
    subject: str
    body: str
    in_reply_to: str | None = None
    references: str | None = None
    html: bool = False


class SmtpError(Exception):
    """Base exception for SMTP operations.

    Raised when SMTP connection, authentication, or sending fails.
    """


class SmtpClient:
    """SMTP client for sending emails.

    Provides context manager interface for automatic connection management.
    Supports both TLS (STARTTLS) and SSL connections.

    Example:
        >>> settings = SmtpSettings(host="smtp.gmail.com", ...)
        >>> with SmtpClient(settings) as client:
        ...     message = EmailMessage(to="user@example.com", ...)
        ...     client.send(message)
    """

    def __init__(self, settings: SmtpSettings) -> None:
        """Initialize SMTP client with configuration.

        Args:
            settings: SMTP configuration settings
        """
        self._settings = settings
        self._connection: smtplib.SMTP | None = None

    def __enter__(self) -> SmtpClient:
        """Enter context manager, establishing connection."""
        self.connect()
        return self

    def __exit__(self, *args: object) -> None:
        """Exit context manager, closing connection."""
        self.disconnect()

    def connect(self) -> None:
        """Establish SMTP connection and authenticate.

        Raises:
            SmtpError: If connection or authentication fails
        """
        if not self._settings.host:
            raise SmtpError("SMTP host not configured")

        try:
            # Create connection based on TLS/SSL preference
            if self._settings.use_tls:
                LOGGER.debug(
                    "Connecting to SMTP server %s:%d with STARTTLS",
                    self._settings.host,
                    self._settings.port,
                )
                self._connection = smtplib.SMTP(
                    self._settings.host,
                    self._settings.port,
                    timeout=30,
                )
                self._connection.starttls()
            else:
                LOGGER.debug(
                    "Connecting to SMTP server %s:%d with SSL",
                    self._settings.host,
                    self._settings.port,
                )
                self._connection = smtplib.SMTP_SSL(
                    self._settings.host,
                    self._settings.port,
                    timeout=30,
                )

            # Authenticate if credentials provided
            if self._settings.username and self._settings.password:
                LOGGER.debug("Authenticating as %s", self._settings.username)
                self._connection.login(
                    self._settings.username,
                    self._settings.password,
                )

            LOGGER.info(
                "Successfully connected to SMTP server: %s", self._settings.host
            )

        except smtplib.SMTPAuthenticationError as exc:
            msg = f"SMTP authentication failed: {exc}"
            LOGGER.error(msg)
            raise SmtpError(msg) from exc
        except smtplib.SMTPException as exc:
            msg = f"SMTP connection error: {exc}"
            LOGGER.error(msg)
            raise SmtpError(msg) from exc
        except OSError as exc:
            msg = f"Network error connecting to SMTP server: {exc}"
            LOGGER.error(msg)
            raise SmtpError(msg) from exc

    def disconnect(self) -> None:
        """Close SMTP connection gracefully."""
        if self._connection:
            try:
                self._connection.quit()
                LOGGER.debug("Disconnected from SMTP server")
            except smtplib.SMTPException:
                # Connection already closed or error occurred
                pass
            finally:
                self._connection = None

    def send(self, message: EmailMessage) -> None:
        """Send an email message.

        Args:
            message: The email message to send

        Raises:
            SmtpError: If sending fails or not connected
        """
        if not self._connection:
            raise SmtpError("Not connected to SMTP server")

        try:
            mime_message = self._build_mime_message(message)
            self._connection.send_message(mime_message)
            LOGGER.info(
                "Sent email to %s: %s (reply: %s)",
                message.to,
                message.subject,
                bool(message.in_reply_to),
            )

        except smtplib.SMTPRecipientsRefused as exc:
            msg = f"Recipient rejected: {message.to}"
            LOGGER.error(msg)
            raise SmtpError(msg) from exc
        except smtplib.SMTPSenderRefused as exc:
            msg = f"Sender rejected: {self._settings.username}"
            LOGGER.error(msg)
            raise SmtpError(msg) from exc
        except smtplib.SMTPDataError as exc:
            msg = f"SMTP data error: {exc}"
            LOGGER.error(msg)
            raise SmtpError(msg) from exc
        except smtplib.SMTPException as exc:
            msg = f"Failed to send email: {exc}"
            LOGGER.error(msg)
            raise SmtpError(msg) from exc

    def _build_mime_message(self, message: EmailMessage) -> MIMEMultipart:
        """Build MIME message from EmailMessage.

        Args:
            message: Source email message

        Returns:
            MIME multipart message ready to send
        """
        mime_msg = MIMEMultipart("alternative")

        # From header with optional display name
        from_address = self._settings.username or ""
        if self._settings.from_name:
            from_address = f"{self._settings.from_name} <{self._settings.username}>"

        mime_msg["From"] = from_address
        mime_msg["To"] = message.to
        mime_msg["Subject"] = message.subject

        # Thread headers for proper email threading
        if message.in_reply_to:
            mime_msg["In-Reply-To"] = message.in_reply_to
        if message.references:
            mime_msg["References"] = message.references

        # Body content
        if message.html:
            mime_msg.attach(MIMEText(message.body, "html", "utf-8"))
        else:
            mime_msg.attach(MIMEText(message.body, "plain", "utf-8"))

        return mime_msg


__all__ = ["SmtpClient", "SmtpError", "EmailMessage"]
