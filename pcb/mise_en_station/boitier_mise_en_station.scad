// ============================================================================
// BOITIER PARAMÉTRIQUE DE LA CARTE DE MISE EN STATION ROBOTISÉE - GOTO-ANDRIVET
// Arduino Nano + 2 drivers StepStick (TMC2209, A4988, DRV8825), carte 110 x 85 mm
// Conçu pour impression 3D (PETG conseillé dehors), sans support.
//
//   openscad -D 'mode="base"'      -o boitier_mise_en_station_base.stl      boitier_mise_en_station.scad
//   openscad -D 'mode="couvercle"' -o boitier_mise_en_station_couvercle.stl boitier_mise_en_station.scad
//   mode "ensemble" : boîtier fermé avec les gabarits des pièces ; modes "verif_*" : contrôle des
//   collisions (le rendu doit être vide, voir verifier_boitier.sh).
// ============================================================================

$fn = 40;

// Dimensions du PCB
pcb_w = 110;
pcb_h = 85;
pcb_thick = 1.6;

// Paramètres du boîtier
wall = 2.5;         // Épaisseur des parois
clearance = 1.5;    // Jeu autour du PCB (flancs gauche et droit, côté borniers)
c_bas = 6.0;        // Jeu côté bas (Y = 0) : laisse la place aux piliers des vis du couvercle
standoff_h = 5.0;   // Hauteur des entretoises sous le PCB
box_h = 40.0;       // Hauteur du boîtier : ~8 mm libres au-dessus des TMC2209 avec radiateur
lid_thick = 2.5;    // Épaisseur du couvercle

// Chambre de câblage côté borniers (Y = max, Y_kicad = 0) : les fils des câbles s'y écartent jusqu'aux
// vis des borniers, dont les entrées font face à la paroi.
ch_haut = 22;

inner_w = pcb_w + 2 * clearance;
inner_h = c_bas + pcb_h + clearance + ch_haut;
outer_w = inner_w + 2 * wall;
outer_h = inner_h + 2 * wall;

// Origine de la carte (coin bas gauche du PCB, Y_kicad = 85) et dessus du PCB
px0 = wall + clearance;
py0 = wall + c_bas;
zt = wall + standoff_h + pcb_thick;

// Repère : X_scad = px0 + X_kicad, Y_scad = py0 + 85 - Y_kicad.
function k(x, y) = [px0 + x, py0 + pcb_h - y];

// Presse-étoupes PG7 ou M12 x 1,5 (câble de 3 à 6,5 mm), contre-écrou de 15 mm sur plats à l'intérieur.
// Centre à Z = 13,5, à la hauteur des entrées de fil des borniers ; l'écrou (17,3 mm sur angles,
// Z 4,8..22,2) reste dans la chambre. Centres espacés d'au moins 18 mm : les écrous ne se touchent pas.
pe_d = 12.5;
pe_z = 13.5;
// X_kicad des presse-étoupes : moteur azimut, câble I2C (pastille à défoncer), moteur hauteur,
// fins de course azimut, fins de course hauteur
pe_moteurs = [24.0, 60.0];      // centres des borniers M_AZ, M_ALT
pe_fc = [79.0, 97.0];           // à côté de J_FC_AZ (83,5) et J_FC_ALT (95,5)
pe_opercule = 42.0;
opercule = 0.6;                 // peau laissée côté intérieur, à percer d'un coup de tournevis

// USB du Nano (mini-USB, centre Y_kicad 66,38, face à X_kicad 109,46), Nano sur barrettes femelles :
// connecteur vers 14,6 mm au-dessus de la carte. L'ouverture va de 1 à 21 mm au-dessus de la carte :
// elle passe aussi un Nano soudé directement, ou à prise micro-USB ou USB-C.
usb_y = 66.38;
// Jack 12 V (corps centré Y_kicad 66,0, face à X_kicad 0,29), axe à 6,4 mm au-dessus de la carte.
jack_y = 66.0;
jack_z = 6.4;

