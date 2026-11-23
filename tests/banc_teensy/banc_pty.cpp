// Firmware simule branche sur un pseudo-terminal, en temps reel : un logiciel
// (driver INDI lx200_OnStep, carte du ciel...) s'y connecte comme a la monture.
//   banc_pty <lien> [type]    lien = chemin du lien vers le pty (ex. /tmp/monture)
// Serial (USB) du firmware <-> pty. Arret par Ctrl-C ou SIGTERM.
#include "banc.h"
#include <fcntl.h>
#include <unistd.h>
#include <termios.h>
#include <signal.h>
#include <sys/select.h>
#include <time.h>

static volatile bool g_stop = false;
static void onSig(int) { g_stop = true; }

static uint64_t wallUs() {
  timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
  return (uint64_t)ts.tv_sec * 1000000ull + ts.tv_nsec / 1000;
}

int main(int argc, char** argv) {
  if (argc < 2) { fprintf(stderr, "usage : %s <lien> [type 0|1|2]\n", argv[0]); return 2; }
  int mt = argc > 2 ? atoi(argv[2]) : 2;
  int m = posix_openpt(O_RDWR | O_NOCTTY);
  if (m < 0 || grantpt(m) || unlockpt(m)) { perror("pty"); return 1; }
  const char* sl = ptsname(m);
  termios t; int s = open(sl, O_RDWR | O_NOCTTY);
  tcgetattr(s, &t); cfmakeraw(&t); tcsetattr(s, TCSANOW, &t); close(s);
  unlink(argv[1]);
  if (symlink(sl, argv[1])) { perror("symlink"); return 1; }
  fcntl(m, F_SETFL, O_NONBLOCK);
  signal(SIGINT, onSig); signal(SIGTERM, onSig);

  bancSetup(mt, 45.75, 4.85);
  if (getenv("BANC_DENTS")) cmd(std::string(":XPW") + getenv("BANC_DENTS") + "#");
  Serial.take();
  // Journal (stderr) des commandes qui touchent au modele, au PEC et a la meteo.
  std::string ligne;
  fprintf(stderr, "monture simulee (type %d) sur %s -> %s\n", mt, argv[1], sl);

  static uint64_t w0, v0;
  static int fdm; static std::string* pl;
  w0 = wallUs(); v0 = g_clk.us; fdm = m; pl = &ligne;
  g_clk.pump = [] {
    char buf[256];
    ssize_t n = read(fdm, buf, sizeof buf);
    if (n > 0) {
      Serial.feed(std::string(buf, n));
      for (ssize_t i = 0; i < n; i++) {
        pl->push_back(buf[i]);
        if (buf[i] == '#') {
          const std::string& l = *pl;
          if (l.find(":CM") != std::string::npos || l.find(":CS") != std::string::npos ||
              l.find(":$QZ") != std::string::npos || l.find(":SX9") != std::string::npos)
            fprintf(stderr, "[%8.1f] %s\n", g_clk.us * 1e-6, l.c_str());
          pl->clear();
        }
      }
    }
    std::string out = Serial.take();
    if (out.rfind("N/A#", 0) == 0 || out.rfind("E", 0) == 0)
      fprintf(stderr, "           -> %s  (points : %d)\n", out.c_str(), numSyncPoints);
    if (!out.empty()) { ssize_t r = write(fdm, out.data(), out.size()); (void)r; }
    // Temps reel : le temps simule ne prend pas d'avance sur l'horloge murale.
    for (;;) {
      int64_t ahead = (int64_t)(g_clk.us - v0) - (int64_t)(wallUs() - w0);
      if (ahead <= 0) break;
      usleep(ahead > 2000 ? 2000 : (useconds_t)ahead);
    }
  };
  while (!g_stop) { loop(); bancAdvance(100); }
  unlink(argv[1]);
  return 0;
}
