# TraceCDS

**Traceable, source-checked answers to healthcare questions, built to stay within FDA's non-device clinical decision support criteria.**

Live demo: **https://tracecds.com**

> **Research use only. Not for clinical use. Not a medical device.** TraceCDS is a research prototype. It does not provide medical advice and is not a substitute for professional judgment.

Large language models give fluent answers to clinical questions, but clinicians can't easily tell which parts are grounded in an authoritative source and which are invented. FDA's criteria for non-device clinical decision support (CDS) require that software *support* a healthcare professional's judgment rather than direct it, and let the professional *independently review the basis* for what it says. Research has shown that instructing an LLM to follow these criteria in a prompt is not enough.

TraceCDS answers from FDA drug labeling first and, when the labels don't cover a question, from a live web search. **Every source is trust-checked**: approved healthcare sources (FDA, CDC, NIH and PubMed, WHO, major peer-reviewed journals, national medical societies) are marked as approved; recognized medical institutions are marked as such; and anything else is used only with a clear warning that it is not an approved healthcare source. Non-device criteria are enforced **in code, on every statement**:

- **Every statement cites its source** (label section, DailyMed link, and label effective date).
- **Every number must appear in the cited source.** A dose that isn't in the label is removed.
- **Directive statements are removed.** "Give 500 mg" fails; "The label states the starting dose is 500 mg [S1]" passes.
- **Time-critical, image-based, and identifiable-patient questions are declined** before any retrieval.
- **Sources are ranked by trust before use**, and any statement from a non-approved source is flagged in the answer.
- **When nothing can be verified, it abstains** instead of guessing.
- **Label tables are preserved.** Dosing tables are converted from HTML to Markdown and quoted row by row with their column headers.

Every answer includes an audit trail: which statements were removed and why, and how each of FDA's four criteria was handled. See [docs/fda_cds_mapping.md](docs/fda_cds_mapping.md).

## Example

Real output from `tracecds ask "What are the contraindications for metformin?"`
(extractive mode — every statement quoted verbatim from the live FDA label, no model):

```text
Q: What are the contraindications for metformin?

- According to the metformin label (Contraindications): "Metformin hydrochloride
  extended-release tablets are contraindicated in patients with: Severe renal impairment
  (eGFR below 30 mL/min/1.73 m2) [see Warnings and Precautions (5.1)]. Hypersensitivity to
  metformin. Acute or chronic metabolic acidosis, including diabetic ketoacidosis, with or
  without coma." [S1]
- According to the metformin label (Use in Specific Populations): "Metformin hydrochloride
  extended-release tablets are contraindicated in severe renal impairment, patients with an
  estimated glomerular filtration rate (eGFR) below 30 mL/min/1.73 m2 ..." [S2]

Sources:
  [S1] APPROVED HEALTHCARE SOURCE: FDA label: metformin | Contraindications | effective 2026-09-09
       https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=05999192-ebc6-4198-bd1e-f46abbfb4f8a
  [S2] APPROVED HEALTHCARE SOURCE: FDA label: metformin | Use in Specific Populations | effective 2026-09-09
       https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=05999192-ebc6-4198-bd1e-f46abbfb4f8a

Checks:
  PASS C1 No analysis of medical images or signals: Text-only input.
  PASS C2 Uses well-understood, authoritative medical sources: All sources are approved healthcare sources.
  PASS C3 Supports, does not direct, clinical judgment: Statements report what sources say; directive statements removed.
  PASS C4 Basis is available for independent review: Each statement cites a source with a link the clinician can open.
```

## Measured compliance results

Running the 31-question suite against the plain LLM and against TraceCDS (same model,
same questions) on **2026-11-03**:

| Metric | Plain LLM (FDA criteria in prompt) | TraceCDS |
| --- | --- | --- |
| Directive statements in final answers | 13 of 221 sentences (6%) | **0** |
| Citation coverage | 0% | **100%** |
| Behaves as expected | — | 94% (29/31) |

The same model told in its prompt to follow FDA's criteria still produced directive
clinical statements and cited nothing; routed through TraceCDS, directive statements are
removed before the answer is returned and every statement cites an authoritative source.
Full report, per-category breakdown, and the two questions TraceCDS did **not** yet handle
as expected: [docs/compliance_results.md](docs/compliance_results.md).

## Quick start

Requires Python 3.10+. The core has no third-party dependencies.

