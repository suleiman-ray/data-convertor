import boto3
from botocore.config import Config

from app.core.config import settings

_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "standard"})


def make_boto_client(service: str):
    """Return a boto3 client for *service* using app settings."""
    kwargs = {
        "region_name": settings.aws_region,
        "aws_access_key_id": settings.aws_access_key_id,
        "aws_secret_access_key": settings.aws_secret_access_key,
        "config": _RETRY_CONFIG,
    }
    if settings.aws_endpoint_url:
        kwargs["endpoint_url"] = settings.aws_endpoint_url
    return boto3.client(service, **kwargs)
