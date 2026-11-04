"""Retrieval over label passages.

The default retriever is BM25, implemented here with no dependencies so the
whole pipeline runs offline and is easy to audit. An optional, fully
open-source hybrid pipeline (``pip install -e ".[dense]"``) blends BM25 with
BAAI/bge-m3 dense embeddings and reranks the result with the BAAI/bge-reranker-v2-m3
cross-encoder before generation -- use build_retriever() to get it when
available and fall back to BM25 otherwise.
"""

from __future__ import annotations

import math
from collections import Counter

from .schema import Passage
from .text import content_tokens


class BM25Retriever:
    def __init__(self, passages: list[Passage], k1: float = 1.5, b: float = 0.75) -> None:
        self.passages = passages
        self.k1, self.b = k1, b
        self.docs = [content_tokens(f"{p.drug} {p.section} {p.text}") for p in passages]
        self.doc_len = [len(d) for d in self.docs]
        self.avgdl = (sum(self.doc_len) / len(self.docs)) if self.docs else 0.0
        self.tf = [Counter(d) for d in self.docs]
        df: Counter[str] = Counter()
        for d in self.docs:
            df.update(set(d))
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.drugs = sorted({p.drug for p in passages})

    def mentioned_drugs(self, query: str) -> list[str]:
        q = query.lower()
        return [d for d in self.drugs if d in q]

    def score(self, query: str) -> list[float]:
        q = content_tokens(query)
        scores = []
        for i, tf in enumerate(self.tf):
            s = 0.0
            for t in q:
                if t not in tf:
                    continue
                f = tf[t]
                denom = f + self.k1 * (1 - self.b + self.b * self.doc_len[i] / (self.avgdl or 1))
                s += self.idf.get(t, 0.0) * f * (self.k1 + 1) / denom
            scores.append(s)
        return scores

    def search(self, query: str, k: int = 5) -> list[tuple[Passage, float]]:
        scores = self.score(query)
        drugs = self.mentioned_drugs(query)
        ranked = []
        for p, s in zip(self.passages, scores):
            if drugs and p.drug not in drugs:
                continue  # stay within the drugs the question is about
            if s > 0:
                ranked.append((p, s))
        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked[:k]


class HybridRetriever(BM25Retriever):
    """BM25 blended with dense embeddings (requires sentence-transformers)."""

    def __init__(self, passages: list[Passage], model_name: str = "BAAI/bge-m3",
                 alpha: float = 0.5) -> None:
        super().__init__(passages)
        from sentence_transformers import SentenceTransformer  # optional dependency

        self.alpha = alpha
        self.model = SentenceTransformer(model_name)
        self.emb = self.model.encode([p.text for p in passages], normalize_embeddings=True)

    def score(self, query: str) -> list[float]:
        sparse = super().score(query)
        top = max(sparse) or 1.0
        qv = self.model.encode([query], normalize_embeddings=True)[0]
        dense = (self.emb @ qv).tolist()
        return [self.alpha * (s / top) + (1 - self.alpha) * max(d, 0.0) for s, d in zip(sparse, dense)]


class Reranker:
    """Cross-encoder reranker (requires sentence-transformers)."""

    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3") -> None:
        from sentence_transformers import CrossEncoder  # optional dependency

        self.model = CrossEncoder(model_name)

    def rerank(self, query: str, passages: list[Passage], top_k: int) -> list[tuple[Passage, float]]:
        pairs = [[query, p.text] for p in passages]
        scores = self.model.predict(pairs)
        ranked = sorted(zip(passages, scores), key=lambda x: x[1], reverse=True)
        return ranked[:top_k]


class HybridRerankRetriever(HybridRetriever):
    """Hybrid BM25+dense retrieval, then cross-encoder reranking (frontier RAG pattern).

    Stage 1 pulls a wider candidate pool with the fused BM25/dense score;
    stage 2 reranks that pool with a cross-encoder for the final top k.
    """

    def __init__(self, passages: list[Passage], model_name: str = "BAAI/bge-m3", alpha: float = 0.5,
                 reranker_model: str = "BAAI/bge-reranker-v2-m3", pool_size: int = 20) -> None:
        super().__init__(passages, model_name=model_name, alpha=alpha)
        self.reranker = Reranker(reranker_model)
        self.pool_size = pool_size

    def search(self, query: str, k: int = 5) -> list[tuple[Passage, float]]:
        pool = super().search(query, k=self.pool_size)
        if not pool:
            return pool
        return self.reranker.rerank(query, [p for p, _ in pool], top_k=k)


def build_retriever(passages: list[Passage]) -> BM25Retriever:
    """HybridRerankRetriever if the dense extras are installed, else plain BM25."""
    try:
        return HybridRerankRetriever(passages)
    except ImportError:
        return BM25Retriever(passages)