```bash
git clone https://github.com/bigsleeme/trace-cds.git
cd trace-cds
pip install -e ".[dev]"

# 1. Download FDA labels for the default drug set from openFDA
tracecds ingest
#    or choose drugs:  tracecds ingest --drugs metformin warfarin isotretinoin

# 2. Ask a question (extractive mode: no API key needed)
tracecds ask "What are the contraindications for metformin?"

# 3. Questions beyond the labels: live web search through self-hosted SearXNG
docker run -d -p 8888:8080 -v "$(pwd)/deploy/searxng:/etc/searxng" searxng/searxng
tracecds ask "FDA approval of a heart valve designed to grow with children" --auto

# 4. Write answers with an LLM instead of quoting (same guardrails apply).
#    Point at any OpenAI-compatible endpoint -- a hosted API:
export TRACECDS_LLM_URL="https://api.deepinfra.com/v1/openai"
export TRACECDS_MODEL="nvidia/NVIDIA-Nemotron-3.5-Super-VL"
export TRACECDS_LLM_API_KEY="your-deepinfra-key"
#    ...or a self-hosted server (e.g. Ollama: ollama pull qwen2.5:7b-instruct,
#    then TRACECDS_LLM_URL=http://localhost:11434/v1 TRACECDS_MODEL=qwen2.5:7b-instruct).
tracecds ask "What does the isotretinoin label say about pregnancy?" --llm

# 5. Run the compliance suite (add --baseline to compare the plain LLM)
tracecds eval
tracecds eval --llm --baseline
```

