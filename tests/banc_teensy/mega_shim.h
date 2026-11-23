// Complement du banc pour le firmware mega_monture (ATmega2560) : registres de
// ports et du Timer1, SREG/cli, ISR(TIMER1_COMPA_vect) appelee a 10 kHz par
// l'horloge virtuelle, Serial2 (GPS). Le Mega calcule en flottant 32 bits :
// le banc le compile avec `#define double float` et -fsingle-precision-constant.
#pragma once
#include "arduino_shim.h"

// Ports : PE4 = broche 2 (AZ_STEP), PE3 = 5 (ALT_STEP), PE5 = 3 (AZ_DIR), PH3 = 6 (ALT_DIR).
struct BancPort {
  uint8_t v = 0; const uint8_t* pins;
  explicit BancPort(const uint8_t* p) : pins(p) {}
  void put(uint8_t nv) {
    for (int b = 0; b < 8; b++)
      if (((v ^ nv) >> b & 1) && pins[b] != 0xFF && g_pinHook) g_pinHook(pins[b], (nv >> b) & 1);
    v = nv;
  }
  BancPort& operator|=(uint8_t m) { put(v | m); return *this; }
  BancPort& operator&=(uint8_t m) { put(v & m); return *this; }
  operator uint8_t() const { return v; }
};
static const uint8_t bancPinsE[8] = { 0xFF, 0xFF, 0xFF, 5, 2, 3, 0xFF, 0xFF };
static const uint8_t bancPinsH[8] = { 0xFF, 0xFF, 0xFF, 6, 0xFF, 0xFF, 0xFF, 0xFF };
static BancPort PORTE(bancPinsE), PORTH(bancPinsH);

// SREG : seul le bit I (0x80) compte.
struct BancSreg {
  operator uint8_t() const { return g_clk.irqOn ? 0x80 : 0; }
  BancSreg& operator=(uint8_t s) { if (s & 0x80) interrupts(); else noInterrupts(); return *this; }
};
static BancSreg SREG;
static inline void cli() { noInterrupts(); }
static inline void sei() { interrupts(); }

static uint8_t TCCR1A, TCCR1B, TIMSK1;
static uint16_t TCNT1, OCR1A;
#define WGM12 3
#define CS11 1
#define OCIE1A 1
#define ISR(v) void banc_isr_##v()

#define Serial2 Serial4
