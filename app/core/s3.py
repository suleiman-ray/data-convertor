import hashlib

from app.core.aws import make_boto_client
from app.core.config import settings

_s3_client = None


def get_s3():
    global _s3_client
    if _s3_client is None:
        _s3_client = make_boto_client("s3")
    return _s3_client


def upload_raw_artifact(submission_id: str, content: bytes, content_type: str = "application/octet-stream") -> tuple[str, str]:
    """Upload raw intake artifact. Returns (s3_uri, sha256_hex)."""
    key = f"raw/{submission_id}/intake"
    sha256 = hashlib.sha256(content).hexdigest()
    get_s3().put_object(
        Bucket=settings.s3_bucket_raw,
        Key=key,
        Body=content,
        ContentType=content_type,
        Metadata={"sha256": sha256},
    )
    uri = f"s3://{settings.s3_bucket_raw}/{key}"
    return uri, sha256


def download_raw_artifact(raw_uri: str) -> bytes:
    """Download raw artifact from S3 URI."""
    bucket, key = _parse_s3_uri(raw_uri)
    response = get_s3().get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


def upload_fhir_bundle(bundle_id: str, bundle_json: str) -> tuple[str, str]:
    """Upload FHIR bundle JSON. Returns (s3_uri, sha256_hex)."""
    key = f"bundles/{bundle_id}/bundle.json"
    content = bundle_json.encode("utf-8")
    sha256 = hashlib.sha256(content).hexdigest()
    get_s3().put_object(
        Bucket=settings.s3_bucket_bundles,
        Key=key,
        Body=content,
        ContentType="application/fhir+json",
        Metadata={"sha256": sha256},
    )
    uri = f"s3://{settings.s3_bucket_bundles}/{key}"
    return uri, sha256


def download_fhir_bundle(bundle_uri: str) -> str:
    """Download FHIR bundle JSON from S3 URI."""
    bucket, key = _parse_s3_uri(bundle_uri)
    response = get_s3().get_object(Bucket=bucket, Key=key)
    return response["Body"].read().decode("utf-8")


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    """Parse s3://bucket/key into (bucket, key)."""
    if not uri.startswith("s3://"):
        raise ValueError(f"Invalid S3 URI (must start with 's3://'): {uri!r}")
    parts = uri[5:].split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Malformed S3 URI (expected s3://bucket/key): {uri!r}")
    return parts[0], parts[1]
