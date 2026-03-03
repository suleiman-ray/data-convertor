import asyncio

from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.redis import get_redis
from app.core.s3 import get_s3
from app.core.sqs import get_sqs
from app.schemas.health import HealthResponse, ServiceStatus

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check() -> HealthResponse:
    services: dict[str, ServiceStatus] = {}

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        services["postgres"] = ServiceStatus(status="ok")
    except Exception as exc:
        services["postgres"] = ServiceStatus(status="error", detail=str(exc))

    try:
        redis = get_redis()
        await redis.ping()
        services["redis"] = ServiceStatus(status="ok")
    except Exception as exc:
        services["redis"] = ServiceStatus(status="error", detail=str(exc))

    try:
        await asyncio.to_thread(
            get_s3().head_bucket, Bucket=settings.s3_bucket_raw
        )
        services["s3"] = ServiceStatus(status="ok")
    except Exception as exc:
        services["s3"] = ServiceStatus(status="error", detail=str(exc))

    try:
        await asyncio.to_thread(
            get_sqs().get_queue_attributes,
            QueueUrl=settings.sqs_extraction_queue_url,
            AttributeNames=["QueueArn"],
        )
        services["sqs"] = ServiceStatus(status="ok")
    except Exception as exc:
        services["sqs"] = ServiceStatus(status="error", detail=str(exc))

    overall = "ok" if all(s.status == "ok" for s in services.values()) else "degraded"
    return HealthResponse(status=overall, services=services)
