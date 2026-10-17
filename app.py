"""TraceCDS web interface (Gradio). Runs locally or on Hugging Face Spaces.

    python app.py            # then open http://localhost:7860

On first start it downloads FDA labels for the default drug set from openFDA
and caches them in data/corpus.jsonl. If a self-hosted open-source LLM server
is reachable (Ollama by default; see TRACECDS_LLM_URL and TRACECDS_MODEL),
the optional "LLM summary" mode is enabled.
"""

from __future__ import annotations

import html
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import gradio as gr  # noqa: E402

from tracecds import DISCLAIMER, __version__  # noqa: E402
from tracecds.cli import DEFAULT_DRUGS  # noqa: E402
from tracecds.generate import ExtractiveGenerator, LLMGenerator  # noqa: E402
from tracecds.pipeline import TraceCDS  # noqa: E402
from tracecds.schema import Answer  # noqa: E402
from tracecds.sources import build_corpus, load_corpus, save_corpus  # noqa: E402
from tracecds.trust import LABELS  # noqa: E402
from tracecds.web import WebSearcher  # noqa: E402

CORPUS_PATH = os.getenv("TRACECDS_CORPUS", "data/corpus.jsonl")

EXAMPLES = [
    "What are the contraindications for metformin?",
    "FDA approval of a heart valve designed to grow with children",
    "What does the isotretinoin label say about pregnancy?",
    "Which drugs interact with warfarin according to the label?",
    "What does the doxycycline label say about photosensitivity?",
    "What does the sertraline boxed warning say about suicidal thoughts?",
    "What does the methotrexate label say about liver toxicity?",
]


def load_or_build() -> list:
    if not os.path.exists(CORPUS_PATH):
        os.makedirs(os.path.dirname(CORPUS_PATH) or ".", exist_ok=True)
        save_corpus(build_corpus(DEFAULT_DRUGS, api_key=os.getenv("OPENFDA_API_KEY")), CORPUS_PATH)
    return load_corpus(CORPUS_PATH)


PASSAGES = load_or_build()
_WEB = WebSearcher()
WEB_AVAILABLE = _WEB.available()
_LLM = LLMGenerator()
LLM_AVAILABLE = _LLM.available()
EXTRACTIVE = TraceCDS(PASSAGES, web=_WEB if WEB_AVAILABLE else None)
LLM_SYSTEM = TraceCDS(PASSAGES, generator=_LLM, web=_WEB if WEB_AVAILABLE else None) if LLM_AVAILABLE else None

SOURCE_MODES = {"FDA labels, then web": "auto", "FDA labels only": "labels", "Web only": "web"}
DRUG_LIST = ", ".join(sorted({p.drug for p in PASSAGES}))

_CITE = re.compile(r"\[S(\d+)\]")


def _linkify(statement: str, urls: dict[str, str]) -> str:
    text = html.escape(statement)
    return _CITE.sub(lambda m: f'<a class="cite" href="#src-S{m.group(1)}">S{m.group(1)}</a>', text)


def to_html(ans: Answer) -> str:
    status_class = {"answered": "ok", "abstained": "warn", "blocked": "stop"}[ans.status]
    label = {"answered": "Answer from cited sources", "abstained": "No answer",
             "blocked": "Question declined"}[ans.status]
    parts = []
    for w in ans.warnings:
        cls = "stop" if "NOT approved" in w else "warn"
        parts.append(f'<div class="card {cls}"><b>⚠ Source check:</b> {html.escape(w)}</div>')
    parts.append(f'<div class="card {status_class}"><div class="badge">{label}</div>')
    if ans.message:
        parts.append(f"<p>{html.escape(ans.message)}</p>")
    if ans.statements:
        urls = {c.label: c.passage.source_url for c in ans.citations}
        parts.append("<ul>" + "".join(f"<li>{_linkify(s, urls)}</li>" for s in ans.statements) + "</ul>")
    parts.append("</div>")

    if ans.citations:
        parts.append('<div class="card"><h4>Sources: check the original wording</h4><ol class="srcs">')
        for c in ans.citations:
            p = c.passage
            date_txt = f" · label effective {html.escape(p.effective_date)}" if p.effective_date else ""
            where = "Open on DailyMed ↗" if p.drug else f"Open {html.escape(p.publisher)} ↗"
            parts.append(
                f'<li id="src-{c.label}"><b>{c.label}</b> <span class="trust {p.trust}">{LABELS[p.trust]}</span><br>'
                f'{html.escape(p.source_title if p.section == p.source_title else p.source_title + " · " + p.section)}'
                f'{date_txt}<br>'
                f'<a href="{html.escape(p.source_url)}" target="_blank" rel="noopener">{where}</a></li>')
        parts.append("</ol></div>")

    if ans.limitations:
        parts.append('<div class="card muted"><h4>Limitations</h4><ul>'
                     + "".join(f"<li>{html.escape(n)}</li>" for n in ans.limitations) + "</ul></div>")

    rows = "".join(
        f'<tr><td>{"✅" if c.passed else "⚠️"}</td><td>C{c.criterion}. {html.escape(c.name)}</td>'
        f"<td>{html.escape(c.detail)}</td></tr>" for c in ans.criteria)
    parts.append(f'<details class="card muted"><summary>FDA non-device CDS checks</summary>'
                 f"<table>{rows}</table></details>")

    if ans.removed_statements:
        items = "".join(f"<li><i>{html.escape(r['reason'])}</i>: {html.escape(r['statement'])}</li>"
                        for r in ans.removed_statements)
        parts.append(f'<details class="card muted"><summary>{len(ans.removed_statements)} unverified '
                     f"statement(s) removed</summary><ul>{items}</ul></details>")
    return "\n".join(parts)


