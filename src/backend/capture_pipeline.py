from pathlib import Path
from datetime import datetime
import serial
import time

from ocr_engine import OcrEngine

PORT = "COM12"
BAUDRATE = 115200

ROOT = Path(__file__).resolve().parent
CAPTURES_DIR = ROOT / "captures" / "gantry_1"


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def read_line(ser: serial.Serial) -> str:
    line = ser.readline()
    if not line:
        return ""
    return line.decode("utf-8", errors="ignore").strip()


def read_exact(ser: serial.Serial, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = ser.read(size - len(data))
        if not chunk:
            raise TimeoutError(
                f"Timed out while reading image bytes "
                f"({len(data)}/{size} received)"
            )
        data += chunk
    return data


def parse_img_header(header: str) -> int:
    # Expected: IMG|12345
    parts = header.split("|")
    if len(parts) != 2 or parts[0] != "IMG":
        raise ValueError(f"Invalid image header: {header!r}")
    size = int(parts[1])
    if size <= 0:
        raise ValueError(f"Invalid image size: {size}")
    return size


def looks_like_jpeg(data: bytes) -> bool:
    return len(data) >= 4 and data[:2] == b"\xff\xd8" and data[-2:] == b"\xff\xd9"


def save_image(image_bytes: bytes) -> tuple[Path, Path]:
    ensure_dir(CAPTURES_DIR)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_path = CAPTURES_DIR / f"{timestamp}.jpg"
    latest_path = CAPTURES_DIR / "latest.jpg"

    archive_path.write_bytes(image_bytes)
    latest_path.write_bytes(image_bytes)

    return archive_path, latest_path


def drain_startup_lines(ser: serial.Serial, seconds: float = 1.5):
    start = time.time()
    while time.time() - start < seconds:
        line = read_line(ser)
        if line:
            print("NICLA:", line)


def ping_test(ser: serial.Serial) -> bool:
    ser.reset_input_buffer()
    ser.reset_output_buffer()

    ser.write(b"ping\n")
    ser.flush()

    start = time.time()
    while time.time() - start < 2:
        line = read_line(ser)
        if line:
            print("NICLA:", line)
            if line == "pong":
                return True
    return False


def request_capture(ser: serial.Serial) -> bytes:
    ser.reset_input_buffer()

    ser.write(b"capture\n")
    ser.flush()

    header = read_line(ser)
    if not header:
        raise TimeoutError("No response header from Nicla")

    print("NICLA:", header)

    if header.startswith("ERROR|"):
        raise RuntimeError(header)

    size = parse_img_header(header)
    print(f"Expecting {size} bytes...")

    image_bytes = read_exact(ser, size)

    if not looks_like_jpeg(image_bytes):
        raise ValueError("Payload does not look like a valid JPEG")

    return image_bytes


def run_ocr(ocr_engine: OcrEngine, image_path: Path) -> dict:
    result = ocr_engine.process_image(image_path)

    carplate_num = result.get("carplate_num")
    confidence_percentage = result.get("confidence_percentage", 0.0)

    return {
        "carplate_num": carplate_num,
        "confidence_percentage": confidence_percentage,
    }


def main():
    ensure_dir(CAPTURES_DIR)

    print("[*] Loading OCR engine...")
    ocr_engine = OcrEngine(confidence_threshold=0.85)
    print("[+] OCR engine ready.")

    print(f"Opening {PORT}...")

    with serial.Serial(PORT, BAUDRATE, timeout=2) as ser:
        time.sleep(2)

        print("Reading startup lines...")
        drain_startup_lines(ser)

        print("Running ping test...")
        if not ping_test(ser):
            print("FAIL: could not ping Nicla.")
            return

        print("SUCCESS: ping works.")
        print("Type 'c' to capture, 'q' to quit.")

        while True:
            cmd = input(">> ").strip().lower()

            if cmd == "q":
                print("Exiting.")
                break

            if cmd != "c":
                print("Unknown command. Use 'c' or 'q'.")
                continue

            try:
                image_bytes = request_capture(ser)
                archive_path, latest_path = save_image(image_bytes)

                print(f"Saved: {archive_path}")
                print(f"Updated: {latest_path}")

                print("[*] Running OCR...")
                ocr_result = run_ocr(ocr_engine, archive_path)

                print("OCR RESULT")
                print("carplate num:", ocr_result["carplate_num"])
                print("confidence percentage:", ocr_result["confidence_percentage"])

            except Exception as e:
                print("Capture/OCR failed:", e)


if __name__ == "__main__":
    main()