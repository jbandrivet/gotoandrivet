// Test du guidage :Mg : une impulsion doit deplacer l'axe de vitesse de guidage x
// duree, et le deplacement doit rester apres l'impulsion. Avant le correctif, le
// servo du suivi prenait l'impulsion pour une erreur et la defaisait pendant
// qu'elle durait (vu sur le vrai Teensy : 5 s = 18-22" au lieu de 37,6").
// On mesure l'ecart de l'etoile sur chaque axe (pas reellement faits - position
// voulue), a la fin de l'impulsion et 10 s apres. Argument : 1 = fourche, 2 = allemande.
#include "banc.h"

static int echecs = 0;
#define VERIF(c, ...) do { if (c) printf("  ok    "); else { printf("  ECHEC "); echecs++; } printf(__VA_ARGS__); printf("\n"); } while (0)

static long offAz = 0, offAlt = 0;
static double tgtRa = 0, tgtDec = 0;

// Ecarts de l'etoile (") sur les deux axes : axe reel - axe voulu.
static void ecarts(double* eAz, double* eAlt) {
  double alt, az;
  ideal_rd2aa_at(tgtRa, tgtDec, &alt, &az, 0.0);
  double dz = (double)(g_phys.az + offAz) / AZ_PPD - az;
  while (dz > 180) dz -= 360;
  while (dz < -180) dz += 360;
  *eAz = dz * 3600.0;
  *eAlt = ((double)(g_phys.alt + offAlt) / ALT_PPD - alt) * 3600.0;
}

int main(int argc, char** argv) {
  int mt = argc > 1 ? atoi(argv[1]) : 2;
  bancSetup(mt, 45.0, 5.0);
  cmd(":Tn#");
  double r = lst() - 1.0; if (r < 0) r += 24;
  long rs = lround(r * 3600); tgtRa = rs / 3600.0; tgtDec = 60.0;
  char b[32];
  snprintf(b, sizeof b, ":Sr%02ld:%02ld:%02ld#", rs / 3600, (rs / 60) % 60, rs % 60); cmd(b);
  cmd(":Sd+60*00:00#");
  cmd(":MS#");
  runFor(60.0);
  offAz = azPos - g_phys.az; offAlt = altPos - g_phys.alt;
  printf("  %s, vitesse de guidage %.2fx\n", mt == 1 ? "fourche" : "allemande", guideRate);

  const char dirs[] = { 'n', 's', 'e', 'w' };
  const int durees[] = { 500, 1000, 3000, 5000 };
  for (char d : dirs) for (int ms : durees) {
    runFor(3.0);
    double z0, a0; ecarts(&z0, &a0);
    snprintf(b, sizeof b, ":Mg%c%d#", d, ms); cmd(b);
    runFor(ms / 1000.0 + 0.05);
    double z1, a1; ecarts(&z1, &a1);
    runFor(10.0);
    double z2, a2; ecarts(&z2, &a2);
    const bool dec = (d == 'n' || d == 's');
    double fin = dec ? a1 - a0 : z1 - z0, apres = dec ? a2 - a0 : z2 - z0;
    double autre = dec ? z2 - z0 : a2 - a0;
    double att = guideRate * SIDEREAL_ARCSEC_S * ms / 1000.0;
    VERIF(fabs(fabs(fin) - att) < 0.1 * att + 1.0 && fabs(apres - fin) < 1.0 && fabs(autre) < 1.0,
          ":Mg%c%-4d attendu %5.1f\" : fin %+6.1f\", 10 s apres %+6.1f\", autre axe %+4.1f\"",
          d, ms, att, fin, apres, autre);
  }
  printf(echecs ? "%d ECHEC(S)\n" : "guidage : tout est bon\n", echecs);
  return echecs ? 1 : 0;
}
