"""
AWS Glue Python Shell ETL job.

Pipeline:  S3 (raw documents)  -->  parse / chunk / embed  -->  RDS PostgreSQL + pgvector

Usage on Glue console:
    Type            : Python Shell
    Python version  : 3.9
    Script location : s3://<bucket>/glue-scripts/glue_etl_job.py
    Job parameters  :
        --S3_BUCKET          source bucket name
        --S3_PREFIX          key prefix to process (default: "raw/")
        --DB_HOST            RDS endpoint
        --DB_PORT            (default 5432)
        --DB_NAME            database name
        --DB_USER            database user
        --DB_PASSWORD        database password  (or use --DB_SECRET_ARN)
        --DB_SECRET_ARN      Secrets Manager ARN (overrides user/password)
        --GOOGLE_API_KEY     Google AI Studio key
        --CHUNK_SIZE         (default 1024)
        --CHUNK_OVERLAP      (default 50)
    Additional python modules (--additional-python-modules):
        pypdf,beautifulsoup4,google-generativeai,pg8000

This script is intentionally self-contained so it can run inside the Glue
Python Shell runtime without importing the rag_agent package.  For local
development, use etl/local_runner.py which calls the same functions.
"""

from __future__ import annotations

import io
import json
import hashlib
import sys
import os
import time
import logging
from typing import Any, Dict, List, Optional, Tuple

import boto3

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("glue_etl")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
EMBEDDING_MODEL = "models/gemini-embedding-001"
EMBEDDING_DIM = 768  # reduced via output_dimensionality (pgvector index limit: 2000)

# ---------------------------------------------------------------------------
# Argument parsing (Glue-compatible)
# ---------------------------------------------------------------------------

def _parse_args() -> Dict[str, str]:
    """Parse --key value pairs from sys.argv (Glue convention)."""
    args: Dict[str, str] = {}
    i = 0
    while i < len(sys.argv):
        if sys.argv[i].startswith("--"):
            key = sys.argv[i][2:]
            val = sys.argv[i + 1] if i + 1 < len(sys.argv) else ""
            args[key] = val
            i += 2
        else:
            i += 1
    return args


def _get(args: dict, key: str, default: str = "") -> str:
    return args.get(key, os.getenv(key, default))


# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------

def list_s3_objects(bucket: str, prefix: str) -> List[Dict[str, Any]]:
    s3 = boto3.client("s3")
    objects: List[Dict[str, Any]] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/"):
                continue
            objects.append(obj)
    return objects


def download_s3_bytes(bucket: str, key: str) -> bytes:
    s3 = boto3.client("s3")
    resp = s3.get_object(Bucket=bucket, Key=key)
    return resp["Body"].read()


# ---------------------------------------------------------------------------
# Document parsing  (mirrors rag_agent/loader.py logic, no langchain dep)
# ---------------------------------------------------------------------------

def parse_pdf(data: bytes, source: str) -> List[Dict[str, Any]]:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    docs = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            docs.append({
                "content": text,
                "metadata": {"source": source, "page": i},
            })
    return docs


def parse_html(data: bytes, source: str) -> List[Dict[str, Any]]:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(data, "html.parser")
    # remove script / style tags
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    if text.strip():
        return [{"content": text, "metadata": {"source": source, "title": title}}]
    return []


def parse_text(data: bytes, source: str) -> List[Dict[str, Any]]:
    text = data.decode("utf-8", errors="ignore")
    if text.strip():
        return [{"content": text, "metadata": {"source": source}}]
    return []


def parse_document(data: bytes, key: str) -> List[Dict[str, Any]]:
    """Route to the correct parser based on file extension."""
    lower = key.lower()
    source = f"s3://{key}"
    if lower.endswith(".pdf"):
        return parse_pdf(data, source)
    if lower.endswith((".html", ".htm")):
        return parse_html(data, source)
    # fallback: plain text / markdown / etc.
    return parse_text(data, source)


# ---------------------------------------------------------------------------
# Chunking  (character-based, pure Python -- no native dependencies)
# ---------------------------------------------------------------------------

def chunk_text(text: str, chunk_size: int = 1024, chunk_overlap: int = 50) -> List[str]:
    """Split text into overlapping chunks by character count.

    Uses character length as the size metric to avoid requiring tiktoken
    (which needs a Rust toolchain unavailable in Glue Python Shell).
    """
    if len(text) <= chunk_size:
        return [text] if text.strip() else []

    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk)
        start += chunk_size - chunk_overlap

    return chunks


def split_documents(
    docs: List[Dict[str, Any]],
    chunk_size: int = 1024,
    chunk_overlap: int = 50,
) -> List[Dict[str, Any]]:
    """Split parsed documents into smaller chunks with stable IDs."""
    splits: List[Dict[str, Any]] = []
    for doc in docs:
        text = doc["content"]
        meta = doc["metadata"]
        chunks = chunk_text(text, chunk_size, chunk_overlap)
        for idx, chunk in enumerate(chunks):
            chunk_id = hashlib.sha256(
                f"{meta.get('source', '')}:{meta.get('page', '')}:{idx}".encode()
            ).hexdigest()[:16]

            splits.append({
                "chunk_id": chunk_id,
                "content": chunk,
                "metadata": {**meta, "chunk_index": idx},
            })
    return splits


# ---------------------------------------------------------------------------
# Embedding generation  (Google Generative AI -- lightweight, no langchain)
# ---------------------------------------------------------------------------

