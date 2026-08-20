import importlib
import json
from decimal import Decimal

import pytest


telemetry = importlib.import_module(
    "lambda.store_telemetry.lambda_function"
)


class FakeTable:
    def __init__(self):
        self.items = []

    def put_item(self, Item):
        self.items.append(Item)
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}


def valid_event():
    return {
        "device_id": "sim-device-001",
        "topic_device_id": "sim-device-001",
        "timestamp": "2026-08-20T10:30:00+00:00",
        "temperature": 28.5,
        "humidity": 64.2,
        "status": "online",
    }


def test_build_item_converts_numbers_to_decimal():
    item = telemetry.build_item(valid_event())

    assert item["device_id"] == "sim-device-001"
    assert item["temperature"] == Decimal("28.5")
    assert item["humidity"] == Decimal("64.2")
    assert "received_at" in item


def test_missing_required_field_is_rejected():
    event = valid_event()
    del event["temperature"]

    with pytest.raises(ValueError, match="temperature"):
        telemetry.build_item(event)


def test_topic_device_id_mismatch_is_rejected():
    event = valid_event()
    event["topic_device_id"] = "sim-device-002"

    with pytest.raises(ValueError, match="does not match"):
        telemetry.build_item(event)


def test_invalid_timestamp_is_rejected():
    event = valid_event()
    event["timestamp"] = "not-a-timestamp"

    with pytest.raises(ValueError, match="ISO-8601"):
        telemetry.build_item(event)


def test_lambda_handler_writes_to_dynamodb(monkeypatch):
    fake_table = FakeTable()

    monkeypatch.setattr(
        telemetry,
        "get_table",
        lambda: fake_table,
    )

    result = telemetry.lambda_handler(valid_event(), None)

    assert result["statusCode"] == 200
    assert len(fake_table.items) == 1
    assert fake_table.items[0]["device_id"] == "sim-device-001"

    response_body = json.loads(result["body"])
    assert response_body["message"] == (
        "Telemetry stored successfully"
    )