"""Convert HTML tables from drug labels into Markdown.

Dosing and interaction tables carry information that plain-text extraction
often scrambles. Keeping them as Markdown preserves row/column meaning so
retrieval and generation can use them, and so clinicians can read them.
"""

from __future__ import annotations

from html.parser import HTMLParser


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._colspan = 1
        self.caption: list[str] = []
        self._in_caption = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
            span = dict(attrs).get("colspan", "1")
            self._colspan = int(span) if str(span).isdigit() else 1
        elif tag == "caption":
            self._in_caption = True
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            text = " ".join("".join(self._cell).split())
            self._row.append(text)
            self._row.extend([""] * (self._colspan - 1))
            self._cell = None
            self._colspan = 1
        elif tag == "tr" and self._row is not None:
            if any(c.strip() for c in self._row):
                self.rows.append(self._row)
            self._row = None
        elif tag == "caption":
            self._in_caption = False

    def handle_data(self, data):
        if self._in_caption:
            self.caption.append(data)
        elif self._cell is not None:
            self._cell.append(data)


def html_table_to_markdown(html: str) -> str:
    """Return a Markdown table for the first table in `html` (empty if none)."""
    parser = _TableParser()
    parser.feed(html)
    rows = parser.rows
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    esc = lambda s: s.replace("|", "\\|")  # noqa: E731
    lines = ["| " + " | ".join(esc(c) for c in rows[0]) + " |",
             "| " + " | ".join("---" for _ in range(width)) + " |"]
    for r in rows[1:]:
        lines.append("| " + " | ".join(esc(c) for c in r) + " |")
    caption = " ".join("".join(parser.caption).split())
    return (f"{caption}\n\n" if caption else "") + "\n".join(lines)
