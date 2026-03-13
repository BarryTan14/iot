#!/usr/bin/env python3
"""
Serial bridge: reads from Arduino, forwards commands to micro:bit.
Both devices connected to Mac via USB.

Usage: python3 serial_bridge.py [arduino_port] [microbit_port]
"""

import serial
import sys
import time

ARDUINO_PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/cu.usbmodem2101"
MICROBIT_PORT = sys.argv[2] if len(sys.argv) > 2 else "/dev/cu.usbmodem11202"
ARDUINO_BAUD = 9600
MICROBIT_BAUD = 115200  # micro:bit v2 default USB serial baud rate

COMMANDS = {"ALARM", "VALID", "STOP"}

def main():
    print(f"Arduino port: {ARDUINO_PORT}")
    print(f"micro:bit port: {MICROBIT_PORT}")

    arduino = serial.Serial(ARDUINO_PORT, ARDUINO_BAUD, timeout=1)
    microbit = serial.Serial(MICROBIT_PORT, MICROBIT_BAUD, timeout=1)
    time.sleep(2)  # wait for serial connections to stabilize

    print("Bridge running. Ctrl+C to stop.\n")

    while True:
        line = arduino.readline().decode("utf-8", errors="replace").strip()
        if not line:
            continue

        print(f"[Arduino] {line}")

        # Arduino sends "CMD:ALARM", "CMD:VALID", or "CMD:STOP"
        if line.startswith("CMD:"):
            cmd = line[4:]
            print(f"  >>> Forwarding '{cmd}' to micro:bit")
            microbit.write((cmd + "\n").encode())
            # Read any response from micro:bit
            time.sleep(0.5)
            while microbit.in_waiting:
                resp = microbit.readline().decode("utf-8", errors="replace").strip()
                if resp:
                    print(f"  [micro:bit] {resp}")

if __name__ == "__main__":
    main()
