import time
import pyb
import sensor

usb = pyb.USB_VCP()
usb.setinterrupt(-1)

JPEG_QUALITY = 85
FRAME_SIZE = sensor.QVGA

def send_line(msg):
    usb.write((msg + "\n").encode())

def init_camera():
    sensor.reset()
    sensor.set_pixformat(sensor.RGB565)
    sensor.set_framesize(FRAME_SIZE)
    sensor.skip_frames(time=2000)

def send_bytes(data, chunk_size=512):
    total = len(data)
    sent_total = 0

    while sent_total < total:
        end = sent_total + chunk_size
        chunk = data[sent_total:end]
        sent = usb.write(chunk)

        if sent is None:
            # if write returns None, assume whole chunk went out
            sent = len(chunk)

        if sent <= 0:
            raise Exception("usb write failed")

        sent_total += sent

def capture_and_send():
    img = sensor.snapshot()
    jpeg = img.compress(quality=JPEG_QUALITY)
    jpeg_bytes = jpeg.bytearray()
    size = len(jpeg_bytes)

    send_line("IMG|" + str(size))
    send_bytes(jpeg_bytes)

def main():
    try:
        init_camera()
    except Exception as e:
        send_line("ERROR|INIT|" + str(e))
        while True:
            time.sleep(1)

    # boot marker
    for _ in range(3):
        send_line("BOOT|CAPTURE_V1")
        time.sleep(0.2)

    while True:
        try:
            line = usb.readline()

            if line:
                cmd = line.decode().strip()

                if cmd == "ping":
                    send_line("pong")

                elif cmd == "capture":
                    try:
                        capture_and_send()
                    except Exception as e:
                        send_line("ERROR|CAPTURE|" + str(e))

                elif cmd != "":
                    send_line("ERROR|CMD|UNKNOWN")

        except Exception as e:
            try:
                send_line("ERROR|MAIN|" + str(e))
            except:
                pass

        time.sleep(0.05)

main()