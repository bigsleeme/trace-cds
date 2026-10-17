"""Guardrails that keep outputs within FDA's non-device CDS criteria.

Prompting alone does not reliably keep LLM output non-device ("Unregulated large
language models produce medical device-like output," npj Digital Medicine, 2025). These checks run in code, on every input and on
every generated statement, regardless of which generator produced it.

FDA non-device CDS criteria (FD&C Act 520(o)(1)(E); FDA CDS guidance, Jan 2026):
  1. Does not acquire, process, or analyze medical images or signals.
  2. Displays, analyzes, or prints medical information from well-understood sources.
  3. Supports or provides recommendations to an HCP without replacing or
     directing their judgment.
  4. Enables the HCP to independently review the basis for the recommendations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .schema import Passage
from .text import content_tokens

# ---------------------------------------------------------------- input checks

_IMAGE_SIGNAL_RE = re.compile(
    r"\b(this|attached|uploaded|the following)\s+(image|photo|picture|scan|x-?ray|ct|mri|"
    r"ultrasound|ecg|ekg|eeg|tracing|waveform|slide|dermoscop\w*)\b"
    r"|\b(analy[sz]e|read|interpret|look at)\s+(this|the|my|attached)\s+"
    r"(image|photo|picture|scan|x-?ray|ct|mri|ecg|ekg|eeg|tracing|rash|lesion|mole)\b",
    re.I)

_PHI_PATTERNS = {
    "SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "MRN": re.compile(r"\b(mrn|medical record( number)?)\s*[:#]?\s*\w*\d{4,}", re.I),
    "date of birth": re.compile(r"\b(dob|date of birth|born on)\b\s*[:]?\s*\d", re.I),
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"),
    "phone": re.compile(r"\(?\b\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b"),
}

# Always time-critical, whatever the phrasing.
ACUTE_TERMS = (
    "code blue", "cardiac arrest", "respiratory arrest", "not breathing", "unresponsive",
    "emergency", "right now", "bleeding out", "status epilepticus",
)
# Conditions that are time-critical only when described as happening to a patient now.
CONDITION_TERMS = (
    "anaphylaxis", "anaphylactic", "stroke", "seizure", "seizing", "overdose", "overdosed",
    "sepsis", "septic shock", "hemorrhage", "hemorrhaging", "suicidal", "suicide",
)
_ACUTE_CUE_RE = re.compile(
    r"\b(is|are|currently|now|just|having|having an?|in|going into|presenting with|presents with|"
    r"experiencing|took|ingested|swallowed)\b", re.I)


def _time_critical_hits(question: str) -> list[str]:
    q = f" {question.lower()} "
    hits = [t for t in ACUTE_TERMS if t in q]
    for term in CONDITION_TERMS:
        idx = q.find(term)
        if idx == -1:
            continue
        window = q[max(0, idx - 40):idx]  # words just before the condition
        if _PATIENT_SPECIFIC_RE.search(q) and _ACUTE_CUE_RE.search(window):
            hits.append(term)
    return sorted(set(hits))


_PATIENT_SPECIFIC_RE = re.compile(
    r"\b(my|this|a|the|our)\s+(patient|pt|client)s?\b|\bshould i\b|\bwhat dose should\b|\b(he|she) (is|just|took)\b", re.I)


@dataclass
class InputDecision:
    status: str  # "ok" | "blocked" | "time_critical"
    reasons: list[str] = field(default_factory=list)
    patient_specific: bool = False
    image_or_signal: bool = False


def check_input(question: str, has_attachment: bool = False) -> InputDecision:
    """Screen a question before any retrieval or generation happens."""
    if has_attachment or _IMAGE_SIGNAL_RE.search(question):
        return InputDecision("blocked", ["Criterion 1: TraceCDS does not analyze medical "
                                         "images, signals, or attachments."], image_or_signal=True)
    found = [name for name, rx in _PHI_PATTERNS.items() if rx.search(question)]
    if found:
        return InputDecision("blocked", [f"Possible patient identifiers detected ({', '.join(found)}). "
                                         "Remove identifiers and ask in general terms."])
    hits = _time_critical_hits(question)
    if hits:
        return InputDecision("time_critical", [
            "Criterion 4: the question appears time-critical "
            f"({', '.join(hits)}). TraceCDS is not designed for emergencies; "
            "follow your institution's emergency protocol."])
    return InputDecision("ok", patient_specific=bool(_PATIENT_SPECIFIC_RE.search(question)))


# ------------------------------------------------------------- output checks

CITATION_RE = re.compile(r"\[S(\d+)\]")
_ATTRIBUTION_RE = re.compile(
    r"^(according to|per|the [\w\s-]{0,40}label (states|says|lists|notes|recommends|includes)|"
    r"the label (states|says|lists|notes|recommends|includes))\b", re.I)
_QUOTED_RE = re.compile(r"\"[^\"]*\"|“[^”]*”")
_DIRECTIVE_PATTERNS = [
    re.compile(r"^(give|administer|start|initiate|begin|stop|discontinue|increase|decrease|reduce|"
               r"titrate|prescribe|switch|take|use|avoid|hold|order|continue|add)\b", re.I),
    re.compile(r"\b(you|we|i)\s+(should|must|need to|have to|ought to)\b", re.I),
    re.compile(r"\b(i|we)\s+(recommend|advise|suggest)\b", re.I),
    re.compile(r"\b(the|your|this)\s+patient\s+(should|must|needs to|has to)\b", re.I),
    re.compile(r"\b(the )?(diagnosis|correct treatment|best treatment|right dose|correct dose)\s+"
               r"(is|would be|will be)\b", re.I),
]
_NUM_RE = re.compile(r"\b\d+(?:\.\d+)?\b")


def is_attributed(statement: str) -> bool:
    """True if the statement reports what a source says rather than directing."""
    return bool(_ATTRIBUTION_RE.search(statement.strip()))


def find_directive(statement: str) -> str | None:
    """Return the directive phrase if an unattributed statement directs care."""
    body = CITATION_RE.sub("", statement).strip()
    if is_attributed(body):
        body = _QUOTED_RE.sub("", body)  # quoted label text is reported, not directed
        body = _ATTRIBUTION_RE.sub("", body).strip(" :,")
        # Attributed paraphrase of the label is still reporting; only flag first-person/patient directives.
        checks = _DIRECTIVE_PATTERNS[1:]
    else:
        checks = _DIRECTIVE_PATTERNS
    for rx in checks:
        m = rx.search(body)
        if m:
            return m.group(0)
    return None


@dataclass
class StatementCheck:
    ok: bool
    reason: str = ""
    cited: list[int] = field(default_factory=list)
    support: float = 0.0


def check_statement(statement: str, sources: dict[int, Passage],
                    min_support: float = 0.6) -> StatementCheck:
    """Verify one generated statement against its cited sources.

    A statement passes only if it (a) cites at least one provided source,
    (b) every number in it appears in those sources, (c) most of its content
    words appear in those sources, and (d) it does not direct care.
    """
    cited = [int(n) for n in CITATION_RE.findall(statement)]
    valid = [n for n in cited if n in sources]
    if not valid:
        return StatementCheck(False, "no valid citation (Criterion 4)", cited)
    source_text = " ".join(sources[n].text for n in valid)
    body = CITATION_RE.sub("", statement).strip()
    # Drop the attribution prefix ('According to X (Title): "...') so source names and page
    # titles are not checked as claims.
    if is_attributed(body) and ': "' in body:
        body = body.split(': "', 1)[1]
        body = '"' + body
    quotes = [q.strip('"“” ') for q in _QUOTED_RE.findall(body)]

    src_nums = set(_NUM_RE.findall(source_text))
    missing = [n for n in _NUM_RE.findall(body) if n not in src_nums]
    if missing:
        return StatementCheck(False, f"numbers not found in cited source: {', '.join(missing)}", valid)

    norm = lambda t: " ".join(t.replace('"', "'").replace("“", "'").replace("”", "'").split()).lower()  # noqa: E731
    if quotes and all(norm(q) in norm(source_text) for q in quotes):
        support = 1.0  # verbatim quotation
    else:
        src_tokens = set(content_tokens(source_text))
        check_text = " ".join(quotes) if quotes else _ATTRIBUTION_RE.sub("", body)
        stmt_tokens = [t for t in content_tokens(check_text) if not t.isdigit() and t != "label"]
        support = (sum(t in src_tokens for t in stmt_tokens) / len(stmt_tokens)) if stmt_tokens else 0.0
    if support < min_support:
        return StatementCheck(False, f"insufficient support in cited source ({support:.0%})", valid, support)

    directive = find_directive(statement)
    if directive:
        return StatementCheck(False, f"directive language '{directive}' (Criterion 3)", valid, support)
    return StatementCheck(True, "", valid, support)
