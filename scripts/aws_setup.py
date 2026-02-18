"""
AWS resource provisioning script.

Creates the following resources for the RAG ETL pipeline:
  1. S3 bucket         -- data lake for raw documents
  2. RDS PostgreSQL 16 -- vector warehouse with pgvector
  3. Glue Python Shell  -- ETL job definition

Usage:
    python scripts/aws_setup.py

Requires:
    - AWS credentials configured (~/.aws/credentials)
    - boto3 installed
"""

from __future__ import annotations

import json
import os
import sys
import time
import boto3
from botocore.exceptions import ClientError

# ---------------------------------------------------------------------------
# Configuration  (edit these to match your preferences)
# ---------------------------------------------------------------------------
REGION = os.getenv("AWS_REGION", "ap-northeast-1")
PROJECT_PREFIX = "rag-agent"

# S3
S3_BUCKET_NAME = os.getenv("RAG_S3_BUCKET", f"{PROJECT_PREFIX}-datalake-{REGION}")

# RDS
DB_INSTANCE_ID = f"{PROJECT_PREFIX}-db"
DB_NAME = "ragdb"
DB_USERNAME = "ragadmin"
DB_PASSWORD = os.getenv("RAG_DB_PASSWORD", "RagAdmin2024!")  # change in production
DB_INSTANCE_CLASS = "db.t3.micro"  # free tier eligible

# Glue
GLUE_JOB_NAME = f"{PROJECT_PREFIX}-etl"
GLUE_SCRIPT_KEY = "glue-scripts/glue_etl_job.py"

# Security Group
SG_NAME = f"{PROJECT_PREFIX}-rds-sg"


def get_or_create_s3_bucket(s3) -> str:
    """Create the S3 bucket if it doesn't exist."""
    try:
        s3.head_bucket(Bucket=S3_BUCKET_NAME)
        print(f"[S3] Bucket already exists: {S3_BUCKET_NAME}")
    except ClientError:
        print(f"[S3] Creating bucket: {S3_BUCKET_NAME}")
        if REGION == "us-east-1":
            s3.create_bucket(Bucket=S3_BUCKET_NAME)
        else:
            s3.create_bucket(
                Bucket=S3_BUCKET_NAME,
                CreateBucketConfiguration={"LocationConstraint": REGION},
            )
        print(f"[S3] Bucket created: {S3_BUCKET_NAME}")
    return S3_BUCKET_NAME


def upload_glue_script(s3) -> str:
    """Upload the ETL script to S3."""
    script_path = os.path.join(os.path.dirname(__file__), "..", "etl", "glue_etl_job.py")
    script_path = os.path.abspath(script_path)

    print(f"[S3] Uploading Glue script to s3://{S3_BUCKET_NAME}/{GLUE_SCRIPT_KEY}")
    s3.upload_file(script_path, S3_BUCKET_NAME, GLUE_SCRIPT_KEY)
    print(f"[S3] Script uploaded.")
    return f"s3://{S3_BUCKET_NAME}/{GLUE_SCRIPT_KEY}"


def get_default_vpc_and_subnet(ec2) -> tuple:
    """Get the default VPC and a public subnet."""
    vpcs = ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])
    if not vpcs["Vpcs"]:
        print("[VPC] ERROR: No default VPC found. Create one in the AWS Console first.")
        sys.exit(1)
    vpc_id = vpcs["Vpcs"][0]["VpcId"]

    subnets = ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])
    subnet_ids = [s["SubnetId"] for s in subnets["Subnets"]]
    print(f"[VPC] Default VPC: {vpc_id}  Subnets: {subnet_ids}")
    return vpc_id, subnet_ids


def get_or_create_security_group(ec2, vpc_id: str) -> str:
    """Create a security group that allows inbound PostgreSQL (5432)."""
    try:
        sgs = ec2.describe_security_groups(
            Filters=[
                {"Name": "group-name", "Values": [SG_NAME]},
                {"Name": "vpc-id", "Values": [vpc_id]},
            ]
        )
        if sgs["SecurityGroups"]:
            sg_id = sgs["SecurityGroups"][0]["GroupId"]
            print(f"[SG] Security group already exists: {sg_id}")
            return sg_id
    except ClientError:
        pass

    print(f"[SG] Creating security group: {SG_NAME}")
    sg = ec2.create_security_group(
        GroupName=SG_NAME,
        Description="Allow PostgreSQL inbound for RAG pipeline",
        VpcId=vpc_id,
    )
    sg_id = sg["GroupId"]

    ec2.authorize_security_group_ingress(
        GroupId=sg_id,
        IpPermissions=[
            {
                "IpProtocol": "tcp",
                "FromPort": 5432,
                "ToPort": 5432,
                "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "PostgreSQL access"}],
            }
        ],
    )
    print(f"[SG] Created: {sg_id} (inbound 5432 open)")
    return sg_id


