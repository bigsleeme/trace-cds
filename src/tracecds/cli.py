"""Command-line interface: tracecds ingest | ask | eval"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import DISCLAIMER, __version__
from .generate import ExtractiveGenerator, LLMGenerator
from .pipeline import TraceCDS, render
from .sources import build_corpus, load_corpus, save_corpus
from .web import WebSearcher

DEFAULT_CORPUS = "data/corpus.jsonl"
DEFAULT_DRUGS = ["metformin", "lisinopril", "atorvastatin", "warfarin", "amoxicillin",
                 "ibuprofen", "sertraline", "isotretinoin", "methotrexate", "doxycycline"]


def _system(args) -> TraceCDS:
    if not os.path.exists(args.corpus):
        sys.exit(f"No corpus at {args.corpus}. Run: tracecds ingest")
    gen = LLMGenerator(base_url=args.llm_url, model=args.model) if args.llm else ExtractiveGenerator()
    web = WebSearcher(searxng_url=getattr(args, "searxng_url", None))
    return TraceCDS(load_corpus(args.corpus), generator=gen, k=args.k, web=web)


def cmd_ingest(args) -> None:
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    passages = build_corpus(args.drugs, api_key=os.getenv("OPENFDA_API_KEY"))
    save_corpus(passages, args.out)
    tables = sum(p.is_table for p in passages)
    print(f"Saved {len(passages)} passages ({tables} tables) for {len(args.drugs)} drugs to {args.out}")


def cmd_ask(args) -> None:
    mode = "web" if args.web else "auto" if args.auto else "labels"
    ans = _system(args).ask(args.question, has_attachment=args.attachment, mode=mode)
    print(json.dumps(ans.to_dict(), indent=2) if args.json else render(ans))
    if not args.json:
        print(f"\n{DISCLAIMER}")


def cmd_eval(args) -> None:
    from .evaluate import evaluate_baseline, evaluate_pipeline, load_suite, to_markdown

    suite = load_suite(args.suite)
    pipe = evaluate_pipeline(_system(args), suite)
    base = evaluate_baseline(LLMGenerator(base_url=args.llm_url, model=args.model), suite) if args.baseline else None
    os.makedirs(args.out_dir, exist_ok=True)
    with open(os.path.join(args.out_dir, "results.json"), "w") as f:
        json.dump({"pipeline": pipe, "baseline": base}, f, indent=2)
    report = to_markdown(pipe, base)
    with open(os.path.join(args.out_dir, "report.md"), "w") as f:
        f.write(report)
    print(report)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="tracecds", description="Traceable, non-device-by-design clinical RAG.")
    ap.add_argument("--version", action="version", version=f"tracecds {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ingest", help="download FDA labels from openFDA and build the corpus")
    p.add_argument("--drugs", nargs="+", default=DEFAULT_DRUGS)
    p.add_argument("--out", default=DEFAULT_CORPUS)
    p.set_defaults(func=cmd_ingest)

    for name, fn, helptext in (("ask", cmd_ask, "ask a question"), ("eval", cmd_eval, "run the compliance suite")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--corpus", default=DEFAULT_CORPUS)
        p.add_argument("--llm", action="store_true", help="summarize with a self-hosted open-source LLM")
        p.add_argument("--llm-url", help="OpenAI-compatible endpoint (default: Ollama at localhost:11434)")
        p.add_argument("--model", help="model name, e.g. qwen2.5:7b-instruct or olmo2:7b")
        p.add_argument("-k", type=int, default=5)
        p.set_defaults(func=fn)
    sub.choices["ask"].add_argument("question")
    sub.choices["ask"].add_argument("--attachment", action="store_true", help="simulate an attached image/signal")
    sub.choices["ask"].add_argument("--json", action="store_true")
    sub.choices["ask"].add_argument("--web", action="store_true", help="answer from a live web search")
    sub.choices["ask"].add_argument("--auto", action="store_true", help="labels first, then web if not covered")
    sub.choices["ask"].add_argument("--searxng-url", help="SearXNG address (default: $SEARXNG_URL or localhost:8888)")
    sub.choices["eval"].add_argument("--suite", default="eval/compliance_suite.jsonl")
    sub.choices["eval"].add_argument("--baseline", action="store_true", help="also test the plain LLM without TraceCDS")
    sub.choices["eval"].add_argument("--out-dir", default="eval/results")

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
