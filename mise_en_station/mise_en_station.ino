/*
 * GotoAndrivet - Mise en station robotisée (carte pcb/mise_en_station, Arduino Nano)
 * Auteur : Andrivet Jean-Baptiste - Licence GPL v3 (voir LICENSE)
 *
 * Deux moteurs pas à pas tournent les vis de réglage de la monture :
 *   axe A = azimut (vis gauche/droite), axe L = hauteur (vis de latitude).
 * Le PC (mise_en_station_robot.py) mesure l'erreur au pôle avec la caméra et envoie les mouvements.
 *
 * Câblage (carte pcb/mise_en_station) :
 *   D2/D3/D4 = STEP/DIR/EN azimut       D5/D6/D7 = STEP/DIR/EN hauteur (EN actif à l'état bas)
 *   D8/D9    = fins de course az MIN/MAX  D10/D11 = hauteur MIN/MAX (contact vers GND, rappel 10k)
 *   D12      = voyant ACTIF              A0 = 12 V moteurs par pont 47k/10k
 *
 * Liaison USB à 38400 bauds, commandes entre ':' et '#' (comme LX200) :
 *   :GVP#            -> GotoAndrivet-MES#        nom de la carte
 *   :GVN#            -> 1.0#                     version
 *   :GS#             -> a,l,ffff,vvv,r#          a/l = 1 si l'axe bouge ; ffff = fins de course
 *                                                az MIN, az MAX, haut MIN, haut MAX (1 = appuyé) ;
 *                                                vvv = 12 V en dixièmes de volt ; r = cause du dernier arrêt
 *                                                (0 fin normale, 1 fin de course, 2 arrêt demandé, 3 12 V perdu)
 *   :GPA# :GPL#      -> +00001234#               position en pas
 *   :MRA+1200#       -> 1#                       mouvement relatif en pas (MRL pour la hauteur)
 *                       0A# 12 V absent, 0B# fin de course de ce côté, 0M# axe déjà en mouvement, 0P# erreur
 *   :Q#  :QA#  :QL#  -> (rien)                   arrêt avec décélération (tous, azimut, hauteur)
 *   :SZA#  :SZL#     -> 1#                       position remise à zéro
 *   :GCxk#           -> valeur#                  lit un réglage (x = A, L ou G pour général)
 *   :SCxk<valeur>#   -> 1# ou 0#                 écrit un réglage, gardé en EEPROM
 *        par axe : V vitesse (pas/s), C accélération (pas/s²), J jeu à rattraper (pas),
 *                  I sens inversé (0/1), T moteur alimenté à l'arrêt (0/1),
 *                  K calibration en pas par minute d'arc (réel, mesuré par le PC)
 *        général : F fins de course normalement fermés (0/1), M seuil du 12 V en dixièmes de volt
 *
 * Rattrapage du jeu : un mouvement vers les pas négatifs va J pas trop loin puis revient,
 * la vis arrive donc toujours sur sa cible dans le même sens.
 */

#include <EEPROM.h>

#define MES_VERSION "1.0"

const uint8_t PIN_STEP[2] = {2, 5};
const uint8_t PIN_DIR[2]  = {3, 6};
const uint8_t PIN_EN[2]   = {4, 7};
const uint8_t PIN_FC_MIN[2] = {8, 10};
const uint8_t PIN_FC_MAX[2] = {9, 11};
const uint8_t PIN_LED = 12;
const uint8_t PIN_VM  = A0;
const float   VM_RATIO = 5.0f / 1023.0f * (47.0f + 10.0f) / 10.0f;   // volts par point du CAN

// ------------------------------------------------------------------ réglages (EEPROM)
struct ReglagesAxe {
  float vitesse;      // pas/s
  float accel;        // pas/s²
  long  jeu;          // pas
  uint8_t inverse;
  uint8_t maintien;
  float pasParArcmin; // 0 = pas encore calibré
};
struct Reglages {
  uint16_t magie;
  ReglagesAxe axe[2];
  uint8_t fcFermes;
  uint16_t seuilVm;   // dixièmes de volt
};
const uint16_t MAGIE = 0x4D31;   // "M1"
Reglages R;

