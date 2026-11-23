// Monture virtuelle a defauts reels, partagee par les tests du modele.
#pragma once
#include "banc.h"

struct Defauts {
  const char* nom;
  double ih, id;        // decalages des codeurs (deg)
  double pa, pb;        // inclinaison de l'axe principal (mise en station / calage)
  double cone, np;      // tube pas d'equerre, axes pas perpendiculaires
  double tf;            // flexion du tube (vers l'horizon, x cos hauteur)
  double fo;            // flexion de fourche (dec += fo cos AH)
  double e1s, e1c;      // excentricite axe 1 (x sin a, x cos a)
  double e2s, e2c;      // excentricite axe 2
};

static Defauts D;

static V3 zenithF() {
  if (mountType == 0) return {0, 0, 1};
  return {cos(siteLat * DEG_TO_RAD), 0, sin(siteLat * DEG_TO_RAD)};
}

// Position des moteurs (a_m, e_m) -> direction reelle du tube (repere du ciel).
static V3 mech(double am, double em) {
  double A = am - D.ih + D.e1s * sin(am * DEG_TO_RAD) + D.e1c * cos(am * DEG_TO_RAD);
  double E = em - D.id + D.e2s * sin(em * DEG_TO_RAD) + D.e2c * cos(em * DEG_TO_RAD)
           + D.fo * cos(am * DEG_TO_RAD);
  double c = D.cone * DEG_TO_RAD, er = E * DEG_TO_RAD;
  V3 t = {cos(c) * cos(er), sin(c), cos(c) * sin(er)};
  t = rotX(t, D.np);
  t = rotZ(t, -A);
  t = rotX(t, D.pa);
  t = rotY(t, D.pb);
  if (D.tf != 0.0) {
    V3 z = zenithF();
    double s = dot(t, z);
    V3 u = {z.x - s * t.x, z.y - s * t.y, z.z - s * t.z};
    double n = norm(u);
    if (n > 1e-9) {
      u = {u.x / n, u.y / n, u.z / n};
      double d = D.tf * n * DEG_TO_RAD;   // n = cos(hauteur)
      t = {t.x * cos(d) - u.x * sin(d), t.y * cos(d) - u.y * sin(d), t.z * cos(d) - u.z * sin(d)};
    }
  }
  return t;
}

// Moteurs qui pointent exactement la direction w (Gauss-Newton depuis a0, e0).
static void inverse(V3 w, double a0, double e0, double* am, double* em) {
  double a = a0, e = e0;
  for (int it = 0; it < 30; it++) {
    V3 f = mech(a, e);
    V3 r = {w.x - f.x, w.y - f.y, w.z - f.z};
    const double h = 1e-5;
    V3 fa = mech(a + h, e), fe = mech(a, e + h);
    V3 ja = {(fa.x - f.x) / h, (fa.y - f.y) / h, (fa.z - f.z) / h};
    V3 je = {(fe.x - f.x) / h, (fe.y - f.y) / h, (fe.z - f.z) / h};
    double aa = dot(ja, ja), ae = dot(ja, je), ee = dot(je, je);
    double ba = dot(ja, r), be = dot(je, r);
    double det = aa * ee - ae * ae;
    if (fabs(det) < 1e-30) break;
    double da = (ee * ba - ae * be) / det, de = (aa * be - ae * ba) / det;
    a += da; e += de;
    if (fabs(da) + fabs(de) < 1e-10) break;
  }
  *am = a; *em = e;
}

static std::mt19937 rng;
static double urand(double a, double b) { return std::uniform_real_distribution<double>(a, b)(rng); }
static double nrand(double s) { return std::normal_distribution<double>(0.0, s)(rng); }

// Etoile visible au hasard (hauteur > hmin), en coordonnees de la monture.
static void tirage(double hmin, long* ra, long* dec) {
  for (;;) {
    double h = urand(0, 360), d = urand(-60, 89);
    if (mountType != 0 && fabs(d) > 84.0) continue;        // synchro refusee pres du pole
    double lr = siteLat * DEG_TO_RAD, hr = h * DEG_TO_RAD, dr = d * DEG_TO_RAD;
    double alt = asin(sin(dr) * sin(lr) + cos(dr) * cos(lr) * cos(hr)) * RAD_TO_DEG;
    if (alt < hmin) continue;
    if (mountType == 0 && alt > 85.0) continue;
    double r = lst() - h / 15.0;
    while (r < 0) r += 24.0;
    while (r >= 24.0) r -= 24.0;
    *ra = lround(r * 3600.0); *dec = lround(d * 3600.0);
    return;
  }
}

static void ideal(long ra, long dec, double* a, double* e) {
  ideal_rd2aa_at(ra / 3600.0, dec / 3600.0, e, a, 0.0);
}

// La monture pointe en vrai (moteurs) l'etoile ra/dec, au centrage pres, puis :CM.
static std::string syncSur(long ra, long dec, double bruitArcmin, long faussRa = -1, long faussDec = 0) {
  double a, e; ideal(ra, dec, &a, &e);
  V3 w = v3(a, e);
  if (bruitArcmin > 0) {
    w = rotX(w, nrand(bruitArcmin / 60.0)); w = rotY(w, nrand(bruitArcmin / 60.0)); w = rotZ(w, nrand(bruitArcmin / 60.0));
  }
  double am, em; inverse(w, a, e, &am, &em);
  currAz = fmod(am, 360.0); if (currAz < 0) currAz += 360.0;
  currAlt = em;
  azPos = azPosFromAz(currAz); altPos = (long)(currAlt * ALT_PPD);
  inRA = faussRa >= 0 ? faussRa : ra;
  inDEC = faussRa >= 0 ? faussDec : dec;
  return cmd(":CM#");
}

// Erreur de pointage (arcmin) sur des cibles tirees au hasard.
static void evaluer(int n, std::vector<double>& err) {
  err.clear();
  for (int i = 0; i < n; i++) {
    long ra, dec; tirage(15.0, &ra, &dec);
    double a, e; ideal(ra, dec, &a, &e);
    double ma, me; rd2mach_at(ra / 3600.0, dec / 3600.0, &me, &ma, 0.0);
    err.push_back(angDeg(mech(ma, me), v3(a, e)) * 60.0);
  }
  std::sort(err.begin(), err.end());
}