// Trous de fixation de la carte (H1..H4)
pcb_holes = [[5, 5], [105, 5], [5, 80], [105, 80]];

// Vis du couvercle dans les 4 coins
corners = [
    [wall + 1.5, wall + 1.5],
    [outer_w - wall - 1.5, wall + 1.5],
    [wall + 1.5, outer_h - wall - 1.5],
    [outer_w - wall - 1.5, outer_h - wall - 1.5]
];

// Pattes de fixation sur la monture : 2 de chaque côté, lumière de 5,5 mm (vis M5 ou M4)
patte_l = 12;       // dépassement hors du boîtier
patte_e = 4;        // épaisseur
patte_y = [18, outer_h - 18];

// Modules drivers (centres entre les deux rangées de leur support)
drv_x = [24.0, 60.0];
drv_y = 36.89;

module coque() {
    hull() {
        translate([3, 3, 0]) cylinder(r=3, h=box_h);
        translate([outer_w - 3, 3, 0]) cylinder(r=3, h=box_h);
        translate([3, outer_h - 3, 0]) cylinder(r=3, h=box_h);
        translate([outer_w - 3, outer_h - 3, 0]) cylinder(r=3, h=box_h);
    }
}

module patte(cote, y) {   // cote = -1 à gauche, +1 à droite
    x0 = cote < 0 ? -patte_l : outer_w - 1;
    difference() {
        translate([x0, y - 8, 0]) cube([patte_l + 1, 16, patte_e]);
        // lumière oblongue, pour rattraper la position des trous
        hull() for (dx = [3.5, patte_l - 4.5])
            translate([cote < 0 ? -patte_l + dx : outer_w + patte_l - dx, y, -1]) cylinder(d=5.5, h=patte_e + 2);
    }
}

// ----------------------------------------------------------------------------
// 1. CORPS INFÉRIEUR (BASE DU BOÎTIER)
// ----------------------------------------------------------------------------
module boitier_base() {
    difference() {
        union() {
            difference() {
                coque();
                // Évidement intérieur
                translate([wall, wall, wall]) cube([inner_w, inner_h, box_h + 1]);

                // A. Paroi des borniers (Y = max) : 4 presse-étoupes et la pastille du câble I2C
                for (x = concat(pe_moteurs, pe_fc))
                    translate([px0 + x, outer_h - wall - 1, pe_z]) rotate([-90, 0, 0]) cylinder(d=pe_d, h=wall + 2, $fn=64);
                translate([px0 + pe_opercule, outer_h - wall + opercule, pe_z])
                    rotate([-90, 0, 0]) cylinder(d=pe_d, h=wall, $fn=64);

                // B. Flanc gauche (X = 0) : jack 12 V, trou de 12 mm pour le corps de la fiche
                translate([-1, k(0, jack_y)[1], zt + jack_z]) rotate([0, 90, 0]) cylinder(d=12, h=wall + 2, $fn=64);

                // C. Flanc droit (X = max) : câble USB du Nano
                translate([outer_w - wall - 1, k(0, usb_y)[1] - 6.5, zt + 1]) cube([wall + 2, 13, 20]);
            }

            // Entretoises de la carte
            for (p = pcb_holes)
                translate([k(p[0], p[1])[0], k(p[0], p[1])[1], wall - 0.2])
                    difference() {
                        cylinder(d=7.0, h=standoff_h + 0.2);
                        translate([0, 0, -0.1]) cylinder(d=2.8, h=standoff_h + 1);   // vis M3 x 6
                    }

            // Piliers des vis du couvercle
            for (c = corners)
                translate([c[0], c[1], wall - 0.2])
                    difference() {
                        cylinder(d=6.0, h=box_h - wall + 0.2);
                        translate([0, 0, box_h - wall - 12]) cylinder(d=2.8, h=13);   // vis M3 x 10 fraisée
                    }

            // Pattes de fixation
            for (y = patte_y) { patte(-1, y); patte(1, y); }
        }
        // Dégagement de la carte (pose sans forcer)
        translate([px0 - 0.5, py0 - 0.5, wall + standoff_h]) cube([pcb_w + 1.0, pcb_h + 1.0, pcb_thick + 1.5]);
    }
}

