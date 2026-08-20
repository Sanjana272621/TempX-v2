import argparse
import json
import os
import random
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from awscrt import mqtt
from awsiot import mqtt_connection_builder
from dotenv import load_dotenv


load_dotenv()

IOT_ENDPOINT = os.getenv("IOT_ENDPOINT")

ROOT_CA_PATH = "certs/AmazonRootCA1.pem"

PUBLISH_INTERVAL_SECONDS = 5

MIN_PUBLISH_INTERVAL_SECONDS = 1
MAX_PUBLISH_INTERVAL_SECONDS = 300

SUPPORTED_DEVICES = [
    "sim-device-001",
    "sim-device-002",
    "sim-device-003",
]

# Stops all devices running inside this Python process.
stop_event = threading.Event()


class SimulatedDevice:
    def __init__(self, device_id):
        self.device_id = device_id

        self.cert_path = (
            f"certs/{device_id}/certificate.pem.crt"
        )
        self.private_key_path = (
            f"certs/{device_id}/private.pem.key"
        )

        # Existing telemetry topic.
        self.mqtt_topic = (
            f"devices/{self.device_id}/telemetry"
        )

        # Device Shadow topics.
        self.shadow_prefix = (
            f"$aws/things/{self.device_id}/shadow"
        )

        self.shadow_get_topic = (
            f"{self.shadow_prefix}/get"
        )
        self.shadow_get_accepted_topic = (
            f"{self.shadow_prefix}/get/accepted"
        )
        self.shadow_get_rejected_topic = (
            f"{self.shadow_prefix}/get/rejected"
        )

        self.shadow_update_topic = (
            f"{self.shadow_prefix}/update"
        )
        self.shadow_update_accepted_topic = (
            f"{self.shadow_prefix}/update/accepted"
        )
        self.shadow_update_rejected_topic = (
            f"{self.shadow_prefix}/update/rejected"
        )
        self.shadow_delta_topic = (
            f"{self.shadow_prefix}/update/delta"
        )

        # Existing simulated sensor values.
        self.temperature = 27.0
        self.humidity = 60.0

        # Each device has its own configuration.
        self.publish_interval_seconds = (
            PUBLISH_INTERVAL_SECONDS
        )
        self.telemetry_enabled = True

        # Protects configuration accessed by the MQTT
        # callback thread and telemetry thread.
        self.state_lock = threading.Lock()

        # Set whenever a shadow changes the configuration.
        # This allows an interval change to take effect quickly.
        self.configuration_changed_event = (
            threading.Event()
        )

        # Set after the initial shadow GET finishes.
        self.shadow_ready_event = threading.Event()

        self.mqtt_connection = None

    def validate_files(self):
        if not IOT_ENDPOINT:
            raise ValueError(
                "IOT_ENDPOINT is missing from the .env file"
            )

        required_files = [
            ROOT_CA_PATH,
            self.cert_path,
            self.private_key_path,
        ]

        for file_path in required_files:
            if not Path(file_path).exists():
                raise FileNotFoundError(
                    f"{self.device_id}: "
                    f"missing file {file_path}"
                )

    # MQTT connection

    def connect(self):
        self.validate_files()

        print(
            f"{self.device_id}: connecting to "
            f"{IOT_ENDPOINT}"
        )

        self.mqtt_connection = (
            mqtt_connection_builder.mtls_from_path(
                endpoint=IOT_ENDPOINT,
                cert_filepath=self.cert_path,
                pri_key_filepath=self.private_key_path,
                ca_filepath=ROOT_CA_PATH,
                client_id=self.device_id,
                clean_session=True,
                keep_alive_secs=30,
            )
        )

        connect_future = self.mqtt_connection.connect()
        connect_future.result()

        print(f"{self.device_id}: connected")

        # Subscribe before requesting the shadow.
        self.subscribe_to_shadow_topics()

        # Retrieve any desired configuration that was
        # stored while the device was offline.
        self.request_current_shadow()

        # Give AWS up to 10 seconds to return either
        # get/accepted or get/rejected.
        shadow_received = self.shadow_ready_event.wait(
            timeout=10
        )

        if shadow_received:
            print(
                f"{self.device_id}: "
                "initial shadow synchronization complete"
            )
        else:
            print(
                f"{self.device_id}: warning: "
                "shadow GET timed out; using local defaults"
            )

        # Do not allow an initial configuration-change
        # event to cause two immediate telemetry messages.
        self.configuration_changed_event.clear()

    # Shadow subscriptions

    def subscribe_to_shadow_topics(self):
        subscriptions = [
            (
                self.shadow_get_accepted_topic,
                self.on_shadow_get_accepted,
            ),
            (
                self.shadow_get_rejected_topic,
                self.on_shadow_get_rejected,
            ),
            (
                self.shadow_update_accepted_topic,
                self.on_shadow_update_accepted,
            ),
            (
                self.shadow_update_rejected_topic,
                self.on_shadow_update_rejected,
            ),
            (
                self.shadow_delta_topic,
                self.on_shadow_delta,
            ),
        ]

        for topic, callback in subscriptions:
            subscribe_future, _ = (
                self.mqtt_connection.subscribe(
                    topic=topic,
                    qos=mqtt.QoS.AT_LEAST_ONCE,
                    callback=callback,
                )
            )

            subscribe_future.result()

            print(
                f"{self.device_id}: "
                f"subscribed to {topic}"
            )

    # Shadow GET

    def request_current_shadow(self):
        print(
            f"{self.device_id}: requesting current shadow"
        )

        publish_future, _ = self.mqtt_connection.publish(
            topic=self.shadow_get_topic,
            payload="{}",
            qos=mqtt.QoS.AT_LEAST_ONCE,
        )

        # This call is made from the device thread, so
        # waiting for the publish to complete is safe.
        publish_future.result()

    def on_shadow_get_accepted(
        self,
        topic,
        payload,
        dup=None,
        qos=None,
        retain=None,
        **kwargs,
    ):
        try:
            shadow_document = json.loads(
                payload.decode("utf-8")
            )

            print(
                f"{self.device_id}: "
                "existing shadow retrieved"
            )
            print(
                json.dumps(
                    shadow_document,
                    indent=2,
                )
            )

            shadow_state = shadow_document.get(
                "state",
                {},
            )

            desired_state = shadow_state.get(
                "desired",
                {},
            )

            reported_state = shadow_state.get(
                "reported",
                {},
            )

            # This simulator does not persist configuration
            # to disk. Therefore, on restart it first restores
            # the last reported state and then overlays desired
            # values on top of it.
            effective_configuration = {
                **reported_state,
                **desired_state,
            }

            self.apply_shadow_configuration(
                effective_configuration
            )

            # Confirm the state actually being used.
            self.publish_reported_state()

        except Exception as error:
            print(
                f"{self.device_id}: "
                f"error processing shadow GET: {error}"
            )

        finally:
            self.shadow_ready_event.set()

    def on_shadow_get_rejected(
        self,
        topic,
        payload,
        dup=None,
        qos=None,
        retain=None,
        **kwargs,
    ):
        try:
            error_message = json.loads(
                payload.decode("utf-8")
            )
        except Exception:
            error_message = {
                "message": payload.decode("utf-8")
            }

        print(
            f"{self.device_id}: shadow GET rejected"
        )
        print(json.dumps(error_message, indent=2))

        if error_message.get("code") == 404:
            print(
                f"{self.device_id}: "
                "no classic shadow exists yet; "
                "creating one with default state"
            )

            # The first reported-state update creates
            # the classic shadow.
            self.publish_reported_state()

        self.shadow_ready_event.set()

    # Shadow desired/reported state

    def apply_shadow_configuration(
        self,
        configuration,
    ):
        configuration_changed = False

        with self.state_lock:
            if "publish_interval" in configuration:
                new_interval = configuration[
                    "publish_interval"
                ]

                is_valid_number = (
                    isinstance(
                        new_interval,
                        (int, float),
                    )
                    and not isinstance(
                        new_interval,
                        bool,
                    )
                )

                is_in_range = (
                    is_valid_number
                    and MIN_PUBLISH_INTERVAL_SECONDS
                    <= new_interval
                    <= MAX_PUBLISH_INTERVAL_SECONDS
                )

                if is_in_range:
                    new_interval = int(new_interval)

                    if (
                        self.publish_interval_seconds
                        != new_interval
                    ):
                        self.publish_interval_seconds = (
                            new_interval
                        )
                        configuration_changed = True

                    print(
                        f"{self.device_id}: "
                        "applied publish_interval="
                        f"{self.publish_interval_seconds}"
                    )

                else:
                    print(
                        f"{self.device_id}: rejected "
                        "invalid publish_interval="
                        f"{new_interval}"
                    )

            if "telemetry_enabled" in configuration:
                new_enabled = configuration[
                    "telemetry_enabled"
                ]

                if isinstance(new_enabled, bool):
                    if (
                        self.telemetry_enabled
                        != new_enabled
                    ):
                        self.telemetry_enabled = (
                            new_enabled
                        )
                        configuration_changed = True

                    print(
                        f"{self.device_id}: "
                        "applied telemetry_enabled="
                        f"{self.telemetry_enabled}"
                    )

                else:
                    print(
                        f"{self.device_id}: rejected "
                        "invalid telemetry_enabled="
                        f"{new_enabled}"
                    )

        if configuration_changed:
            self.configuration_changed_event.set()

        return configuration_changed

    def publish_reported_state(self):
        with self.state_lock:
            reported_interval = (
                self.publish_interval_seconds
            )
            reported_enabled = (
                self.telemetry_enabled
            )

        shadow_payload = {
            "state": {
                "reported": {
                    "publish_interval": (
                        reported_interval
                    ),
                    "telemetry_enabled": (
                        reported_enabled
                    ),
                }
            }
        }

        payload_json = json.dumps(shadow_payload)

        # Do not call future.result() here. This function
        # can be called from an MQTT callback thread.
        self.mqtt_connection.publish(
            topic=self.shadow_update_topic,
            payload=payload_json,
            qos=mqtt.QoS.AT_LEAST_ONCE,
        )

        print(
            f"{self.device_id}: "
            "published reported shadow state: "
            f"{payload_json}"
        )

    # Shadow delta

    def on_shadow_delta(
        self,
        topic,
        payload,
        dup=None,
        qos=None,
        retain=None,
        **kwargs,
    ):
        try:
            delta_message = json.loads(
                payload.decode("utf-8")
            )

            delta_state = delta_message.get(
                "state",
                {},
            )

            print(
                f"{self.device_id}: "
                "shadow delta received"
            )
            print(json.dumps(delta_state, indent=2))

            self.apply_shadow_configuration(
                delta_state
            )

            # Report the actual resulting state.
            self.publish_reported_state()

        except Exception as error:
            print(
                f"{self.device_id}: "
                f"error processing shadow delta: "
                f"{error}"
            )

    def on_shadow_update_accepted(
        self,
        topic,
        payload,
        dup=None,
        qos=None,
        retain=None,
        **kwargs,
    ):
        print(
            f"{self.device_id}: "
            "shadow update accepted by AWS"
        )

    def on_shadow_update_rejected(
        self,
        topic,
        payload,
        dup=None,
        qos=None,
        retain=None,
        **kwargs,
    ):
        try:
            error_message = json.loads(
                payload.decode("utf-8")
            )
        except Exception:
            error_message = {
                "message": payload.decode("utf-8")
            }

        print(
            f"{self.device_id}: "
            "shadow update rejected"
        )
        print(json.dumps(error_message, indent=2))

    # -----------------------------------------------------
    # Telemetry
    # -----------------------------------------------------

    def create_payload(self):
        self.temperature += random.uniform(
            -0.3,
            0.3,
        )
        self.humidity += random.uniform(
            -0.5,
            0.5,
        )

        # Retain sensible ranges.
        self.temperature = max(
            15.0,
            min(45.0, self.temperature),
        )
        self.humidity = max(
            20.0,
            min(90.0, self.humidity),
        )

        return {
            "device_id": self.device_id,
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
            "temperature": round(
                self.temperature,
                2,
            ),
            "humidity": round(
                self.humidity,
                2,
            ),
        }

    def publish_telemetry(self):
        payload = self.create_payload()
        payload_json = json.dumps(payload)

        publish_future, _ = self.mqtt_connection.publish(
            topic=self.mqtt_topic,
            payload=payload_json,
            qos=mqtt.QoS.AT_LEAST_ONCE,
        )

        publish_future.result()

        print(
            f"{self.device_id}: published "
            f"{payload_json}"
        )

    def get_current_configuration(self):
        with self.state_lock:
            return (
                self.publish_interval_seconds,
                self.telemetry_enabled,
            )

    def wait_for_next_cycle(self, interval):
        """
        Wait until:
        1. the interval finishes,
        2. shadow configuration changes, or
        3. the fleet is stopped.
        """

        deadline = time.monotonic() + interval

        while not stop_event.is_set():
            remaining = deadline - time.monotonic()

            if remaining <= 0:
                return

            configuration_changed = (
                self.configuration_changed_event.wait(
                    timeout=min(remaining, 0.5)
                )
            )

            if configuration_changed:
                self.configuration_changed_event.clear()
                return

    # -----------------------------------------------------
    # Main device lifecycle
    # -----------------------------------------------------

    def run(self):
        try:
            self.connect()

            while not stop_event.is_set():
                (
                    current_interval,
                    telemetry_enabled,
                ) = self.get_current_configuration()

                if telemetry_enabled:
                    self.publish_telemetry()
                else:
                    print(
                        f"{self.device_id}: "
                        "telemetry paused; "
                        "MQTT remains connected"
                    )

                self.wait_for_next_cycle(
                    current_interval
                )

        except Exception as error:
            print(
                f"{self.device_id}: error: {error}"
            )

        finally:
            if self.mqtt_connection is not None:
                try:
                    disconnect_future = (
                        self.mqtt_connection.disconnect()
                    )
                    disconnect_future.result()

                    print(
                        f"{self.device_id}: disconnected"
                    )

                except Exception:
                    pass


def run_device(device_id):
    device = SimulatedDevice(device_id)
    device.run()


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="TempX fleet simulator"
    )

    parser.add_argument(
        "--devices",
        nargs="+",
        choices=SUPPORTED_DEVICES,
        default=SUPPORTED_DEVICES,
        help="Devices to run",
    )

    return parser.parse_args()


def main():
    args = parse_arguments()

    print("Starting devices:")

    for device_id in args.devices:
        print(f"  - {device_id}")

    threads = []

    for device_id in args.devices:
        thread = threading.Thread(
            target=run_device,
            args=(device_id,),
            name=device_id,
        )

        thread.start()
        threads.append(thread)

    try:
        while any(
            thread.is_alive()
            for thread in threads
        ):
            for thread in threads:
                thread.join(timeout=1)

    except KeyboardInterrupt:
        print("\nStopping fleet...")
        stop_event.set()

        for thread in threads:
            thread.join(timeout=5)

        print("Fleet stopped.")


if __name__ == "__main__":
    main()