def generate_embeddings(
    texts: List[str],
    api_key: str,
    model: str = EMBEDDING_MODEL,
    batch_size: int = 20,
    max_retries: int = 3,
) -> List[List[float]]:
    """Call the Google Generative AI embedding endpoint in batches."""
    import google.generativeai as genai
    genai.configure(api_key=api_key)

    all_embeddings: List[List[float]] = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        for attempt in range(1, max_retries + 1):
            try:
                result = genai.embed_content(
                    model=model,
                    content=batch,
                    task_type="retrieval_document",
                    output_dimensionality=EMBEDDING_DIM,
                )
                all_embeddings.extend(result["embedding"])
                break
            except Exception as e:
                logger.warning("Embedding batch %d attempt %d failed: %s", i, attempt, e)
                if attempt == max_retries:
                    raise
                time.sleep(2 ** attempt)

    return all_embeddings


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------

def _get_db_connection(args: dict):
    import pg8000.native

    secret_arn = _get(args, "DB_SECRET_ARN")
    if secret_arn:
        sm = boto3.client("secretsmanager")
        secret = json.loads(sm.get_secret_value(SecretId=secret_arn)["SecretString"])
        host = secret["host"]
        port = int(secret.get("port", 5432))
        dbname = secret.get("dbname", _get(args, "DB_NAME", "ragdb"))
        user = secret["username"]
        password = secret["password"]
    else:
        host = _get(args, "DB_HOST", "localhost")
        port = int(_get(args, "DB_PORT", "5432"))
        dbname = _get(args, "DB_NAME", "ragdb")
        user = _get(args, "DB_USER", "postgres")
        password = _get(args, "DB_PASSWORD", "")

    import ssl
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    return pg8000.native.Connection(
        host=host, port=port, database=dbname, user=user, password=password,
        ssl_context=ssl_context,
    )


def ensure_schema(conn) -> None:
    """Create the pgvector extension and documents table if they don't exist."""
    conn.run("CREATE EXTENSION IF NOT EXISTS vector;")
    conn.run(f"""
        CREATE TABLE IF NOT EXISTS documents (
            id          SERIAL       PRIMARY KEY,
            chunk_id    TEXT         UNIQUE NOT NULL,
            content     TEXT         NOT NULL,
            metadata    JSONB        DEFAULT '{{}}'::jsonb,
            embedding   vector({EMBEDDING_DIM}),
            created_at  TIMESTAMPTZ  DEFAULT now()
        );
    """)
    conn.run("""
        CREATE INDEX IF NOT EXISTS idx_documents_embedding
            ON documents USING hnsw (embedding vector_cosine_ops);
    """)
    conn.run("""
        CREATE INDEX IF NOT EXISTS idx_documents_source
            ON documents USING btree ((metadata ->> 'source'));
    """)
    logger.info("Schema ensured.")


def upsert_chunks(
    conn,
    chunks: List[Dict[str, Any]],
    embeddings: List[List[float]],
) -> int:
    """Insert chunks into RDS; skip duplicates by chunk_id."""
    inserted = 0
    for chunk, emb in zip(chunks, embeddings):
        emb_str = "[" + ",".join(str(v) for v in emb) + "]"
        result = conn.run(
            """
            INSERT INTO documents (chunk_id, content, metadata, embedding)
            VALUES (:cid, :content, :meta::jsonb, :emb::vector)
            ON CONFLICT (chunk_id) DO NOTHING
            """,
            cid=chunk["chunk_id"],
            content=chunk["content"],
            meta=json.dumps(chunk["metadata"]),
            emb=emb_str,
        )
        inserted += conn.row_count
    return inserted


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_pipeline(args: dict) -> Dict[str, Any]:
    """Execute the full ETL pipeline.  Returns a summary dict."""

    bucket = _get(args, "S3_BUCKET")
    prefix = _get(args, "S3_PREFIX", "raw/")
    api_key = _get(args, "GOOGLE_API_KEY")
    chunk_size = int(_get(args, "CHUNK_SIZE", "1024"))
    chunk_overlap = int(_get(args, "CHUNK_OVERLAP", "50"))

    if not bucket:
        raise ValueError("S3_BUCKET is required.")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY is required.")

    # ---- Extract ----
    logger.info("Listing objects in s3://%s/%s ...", bucket, prefix)
    objects = list_s3_objects(bucket, prefix)
    logger.info("Found %d objects.", len(objects))

    if not objects:
        return {"files": 0, "chunks": 0, "inserted": 0}

    # ---- Transform: parse + chunk ----
    all_chunks: List[Dict[str, Any]] = []
    for obj in objects:
        key = obj["Key"]
        logger.info("Processing %s  (%d bytes)", key, obj.get("Size", 0))
        data = download_s3_bytes(bucket, key)
        docs = parse_document(data, key)
        chunks = split_documents(docs, chunk_size, chunk_overlap)
        all_chunks.extend(chunks)
        logger.info("  -> %d chunks", len(chunks))

    logger.info("Total chunks: %d", len(all_chunks))

    if not all_chunks:
        return {"files": len(objects), "chunks": 0, "inserted": 0}

    # ---- Transform: embed ----
    logger.info("Generating embeddings ...")
    texts = [c["content"] for c in all_chunks]
    embeddings = generate_embeddings(texts, api_key)
    logger.info("Embeddings generated: %d vectors of dim %d", len(embeddings), len(embeddings[0]))

    # ---- Load ----
    logger.info("Connecting to RDS ...")
    conn = _get_db_connection(args)
    try:
        ensure_schema(conn)
        inserted = upsert_chunks(conn, all_chunks, embeddings)
        logger.info("Inserted %d new rows (skipped %d duplicates).",
                     inserted, len(all_chunks) - inserted)
    finally:
        conn.close()

    summary = {
        "files": len(objects),
        "chunks": len(all_chunks),
        "inserted": inserted,
    }
    logger.info("Pipeline complete: %s", summary)
    return summary


# ---------------------------------------------------------------------------
# Glue entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    args = _parse_args()
    run_pipeline(args)
