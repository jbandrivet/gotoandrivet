// Banc d'essai PC du firmware teensy_monture : remplace l'Arduino/Teensy.
// Horloge virtuelle (micros/millis/delay avancent un compteur), ISR IntervalTimer
// declenchee par cette horloge, ports serie en memoire, EEPROM en memoire
// (gardee dans un fichier si BANC_EE est defini dans l'environnement).
// Le firmware est inclus tel quel par le programme de test (#include FIRMWARE).
#pragma once
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <string>
#include <deque>
#include <type_traits>

typedef uint8_t byte;
#define HIGH 1
#define LOW 0
#define OUTPUT 1
#define INPUT 0
#define INPUT_PULLUP 2
#define LED_BUILTIN 13
#define DEC 10
#define PROGMEM
#define F(x) (x)
#define memcpy_P memcpy
#ifndef DEG_TO_RAD
#define DEG_TO_RAD 0.017453292519943295769236907684886
#define RAD_TO_DEG 57.295779513082320876798154814105
#endif

template <class A, class B, class C>
static inline A constrain(A x, B lo, C hi) { return x < (A)lo ? (A)lo : (x > (A)hi ? (A)hi : x); }
// Par valeur : un max() qui rend une reference donne des NaN en -O2.
template <class A, class B>
static inline typename std::common_type<A, B>::type max(A a, B b) { return a > b ? a : b; }
template <class A, class B>
static inline typename std::common_type<A, B>::type min(A a, B b) { return a < b ? a : b; }

// ---------------------------------------------------------------- horloge
struct BancClock {
  uint64_t us = 1000000;          // 1 s au demarrage
  bool irqOn = true;
  bool inIsr = false;
  void (*isr)() = nullptr;
  uint32_t period = 100;
  uint64_t next = 0;
  // Appele toutes les millisecondes de temps simule (hors ISR) : le banc pty y
  // echange avec le port et se cale sur le temps reel, y compris pendant un
  // GoTo, ou le firmware sert lui-meme ses ports dans sa boucle.
  void (*pump)() = nullptr;
  uint64_t nextPump = 0;
  bool inPump = false;
};
extern BancClock g_clk;
extern void (*g_pinHook)(uint8_t pin, uint8_t val);   // monture virtuelle

static inline void bancFireDue() {
  if (!g_clk.isr || !g_clk.irqOn || g_clk.inIsr) return;
  // Comme un vrai timer : les ticks manques pendant une section masquee ne
  // s'accumulent pas, un seul est servi.
  if (g_clk.next <= g_clk.us) {
    g_clk.inIsr = true;
    g_clk.isr();
    g_clk.inIsr = false;
    g_clk.next += g_clk.period;
    if (g_clk.next <= g_clk.us) g_clk.next = g_clk.us - (g_clk.us % g_clk.period) + g_clk.period;
  }
}
static inline void bancAdvance(uint64_t d) {
  uint64_t target = g_clk.us + d;
  while (g_clk.isr && g_clk.irqOn && !g_clk.inIsr && g_clk.next <= target) {
    if (g_clk.us < g_clk.next) g_clk.us = g_clk.next;
    bancFireDue();
  }
  if (g_clk.us < target) g_clk.us = target;
  if (g_clk.pump && !g_clk.inIsr && !g_clk.inPump && g_clk.us >= g_clk.nextPump) {
    g_clk.inPump = true;
    g_clk.pump();
    g_clk.nextPump = g_clk.us + 1000;
    g_clk.inPump = false;
  }
}
static inline uint32_t micros() { bancAdvance(1); return (uint32_t)g_clk.us; }
static inline uint32_t millis() { bancAdvance(1); return (uint32_t)(g_clk.us / 1000); }
static inline void delayMicroseconds(uint32_t n) { bancAdvance(n); }
static inline void delay(uint32_t ms) { bancAdvance((uint64_t)ms * 1000); }
static inline void noInterrupts() { g_clk.irqOn = false; }
static inline void interrupts() { g_clk.irqOn = true; bancFireDue(); }

struct IntervalTimer {
  bool begin(void (*f)(), uint32_t us) {
    g_clk.isr = f; g_clk.period = us; g_clk.next = g_clk.us + us; return true;
  }
  void end() { g_clk.isr = nullptr; }
};

// ---------------------------------------------------------------- broches
static inline void pinMode(uint8_t, uint8_t) {}
static inline void digitalWrite(uint8_t p, uint8_t v) { if (g_pinHook) g_pinHook(p, v); }
static inline void digitalWriteFast(uint8_t p, uint8_t v) { if (g_pinHook) g_pinHook(p, v); }
static inline int digitalRead(uint8_t) { return 0; }
static inline void tone(uint8_t, unsigned int) {}
static inline void tone(uint8_t, unsigned int, unsigned long) {}
static inline void noTone(uint8_t) {}

// ---------------------------------------------------------------- Print / Stream
class Print {
 public:
  virtual ~Print() {}
  virtual size_t write(uint8_t c) = 0;
  size_t write(const char* s) { size_t n = 0; while (*s) n += write((uint8_t)*s++); return n; }
  size_t print(const char* s) { return write(s); }
  size_t print(char c) { return write((uint8_t)c); }
  size_t print(unsigned char v, int = DEC) { return printNum((unsigned long)v); }
  size_t print(int v, int = DEC) { return printSigned(v); }
  size_t print(unsigned int v, int = DEC) { return printNum(v); }
  size_t print(long v, int = DEC) { return printSigned(v); }
  size_t print(unsigned long v, int = DEC) { return printNum(v); }
  size_t print(double v, int digits = 2) {
    char b[48]; snprintf(b, sizeof b, "%.*f", digits, v); return write(b);
  }
  size_t print(const std::string& s) { return write(s.c_str()); }
  template <class T> size_t println(T v) { size_t n = print(v); n += write("\r\n"); return n; }
  size_t println() { return write("\r\n"); }
 private:
  size_t printNum(unsigned long v) { char b[24]; snprintf(b, sizeof b, "%lu", v); return write(b); }
  size_t printSigned(long v) { char b[24]; snprintf(b, sizeof b, "%ld", v); return write(b); }
};

class Stream : public Print {
 public:
  virtual int available() = 0;
  virtual int read() = 0;
};

class BancSerial : public Stream {
 public:
  std::deque<char> rx;
  std::string tx;
  void begin(unsigned long) {}
  int available() override { return (int)rx.size(); }
  int read() override { if (rx.empty()) return -1; char c = rx.front(); rx.pop_front(); return (unsigned char)c; }
  size_t write(uint8_t c) override { tx.push_back((char)c); return 1; }
  using Print::write;
  void feed(const std::string& s) { for (char c : s) rx.push_back(c); }
  std::string take() { std::string s; s.swap(tx); return s; }
};
extern BancSerial Serial, Serial3, Serial4, Serial6;

// ---------------------------------------------------------------- EEPROM
struct BancEEPROM {
  uint8_t mem[4284];
  BancEEPROM() { memset(mem, 0xFF, sizeof mem); }
  uint8_t read(int a) const { return (a >= 0 && a < (int)sizeof mem) ? mem[a] : 0xFF; }
  void update(int a, uint8_t v) { if (a >= 0 && a < (int)sizeof mem) mem[a] = v; }
  void write(int a, uint8_t v) { update(a, v); }
  int length() const { return (int)sizeof mem; }
};
extern BancEEPROM EEPROM;
