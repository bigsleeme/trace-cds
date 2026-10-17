"""Answer generators.

ExtractiveGenerator needs no model: it quotes the most relevant label
sentences with attribution. LLMGenerator asks a self-hosted open-source
language model to summarize the sources. Both are checked by the same guardrails afterward;
neither is trusted on its own.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request

from .chunking import split_sentences
from .schema import Passage
from .text import content_tokens

SYSTEM_PROMPT = """You support licensed healthcare professionals by summarizing FDA drug labeling.
Rules:
- Use ONLY the numbered sources provided. If they do not answer the question, reply exactly: INSUFFICIENT
- Write 2 to 5 short statements. End every statement with its source tag, e.g. [S2].
- Report what the label says ("The label states..."). Do not give orders, choose a treatment,
  set a dose for a specific patient, or make a diagnosis.
- Copy numbers (doses, frequencies, thresholds) exactly as they appear in the sources.
Return one statement per line, nothing else."""


def format_sources(passages: list[Passage]) -> str:
    return "\n\n".join(
        f"[S{i}] {p.source_title} - {p.section} (label effective {p.effective_date or 'n/a'}):\n{p.text}"
        for i, p in enumerate(passages, 1))


class ExtractiveGenerator:
    """Select and attribute the source sentences that best match the question."""

    name = "extractive"

    def __init__(self, max_statements: int = 4, per_passage: int = 2) -> None:
        self.max_statements = max_statements
        self.per_passage = per_passage

    def generate(self, question: str, passages: list[Passage]) -> list[str]:
        q = set(content_tokens(question))
        candidates: list[tuple[float, int, str]] = []
        for i, p in enumerate(passages, 1):
            if p.is_table:
                stmt = self._table_statement(q, p, i)
                if stmt:
                    candidates.append(stmt)
                continue
            scored = []
            for sent in split_sentences(p.text):
                toks = set(content_tokens(sent))
                if len(toks) < 4:
                    continue
                scored.append((len(q & toks) / (len(q) or 1) + 0.01 * (len(passages) - i), sent))
            scored.sort(reverse=True)
            for score, sent in scored[: self.per_passage]:
                if score > 0.05:
                    quote = sent.replace('"', "'")
                    candidates.append((score, i, f'According to the {p.drug} label ({p.section}): '
                                                 f'"{quote}" [S{i}]'))
        candidates.sort(key=lambda c: c[0], reverse=True)
        return [c[2] for c in candidates[: self.max_statements]]

    @staticmethod
    def _table_statement(q: set[str], p: Passage, i: int) -> tuple[float, int, str] | None:
        """Quote the table rows that best match the question, labeled by column."""
        lines = p.text.splitlines()
        rows = [ln for ln in lines if ln.startswith("|")]
        caption = " ".join(ln for ln in lines if ln and not ln.startswith("|")).strip()
        if len(rows) < 3:
            return None
        cells = lambda ln: [c.strip() for c in ln.strip().strip("|").split(" | ")]  # noqa: E731
        header, body = cells(rows[0]), [cells(r) for r in rows[2:]]
        table_hit = len(q & set(content_tokens(p.text)))
        if not table_hit:
            return None
        scored = sorted(body, key=lambda r: len(q & set(content_tokens(" ".join(r)))), reverse=True)
        chosen = scored[:2] if len(body) > 2 else body
        quoted = "; ".join(", ".join(f"{h}: {c}" for h, c in zip(header, r) if c) for r in chosen)
        quoted = quoted.replace('"', "'")
        where = p.section + (f", {caption}" if caption else "")
        return (table_hit / (len(q) or 1) + 0.25, i, f'According to the {p.drug} label ({where}): "{quoted}" [S{i}]')


class LLMGenerator:
    """Summarize sources with a self-hosted open-source LLM.

    Talks to any OpenAI-compatible endpoint served by open-source software:
    Ollama (default, http://localhost:11434/v1), vLLM, or the llama.cpp server.
    Default model: Qwen2.5-7B-Instruct (Apache 2.0). Fully open alternative:
    OLMo 2 7B (Apache 2.0, open weights, data, and training code).
    """

    name = "llm"
    DEFAULT_URL = "http://localhost:11434/v1"
    DEFAULT_MODEL = "qwen2.5:7b-instruct"

    def __init__(self, base_url: str | None = None, model: str | None = None, timeout: int = 180) -> None:
        self.base_url = (base_url or os.getenv("TRACECDS_LLM_URL") or self.DEFAULT_URL).rstrip("/")
        self.model = model or os.getenv("TRACECDS_MODEL") or self.DEFAULT_MODEL
        self.api_key = os.getenv("TRACECDS_LLM_API_KEY", "not-needed")
        self.timeout = timeout

    def available(self) -> bool:
        """True if the LLM server answers."""
        try:
            req = urllib.request.Request(f"{self.base_url}/models",
                                         headers={"authorization": f"Bearer {self.api_key}"})
            with urllib.request.urlopen(req, timeout=3):
                return True
        except Exception:  # noqa: BLE001
            return False

    def complete(self, system: str, user: str) -> str:
        body = {"model": self.model, "temperature": 0,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=json.dumps(body).encode(), method="POST",
            headers={"content-type": "application/json", "authorization": f"Bearer {self.api_key}"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode())
        text = data["choices"][0]["message"]["content"] or ""
        return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()  # reasoning models

    def generate(self, question: str, passages: list[Passage]) -> list[str]:
        text = self.complete(SYSTEM_PROMPT, f"Sources:\n{format_sources(passages)}\n\nQuestion: {question}")
        if text.strip().upper().startswith("INSUFFICIENT"):
            return []
        lines = [re.sub(r"^\s*[-*\d.)]+\s*", "", ln).strip() for ln in text.splitlines()]
        return [ln for ln in lines if ln]
