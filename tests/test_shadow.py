import json

import pytest

from simulator.shadow import (
    apply_shadow_delta,
    build_reported_state,
    shadow_topics,
)


def test_build_reported_shadow_payload():
    payload = build_reported_state(
        {
            "status": "online",
            "publish_interval": 5,
        }
    )

    document = json.loads(payload)

    assert document["state"]["reported"]["status"] == "online"
    assert (
        document["state"]["reported"]["publish_interval"]
        == 5
    )


def test_apply_shadow_delta():
    current = {
        "publish_interval": 5,
        "enabled": True,
    }

    delta = {
        "state": {
            "publish_interval": 10,
        }
    }

    updated = apply_shadow_delta(current, delta)

    assert updated["publish_interval"] == 10
    assert updated["enabled"] is True


def test_invalid_delta_is_rejected():
    with pytest.raises(ValueError):
        apply_shadow_delta(
            {"enabled": True},
            {"state": "invalid"},
        )


def test_shadow_topics_use_correct_device_id():
    topics = shadow_topics("sim-device-003")

    assert topics["update"] == (
        "$aws/things/sim-device-003/shadow/update"
    )
    assert topics["delta"].endswith("/shadow/update/delta")