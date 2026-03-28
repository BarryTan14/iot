import sensor
import time

try:
    import pyb
except ImportError:
    pyb = None


JPEG_QUALITY = 85
FRAME_SIZE = sensor.QQVGA


try:
    with open("bootlog.txt", "w") as f:
        f.write("=== NEW BOOT ===\n")
except Exception:
    pass


def log_file(msg):
    try:
        with open("bootlog.txt", "a") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def init_camera():
    log_file("INIT_CAMERA: start")

    sensor.reset()
    log_file("INIT_CAMERA: after reset")

    sensor.set_pixformat(sensor.RGB565)
    log_file("INIT_CAMERA: pixformat ok")

    sensor.set_framesize(FRAME_SIZE)
    log_file("INIT_CAMERA: framesize ok")

    sensor.skip_frames(time=500)
    log_file("INIT_CAMERA: skip_frames ok")

    sensor.set_auto_whitebal(True)
    log_file("INIT_CAMERA: auto_whitebal ok")
    log_file("INIT_CAMERA: done")


def capture_image():
    log_file("CAPTURE: start")
    img = sensor.snapshot()
    jpeg = img.compress(quality=JPEG_QUALITY)
    jpeg_bytes = jpeg.bytearray()
    log_file("CAPTURE: jpeg size={}".format(len(jpeg_bytes)))
    return jpeg_bytes


def get_usb_vcp():
    if pyb is None:
        raise RuntimeError("pyb.USB_VCP is unavailable on this firmware")
    return pyb.USB_VCP()


def write_line(usb, message):
    usb.write((message + "\n").encode())


def read_command(usb):
    line = usb.readline()
    if not line:
        return None
    return line.decode("utf-8", "ignore").strip().upper()


def run_serial_server():
    usb = get_usb_vcp()

    print("USB serial camera ready")
    print("Commands supported: PING, CAPTURE")
    log_file("SERIAL: ready")

    while True:
        try:
            command = read_command(usb)
            if not command:
                time.sleep_ms(50)
                continue

            print("Command:", command)
            log_file("SERIAL: command {}".format(command))

            if command == "PING":
                write_line(usb, "PONG")
                log_file("SERIAL: pong sent")

            elif command == "CAPTURE":
                jpeg_bytes = capture_image()
                write_line(usb, "IMG {}".format(len(jpeg_bytes)))
                usb.write(jpeg_bytes)
                log_file("SERIAL: image sent")

            else:
                write_line(usb, "ERR unknown_command")
                log_file("SERIAL: unknown command {}".format(command))

        except Exception as e:
            print("SERIAL ERROR:", e)
            log_file("SERIAL ERROR: {}".format(e))
            time.sleep_ms(200)


def main():
    log_file("BOOT: main start")

    try:
        init_camera()
        log_file("BOOT: camera ok")
        run_serial_server()

    except Exception as e:
        print("BOOT ERROR:", e)
        log_file("BOOT ERROR: {}".format(e))
        raise


main()
