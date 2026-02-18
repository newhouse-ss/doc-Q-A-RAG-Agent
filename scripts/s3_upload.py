"""
Upload local documents to the S3 data lake.

Usage:
    python scripts/s3_upload.py <local_directory_or_file>
    python scripts/s3_upload.py ./sample_docs
    python scripts/s3_upload.py ./report.pdf

Files are uploaded under the "raw/" prefix in the S3 bucket.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import boto3

REGION = os.getenv("AWS_REGION", "ap-northeast-1")
S3_BUCKET_NAME = os.getenv("RAG_S3_BUCKET", f"rag-agent-datalake-{REGION}")
S3_PREFIX = "raw/"


def upload_file(s3, local_path: Path) -> str:
    key = S3_PREFIX + local_path.name
    print(f"  Uploading {local_path} -> s3://{S3_BUCKET_NAME}/{key}")
    s3.upload_file(str(local_path), S3_BUCKET_NAME, key)
    return key


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/s3_upload.py <local_dir_or_file>")
        sys.exit(1)

    target = Path(sys.argv[1])
    if not target.exists():
        print(f"ERROR: Path not found: {target}")
        sys.exit(1)

    s3 = boto3.client("s3", region_name=REGION)

    uploaded = []
    if target.is_file():
        uploaded.append(upload_file(s3, target))
    elif target.is_dir():
        for f in sorted(target.rglob("*")):
            if f.is_file():
                uploaded.append(upload_file(s3, f))
    else:
        print(f"ERROR: {target} is neither a file nor a directory.")
        sys.exit(1)

    print(f"\nUploaded {len(uploaded)} file(s) to s3://{S3_BUCKET_NAME}/{S3_PREFIX}")
    print("Next step: python scripts/run_glue_job.py")


if __name__ == "__main__":
    main()
