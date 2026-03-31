import abc
import asyncio
import json
import logging
import signal

from app.core.config import settings
from app.core.sqs import delete_message, receive_messages

logger = logging.getLogger(__name__)


class SQSWorker(abc.ABC):
    """
    Abstract base for SQS workers.

    Subclasses MUST define class-level attributes:
        queue_url:   str  — SQS queue URL to poll
        worker_name: str  — human-readable name used in log messages

    Missing attributes are caught at subclass definition time via
    __init_subclass__, not silently at first poll attempt.
    """

    queue_url: str
    worker_name: str

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        # Skip enforcement on abstract intermediaries (e.g. test base classes)
        if abc.ABC in cls.__bases__:
            return
        missing = [attr for attr in ("queue_url", "worker_name") if not hasattr(cls, attr)]
        if missing:
            raise TypeError(
                f"{cls.__name__} must define class attributes: {missing}"
            )

    def __init__(self) -> None:
        self._running = False

    async def _serve_health(self, port: int) -> None:
        async def handle(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            try:
                await reader.read(65536)
                writer.write(
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: text/plain\r\n"
                    b"Connection: close\r\n"
                    b"Content-Length: 2\r\n\r\n"
                    b"ok"
                )
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(
            handle,
            "0.0.0.0",
            port,
        )
        async with server:
            await server.serve_forever()

    @abc.abstractmethod
    async def handle(self, body: dict, receipt_handle: str) -> None:
        """
        Process one message. Must be implemented by each worker.

        Contract:
          1. Acquire SELECT FOR UPDATE on the relevant DB row.
          2. Check idempotency — if already processed, return early.
          3. Do the work.
          4. Commit the DB session.
          5. Return (caller deletes the SQS message after this returns).

        Raising any exception causes the message to remain in the queue
        and be re-delivered after the visibility timeout.
        """

    async def run(self) -> None:
        self._running = True
        self._register_signals()
        logger.info("[%s] Worker started, polling %s", self.worker_name, self.queue_url)

        health_task: asyncio.Task[None] | None = None
        if settings.worker_health_port is not None:
            health_task = asyncio.create_task(
                self._serve_health(settings.worker_health_port),
                name=f"{self.worker_name}-health",
            )
            logger.info(
                "[%s] Health probe listening on 0.0.0.0:%s",
                self.worker_name,
                settings.worker_health_port,
            )

        try:
            while self._running:
                try:
                    messages = await asyncio.to_thread(
                        receive_messages, self.queue_url, settings.sqs_max_messages
                    )
                except Exception:
                    logger.exception(
                        "[%s] Error receiving messages — retrying in 5s", self.worker_name
                    )
                    await asyncio.sleep(5)
                    continue

                for msg in messages:
                    receipt_handle = msg["ReceiptHandle"]
                    receive_count = int(
                        msg.get("Attributes", {}).get("ApproximateReceiveCount", 1)
                    )

                    try:
                        body = json.loads(msg["Body"])
                    except json.JSONDecodeError:
                        logger.error(
                            "[%s] Malformed message body (receive_count=%d) — deleting to avoid loop",
                            self.worker_name, receive_count,
                        )
                        await asyncio.to_thread(delete_message, self.queue_url, receipt_handle)
                        continue

                    logger.info(
                        "[%s] Processing message (receive_count=%d) body_keys=%s",
                        self.worker_name, receive_count, list(body.keys()),
                    )

                    try:
                        await self.handle(body, receipt_handle)
                        # Ack: delete only after successful handle (which includes db.commit)
                        await asyncio.to_thread(delete_message, self.queue_url, receipt_handle)
                        logger.info("[%s] Message processed and acknowledged", self.worker_name)
                    except Exception:
                        logger.exception(
                            "[%s] handle() raised — message will be re-delivered (receive_count=%d)",
                            self.worker_name, receive_count,
                        )
                        # Do NOT delete — SQS re-delivers after visibility timeout.
                        # After maxReceiveCount retries, SQS moves it to the DLQ.

        finally:
            if health_task is not None:
                health_task.cancel()
                try:
                    await health_task
                except asyncio.CancelledError:
                    pass

        logger.info("[%s] Worker stopped", self.worker_name)

    def _register_signals(self) -> None:
        # asyncio.get_event_loop() is deprecated since Python 3.10;
        # get_running_loop() is correct inside an async context.
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._stop)

    def _stop(self) -> None:
        logger.info("[%s] Shutdown signal received — stopping after current message", self.worker_name)
        self._running = False
