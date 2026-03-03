#!/usr/bin/env bash
# Runs inside LocalStack on startup — creates all S3 buckets and SQS queues

set -e

REGION=us-east-1
ENDPOINT=http://localhost:4566

echo ">>> Creating S3 buckets..."
awslocal s3 mb s3://fhir-raw-artifacts  --region $REGION
awslocal s3 mb s3://fhir-bundles        --region $REGION

echo ">>> Creating SQS dead-letter queues..."
awslocal sqs create-queue --queue-name extraction-dlq         --region $REGION
awslocal sqs create-queue --queue-name resolve-normalize-dlq  --region $REGION
awslocal sqs create-queue --queue-name fhir-dlq               --region $REGION
awslocal sqs create-queue --queue-name delivery-dlq           --region $REGION

EXTRACTION_DLQ_ARN=$(awslocal sqs get-queue-attributes \
  --queue-url http://localhost:4566/000000000000/extraction-dlq \
  --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)

RESOLVE_DLQ_ARN=$(awslocal sqs get-queue-attributes \
  --queue-url http://localhost:4566/000000000000/resolve-normalize-dlq \
  --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)

FHIR_DLQ_ARN=$(awslocal sqs get-queue-attributes \
  --queue-url http://localhost:4566/000000000000/fhir-dlq \
  --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)

DELIVERY_DLQ_ARN=$(awslocal sqs get-queue-attributes \
  --queue-url http://localhost:4566/000000000000/delivery-dlq \
  --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)

echo ">>> Creating SQS main queues with DLQ redrive policies..."
awslocal sqs create-queue --queue-name extraction-queue --region $REGION \
  --attributes "VisibilityTimeout=300,RedrivePolicy={\"deadLetterTargetArn\":\"$EXTRACTION_DLQ_ARN\",\"maxReceiveCount\":\"3\"}"

awslocal sqs create-queue --queue-name resolve-normalize-queue --region $REGION \
  --attributes "VisibilityTimeout=300,RedrivePolicy={\"deadLetterTargetArn\":\"$RESOLVE_DLQ_ARN\",\"maxReceiveCount\":\"3\"}"

awslocal sqs create-queue --queue-name fhir-queue --region $REGION \
  --attributes "VisibilityTimeout=300,RedrivePolicy={\"deadLetterTargetArn\":\"$FHIR_DLQ_ARN\",\"maxReceiveCount\":\"3\"}"

awslocal sqs create-queue --queue-name delivery-queue --region $REGION \
  --attributes "VisibilityTimeout=300,RedrivePolicy={\"deadLetterTargetArn\":\"$DELIVERY_DLQ_ARN\",\"maxReceiveCount\":\"3\"}"

echo ">>> LocalStack init complete."