def get_or_create_rds(rds_client, ec2) -> dict:
    """Create RDS PostgreSQL instance."""
    # check if already exists
    try:
        resp = rds_client.describe_db_instances(DBInstanceIdentifier=DB_INSTANCE_ID)
        inst = resp["DBInstances"][0]
        status = inst["DBInstanceStatus"]
        endpoint = inst.get("Endpoint", {}).get("Address", "pending...")
        print(f"[RDS] Instance already exists: {DB_INSTANCE_ID}  status={status}  endpoint={endpoint}")
        return inst
    except ClientError as e:
        if "DBInstanceNotFound" not in str(e):
            raise

    vpc_id, subnet_ids = get_default_vpc_and_subnet(ec2)
    sg_id = get_or_create_security_group(ec2, vpc_id)

    print(f"[RDS] Creating PostgreSQL instance: {DB_INSTANCE_ID}  (this takes 5-10 minutes)")
    rds_client.create_db_instance(
        DBInstanceIdentifier=DB_INSTANCE_ID,
        DBInstanceClass=DB_INSTANCE_CLASS,
        Engine="postgres",
        EngineVersion="16",
        MasterUsername=DB_USERNAME,
        MasterUserPassword=DB_PASSWORD,
        DBName=DB_NAME,
        AllocatedStorage=20,
        MaxAllocatedStorage=20,
        StorageType="gp2",
        PubliclyAccessible=True,
        VpcSecurityGroupIds=[sg_id],
        BackupRetentionPeriod=0,       # no backups (free tier friendly)
        DeletionProtection=False,
        Tags=[{"Key": "Project", "Value": PROJECT_PREFIX}],
    )
    print(f"[RDS] Instance creation initiated. Waiting for it to become available...")

    waiter = rds_client.get_waiter("db_instance_available")
    waiter.wait(
        DBInstanceIdentifier=DB_INSTANCE_ID,
        WaiterConfig={"Delay": 30, "MaxAttempts": 40},
    )

    resp = rds_client.describe_db_instances(DBInstanceIdentifier=DB_INSTANCE_ID)
    inst = resp["DBInstances"][0]
    endpoint = inst["Endpoint"]["Address"]
    port = inst["Endpoint"]["Port"]
    print(f"[RDS] Instance ready: {endpoint}:{port}")
    return inst


