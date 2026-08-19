import json
import random
import time
from datetime import datetime, timezone

from awscrt import mqtt
from awsiot import mqtt_connection_builder

import os
from dotenv import load_dotenv

load_dotenv()

DEVICE_ID = "sim-device-001"

IOT_ENDPOINT = os.getenv("IOT_ENDPOINT")

CERT_DIR = os.path.join("certs", DEVICE_ID)

CERT_PATH = os.path.join(CERT_DIR, "certificate.pem.crt")
PRIVATE_KEY_PATH = os.path.join(CERT_DIR, "private.pem.key")
ROOT_CA_PATH = os.path.join("certs", "AmazonRootCA1.pem")

MQTT_TOPIC = f"devices/{DEVICE_ID}/telemetry"

PUBLISH_INTERVAL_SECONDS = 5


temperature = 27.0
humidity = 60.0


# CREATE MQTT CONNECTION

mqtt_connection = mqtt_connection_builder.mtls_from_path(
    endpoint=IOT_ENDPOINT,
    cert_filepath=CERT_PATH,
    pri_key_filepath=PRIVATE_KEY_PATH,
    ca_filepath=ROOT_CA_PATH,

    client_id=DEVICE_ID,

    clean_session=True,
    keep_alive_secs=30
)


print(f"Connecting device: {DEVICE_ID}")


# .result() blocks until AWS responds
mqtt_connection.connect().result()


print("Connected successfully to AWS IoT Core!")

# GENERATE + PUBLISH TELEMETRY

try:

    while True:

        # Random walk instead of completely random readings.
        temperature += random.uniform(-0.3, 0.3)
        humidity += random.uniform(-0.8, 0.8)

        # Keep values inside sensible limits.
        temperature = max(15.0, min(45.0, temperature))
        humidity = max(20.0, min(90.0, humidity))

        timestamp = (
            datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )

        payload = {
            "device_id": DEVICE_ID,
            "timestamp": timestamp,
            "temperature": round(temperature, 2),
            "humidity": round(humidity, 2)
        }

        print("\nPublishing:")
        print(json.dumps(payload, indent=2))

        mqtt_connection.publish(
            topic=MQTT_TOPIC,
            payload=json.dumps(payload),
            qos=mqtt.QoS.AT_LEAST_ONCE
        )

        time.sleep(PUBLISH_INTERVAL_SECONDS)


except KeyboardInterrupt:

    print("\nStopping simulator...")


finally:

    print("Disconnecting from AWS IoT Core...")

    mqtt_connection.disconnect().result()

    print("Disconnected.")