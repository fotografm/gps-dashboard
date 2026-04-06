/*
 * tbeam_gps_passthrough.ino v2
 * T-Beam v1.2 (AXP2101) GPS NMEA Passthrough
 *
 * Powers GPS via AXP2101 DLDO1, enables all NMEA sentences
 * (including GPGSV for satellite SNR bars) via UBX CFG-MSG,
 * then relays NMEA to USB serial at 115200 baud.
 *
 * Board: TTGO T1 (esp32:esp32:ttgo-t1)
 * Flash merged.bin at offset 0x0 via esptool.spacehuhn.com
 *
 * Key change from v1: USB->GPS relay removed to prevent
 * accidental GPS config corruption. GSV enabled on startup.
 */

#include <Wire.h>
#include <HardwareSerial.h>

#define GPS_RX_PIN    34
#define GPS_TX_PIN    12
#define I2C_SDA       21
#define I2C_SCL       22

#define AXP2101_ADDR      0x34
#define AXP2101_DLDO1_VOL 0x99
#define AXP2101_DLDO_EN   0x9C

#define GPS_BAUD   9600
#define USB_BAUD   115200

HardwareSerial gpsSerial(1);


// ── AXP2101 ─────────────────────────────────────────────────

void axpWrite(uint8_t reg, uint8_t val) {
    Wire.beginTransmission(AXP2101_ADDR);
    Wire.write(reg); Wire.write(val);
    Wire.endTransmission();
}

uint8_t axpRead(uint8_t reg) {
    Wire.beginTransmission(AXP2101_ADDR);
    Wire.write(reg);
    Wire.endTransmission(false);
    Wire.requestFrom((uint8_t)AXP2101_ADDR, (uint8_t)1);
    return Wire.available() ? Wire.read() : 0xFF;
}

void enableGPSPower() {
    axpWrite(AXP2101_DLDO1_VOL, 0x1C);  // 3.3V
    delay(20);
    axpWrite(AXP2101_DLDO_EN, axpRead(AXP2101_DLDO_EN) | 0x01);
    delay(100);
}


// ── UBX CFG-MSG ─────────────────────────────────────────────
// Enable one NMEA sentence on UART1 at rate 1 (every fix)
// NMEA class 0xF0: GGA=0x00 GLL=0x01 GSA=0x02 GSV=0x03 RMC=0x04 VTG=0x05

void enableNMEA(uint8_t msgId) {
    // CFG-MSG payload: msgClass, msgId, rates for 6 ports
    // We set UART1 (index 2) = 1, rest = 0
    uint8_t payload[8] = {0xF0, msgId, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00};

    // Calculate checksum over: class(0x06) id(0x01) len(0x08,0x00) payload
    uint8_t ck_a = 0, ck_b = 0;
    uint8_t toCheck[] = {0x06, 0x01, 0x08, 0x00,
                         payload[0], payload[1], payload[2], payload[3],
                         payload[4], payload[5], payload[6], payload[7]};
    for (size_t i = 0; i < sizeof(toCheck); i++) {
        ck_a += toCheck[i];
        ck_b += ck_a;
    }

    uint8_t msg[16] = {
        0xB5, 0x62,
        0x06, 0x01,
        0x08, 0x00,
        payload[0], payload[1], payload[2], payload[3],
        payload[4], payload[5], payload[6], payload[7],
        ck_a, ck_b
    };

    gpsSerial.write(msg, 16);
    gpsSerial.flush();
    delay(150);
}

void enableAllNMEA() {
    enableNMEA(0x00);  // GGA — position, altitude, fix quality
    enableNMEA(0x01);  // GLL — position
    enableNMEA(0x02);  // GSA — DOP and active satellites
    enableNMEA(0x03);  // GSV — satellites in view + SNR bars
    enableNMEA(0x04);  // RMC — speed, track, date
    enableNMEA(0x05);  // VTG — speed over ground
}


// ── Setup ────────────────────────────────────────────────────

void setup() {
    Serial.begin(USB_BAUD);
    delay(500);
    Serial.println("=== T-Beam GPS Passthrough v2 ===");

    Wire.begin(I2C_SDA, I2C_SCL);
    delay(100);

    Wire.beginTransmission(AXP2101_ADDR);
    if (Wire.endTransmission() == 0) {
        Serial.println("AXP2101 found - enabling GPS power (DLDO1=3.3V)...");
        enableGPSPower();
        Serial.println("GPS power on.");
    } else {
        Serial.println("WARNING: AXP2101 not found at 0x34.");
    }

    gpsSerial.begin(GPS_BAUD, SERIAL_8N1, GPS_RX_PIN, GPS_TX_PIN);
    delay(1000);  // let GPS fully wake before sending UBX

    Serial.println("Enabling NMEA sentences: GGA GLL GSA GSV RMC VTG...");
    enableAllNMEA();
    Serial.println("Done. Streaming NMEA...");
    Serial.println("---");
}


// ── Loop ─────────────────────────────────────────────────────

void loop() {
    // Relay GPS -> USB only
    // USB -> GPS relay intentionally removed to protect GPS config
    while (gpsSerial.available()) {
        Serial.write(gpsSerial.read());
    }
}
