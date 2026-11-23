#pragma once
#include "../arduino_shim.h"
#define MSBFIRST 1
#define SPI_MODE3 3
struct SPISettings { SPISettings(uint32_t, int, int) {} };
struct BancSPI {
  void setMISO(int) {}
  void begin() {}
  void beginTransaction(SPISettings) {}
  void endTransaction() {}
  uint8_t transfer(uint8_t) { return 0; }   // pas de TMC5160 : etat '0'
};
extern BancSPI SPI1;
