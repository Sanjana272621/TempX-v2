import json
from typing import Any


def build_reported_state(
    device_state: dict[str, Any],
) -> str:
    payload = {
        "state": {
            "reported": device_state,
        }
    }

    return json.dumps(payload)


def apply_shadow_delta(
    current_state: dict[str, Any],
    delta_payload: dict[str, Any],
) -> dict[str, Any]:
    requested_state = delta_payload.get("state", {})

    if not isinstance(requested_state, dict):
        raise ValueError("Shadow delta state must be an object")

    updated_state = current_state.copy()
    updated_state.update(requested_state)

    return updated_state


def shadow_topics(device_id: str) -> dict[str, str]:
    prefix = f"$aws/things/{device_id}/shadow"

    return {
        "get": f"{prefix}/get",
        "get_accepted": f"{prefix}/get/accepted",
        "get_rejected": f"{prefix}/get/rejected",
        "update": f"{prefix}/update",
        "update_accepted": f"{prefix}/update/accepted",
        "update_rejected": f"{prefix}/update/rejected",
        "delta": f"{prefix}/update/delta",
    }