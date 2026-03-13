#include <Arduino.h>
#include <ArduinoBLE.h>

// --- CONFIG ---
// Comms mode to micro:bit:
// COMMS_BLE    = send via BLE UART (wireless, standalone)
// COMMS_BRIDGE = send via USB serial bridge (laptop as middleman, allows speaker)
// COMMS_WIRE   = send via UART wire (Serial1 TX/RX, direct pin connection)
enum CommsMode { COMMS_BLE, COMMS_BRIDGE, COMMS_WIRE };
const CommsMode COMMS_MODE = COMMS_BLE;

// RSSI range guide:
// -40  = touching (~0.1m)
// -50  = very close (~0.3m)
// -60  = close (~0.5-1m)
// -70  = medium (~2-5m)
// -80  = far (~5-10m)
// -90  = very far (~10m+)
const int RSSI_THRESHOLD  = -50;

const int CAR_PRESENT_CM     = 20;    // car present if distance < 20cm (prototype scale)

const unsigned long CONFIRM_MS       = 2000;   // car must be present continuously for 2s to confirm arrival (prototype)
const unsigned long SCAN_WINDOW_MS   = 10000;  // time window to scan beacon after car confirmed
const unsigned long SCAN_COOLDOWN_MS = 5000;   // ignore beacon for 5s after reset
const unsigned long DEBOUNCE_MS      = 3000;   // car must be absent for 3s to confirm it left

// Ultrasonic Ranger on pin 11 (Grove single-pin interface)
const int ULTRASONIC_PIN = 11;

// BLE-safe ultrasonic using hardware interrupts instead of pulseIn().
// pulseIn() disables interrupts which corrupts the nRF52840 BLE SoftDevice.
// This approach uses attachInterrupt() so BLE radio events keep firing.
volatile unsigned long echoStart = 0;
volatile unsigned long echoEnd = 0;
volatile bool echoDone = false;

void echoISR() {
    if (digitalRead(ULTRASONIC_PIN) == HIGH) {
        echoStart = micros();
    } else {
        echoEnd = micros();
        echoDone = true;
    }
}

long measureCm() {
    echoDone = false;
    echoStart = 0;
    echoEnd = 0;

    // Send trigger pulse
    detachInterrupt(digitalPinToInterrupt(ULTRASONIC_PIN));
    pinMode(ULTRASONIC_PIN, OUTPUT);
    digitalWrite(ULTRASONIC_PIN, LOW);
    delayMicroseconds(2);
    digitalWrite(ULTRASONIC_PIN, HIGH);
    delayMicroseconds(5);
    digitalWrite(ULTRASONIC_PIN, LOW);

    // Switch to input and attach interrupt for echo
    pinMode(ULTRASONIC_PIN, INPUT);
    attachInterrupt(digitalPinToInterrupt(ULTRASONIC_PIN), echoISR, CHANGE);

    // Wait for echo — BLE interrupts keep firing during this loop
    unsigned long start = millis();
    while (!echoDone && (millis() - start < 50)) {
        // yield to BLE stack
    }

    detachInterrupt(digitalPinToInterrupt(ULTRASONIC_PIN));

    if (!echoDone || echoEnd <= echoStart) return 999;
    unsigned long duration = echoEnd - echoStart;
    return duration / 29 / 2;
}
// --------------

// iBeacon recognized beacons: UUID + Major + Minor -> Name
struct Beacon {
    const char* uuid;
    uint16_t major;
    uint16_t minor;
    const char* name;
};

// --- BEACON VALUES ---
const Beacon recognizedBeacons[] = {
    {"E2C56DB5-DFFB-48D2-B060-D0F5A71096E0", 46212, 3, "Faded Label"},
    {"E2C56DB5-DFFB-48D2-B060-D0F5A71096E2", 46212, 2, "Clear Label"}
};
// ------------------------------------

const int NUM_BEACONS = sizeof(recognizedBeacons) / sizeof(recognizedBeacons[0]);

// State machine
enum State {
    WAITING,        // no car present
    CONFIRMING,     // car first detected, waiting for continuous presence to confirm
    SCANNING,       // car confirmed parked, waiting for beacon scan
    VERIFIED,       // valid beacon scanned, car authorized
    ALARMING        // time expired, alarm active
};

