import json
import logging
import os
import signal
import time
from datetime import datetime, timezone

import boto3
from prometheus_client import Counter, start_http_server


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "message": record.getMessage(),
        })


stream_handler = logging.StreamHandler()
stream_handler.setFormatter(JsonFormatter())
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), handlers=[stream_handler], force=True)
logger = logging.getLogger("audit-worker")

PROCESSED = Counter("audit_events_processed_total", "Audit events archived to S3.")
FAILED = Counter("audit_events_failed_total", "Audit events that could not be archived.")

endpoint = os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566")
region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
queue_name = os.getenv("AUDIT_QUEUE_NAME", "floci-contact-events")
bucket_name = os.getenv("AUDIT_BUCKET", "floci-contact-audit")
sqs = boto3.client("sqs", endpoint_url=endpoint, region_name=region)
s3 = boto3.client("s3", endpoint_url=endpoint, region_name=region)
running = True


def stop_worker(signum, frame):
    global running
    running = False


signal.signal(signal.SIGTERM, stop_worker)
signal.signal(signal.SIGINT, stop_worker)


def run():
    start_http_server(9101, addr="0.0.0.0")
    queue_url = sqs.get_queue_url(QueueName=queue_name)["QueueUrl"]
    logger.info("audit_worker_started")

    while running:
        response = sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=10,
            VisibilityTimeout=45,
        )
        for message in response.get("Messages", []):
            try:
                event = json.loads(message["Body"])
                key = f"events/{event['event_id']}.json"
                s3.put_object(
                    Bucket=bucket_name,
                    Key=key,
                    Body=json.dumps(event, sort_keys=True).encode("utf-8"),
                    ContentType="application/json",
                )
                sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])
                PROCESSED.inc()
                logger.info("audit_event_archived")
            except Exception as error:
                FAILED.inc()
                logger.error("audit_event_failed: %s", error)
                time.sleep(1)


if __name__ == "__main__":
    run()
