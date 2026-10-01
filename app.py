import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError
from flask import Flask, Response, jsonify, render_template, request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from werkzeug.exceptions import HTTPException


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "message": record.getMessage(),
        }
        for field in ("contact_id", "action", "error"):
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        return json.dumps(payload)


stream_handler = logging.StreamHandler()
stream_handler.setFormatter(JsonFormatter())
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), handlers=[stream_handler], force=True)
logger = logging.getLogger("contacts")

AWS_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
AWS_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566")
TABLE_NAME = os.getenv("DYNAMODB_TABLE", "floci-contacts")
QUEUE_NAME = os.getenv("AUDIT_QUEUE_NAME", "floci-contact-events")

dynamodb = boto3.resource("dynamodb", endpoint_url=AWS_ENDPOINT_URL, region_name=AWS_REGION)
sqs = boto3.client("sqs", endpoint_url=AWS_ENDPOINT_URL, region_name=AWS_REGION)
table = dynamodb.Table(TABLE_NAME)

REQUESTS = Counter(
    "contacts_http_requests_total",
    "HTTP requests handled by the contacts API.",
    ("method", "route", "status"),
)
REQUEST_DURATION = Histogram(
    "contacts_http_request_duration_seconds",
    "HTTP request latency for the contacts API.",
    ("method", "route"),
)

app = Flask(__name__)


@app.before_request
def start_timer():
    request.started_at = time.perf_counter()


@app.after_request
def record_metrics(response):
    route = request.endpoint or "unmatched"
    REQUESTS.labels(request.method, route, str(response.status_code)).inc()
    REQUEST_DURATION.labels(request.method, route).observe(time.perf_counter() - request.started_at)
    return response


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def emit_audit_event(action, contact):
    event = {
        "event_id": str(uuid.uuid4()),
        "action": action,
        "occurred_at": now_iso(),
        "contact": contact,
    }
    try:
        queue_url = sqs.get_queue_url(QueueName=QUEUE_NAME)["QueueUrl"]
        sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(event))
    except Exception as error:
        logger.error("audit_event_enqueue_failed", extra={"action": action, "error": str(error)})


def validate_contact(data, partial=False):
    if not isinstance(data, dict):
        return None, "Request body must be a JSON object."

    allowed = {"name", "email", "company"}
    if set(data) - allowed:
        return None, "Only name, email, and company fields are accepted."

    fields = {}
    for field in allowed:
        if field not in data:
            continue
        value = data[field]
        if not isinstance(value, str):
            return None, f"{field} must be text."
        value = value.strip()
        if field in {"name", "email"} and not value:
            return None, f"{field} cannot be empty."
        if len(value) > 200:
            return None, f"{field} must be 200 characters or fewer."
        fields[field] = value

    if not partial and not {"name", "email"}.issubset(fields):
        return None, "Both name and email are required."
    if partial and not fields:
        return None, "Provide at least one field to update."
    if "email" in fields and ("@" not in fields["email"] or fields["email"].startswith("@")):
        return None, "Enter a valid email address."
    return fields, None


def is_missing_contact(error):
    return error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/healthz")
def health():
    return jsonify({"status": "alive"})


@app.get("/readyz")
def readiness():
    try:
        table.load()
        sqs.get_queue_url(QueueName=QUEUE_NAME)
    except Exception as error:
        return jsonify({"status": "not_ready", "error": str(error)}), 503
    return jsonify({"status": "ready"})


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


@app.get("/api/contacts")
def list_contacts():
    result = table.scan()
    contacts = result.get("Items", [])
    while "LastEvaluatedKey" in result:
        result = table.scan(ExclusiveStartKey=result["LastEvaluatedKey"])
        contacts.extend(result.get("Items", []))
    contacts.sort(key=lambda item: item.get("name", "").lower())
    return jsonify(contacts)


@app.post("/api/contacts")
def create_contact():
    fields, error = validate_contact(request.get_json(silent=True))
    if error:
        return jsonify({"error": error}), 400

    timestamp = now_iso()
    contact = {
        "contact_id": str(uuid.uuid4()),
        **fields,
        "company": fields.get("company", ""),
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    table.put_item(Item=contact, ConditionExpression="attribute_not_exists(contact_id)")
    emit_audit_event("created", contact)
    logger.info("contact_created", extra={"contact_id": contact["contact_id"], "action": "created"})
    return jsonify(contact), 201


@app.get("/api/contacts/<contact_id>")
def get_contact(contact_id):
    result = table.get_item(Key={"contact_id": contact_id})
    contact = result.get("Item")
    if contact is None:
        return jsonify({"error": "Contact not found."}), 404
    return jsonify(contact)


@app.patch("/api/contacts/<contact_id>")
def update_contact(contact_id):
    fields, error = validate_contact(request.get_json(silent=True), partial=True)
    if error:
        return jsonify({"error": error}), 400

    fields["updated_at"] = now_iso()
    expression_names = {"#updated_at": "updated_at"}
    expression_values = {":updated_at": fields["updated_at"]}
    assignments = ["#updated_at = :updated_at"]
    for field, value in fields.items():
        if field == "updated_at":
            continue
        expression_names[f"#{field}"] = field
        expression_values[f":{field}"] = value
        assignments.append(f"#{field} = :{field}")

    try:
        result = table.update_item(
            Key={"contact_id": contact_id},
            UpdateExpression="SET " + ", ".join(assignments),
            ConditionExpression="attribute_exists(contact_id)",
            ExpressionAttributeNames=expression_names,
            ExpressionAttributeValues=expression_values,
            ReturnValues="ALL_NEW",
        )
    except ClientError as error_response:
        if is_missing_contact(error_response):
            return jsonify({"error": "Contact not found."}), 404
        raise

    contact = result["Attributes"]
    emit_audit_event("updated", contact)
    logger.info("contact_updated", extra={"contact_id": contact_id, "action": "updated"})
    return jsonify(contact)


@app.delete("/api/contacts/<contact_id>")
def delete_contact(contact_id):
    try:
        result = table.delete_item(
            Key={"contact_id": contact_id},
            ConditionExpression="attribute_exists(contact_id)",
            ReturnValues="ALL_OLD",
        )
    except ClientError as error_response:
        if is_missing_contact(error_response):
            return jsonify({"error": "Contact not found."}), 404
        raise

    contact = result["Attributes"]
    emit_audit_event("deleted", contact)
    logger.info("contact_deleted", extra={"contact_id": contact_id, "action": "deleted"})
    return "", 204


@app.errorhandler(Exception)
def handle_unexpected_error(error):
    if isinstance(error, HTTPException):
        return jsonify({"error": error.description}), error.code
    logger.exception("request_failed", extra={"error": str(error)})
    return jsonify({"error": "The request could not be completed."}), 500
