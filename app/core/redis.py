import json

import redis.asyncio as aioredis

from app.core.config import settings

_redis_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


async def close_redis() -> None:
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None



RESOLVER_CACHE_TTL = 86_400  # 24 hours


def _resolver_key(intake_type_id: str, intake_type_version: str, stable_field_id: str) -> str:
    return f"resolver:v1:{intake_type_id}:{intake_type_version}:{stable_field_id}"


async def get_cached_mapping(
    intake_type_id: str,
    intake_type_version: str,
    stable_field_id: str,
) -> dict | None:
    redis = get_redis()
    key = _resolver_key(intake_type_id, intake_type_version, stable_field_id)
    raw = await redis.get(key)
    if raw is None:
        return None
    return json.loads(raw)


async def set_cached_mapping(
    intake_type_id: str,
    intake_type_version: str,
    stable_field_id: str,
    mapping: dict,
) -> None:
    redis = get_redis()
    key = _resolver_key(intake_type_id, intake_type_version, stable_field_id)
    await redis.setex(key, RESOLVER_CACHE_TTL, json.dumps(mapping))


async def invalidate_cached_mapping(
    intake_type_id: str,
    intake_type_version: str,
    stable_field_id: str,
) -> None:
    redis = get_redis()
    key = _resolver_key(intake_type_id, intake_type_version, stable_field_id)
    await redis.delete(key)
