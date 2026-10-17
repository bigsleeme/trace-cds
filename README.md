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

```text
Q: How is exampledrug dosed for kidney function and eGFR?

- According to the exampledrug label (Dosage and Administration (table), Table 1. Dosing by
  kidney function): "eGFR (mL/min): 45 or more, Recommendation: No adjustment; eGFR (mL/min):
  30 to 44, Recommendation: Do not initiate" [S1]
- According to the exampledrug label (Contraindications): "Exampledrug is contraindicated in
  patients with severe renal impairment (eGFR below 30 mL/min)." [S2]

Sources:
  [S1] FDA label: exampledrug | Dosage and Administration (table) | effective 2025-01-15
       https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=...

Non-device CDS checks:
  PASS C1 No analysis of medical images or signals: Text-only input.
  PASS C2 Uses well-understood medical information (FDA labeling): All sources are FDA labels.
  PASS C3 Supports, does not direct, clinical judgment: Statements report labeling; ...
  PASS C4 Basis is available for independent review: Each statement cites a source with ...
```

*(Output from the synthetic test label in `tests/conftest.py`.)*

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

# 4. Summarize with a local open-source LLM instead (same guardrails apply)
#    Install Ollama (https://ollama.com), then:
ollama pull qwen2.5:7b-instruct
tracecds ask "What does the isotretinoin label say about pregnancy?" --llm

# 5. Run the compliance suite (add --baseline to compare the plain LLM)
tracecds eval
tracecds eval --llm --baseline
```

TraceCDS uses only open-source software and models. Web search runs through [SearXNG](https://github.com/searxng/searxng) (AGPL-3.0), a self-hosted metasearch engine that queries Google, Bing, DuckDuckGo, and PubMed from your own server. The LLM generator talks to any OpenAI-compatible server you run yourself (Ollama by default, or vLLM or the llama.cpp server). Recommended models, all Apache-2.0: `qwen2.5:7b-instruct` (default), `olmo2:7b` (fully open weights, data, and code), and `mistral:7b`. Set `TRACECDS_LLM_URL` and `TRACECDS_MODEL` to change them. No question is sent to an outside AI service.

An optional free openFDA API key (`OPENFDA_API_KEY`) raises rate limits. For semantic retrieval, install `pip install -e ".[dense]"` and use `HybridRetriever`.

## Web app

`app.py` is a Gradio interface for quick questions: type a question, get quoted label statements with links to DailyMed, limitations, and the non-device checks.

```bash
pip install gradio
python app.py        # open http://localhost:7860
```

To host it on your own domain with HTTPS and a self-hosted open-source LLM, follow [deploy/SELF_HOSTING.md](deploy/SELF_HOSTING.md). One command (`docker compose up -d`) starts the app, the model server, and automatic HTTPS.

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
| `sources.py` | Fetches labels from openFDA; splits them into section-tagged passages with DailyMed links |
| `tables.py` | Converts label HTML tables to Markdown |
| `chunking.py` | Sentence-aware chunking that never splits a sentence or a decimal |
| `retrieval.py` | Dependency-free BM25; optional hybrid dense retrieval |
| `web.py` | Web search through self-hosted SearXNG; page text extraction |
| `trust.py` | Classifies each source as approved, recognized institution, or not approved |
| `generate.py` | Extractive generator (no model) and LLM generator (self-hosted open-source model) |
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
