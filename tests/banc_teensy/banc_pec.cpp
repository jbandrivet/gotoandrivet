// Test du PEC : la vis de la monture virtuelle a une erreur periodique (15" au
// tour de vis + 5" au demi-tour). Un autoguideur simule mesure l'etoile toutes
// les 2 s et envoie des impulsions :Mg comme PHD2. On mesure l'erreur de suivi
// sur un tour de vis : sans PEC, pendant l'enregistrement guide, puis en lecture
// SANS guidage, apres sauvegarde, redemarrage parque et synchro :CS#.
#include "banc.h"

static int echecs = 0;
#define VERIF(c, ...) do { if (c) printf("  ok    "); else { printf("  ECHEC "); echecs++; } printf(__VA_ARGS__); printf("\n"); } while (0)

static const double A1 = 15.0, A2 = 5.0;      // erreur de la vis (")
static long W = 0;                             // pas par tour de vis
static long physOff = 0;                       // azPos - pas physiques au depart
static double tgtRa = 0, tgtDec = 0;           // cible (h, deg), fixe

// Angle vrai de l'axe 1 (deg) : pas reellement faits + erreur de la vis.
static double axeVrai() {
  long p = g_phys.az;
  double ph = 2.0 * M_PI * (double)(((p % W) + W) % W) / (double)W;
  double e = A1 * sin(ph) + A2 * sin(2.0 * ph + 1.0);
  return (double)(p + physOff) / AZ_PPD + e / 3600.0;
}
// Ecart de l'etoile sur l'axe 1 (") : axe vrai - axe voulu.
static double ecart() {
  double alt, az;
  ideal_rd2aa_at(tgtRa, tgtDec, &alt, &az, 0.0);
  double d = axeVrai() - az;
  while (d > 180) d -= 360;
  while (d < -180) d += 360;
  return d * 3600.0;
}

struct Stat { double s2 = 0, mx = 0; long n = 0; void add(double v) { s2 += v * v; n++; if (fabs(v) > mx) mx = fabs(v); } double rms() const { return n ? sqrt(s2 / n) : 0; } };

// Fait tourner la monture `sec` secondes, avec ou sans autoguideur.
static Stat tourner(double sec, bool guide) {
  Stat st;
  double prochaine = g_clk.us * 1e-6;
  runFor(sec, [&](double t) {
    st.add(ecart());
    if (guide && t >= prochaine) {
      prochaine = t + 2.0;
      double e = ecart();
      if (fabs(e) > 0.3) {
        int ms = (int)(0.7 * fabs(e) / (guideRate * SIDEREAL_ARCSEC_S) * 1000.0);
        if (ms > 1500) ms = 1500;
        char b[16]; snprintf(b, sizeof b, ":Mg%c%04d#", e > 0 ? 'e' : 'w', ms);
        cmd(b);
        if (getenv("DBG")) printf("    t=%7.1f ecart=%+6.1f\" -> %s  azPos=%ld\n", t, e, b, (long)azPos);
      }
    }
  });
  return st;
}

static std::string champ(const std::string& r, int i) {
  size_t p = 0; for (int k = 0; k < i; k++) p = r.find(',', p) + 1;
  size_t q = r.find_first_of(",#", p); return r.substr(p, q - p);
}

