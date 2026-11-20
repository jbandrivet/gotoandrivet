// Émulateur PC de la carte de mise en station : compile mise_en_station.ino tel quel
// avec une fausse bibliothèque Arduino, et le relie à un port série virtuel (pty).
//
//   g++ -O2 -o emulateur emulateur.cpp   (depuis ce dossier)
//   ./emulateur            -> écrit sur la sortie d'erreur : PORT /dev/pts/N
//
// Variables d'environnement :
//   MES_VM=12.0            tension du 12 V moteurs (0 = débranché)
//   MES_FC="A+:5000,L-:-3000"  fin de course appuyée quand la vis dépasse ce nombre de pas
//   MES_JEU="A:40,L:25"    jeu mécanique simulé (pas perdus à chaque changement de sens)
//   MES_ETAT=fichier       écrit "vis_A sortie_A vis_L sortie_L" (pas) à chaque changement
//   MES_EEPROM=fichier     EEPROM conservée entre deux lancements
//   MES_ACCEL=10           le temps passe 10 fois plus vite (mouvements plus courts)
#include <cerrno>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <fcntl.h>
#include <string>
#include <unistd.h>
#include <sys/select.h>

#include "Arduino.h"

// ------------------------------------------------------------------ temps
static double acceleration = 1.0;
static struct timespec t0;
static double secondes() {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return ((t.tv_sec - t0.tv_sec) + (t.tv_nsec - t0.tv_nsec) * 1e-9) * acceleration;
}
unsigned long micros() { return (unsigned long)(secondes() * 1e6); }
unsigned long millis() { return (unsigned long)(secondes() * 1e3); }
void delayMicroseconds(unsigned int) {}
void delay(unsigned long) {}

// ------------------------------------------------------------------ série sur pty
static int maitre = -1;
static std::string recu;
static void pomper() {
  char b[256];
  for (;;) {
    ssize_t n = read(maitre, b, sizeof b);
    if (n <= 0) break;
    recu.append(b, n);
  }
}
void SerialEmu::begin(long) {}
int SerialEmu::available() { pomper(); return (int)recu.size(); }
int SerialEmu::read() {
  pomper();
  if (recu.empty()) return -1;
  int c = (unsigned char)recu[0];
  recu.erase(0, 1);
  return c;
}
void SerialEmu::ecrire(const char *s) {
  size_t n = strlen(s);
  while (n) {
    ssize_t k = write(maitre, s, n);
    if (k < 0) { if (errno == EAGAIN) { usleep(100); continue; } return; }
    s += k; n -= k;
  }
}
void SerialEmu::print(const char *s) { ecrire(s); }
void SerialEmu::print(char c) { char s[2] = {c, 0}; ecrire(s); }
void SerialEmu::print(int v) { print((long)v); }
void SerialEmu::print(unsigned int v) { print((long)v); }
void SerialEmu::print(uint8_t v) { print((long)v); }
void SerialEmu::print(long v) { char s[24]; snprintf(s, sizeof s, "%ld", v); ecrire(s); }
void SerialEmu::print(double v, int d) { char s[40]; snprintf(s, sizeof s, "%.*f", d, v); ecrire(s); }
SerialEmu Serial;

// ------------------------------------------------------------------ EEPROM
static uint8_t eeprom[1024];
static const char *fichierEeprom = nullptr;
EEPROMEmu EEPROM;
uint8_t *EEPROMEmu::data() { return eeprom; }
void EEPROMEmu::sauver() {
  if (!fichierEeprom) return;
  FILE *f = fopen(fichierEeprom, "wb");
  if (f) { fwrite(eeprom, 1, sizeof eeprom, f); fclose(f); }
}

// ------------------------------------------------------------------ broches et mécanique
static uint8_t etat[32];
static double simVm = 12.0;
static long vis[2] = {0, 0};        // pas réellement faits par le moteur
static long sortie[2] = {0, 0};     // ce que voit la monture, après le jeu
static long jeu[2] = {0, 0};
static long fcPlus[2] = {0x7fffffff, 0x7fffffff}, fcMoins[2] = {-0x7fffffff, -0x7fffffff};
static const char *fichierEtat = nullptr;

