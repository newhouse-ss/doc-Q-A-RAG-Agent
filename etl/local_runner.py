"""
Local runner for the ETL pipeline.

Simulates the Glue job locally by:
  1. Reading files from a local directory (instead of S3)
  2. Running the same parse -> chunk -> embed -> load logic
  3. Writing to a local or remote PostgreSQL instance

Usage:
    python -m etl.local_runner \
        --input_dir ./sample_docs \
        --DB_HOST localhost \
        --DB_NAME ragdb \
        --DB_USER postgres \
        --DB_PASSWORD secret \
        --GOOGLE_API_KEY <key>

    Or with environment variables:
    export GOOGLE_API_KEY=...
    export DB_HOST=localhost
    python -m etl.local_runner --input_dir ./sample_docs
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from etl.glue_etl_job import (
    parse_document,
    split_documents,
    generate_embeddings,
    ensure_schema,
    upsert_chunks,
    EMBEDDING_DIM,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger("local_runner")


def _get_db_connection_local(args: argparse.Namespace):
    import psycopg2

    return psycopg2.connect(
        host=args.db_host,
        port=args.db_port,
        dbname=args.db_name,
        user=args.db_user,
        password=args.db_password,
    )


def load_local_files(input_dir: str) -> List[Dict[str, Any]]:
    """Read every file in *input_dir* and parse it into document dicts."""
    root = Path(input_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"Directory not found: {root}")

    all_docs: List[Dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        logger.info("Reading %s", path)
        data = path.read_bytes()
        docs = parse_document(data, key=str(path))
        all_docs.extend(docs)
        logger.info("  -> %d document section(s)", len(docs))

    return all_docs


def main() -> None:
    parser = argparse.ArgumentParser(description="Local ETL runner")
    parser.add_argument("--input_dir", required=True, help="Directory with raw documents")
    parser.add_argument("--db_host", default=os.getenv("DB_HOST", "localhost"))
    parser.add_argument("--db_port", type=int, default=int(os.getenv("DB_PORT", "5432")))
    parser.add_argument("--db_name", default=os.getenv("DB_NAME", "ragdb"))
    parser.add_argument("--db_user", default=os.getenv("DB_USER", "postgres"))
    parser.add_argument("--db_password", default=os.getenv("DB_PASSWORD", ""))
    parser.add_argument("--google_api_key", default=os.getenv("GOOGLE_API_KEY", ""))
    parser.add_argument("--chunk_size", type=int, default=1024)
    parser.add_argument("--chunk_overlap", type=int, default=50)
    parser.add_argument("--dry_run", action="store_true",
                        help="Parse and chunk only; skip embedding and DB write")

    args = parser.parse_args()

    if not args.google_api_key and not args.dry_run:
        print("ERROR: --google_api_key or GOOGLE_API_KEY env var is required "
              "(unless --dry_run).", file=sys.stderr)
        sys.exit(1)

    # ---- Extract + Transform: parse ----
    docs = load_local_files(args.input_dir)
    logger.info("Parsed %d document section(s) total.", len(docs))

    # ---- Transform: chunk ----
    chunks = split_documents(docs, args.chunk_size, args.chunk_overlap)
    logger.info("Split into %d chunks.", len(chunks))

    if args.dry_run:
        logger.info("Dry run: printing first 3 chunks then exiting.")
        for c in chunks[:3]:
            print(json.dumps(c, indent=2, ensure_ascii=False)[:500])
        logger.info("Total chunks: %d", len(chunks))
        return

    # ---- Transform: embed ----
    logger.info("Generating embeddings ...")
    texts = [c["content"] for c in chunks]
    embeddings = generate_embeddings(texts, args.google_api_key)
    logger.info("Generated %d embeddings.", len(embeddings))

    # ---- Load ----
    logger.info("Connecting to PostgreSQL %s:%d/%s ...", args.db_host, args.db_port, args.db_name)
    conn = _get_db_connection_local(args)
    try:
        ensure_schema(conn)
        inserted = upsert_chunks(conn, chunks, embeddings)
        logger.info("Inserted %d rows (%d duplicates skipped).",
                     inserted, len(chunks) - inserted)
    finally:
        conn.close()

    logger.info("Done.")


if __name__ == "__main__":
    main()
