from pathlib import Path
from datetime import datetime, timezone
import csv
import io
import re
import time

from PIL import Image
import requests
import serial
from serial import SerialException
from serial.tools import list_ports

from ocr_engine import OcrEngine


ROOT = Path(__file__).resolve().parent
API_URL = "https://web-production-437da.up.railway.app/api/cars/"
OCR_CONFIDENCE_THRESHOLD = 80.0
MAX_CAPTURE_ATTEMPTS = 3
RETRY_INTERVAL_SECONDS = 3
EV_CARPLATES_CSV = ROOT / "ev_carplates.csv"
DEFAULT_CAR_TYPE = "ICE"

SERIAL_BAUDRATE = 115200
SERIAL_TIMEOUT_SECONDS = 10
SERIAL_CAPTURE_TIMEOUT_SECONDS = 20

CAMERA_CONFIGS = {
    "entered": {
        "default_port": "",
        "captures_dir": ROOT / "captures" / "entered",
    },
    "left": {
        "default_port": "",
        "captures_dir": ROOT / "captures" / "left",
    },
}


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def looks_like_jpeg(data: bytes) -> bool:
    return len(data) >= 4 and data[:2] == b"\xff\xd8" and data[-2:] == b"\xff\xd9"


def save_image(image_bytes: bytes, captures_dir: Path, attempt_no: int | None = None) -> tuple[Path, Path]:
    ensure_dir(captures_dir)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    if attempt_no is None:
        archive_path = captures_dir / f"{timestamp}.jpg"
    else:
        archive_path = captures_dir / f"{timestamp}_attempt{attempt_no}.jpg"

    latest_path = captures_dir / "latest.jpg"

    archive_path.write_bytes(image_bytes)
    latest_path.write_bytes(image_bytes)

    return archive_path, latest_path


def run_ocr(ocr_engine: OcrEngine, image_path: Path) -> dict:
    result = ocr_engine.process_image(image_path)

    carplate_num = result.get("carplate_num")
    confidence_percentage = result.get("confidence_percentage", 0.0)

    return {
        "carplate_num": carplate_num,
        "confidence_percentage": confidence_percentage,
    }


def get_iso_utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def flip_image_bytes(image_bytes: bytes) -> bytes:
    image = Image.open(io.BytesIO(image_bytes))
    flipped = image.rotate(180, expand=True)

    output = io.BytesIO()
    flipped.save(output, format="JPEG")

    return output.getvalue()


