# Handicap Lot Monitor

Arduino Nano 33 BLE-based system that detects unauthorized use of handicap parking spaces using an ultrasonic sensor and iBeacon verification.

## Hardware

- **Arduino Nano 33 BLE** — main controller
- **Grove Ultrasonic Ranger** — car presence detection (max range: 4m)
- **micro:bit** — alarm output, communicates via BLE (Nordic UART Service)

## Sensor Placement

The ultrasonic sensor is mounted at the **back wall** of the parking space, facing inward toward the entrance.

**Why the back and not the front (entrance boundary)?**
- A properly parked car will always be close to the back wall (~50-100cm), well within reliable sensor range
- Mounting at the front risks false triggers from passing cars/pedestrians on the road
- The 4m max range of the sensor is not a constraint when mounted at the back, since parked cars are always nearby

**Detection threshold:** ~150-200cm. Generous enough to cover parking adjustments, tight enough to ignore anything outside the space.

## Car Presence Logic

### Arrival — Confirmation Timer
When the sensor first detects something within the threshold, a **5-second confirmation timer** starts. The car must be **continuously present** for the full 5 seconds before the system transitions to active monitoring (beacon scanning).

- If the car leaves at any point during those 5 seconds, the timer resets
- This filters out brief false triggers (pedestrians, drive-throughs)
- This also handles parking adjustments — a driver repositioning during those 5 seconds simply keeps the timer running as long as they remain within the threshold

**Why not a distance hysteresis (two thresholds)?**
A two-threshold approach (e.g. "present if < 150cm, absent if > 200cm") creates an exploitable gap. Someone aware of the thresholds could hover in the intermediate zone to manipulate the state machine. A single threshold with a continuous presence timer avoids this.

### Departure — Debounce
Once the car is confirmed parked, the system requires the spot to be continuously empty for `DEBOUNCE_MS` before declaring the car gone. This prevents brief sensor noise from resetting the alarm prematurely.

## State Machine

```
WAITING → (car present for 5s continuously) → SCANNING → (valid beacon within window) → VERIFIED
                                                        → (window expires, no beacon)  → ALARMING
VERIFIED / ALARMING → (car absent for DEBOUNCE_MS) → WAITING
```

## BLE Communication

- Arduino acts as **BLE central**, scanning for iBeacons (handicap permit tags) and for the micro:bit peripheral
- micro:bit advertises Nordic UART Service (NUS); Arduino sends `VALID`, `ALARM`, or `STOP` messages
- Comms mode configurable via `USE_BLE_COMMS` flag (BLE wireless or UART wire)