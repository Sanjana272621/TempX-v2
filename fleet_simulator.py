import argparse
import json
import random
import threading
from datetime import datetime, timezone
from pathlib import Path

from awscrt import mqtt
from awsiot import mqtt_connection_builder

import os
from dotenv import load_dotenv

load_dotenv()

IOT_ENDPOINT = os.getenv("IOT_ENDPOINT")

ROOT_CA_PATH = "certs/AmazonRootCA1.pem"

PUBLISH_INTERVAL_SECONDS = 5

SUPPORTED_DEVICES = [
    "sim-device-001",
    "sim-device-002",
    "sim-device-003",
]

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

        self.mqtt_topic = (
            f"devices/{self.device_id}/telemetry"
        )

        self.temperature = 27.0
        self.humidity = 60.0

        self.mqtt_connection = None

    def validate_files(self):
        required_files = [
            ROOT_CA_PATH,
            self.cert_path,
            self.private_key_path,
        ]

        for file_path in required_files:
            if not Path(file_path).exists():
                raise FileNotFoundError(
                    f"{self.device_id}: missing file {file_path}"
                )

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

    def create_payload(self):
        self.temperature += random.uniform(-0.3, 0.3)
        self.humidity += random.uniform(-0.5, 0.5)

        return {
            "device_id": self.device_id,
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
            "temperature": round(self.temperature, 2),
            "humidity": round(self.humidity, 2),
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

    def run(self):
        try:
            self.connect()

            while not stop_event.is_set():
                self.publish_telemetry()

                stop_event.wait(
                    PUBLISH_INTERVAL_SECONDS
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
        for thread in threads:
            thread.join()

    except KeyboardInterrupt:
        print("\nStopping fleet...")
        stop_event.set()

        for thread in threads:
            thread.join()


if __name__ == "__main__":
    main()