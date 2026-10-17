"""End-to-end pipeline: screen input -> retrieve -> generate -> verify -> report."""

from __future__ import annotations

from .generate import ExtractiveGenerator
from .guardrails import check_input, check_statement
from .retrieval import BM25Retriever
from .schema import Answer, Citation, CriterionCheck, Passage
from .text import content_tokens

CRITERIA_NAMES = {
    1: "No analysis of medical images or signals",
    2: "Uses well-understood medical information (FDA labeling)",
    3: "Supports, does not direct, clinical judgment",
    4: "Basis is available for independent review",
}


class TraceCDS:
    def __init__(self, passages: list[Passage], generator=None, retriever=None,
                 k: int = 5, min_score: float = 1.0) -> None:
        self.retriever = retriever or BM25Retriever(passages)
        self.generator = generator or ExtractiveGenerator()
        self.fallback = ExtractiveGenerator()
        self.k = k
        self.min_score = min_score

    def ask(self, question: str, has_attachment: bool = False) -> Answer:
        decision = check_input(question, has_attachment=has_attachment)
        if decision.status != "ok":
            ans = Answer(question, "blocked", message=" ".join(decision.reasons))
            ans.criteria = self._criteria(ans, image=decision.image_or_signal,
                                          time_critical=decision.status == "time_critical")
            return ans

        unknown = self._unknown_terms(question)
        if unknown and not self.retriever.mentioned_drugs(question):
            return self._abstain(question, "Not covered by the indexed FDA labels "
                                           f"(unrecognized terms: {', '.join(unknown)}).")
        hits = [(p, s) for p, s in self.retriever.search(question, k=self.k) if s >= self.min_score]
        if not hits:
            return self._abstain(question, "The indexed FDA labels do not address this question.")
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
        ans.limitations = self._limitations(ans, decision.patient_specific)
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
    def _limitations(ans: Answer, patient_specific: bool) -> list[str]:
        dates = sorted({c.passage.effective_date for c in ans.citations if c.passage.effective_date})
        notes = ["Drawn only from FDA drug labeling; it may not reflect newer evidence or guidelines."]
        if dates:
            notes.append(f"Label versions cited are effective {', '.join(dates)}; check DailyMed for updates.")
        if patient_specific:
            notes.append("The question concerns a specific patient. Labeling information is general; "
                         "patient-specific factors require the clinician's own judgment.")
        return notes

    @staticmethod
    def _criteria(ans: Answer, image: bool = False, time_critical: bool = False) -> list[CriterionCheck]:
        answered = ans.status == "answered"
        all_fda = all("dailymed.nlm.nih.gov" in c.passage.source_url or not c.passage.source_url
                      for c in ans.citations)
        reviewable = answered and all(c.passage.source_url for c in ans.citations)
        if time_critical:
            detail4 = "Time-critical question declined; independent review is not feasible in an emergency."
        elif reviewable:
            detail4 = "Each statement cites a source with link, section, and label date."
        elif not answered:
            detail4 = "No recommendation given."
        else:
            detail4 = "Some citations lack a link."
        return [
            CriterionCheck(1, CRITERIA_NAMES[1], True,
                           "Image or signal input declined." if image else "Text-only input."),
            CriterionCheck(2, CRITERIA_NAMES[2], all_fda,
                           "All sources are FDA labels." if answered else "No sources used."),
            CriterionCheck(3, CRITERIA_NAMES[3], True,
                           "Statements report labeling; directive statements removed."
                           if answered else "No recommendation given."),
            CriterionCheck(4, CRITERIA_NAMES[4], reviewable or not answered, detail4),
        ]


def render(ans: Answer) -> str:
    """Plain-text rendering for the command line."""
    out = [f"Q: {ans.question}", ""]
    if ans.status != "answered":
        out.append(f"[{ans.status.upper()}] {ans.message}")
    for s in ans.statements:
        out.append(f"- {s}")
    if ans.citations:
        out += ["", "Sources:"]
        for c in ans.citations:
            p = c.passage
            out.append(f"  [{c.label}] {p.source_title} | {p.section} | effective {p.effective_date or 'n/a'}")
            out.append(f"       {p.source_url}")
    if ans.limitations:
        out += ["", "Limitations:"] + [f"  - {n}" for n in ans.limitations]
    out += ["", "Non-device CDS checks:"]
    out += [f"  {'PASS' if c.passed else 'FAIL'} C{c.criterion} {c.name}: {c.detail}" for c in ans.criteria]
    if ans.removed_statements:
        out += ["", f"Removed {len(ans.removed_statements)} unverified statement(s):"]
        out += [f"  - {r['reason']}: {r['statement'][:120]}" for r in ans.removed_statements]
    return "\n".join(out)
