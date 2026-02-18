"""
Trigger the AWS Glue ETL job and monitor its execution.

Usage:
    python scripts/run_glue_job.py
    python scripts/run_glue_job.py --wait    # poll until completion
"""

from __future__ import annotations

import os
import sys
import time

import boto3

REGION = os.getenv("AWS_REGION", "ap-northeast-1")
GLUE_JOB_NAME = "rag-agent-etl"


def main():
    wait = "--wait" in sys.argv

    glue = boto3.client("glue", region_name=REGION)

    print(f"Starting Glue job: {GLUE_JOB_NAME}")
    resp = glue.start_job_run(JobName=GLUE_JOB_NAME)
    run_id = resp["JobRunId"]
    print(f"Job run started: {run_id}")

    if not wait:
        print("Use --wait to poll until completion, or check in AWS Console:")
        print(f"  https://{REGION}.console.aws.amazon.com/glue/home?region={REGION}#/v2/etl-configuration/jobs/runs/{GLUE_JOB_NAME}")
        return

    print("Polling for completion (Ctrl+C to stop)...")
    while True:
        time.sleep(15)
        status_resp = glue.get_job_run(JobName=GLUE_JOB_NAME, RunId=run_id)
        run = status_resp["JobRun"]
        state = run["JobRunState"]
        duration = run.get("ExecutionTime", 0)

        print(f"  [{duration:>4}s] {state}")

        if state in ("SUCCEEDED", "FAILED", "STOPPED", "ERROR", "TIMEOUT"):
            break

    if state == "SUCCEEDED":
        print(f"\nETL job completed successfully in {duration}s.")
        print("Data has been loaded into RDS PostgreSQL.")
        print("Next step: start the FastAPI service with PGVECTOR_CONNECTION_STRING set.")
    else:
        error = run.get("ErrorMessage", "No error message")
        print(f"\nJob ended with state: {state}")
        print(f"Error: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