// ----------------------------------------------------------------------------
// 2. COUVERCLE (imprimé à plat, face extérieure sur le plateau)
// Dans le couvercle, X est en miroir : X_couvercle = outer_w - X_base.
// ----------------------------------------------------------------------------
module boitier_couvercle() {
    difference() {
        union() {
            hull() {
                translate([3, 3, 0]) cylinder(r=3, h=lid_thick);
                translate([outer_w - 3, 3, 0]) cylinder(r=3, h=lid_thick);
                translate([3, outer_h - 3, 0]) cylinder(r=3, h=lid_thick);
                translate([outer_w - 3, outer_h - 3, 0]) cylinder(r=3, h=lid_thick);
            }
            // Rebord d'emboîtement intérieur, échancré autour des piliers des vis
            translate([wall + 0.3, wall + 0.3, lid_thick])
                difference() {
                    cube([inner_w - 0.6, inner_h - 0.6, 2.5]);
                    translate([2, 2, -0.5]) cube([inner_w - 4.6, inner_h - 4.6, 4]);
                }
        }
        for (c = corners) {
            translate([c[0], c[1], lid_thick - 0.01]) cylinder(d=6.8, h=4);   // place des piliers
            translate([c[0], c[1], -1]) {
                cylinder(d=3.4, h=lid_thick + 5);
                cylinder(d1=6.5, d2=3.4, h=2.5);   // fraisage de la tête de vis
            }
        }
        // Grilles d'aération au-dessus des deux drivers
        for (cx = drv_x)
            for (gy = [-10 : 4 : 10])
                translate([outer_w - k(cx, 0)[0] - 9, k(0, drv_y)[1] + gy - 1.1, -1]) cube([18, 2.2, lid_thick + 2]);
        // Voyant D_ACT (LED 3 mm, centre X_kicad 99,77 ; Y_kicad 50,5)
        translate([outer_w - k(99.77, 0)[0], k(0, 50.5)[1], -1]) cylinder(d=4, h=lid_thick + 2);
    }
}

// Couvercle à sa place sur la base
module couvercle_pose() {
    translate([outer_w, 0, box_h + lid_thick]) rotate([0, 180, 0]) boitier_couvercle();
}

// ----------------------------------------------------------------------------
// 3. GABARITS DES PIÈCES (hauteurs au-dessus de la carte, prises larges)
// ----------------------------------------------------------------------------
module kbox(x1, x2, y1, y2, z1, z2) {
    translate([px0 + x1, py0 + pcb_h - y2, zt + z1]) cube([x2 - x1, y2 - y1, z2 - z1]);
}
module kcyl(x, y, d, z1, z2) {
    translate([px0 + x, py0 + pcb_h - y, zt + z1]) cylinder(d=d, h=z2 - z1);
}

