"""
AWS CDK stack: S3 + Glue ETL + RDS pgvector + ECS Fargate + ALB.

Resources:
  - VPC (2 AZs, public + private subnets, NAT gateway)
  - S3 bucket as the document data lake
  - RDS PostgreSQL 16 with pgvector extension
  - AWS Glue Python Shell job for the ETL pipeline
  - ECS Fargate service running the FastAPI container
  - Application Load Balancer (public)
  - Secrets Manager secrets for API keys and DB credentials
"""

from constructs import Construct
import aws_cdk as cdk
from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_rds as rds,
    aws_s3 as s3,
    aws_iam as iam,
    aws_glue as glue,
    aws_secretsmanager as secretsmanager,
    aws_logs as logs,
    aws_s3_deployment as s3deploy,
)


class RagServiceStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ---------------------------------------------------------------
        # VPC
        # ---------------------------------------------------------------
        vpc = ec2.Vpc(self, "RagVpc", max_azs=2, nat_gateways=1)

        # ---------------------------------------------------------------
        # Secrets
        # ---------------------------------------------------------------
        google_api_secret = secretsmanager.Secret(
            self, "GoogleApiKey",
            description="Google AI Studio API key for Gemini models",
            secret_string_value=cdk.SecretValue.unsafe_plain_text("CHANGE_ME"),
        )

        db_credentials = rds.DatabaseSecret(self, "DbCredentials", username="ragadmin")

        # ---------------------------------------------------------------
        # S3 -- document data lake
        # ---------------------------------------------------------------
        doc_bucket = s3.Bucket(
            self, "DocBucket",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # ---------------------------------------------------------------
        # RDS PostgreSQL + pgvector
        # ---------------------------------------------------------------
        db = rds.DatabaseInstance(
            self, "RagDatabase",
            engine=rds.DatabaseInstanceEngine.postgres(
                version=rds.PostgresEngineVersion.VER_16,
            ),
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.BURSTABLE4_GRAVITON, ec2.InstanceSize.MICRO,
            ),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            credentials=rds.Credentials.from_secret(db_credentials),
            database_name="ragdb",
            allocated_storage=20,
            max_allocated_storage=50,
            removal_policy=RemovalPolicy.DESTROY,
            deletion_protection=False,
        )

        # ---------------------------------------------------------------
        # Glue -- IAM role
        # ---------------------------------------------------------------
        glue_role = iam.Role(
            self, "GlueJobRole",
            assumed_by=iam.ServicePrincipal("glue.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSGlueServiceRole"
                ),
            ],
        )
        doc_bucket.grant_read(glue_role)
        google_api_secret.grant_read(glue_role)
        db_credentials.grant_read(glue_role)

        # ---------------------------------------------------------------
        # Glue -- upload ETL script to S3
        # ---------------------------------------------------------------
        script_asset = s3deploy.BucketDeployment(
            self, "GlueScriptDeploy",
            sources=[s3deploy.Source.asset("../etl")],
            destination_bucket=doc_bucket,
            destination_key_prefix="glue-scripts",
        )

        # ---------------------------------------------------------------
        # Glue -- Python Shell job
        # ---------------------------------------------------------------
        glue_job = glue.CfnJob(
            self, "EtlJob",
            name="rag-etl-pipeline",
            role=glue_role.role_arn,
            command=glue.CfnJob.JobCommandProperty(
                name="pythonshell",
                python_version="3.9",
                script_location=f"s3://{doc_bucket.bucket_name}/glue-scripts/glue_etl_job.py",
            ),
            glue_version="3.0",
            max_capacity=0.0625,  # 1/16 DPU -- minimum for Python Shell
            timeout=60,           # minutes
            default_arguments={
                "--S3_BUCKET": doc_bucket.bucket_name,
                "--S3_PREFIX": "raw/",
                "--DB_SECRET_ARN": db_credentials.secret_arn,
                "--DB_HOST": db.db_instance_endpoint_address,
                "--DB_NAME": "ragdb",
                "--GOOGLE_API_KEY": google_api_secret.secret_value.unsafe_unwrap(),
                "--additional-python-modules": (
                    "pypdf,beautifulsoup4,tiktoken,"
                    "google-generativeai,psycopg2-binary,lxml"
                ),
            },
        )

        # ---------------------------------------------------------------
        # ECS Cluster + Fargate service
        # ---------------------------------------------------------------
        cluster = ecs.Cluster(self, "RagCluster", vpc=vpc)

        pg_conn = (
            f"postgresql://"
            f"{db_credentials.secret_value_from_json('username').unsafe_unwrap()}"
            f":{db_credentials.secret_value_from_json('password').unsafe_unwrap()}"
            f"@{db.db_instance_endpoint_address}:{db.db_instance_endpoint_port}/ragdb"
        )

        fargate_service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self, "RagService",
            cluster=cluster,
            cpu=512,
            memory_limit_mib=1024,
            desired_count=1,
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=ecs.ContainerImage.from_asset(".."),
                container_port=8000,
                environment={
                    "PGVECTOR_CONNECTION_STRING": pg_conn,
                    "PGVECTOR_COLLECTION": "documents",
                },
                secrets={
                    "GOOGLE_API_KEY": ecs.Secret.from_secrets_manager(google_api_secret),
                },
                log_driver=ecs.LogDrivers.aws_logs(
                    stream_prefix="rag-agent",
                    log_retention=logs.RetentionDays.TWO_WEEKS,
                ),
            ),
            public_load_balancer=True,
        )

        fargate_service.target_group.configure_health_check(
            path="/healthz",
            interval=Duration.seconds(30),
            healthy_threshold_count=2,
            unhealthy_threshold_count=3,
        )

        db.connections.allow_default_port_from(fargate_service.service)

        # ---------------------------------------------------------------
        # Outputs
        # ---------------------------------------------------------------
        cdk.CfnOutput(self, "DocBucketName", value=doc_bucket.bucket_name)
        cdk.CfnOutput(self, "LoadBalancerDNS",
                       value=fargate_service.load_balancer.load_balancer_dns_name)
        cdk.CfnOutput(self, "DatabaseEndpoint",
                       value=db.db_instance_endpoint_address)
        cdk.CfnOutput(self, "GlueJobName", value=glue_job.name or "rag-etl-pipeline")
