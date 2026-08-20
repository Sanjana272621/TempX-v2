import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import boto3


_dynamodb_table = None


def get_table():
    global _dynamodb_table

    table_name = os.getenv("TELEMETRY_TABLE")

    if not table_name:
        raise RuntimeError("TELEMETRY_TABLE environment variable is not set")

    if _dynamodb_table is None:
        dynamodb = boto3.resource("dynamodb")
        _dynamodb_table = dynamodb.Table(table_name)

    return _dynamodb_table


def parse_event(event: dict[str, Any]) -> dict[str, Any]:

    if not isinstance(event, dict):
        raise ValueError("Event must be a JSON object")

    if "body" in event:
        body = event["body"]

        if isinstance(body, str):
            return json.loads(body)

        if isinstance(body, dict):
            return body

        raise ValueError("Event body must be a JSON object or JSON string")

    return event


def validate_timestamp(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp must be a non-empty ISO-8601 string")

    normalized = value.replace("Z", "+00:00")

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("timestamp must be valid ISO-8601") from exc

    if parsed.tzinfo is None:
        raise ValueError("timestamp must contain timezone information")

    return value


def to_decimal(value: Any, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be numeric")

    try:
        return Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{field_name} must be numeric") from exc


def build_item(payload: dict[str, Any]) -> dict[str, Any]:
    required_fields = [
        "device_id",
        "timestamp",
        "temperature",
        "humidity",
    ]

    missing_fields = [
        field for field in required_fields
        if field not in payload
    ]

    if missing_fields:
        raise ValueError(
            f"Missing required fields: {', '.join(missing_fields)}"
        )

    device_id = payload["device_id"]

    if not isinstance(device_id, str) or not device_id.strip():
        raise ValueError("device_id must be a non-empty string")

    topic_device_id = payload.get("topic_device_id")

    if topic_device_id and topic_device_id != device_id:
        raise ValueError(
            "Payload device_id does not match MQTT topic device ID"
        )

    item = {
        "device_id": device_id,
        "timestamp": validate_timestamp(payload["timestamp"]),
        "temperature": to_decimal(
            payload["temperature"],
            "temperature",
        ),
        "humidity": to_decimal(
            payload["humidity"],
            "humidity",
        ),
        "received_at": datetime.now(timezone.utc).isoformat(),
    }

    if "status" in payload:
        item["status"] = str(payload["status"])

    return item


def lambda_handler(event, context):
    payload = parse_event(event)
    item = build_item(payload)

    table = get_table()
    table.put_item(Item=item)

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "message": "Telemetry stored successfully",
                "device_id": item["device_id"],
                "timestamp": item["timestamp"],
            }
        ),
    }