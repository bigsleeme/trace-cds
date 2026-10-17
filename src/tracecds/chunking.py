"""Sentence-aware chunking that never splits a sentence across passages."""

from __future__ import annotations

import re

# Split after . ! ? when followed by whitespace and an uppercase letter, digit,
# or opening bracket; avoids splitting on decimals like "0.5 mg".
_SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\[])")
_SECTION_NUM = re.compile(r"^\s*\d+(\.\d+)*\s+")
# Leading all-caps section heading, e.g. "DOSAGE AND ADMINISTRATION The recommended..."
_HEADING = re.compile(r"^(?:[A-Z][A-Z&/,()\-]*\s+){1,10}(?=[A-Z][a-z])")


def split_sentences(text: str) -> list[str]:
    text = " ".join(text.split())
    return [s.strip() for s in _SENT_RE.split(text) if s.strip()]


def chunk_text(text: str, max_chars: int = 900) -> list[str]:
    """Group whole sentences into chunks of at most ~max_chars characters."""
    text = _HEADING.sub("", _SECTION_NUM.sub("", " ".join(text.split())))
    chunks: list[str] = []
    current = ""
    for sent in split_sentences(text):
        if current and len(current) + 1 + len(sent) > max_chars:
            chunks.append(current)
            current = sent
        else:
            current = f"{current} {sent}".strip()
    if current:
        chunks.append(current)
    return chunks
