import json

from app.core.aws import make_boto_client
from app.core.config import settings

_sqs_client = None


def get_sqs():
    global _sqs_client
    if _sqs_client is None:
        _sqs_client = make_boto_client("sqs")
    return _sqs_client


def send_message(queue_url: str, body: dict) -> None:
    get_sqs().send_message(QueueUrl=queue_url, MessageBody=json.dumps(body))


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
