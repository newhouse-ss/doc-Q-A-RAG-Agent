"""
Verify RDS PostgreSQL connection and inspect loaded data.

Usage:
    python scripts/check_rds.py

Reads connection info from environment or falls back to aws_setup defaults.
"""

from __future__ import annotations

import os
import sys


def main():
    try:
        import psycopg2
    except ImportError:
        print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary")
        sys.exit(1)

    host = os.getenv("DB_HOST", "")
    port = int(os.getenv("DB_PORT", "5432"))
    dbname = os.getenv("DB_NAME", "ragdb")
    user = os.getenv("DB_USER", "ragadmin")
    password = os.getenv("DB_PASSWORD", "RagAdmin2024!")

    if not host:
        # try to discover from RDS
        try:
            import boto3
            region = os.getenv("AWS_REGION", "ap-northeast-1")
            rds = boto3.client("rds", region_name=region)
            resp = rds.describe_db_instances(DBInstanceIdentifier="rag-agent-db")
            inst = resp["DBInstances"][0]
            host = inst["Endpoint"]["Address"]
            port = inst["Endpoint"]["Port"]
            print(f"Discovered RDS endpoint: {host}:{port}")
        except Exception as e:
            print(f"ERROR: DB_HOST not set and RDS discovery failed: {e}")
            sys.exit(1)

    print(f"Connecting to {host}:{port}/{dbname} as {user} ...")
    conn = psycopg2.connect(host=host, port=port, dbname=dbname, user=user, password=password)

    with conn.cursor() as cur:
        # check pgvector
        cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector';")
        row = cur.fetchone()
        if row:
            print(f"pgvector extension: v{row[0]}")
        else:
            print("WARNING: pgvector extension NOT installed.")

        # check table
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'documents'
            );
        """)
        exists = cur.fetchone()[0]
        if not exists:
            print("WARNING: 'documents' table does not exist.")
            conn.close()
            return

        # row count
        cur.execute("SELECT count(*) FROM documents;")
        count = cur.fetchone()[0]
        print(f"Documents table: {count} rows")

        if count > 0:
            # sample row
            cur.execute("""
                SELECT chunk_id, length(content), metadata, created_at
                FROM documents
                ORDER BY created_at DESC
                LIMIT 3;
            """)
            rows = cur.fetchall()
            print("\nLatest 3 chunks:")
            for r in rows:
                print(f"  chunk_id={r[0]}  content_len={r[1]}  metadata={r[2]}  created={r[3]}")

            # distinct sources
            cur.execute("SELECT DISTINCT metadata->>'source' FROM documents;")
            sources = [r[0] for r in cur.fetchall()]
            print(f"\nDistinct sources ({len(sources)}):")
            for s in sources:
                print(f"  {s}")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
