import asyncio
import json
import logging

from app.core.aws import make_boto_client
from app.core.config import settings

logger = logging.getLogger(__name__)

_sqs_client = None

# Retries after successful DB commit — mitigates transient AWS/network errors (see P1-2).
SQS_SEND_MAX_ATTEMPTS = 3
SQS_SEND_BASE_DELAY_SEC = 0.5


def get_sqs():
    global _sqs_client
    if _sqs_client is None:
        _sqs_client = make_boto_client("sqs")
    return _sqs_client


def send_message(queue_url: str, body: dict) -> None:
    get_sqs().send_message(QueueUrl=queue_url, MessageBody=json.dumps(body))


async def send_message_async(queue_url: str, body: dict) -> None:
    """Non-blocking `send_message` for use from async endpoints/services."""
    await asyncio.to_thread(send_message, queue_url, body)


async def send_message_async_with_retry(queue_url: str, body: dict) -> None:
    """
    Send after DB commit with exponential backoff on failure.

    Does not eliminate orphan PROCESSING if all attempts fail — operators may
    need to re-publish or a future scheduled sweep may replay stuck rows — but
    clears transient errors.
    """
    delay = SQS_SEND_BASE_DELAY_SEC
    last_exc: BaseException | None = None
    for attempt in range(SQS_SEND_MAX_ATTEMPTS):
        try:
            await send_message_async(queue_url, body)
            return
        except Exception as exc: 
            last_exc = exc
            logger.warning(
                "SQS send_message attempt %d/%d failed for queue ending ...%s: %s",
                attempt + 1,
                SQS_SEND_MAX_ATTEMPTS,
                queue_url[-40:],
                exc,
            )
            if attempt < SQS_SEND_MAX_ATTEMPTS - 1:
                await asyncio.sleep(delay)
                delay *= 2
    if last_exc is None:
        raise RuntimeError("SQS send retry exhausted without exception (unreachable)")
    raise last_exc


def delete_message(queue_url: str, receipt_handle: str) -> None:
    get_sqs().delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)


def receive_messages(queue_url: str, max_messages: int = 1) -> list[dict]:
    response = get_sqs().receive_message(
        QueueUrl=queue_url,
        MaxNumberOfMessages=max_messages,
        WaitTimeSeconds=settings.sqs_wait_time_seconds,
        VisibilityTimeout=settings.sqs_visibility_timeout,
        AttributeNames=["ApproximateReceiveCount"],
    )
    return response.get("Messages", [])
