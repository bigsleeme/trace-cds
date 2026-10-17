"""Shared text utilities: tokenization and stopwords."""

from __future__ import annotations

import re

STOPWORDS = frozenset("""
a an and are as at be been being but by can could did do does for from had has have
how i if in into is it its may might more most must no not of on or our should so
such than that the their them then there these they this those to was were what
when where which while who whom why will with would you your about also any both
each other per via vs between during after before over under than very up out
""".split())

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def content_tokens(text: str) -> list[str]:
    return [t for t in tokenize(text) if t not in STOPWORDS and len(t) > 1]
