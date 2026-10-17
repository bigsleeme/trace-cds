"""End-to-end pipeline: screen input -> retrieve -> generate -> verify -> report.

Three source modes:
  labels  FDA drug labels only (indexed in advance).
  web     Live web search through self-hosted SearXNG; every source is
          classified by trust and non-approved sources are flagged.
  auto    Labels first; if they don't cover the question, search the web.
"""

from __future__ import annotations

from datetime import date

from .generate import ExtractiveGenerator
from .guardrails import check_input, check_statement
from .retrieval import BM25Retriever
from .schema import Answer, Citation, CriterionCheck, Passage
from .text import content_tokens
from .trust import LABELS

CRITERIA_NAMES = {
    1: "No analysis of medical images or signals",
    2: "Uses well-understood, authoritative medical sources",
    3: "Supports, does not direct, clinical judgment",
    4: "Basis is available for independent review",
}


class TraceCDS:
    def __init__(self, passages: list[Passage], generator=None, retriever=None,
                 k: int = 5, min_score: float = 1.0, web=None) -> None:
        self.retriever = retriever or BM25Retriever(passages)
        self.generator = generator or ExtractiveGenerator()
        self.fallback = ExtractiveGenerator()
        self.k = k
        self.min_score = min_score
        self.web = web  # a web.WebSearcher, or None

    # --------------------------------------------------------------- public API

    def ask(self, question: str, has_attachment: bool = False, mode: str = "labels") -> Answer:
        decision = check_input(question, has_attachment=has_attachment)
        if decision.status != "ok":
            ans = Answer(question, "blocked", message=" ".join(decision.reasons))
            ans.criteria = self._criteria(ans, image=decision.image_or_signal,
                                          time_critical=decision.status == "time_critical")
            return ans
        if mode == "web":
            return self._ask_web(question, decision)
        ans = self._ask_labels(question, decision)
        if mode == "auto" and ans.status == "abstained" and self.web is not None:
            web_ans = self._ask_web(question, decision)
            web_ans.limitations.insert(0, "The indexed FDA labels did not cover this question, so the web was searched.")
            return web_ans
        return ans

    # ------------------------------------------------------------------ sources

    def _ask_labels(self, question: str, decision) -> Answer:
        unknown = self._unknown_terms(question)
        if unknown and not self.retriever.mentioned_drugs(question):
            return self._abstain(question, "Not covered by the indexed FDA labels "
                                           f"(unrecognized terms: {', '.join(unknown)}).")
        hits = [(p, s) for p, s in self.retriever.search(question, k=self.k) if s >= self.min_score]
        if not hits:
            return self._abstain(question, "The indexed FDA labels do not address this question.")
        return self._answer(question, hits, decision)

    def _ask_web(self, question: str, decision) -> Answer:
        if self.web is None:
            return self._abstain(question, "Web search is not configured (set SEARXNG_URL).")
        try:
            passages = self.web.passages_for(question)
        except Exception as exc:  # noqa: BLE001
            return self._abstain(question, f"Web search failed: {exc}")
        if not passages:
            return self._abstain(question, "Web search returned no usable pages.")
        retriever = BM25Retriever(passages)
        hits = [(p, s) for p, s in retriever.search(question, k=self.k) if s > 0]
        if not hits:
            return self._abstain(question, "The pages found do not address this question.")
        return self._answer(question, hits, decision, web=True)

    # ------------------------------------------------------------------ answer

    def _answer(self, question: str, hits, decision, web: bool = False) -> Answer:
        passages = [p for p, _ in hits]
        sources = dict(enumerate(passages, 1))
        statements, removed = self._verified(self.generator, question, passages, sources)
        if not statements and self.generator.name != "extractive":
            statements, more = self._verified(self.fallback, question, passages, sources)
            removed += more
        if not statements:
            ans = self._abstain(question, "No statement could be verified against the sources.")
            ans.removed_statements = removed
            return ans

        used = sorted({n for s in statements for n in check_statement(s, sources).cited})
        ans = Answer(question, "answered", statements=statements, removed_statements=removed)
        ans.citations = [Citation(f"S{n}", sources[n], score=hits[n - 1][1]) for n in used]
        ans.warnings = self._trust_warnings(ans)
        ans.limitations = self._limitations(ans, decision.patient_specific, web)
        ans.criteria = self._criteria(ans)
        return ans

    # ------------------------------------------------------------------ helpers

    def _unknown_terms(self, question: str) -> list[str]:
        """Substantive question words that appear nowhere in the indexed labels."""
        vocab = self.retriever.idf
        return sorted({t for t in content_tokens(question) if len(t) >= 5 and t not in vocab})

    def _verified(self, generator, question, passages, sources):
        kept, removed = [], []
        for stmt in generator.generate(question, passages):
            check = check_statement(stmt, sources)
            if check.ok:
                kept.append(stmt)
            else:
                removed.append({"statement": stmt, "reason": check.reason, "generator": generator.name})
        return kept, removed

    def _abstain(self, question: str, why: str) -> Answer:
        ans = Answer(question, "abstained", message=why)
        ans.criteria = self._criteria(ans)
        return ans

    @staticmethod
    def _trust_warnings(ans: Answer) -> list[str]:
        warnings = []
        for tier in ("unverified", "reputable"):
            labels = [c.label for c in ans.citations if c.passage.trust == tier]
            if not labels:
                continue
            pubs = sorted({c.passage.publisher for c in ans.citations if c.passage.trust == tier})
            if tier == "unverified":
                warnings.append(f"{', '.join(labels)} come from sources that are NOT approved healthcare sources "
                                f"({', '.join(pubs)}). Verify this information with an authoritative source "
                                "before relying on it.")
            else:
                warnings.append(f"{', '.join(labels)} come from recognized medical institutions "
                                f"({', '.join(pubs)}), not regulatory or peer-reviewed sources.")
        return warnings

    @staticmethod
    def _limitations(ans: Answer, patient_specific: bool, web: bool) -> list[str]:
        notes = []
        if web:
            notes.append(f"Web sources were retrieved on {date.today().isoformat()}; pages can change or be removed.")
        if any(c.passage.drug for c in ans.citations):
            notes.append("Label information may not reflect newer evidence or guidelines.")
            dates = sorted({c.passage.effective_date for c in ans.citations if c.passage.effective_date})
            if dates:
                notes.append(f"Label versions cited are effective {', '.join(dates)}; check DailyMed for updates.")
        if patient_specific:
            notes.append("The question concerns a specific patient. Source information is general; "
                         "patient-specific factors require the clinician's own judgment.")
        return notes

    @staticmethod
    def _criteria(ans: Answer, image: bool = False, time_critical: bool = False) -> list[CriterionCheck]:
        answered = ans.status == "answered"
        flagged = sorted({c.passage.publisher for c in ans.citations if c.passage.trust != "approved"})
        reviewable = answered and all(c.passage.source_url for c in ans.citations)
        if time_critical:
            detail4 = "Time-critical question declined; independent review is not feasible in an emergency."
        elif reviewable:
            detail4 = "Each statement cites a source with a link the clinician can open."
        elif not answered:
            detail4 = "No recommendation given."
        else:
            detail4 = "Some citations lack a link."
        detail2 = ("No sources used." if not answered else
                   "All sources are approved healthcare sources." if not flagged else
                   f"Includes sources that are not approved healthcare sources ({', '.join(flagged)}); "
                   "flagged to the user.")
        return [
            CriterionCheck(1, CRITERIA_NAMES[1], True,
                           "Image or signal input declined." if image else "Text-only input."),
            CriterionCheck(2, CRITERIA_NAMES[2], not flagged, detail2),
            CriterionCheck(3, CRITERIA_NAMES[3], True,
                           "Statements report what sources say; directive statements removed."
                           if answered else "No recommendation given."),
            CriterionCheck(4, CRITERIA_NAMES[4], reviewable or not answered, detail4),
        ]