module encombrement() {
    // Carte, et pattes des composants sous la carte (2 mm), sauf autour des trous de fixation
    kbox(0, pcb_w, 0, pcb_h, -pcb_thick, 0);
    difference() {
        kbox(0, pcb_w, 0, pcb_h, -pcb_thick - 2, -pcb_thick);
        for (p = pcb_holes) kcyl(p[0], p[1], 7.6, -pcb_thick - 3, 1);
    }
    // Têtes des vis M3 de la carte
    for (p = pcb_holes) kcyl(p[0], p[1], 5.8, 0, 3);
    // Drivers : barrettes femelles 8,5 mm, module 15,3 x 20,4 mm avec radiateur jusqu'à 23 mm
    for (cx = drv_x) {
        for (dx = [-6.35, 6.35]) kbox(cx + dx - 1.3, cx + dx + 1.3, 26.2, 47.6, 0, 8.5);
        kbox(cx - 7.65, cx + 7.65, drv_y - 10.2, drv_y + 10.2, 8.5, 23);
    }
    // Nano sur barrettes femelles : carte de 11 à 12,6 mm, composants et ICSP jusqu'à 19 mm,
    // prise mini-USB de 12,6 à 16,6 mm
    kbox(66.2, 104.4, 57.4, 75.4, 0, 8.5);
    kbox(63.64, 106.92, 57.44, 75.32, 8.5, 19);
    kbox(99.2, 109.46, 62.52, 70.24, 11, 16.6);
    // Fiche USB : surmoulage de 11 x 8 mm qui entre jusqu'à 0,5 mm de la prise
    kbox(109.96, 140, usb_y - 5.5, usb_y + 5.5, 14.6 - 4, 14.6 + 4);
    // Jack 12 V et fiche (surmoulage de 11 mm de diamètre)
    kbox(0.29, 14.89, 61.45, 70.55, 0, 11);
    translate([-40, k(0, jack_y)[1], zt + jack_z]) rotate([0, 90, 0]) cylinder(d=11, h=40 + px0 + 0.29 - 0.5);
    // Condensateurs, fusible, diode
    kcyl(53.5, 77.5, 10.5, 0, 21);    // C_IN 470 µF 35 V, 10 x 20 mm
    kcyl(24.0, 21.6, 8.5, 0, 13);     // C_AZ 100 µF 35 V, 8 x 11,5 mm
    kcyl(60.0, 21.6, 8.5, 0, 13);     // C_ALT
    kcyl(24.54, 79.0, 8.6, 0, 10);    // F_IN
    kbox(30.1, 46.6, 76.1, 81.9, 0, 6);   // D_IN
    // Borniers, et fils jusqu'à la paroi
    kbox(13.29, 34.7, 2.85, 13.76, 0, 10.5);   // M_AZ
    kbox(49.3, 70.7, 2.85, 13.76, 0, 10.5);    // M_ALT
    kbox(77.7, 89.3, 2.96, 11.64, 0, 9);       // J_FC_AZ
    kbox(89.7, 101.3, 2.96, 11.64, 0, 9);      // J_FC_ALT
    // Barrette I2C et son connecteur Dupont, voyant
    kbox(104.2, 107.8, 31.2, 42.4, 0, 8.5 + 14);
    kbox(98.2, 101.8, 48.5, 52.5, 0, 6);
    // Contre-écrous des presse-étoupes (17,3 mm sur angles, 5 mm d'épaisseur) côté intérieur
    for (x = concat(pe_moteurs, pe_fc, [pe_opercule]))
        translate([px0 + x, outer_h - wall - 5, pe_z]) rotate([-90, 0, 0]) cylinder(d=17.3, h=5, $fn=6);
}

// ----------------------------------------------------------------------------
// CHOIX DU MODÈLE : "base", "couvercle", "ensemble", "vue", ou "verif_*" (doit être vide)
// ----------------------------------------------------------------------------
mode = "ensemble";

if (mode == "base") {
    boitier_base();
} else if (mode == "couvercle") {
    boitier_couvercle();
} else if (mode == "verif_base") {
    intersection() { boitier_base(); encombrement(); }
} else if (mode == "verif_couvercle") {
    intersection() { couvercle_pose(); encombrement(); }
} else if (mode == "verif_fermeture") {
    intersection() { couvercle_pose(); boitier_base(); }
} else if (mode == "vue") {
    // Image du site : boîtier ouvert, couvercle soulevé de 15 mm
    boitier_base();
    translate([0, 0, 15]) couvercle_pose();
} else {
    color([0.2, 0.2, 0.2]) boitier_base();
    color([0.3, 0.5, 0.8, 0.5]) couvercle_pose();
    color([0.1, 0.6, 0.2]) encombrement();
}