Retrieval, source trust-checking, and the guardrails run in open-source code. Web search runs through [SearXNG](https://github.com/searxng/searxng) (AGPL-3.0), a self-hosted metasearch engine that queries Google, Bing, DuckDuckGo, and PubMed from your own server. Retrieval is BM25 by default and, with `pip install -e ".[dense]"`, hybrid BM25 + [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) (MIT) dense retrieval reranked by [BAAI/bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3) (Apache-2.0) — use `retrieval.build_retriever()` to get the best available option automatically.

The LLM generator talks to any OpenAI-compatible endpoint, set via `TRACECDS_LLM_URL`, `TRACECDS_MODEL`, and (for a hosted API) `TRACECDS_LLM_API_KEY`. The reference deployment uses NVIDIA Nemotron (an open-weight model) served through the [DeepInfra](https://deepinfra.com) API for fast answers — in that configuration your question is sent to DeepInfra to generate the answer, though every statement it returns is still verified against the cited sources first. Point the same variables at a self-hosted server (Ollama, vLLM, or the llama.cpp server) instead to keep generation on your own infrastructure; the "Quoted from label" mode uses no model at all and never leaves your server.

An optional free openFDA API key (`OPENFDA_API_KEY`) raises rate limits. For semantic retrieval, install `pip install -e ".[dense]"` and use `HybridRetriever`.

## Web app

`app.py` is a FastAPI service: a custom chat interface at `/`, plus the developer API below. Ask a question and get source-checked statements (written by the LLM, or quoted verbatim) with links to DailyMed, limitations, and the non-device checks.

```bash
python app.py        # open http://localhost:7860
```

`site/index.html` is a static marketing homepage with a "Use TraceCDS" button that links to the chat app — no build step, open it directly in a browser.

To host it on your own domain with HTTPS, follow [deploy/SELF_HOSTING.md](deploy/SELF_HOSTING.md).

## API

The same service exposes a key-protected JSON API under `/v1`. Interactive docs are at `/v1/docs` (Swagger) and `/v1/redoc`; the live deployment serves it at `https://api.tracecds.com`.

Authenticate with an API key in the `Authorization` header (or `X-API-Key`). Keys are configured via the `TRACECDS_API_KEYS` environment variable (comma-separated) and are never stored in the repo.

| Endpoint | Auth | Purpose |
| --- | --- | --- |
| `GET /v1/health` | none | Liveness check |
| `GET /v1/info` | key | Capabilities: answer modes, source modes, indexed drugs |
| `POST /v1/ask` | key | Ask a question; returns structured, source-checked JSON |
| `POST /v1/interactions` | key | Check drug–drug interactions across 2+ drugs from their labels |

```bash
curl https://api.tracecds.com/v1/ask \
  -H "Authorization: Bearer $TRACECDS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"question": "What are the contraindications for metformin?"}'
```

A common set of drugs is pre-indexed for speed; any **other** drug is looked up live from openFDA on demand (and then cached), so the service effectively covers every drug openFDA has, not just the pre-indexed set.

`POST /v1/ask` accepts `question` (required), optional `answer_mode` and `source_mode`, and an optional `history` array of prior questions so follow-ups resolve references ("what is its dose?"). The response contains `status`, the `statements` (each citing its source), `citations` (with the verified source `text`, `trust` tier, DailyMed `source_url`, and `effective_date`), the four FDA non-device CDS `criteria` results, `limitations`, `warnings`, and any `removed_statements` that failed verification.

`POST /v1/interactions` takes `drugs` (two or more generic names) and reports what their FDA labels say about interactions among them — surfacing passages in one drug's label that name another of the drugs first. Same verified, cited response shape as `/v1/ask`. The chat also auto-detects interaction questions ("does X interact with Y", "can I take X with Y").

```bash
curl https://api.tracecds.com/v1/interactions \
  -H "Authorization: Bearer $TRACECDS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"drugs": ["clopidogrel", "omeprazole"]}'
```

To run the full stack (homepage, chat, API, HTTPS) with Docker, see [deploy/SELF_HOSTING.md](deploy/SELF_HOSTING.md).

## How it works

```text
question ──► input screen ──► retrieve (BM25 over label passages) ──► generate ──► verify each statement ──► answer + audit trail
             │ images/signals: decline                                │ extractive quotes, or LLM summary
             │ patient identifiers: decline                           │
             │ time-critical: decline                                 └─ failed statements removed and logged;
             └ outside indexed labels: abstain                           if none pass, fall back to quotes or abstain
```

| Module | Purpose |
| --- | --- |
| `sources.py` | Fetches labels from openFDA (a common set is pre-indexed; any other drug is looked up live on demand); splits them into section-tagged passages with DailyMed links |
| `tables.py` | Converts label HTML tables to Markdown |
| `chunking.py` | Sentence-aware chunking that never splits a sentence or a decimal |
| `retrieval.py` | Dependency-free BM25; optional hybrid dense retrieval (BAAI/bge-m3) with cross-encoder reranking (BAAI/bge-reranker-v2-m3) |
| `web.py` | Web search through self-hosted SearXNG; page text extraction |
| `trust.py` | Classifies each source as approved, recognized institution, or not approved |
| `generate.py` | Extractive generator (no model) and LLM generator (open-weight model via a hosted or self-hosted OpenAI-compatible endpoint) |
| `guardrails.py` | Input screening and per-statement verification |
| `pipeline.py` | Orchestration, limitations, and the criteria report |
| `evaluate.py` | Compliance suite runner and report |

## Compliance suite

`eval/compliance_suite.jsonl` holds 31 questions in six categories: informational, directive-seeking, time-critical, identifiable-patient, image or signal, and out-of-scope. It includes dermatology drugs (isotretinoin, methotrexate, doxycycline). The suite reports how often TraceCDS behaves as expected, citation coverage, and how many directive statements the guardrails removed. With `--baseline`, it also sends the same questions to a plain LLM given FDA's criteria in its prompt, and measures how often that LLM produces directive sentences.

Results depend on the label versions downloaded and the model used, so run the suite yourself; reports are written to `eval/results/`.

## Related work

- **MedRAG and MIRAGE** (Xiong et al., 2024): a toolkit and benchmark for medical RAG across corpora, retrievers, and LLMs.
- **MedCite**: a framework for generating and evaluating citations in medical LLM answers.
- **"Unregulated large language models produce medical device-like output"** (*npj Digital Medicine*, 2025): shows prompts based on FDA guidance do not reliably keep LLM output within non-device CDS.

TraceCDS differs in its goal: it treats FDA's non-device criteria as testable requirements, enforces them in code on every statement, and ships a suite to measure compliance.

This project builds on the author's prior research comparing a RAG question-answering system with a standard LLM, evaluated by health professionals: E. Balogun, H. Wimmer, and C. Rebman Jr., "A Comparative Analysis of an LLM and RAG (Retrieval Augmented Generation) in a Question and Answer System," *Journal of Information Systems Applied Research and Analytics*, vol. 19, no. 2, pp. 36–49, 2026.

## Data and license

FDA drug labeling is obtained from [openFDA](https://open.fda.gov/) and linked to [DailyMed](https://dailymed.nlm.nih.gov/). Labels are downloaded at run time and are not stored in this repository.

Code is licensed under the [Apache License 2.0](LICENSE). See [CITATION.cff](CITATION.cff) to cite this project.
