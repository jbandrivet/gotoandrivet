// Synchros : refus d'une synchro ratee (mauvaise etoile) puis confirmation,
// retrait du dernier point (:CMU#), bilan :GXMS# et sens de la mise en station.
#include "monture_virtuelle.h"

static int echecs = 0;
#define VERIF(c, ...) do { if (c) printf("  ok    "); else { printf("  ECHEC "); echecs++; } printf(__VA_ARGS__); printf("\n"); } while (0)

static double champ(const std::string& r, int i) {
  size_t p = 0; for (int k = 0; k < i; k++) p = r.find(',', p) + 1; return atof(r.c_str() + p);
}

// Bilan apres 12 synchros sans bruit sur une monture n'ayant que le defaut d.
static std::string bilan(int mt, double lat, Defauts d) {
  rng.seed(5);
  bancSetup(mt, lat, 5.0); cmd(":Tn#"); cmd(":CML#");
  D = d;
  for (int i = 0; i < 12; i++) { long ra, dec; tirage(20.0, &ra, &dec); syncSur(ra, dec, 0.0); }
  return cmd(":GXMS#");
}

int main() {
  // ---------------------------------------------------- refus et confirmation
  printf("Refus d'une synchro sur la mauvaise etoile (allemande) :\n");
  rng.seed(42);
  bancSetup(2, 45.0, 5.0); cmd(":Tn#"); cmd(":CML#");
  D = {"geometrie", 2.0, 1.5, 1.0, 0.6, 0.3, 0.15, 0.05, 0, 0, 0, 0, 0};
  for (int i = 0; i < 5; i++) { long ra, dec; tirage(25.0, &ra, &dec); syncSur(ra, dec, 0.5); }
  VERIF(numSyncPoints == 5, "5 synchros acceptees (%d)", numSyncPoints);
  long ra, dec;
  do tirage(25.0, &ra, &dec); while (dec > 70L * 3600L);
  long faux = ra + 4 * 60 * 15 / 15;       // AD decalee de 4 min (~1 deg) ...
  long fauxDec = dec + 3 * 3600;           // ... et 3 deg en dec : etoile voisine
  std::string r1 = syncSur(ra, dec, 0.5, faux, fauxDec);
  VERIF(r1.rfind("E9,", 0) == 0, "mauvaise etoile refusee : %s", r1.c_str());
  VERIF(numSyncPoints == 5, "modele inchange (%d points)", numSyncPoints);
  std::string r2 = syncSur(ra, dec, 0.5, faux, fauxDec);
  VERIF(r2 == "N/A#", "refaite au meme endroit : acceptee (%s)", r2.c_str());
  VERIF(numSyncPoints == 1, "ancien modele efface, on repart de ce point (%d)", numSyncPoints);

  printf("Synchro normale pres du modele acceptee :\n");
  bancSetup(2, 45.0, 5.0); cmd(":Tn#"); cmd(":CML#");
  for (int i = 0; i < 6; i++) { long r, d; tirage(25.0, &r, &d); syncSur(r, d, 0.5); }
  { long r, d; tirage(25.0, &r, &d); std::string s = syncSur(r, d, 0.5);
    VERIF(s == "N/A#" && numSyncPoints == 7, "7e etoile acceptee (%s, %d points)", s.c_str(), numSyncPoints); }

  // ---------------------------------------------------- retrait du dernier point
  printf("Retrait du dernier point (:CMU#) :\n");
  {
    long r, d; tirage(25.0, &r, &d);
    // Fausse etoile a 1 deg : sous le seuil de refus, elle entre dans le modele.
    syncSur(r, d, 0.0, r, d + 3600);
    int n = numSyncPoints;
    long ap = azPos, lp = altPos;
    updatePos(); long decAvant = currDEC;
    std::string u = cmd(":CMU#");
    updatePos();
    VERIF(u == "1#" && numSyncPoints == n - 1, ":CMU# retire un point (%s, %d -> %d)", u.c_str(), n, numSyncPoints);
    VERIF(azPos == ap && altPos == lp, "la monture n'a pas bouge");
    VERIF(fabs((double)(currDEC - d)) < 300 && fabs((double)(decAvant - (d + 3600))) < 60,
          "position relue sans le point : dec %+.1f' de la vraie etoile (avant : %+.1f')",
          (currDEC - d) / 60.0, (decAvant - d) / 60.0);
    while (numSyncPoints > 0) cmd(":CMU#");
    VERIF(cmd(":CMU#") == "0#", "plus rien a retirer : 0#");
  }

  // ---------------------------------------------------- memoire : rangement
  printf("Plein (50 points) : le plus ancien part, le dernier se retire :\n");
  bancSetup(1, 45.0, 5.0); cmd(":Tn#"); cmd(":CML#");
  D = {"geometrie", 0.5, 0.3, 0.2, 0.1, 0.05, 0.02, 0, 0, 0, 0, 0, 0};
  for (int i = 0; i < 55; i++) { long r, d; tirage(20.0, &r, &d); syncSur(r, d, 0.2); }
  VERIF(numSyncPoints == 50 && syncIndex == 0, "50 points, index %d", syncIndex);
  cmd(":CMU#");
  VERIF(numSyncPoints == 49 && syncIndex == 49, "49 points, index %d", syncIndex);

  // ---------------------------------------------------- sens de la mise en station
  printf("Sens des valeurs de mise en station (:GXMS#) :\n");
  Defauts z = {"rien", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0};
  Defauts d;
  for (double lat : {45.0, -30.0}) {
    for (int mt = 1; mt <= 2; mt++) {
      // pb > 0 penche l'axe (bout nord) vers le meridien sud, en passant par le
      // zenith : pole nord plus haut ; au sud, le pole sud descend vers l'horizon.
      // pa > 0 penche le bout nord vers l'ouest (angle horaire +6 h) : pole nord
      // a l'ouest ; au sud, le bout sud part vers l'est.
      double sg = lat > 0 ? 1.0 : -1.0;
      d = z; d.pb = 0.5;
      std::string b1 = bilan(mt, lat, d);
      d = z; d.pa = 0.5;
      std::string b2 = bilan(mt, lat, d);
      printf("  lat %+.0f %s : pb=+0,5 -> %s | pa=+0,5 -> %s\n", lat, mt == 1 ? "fourche" : "allem.", b1.c_str(), b2.c_str());
      VERIF(fabs(champ(b1, 3) - 30 * sg) < 3 && fabs(champ(b1, 4)) < 3, "  axe trop %s de 30' : haut = %.1f'", sg > 0 ? "haut" : "bas", champ(b1, 3));
      VERIF(fabs(champ(b2, 4) + 30 * sg) < 3 && fabs(champ(b2, 3)) < 3, "  axe trop a l'%s de 30' : est = %.1f'", sg > 0 ? "ouest" : "est", champ(b2, 4));
    }
  }
  d = z; d.pb = 0.5; std::string b3 = bilan(0, 45.0, d);
  d = z; d.pa = 0.5; std::string b4 = bilan(0, 45.0, d);
  printf("  alt-az : pb=+0,5 -> %s | pa=+0,5 -> %s\n", b3.c_str(), b4.c_str());
  VERIF(fabs(champ(b3, 3) - 30) < 3 && (champ(b3, 4) < 5 || champ(b3, 4) > 355), "  axe penche de 30' vers le nord : %.1f' vers %.0f deg", champ(b3, 3), champ(b3, 4));
  VERIF(fabs(champ(b4, 3) - 30) < 3 && fabs(champ(b4, 4) - 90) < 5, "  axe penche de 30' vers l'est : %.1f' vers %.0f deg", champ(b4, 3), champ(b4, 4));

  printf(echecs ? "%d ECHEC(S)\n" : "Tout est bon.\n", echecs);
  return echecs ? 1 : 0;
}
