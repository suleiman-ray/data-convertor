from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Application
    app_env: str = "development"
    app_debug: bool = True
    secret_key: str = "fake-key"

    # Database
    database_url: str = "postgresql+asyncpg://fhir:fhir@localhost:5432/fhir_convertor"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # AWS
    aws_region: str = "us-east-1"
    aws_access_key_id: str = "test"
    aws_secret_access_key: str = "test"
    aws_endpoint_url: str | None = None

    # S3
    s3_bucket_raw: str = "fhir-raw-artifacts"
    s3_bucket_bundles: str = "fhir-bundles"

    # SQS queue URLs
    sqs_extraction_queue_url: str = "http://localhost:4566/000000000000/extraction-queue"
    sqs_resolve_normalize_queue_url: str = "http://localhost:4566/000000000000/resolve-normalize-queue"
    sqs_fhir_queue_url: str = "http://localhost:4566/000000000000/fhir-queue"
    sqs_delivery_queue_url: str = "http://localhost:4566/000000000000/delivery-queue"

    # SQS DLQ URLs
    sqs_extraction_dlq_url: str = "http://localhost:4566/000000000000/extraction-dlq"
    sqs_resolve_normalize_dlq_url: str = "http://localhost:4566/000000000000/resolve-normalize-dlq"
    sqs_fhir_dlq_url: str = "http://localhost:4566/000000000000/fhir-dlq"
    sqs_delivery_dlq_url: str = "http://localhost:4566/000000000000/delivery-dlq"

    # SQS configuration
    sqs_visibility_timeout: int = 300
    sqs_wait_time_seconds: int = 20
    sqs_max_messages: int = 1

    # HealthLake
    healthlake_datastore_endpoint: str | None = None


settings = Settings()