def render(ans: Answer) -> str:
    """Plain-text rendering for the command line."""
    out = [f"Q: {ans.question}", ""]
    if ans.status != "answered":
        out.append(f"[{ans.status.upper()}] {ans.message}")
    for w in ans.warnings:
        out.append(f"!! {w}")
    if ans.warnings:
        out.append("")
    for s in ans.statements:
        out.append(f"- {s}")
    if ans.citations:
        out += ["", "Sources:"]
        for c in ans.citations:
            p = c.passage
            extra = f" | effective {p.effective_date}" if p.effective_date else ""
            where = p.source_title if p.section == p.source_title else f"{p.source_title} | {p.section}"
            out.append(f"  [{c.label}] {LABELS[p.trust].upper()}: {where}{extra}")
            out.append(f"       {p.source_url}")
    if ans.limitations:
        out += ["", "Limitations:"] + [f"  - {n}" for n in ans.limitations]
    out += ["", "Checks:"]
    out += [f"  {'PASS' if c.passed else 'FLAG'} C{c.criterion} {c.name}: {c.detail}" for c in ans.criteria]
    if ans.removed_statements:
        out += ["", f"Removed {len(ans.removed_statements)} unverified statement(s):"]
        out += [f"  - {r['reason']}: {r['statement'][:120]}" for r in ans.removed_statements]
    return "\n".join(out)
