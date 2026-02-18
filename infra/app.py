#!/usr/bin/env python3
"""
AWS CDK entry point.

Provisions:
  - VPC with public/private subnets
  - S3 bucket (data lake for raw documents)
  - RDS PostgreSQL 16 with pgvector
  - AWS Glue Python Shell job (ETL pipeline)
  - ECS Fargate service for the FastAPI container
  - Application Load Balancer
"""

import aws_cdk as cdk

from stacks.rag_service_stack import RagServiceStack

app = cdk.App()

RagServiceStack(
    app,
    "RagServiceStack",
    env=cdk.Environment(
        account=app.node.try_get_context("account"),
        region=app.node.try_get_context("region") or "ap-northeast-1",
    ),
)

app.synth()