State state = WAITING;
unsigned long carArrivedAt = 0;
unsigned long carConfirmedAt = 0;
unsigned long carLeftAt = 0;
unsigned long lastResetAt = 0;
bool validScanReceived = false;

// Cached distance — only measure every 500ms to give BLE time to breathe
long lastDist = 999;
unsigned long lastMeasureAt = 0;
const unsigned long MEASURE_INTERVAL_MS = 500;

// ---------- BLE comms to micro:bit ----------

// Arduino acts as BLE central — scans for micro:bit peripheral and connects to it
// micro:bit advertises Nordic UART Service (NUS) via MakeCode bluetooth.startUartService()
// NUS Service UUID:     6E400001-B5A3-F393-E0A9-E50E24DCCA9E
// NUS RX Characteristic:6E400002-B5A3-F393-E0A9-E50E24DCCA9E (Arduino writes msg here)
// NUS TX Characteristic:6E400003-B5A3-F393-E0A9-E50E24DCCA9E (micro:bit writes ACK here)

// ---------- iBeacon parsing ----------

bool parseiBeacon(BLEDevice& peripheral, String& uuid, uint16_t& major, uint16_t& minor) {
    int len = peripheral.manufacturerDataLength();
    if (len < 25) return false;

    uint8_t data[25];
    peripheral.manufacturerData(data, len);

    if (data[0] != 0x4C || data[1] != 0x00) return false;
    if (data[2] != 0x02 || data[3] != 0x15) return false;

    char uuidStr[37];
    snprintf(uuidStr, sizeof(uuidStr),
        "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
        data[4],  data[5],  data[6],  data[7],
        data[8],  data[9],
        data[10], data[11],
        data[12], data[13],
        data[14], data[15], data[16], data[17], data[18], data[19]);
    uuid = String(uuidStr);

    major = (data[20] << 8) | data[21];
    minor = (data[22] << 8) | data[23];

    return true;
}

const char* findBeacon(const String& uuid, uint16_t major, uint16_t minor) {
    for (const auto recognizedBeacon : recognizedBeacons) {
        if (uuid.equalsIgnoreCase(recognizedBeacon.uuid) &&
            major == recognizedBeacon.major &&
            minor == recognizedBeacon.minor) {
            return recognizedBeacon.name;
        }
    }
    return nullptr;
}

// ---------- Send message to micro:bit ----------

bool trySendBLE(const char* msg) {
    BLE.stopScan();
    BLE.scan();

    BLEDevice microbit;
    unsigned long scanTimeout = millis();
    while (millis() - scanTimeout < 10000) {
        BLEDevice found = BLE.available();
        if (found && String(found.localName()).startsWith("BBC micro:bit")) {
            microbit = found;
            break;
        }
    }
    BLE.stopScan();

    if (!microbit) {
        Serial.println("BLE: micro:bit not found.");
        BLE.scan();
        return false;
    }

    delay(500);
    if (!microbit.connect()) {
        Serial.println("BLE: Connection failed.");
        BLE.scan();
        return false;
    }

    if (!microbit.discoverAttributes()) {
        Serial.println("BLE: Failed to discover attributes.");
        microbit.disconnect();
        BLE.scan();
        return false;
    }

    BLECharacteristic rxChar = microbit.characteristic("6E400003-B5A3-F393-E0A9-E50E24DCCA9E");
    if (!rxChar) {
        Serial.println("BLE: RX characteristic not found.");
        microbit.disconnect();
        BLE.scan();
        return false;
    }

    String payload = String(msg) + "\n";
    bool writeOk = rxChar.writeValue(payload.c_str(), payload.length(), false);
    Serial.print("BLE: Sent \""); Serial.print(msg); Serial.print("\" writeOk="); Serial.println(writeOk);

    delay(200);
    microbit.disconnect();

    BLE.scan();
    return writeOk;
}

void sendToMicrobit(const char* msg) {
    if (COMMS_MODE == COMMS_BLE) {
        for (int attempt = 0; attempt < 3; attempt++) {
            if (attempt > 0) {
                Serial.print("BLE: Retry "); Serial.println(attempt + 1);
                delay(2000);
            }
            if (trySendBLE(msg)) {
                Serial.println("BLE: Message delivered.");
                return;
            }
        }
        Serial.println("BLE: Failed to deliver message after retries.");

    } else if (COMMS_MODE == COMMS_BRIDGE) {
        Serial.print("CMD:");
        Serial.println(msg);

    } else {
        Serial1.println(msg);
    }
}

