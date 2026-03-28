import pytest
from unittest.mock import patch

from app.core.sqs import (
    SQS_SEND_MAX_ATTEMPTS,
    send_message_async_with_retry,
)


@pytest.mark.asyncio
async def test_send_message_async_with_retry_succeeds_after_transient_failures():
    attempts = {"n": 0}

    async def flaky_send(queue_url: str, body: dict) -> None:
        attempts["n"] += 1
        if attempts["n"] < SQS_SEND_MAX_ATTEMPTS:
            raise ConnectionError("transient")

    with patch("app.core.sqs.send_message_async", side_effect=flaky_send):
        await send_message_async_with_retry("http://localhost/q", {"a": 1})

    assert attempts["n"] == SQS_SEND_MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_send_message_async_with_retry_raises_after_all_attempts_fail():
    async def always_fail(queue_url: str, body: dict) -> None:
        raise RuntimeError("persistent")

    with patch("app.core.sqs.send_message_async", side_effect=always_fail):
        with pytest.raises(RuntimeError, match="persistent"):
            await send_message_async_with_retry("http://localhost/q", {})
