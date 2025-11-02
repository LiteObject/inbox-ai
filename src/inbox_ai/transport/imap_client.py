"""IMAP transport adapter providing mailbox access."""

from __future__ import annotations

import imaplib
import logging
from collections.abc import Iterable, Iterator
from types import TracebackType

from ..core.config import ImapSettings
from ..core.interfaces import MailboxProvider
from ..core.models import MessageChunk

LOGGER = logging.getLogger(__name__)


class ImapError(RuntimeError):
    """Wrap low level IMAP errors with additional context."""


class ImapClient(MailboxProvider):
    """Thin wrapper around ``imaplib`` offering typed fetch helpers."""

    def __init__(self, settings: ImapSettings, mailbox: str) -> None:
        """Initialise the client with configuration settings and mailbox."""
        self._settings = settings
        self._connection: imaplib.IMAP4 | imaplib.IMAP4_SSL | None = None
        self.mailbox = mailbox

    # Context manager helpers -------------------------------------------------
    def __enter__(self) -> ImapClient:
        """Connect on entering a context manager scope."""
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Ensure resources are released on context exit."""
        self.close()

    # Public API ---------------------------------------------------------------
    def connect(self) -> None:
        """Establish IMAP connection and select the configured mailbox."""
        if self._connection is not None:
            return

        try:
            if self._settings.use_ssl:
                LOGGER.debug(
                    "Connecting to IMAP host %s:%s via SSL",
                    self._settings.host,
                    self._settings.port,
                )
                connection: imaplib.IMAP4 | imaplib.IMAP4_SSL = imaplib.IMAP4_SSL(
                    self._settings.host, self._settings.port
                )
            else:
                LOGGER.debug(
                    "Connecting to IMAP host %s:%s without SSL",
                    self._settings.host,
                    self._settings.port,
                )
                connection = imaplib.IMAP4(self._settings.host, self._settings.port)

            username = self._settings.username
            password = self._settings.app_password
            if username is None or password is None:
                raise ImapError("IMAP credentials are not configured")

            LOGGER.debug("Authenticating as %s", username)
            connection.login(username, password)
            status, _ = connection.select(self.mailbox)
            if status != "OK":
                raise ImapError(f"Unable to select mailbox '{self.mailbox}'")
            self._connection = connection
        except imaplib.IMAP4.error as exc:  # pragma: no cover - network dependent
            raise ImapError("Failed to connect to IMAP server") from exc

    def fetch_since(
        self, last_uid: int | None, batch_size: int
    ) -> Iterable[MessageChunk]:
        """Yield messages whose UID exceeds ``last_uid`` in ascending order."""
        connection = self._require_connection()
        start_uid = 1 if last_uid is None else last_uid + 1
        LOGGER.debug("Searching for messages from UID %s", start_uid)
        status, data = connection.uid("SEARCH", None, f"{start_uid}:*")  # type: ignore[arg-type]
        if status != "OK":
            raise ImapError("Failed to search for message UIDs")

        raw_ids = data[0].split() if data and data[0] else []
        if not raw_ids:
            LOGGER.debug("No new messages found")
            return []

        def generator() -> Iterator[MessageChunk]:
            for chunk in _chunked(raw_ids, batch_size):
                for uid_bytes in chunk:
                    uid_str = uid_bytes.decode()
                    LOGGER.debug("Fetching RFC822 payload for UID %s", uid_str)
                    status_fetch, fetch_data = connection.uid(
                        "FETCH", uid_str, "(RFC822)"
                    )
                    if status_fetch != "OK":
                        raise ImapError(f"Failed to fetch message UID {uid_str}")
                    payload = _extract_rfc822(fetch_data)
                    if payload is None:
                        LOGGER.warning("No RFC822 payload returned for UID %s", uid_str)
                        continue
                    yield MessageChunk(uid=int(uid_str), raw=payload)

        return generator()

    def delete(self, uid: int) -> None:
        """Delete a message by UID and expunge it from the mailbox."""
        connection = self._require_connection()
        uid_str = str(uid)
        LOGGER.debug("Marking UID %s for deletion", uid_str)
        try:
            status, _ = connection.uid(
                "STORE",
                uid_str,
                "+FLAGS.SILENT",
                r"(\Deleted)",
            )
            if status != "OK":
                raise ImapError(f"Failed to mark message UID {uid_str} for deletion")
            LOGGER.debug("Expunging deleted messages")
            status_expunge, _ = connection.expunge()
            if status_expunge != "OK":
                raise ImapError(f"Failed to expunge message UID {uid_str}")
        except imaplib.IMAP4.error as exc:  # pragma: no cover - network dependent
            raise ImapError(f"IMAP error while deleting UID {uid_str}") from exc

    def move_to_trash(self, uid: int, trash_folder: str) -> None:
        """Move a message to the trash folder by UID using the MOVE command."""
        connection = self._require_connection()
        uid_str = str(uid)
        LOGGER.debug("Moving UID %s to trash folder '%s'", uid_str, trash_folder)
        try:
            # The MOVE command is an IMAP extension supported by Gmail.
            status, _ = connection.uid("MOVE", uid_str, f'"{trash_folder}"')
            if status != "OK":
                raise ImapError(f"Failed to move message UID {uid_str} to trash")
        except imaplib.IMAP4.error as exc:
            raise ImapError(f"IMAP error while moving UID {uid_str} to trash") from exc

    def close(self) -> None:
        """Terminate the IMAP session cleanly."""
        if self._connection is None:
            return
        try:
            LOGGER.debug("Closing IMAP connection")
            self._connection.close()
        except imaplib.IMAP4.error:  # pragma: no cover - depends on server state
            LOGGER.debug("IMAP close raised; continuing with logout")
        finally:
            try:
                self._connection.logout()
            except imaplib.IMAP4.error:  # pragma: no cover
                LOGGER.debug("IMAP logout raised; suppressing during shutdown")
            self._connection = None

    # Internal helpers ---------------------------------------------------------
    def _require_connection(self) -> imaplib.IMAP4 | imaplib.IMAP4_SSL:
        if self._connection is None:
            raise ImapError("IMAP connection has not been established")
        return self._connection


def _chunked(items: Iterable[bytes], size: int) -> Iterator[list[bytes]]:
    """Yield successive lists of ``size`` elements."""
    bucket: list[bytes] = []
    for item in items:
        bucket.append(item)
        if len(bucket) >= size:
            yield bucket
            bucket = []
    if bucket:
        yield bucket


def _extract_rfc822(fetch_data: list[tuple[bytes, bytes] | bytes]) -> bytes | None:
    """Extract RFC822 payload from ``imaplib`` response chunks."""
    for entry in fetch_data:
        if isinstance(entry, tuple) and len(entry) == 2:
            return entry[1]
    return None


__all__ = [
    "ImapClient",
    "ImapError",
]
