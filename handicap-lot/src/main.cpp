#include <Arduino.h>
#include <ArduinoBLE.h>

// --- CONFIG ---
// Set to true to send messages to micro:bit via BLE (wireless)
// Set to false to send via UART wire (Serial1 TX/RX)
const bool USE_BLE_COMMS = true;

// RSSI range guide:
// -40  = touching (~0.1m)
// -50  = very close (~0.3m)
// -60  = close (~0.5-1m)
// -70  = medium (~2-5m)
// -80  = far (~5-10m)
// -90  = very far (~10m+)
const int RSSI_THRESHOLD  = -50;

// NOTE: Grove IR Distance Interrupter is not ideal for outdoor car detection.
// It has a short range (7.5-40cm), is affected by sunlight, and can give false positives.
// Recommended upgrade: HC-SR04 ultrasonic sensor (range up to 4m, not affected by sunlight,
// cheap, Grove compatible). Inductive loop sensors are the industry standard but require
// pavement installation.
const int IR_PIN          = 11;    // Grove IR Distance Interrupter on D11

const unsigned long SCAN_WINDOW_MS   = 10000;  // 1 minute to scan beacon
const unsigned long SCAN_COOLDOWN_MS = 5000;   // ignore beacon for 5s after reset
const unsigned long DEBOUNCE_MS      = 1000;   // car must be absent for 1s to confirm it left
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
    SCANNING,       // car detected, waiting for beacon scan
    VERIFIED,       // valid beacon scanned, car authorized
    ALARMING        // time expired, alarm active
};

State state = WAITING;
unsigned long carArrivedAt = 0;
unsigned long carLeftAt = 0;
unsigned long lastResetAt = 0;
bool validScanReceived = false;

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

void sendToMicrobit(const char* msg) {
    if (USE_BLE_COMMS) {
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
            return;
        }

        delay(500);  // give micro:bit time to recover between connections
        if (!microbit.connect()) {
            Serial.println("BLE: Connection failed.");
            BLE.scan();
            return;
        }

        if (!microbit.discoverAttributes()) {
            Serial.println("BLE: Failed to discover attributes.");
            microbit.disconnect();
            BLE.scan();
            return;
        }

        // NUS UUIDs are swapped in MakeCode: 6E400003 is writable (Arduino→micro:bit)
        BLECharacteristic rxChar = microbit.characteristic("6E400003-B5A3-F393-E0A9-E50E24DCCA9E");
        if (!rxChar) {
            Serial.println("BLE: RX characteristic not found.");
            microbit.disconnect();
            BLE.scan();
            return;
        }


        // Write message with newline delimiter (NUS RX uses write-without-response)
        String payload = String(msg) + "\n";
        bool writeOk = rxChar.writeValue(payload.c_str(), payload.length(), false);
        Serial.print("BLE: Sent \""); Serial.print(msg); Serial.print("\" writeOk="); Serial.println(writeOk);

        delay(200);
        microbit.disconnect();

        BLE.scan();
        Serial.println("BLE: Back to scanning mode.");

    } else {
        Serial1.println(msg);
    }
}

// ---------- Setup ----------

void setup() {
    Serial.begin(9600);
    if (!USE_BLE_COMMS) Serial1.begin(9600);
    delay(1000);

    pinMode(IR_PIN, INPUT);

    if (!BLE.begin()) {
        Serial.println("Error: Could not start BLE!");
        while (1);
    }

    BLE.scan();
    delay(2000);  // wait for serial monitor to connect and sensor to stabilize

    // Discard false triggers on startup — wait until sensor reads stable HIGH (no car)
    while (digitalRead(IR_PIN) == LOW) {
        delay(100);
    }

    Serial.println("System ready. Waiting for car...");
    Serial.print("Comms mode: ");
    Serial.println(USE_BLE_COMMS ? "BLE (wireless)" : "UART (wire)");
}

// ---------- Loop ----------

void loop() {
    bool carPresent = (digitalRead(IR_PIN) == LOW);  // LOW = beam broken = car present


    switch (state) {

        case WAITING:
            if (carPresent) {
                state = SCANNING;
                carArrivedAt = millis();
                validScanReceived = false;
                Serial.println("Car detected. Waiting for beacon scan...");
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
            if (millis() - carArrivedAt >= SCAN_WINDOW_MS) {
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