def setup_pgvector(host: str, port: int) -> None:
    """Connect to RDS and enable pgvector + create table."""
    try:
        import psycopg2
    except ImportError:
        print("[DB] psycopg2 not installed. Install with: pip install psycopg2-binary")
        print("[DB] Skipping schema setup. Run manually later with etl/schema.sql")
        return

    print(f"[DB] Connecting to {host}:{port}/{DB_NAME} ...")
    conn = psycopg2.connect(
        host=host, port=port, dbname=DB_NAME,
        user=DB_USERNAME, password=DB_PASSWORD,
    )
    conn.autocommit = True

    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        print("[DB] pgvector extension enabled.")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id          SERIAL       PRIMARY KEY,
                chunk_id    TEXT         UNIQUE NOT NULL,
                content     TEXT         NOT NULL,
                metadata    JSONB        DEFAULT '{}'::jsonb,
                embedding   vector(768),
                created_at  TIMESTAMPTZ  DEFAULT now()
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_documents_embedding
                ON documents USING hnsw (embedding vector_cosine_ops);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_documents_source
                ON documents USING btree ((metadata ->> 'source'));
        """)
        print("[DB] Table 'documents' and indexes created.")

    conn.close()


def get_or_create_glue_role(iam) -> str:
    """Create IAM role for Glue job."""
    role_name = f"{PROJECT_PREFIX}-glue-role"

    try:
        resp = iam.get_role(RoleName=role_name)
        arn = resp["Role"]["Arn"]
        print(f"[IAM] Glue role already exists: {arn}")
        return arn
    except ClientError:
        pass

    trust_policy = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "glue.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }],
    })

    print(f"[IAM] Creating Glue role: {role_name}")
    resp = iam.create_role(
        RoleName=role_name,
        AssumeRolePolicyDocument=trust_policy,
        Description="IAM role for RAG ETL Glue job",
    )
    arn = resp["Role"]["Arn"]

    # attach policies
    for policy in [
        "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole",
        "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess",
    ]:
        iam.attach_role_policy(RoleName=role_name, PolicyArn=policy)

    print(f"[IAM] Role created: {arn}")
    # IAM role propagation delay
    print("[IAM] Waiting 10s for role propagation...")
    time.sleep(10)
    return arn


def get_or_create_glue_job(glue_client, role_arn: str, script_s3_path: str, rds_host: str) -> None:
    """Create Glue Python Shell ETL job."""
    try:
        glue_client.get_job(JobName=GLUE_JOB_NAME)
        print(f"[Glue] Job already exists: {GLUE_JOB_NAME}")
        # update the job to ensure latest config
        glue_client.update_job(
            JobName=GLUE_JOB_NAME,
            JobUpdate={
                "Role": role_arn,
                "Command": {
                    "Name": "pythonshell",
                    "PythonVersion": "3.9",
                    "ScriptLocation": script_s3_path,
                },
                "MaxCapacity": 0.0625,
                "Timeout": 60,
                "GlueVersion": "3.0",
                "DefaultArguments": {
                    "--S3_BUCKET": S3_BUCKET_NAME,
                    "--S3_PREFIX": "raw/",
                    "--DB_HOST": rds_host,
                    "--DB_PORT": "5432",
                    "--DB_NAME": DB_NAME,
                    "--DB_USER": DB_USERNAME,
                    "--DB_PASSWORD": DB_PASSWORD,
                    "--GOOGLE_API_KEY": os.getenv("GOOGLE_API_KEY", ""),
                    "--additional-python-modules": (
                        "pypdf,beautifulsoup4,"
                        "google-generativeai,pg8000"
                    ),
                },
            },
        )
        print(f"[Glue] Job updated with latest config.")
        return
    except ClientError as e:
        if "EntityNotFoundException" not in str(e):
            raise

    print(f"[Glue] Creating job: {GLUE_JOB_NAME}")
    glue_client.create_job(
        Name=GLUE_JOB_NAME,
        Role=role_arn,
        Command={
            "Name": "pythonshell",
            "PythonVersion": "3.9",
            "ScriptLocation": script_s3_path,
        },
        MaxCapacity=0.0625,
        Timeout=60,
        GlueVersion="3.0",
        DefaultArguments={
            "--S3_BUCKET": S3_BUCKET_NAME,
            "--S3_PREFIX": "raw/",
            "--DB_HOST": rds_host,
            "--DB_PORT": "5432",
            "--DB_NAME": DB_NAME,
            "--DB_USER": DB_USERNAME,
            "--DB_PASSWORD": DB_PASSWORD,
            "--GOOGLE_API_KEY": os.getenv("GOOGLE_API_KEY", ""),
            "--additional-python-modules": (
                "pypdf,beautifulsoup4,"
                "google-generativeai,pg8000"
            ),
        },
    )
    print(f"[Glue] Job created: {GLUE_JOB_NAME}")


def main():
    print("=" * 60)
    print("  RAG Agent -- AWS Resource Setup")
    print("=" * 60)

    session = boto3.Session(region_name=REGION)

    # verify credentials
    sts = session.client("sts")
    try:
        identity = sts.get_caller_identity()
        print(f"\nAWS Account: {identity['Account']}")
        print(f"IAM ARN:     {identity['Arn']}")
        print(f"Region:      {REGION}\n")
    except Exception as e:
        print(f"\nERROR: AWS credentials not configured.\n{e}")
        print("Run: python scripts/configure_aws.py")
        sys.exit(1)

    s3 = session.client("s3")
    ec2 = session.client("ec2")
    rds_client = session.client("rds")
    iam = session.client("iam")
    glue_client = session.client("glue")

    # Step 1: S3 bucket
    print("-" * 60)
    bucket = get_or_create_s3_bucket(s3)

    # Step 2: Upload Glue script
    print("-" * 60)
    script_path = upload_glue_script(s3)

    # Step 3: RDS PostgreSQL
    print("-" * 60)
    inst = get_or_create_rds(rds_client, ec2)
    rds_host = inst.get("Endpoint", {}).get("Address")
    rds_port = inst.get("Endpoint", {}).get("Port", 5432)

    if rds_host:
        # Step 4: Enable pgvector + create table
        print("-" * 60)
        setup_pgvector(rds_host, rds_port)
    else:
        print("[RDS] Endpoint not yet available. Re-run this script in a few minutes.")

    # Step 5: Glue IAM role
    print("-" * 60)
    role_arn = get_or_create_glue_role(iam)

    # Step 6: Glue job
    print("-" * 60)
    get_or_create_glue_job(glue_client, role_arn, script_path, rds_host or "PENDING")

    # Summary
    print("\n" + "=" * 60)
    print("  Setup Complete!")
    print("=" * 60)
    print(f"  S3 Bucket:     {bucket}")
    print(f"  RDS Endpoint:  {rds_host or 'PENDING'}:{rds_port}")
    print(f"  RDS Database:  {DB_NAME}")
    print(f"  RDS User:      {DB_USERNAME}")
    print(f"  Glue Job:      {GLUE_JOB_NAME}")
    print(f"  Glue Script:   {script_path}")
    print()
    print("Next steps:")
    print(f"  1. Upload docs:  python scripts/s3_upload.py <local_dir>")
    print(f"  2. Run ETL:      python scripts/run_glue_job.py")
    print(f"  3. Start API:    set PGVECTOR_CONNECTION_STRING=postgresql://{DB_USERNAME}:{DB_PASSWORD}@{rds_host}:{rds_port}/{DB_NAME}")
    print(f"                   uvicorn rag_agent.api:app --port 8000")


if __name__ == "__main__":
    main()
