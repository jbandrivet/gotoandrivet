// Test du modele de pointage : monture virtuelle a defauts reels (geometrie
// exacte par rotations, pas les formules lineaires du firmware), synchros sur
// N etoiles tirees au hasard (centrage a 0,5' pres), puis erreur de pointage
// mesuree sur 300 cibles visibles. Meme programme pour l'ancien et le nouveau
// firmware (seules des fonctions communes aux deux sont utilisees).
#include "banc.h"

#include "monture_virtuelle.h"

static double pct(const std::vector<double>& v, double p) { return v[(size_t)(p * (v.size() - 1))]; }

int main(int argc, char** argv) {
  const char* etiquette = argc > 1 ? argv[1] : "";
  const Defauts cas[] = {
    // nom            ih   id   pa   pb   cone np   tf   fo   e1s  e1c  e2s  e2c
    {"geometrie",     2.0, 1.5, 1.0, 0.6, 0.3, 0.15, 0,  0,   0,   0,   0,   0},
    {"+flexion",      2.0, 1.5, 1.0, 0.6, 0.3, 0.15, 0.15, 0, 0,   0,   0,   0},
    {"+excentricite", 2.0, 1.5, 1.0, 0.6, 0.3, 0.15, 0.1, 0, 0.08, -0.05, 0.05, 0.04},
    {"bien reglee",   0.3, 0.2, 0.05, 0.03, 0.02, 0.01, 0, 0,  0,   0,   0,   0},
  };
  const int nEt[] = {1, 2, 3, 4, 6, 8, 12, 20};
  printf("%s\n", etiquette);
  for (int mt = 0; mt <= 2; mt++) {
    for (const Defauts& d : cas) {
      printf("%-6s %-14s |", mt == 0 ? "altaz" : mt == 1 ? "fourche" : "allem.", d.nom);
      for (int n : nEt) {
        // Mediane et 90 % de l'erreur, moyennees sur 6 tirages d'etoiles.
        double med = 0, p90 = 0; int essais = getenv("ESSAIS") ? atoi(getenv("ESSAIS")) : 6;
        for (int k = 0; k < essais; k++) {
          rng.seed(1000 * mt + 17 * n + k);
          bancSetup(mt, 45.0, 5.0);
          cmd(":Tn#");             // refraction coupee : geometrie seule
          cmd(":CML#");
          D = d;
          for (int i = 0; i < n; i++) { long ra, dec; tirage(20.0, &ra, &dec); syncSur(ra, dec, 0.5); }
          std::vector<double> err; evaluer(300, err);
          med += pct(err, 0.5) / essais; p90 += pct(err, 0.9) / essais;
        }
        printf(" %2d:%5.1f/%5.1f", n, med, p90);
      }
      printf("\n");
    }
  }
  return 0;
}
