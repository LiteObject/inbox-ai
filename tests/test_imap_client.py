"""Tests for the IMAP transport adapter."""

# pylint: disable=protected-access

from __future__ import annotations

from unittest.mock import MagicMock

from inbox_ai.core.config import ImapSettings
from inbox_ai.transport import ImapClient


def test_fetch_since_returns_message_chunks() -> None:
    settings = ImapSettings(
        host="imap.test",
        port=993,
        username="user",
        app_password="password",
        mailboxes=["INBOX"],
        use_ssl=False,
    )
    client = ImapClient(settings, "INBOX")

    mock_connection = MagicMock()

    def uid(command, *args):
        if command == "SEARCH":
            return "OK", [b"101 102"]
        if command == "FETCH":
            uid_arg = args[0]
            return "OK", [(b"", f"raw-{uid_arg}".encode())]
        raise AssertionError("Unexpected IMAP command")

    mock_connection.uid.side_effect = uid

    client._connection = mock_connection  # type: ignore[attr-defined]

    chunks = list(client.fetch_since(last_uid=None, batch_size=2))

    assert [chunk.uid for chunk in chunks] == [101, 102]
    assert chunks[0].raw == b"raw-101"
    mock_connection.uid.assert_any_call("SEARCH", None, "1:*")
    mock_connection.uid.assert_any_call("FETCH", "101", "(RFC822)")
    mock_connection.uid.assert_any_call("FETCH", "102", "(RFC822)")
