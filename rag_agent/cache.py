"""
Semantic cache for the RAG agent.

Stores previous query-answer pairs and checks incoming queries against them
using cosine similarity on embeddings.  When a sufficiently similar query is
found the cached answer is returned directly, avoiding redundant LLM calls
and cutting latency.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np


@dataclass
class CacheEntry:
    query: str
    answer: str
    citations: list
    embedding: np.ndarray
    created_at: float = field(default_factory=time.time)
    hit_count: int = 0


class SemanticCache:
    """Embedding-based semantic cache with cosine-similarity lookup."""

    def __init__(
        self,
        embeddings_model=None,
        similarity_threshold: float = 0.92,
        max_entries: int = 2048,
        ttl_seconds: float = 3600.0,
    ):
        self._embed = embeddings_model
        self.threshold = similarity_threshold
        self.max_entries = max_entries
        self.ttl = ttl_seconds
        self._store: Dict[str, CacheEntry] = {}

    def get(self, query: str) -> Optional[Tuple[str, list]]:
        """Return (answer, citations) on hit, or None on miss."""
        if not self._store:
            return None

        q_vec = self._get_embedding(query)
        self._evict_expired()

        best_key: Optional[str] = None
        best_sim: float = -1.0

        for key, entry in self._store.items():
            sim = self._cosine_similarity(q_vec, entry.embedding)
            if sim > best_sim:
                best_sim = sim
                best_key = key

        if best_key is not None and best_sim >= self.threshold:
            entry = self._store[best_key]
            entry.hit_count += 1
            return entry.answer, entry.citations

        return None

    def put(self, query: str, answer: str, citations: list | None = None) -> None:
        q_vec = self._get_embedding(query)
        key = self._make_key(query)
        self._store[key] = CacheEntry(
            query=query,
            answer=answer,
            citations=citations or [],
            embedding=q_vec,
        )
        self._enforce_capacity()

    def invalidate(self, query: str) -> bool:
        key = self._make_key(query)
        return self._store.pop(key, None) is not None

    def clear(self) -> None:
        self._store.clear()

    @property
    def size(self) -> int:
        return len(self._store)

    # -- internals --

    def _get_embedding(self, text: str) -> np.ndarray:
        raw = self._embed.embed_query(text)
        return np.asarray(raw, dtype=np.float32)

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        denom = np.linalg.norm(a) * np.linalg.norm(b)
        if denom == 0:
            return 0.0
        return float(np.dot(a, b) / denom)

    @staticmethod
    def _make_key(query: str) -> str:
        return hashlib.sha256(query.strip().lower().encode()).hexdigest()

    def _evict_expired(self) -> None:
        now = time.time()
        expired = [k for k, v in self._store.items() if now - v.created_at > self.ttl]
        for k in expired:
            del self._store[k]

    def _enforce_capacity(self) -> None:
        while len(self._store) > self.max_entries:
            oldest_key = min(self._store, key=lambda k: self._store[k].created_at)
            del self._store[oldest_key]
