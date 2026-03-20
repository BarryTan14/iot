from pathlib import Path
from datetime import datetime, timezone
import time
import requests
import csv
import re

from ocr_engine import OcrEngine


# =========================================================
# CHANGED FOR WIFI: removed serial PORT / BAUDRATE
# Added Nicla HTTP server config instead
# =========================================================
NICLA_IP = ""   # <-- CHANGE THIS if you use another Nicla IP: 10.176.72.250
NICLA_PORT = 80
# NICLA_CAPTURE_URL = f"http://{NICLA_IP}:{NICLA_PORT}/capture"

NICLA_CAPTURE_URL = f"http://{NICLA_IP}:{NICLA_PORT}/capture"

ROOT = Path(__file__).resolve().parent
CAPTURES_DIR = ROOT / "captures" / "gantry_1"

API_URL = "https://web-production-437da.up.railway.app/api/cars/"

OCR_CONFIDENCE_THRESHOLD = 80.0
MAX_CAPTURE_ATTEMPTS = 3
RETRY_INTERVAL_SECONDS = 3
EV_CARPLATES_CSV = ROOT / "ev_carplates.csv"
DEFAULT_CAR_TYPE = "ICE"

def get_nicla_capture_url() -> str:
    nicla_ip = input("Enter Nicla IP (shown in OpenMV boot log): ").strip()
    return f"http://{nicla_ip}:{NICLA_PORT}/capture"

def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


# =========================================================
# REMOVED FOR WIFI:
# - read_line(...)
# - read_exact(...)
# - parse_img_header(...)
# These were only for USB serial protocol
# =========================================================


def looks_like_jpeg(data: bytes) -> bool:
    return len(data) >= 4 and data[:2] == b"\xff\xd8" and data[-2:] == b"\xff\xd9"


def save_image(image_bytes: bytes, attempt_no: int | None = None) -> tuple[Path, Path]:
    ensure_dir(CAPTURES_DIR)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    if attempt_no is None:
        archive_path = CAPTURES_DIR / f"{timestamp}.jpg"
    else:
        archive_path = CAPTURES_DIR / f"{timestamp}_attempt{attempt_no}.jpg"

    latest_path = CAPTURES_DIR / "latest.jpg"

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


# =========================================================
# CHANGED FOR WIFI:
# New function replaces request_capture(ser)
# Instead of sending "capture" over serial,
# backend calls Nicla HTTP endpoint and gets JPEG bytes back
# =========================================================
def request_capture_over_http(nicla_capture_url: str) -> bytes:
    print(f"[*] Requesting image from Nicla: {nicla_capture_url}")

    response = requests.get(nicla_capture_url, timeout=20)
    response.raise_for_status()

    image_bytes = response.content

    if not looks_like_jpeg(image_bytes):
        raise ValueError("Response from Nicla is not a valid JPEG")

    return image_bytes

# =========================================================
# CHANGED FOR WIFI:
# Function signature no longer takes 'ser'
# Retry logic stays here in backend
# =========================================================
def capture_and_ocr_with_retries(ocr_engine: OcrEngine, nicla_capture_url: str) -> dict:
    last_result = None

    for attempt in range(1, MAX_CAPTURE_ATTEMPTS + 1):
        print(f"\n--- Attempt {attempt}/{MAX_CAPTURE_ATTEMPTS} ---")

        image_bytes = request_capture_over_http(nicla_capture_url)
        archive_path, latest_path = save_image(image_bytes, attempt_no=attempt)

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


def send_to_api(carplate_num: str, car_type: str) -> dict:
    payload = {
        "carplate": carplate_num,
        "type": car_type,
        "action":"entered",
        "time_entered": get_iso_utc_now(),
    }

    response = requests.post(API_URL, json=payload, timeout=10)
    response.raise_for_status()

    try:
        return response.json()
    except Exception:
        return {"status_code": response.status_code, "text": response.text}


def main():
    ensure_dir(CAPTURES_DIR)

    print("[*] Loading OCR engine...")
    ocr_engine = OcrEngine()
    print("[+] OCR engine ready.")

    print("[*] Loading EV carplate list...")
    ev_carplates = load_ev_carplates(EV_CARPLATES_CSV)
    print(f"[+] Loaded {len(ev_carplates)} EV carplate(s).")

    # =====================================================
    # CHANGED FOR WIFI:
    # Removed serial open / startup drain / ping test
    # Just print the Nicla URL we will call
    # =====================================================
    nicla_capture_url = get_nicla_capture_url()

    print("[*] Wireless capture pipeline ready.")
    print(f"[*] Nicla capture URL: {NICLA_CAPTURE_URL}")
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
            # =============================================
            # CHANGED FOR WIFI:
            # no more 'ser' argument
            # =============================================
            final_result = capture_and_ocr_with_retries(ocr_engine, nicla_capture_url)

            carplate_num = final_result["carplate_num"]
            confidence_percentage = final_result["confidence_percentage"]

            if carplate_num is None:
                print("[!] No valid carplate found after retries. Not sending to API.")
                continue

            if confidence_percentage < OCR_CONFIDENCE_THRESHOLD:
                print(
                    f"[!] Best confidence ({confidence_percentage}%) is still below "
                    f"threshold ({OCR_CONFIDENCE_THRESHOLD}%). Not sending to API."
                )
                continue

            car_type = check_car_type(carplate_num, ev_carplates)
            print(f"[*] Car type determined: {car_type}")

            print("[*] Sending result to API...")
            api_response = send_to_api(carplate_num, car_type)

            print("[+] API POST successful.")
            print("API response:", api_response)

        except requests.RequestException as e:
            print("[!] HTTP/API request failed:", e)
        except Exception as e:
            print("[!] Capture/OCR pipeline failed:", e)


if __name__ == "__main__":
    main()