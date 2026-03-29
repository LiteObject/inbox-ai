"""Tests for the IMAP transport adapter."""

# pylint: disable=protected-access

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from inbox_ai.core.config import ImapSettings
from inbox_ai.transport import ImapClient
from inbox_ai.transport.imap_client import ImapError


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


def _make_client() -> tuple[ImapClient, MagicMock]:
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
    client._connection = mock_connection
    return client, mock_connection


def test_uid_exists_returns_true_when_found() -> None:
    client, conn = _make_client()
    conn.uid.return_value = ("OK", [b"42"])
    assert client.uid_exists(42) is True


def test_uid_exists_returns_false_when_not_found() -> None:
    client, conn = _make_client()
    conn.uid.return_value = ("OK", [b""])
    assert client.uid_exists(42) is False


def test_uid_exists_returns_false_on_error() -> None:
    client, conn = _make_client()
    conn.uid.return_value = ("NO", [b""])
    assert client.uid_exists(42) is False


def test_move_to_trash_succeeds_when_uid_gone() -> None:
    client, conn = _make_client()

    def uid_side_effect(command, *args):
        if command == "MOVE":
            return ("OK", [None])
        if command == "SEARCH":
            return ("OK", [b""])  # UID is gone
        raise AssertionError(f"Unexpected command: {command}")

    conn.uid.side_effect = uid_side_effect

    # Should not raise
    client.move_to_trash(42, "[Gmail]/Trash")


def test_move_to_trash_raises_when_uid_still_present() -> None:
    client, conn = _make_client()

    def uid_side_effect(command, *args):
        if command == "MOVE":
            return ("OK", [None])
        if command == "SEARCH":
            return ("OK", [b"42"])  # UID still there
        raise AssertionError(f"Unexpected command: {command}")

    conn.uid.side_effect = uid_side_effect

    with pytest.raises(ImapError, match="still present"):
        client.move_to_trash(42, "[Gmail]/Trash")
