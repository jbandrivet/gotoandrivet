// Fausse bibliothèque Arduino pour emulateur.cpp (juste ce qu'utilise mise_en_station.ino)
#pragma once
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#define HIGH 1
#define LOW 0
#define INPUT 0
#define OUTPUT 1
#define INPUT_PULLUP 2
#define A0 14

unsigned long micros();
unsigned long millis();
void delayMicroseconds(unsigned int);
void delay(unsigned long);
void pinMode(uint8_t, uint8_t);
void digitalWrite(uint8_t, uint8_t);
int digitalRead(uint8_t);
int analogRead(uint8_t);
char *dtostrf(double, signed char, unsigned char, char *);

struct SerialEmu {
  void begin(long);
  int available();
  int read();
  void print(const char *);
  void print(char);
  void print(int);
  void print(unsigned int);
  void print(uint8_t);
  void print(long);
  void print(double, int = 2);
  void ecrire(const char *);
};
extern SerialEmu Serial;

struct EEPROMEmu {
  uint8_t *data();
  void sauver();
  template <class T> T &get(int a, T &v) { memcpy(&v, data() + a, sizeof(T)); return v; }
  template <class T> const T &put(int a, const T &v) { memcpy(data() + a, &v, sizeof(T)); sauver(); return v; }
};
extern EEPROMEmu EEPROM;
