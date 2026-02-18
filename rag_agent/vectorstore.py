"""
Vector store factory.

Provides a unified build_vectorstore() that selects the backend automatically:
  - PGVECTOR_CONNECTION_STRING is set  ->  query from RDS PostgreSQL / pgvector
  - Otherwise                          ->  in-memory store (development fallback)

In production the ETL pipeline (etl/glue_etl_job.py) writes embeddings into
RDS.  This module is the *read* side only.
"""

from __future__ import annotations

import json
import os
from typing import Any, List, Optional

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import InMemoryVectorStore, VectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter

from rag_agent.config import CHUNK_SIZE, CHUNK_OVERLAP, load_urls
from rag_agent.models import get_embeddings_model
from rag_agent.loader import load_documents

# ---------------------------------------------------------------------------
# pgvector connection
# ---------------------------------------------------------------------------
PGVECTOR_CONNECTION_STRING = os.getenv("PGVECTOR_CONNECTION_STRING", "")
PGVECTOR_COLLECTION = os.getenv("PGVECTOR_COLLECTION", "documents")


# ---------------------------------------------------------------------------
# Custom pgvector VectorStore (reads directly from the ETL "documents" table)
# ---------------------------------------------------------------------------

class PgVectorStore(VectorStore):
    """Read-only vector store backed by the ETL-populated 'documents' table."""

    def __init__(self, connection_string: str, embedding: Embeddings):
        self._conn_str = connection_string
        self._embedding = embedding

    @property
    def embeddings(self) -> Embeddings:
        return self._embedding

    def _get_conn(self):
        import psycopg
        # Strip SQLAlchemy dialect prefix if present
        conn_str = self._conn_str.replace("postgresql+psycopg://", "postgresql://")
        return psycopg.connect(conn_str)

    def add_texts(self, texts: List[str], metadatas: Optional[List[dict]] = None, **kwargs) -> List[str]:
        raise NotImplementedError("Read-only store. Use the ETL pipeline to ingest data.")

    def similarity_search(self, query: str, k: int = 4, **kwargs) -> List[Document]:
        query_embedding = self._embedding.embed_query(query)
        emb_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

        sql = """
            SELECT content, metadata, 1 - (embedding <=> %s::vector) AS score
            FROM documents
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """

        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (emb_str, emb_str, k))
                rows = cur.fetchall()

        docs = []
        for content, metadata, score in rows:
            meta = metadata if isinstance(metadata, dict) else json.loads(metadata)
            meta["score"] = float(score)
            docs.append(Document(page_content=content, metadata=meta))
        return docs

    @classmethod
    def from_texts(cls, texts, embedding, metadatas=None, **kwargs):
        raise NotImplementedError("Read-only store.")


# ---------------------------------------------------------------------------
# pgvector backend  (reads from RDS populated by the Glue ETL job)
# ---------------------------------------------------------------------------

def _build_pgvector(embeddings) -> VectorStore:
    store = PgVectorStore(
        connection_string=PGVECTOR_CONNECTION_STRING,
        embedding=embeddings,
    )
    # verify connectivity
    with store._get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM documents;")
            count = cur.fetchone()[0]
    print(f"PGVector store connected  table=documents  rows={count}")
    return store


# ---------------------------------------------------------------------------
# In-memory backend  (development -- ingests on every startup)
# ---------------------------------------------------------------------------

def _build_inmemory(embeddings, urls: list[str] | None = None) -> VectorStore:
    urls = urls or load_urls()
    docs_list = load_documents(urls)

    text_splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    doc_splits = text_splitter.split_documents(docs_list)
    print(f"Documents split into {len(doc_splits)} chunks.")

    for idx, d in enumerate(doc_splits):
        d.metadata = d.metadata or {}
        d.metadata["chunk_id"] = str(idx)

    return InMemoryVectorStore.from_documents(documents=doc_splits, embedding=embeddings)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_vectorstore(urls: list[str] | None = None) -> VectorStore:
    """
    Build or connect to the vector store.

    Backend selection:
      - PGVECTOR_CONNECTION_STRING set  ->  pgvector (production, data loaded by Glue ETL)
      - Otherwise                       ->  in-memory (development, loads from urls.txt)
    """
    embeddings = get_embeddings_model()

    if PGVECTOR_CONNECTION_STRING:
        return _build_pgvector(embeddings)
    return _build_inmemory(embeddings, urls)


def build_retriever(urls: list[str] | None = None):
    vs = build_vectorstore(urls=urls)
    return vs.as_retriever()