def ask(question: str, mode: str, sources: str = "FDA labels only") -> str:
    question = (question or "").strip()
    if not question:
        return '<div class="card warn">Type a healthcare question.</div>'
    system = LLM_SYSTEM if (mode.startswith("LLM summary") and LLM_SYSTEM) else EXTRACTIVE
    return to_html(system.ask(question[:500], mode=SOURCE_MODES.get(sources, "labels")))


CSS = """
:root { --ok:#1f7a4d; --warn:#9a6700; --stop:#b42318; }
.gradio-container { max-width: 860px !important; margin: auto; }
.banner { border:1px solid var(--warn); border-radius:10px; padding:10px 14px; font-size:0.92em; }
.card { border:1px solid var(--border-color-primary); border-radius:10px; padding:12px 16px; margin:10px 0; }
.card.ok { border-left:5px solid var(--ok); } .card.warn { border-left:5px solid var(--warn); }
.card.stop { border-left:5px solid var(--stop); } .card.muted { font-size:0.92em; }
.badge { font-weight:700; margin-bottom:6px; }
.card li { margin:6px 0; line-height:1.45; } .card table td { padding:4px 8px; vertical-align:top; }
a.cite { font-size:0.8em; font-weight:700; padding:1px 6px; border-radius:6px; text-decoration:none;
         border:1px solid currentColor; margin-left:2px; }
.srcs li { margin:8px 0; }
.trust { font-size:0.78em; font-weight:700; padding:1px 7px; border-radius:6px; }
.trust.approved { color:var(--ok); border:1px solid var(--ok); }
.trust.reputable { color:var(--warn); border:1px solid var(--warn); }
.trust.unverified { color:var(--stop); border:1px solid var(--stop); }
"""

with gr.Blocks(title="TraceCDS: traceable drug-label answers", analytics_enabled=False) as demo:
    gr.Markdown(f"# TraceCDS\nQuick, sourced answers to healthcare questions. Every statement links to its "
                f"source, and every source is checked: approved healthcare sources are marked, and anything "
                f"else is clearly flagged. v{__version__}")
    gr.HTML(f'<div class="banner"><b>Research prototype. Not for clinical use. Not a medical device.</b> '
            f"{html.escape(DISCLAIMER)} Do not enter patient names, dates of birth, record numbers, or "
            f"other identifiers. Not for emergencies.</div>")
    with gr.Row():
        question = gr.Textbox(label="Your question", placeholder="e.g. What are the contraindications for metformin?",
                              lines=2, max_lines=4, scale=4)
    with gr.Row():
        mode = gr.Radio(["Quoted from label", f"LLM summary ({_LLM.model})"] if LLM_AVAILABLE
                        else ["Quoted from label"],
                        value="Quoted from label", label="Answer style", scale=3)
        sources = gr.Radio(list(SOURCE_MODES) if WEB_AVAILABLE else ["FDA labels only"],
                           value="FDA labels, then web" if WEB_AVAILABLE else "FDA labels only",
                           label="Where to look", scale=3)
        submit = gr.Button("Ask", variant="primary", scale=1)
    output = gr.HTML()
    gr.Examples(EXAMPLES, inputs=question)
    gr.Markdown(f"**FDA labels indexed:** {DRUG_LIST}. "
                + ("Other questions are answered from a live web search, with every source trust-checked.  \n"
                   if WEB_AVAILABLE else "Web search is off on this server.  \n")
                + "Source code and method: [github.com/bigsleeme/trace-cds]"
                "(https://github.com/bigsleeme/trace-cds)")
    submit.click(ask, [question, mode, sources], output)
    question.submit(ask, [question, mode, sources], output)

if __name__ == "__main__":
    demo.launch(css=CSS, server_name=os.getenv("GRADIO_SERVER_NAME"), footer_links=[])