static void ecrireEtat() {
  if (!fichierEtat) return;
  std::string tmp = std::string(fichierEtat) + ".tmp";
  FILE *f = fopen(tmp.c_str(), "w");
  if (!f) return;
  fprintf(f, "%ld %ld %ld %ld\n", vis[0], sortie[0], vis[1], sortie[1]);
  fclose(f);
  rename(tmp.c_str(), fichierEtat);
}

void pinMode(uint8_t, uint8_t) {}
void digitalWrite(uint8_t p, uint8_t v) {
  uint8_t avant = etat[p];
  etat[p] = v;
  int i = p == 2 ? 0 : p == 5 ? 1 : -1;           // broches STEP
  if (i >= 0 && avant == LOW && v == HIGH && etat[i ? 7 : 4] == LOW) {   // pas, moteur actif
    // DIR à HIGH = sens + (le firmware gère lui-même l'inversion)
    int s = etat[i ? 6 : 3] == HIGH ? 1 : -1;
    vis[i] += s;
    // jeu : la sortie ne suit que lorsque la vis a rattrapé le jeu
    if (vis[i] - sortie[i] > jeu[i]) sortie[i] = vis[i] - jeu[i];
    if (sortie[i] - vis[i] > 0) sortie[i] = vis[i];
    if (vis[i] - sortie[i] < 0) sortie[i] = vis[i];
    ecrireEtat();
  }
}
int digitalRead(uint8_t p) {
  // fins de course : D8/D9 = azimut MIN/MAX, D10/D11 = hauteur MIN/MAX, contact -> LOW
  if (p == 8) return vis[0] <= fcMoins[0] ? LOW : HIGH;
  if (p == 9) return vis[0] >= fcPlus[0] ? LOW : HIGH;
  if (p == 10) return vis[1] <= fcMoins[1] ? LOW : HIGH;
  if (p == 11) return vis[1] >= fcPlus[1] ? LOW : HIGH;
  return etat[p];
}
int analogRead(uint8_t) {
  double adc = simVm * 10.0 / 57.0 / 5.0 * 1023.0;
  return adc > 1023 ? 1023 : (int)adc;
}
char *dtostrf(double v, signed char w, unsigned char d, char *s) { sprintf(s, "%*.*f", w, d, v); return s; }

static void lireEnv() {
  if (const char *e = getenv("MES_VM")) simVm = atof(e);
  if (const char *e = getenv("MES_ACCEL")) acceleration = atof(e) > 0 ? atof(e) : 1.0;
  if (const char *e = getenv("MES_FC")) {
    std::string s(e);
    size_t k = 0;
    while (k < s.size()) {
      size_t f = s.find(',', k);
      std::string t = s.substr(k, f == std::string::npos ? std::string::npos : f - k);
      if (t.size() > 3) {
        int i = t[0] == 'A' ? 0 : 1;
        long v = atol(t.c_str() + 3);
        if (t[1] == '+') fcPlus[i] = v; else fcMoins[i] = v;
      }
      if (f == std::string::npos) break;
      k = f + 1;
    }
  }
  if (const char *e = getenv("MES_JEU")) {
    const char *a = strstr(e, "A:"), *l = strstr(e, "L:");
    if (a) jeu[0] = atol(a + 2);
    if (l) jeu[1] = atol(l + 2);
  }
  fichierEtat = getenv("MES_ETAT");
  fichierEeprom = getenv("MES_EEPROM");
  memset(eeprom, 0xff, sizeof eeprom);
  if (fichierEeprom) {
    FILE *f = fopen(fichierEeprom, "rb");
    if (f) { if (fread(eeprom, 1, sizeof eeprom, f)) {} fclose(f); }
  }
}

#include "../mise_en_station.ino"

int main() {
  clock_gettime(CLOCK_MONOTONIC, &t0);
  lireEnv();
  maitre = posix_openpt(O_RDWR | O_NOCTTY);
  if (maitre < 0 || grantpt(maitre) || unlockpt(maitre)) { perror("pty"); return 1; }
  fcntl(maitre, F_SETFL, O_NONBLOCK);
  fprintf(stderr, "PORT %s\n", ptsname(maitre));
  fflush(stderr);
  ecrireEtat();
  setup();
  for (;;) {
    loop();
    if (!ax[0].enMouvement && !ax[1].enMouvement) {
      fd_set f;
      FD_ZERO(&f);
      FD_SET(maitre, &f);
      struct timeval tv = {0, 2000};
      select(maitre + 1, &f, nullptr, nullptr, &tv);
    }
  }
}