void reglagesParDefaut() {
  R.magie = MAGIE;
  for (uint8_t i = 0; i < 2; i++) {
    R.axe[i].vitesse = 800.0f;
    R.axe[i].accel = 1600.0f;
    R.axe[i].jeu = 0;
    R.axe[i].inverse = 0;
    R.axe[i].maintien = 0;
    R.axe[i].pasParArcmin = 0.0f;
  }
  R.fcFermes = 0;
  R.seuilVm = 90;
}

void chargerReglages() {
  EEPROM.get(0, R);
  if (R.magie != MAGIE) {
    reglagesParDefaut();
    EEPROM.put(0, R);
  }
}

void sauverReglages() { EEPROM.put(0, R); }

// ------------------------------------------------------------------ état des axes
struct Axe {
  long pos;          // position logique en pas
  long cible;        // cible du mouvement en cours
  long apres;        // cible finale après le dépassement de rattrapage du jeu
  bool rattrapage;   // un retour vers 'apres' suit le mouvement en cours
  bool enMouvement;
  int8_t sens;       // +1 / -1
  float v;           // vitesse courante (pas/s)
  unsigned long dernierPas;
  unsigned long intervalle;
  bool arretDemande;
};
Axe ax[2];
uint8_t dernierArret = 0;
float vm = 0.0f;
unsigned long derniereMesureVm = 0;

bool fcAppuye(uint8_t pin) {
  bool bas = digitalRead(pin) == LOW;     // contact vers GND
  return R.fcFermes ? !bas : bas;
}

bool butee(uint8_t i, int8_t sens) {
  return sens > 0 ? fcAppuye(PIN_FC_MAX[i]) : fcAppuye(PIN_FC_MIN[i]);
}

void lireVm() {
  vm = analogRead(PIN_VM) * VM_RATIO;
  derniereMesureVm = millis();
}

bool alimOk() { return vm * 10.0f >= R.seuilVm; }

void moteur(uint8_t i, bool actif) { digitalWrite(PIN_EN[i], actif ? LOW : HIGH); }

void demarrer(uint8_t i, long cible) {
  Axe &a = ax[i];
  if (cible == a.pos) { a.enMouvement = false; return; }
  a.cible = cible;
  a.sens = cible > a.pos ? 1 : -1;
  bool versLeHaut = (a.sens > 0) != (R.axe[i].inverse != 0);
  digitalWrite(PIN_DIR[i], versLeHaut ? HIGH : LOW);
  moteur(i, true);
  delayMicroseconds(50);          // EN puis DIR établis avant le premier pas
  float vMin = sqrt(2.0f * R.axe[i].accel);
  if (vMin < 20.0f) vMin = 20.0f;
  a.v = vMin;
  a.intervalle = (unsigned long)(1000000.0f / a.v);
  a.dernierPas = micros() - a.intervalle;
  a.enMouvement = true;
  a.arretDemande = false;
}

// Mouvement relatif demandé par le PC ; renvoie le code de réponse
char mouvement(uint8_t i, long pas) {
  Axe &a = ax[i];
  if (a.enMouvement) return 'M';
  if (pas == 0) return '1';
  int8_t sens = pas > 0 ? 1 : -1;
  lireVm();
  if (!alimOk()) return 'A';
  if (butee(i, sens)) return 'B';
  long fin = a.pos + pas;
  long jeu = R.axe[i].jeu;
  if (sens < 0 && jeu > 0) {
    a.apres = fin;
    a.rattrapage = true;
    demarrer(i, fin - jeu);
  } else {
    a.rattrapage = false;
    demarrer(i, fin);
  }
  return '1';
}

void finMouvement(uint8_t i, uint8_t cause) {
  ax[i].enMouvement = false;
  ax[i].rattrapage = false;
  ax[i].arretDemande = false;
  if (!R.axe[i].maintien) moteur(i, false);
  dernierArret = cause;
}

void arreter(uint8_t i) {
  if (!ax[i].enMouvement) return;
  ax[i].arretDemande = true;
  ax[i].rattrapage = false;
}

