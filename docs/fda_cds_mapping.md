# How TraceCDS maps to FDA's non-device CDS criteria

Section 520(o)(1)(E) of the Federal Food, Drug, and Cosmetic Act excludes certain clinical decision support (CDS) software functions from the definition of a medical device when all four criteria below are met. FDA explains its current interpretation in the guidance *Clinical Decision Support Software* (January 2026). This project is a research prototype; this mapping describes design intent, not a regulatory determination.

| Criterion | What it requires | How TraceCDS addresses it | Where in the code |
| --- | --- | --- | --- |
| 1 | Not intended to acquire, process, or analyze a medical image, signal, or pattern | Questions with attachments, or asking to read an image, scan, tracing, or photo, are declined before retrieval | `guardrails.check_input` |
| 2 | Intended to display, analyze, or print medical information from well-understood sources | FDA drug labeling is searched first. Web sources are classified as approved (government health agencies, NLM, peer-reviewed journals, national medical societies), recognized institution, or not approved. Answers that use any non-approved source are flagged to the user, and this criterion is marked FLAG rather than PASS | `sources.py`, `trust.py`, `pipeline._trust_warnings` |
| 3 | Intended to support or provide recommendations to a healthcare professional, not replace or direct their judgment | Every generated statement is checked in code for directive language (orders, first-person recommendations, definitive diagnoses). Directive statements are removed, and patient-specific questions get a note that labeling is general | `guardrails.find_directive`, `pipeline._limitations` |
| 4 | Intended to let the healthcare professional independently review the basis for the recommendation | Every statement must cite a numbered source; every number in it must appear in that source; most of its words must be supported by that source. Each source shows its DailyMed link, label section, and effective date. Time-critical questions are declined | `guardrails.check_statement`, `pipeline.render` |

## Why checks run in code

A 2025 study in *npj Digital Medicine* ("Unregulated large language models produce medical device-like output") found that prompts built from FDA guidance language did not reliably keep LLM output within non-device decision support. TraceCDS therefore treats the prompt as a request, not a control: the same checks run on every statement from every generator, and a statement that fails is removed and logged in `removed_statements`.

## Known limitations

- Directive detection is rule-based. It catches common phrasings and is tested, but it is not exhaustive.
- The support check uses word overlap, not semantic entailment. A statement can reuse source words and still misstate their meaning. Clinician review of the cited source remains essential.
- Time-critical detection relies on keywords plus context cues and can miss unusual phrasings.
- FDA labeling is one source. It may lag newer evidence and does not cover off-label use.
