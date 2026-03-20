import network
import socket
import sensor
import time

# -----------------------------
# WIFI CONFIG
# -----------------------------
SSID = "AndroidAPEdric"
PASSWORD = "12345678"

PORT = 80

JPEG_QUALITY = 85
FRAME_SIZE = sensor.QVGA

# -----------------------------
# BOOT LOG FILE
# -----------------------------
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


# -----------------------------
# CAMERA INIT
# -----------------------------
def init_camera():
    log_file("INIT_CAMERA: start")

    sensor.reset()
    log_file("INIT_CAMERA: after reset")

    sensor.set_pixformat(sensor.RGB565)
    log_file("INIT_CAMERA: pixformat ok")

    sensor.set_framesize(FRAME_SIZE)
    log_file("INIT_CAMERA: framesize ok")

    sensor.skip_frames(time=2000)
    log_file("INIT_CAMERA: skip_frames ok")

    # auto gain unsupported on your sensor
    # sensor.set_auto_gain(True)

    sensor.set_auto_whitebal(True)
    log_file("INIT_CAMERA: auto_whitebal ok")
    log_file("INIT_CAMERA: done")


# -----------------------------
# WIFI CONNECT (DHCP)
# -----------------------------
def connect_wifi():
    log_file("CONNECT_WIFI: start")

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    log_file("CONNECT_WIFI: wlan active")

    wlan.connect(SSID, PASSWORD)
    log_file("CONNECT_WIFI: connect called")

    print("Connecting to WiFi...")
    log_file("CONNECT_WIFI: waiting for connection")

    attempts = 0
    while not wlan.isconnected():
        attempts += 1
        log_file("CONNECT_WIFI: waiting {}".format(attempts))
        time.sleep(1)

        if attempts >= 20:
            log_file("CONNECT_WIFI: timeout")
            raise Exception("WiFi connection timeout")

    ip = wlan.ifconfig()[0]

    print("Connected!")
    print("IP:", ip)

    log_file("CONNECT_WIFI: connected ip={}".format(ip))
    return ip


# -----------------------------
# CAPTURE IMAGE
# -----------------------------
def capture_image():
    log_file("CAPTURE: start")
    img = sensor.snapshot()
    jpeg = img.compress(quality=JPEG_QUALITY)
    jpeg_bytes = jpeg.bytearray()
    log_file("CAPTURE: jpeg size={}".format(len(jpeg_bytes)))
    return jpeg_bytes


# -----------------------------
# SEND ALL DATA IN CHUNKS
# -----------------------------
def send_all(sock, data, chunk_size=1024):
    total_sent = 0
    data_len = len(data)

    while total_sent < data_len:
        end = total_sent + chunk_size
        chunk = data[total_sent:end]
        sent = sock.send(chunk)

        if sent is None or sent <= 0:
            raise Exception("Socket send failed")

        total_sent += sent


# -----------------------------
# START HTTP SERVER
# -----------------------------
def start_server():
    log_file("SERVER: start")

    addr = socket.getaddrinfo("0.0.0.0", PORT)[0][-1]
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(addr)
    server.listen(1)

    print("Server listening on port", PORT)
    log_file("SERVER: listening on port {}".format(PORT))

    while True:
        client = None
        try:
            log_file("SERVER: waiting for client")
            client, addr = server.accept()

            print("Client connected:", addr)
            log_file("SERVER: client connected {}".format(addr))

            request = client.recv(1024)

            if not request:
                log_file("SERVER: empty request")
                client.close()
                continue

            request_str = request.decode()
            log_file("SERVER: request received")

            if "GET /capture" in request_str:
                print("Capture requested")
                log_file("SERVER: capture requested")

                jpeg_bytes = capture_image()

                header = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: image/jpeg\r\n"
                    "Content-Length: {}\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                ).format(len(jpeg_bytes))

                client.send(header.encode())
                send_all(client, jpeg_bytes)

                log_file("SERVER: image sent")

            else:
                msg = "HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\n"
                client.send(msg.encode())
                log_file("SERVER: 404 sent")

        except Exception as e:
            print("SERVER ERROR:", e)
            log_file("SERVER ERROR: {}".format(e))

        finally:
            if client:
                try:
                    client.close()
                except Exception:
                    pass


# -----------------------------
# MAIN
# -----------------------------
def main():
    log_file("BOOT: main start")

    try:
        init_camera()
        log_file("BOOT: camera ok")

        ip = connect_wifi()
        log_file("BOOT: wifi ok ip={}".format(ip))

        print("Camera server ready")
        print("Capture URL:")
        print("http://{}:{}/capture".format(ip, PORT))

        log_file("BOOT: server starting")
        start_server()

    except Exception as e:
        print("BOOT ERROR:", e)
        log_file("BOOT ERROR: {}".format(e))
        raise


main()
