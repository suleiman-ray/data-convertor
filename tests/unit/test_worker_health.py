import asyncio
import socket

import pytest

from app.workers.base import SQSWorker


class _ProbeWorker(SQSWorker):
    queue_url = "http://example.invalid/q"
    worker_name = "probe"

    async def handle(self, body: dict, receipt_handle: str) -> None:
        raise NotImplementedError


@pytest.mark.asyncio
async def test_serve_health_returns_http_200():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    w = _ProbeWorker()
    task = asyncio.create_task(w._serve_health(port))
    await asyncio.sleep(0.05)

    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"GET / HTTP/1.0\r\n\r\n")
        await writer.drain()
        data = await reader.read()
        writer.close()
        await writer.wait_closed()
        assert b"200 OK" in data
        assert data.endswith(b"ok")
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
