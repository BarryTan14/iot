import serial
import time

PORT = "COM12"
BAUDRATE = 115200

def main():
    print(f"Opening {PORT}...")

    with serial.Serial(PORT, BAUDRATE, timeout=1) as ser:
        time.sleep(2)

        ser.reset_input_buffer()
        ser.reset_output_buffer()

        print("Sending ping...")
        ser.write(b"ping\n")
        ser.flush()

        print("Reading reply...")
        got_pong = False
        start = time.time()

        while time.time() - start < 3:
            line = ser.readline()
            if line:
                text = line.decode("utf-8", errors="ignore").strip()
                print("NICLA:", text)
                if text == "pong":
                    got_pong = True
                    break

        if got_pong:
            print("\nSUCCESS: Laptop can ping Nicla.")
        else:
            print("\nFAIL: Did not receive 'pong' from Nicla.")

if __name__ == "__main__":
    main()