"""TraceCDS chat app: FastAPI backend + custom web frontend.

    python app.py            # then open http://localhost:7860

On first start it downloads FDA labels for the default drug set from openFDA and
caches them in data/corpus.jsonl. The LLM "Written answer" mode talks to any
OpenAI-compatible endpoint set via TRACECDS_LLM_URL / TRACECDS_MODEL /
TRACECDS_LLM_API_KEY (the deployment points these at the DeepInfra API). In
production this is served at chat.tracecds.com; the marketing homepage
(site/index.html) is served separately -- see deploy/Caddyfile.

The frontend lives in chat/ (index.html, style.css, app.js) and talks to this
backend over /api/config and /api/ask.
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from fastapi import Depends, FastAPI, Header, HTTPException  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from tracecds import DISCLAIMER, __version__  # noqa: E402
from tracecds.generate import LLMGenerator  # noqa: E402
from tracecds.pipeline import TraceCDS  # noqa: E402
from tracecds.retrieval import BM25Retriever, build_retriever  # noqa: E402
from tracecds.schema import Answer  # noqa: E402
from tracecds.cli import DEFAULT_DRUGS  # noqa: E402
from tracecds.sources import build_corpus, label_to_passages, load_corpus, save_corpus, search_label  # noqa: E402
from tracecds.text import content_tokens  # noqa: E402
from tracecds.web import WebSearcher  # noqa: E402

HERE = Path(__file__).parent
CHAT_DIR = HERE / "chat"
CORPUS_PATH = os.getenv("TRACECDS_CORPUS", "data/corpus.jsonl")
HOME_URL = os.getenv("TRACECDS_HOME_URL", "https://tracecds.com")

EXAMPLES = [
    "What are the contraindications for metformin?",
    "Does clopidogrel interact with omeprazole?",
    "Can I take ibuprofen together with warfarin?",
    "What does the isotretinoin label say about pregnancy?",
    "What is the renal dosing for gabapentin?",
    "What does the sertraline boxed warning say about suicidal thoughts?",
]


def load_or_build() -> list:
    if not os.path.exists(CORPUS_PATH):
        os.makedirs(os.path.dirname(CORPUS_PATH) or ".", exist_ok=True)
        save_corpus(build_corpus(DEFAULT_DRUGS, api_key=os.getenv("OPENFDA_API_KEY")), CORPUS_PATH)
    return load_corpus(CORPUS_PATH)


# --------------------------------------------------------------------- pipeline

PASSAGES = load_or_build()
RETRIEVER = build_retriever(PASSAGES)
_WEB = WebSearcher()
WEB_AVAILABLE = _WEB.available()

# The LLM writes a real answer synthesized from the retrieved sources (still
# verified against them, with directive language stripped -- see guardrails.py).
# Configured via env; the deployment points it at the DeepInfra API.
LLM_MODELS = {"Written answer": os.getenv("TRACECDS_MODEL", "qwen2.5:7b-instruct")}
_LLM = LLMGenerator()
LLM_AVAILABLE = _LLM.available()

EXTRACTIVE = TraceCDS(PASSAGES, retriever=RETRIEVER, web=_WEB if WEB_AVAILABLE else None)

EXTRACTIVE_MODE = "Quoted from label"
LLM_MODE = "Written answer"
SYSTEMS = {}
if LLM_AVAILABLE:
    SYSTEMS[LLM_MODE] = TraceCDS(PASSAGES, generator=_LLM, retriever=RETRIEVER,
                                 web=_WEB if WEB_AVAILABLE else None)
SYSTEMS[EXTRACTIVE_MODE] = EXTRACTIVE
ANSWER_MODES = list(SYSTEMS.keys())
DEFAULT_ANSWER_MODE = ANSWER_MODES[0]

SOURCE_MODES = {"FDA labels, then web": "auto", "FDA labels only": "labels", "Web only": "web"}
SOURCE_CHOICES = list(SOURCE_MODES) if WEB_AVAILABLE else ["FDA labels only"]
DEFAULT_SOURCE_MODE = SOURCE_CHOICES[0]
DRUG_LIST = sorted({p.drug for p in PASSAGES})

# --------------------------------------------------------------------- render

_CITE = re.compile(r"\[S(\d+)\]")
SHORT_TRUST = {"approved": "Approved", "reputable": "Recognized institution", "unverified": "Not approved"}


def _linkify(statement: str) -> str:
    text = html.escape(statement)
    return _CITE.sub(lambda m: f'<a class="cite" href="#src-S{m.group(1)}">S{m.group(1)}</a>', text)


def answer_html(ans: Answer) -> str:
    """Inner HTML for one assistant turn: flowing prose, a quiet sources list,
    and a condensed checks line with the full detail tucked in a collapsible.
    The frontend wraps this with the avatar and message container."""
    body = []

    for w in ans.warnings:
        cls = "stop" if "NOT approved" in w else "warn"
        body.append(f'<div class="warn-line {cls}">⚠ Source check: {html.escape(w)}</div>')

    if ans.statements:
        body.append("".join(f"<p>{_linkify(s)}</p>" for s in ans.statements))
    elif ans.message:
        body.append(f'<p class="muted">{html.escape(ans.message)}</p>')

    if ans.citations:
        src = ['<div class="src-block"><h4>Sources</h4>']
        for c in ans.citations:
            p = c.passage
            date_txt = (f' · <span class="muted">effective {html.escape(p.effective_date)}</span>'
                        if p.effective_date else "")
            where = "DailyMed ↗" if p.drug else f"{html.escape(p.publisher)} ↗"
            whereline = p.source_title if p.section == p.source_title else p.source_title + " · " + p.section
            src.append(
                f'<div class="src-item" id="src-{c.label}"><b>{c.label}</b> '
                f'<span class="trust {p.trust}">{SHORT_TRUST[p.trust]}</span> '
                f'{html.escape(whereline)}{date_txt} · '
                f'<a href="{html.escape(p.source_url)}" target="_blank" rel="noopener">{where}</a></div>')
        src.append("</div>")
        body.append("".join(src))

    passed = sum(1 for c in ans.criteria if c.passed)
    total = len(ans.criteria)
    if ans.criteria:
        mark = "✓" if passed == total else "⚠"
        summary = (f"All {total} FDA non-device CDS checks passed" if passed == total
                   else f"{total - passed} of {total} FDA checks flagged")
        tail = f' · <span class="muted">{html.escape(ans.limitations[0])}</span>' if ans.limitations else ""
        body.append(f'<div class="meta-line">{mark} {summary}{tail}</div>')

    details = []
    if ans.limitations:
        details.append("<b>Limitations</b><ul>"
                       + "".join(f"<li>{html.escape(n)}</li>" for n in ans.limitations) + "</ul>")
    if ans.criteria:
        rows = "".join(
            f'<tr><td>{"✅" if c.passed else "⚠️"}</td><td>C{c.criterion}. {html.escape(c.name)}</td>'
            f"<td>{html.escape(c.detail)}</td></tr>" for c in ans.criteria)
        details.append(f"<b>FDA non-device CDS checks</b><table>{rows}</table>")
    if ans.removed_statements:
        items = "".join(f"<li><i>{html.escape(r['reason'])}</i>: {html.escape(r['statement'])}</li>"
                        for r in ans.removed_statements)
        details.append(f"<b>{len(ans.removed_statements)} unverified statement(s) removed</b><ul>{items}</ul>")
    if details:
        body.append('<details class="meta-details"><summary>Show checks &amp; details</summary>'
                     + "".join(details) + "</details>")

    return "".join(body)


# --------------------------------------------------------------------- follow-ups

_REWRITE_SYS = (
    "You rewrite the user's LAST question into a standalone search query, using the earlier "
    "questions to resolve references like 'it', 'that', 'the benefits', 'the dose'. "
    "Reply with ONLY the rewritten query on a single line, no quotes or preamble. "
    "If the last question already stands on its own, reply with it unchanged.")


def standalone_query(question: str, prior_questions: list[str]) -> str:
    """Turn a follow-up into a self-contained query using prior user turns."""
    if not prior_questions or not LLM_AVAILABLE:
        return question
    convo = "\n".join(f"- {q}" for q in prior_questions[-4:]) + f"\n- {question}"
    try:
        out = _LLM.complete(_REWRITE_SYS,
                            f"Earlier questions, then the last one:\n{convo}\n\n"
                            "Standalone version of the last question:")
        out = out.strip().strip('"').splitlines()[0].strip() if out else ""
        return out[:300] or question
    except Exception:  # noqa: BLE001
        return question


# --------------------------------------------------------------------- interactions

_INTERACTION_CUES = ("interact", "combined", "combine", "together", "concurrent",
                     "co-administer", "coadminister", "co-administration", "mixing", " mix ",
                     "taken with", "take with", "safe with", "same time")


def interaction_drugs(question: str) -> list[str]:
    """If the question is asking about an interaction between 2+ indexed drugs,
    return those drug names; otherwise an empty list."""
    drugs = EXTRACTIVE.retriever.mentioned_drugs(question)
    q = question.lower()
    if len(drugs) >= 2 and any(cue in q for cue in _INTERACTION_CUES):
        return drugs
    return []


# ----- on-demand drug lookup: any drug not pre-indexed is fetched live from openFDA -----
OPENFDA_KEY = os.getenv("OPENFDA_API_KEY")
LIVE_LOOKUP = os.getenv("TRACECDS_LIVE_LOOKUP", "1") != "0"
LIVE_CACHE: dict[str, list] = {}   # term/name -> passages (per process)
LIVE_NEG: set[str] = set()         # terms openFDA had no label for

# Words that are questions-about-drugs, not drug names -- never looked up as drugs.
_QUESTION_WORDS = {
    "contraindication", "contraindications", "dose", "dosage", "dosing", "doses",
    "interaction", "interactions", "pregnancy", "pregnant", "warning", "warnings",
    "adverse", "reaction", "reactions", "label", "labels", "indication", "indications",
    "precaution", "precautions", "overdose", "overdosage", "renal", "hepatic", "pediatric",
    "geriatric", "effect", "effects", "side", "drug", "drugs", "take", "taking", "used",
    "using", "patient", "patients", "safe", "risk", "risks", "according", "tablet", "tablets",
    "boxed", "mechanism", "action", "administration", "treatment", "treat", "with", "what",
    "which", "does", "about", "between", "severe", "renal", "function", "impairment",
}


def _candidate_terms(question: str) -> list[str]:
    """Substantive words that could be a drug name, longest first (drug names tend
    to be longer and uncommon), excluding question words and already-indexed drugs."""
    indexed = set(EXTRACTIVE.retriever.drugs)
    seen, out = set(), []
    for t in content_tokens(question):
        if len(t) < 4 or t in _QUESTION_WORDS or t in indexed or t in seen or t.isdigit():
            continue
        seen.add(t)
        out.append(t)
    out.sort(key=len, reverse=True)
    return out[:4]


def _persist_live(passages: list) -> None:
    """Append a freshly-fetched label to the corpus file so it is pre-indexed next restart."""
    try:
        with open(CORPUS_PATH, "a", encoding="utf-8") as f:
            for p in passages:
                f.write(json.dumps(p.to_dict(), ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


def live_label_answer(question: str, answer_mode: str):
    """Answer from a drug's label fetched live from openFDA, for drugs not in the
    pre-indexed corpus. Returns an answered Answer, or None if nothing matched."""
    if not LIVE_LOOKUP:
        return None
    generator = SYSTEMS.get(answer_mode, EXTRACTIVE).generator
    for term in _candidate_terms(question):
        if term in LIVE_NEG:
            continue
        passages = LIVE_CACHE.get(term)
        if passages is None:
            res = search_label(term, api_key=OPENFDA_KEY)
            if not res:
                LIVE_NEG.add(term)
                continue
            label, name = res
            passages = label_to_passages(label, drug=name)
            LIVE_CACHE[term] = passages
            LIVE_CACHE[name] = passages
            _persist_live(passages)
        if not passages:
            continue
        transient = TraceCDS(passages, generator=generator,
                             retriever=BM25Retriever(passages), web=None)
        ans = transient.ask(question[:500], mode="labels")
        if ans.status == "answered":
            ans.limitations.append("This drug's label was fetched live from openFDA/DailyMed on "
                                   "demand (not in the pre-indexed set).")
            return ans
    return None


def run_query(answer_mode: str, question: str, source_mode: str):
    """Route a question across tiers of FDA-label sourcing, then the web:
    interaction check -> (on-demand lookup when no indexed drug is named) ->
    local index -> web (auto)."""
    system = SYSTEMS.get(answer_mode, EXTRACTIVE)
    smode = SOURCE_MODES.get(source_mode, "labels")

    drugs = interaction_drugs(question)
    if drugs:
        return system.ask_interactions(drugs)

    if smode == "web":
        return system.ask(question[:500], mode="web")

    # If the question names a drug that isn't pre-indexed, fetch that drug's label
    # live from openFDA first -- otherwise a keyword match in some other drug's
    # label could answer in the wrong context.
    if not system.retriever.mentioned_drugs(question):
        live = live_label_answer(question, answer_mode)
        if live is not None:
            return live

    # pre-indexed labels
    ans = system.ask(question[:500], mode="labels")
    if ans.status in ("answered", "blocked"):
        return ans

    # still nothing -> web, only in "labels, then web" (auto) mode
    if smode == "auto" and system.web is not None:
        web_ans = system.ask(question[:500], mode="web")
        web_ans.limitations.insert(0, "Not covered by indexed or on-demand FDA labels, so the web was searched.")
        return web_ans
    return ans


# --------------------------------------------------------------------- app

app = FastAPI(
    title="TraceCDS API",
    version=__version__,
    description=(
        "Traceable, source-checked answers to drug-information questions, kept within FDA's "
        "non-device clinical decision support criteria. Every statement is verified against its "
        "cited source and directive language is removed before the answer is returned.\n\n"
        "**Research use only. Not for clinical use. Not a medical device.**\n\n"
        "Authenticate with an API key: `Authorization: Bearer <key>` (or the `X-API-Key` header)."),
    docs_url="/v1/docs", redoc_url="/v1/redoc", openapi_url="/v1/openapi.json",
)

# ----- API-key auth (keys come from the env, comma-separated; kept out of the repo) -----
API_KEYS = {k.strip() for k in os.getenv("TRACECDS_API_KEYS", "").split(",") if k.strip()}


def require_key(authorization: str = Header(None), x_api_key: str = Header(None)) -> str:
    if not API_KEYS:
        raise HTTPException(503, "API is not configured: no keys are set (TRACECDS_API_KEYS).")
    key = None
    if authorization and authorization.lower().startswith("bearer "):
        key = authorization[7:].strip()
    key = key or (x_api_key.strip() if x_api_key else None)
    if not key or key not in API_KEYS:
        raise HTTPException(401, "Invalid or missing API key.")
    return key


# ----- schemas -----
class V1AskRequest(BaseModel):
    question: str = Field(..., description="The drug-information question to answer.",
                          examples=["What are the contraindications for metformin?"])
    answer_mode: str | None = Field(None, description=f"One of {ANSWER_MODES}. Default: {DEFAULT_ANSWER_MODE}.")
    source_mode: str | None = Field(None, description=f"One of {SOURCE_CHOICES}. Default: {DEFAULT_SOURCE_MODE}.")
    history: list[str] = Field(default_factory=list,
                               description="Prior user questions (oldest first) so follow-ups resolve references.")


class V1Citation(BaseModel):
    label: str
    score: float
    passage_id: str
    text: str
    drug: str
    section: str
    source_title: str
    source_url: str
    effective_date: str
    is_table: bool
    trust: str = Field(..., description="approved | reputable | unverified")
    publisher: str


class V1Criterion(BaseModel):
    criterion: int
    name: str
    passed: bool
    detail: str


class V1AskResponse(BaseModel):
    status: str = Field(..., description="answered | abstained | blocked")
    question: str = Field(..., description="The question as received.")
    query_used: str = Field(..., description="The (possibly rewritten) standalone query used for retrieval.")
    answer_mode: str
    source_mode: str
    message: str
    statements: list[str]
    citations: list[V1Citation]
    criteria: list[V1Criterion]
    limitations: list[str]
    warnings: list[str]
    removed_statements: list[dict]


# ----- internal endpoints used by the web chat (same origin, no key) -----
class AskRequest(BaseModel):
    question: str
    answer_mode: str = DEFAULT_ANSWER_MODE
    source_mode: str = DEFAULT_SOURCE_MODE
    history: list[str] = []


@app.get("/api/config", include_in_schema=False)
def config() -> JSONResponse:
    return JSONResponse({
        "version": __version__, "disclaimer": DISCLAIMER, "home_url": HOME_URL,
        "answer_modes": ANSWER_MODES, "default_answer_mode": DEFAULT_ANSWER_MODE,
        "source_modes": SOURCE_CHOICES, "default_source_mode": DEFAULT_SOURCE_MODE,
        "web_available": WEB_AVAILABLE, "llm_available": LLM_AVAILABLE,
        "drugs": DRUG_LIST, "examples": EXAMPLES,
    })


@app.post("/api/ask", include_in_schema=False)
def web_ask(req: AskRequest) -> JSONResponse:
    question = (req.question or "").strip()
    if not question:
        return JSONResponse({"error": "empty question"}, status_code=400)
    query = standalone_query(question, req.history)
    ans = run_query(req.answer_mode, query, req.source_mode)
    return JSONResponse({"html": answer_html(ans), "status": ans.status})


# ----- public v1 developer API (key required) -----
@app.get("/v1/health", tags=["service"], summary="Liveness check (no key required)")
def v1_health() -> dict:
    return {"status": "ok", "version": __version__}


@app.get("/v1/info", tags=["service"], summary="Service capabilities and options")
def v1_info(_: str = Depends(require_key)) -> dict:
    return {
        "version": __version__,
        "disclaimer": DISCLAIMER,
        "answer_modes": ANSWER_MODES,
        "default_answer_mode": DEFAULT_ANSWER_MODE,
        "source_modes": SOURCE_CHOICES,
        "default_source_mode": DEFAULT_SOURCE_MODE,
        "web_search": WEB_AVAILABLE,
        "llm_answers": LLM_AVAILABLE,
        "indexed_drugs": DRUG_LIST,
    }


@app.post("/v1/ask", response_model=V1AskResponse, tags=["answers"],
          summary="Ask a drug-information question",
          description="Returns source-checked statements, their cited sources (with trust tier and "
                      "effective date), the FDA non-device CDS criteria results, limitations, and any "
                      "statements that were removed because they could not be verified.")
def v1_ask(req: V1AskRequest, _: str = Depends(require_key)) -> dict:
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(400, "question must not be empty.")
    if len(question) > 500:
        raise HTTPException(400, "question must be 500 characters or fewer.")
    answer_mode = req.answer_mode or DEFAULT_ANSWER_MODE
    source_mode = req.source_mode or DEFAULT_SOURCE_MODE
    if answer_mode not in SYSTEMS:
        raise HTTPException(400, f"answer_mode must be one of {ANSWER_MODES}.")
    if source_mode not in SOURCE_MODES:
        raise HTTPException(400, f"source_mode must be one of {list(SOURCE_MODES)}.")
    query = standalone_query(question, req.history)
    ans = run_query(answer_mode, query, source_mode)
    out = ans.to_dict()
    out["query_used"] = query
    out["answer_mode"] = answer_mode
    out["source_mode"] = source_mode
    return out


class V1InteractionsRequest(BaseModel):
    drugs: list[str] = Field(..., min_length=2,
                             description="Two or more generic drug names to check for interactions.",
                             examples=[["warfarin", "amoxicillin"]])
    answer_mode: str | None = Field(None, description=f"One of {ANSWER_MODES}. Default: {DEFAULT_ANSWER_MODE}.")


@app.post("/v1/interactions", response_model=V1AskResponse, tags=["answers"],
          summary="Check drug–drug interactions",
          description="Reports what the drugs' FDA labels say about interactions among them — surfacing "
                      "passages in one drug's label that name another of the drugs first. Each statement "
                      "is cited and verified against its source. Reports what the labels say; it does not "
                      "decide whether to co-prescribe.")
def v1_interactions(req: V1InteractionsRequest, _: str = Depends(require_key)) -> dict:
    drugs = [d.strip() for d in req.drugs if d and d.strip()]
    if len(drugs) < 2:
        raise HTTPException(400, "Provide at least two drug names.")
    answer_mode = req.answer_mode or DEFAULT_ANSWER_MODE
    if answer_mode not in SYSTEMS:
        raise HTTPException(400, f"answer_mode must be one of {ANSWER_MODES}.")
    ans = SYSTEMS[answer_mode].ask_interactions(drugs)
    out = ans.to_dict()
    out["query_used"] = ans.question
    out["answer_mode"] = answer_mode
    out["source_mode"] = "labels"
    return out


# ----- web chat (served last so the static mount doesn't shadow the API) -----
@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(CHAT_DIR / "index.html")


app.mount("/", StaticFiles(directory=CHAT_DIR), name="static")


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("TRACECDS_HOST") or os.getenv("GRADIO_SERVER_NAME") or "127.0.0.1"
    uvicorn.run(app, host=host, port=int(os.getenv("TRACECDS_PORT", "7860")))
