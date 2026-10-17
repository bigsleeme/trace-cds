"""Core data structures shared across the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Passage:
    """A retrievable unit of source text with full provenance."""

    passage_id: str
    text: str
    drug: str
    section: str
    source_title: str
    source_url: str
    effective_date: str = ""
    is_table: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Passage":
        return cls(**d)


@dataclass
class Citation:
    """A source shown to the user, numbered as it appears in the answer."""

    label: str  # e.g. "S1"
    passage: Passage
    score: float = 0.0


@dataclass
class CriterionCheck:
    """Result of checking one FDA non-device CDS criterion."""

    criterion: int
    name: str
    passed: bool
    detail: str


@dataclass
class Answer:
    """Final response: grounded statements, their sources, and the audit trail."""

    question: str
    status: str  # "answered" | "abstained" | "blocked"
    statements: list[str] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    criteria: list[CriterionCheck] = field(default_factory=list)
    removed_statements: list[dict[str, str]] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "status": self.status,
            "message": self.message,
            "statements": self.statements,
            "citations": [
                {"label": c.label, "score": round(c.score, 4), **c.passage.to_dict()}
                for c in self.citations
            ],
            "limitations": self.limitations,
            "criteria": [asdict(c) for c in self.criteria],
            "removed_statements": self.removed_statements,
        }
