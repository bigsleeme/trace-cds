"""Tests for the optional hybrid + reranking retrieval path.

The real production models (BAAI/bge-m3, BAAI/bge-reranker-v2-m3) are multi-GB
downloads, so tests that need sentence-transformers use small stand-in models
to exercise the same code paths quickly. These are skipped where the `dense`
extra isn't installed (e.g. the default CI job, which only installs `[dev]`).
"""

import builtins

import pytest

from tracecds.retrieval import BM25Retriever, build_retriever


def test_build_retriever_falls_back_without_dense(monkeypatch, passages):
    """build_retriever() must degrade to BM25 if sentence-transformers is unavailable,
    regardless of whether it's actually installed in this environment."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "sentence_transformers":
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    retriever = build_retriever(passages)
    assert isinstance(retriever, BM25Retriever)


def test_hybrid_retriever_finds_relevant_passage(passages):
    pytest.importorskip("sentence_transformers")
    from tracecds.retrieval import HybridRetriever

    r = HybridRetriever(passages, model_name="sentence-transformers/all-MiniLM-L6-v2")
    hits = r.search("What are the contraindications for exampledrug?", k=3)
    assert hits
    assert any("contraindicat" in p.text.lower() for p, _ in hits)


def test_reranker_orders_candidates(passages):
    pytest.importorskip("sentence_transformers")
    from tracecds.retrieval import Reranker

    rr = Reranker(model_name="cross-encoder/ms-marco-MiniLM-L-6-v2")
    ranked = rr.rerank("contraindications for exampledrug", passages, top_k=2)
    assert len(ranked) == 2
    assert ranked[0][1] >= ranked[1][1]


def test_hybrid_rerank_retriever_returns_up_to_k(passages):
    pytest.importorskip("sentence_transformers")
    from tracecds.retrieval import HybridRerankRetriever

    r = HybridRerankRetriever(passages, model_name="sentence-transformers/all-MiniLM-L6-v2",
                              reranker_model="cross-encoder/ms-marco-MiniLM-L-6-v2", pool_size=5)
    hits = r.search("What is the starting dose of exampledrug?", k=2)
    assert hits and len(hits) <= 2