int main(int argc, char** argv) {
  int mt = argc > 1 ? atoi(argv[1]) : 1;
  bancSetup(mt, 45.0, 5.0);
  cmd(":Tn#");
  VERIF(cmd(":XPW144#") == "1#", "roue de 144 dents (:XPW144#)");
  W = pecWormSteps();
  printf("  %s, %.0f pas/deg, tour de vis = %ld pas = %.0f s\n", mt == 1 ? "fourche" : "allemande", AZ_PPD, W, W / AZ_PPD * 3600 / 15.041);
  // Cible a 1 h a l'est du meridien, dec 20.
  double r = lst() - 1.0; if (r < 0) r += 24;
  long rs = lround(r * 3600); tgtRa = rs / 3600.0; tgtDec = 20.0;
  char b[32];
  snprintf(b, sizeof b, ":Sr%02ld:%02ld:%02ld#", rs / 3600, (rs / 60) % 60, rs % 60); cmd(b);
  cmd(":Sd+20*00:00#");
  cmd(":MS#");
  runFor(20.0);
  physOff = azPos - g_phys.az;
  double tour = W / AZ_PPD * 3600 / 15.041;

  printf("Sans PEC, sans guidage :\n");
  Stat s0 = tourner(tour, false);
  printf("  erreur efficace %.1f\" (crete %.1f\")\n", s0.rms(), s0.mx);
  VERIF(s0.rms() > 8, "l'erreur de la vis se voit (%.1f\")", s0.rms());

  printf("Enregistrement guide (:$QZ/#), le guidage tournant depuis 1 min :\n");
  tourner(60, true);
  cmd(":$QZ/#");
  runFor(1.0);
  VERIF(pecStatusQZ() == 'R', "enregistrement en cours (%c), :GU# = %s", pecStatusQZ(), cmd(":GU#").c_str());
  Stat s1 = tourner(tour + 10, true);
  std::string pe = cmd(":GXPE#");
  printf("  erreur guidee %.1f\" ; :GXPE# = %s\n", s1.rms(), pe.c_str());
  VERIF(champ(pe, 0) == "P" && champ(pe, 4) == "1", "courbe enregistree et en lecture");
  double amp = atof(champ(pe, 3).c_str());
  VERIF(amp > 30 && amp < 50, "amplitude crete a crete %.1f\" (vraie : ~38\")", amp);

  if (getenv("DBG")) {
    for (int i = 0; i < PEC_BINS; i += 16) {
      double ph = 2 * M_PI * (i + 0.5) / PEC_BINS;   // phase physique si pecRef = physOff = 0
      printf("    case %3d : courbe %+6.1f\"  -erreur vis %+6.1f\"\n", i, pecTable[i] * 3600.0 / AZ_PPD, -(A1 * sin(ph) + A2 * sin(2 * ph + 1)));
    }
    printf("    pecRef=%ld physOff=%ld\n", pecRef, physOff);
  }
  printf("Lecture du PEC, SANS guidage :\n");
  if (getenv("DBG")) {
    double last = -100;
    runFor(120, [&](double t) {
      if (t - last < 10) return; last = t;
      long raw = azPos; double ph = 2 * M_PI * (double)(((g_phys.az % W) + W) % W) / W;
      double alt, az; ideal_rd2aa_at(tgtRa, tgtDec, &alt, &az, 0.0);
      printf("    t=%6.0f ecart=%+6.1f\"  courbe=%+6.1f\"  -E=%+6.1f\"  (brut-cible)=%+6.1f\"  etat=%d trkRA-cible=%+.2f\"\n", t, ecart(),
             pecOffsetSteps(raw) * 3600.0 / AZ_PPD, -(A1 * sin(ph) + A2 * sin(2 * ph + 1)),
             ((double)raw / AZ_PPD - az) * 3600.0, pecState, (trkRA - tgtRa) * 54000.0);
    });
  }
  Stat s2 = tourner(tour, false);
  printf("  erreur efficace %.1f\" (crete %.1f\")\n", s2.rms(), s2.mx);
  VERIF(s2.rms() < 0.25 * s0.rms(), "erreur divisee par %.1f", s0.rms() / s2.rms());

  printf("Arret de la lecture (:$QZ-#) :\n");
  cmd(":$QZ-#");
  Stat s3 = tourner(tour, false);
  VERIF(s3.rms() > 8 && pecStatusQZ() == 'I', "l'erreur revient (%.1f\"), etat %c", s3.rms(), pecStatusQZ());
  cmd(":$QZ+#");
  runFor(5.0);

  printf("Parking, extinction, redemarrage parque :\n");
  cmd(":$QZ!#");
  cmd(":hP#");
  runFor(5.0);
  long phys = g_phys.az;
  if (getenv("DBG")) printf("    avant : azPos=%ld phys=%ld parkAz=%.3f currAz=%.4f parked=%d\n", (long)azPos, phys, parkAz, currAz, (int)parked);
  // "Redemarrage" : etat RAM remis comme au boot, l'EEPROM (en memoire) est gardee.
  memset(&pecTable, 0, sizeof pecTable); pecValid = false; pecState = PEC_OFF; wormTeeth = 0;
  azPos = 0; altPos = 0;
  loadStateFromEEPROM();
  physOff = azPos - phys;
  if (getenv("DBG")) printf("    apres : azPos=%ld currAz=%.4f pecRef=%ld phase=%.2f\n", (long)azPos, currAz, pecRef, pecPhaseBins(azPos));
  VERIF(pecValid && pecState == PEC_PLAY && wormTeeth == 144, "courbe et lecture reprises (dents %u)", (unsigned)wormTeeth);
  cmd(":SC11/23/26#"); cmd(":SL23:30:00#");
  r = lst() - 1.0; if (r < 0) r += 24; rs = lround(r * 3600); tgtRa = rs / 3600.0;
  snprintf(b, sizeof b, ":Sr%02ld:%02ld:%02ld#", rs / 3600, (rs / 60) % 60, rs % 60); cmd(b);
  cmd(":Sd+20*00:00#");
  cmd(":MS#");
  runFor(20.0);
  if (getenv("DBG")) {
    double last = -100;
    runFor(60, [&](double t) {
      if (t - last < 10) return; last = t;
      long raw = azPos; double ph = 2 * M_PI * (double)(((g_phys.az % W) + W) % W) / W;
      double alt, az; ideal_rd2aa_at(tgtRa, tgtDec, &alt, &az, 0.0);
      printf("    R t=%6.0f ecart=%+6.1f\"  courbe=%+6.1f\"  -E=%+6.1f\"  phase fw=%.1f phys=%.1f cases  etat=%d trk=%d alarm=%d parked=%d\n", t, ecart(),
             pecOffsetSteps(raw) * 3600.0 / AZ_PPD, -(A1 * sin(ph) + A2 * sin(2 * ph + 1)),
             pecPhaseBins(raw), (double)(((g_phys.az % W) + W) % W) * 256 / W, pecState, (int)tracking, (int)alarmActive, (int)parked);
    });
  }
  Stat s4 = tourner(tour, false);
  printf("  erreur apres redemarrage %.1f\"\n", s4.rms());
  VERIF(s4.rms() < 0.3 * s0.rms(), "le PEC marche encore (%.1f\")", s4.rms());

  printf("Synchro :CS# (le compteur de pas est recale) :\n");
  snprintf(b, sizeof b, ":Sr%02ld:%02ld:%02ld#", (rs + 4) / 3600, ((rs + 4) / 60) % 60, (rs + 4) % 60); cmd(b);
  cmd(":Sd+20*00:30#");
  cmd(":CS#");
  // La monture croit maintenant pointer 4 s plus loin en AD : la cible suivie
  // (vue par la monture) est decalee d'autant, on la suit dans le test.
  tgtRa = (rs + 4) / 3600.0; tgtDec = 20.0 + 30.0 / 3600.0;
  physOff = azPos - g_phys.az;
  // Ecart introduit par la synchro elle-meme mis a part : on mesure l'oscillation.
  Stat s5; double m = 0; int k = 0;
  std::vector<double> v;
  runFor(tour, [&](double) { v.push_back(ecart()); });
  for (double x : v) { m += x; k++; } m /= k;
  for (double x : v) s5.add(x - m);
  printf("  oscillation apres :CS# %.1f\"\n", s5.rms());
  VERIF(s5.rms() < 0.3 * s0.rms(), "le tour de vis n'est pas perdu (%.1f\")", s5.rms());

  printf("Effacement (:$QZZ#) et alt-az :\n");
  cmd(":$QZZ#");
  VERIF(!pecValid && pecStatusQZ() == 'I', "courbe effacee");
  cmd(":BMa#");
  VERIF(pecStatusQZ() == 'I' && cmd(":GU#").find('/') == std::string::npos, "alt-az : pas de PEC, rien dans :GU# (%s)", cmd(":GU#").c_str());
  printf(echecs ? "%d ECHEC(S)\n" : "Tout est bon.\n", echecs);
  return echecs ? 1 : 0;
}
