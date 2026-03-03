import boto3
import json
import sys
import os

endpoint_url = os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566")
region = os.getenv("AWS_REGION", "us-east-1")
access_key = os.getenv("AWS_ACCESS_KEY_ID", "test")
secret_key = os.getenv("AWS_SECRET_ACCESS_KEY", "test")

sqs = boto3.client(
    "sqs",
    endpoint_url=endpoint_url,
    region_name=region,
    aws_access_key_id=access_key,
    aws_secret_access_key=secret_key,
)

s3 = boto3.client(
    "s3",
    endpoint_url=endpoint_url,
    region_name=region,
    aws_access_key_id=access_key,
    aws_secret_access_key=secret_key,
)

QUEUES = [
    ("extraction-queue",        "extraction-dlq"),
    ("resolve-normalize-queue", "resolve-normalize-dlq"),
    ("fhir-queue",              "fhir-dlq"),
    ("delivery-queue",          "delivery-dlq"),
]

BUCKETS = ["fhir-raw-artifacts", "fhir-bundles"]

def create_queue_idempotent(name: str, extra_attrs: dict = None) -> str:
    attrs = {"VisibilityTimeout": "300"}
    if extra_attrs:
        attrs.update(extra_attrs)
    try:
        resp = sqs.create_queue(QueueName=name, Attributes=attrs)
        url = resp["QueueUrl"]
        print(f"  [ok] queue: {name} → {url}")
        return url
    except sqs.exceptions.QueueNameExists:
        url = sqs.get_queue_url(QueueName=name)["QueueUrl"]
        print(f"  [exists] queue: {name} → {url}")
        return url

def get_queue_arn(url: str) -> str:
    resp = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["QueueArn"])
    return resp["Attributes"]["QueueArn"]

def main():
    print(f"Connecting to LocalStack at {endpoint_url} ...")

    print("\nCreating S3 buckets:")
    for bucket in BUCKETS:
        try:
            s3.create_bucket(Bucket=bucket)
            print(f"  [ok] bucket: {bucket}")
        except Exception as e:
            if "BucketAlreadyOwnedByYou" in str(e) or "BucketAlreadyExists" in str(e):
                print(f"  [exists] bucket: {bucket}")
            else:
                print(f"  [error] bucket {bucket}: {e}", file=sys.stderr)

    print("\nCreating dead-letter queues:")
    dlq_arns = {}
    for _, dlq_name in QUEUES:
        url = create_queue_idempotent(dlq_name)
        dlq_arns[dlq_name] = get_queue_arn(url)

    print("\nCreating main queues:")
    for queue_name, dlq_name in QUEUES:
        redrive = json.dumps({
            "deadLetterTargetArn": dlq_arns[dlq_name],
            "maxReceiveCount": "3",
        })
        create_queue_idempotent(queue_name, {"RedrivePolicy": redrive})

    print("\nAll resources created successfully.")

if __name__ == "__main__":
    main()
