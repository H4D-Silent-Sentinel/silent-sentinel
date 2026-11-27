# Acoustic node wiring (Wokwi)

ESP32-S3-DevKitC-1, four ICS-43434 microphones, RFM95W LoRa radio. Pins match `../config.h`.

View: open https://wokwi.com/projects/new/esp32-s3, create each file below with the same name and contents, then the diagram draws itself. Hover a pin for its name.

| File | Content |
|---|---|
| `diagram.json` | Parts and wires |
| `ics43434.chip.json`, `rfm95w.chip.json` | Pin layout of the microphone and radio breakouts (drawing only, no simulated audio or radio) |
| `ics43434.chip.c`, `rfm95w.chip.c` | Empty part logic Wokwi requires |
| `sketch.ino` | Prints the pin map to the serial monitor |

| Wire | Signal |
|---|---|
| Red / black | 3V3 / GND |
| Orange, gold, green | I2S BCLK, WS, SD. Mics 0–1 on GPIO 4/5/6, mics 2–3 on GPIO 7/15/16 |
| SEL (black or red) | GND on mics 0 and 2 (left slot), 3V3 on mics 1 and 3 (right slot) |
| Orange, blue, purple, cyan, white, magenta | LoRa SCK 12, MISO 13, MOSI 11, CS 10, RST 9, G0 8 |
