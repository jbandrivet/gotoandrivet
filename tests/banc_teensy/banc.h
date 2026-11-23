// Banc d'essai : inclut le firmware et fournit les outils communs aux tests.
// Compiler avec -DFIRMWARE='"chemin/teensy_monture.ino"' -Istubs.
#pragma once
#include "arduino_shim.h"
#include "stubs/SPI.h"

BancClock g_clk;
void (*g_pinHook)(uint8_t, uint8_t) = nullptr;
BancSerial Serial, Serial3, Serial4, Serial6;
BancEEPROM EEPROM;
BancSPI SPI1;

void playStartupMelody();
void playArrivalMelody();
// Prototypes que l'IDE Arduino genere seul pour un .ino.
static void setTrk(double ra_h, double dec_d);
static void ideal_aa2rd(double alt, double az, long *rs, long *ds);
static void trackRestartAfterSlew();

#include FIRMWARE

#include <vector>
#include <random>
#include <algorithm>

// ------------------------------------------------ monture physique (pas reels)
// Compte les impulsions STEP avec le niveau DIR : position reelle des moteurs.
struct PhysAxes {
  long az = 0, alt = 0;
  int lvlAz = 1, lvlAlt = 1;
  int stAz = 0, stAlt = 0;
};
static PhysAxes g_phys;
static void bancPinHook(uint8_t p, uint8_t v) {
  if (p == AZ_DIR) g_phys.lvlAz = v;
  else if (p == ALT_DIR) g_phys.lvlAlt = v;
  else if (p == AZ_STEP) { if (v && !g_phys.stAz) g_phys.az += g_phys.lvlAz ? 1 : -1; g_phys.stAz = v; }
  else if (p == ALT_STEP) { if (v && !g_phys.stAlt) g_phys.alt += g_phys.lvlAlt ? 1 : -1; g_phys.stAlt = v; }
}

// ------------------------------------------------ commandes
// Envoie une commande LX200 directement au processeur de commandes.
struct Capture : public Print {
  std::string s;
  size_t write(uint8_t c) override { s.push_back((char)c); return 1; }
  using Print::write;
};
static std::string cmd(std::string c) {
  if (!c.empty() && c.back() == '#') c.pop_back();
  char buf[CMD_MAX];
  snprintf(buf, sizeof buf, "%s", c.c_str());
  Capture cap;
  processCmd(buf, (uint8_t)strlen(buf), cap);
  return cap.s;
}

// Fait tourner loop() pendant sec secondes de temps virtuel (100 us par tour),
// en appelant tick(t) environ toutes les 10 ms si fourni.
template <class F>
static void runFor(double sec, F tick) {
  uint64_t end = g_clk.us + (uint64_t)(sec * 1e6);
  uint64_t nextTick = g_clk.us;
  while (g_clk.us < end) {
    loop();
    bancAdvance(100);
    if (g_clk.us >= nextTick) { tick(g_clk.us * 1e-6); nextTick = g_clk.us + 10000; }
  }
}
static void runFor(double sec) { runFor(sec, [](double) {}); }

static std::string fmtLat(double v) {
  char b[24]; double a = fabs(v); int d = (int)a; int m = (int)((a - d) * 60.0 + 0.5);
  if (m == 60) { d++; m = 0; }
  snprintf(b, sizeof b, "%c%02d*%02d", v < 0 ? '-' : '+', d, m); return b;
}

// Demarrage : EEPROM vierge, type de monture, lieu, date/heure fixes.
static void bancSetup(int mount, double lat, double lonEast) {
  g_pinHook = bancPinHook;
  setup();
  cmd(mount == 0 ? ":BMa#" : mount == 1 ? ":BMe#" : ":BMg#");
  cmd(":St" + fmtLat(lat) + "#");
  char b[32];
  double w = -lonEast; double a = fabs(w); int d = (int)a; int m = (int)((a - d) * 60 + 0.5);
  snprintf(b, sizeof b, ":Sg%c%03d*%02d#", w < 0 ? '-' : '+', d, m);
  cmd(b);
  cmd(":SG+00#");
  cmd(":SC11/23/26#");
  cmd(":SL22:00:00#");
}

// ------------------------------------------------ vecteurs
struct V3 { double x, y, z; };
static V3 v3(double a, double e) {   // coordonnees monture -> vecteur (deg)
  double ar = a * DEG_TO_RAD, er = e * DEG_TO_RAD;
  return { cos(er) * cos(ar), -cos(er) * sin(ar), sin(er) };
}
static double dot(V3 a, V3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
static V3 cross(V3 a, V3 b) { return { a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x }; }
static double norm(V3 a) { return sqrt(dot(a, a)); }
static double angDeg(V3 a, V3 b) { return atan2(norm(cross(a, b)), dot(a, b)) * RAD_TO_DEG; }
static V3 rotX(V3 v, double d) { double c = cos(d * DEG_TO_RAD), s = sin(d * DEG_TO_RAD); return { v.x, c * v.y - s * v.z, s * v.y + c * v.z }; }
static V3 rotY(V3 v, double d) { double c = cos(d * DEG_TO_RAD), s = sin(d * DEG_TO_RAD); return { c * v.x + s * v.z, v.y, -s * v.x + c * v.z }; }
static V3 rotZ(V3 v, double d) { double c = cos(d * DEG_TO_RAD), s = sin(d * DEG_TO_RAD); return { c * v.x - s * v.y, s * v.x + c * v.y, v.z }; }
