-- PostgreSQL 16 + pgvector
-- Run once against the target RDS database to initialise the schema.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id          SERIAL       PRIMARY KEY,
    chunk_id    TEXT         UNIQUE NOT NULL,
    content     TEXT         NOT NULL,
    metadata    JSONB        DEFAULT '{}'::jsonb,
    embedding   vector(768),  -- gemini-embedding-001 with output_dimensionality=768
    created_at  TIMESTAMPTZ  DEFAULT now()
);

-- HNSW index for approximate nearest-neighbour search.
-- HNSW supports >2000 dimensions (required for gemini-embedding-001 at 3072-dim).
CREATE INDEX IF NOT EXISTS idx_documents_embedding
    ON documents USING hnsw (embedding vector_cosine_ops);

-- Fast lookup by source for incremental / dedup logic.
CREATE INDEX IF NOT EXISTS idx_documents_source
    ON documents USING btree ((metadata ->> 'source'));