void avancer(uint8_t i) {
  Axe &a = ax[i];
  if (!a.enMouvement) return;
  unsigned long t = micros();
  if ((unsigned long)(t - a.dernierPas) < a.intervalle) return;

  if (butee(i, a.sens)) { finMouvement(i, 1); return; }

  digitalWrite(PIN_STEP[i], HIGH);
  delayMicroseconds(3);
  digitalWrite(PIN_STEP[i], LOW);
  a.pos += a.sens;
  a.dernierPas = t;

  long reste = (a.cible - a.pos) * a.sens;
  if (reste <= 0) {
    if (a.rattrapage) {           // dépassement fait : retour sur la cible, dans le sens +
      a.rattrapage = false;
      demarrer(i, a.apres);
      return;
    }
    finMouvement(i, 0);
    return;
  }
  // Rampe trapézoïdale : v² varie de 2a par pas
  float acc = R.axe[i].accel;
  float vMin = sqrt(2.0f * acc);
  if (vMin < 20.0f) vMin = 20.0f;
  float distArret = a.v * a.v / (2.0f * acc);
  if (a.arretDemande) {
    float v2 = a.v * a.v - 2.0f * acc;
    if (v2 <= vMin * vMin) { finMouvement(i, 2); return; }
    a.v = sqrt(v2);
  } else if (reste <= distArret) {
    float v2 = a.v * a.v - 2.0f * acc;
    a.v = v2 > vMin * vMin ? sqrt(v2) : vMin;
  } else if (a.v < R.axe[i].vitesse) {
    a.v = sqrt(a.v * a.v + 2.0f * acc);
    if (a.v > R.axe[i].vitesse) a.v = R.axe[i].vitesse;
  }
  a.intervalle = (unsigned long)(1000000.0f / a.v);
}

// ------------------------------------------------------------------ liaison série
char tampon[32];
uint8_t lg = 0;
bool dansCommande = false;

void repondre(const char *s) { Serial.print(s); Serial.print('#'); }

int8_t indiceAxe(char c) {
  if (c == 'A') return 0;
  if (c == 'L') return 1;
  return -1;
}

void lireReglage(char x, char k) {
  char s[24];
  if (x == 'G') {
    if (k == 'F') { Serial.print(R.fcFermes); Serial.print('#'); return; }
    if (k == 'M') { Serial.print(R.seuilVm); Serial.print('#'); return; }
    repondre("0");
    return;
  }
  int8_t i = indiceAxe(x);
  if (i < 0) { repondre("0"); return; }
  ReglagesAxe &r = R.axe[i];
  switch (k) {
    case 'V': Serial.print(r.vitesse, 1); break;
    case 'C': Serial.print(r.accel, 1); break;
    case 'J': Serial.print(r.jeu); break;
    case 'I': Serial.print(r.inverse); break;
    case 'T': Serial.print(r.maintien); break;
    case 'K': dtostrf(r.pasParArcmin, 1, 4, s); Serial.print(s); break;
    default: Serial.print('0'); break;
  }
  Serial.print('#');
}

bool ecrireReglage(char x, char k, const char *val) {
  float f = atof(val);
  long n = atol(val);
  if (x == 'G') {
    if (k == 'F') { R.fcFermes = n ? 1 : 0; return true; }
    if (k == 'M' && n >= 0 && n <= 300) { R.seuilVm = n; return true; }
    return false;
  }
  int8_t i = indiceAxe(x);
  if (i < 0 || ax[i].enMouvement) return false;
  ReglagesAxe &r = R.axe[i];
  switch (k) {
    case 'V': if (f < 10.0f || f > 4000.0f) return false; r.vitesse = f; return true;
    case 'C': if (f < 10.0f || f > 50000.0f) return false; r.accel = f; return true;
    case 'J': if (n < 0 || n > 100000L) return false; r.jeu = n; return true;
    case 'I': r.inverse = n ? 1 : 0; return true;
    case 'T': r.maintien = n ? 1 : 0; moteur(i, r.maintien); return true;
    case 'K': if (f < 0.0f) return false; r.pasParArcmin = f; return true;
  }
  return false;
}

