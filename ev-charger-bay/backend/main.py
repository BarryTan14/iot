import asyncio
import json
import ssl
import serial
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from bleak import BleakClient, BleakScanner
import paho.mqtt.client as mqtt

# --- Configuration ---
TARGET_DEVICES = ["ParkingSensor_1", "ParkingSensor_2", "ParkingSensor_3"]
CHARACTERISTIC_UUID = "2A19"
MICROBIT_PORT = "COM15"
BAUDRATE = 115200

CAR_URL = "https://web-production-437da.up.railway.app/api/trigger-workflow/"
MQTT_BROKER = "2524d60d3bcf403889e8824edc2d45d5.s1.eu.hivemq.cloud"
MQTT_PORT = 8883
MQTT_USERNAME = "barry"
MQTT_PASSWORD = "Abcd1234"
MQTT_TOPIC_SUB = "iot_form"

# --- Initialization ---
microbit = serial.Serial(MICROBIT_PORT, BAUDRATE, timeout=1)


def send_to_microbit(code, lot_no):
    message = f"{code}:{lot_no}\n"
    microbit.write(message.encode('utf-8'))
    microbit.flush()
    print(f"Sent to Microbit {lot_no}: {message}")


def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("Connected to MQTT Broker!")
        client.subscribe(MQTT_TOPIC_SUB)
    else:
        print(f"Failed to connect, code {rc}")


def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode())
        event_type = data.get("type")
        lot_number = data.get("lot_number")
        if event_type == "no_submission":
            send_to_microbit("A", lot_number)
        elif event_type == "form_submitted":
            send_to_microbit("S", lot_number)
    except Exception as e:
        print(f"MQTT Error: {e}")


def create_notification_handler(device_name):
    """Creates a specific handler for each Arduino, so we know who sent the data."""

    def handler(sender, data):
        msg = data.decode('utf-8').strip()
        print(f"[{device_name}] BLE Received: {msg}")

        if ":" in msg:
            event, lot_id = msg.split(":")
            ts = datetime.now(ZoneInfo("Asia/Singapore")).strftime('%Y-%m-%dT%H:%M:%SZ')

            if event == "CAR_PARKED":
                requests.post(CAR_URL, json={"parking_lot": lot_id, "action": "entered", "timestamp": ts})
            elif event == "CAR_LEFT":
                send_to_microbit("S", lot_id)
                requests.post(CAR_URL, json={"parking_lot": lot_id, "action": "left", "timestamp": ts})

    return handler


async def manage_connection(device_name):
    """Dedicated loop for one Arduino to handle connecting and auto-reconnecting."""
    while True:
        print(f"Scanning for {device_name}...")
        device = await BleakScanner.find_device_by_name(device_name)

        if not device:
            print(f"{device_name} not found. Retrying in 5s...")
            await asyncio.sleep(5)
            continue

        try:
            async with BleakClient(device) as client_ble:
                print(f"Connected to {device_name}!")
                # Pass the device name to the handler creator
                await client_ble.start_notify(CHARACTERISTIC_UUID, create_notification_handler(device_name))

                # Keep this specific connection alive
                while client_ble.is_connected:
                    await asyncio.sleep(1)
        except Exception as e:
            print(f"Connection lost with {device_name}: {e}")
            await asyncio.sleep(2)


# --- Main Logic ---
async def main():
    # Setup MQTT
    client_mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client_mqtt.on_connect = on_connect
    client_mqtt.on_message = on_message
    client_mqtt.tls_set(cert_reqs=ssl.CERT_REQUIRED)
    client_mqtt.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client_mqtt.connect(MQTT_BROKER, MQTT_PORT, 60)
    client_mqtt.loop_start()

    # Start all 3 connection tasks at once
    connection_tasks = [manage_connection(name) for name in TARGET_DEVICES]
    await asyncio.gather(*connection_tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        microbit.close()
        print("Disconnected.")