// ---------- Setup ----------

void setup() {
    Serial.begin(9600);
    if (COMMS_MODE == COMMS_WIRE) Serial1.begin(9600);
    delay(1000);

    if (!BLE.begin()) {
        Serial.println("Error: Could not start BLE!");
        while (1);
    }

    BLE.scan();
    delay(2000);  // wait for serial monitor to connect and sensor to stabilize

    Serial.println("System ready. Waiting for car...");
    Serial.print("Comms mode: ");
    const char* modeNames[] = {"BLE (wireless)", "Serial Bridge", "UART (wire)"};
    Serial.println(modeNames[COMMS_MODE]);
}

// ---------- Loop ----------

void loop() {
    // Only measure every MEASURE_INTERVAL_MS — pulseIn() blocks interrupts
    // and destroys BLE state if called too frequently
    if (millis() - lastMeasureAt >= MEASURE_INTERVAL_MS) {
        lastDist = measureCm();
        lastMeasureAt = millis();
    }
    bool carPresent = (lastDist < CAR_PRESENT_CM);

    switch (state) {

        case WAITING:
            if (carPresent) {
                state = CONFIRMING;
                carArrivedAt = millis();
                Serial.println("Car detected. Confirming presence...");
            }
            break;

        case CONFIRMING:
            if (!carPresent) {
                // Car left during confirmation window — false trigger, reset
                Serial.println("False trigger. Resetting.");
                carArrivedAt = 0;
                state = WAITING;
            } else if (millis() - carArrivedAt >= CONFIRM_MS) {
                // Car has been continuously present for CONFIRM_MS — confirmed parked
                state = SCANNING;
                carConfirmedAt = millis();
                validScanReceived = false;
                Serial.println("Car confirmed parked. Waiting for beacon scan...");
            }
            break;

        case SCANNING: {
            if (!carPresent) {
                if (carLeftAt == 0) carLeftAt = millis();
                if (millis() - carLeftAt >= DEBOUNCE_MS) {
                    Serial.println("Car left before scanning. Resetting.");
                    carLeftAt = 0;
                    lastResetAt = millis();
                    state = WAITING;
                }
                break;
            } else {
                carLeftAt = 0;
            }

            // Check if time window has expired
            if (millis() - carConfirmedAt >= SCAN_WINDOW_MS) {
                state = ALARMING;
                Serial.println("Time expired! Sending ALARM to micro:bit.");
                sendToMicrobit("ALARM");
                break;
            }

            // Scan for beacons (ignore during cooldown after reset)
            if (millis() - lastResetAt < SCAN_COOLDOWN_MS) break;
            BLEDevice peripheral = BLE.available();
            if (peripheral) {
                String uuid;
                uint16_t major, minor;
                if (parseiBeacon(peripheral, uuid, major, minor)) {
                    const char* beaconName = findBeacon(uuid, major, minor);
                    if (beaconName && peripheral.rssi() > RSSI_THRESHOLD) {
                        validScanReceived = true;
                        state = VERIFIED;
                        Serial.print("Access Granted: ");
                        Serial.println(beaconName);
                        sendToMicrobit("VALID");
                    }
                }
            }
            break;
        }

        case VERIFIED:
            if (!carPresent) {
                if (carLeftAt == 0) carLeftAt = millis();
                if (millis() - carLeftAt >= DEBOUNCE_MS) {
                    Serial.println("Authorized car left. Resetting.");
                    sendToMicrobit("STOP");
                    carLeftAt = 0;
                    lastResetAt = millis();
                    state = WAITING;
                }
            } else {
                carLeftAt = 0;
            }
            break;

        case ALARMING:
            if (!carPresent) {
                if (carLeftAt == 0) carLeftAt = millis();
                if (millis() - carLeftAt >= DEBOUNCE_MS) {
                    Serial.println("Car left. Stopping alarm.");
                    sendToMicrobit("STOP");
                    carLeftAt = 0;
                    lastResetAt = millis();
                    state = WAITING;
                }
            } else {
                carLeftAt = 0;
            }
            break;
    }
}