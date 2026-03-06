import time
import pyb

usb = pyb.USB_VCP()
usb.setinterrupt(-1)

def send_line(msg):
    usb.write((msg + "\n").encode("utf-8"))

for _ in range(5):
    send_line("BOOT|FINAL_PING_V2")
    time.sleep(0.2)

while True:
    try:
        line = usb.readline()
        if line:
            cmd = line.decode("utf-8", errors="ignore").strip()

            if cmd == "ping":
                send_line("pong")
            elif cmd != "":
                send_line("unknown:" + cmd)

    except Exception as e:
        try:
            send_line("ERROR|" + str(e))
        except:
            pass

    time.sleep(0.05)
