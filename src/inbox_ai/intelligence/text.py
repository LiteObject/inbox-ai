"""Utilities for turning email content into readable plain text."""

from __future__ import annotations

from html.parser import HTMLParser

from inbox_ai.core.models import EmailBody

_BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "div",
    "dl",
    "dt",
    "dd",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "ul",
}
_SKIP_TAGS = {"script", "style"}


class _EmailHTMLToTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._current_link_href: str | None = None
        self._current_link_text: list[str] | None = None
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if lowered == "br":
            self._chunks.append("\n")
            return
        if lowered in _BLOCK_TAGS:
            self._chunks.append("\n")
        if lowered == "li":
            self._chunks.append("- ")
        if lowered == "a":
            self._current_link_text = []
            self._current_link_href = next(
                (value for key, value in attrs if key.lower() == "href" and value),
                None,
            )

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if lowered == "a":
            link_text = "".join(self._current_link_text or [])
            normalized_text = " ".join(link_text.split())
            href = self._current_link_href
            if normalized_text:
                self._chunks.append(normalized_text)
                if href and href not in normalized_text:
                    self._chunks.append(f" ({href})")
            elif href:
                self._chunks.append(href)
            self._current_link_href = None
            self._current_link_text = None
            return
        if lowered in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.replace("\xa0", " ")
        if self._current_link_text is not None:
            self._current_link_text.append(text)
        else:
            self._chunks.append(text)

    def get_text(self) -> str:
        return _normalize_text("".join(self._chunks))


def body_to_text(body: EmailBody) -> str:
    """Return the best plain-text representation of an email body."""
    if body.text:
        return body.text
    if body.html:
        return html_to_text(body.html)
    return ""


def html_to_text(payload: str) -> str:
    """Convert HTML email content into readable plain text."""
    parser = _EmailHTMLToTextParser()
    parser.feed(payload)
    parser.close()
    return parser.get_text()


def _normalize_text(raw: str) -> str:
    lines: list[str] = []
    previous_blank = True
    for raw_line in raw.replace("\r", "\n").split("\n"):
        stripped = raw_line.strip()
        if stripped.startswith("-"):
            bullet_content = stripped.removeprefix("-").strip()
            line = f"- {' '.join(bullet_content.split())}" if bullet_content else ""
        else:
            line = " ".join(stripped.split())

        if not line:
            if not previous_blank and lines:
                lines.append("")
            previous_blank = True
            continue

        lines.append(line)
        previous_blank = False

    return "\n".join(lines).strip()


__all__ = ["body_to_text", "html_to_text"]
