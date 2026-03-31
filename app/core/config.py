from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_WEAK_SECRET_KEYS = {"fake-key", "change-me-in-production", "secret", ""}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Application
    app_env: str = "development"
    app_debug: bool = False
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

    # Workers: optional TCP health (HTTP 200 on any request) for orchestrator probes
    worker_health_port: int | None = None

    # HealthLake
    healthlake_datastore_endpoint: str | None = None

    # CORS — set to explicit origins in production, e.g. '["https://app.example.com"]'
    cors_allowed_origins: list[str] = ["*"]

    @model_validator(mode="after")
    def _validate_production_settings(self) -> "Settings":
        if self.app_env == "development":
            return self
        if self.secret_key in _WEAK_SECRET_KEYS or len(self.secret_key) < 32:
            raise ValueError(
                "SECRET_KEY must be a cryptographically strong value of at least 32 characters "
                "in non-development environments."
            )
        if (
            self.aws_access_key_id == "test"
            and self.aws_secret_access_key == "test"
            and self.aws_endpoint_url is None
        ):
            raise ValueError(
                "AWS credentials are set to LocalStack defaults ('test'/'test') but "
                "AWS_ENDPOINT_URL is not configured. Set real credentials or point "
                "AWS_ENDPOINT_URL to your LocalStack instance."
            )
        return self


settings = Settings()
