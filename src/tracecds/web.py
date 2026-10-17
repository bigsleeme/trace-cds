"""Web search through a self-hosted SearXNG instance, then page extraction.

SearXNG (AGPL-3.0) is an open-source metasearch engine: it queries Google,
Bing, DuckDuckGo, and others on your server and returns the combined results.
Start one with the provided docker-compose.yml, or see deploy/SELF_HOSTING.md.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from .chunking import chunk_text
from .schema import Passage
from .trust import RANK, classify, domain_of

USER_AGENT = "TraceCDS/0.2 (+https://github.com/bigsleeme/trace-cds)"


class _TextExtractor(HTMLParser):
    """Keep readable body text; drop scripts, navigation, headers, and footers."""

    SKIP = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg", "button"}
    BLOCKS = {"p", "li", "h1", "h2", "h3", "h4", "td", "th", "blockquote", "dd", "dt"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.in_title = False
        self.title: list[str] = []
        self.blocks: list[str] = []
        self.current: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip_depth += 1
        elif tag == "title":
            self.in_title = True
        elif tag in self.BLOCKS and not self.skip_depth:
            self.current = []

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip_depth:
            self.skip_depth -= 1
        elif tag == "title":
            self.in_title = False
        elif tag in self.BLOCKS and self.current is not None:
            text = " ".join("".join(self.current).split())
            if len(text) > 40:
                self.blocks.append(text if text[-1] in ".!?:" else text + ".")
            self.current = None

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)
        elif self.current is not None and not self.skip_depth:
            self.current.append(data)


def extract_text(html: str) -> tuple[str, str]:
    """Return (page title, readable text) from an HTML page."""
    parser = _TextExtractor()
    parser.feed(html)
    return " ".join("".join(parser.title).split()), " ".join(parser.blocks)


class WebSearcher:
    def __init__(self, searxng_url: str | None = None, max_pages: int = 5, timeout: int = 10) -> None:
        self.base = (searxng_url or os.getenv("SEARXNG_URL") or "http://localhost:8888").rstrip("/")
        self.max_pages = max_pages
        self.timeout = timeout

    def available(self) -> bool:
        try:
            self.search("health", limit=1)
            return True
        except Exception:  # noqa: BLE001
            return False

    def search(self, query: str, limit: int = 12) -> list[dict]:
        params = urllib.parse.urlencode({"q": query, "format": "json", "language": "en", "safesearch": 1})
        req = urllib.request.Request(f"{self.base}/search?{params}", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [r for r in data.get("results", []) if r.get("url", "").startswith("http")][:limit]

    def fetch(self, url: str) -> tuple[str, str]:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            if "html" not in resp.headers.get("Content-Type", ""):
                return "", ""
            raw = resp.read(1_500_000)
            charset = resp.headers.get_content_charset() or "utf-8"
        return extract_text(raw.decode(charset, errors="replace"))

    def passages_for(self, question: str) -> list[Passage]:
        """Search, prefer authoritative sources, fetch pages, and split them into passages."""
        results = self.search(question)
        ranked = sorted(enumerate(results), key=lambda x: (RANK[classify(x[1]["url"])], x[0]))
        chosen, per_domain = [], {}
        for _, r in ranked:
            d = domain_of(r["url"])
            if per_domain.get(d, 0) >= 2:
                continue
            per_domain[d] = per_domain.get(d, 0) + 1
            chosen.append(r)
            if len(chosen) >= self.max_pages:
                break

        passages: list[Passage] = []
        for r in chosen:
            url, d = r["url"], domain_of(r["url"])
            try:
                title, text = self.fetch(url)
            except Exception:  # noqa: BLE001  (unreachable page: fall back to the snippet)
                title, text = "", ""
            title = title or r.get("title", "") or d
            if not text:
                text = r.get("content", "")
            for j, chunk in enumerate(chunk_text(text, max_chars=700)[:40]):
                passages.append(Passage(
                    passage_id=f"web:{d}:{len(passages)}:{j}", text=chunk, drug="", section=title,
                    source_title=title, source_url=url, trust=classify(url), publisher=d))
        return passages