def normalize_plate_text(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", text).upper()


def load_ev_carplates(csv_path: Path) -> set[str]:
    if not csv_path.exists():
        print(f"[!] EV list not found at: {csv_path}. Defaulting all cars to ICE.")
        return set()

    ev_set = set()

    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        if "carplate" not in reader.fieldnames:
            raise ValueError(
                f"CSV must contain a 'carplate' column. Found: {reader.fieldnames}"
            )

        for row in reader:
            raw = row.get("carplate", "")
            normalized = normalize_plate_text(raw)
            if normalized:
                ev_set.add(normalized)

    return ev_set


def check_car_type(carplate_num: str, ev_carplates: set[str]) -> str:
    normalized = normalize_plate_text(carplate_num)
    return "EV" if normalized in ev_carplates else DEFAULT_CAR_TYPE


def send_to_api(carplate_num: str, action: str, car_type: str | None = None) -> dict:
    if action == "entered":
        payload = {
            "carplate": carplate_num,
            "type": car_type,
            "action": "entered",
            "time_entered": get_iso_utc_now(),
        }
    elif action == "left":
        payload = {
            "carplate": carplate_num,
            "action": "left",
            "time_left": get_iso_utc_now(),
        }
    else:
        raise ValueError(f"Unknown action: {action}")

    print("[DEBUG] Payload being sent:")
    print(payload)

    response = requests.post(API_URL, json=payload, timeout=10)

    print("[DEBUG] API status:", response.status_code)
    print("[DEBUG] API raw response:", response.text)

    response.raise_for_status()

    try:
        return response.json()
    except Exception:
        return {"status_code": response.status_code, "text": response.text}


def read_line(ser: serial.Serial) -> bytes:
    line = ser.readline()
    if not line:
        raise TimeoutError("Timed out waiting for line from Nicla")
    return line


def read_nonempty_line(ser: serial.Serial) -> bytes:
    while True:
        line = read_line(ser)
        if line.strip():
            return line


def read_exact(ser: serial.Serial, size: int) -> bytes:
    data = ser.read(size)
    if len(data) != size:
        raise TimeoutError(
            f"Timed out waiting for image bytes from Nicla ({len(data)}/{size} received)"
        )
    return data


def parse_img_header(line: bytes) -> int:
    text = line.decode("utf-8", "replace").strip()
    parts = text.split()

    if len(parts) != 2 or parts[0] != "IMG":
        raise ValueError(f"Unexpected header from Nicla: {text}")

    size = int(parts[1])
    if size <= 0:
        raise ValueError(f"Invalid image size from Nicla: {size}")

    return size


def drain_serial(ser: serial.Serial):
    try:
        waiting = ser.in_waiting
    except OSError:
        waiting = 0

    if waiting:
        ser.read(waiting)


def read_until_expected_line(ser: serial.Serial, expected: str, role: str) -> str:
    deadline = time.time() + SERIAL_TIMEOUT_SECONDS

    while time.time() < deadline:
        line = read_nonempty_line(ser).decode("utf-8", "replace").strip()
        if line == expected:
            return line

        print(f"[*] Ignoring {role} Nicla log line: {line}")

    raise TimeoutError(f"Timed out waiting for {expected} from {role} Nicla")


def validate_nicla(ser: serial.Serial, role: str) -> bool:
    print(f"[*] Checking {role} Nicla over serial...")

    drain_serial(ser)
    ser.timeout = SERIAL_TIMEOUT_SECONDS
    ser.write(b"PING\n")
    ser.flush()

    read_until_expected_line(ser, "PONG", role)
    print(f"[+] {role} Nicla is reachable on {ser.port}")
    return True


def request_capture_over_serial(ser: serial.Serial, role: str) -> bytes:
    print(f"[*] Requesting image from {role} Nicla on {ser.port}")

    drain_serial(ser)
    ser.timeout = SERIAL_CAPTURE_TIMEOUT_SECONDS
    ser.write(b"CAPTURE\n")
    ser.flush()

    header_line = None
    deadline = time.time() + SERIAL_CAPTURE_TIMEOUT_SECONDS
    while time.time() < deadline:
        candidate = read_nonempty_line(ser)
        decoded = candidate.decode("utf-8", "replace").strip()
        if decoded.startswith("IMG "):
            header_line = candidate
            break

        print(f"[*] Ignoring {role} Nicla log line: {decoded}")

    if header_line is None:
        raise TimeoutError(f"Timed out waiting for image header from {role} Nicla")

    image_size = parse_img_header(header_line)
    image_bytes = read_exact(ser, image_size)

    if not looks_like_jpeg(image_bytes):
        raise ValueError(f"{role} Nicla returned invalid JPEG data")

    return image_bytes


def capture_and_ocr_with_retries(
    ocr_engine: OcrEngine,
    ser: serial.Serial,
    role: str,
    captures_dir: Path,
) -> dict:
    last_result = None

    for attempt in range(1, MAX_CAPTURE_ATTEMPTS + 1):
        print(f"\n--- {role.upper()} attempt {attempt}/{MAX_CAPTURE_ATTEMPTS} ---")

        image_bytes = request_capture_over_serial(ser, role)
        image_bytes = flip_image_bytes(image_bytes)
        archive_path, latest_path = save_image(image_bytes, captures_dir, attempt_no=attempt)

        print(f"Saved: {archive_path}")
        print(f"Updated: {latest_path}")

        print("[*] Running OCR...")
        ocr_result = run_ocr(ocr_engine, archive_path)

        carplate_num = ocr_result["carplate_num"]
        confidence_percentage = ocr_result["confidence_percentage"]

        print("OCR RESULT")
        print("carplate num:", carplate_num)
        print("confidence percentage:", confidence_percentage)

        last_result = {
            "image_path": archive_path,
            "latest_path": latest_path,
            "carplate_num": carplate_num,
            "confidence_percentage": confidence_percentage,
            "attempt": attempt,
        }

        if carplate_num is not None and confidence_percentage >= OCR_CONFIDENCE_THRESHOLD:
            print(f"[+] Confidence >= {OCR_CONFIDENCE_THRESHOLD}%. Accepting result.")
            return last_result

        if attempt < MAX_CAPTURE_ATTEMPTS:
            print(
                f"[!] Confidence below {OCR_CONFIDENCE_THRESHOLD}% "
                f"or no valid plate found. Retrying in {RETRY_INTERVAL_SECONDS} seconds..."
            )
            time.sleep(RETRY_INTERVAL_SECONDS)

    print("[!] Max attempts reached. Using last OCR result.")
    return last_result


def list_available_serial_ports() -> list[str]:
    ports = []

    for port_info in list_ports.comports():
        label = port_info.device
        if port_info.description and port_info.description != "n/a":
            label = f"{label} - {port_info.description}"
        ports.append(label)

    return ports


def get_camera_role() -> str:
    while True:
        role = input("Enter role for this pipeline (entered/left): ").strip().lower()
        if role in CAMERA_CONFIGS:
            return role
        print("Invalid role. Enter 'entered' or 'left'.")


def open_camera_connection(role: str, default_port: str) -> serial.Serial:
    while True:
        prompt = f"Enter serial port for {role} Nicla"
        if default_port:
            prompt += f" [{default_port}]"
        prompt += ": "

        user_input = input(prompt).strip()
        port = user_input or default_port

        if not port:
            print("[!] Serial port cannot be empty.")
            continue

        try:
            ser = serial.Serial(
                port=port,
                baudrate=SERIAL_BAUDRATE,
                timeout=SERIAL_TIMEOUT_SECONDS,
                write_timeout=SERIAL_TIMEOUT_SECONDS,
            )
            time.sleep(2)
            validate_nicla(ser, role)
            return ser
        except (SerialException, OSError, TimeoutError, ValueError) as e:
            print(f"[!] Could not open {role} Nicla on {port}")
            print(f"[!] Reason: {e}")
            try:
                ser.close()
            except Exception:
                pass


def process_camera_role(
    role: str,
    ser: serial.Serial,
    captures_dir: Path,
    ocr_engine: OcrEngine,
    ev_carplates: set[str],
):
    final_result = capture_and_ocr_with_retries(
        ocr_engine=ocr_engine,
        ser=ser,
        role=role,
        captures_dir=captures_dir,
    )

    carplate_num = final_result["carplate_num"]
    confidence_percentage = final_result["confidence_percentage"]

    if carplate_num is None:
        print("[!] No valid carplate found after retries. Not sending to API.")
        return

    if confidence_percentage < OCR_CONFIDENCE_THRESHOLD:
        print(
            f"[!] Best confidence ({confidence_percentage}%) is still below "
            f"threshold ({OCR_CONFIDENCE_THRESHOLD}%). Not sending to API."
        )
        return

    if role == "entered":
        car_type = check_car_type(carplate_num, ev_carplates)
        print(f"[*] Car type determined: {car_type}")
        print("[*] Sending result to API...")
        api_response = send_to_api(
            carplate_num=carplate_num,
            action="entered",
            car_type=car_type,
        )
    else:
        print("[*] Sending result to API...")
        api_response = send_to_api(
            carplate_num=carplate_num,
            action="left",
        )

    print("[+] API POST successful.")
    print("API response:", api_response)


def main():
    print("[*] Loading OCR engine...")
    ocr_engine = OcrEngine()
    print("[+] OCR engine ready.")

    print("[*] Loading EV carplate list...")
    ev_carplates = load_ev_carplates(EV_CARPLATES_CSV)
    print(f"[+] Loaded {len(ev_carplates)} EV carplate(s).")

    available_ports = list_available_serial_ports()
    if available_ports:
        print("[*] Detected serial ports:")
        for port_label in available_ports:
            print(f"    {port_label}")
    else:
        print("[!] No serial ports detected automatically. You can still type the COM port manually.")

    role = get_camera_role()
    config = CAMERA_CONFIGS[role]
    captures_dir = config["captures_dir"]
    ensure_dir(captures_dir)

    ser = open_camera_connection(role, config["default_port"])

    print("\n[*] Wired capture pipeline ready.")
    print(f"[*] Role: {role}")
    print(f"[*] Nicla serial port: {ser.port}")
    print("Commands: c, status, q")

    try:
        while True:
            cmd = input(">> ").strip().lower()

            if cmd == "q":
                print("Exiting.")
                break

            if cmd == "status":
                try:
                    validate_nicla(ser, role)
                except Exception as e:
                    print(f"[!] {role} camera is not healthy: {e}")
                continue

            if cmd != "c":
                print("Unknown command. Use c, status, or q.")
                continue

            try:
                process_camera_role(
                    role=role,
                    ser=ser,
                    captures_dir=captures_dir,
                    ocr_engine=ocr_engine,
                    ev_carplates=ev_carplates,
                )
            except requests.RequestException as e:
                print(f"[!] HTTP/API request failed for {role} camera:", e)
            except Exception as e:
                print(f"[!] Capture/OCR pipeline failed for {role} camera:", e)
    finally:
        if ser.is_open:
            ser.close()


if __name__ == "__main__":
    main()
