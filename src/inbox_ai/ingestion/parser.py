"""Utilities for parsing raw RFC822 messages into structured models."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime

from ..core.models import AttachmentMeta, EmailBody, EmailEnvelope


class EmailParser:
    """Convert raw email payloads into normalized envelopes."""

    def __init__(self) -> None:
        """Prepare internal parser instance."""
        self._parser = BytesParser(policy=policy.default)

    def parse(self, uid: int, payload: bytes, mailbox: str) -> EmailEnvelope:
        """Parse raw RFC822 bytes into an :class:`EmailEnvelope`."""
        message = self._parser.parsebytes(payload)
        subject = message.get("Subject")
        sent_at = _try_parse_datetime(message.get("Date"))
        message_id = message.get("Message-ID")
        thread_id = _resolve_thread_id(message)
        sender = _take_first_address(message.get("From"))
        to_recipients = tuple(_extract_addresses(message.get_all("To", [])))
        cc_recipients = tuple(_extract_addresses(message.get_all("Cc", [])))
        bcc_recipients = tuple(_extract_addresses(message.get_all("Bcc", [])))

        body_text, body_html = _extract_bodies(message)
        attachments = tuple(_collect_attachments(message))

        return EmailEnvelope(
            uid=uid,
            mailbox=mailbox,
            message_id=message_id,
            thread_id=thread_id,
            subject=subject,
            sender=sender,
            to=to_recipients,
            cc=cc_recipients,
            bcc=bcc_recipients,
            sent_at=sent_at,
            received_at=sent_at,
            body=EmailBody(text=body_text, html=body_html),
            attachments=attachments,
        )


def _extract_addresses(headers: Iterable[str]) -> Iterable[str]:
    for _, email_address in getaddresses(headers):
        if email_address:
            yield email_address


def _take_first_address(header_value: str | None) -> str | None:
    if header_value is None:
        return None
    addresses = list(_extract_addresses([header_value]))
    return addresses[0] if addresses else None


def _resolve_thread_id(message: EmailMessage) -> str | None:
    for header in (
        "Thread-Index",
        "Thread-Id",
        "In-Reply-To",
        "References",
        "Message-ID",
    ):
        value = message.get(header)
        if isinstance(value, str) and value:
            return value.split()[0]
    return None


def _collapse_chunks(chunks: Iterable[str], separator: str) -> str | None:
    filtered_chunks = [chunk for chunk in chunks if chunk]
    if not filtered_chunks:
        return None
    return separator.join(filtered_chunks)


def _extract_bodies(message: EmailMessage) -> tuple[str | None, str | None]:
    plain_chunks: list[str] = []
    html_chunks: list[str] = []

    for part in message.walk():
        if part.is_multipart():
            continue
        content_type = part.get_content_type()
        disposition = part.get_content_disposition()
        if disposition == "attachment":
            continue
        try:
            content_obj = part.get_content()
        except LookupError:
            continue
        if not isinstance(content_obj, str):
            continue
        content = content_obj.strip()
        if content_type == "text/plain":
            plain_chunks.append(content)
        elif content_type == "text/html":
            html_chunks.append(content)

    text = _collapse_chunks(plain_chunks, "\n\n")
    html = _collapse_chunks(html_chunks, "\n")
    return text, html


def _collect_attachments(message: EmailMessage) -> Iterable[AttachmentMeta]:
    for part in message.iter_attachments():
        payload = part.get_payload(decode=True) or b""
        yield AttachmentMeta(
            filename=part.get_filename(),
            content_type=part.get_content_type(),
            size=len(payload) if payload else None,
        )


def _try_parse_datetime(header_value: str | None) -> datetime | None:
    if header_value is None:
        return None
    try:
        return parsedate_to_datetime(header_value)
    except (TypeError, ValueError):
        return None


__all__ = ["EmailParser"]