void executer(const char *c) {
  uint8_t n = strlen(c);
  if (!strcmp(c, "GVP")) { repondre("GotoAndrivet-MES"); return; }
  if (!strcmp(c, "GVN")) { repondre(MES_VERSION); return; }
  if (!strcmp(c, "GS")) {
    lireVm();
    char s[32];
    snprintf(s, sizeof(s), "%d,%d,%d%d%d%d,%d,%d", ax[0].enMouvement, ax[1].enMouvement,
             fcAppuye(PIN_FC_MIN[0]), fcAppuye(PIN_FC_MAX[0]), fcAppuye(PIN_FC_MIN[1]), fcAppuye(PIN_FC_MAX[1]),
             (int)(vm * 10.0f + 0.5f), dernierArret);
    repondre(s);
    return;
  }
  if (!strcmp(c, "Q")) { arreter(0); arreter(1); return; }
  if (n == 2 && c[0] == 'Q') { int8_t i = indiceAxe(c[1]); if (i >= 0) arreter(i); return; }
  if (n == 3 && c[0] == 'G' && c[1] == 'P') {
    int8_t i = indiceAxe(c[2]);
    if (i < 0) { repondre("0"); return; }
    char s[24];
    long p = ax[i].pos;
    snprintf(s, sizeof(s), "%c%08ld", p < 0 ? '-' : '+', p < 0 ? -p : p);
    repondre(s);
    return;
  }
  if (n == 3 && c[0] == 'S' && c[1] == 'Z') {
    int8_t i = indiceAxe(c[2]);
    if (i < 0 || ax[i].enMouvement) { repondre("0"); return; }
    ax[i].pos = 0;
    repondre("1");
    return;
  }
  if (n >= 4 && c[0] == 'M' && c[1] == 'R') {
    int8_t i = indiceAxe(c[2]);
    char *fin;
    long pas = strtol(c + 3, &fin, 10);
    if (i < 0 || *fin != '\0' || pas > 2000000L || pas < -2000000L) { repondre("0P"); return; }
    char r = mouvement(i, pas);
    if (r == '1') repondre("1");
    else { char s[3] = {'0', r, 0}; repondre(s); }
    return;
  }
  if (n == 4 && c[0] == 'G' && c[1] == 'C') { lireReglage(c[2], c[3]); return; }
  if (n >= 5 && c[0] == 'S' && c[1] == 'C') {
    if (ecrireReglage(c[2], c[3], c + 4)) { sauverReglages(); repondre("1"); }
    else repondre("0");
    return;
  }
  // commande inconnue : pas de réponse (comme LX200)
}

void lireSerie() {
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == ':') { dansCommande = true; lg = 0; continue; }
    if (!dansCommande) continue;
    if (ch == '#') {
      tampon[lg] = 0;
      dansCommande = false;
      executer(tampon);
      continue;
    }
    if (lg < sizeof(tampon) - 1) tampon[lg++] = ch;
    else dansCommande = false;     // trop long : ignoré
  }
}

// ------------------------------------------------------------------ voyant et 12 V
void surveiller() {
  unsigned long t = millis();
  if ((unsigned long)(t - derniereMesureVm) >= 50) {
    lireVm();
    if (!alimOk()) {
      for (uint8_t i = 0; i < 2; i++)
        if (ax[i].enMouvement) finMouvement(i, 3);     // plus de 12 V : on arrête net
    }
  }
  bool bouge = ax[0].enMouvement || ax[1].enMouvement;
  bool led = bouge || (!alimOk() && ((t / 500) & 1));
  digitalWrite(PIN_LED, led ? HIGH : LOW);
}

void setup() {
  for (uint8_t i = 0; i < 2; i++) {
    pinMode(PIN_EN[i], OUTPUT);
    digitalWrite(PIN_EN[i], HIGH);
    pinMode(PIN_STEP[i], OUTPUT);
    digitalWrite(PIN_STEP[i], LOW);
    pinMode(PIN_DIR[i], OUTPUT);
    pinMode(PIN_FC_MIN[i], INPUT_PULLUP);
    pinMode(PIN_FC_MAX[i], INPUT_PULLUP);
    ax[i] = Axe();
  }
  pinMode(PIN_LED, OUTPUT);
  chargerReglages();
  for (uint8_t i = 0; i < 2; i++) moteur(i, R.axe[i].maintien);
  lireVm();
  Serial.begin(38400);
}

void loop() {
  lireSerie();
  avancer(0);
  avancer(1);
  surveiller();
}
