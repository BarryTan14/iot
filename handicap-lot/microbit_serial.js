// micro:bit MakeCode JavaScript — USB Serial mode (no Bluetooth)
// Receives commands from Arduino via serial_bridge.py on Mac
// IMPORTANT: Remove the "bluetooth" extension from pxt.json in MakeCode

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

music.setBuiltInSpeakerEnabled(true)
music.setVolume(255)
basic.showIcon(IconNames.Happy)
serial.writeLine("Ready. Mode=Serial")

// ---------- Receive messages via USB serial ----------

if (!TEST_MODE) {
    serial.onDataReceived(serial.delimiters(Delimiters.NewLine), function () {
        let msg = serial.readUntil(serial.delimiters(Delimiters.NewLine))
        handleMessage(msg)
    })
}

// ---------- Test mode / manual stop buttons ----------

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