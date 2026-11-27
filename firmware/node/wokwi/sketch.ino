// Wiring check for the acoustic node. Real firmware: firmware/node.
// Pins match firmware/node/config.h.
void setup() {
  Serial.begin(115200);
  Serial.println("Acoustic node wiring");
  Serial.println("Mic bus 0 (mics 0,1): BCLK 4, WS 5, SD 6");
  Serial.println("Mic bus 1 (mics 2,3): BCLK 7, WS 15, SD 16");
  Serial.println("SEL: GND = left slot (mics 0,2), 3V3 = right slot (mics 1,3)");
  Serial.println("RFM95W: SCK 12, MISO 13, MOSI 11, CS 10, RST 9, G0 8");
}

void loop() { delay(1000); }
