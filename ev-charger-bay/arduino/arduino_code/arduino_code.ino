#include <ArduinoBLE.h>

const int IR_PIN = 12;
const unsigned long PARK_TIME = 5000;
const String PARKING_LOT = "3"; // Set parking lot

bool carPresent = false;
bool parked = false;
unsigned long detectStartTime = 0;

// BLE Service and Characteristic
BLEService parkingService("180F"); // Custom Service UUID
BLEStringCharacteristic statusChar("2A19", BLERead | BLENotify, 20); // Data char

void setup() {
  Serial.begin(115200);
  pinMode(IR_PIN, INPUT);

  // Initialize BLE
  if (!BLE.begin()) {
    Serial.println("Starting BLE failed!");
    while (1);
  }

  // Set up BLE attributes
  BLE.setLocalName("ParkingSensor_3");
  BLE.setAdvertisedService(parkingService);
  parkingService.addCharacteristic(statusChar);
  BLE.addService(parkingService);
  
  // Start advertising
  BLE.advertise();
  Serial.println("Bluetooth device active, waiting for connections...");
}

void loop() {
  BLE.poll(); // Keep the BLE radio alive
  
  bool detected = (digitalRead(IR_PIN) == LOW);

  if (detected) {
    if (!carPresent) {
      carPresent = true;
      detectStartTime = millis();
      Serial.println("Car detected, checking...");
    }

    if (!parked && millis() - detectStartTime >= PARK_TIME) {
      parked = true;
      String msg = "CAR_PARKED:" + PARKING_LOT;
      Serial.println(msg);
      statusChar.setValue(msg); // Update BLE characteristic
    }
  } else {
    if (carPresent && parked) {
      String msg = "CAR_LEFT:" + PARKING_LOT;
      Serial.println(msg);
      statusChar.setValue(msg); // Update BLE characteristic
    }
    carPresent = false;
    parked = false;
  }
  delay(50);
}