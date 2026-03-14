// micro:bit MakeCode JavaScript
// Set to true to receive commands from Arduino via BLE (wireless)
// Set to false to receive via UART wire (pin 0 = RX, pin 1 = TX)
const USE_BLE_COMMS = true

// Set to true to simulate Arduino messages with buttons (no wiring needed)
// Button A = ALARM / stop alarm manually
// Button B = STOP (simulate car leaving)
const TEST_MODE = false

let alarming = false

function handleMessage(msg: string) {
    serial.writeLine("MSG: " + msg)
    if (msg == "ALARM") {
        alarming = true
        basic.showIcon(IconNames.Sad)

    } else if (msg == "VALID") {
        alarming = false
        music.stopAllSounds()
        basic.showIcon(IconNames.Happy)

    } else if (msg == "STOP") {
        alarming = false
        music.stopAllSounds()
        basic.showIcon(IconNames.Happy)
    }
}

// ---------- Init ----------

if (!TEST_MODE) {
    if (USE_BLE_COMMS) {
        bluetooth.startUartService()
        bluetooth.setTransmitPower(7)  // max power
    } else {
        serial.redirect(SerialPin.P0, SerialPin.P1, BaudRate.BaudRate9600)
    }
}

basic.showIcon(IconNames.Happy)
serial.writeLine("Ready. USE_BLE_COMMS=" + USE_BLE_COMMS)

// ---------- Receive messages ----------

if (!TEST_MODE && USE_BLE_COMMS) {
    bluetooth.onBluetoothConnected(function () {
        serial.writeLine("BLE connected")
    })

    bluetooth.onBluetoothDisconnected(function () {
        serial.writeLine("BLE disconnected")
    })

    bluetooth.onUartDataReceived(serial.delimiters(Delimiters.NewLine), function () {
        let msg = bluetooth.uartReadUntil(serial.delimiters(Delimiters.NewLine))
        serial.writeLine("Received: " + msg)
        handleMessage(msg)
        bluetooth.uartWriteLine("ACK")
        serial.writeLine("ACK sent")
    })
}

if (!TEST_MODE && !USE_BLE_COMMS) {
    serial.onDataReceived(serial.delimiters(Delimiters.NewLine), function () {
        let msg = serial.readUntil(serial.delimiters(Delimiters.NewLine))
        handleMessage(msg)
    })
}

// ---------- Test mode buttons ----------

input.onButtonPressed(Button.A, function () {
    if (TEST_MODE) {
        if (!alarming) {
            handleMessage("ALARM")
        } else {
            handleMessage("STOP")
        }
    } else if (alarming) {
        alarming = false
        music.stopAllSounds()
        basic.showIcon(IconNames.Happy)
    }
})

input.onButtonPressed(Button.B, function () {
    if (TEST_MODE) {
        handleMessage("STOP")
    }
})

// ---------- Alarm loop ----------

basic.forever(function () {
    if (alarming) {
        music.playTone(880, 500)
        music.playTone(440, 500)
        basic.showIcon(IconNames.No)
        basic.pause(300)
        basic.clearScreen()
        basic.pause(300)
    }
})