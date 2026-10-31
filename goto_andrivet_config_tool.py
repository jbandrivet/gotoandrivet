#!/usr/bin/env python3
# Auteur : Andrivet Jean-Baptiste
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
import serial
import serial.tools.list_ports
import time
import json
from pathlib import Path
from datetime import datetime
import subprocess
import threading
import os
import re
import mise_a_jour

CONFIG_FILE = Path.home() / ".config" / "goto_andrivet" / "config_tool_settings.json"

DEFAULTS = {
    "mount_port": "/dev/ttyACM0",
    "mount_baud": 38400,
    "gear_ratio_az": "",
    "gear_ratio_alt": "",
    "mount_type": "AltAz",
    "obs_lat": 48.8566,
    "obs_lon": 2.3522,
    "slew_speed": 2.0,
    "buzzer_on": True,
    "steps_per_rev_motor": 200,
    "microstep": 125,
    "language": "fr",
    "rev_az": False,
    "rev_alt": False,
    "park_alt": 0.0,
    "park_az": 0.0,
    # Drivers TMC5160 en SPI (firmware Teensy uniquement)
    "tmc_spi": True,
    "tmc_current": [800, 800, 400, 400],   # mA RMS : AZ, ALT, DEROT, FOCUS
    "tmc_hold": 50,
    "tmc_stealth": True,
    "tmc_ms_derot": 16,
    "tmc_ms_focus": 16,
    # Câblage de la monture : "stepstick" (pcb/monture), "ext" (pcb/monture_ext)
    # ou "none" (câblage manuel d'après le plan de câblage du README)
    "hardware": "none",
    "board": "Teensy 4.1"
}

TMC_AXES = ("a", "e", "d", "f")   # AZ, ALT, DEROT, FOCUS (commandes :XTI<axe>)
TMC_STATE_TEXT = {"-": "SPI coupé", "0": "absent", "1": "OK", "M": "µpas ?", "E": "défaut"}

HARDWARE_CHOICES = ("stepstick", "ext", "none")

# Plan de câblage de la monture, repris du README (section 4) et conforme aux
# broches des firmwares : composant (fr, en), broche Mega 2560, broche Teensy 4.1
# (None = non disponible), signal côté driver ou module (fr, en).
WIRING_PLAN = (
    ("Moteur Azimut (AZ/RA)", "Azimuth motor (AZ/RA)", "2", "2", "PUL+ (Pulse/Step)", "PUL+ (Pulse/Step)"),
    ("", "", "3", "3", "DIR+ (Direction)", "DIR+ (Direction)"),
    ("", "", "4", "4", "ENB+ (Enable)", "ENB+ (Enable)"),
    ("Moteur Altitude (ALT/DEC)", "Altitude motor (ALT/DEC)", "5", "5", "PUL+ (Pulse/Step)", "PUL+ (Pulse/Step)"),
    ("", "", "6", "6", "DIR+ (Direction)", "DIR+ (Direction)"),
    ("", "", "7", "7", "ENB+ (Enable)", "ENB+ (Enable)"),
    ("Moteur Dérotateur", "Derotator motor", "8", "8", "PUL+ (Pulse/Step)", "PUL+ (Pulse/Step)"),
    ("", "", "9", "9", "DIR+ (Direction)", "DIR+ (Direction)"),
    ("", "", "10", "10", "ENB+ (Enable)", "ENB+ (Enable)"),
    ("Moteur Focuseur", "Focuser motor", "11", "11", "PUL+ (Pulse/Step)", "PUL+ (Pulse/Step)"),
    ("", "", "12", "12", "DIR+ (Direction)", "DIR+ (Direction)"),
    ("", "", "13", "21", "ENB+ (Enable)", "ENB+ (Enable)"),
    ("Buzzer", "Buzzer", "49", "20", "Borne + (actif : direct / passif : via 100 Ω)", "+ terminal (active: direct / passive: via 100 Ω)"),
    ("Port série PC", "PC serial port", None, "25 (RX6)", "TX de l'adaptateur USB/série TTL", "TX of the USB/TTL serial adapter"),
    ("", "", None, "24 (TX6)", "RX de l'adaptateur USB/série TTL", "RX of the USB/TTL serial adapter"),
    ("Raquette Teensy", "Teensy hand controller", "15 (RX3)", "15 (RX3)", "TX de la raquette", "Hand controller TX"),
    ("", "", "14 (TX3)", "14 (TX3)", "RX de la raquette", "Hand controller RX"),
    ("Module GPS", "GPS module", "17 (RX2)", "16 (RX4)", "TX du module GPS", "GPS module TX"),
    ("", "", "16 (TX2)", "17 (TX4)", "RX du module GPS", "GPS module RX"),
    ("Drivers TMC5160 (SPI1)", "TMC5160 drivers (SPI1)", None, "26 (MOSI1)", "SDI des modules", "Module SDI"),
    ("", "", None, "27 (SCK1)", "SCK des modules", "Module SCK"),
    ("", "", None, "39 (MISO1)", "SDO des modules", "Module SDO"),
    ("", "", None, "41 / 40 / 38 / 37", "CSN AZ / ALT / dérotateur / focuseur", "CSN AZ / ALT / derotator / focuser"),
)

# Raquette physique (Teensy 4.1), README section 4.1 : composant, broche, connexion.
WIRING_HANDPAD = (
    ("Écran LCD (I2C)", "LCD screen (I2C)", "18 (SDA0)", "SDA", "SDA"),
    ("", "", "19 (SCL0)", "SCL", "SCL"),
    ("", "", "VIN / GND", "VCC (5 V) / GND", "VCC (5 V) / GND"),
    ("Boutons (vers GND)", "Buttons (to GND)", "6 / 7 / 8 / 9 / 10", "Haut / Bas / Gauche / Droite / Entrée", "Up / Down / Left / Right / Enter"),
    ("Câble vers la monture", "Cable to the mount", "GND / VIN", "Broches 1 / 2 (GND / 5 V de la monture)", "Pins 1 / 2 (mount GND / 5 V)"),
    ("", "", "1 (TX1)", "Broche 3, vers RX3 (broche 15) de la monture", "Pin 3, to mount RX3 (pin 15)"),
    ("", "", "0 (RX1)", "Broche 4, vers TX3 (broche 14) de la monture", "Pin 4, to mount TX3 (pin 14)"),
)

TRANSLATIONS = {
    "en": {
        "title": " GotoAndrivet Configuration Utility",
        "conn_lf": "Connection Settings",
        "port": "Port:",
        "baud": "Baud:",
        "connect": "Connect",
        "disconnect": "Disconnect",
        "disconnected": "Disconnected",
        "connected": "Connected",
        "mount_params": "Telescope Mount parameters",
        "mount_type": "Mount Type:",
        "motor_steps": "Motor Steps/Rev:",
        "microstepping": "Microstepping:",
        "gear_ratio_az": "AZ/RA Gear Ratio:",
        "gear_ratio_alt": "ALT/DEC Ratio:",
        "latitude": "Site Latitude (N):",
        "longitude": "Longitude (E):",
        "park_pos": "Park Position:",
        "park_alt": "Altitude (deg):",
        "park_az": "Azimuth (deg):",
        "park_dec": "DEC (deg):",
        "park_ra": "RA/HA (deg):",
        "gps_coords": "GPS Coordinates:",
        "auto_detect": "Auto Detect (Internet)",
        "goto_speed": "GoTo Speed (°/s):",
        "buzzer": "Bip/Buzzer Mount:",
        "enabled": "Enabled",
        "test_beep": "Test Beep",
        "time_sync": "Time Synchronization",
        "sync_clock": "Synchronize Arduino with PC clock",
        "sync_pc_clock": "Sync PC from Arduino (GPS)",
        "clock_not_synced": "PC clock not synced",
        "clock_synced": "PC clock synced",
        "read_config": "Read Config from Arduino",
        "apply_config": "Apply & Save to Arduino",
        "virtual_pad": "Virtual Handpad",
        "lang_label": "Language / Langue:",
        "mount_control": "Mount Control",
        "park_mount": "Park Mount ⏾",
        "unpark_mount": "Unpark Mount ☉",
        "motor_inversion": "Motor Inversion:",
        "rev_az": "Reverse AZ/RA",
        "rev_alt": "Reverse ALT/DEC",
        "flash_lf": "Firmware Flashing (arduino-cli)",
        "flash_mega": "Update & Flash (Mega)",
        "flash_teensy": "Update & Flash (Teensy)",
        "flashing_title": "Firmware Flashing",
        "flashing_success": "Successfully compiled and flashed the firmware!",
        "flashing_error": "Compilation or Flashing failed:\n",
        "cli_not_found": "arduino-cli was not found. Please install it (or copy to ~/.local/bin/arduino-cli) to use this feature.",
        "hw_label": "Mount wiring:",
        "hw_stepstick": "StepStick PCB (pcb/monture)",
        "hw_ext": "External drivers PCB (pcb/monture_ext)",
        "hw_none": "No PCB: manual wiring",
        "hw_info_stepstick": "Teensy 4.1 on the StepStick PCB: A4988 or DRV8825 modules (RESET tied to SLEEP), TMC2208/2209, or TMC5160 (SPI jumpers closed). Cut the Teensy VUSB-VIN pad.",
        "hw_info_ext": "Teensy 4.1 on the external drivers PCB: 5 V EN/STEP/DIR signals to ENA+/PUL+/DIR+ (DM542, DM556, TB6600...). No SPI bus: TMC5160 settings are not used.",
        "hw_info_none": "Manual wiring of a Mega 2560 or a Teensy 4.1: follow the wiring plan (button next to the choice). The pins are those of the firmware.",
        "wiring_btn": "Wiring plan",
        "wiring_title": "Mount wiring plan",
        "wiring_col_comp": "Component",
        "wiring_col_pin": "{board} pin",
        "wiring_col_sig": "Driver / module signal",
        "wiring_na": "not available",
        "wiring_gnd": "Negative signals (PUL-, DIR-, ENB-) and all grounds (drivers, buzzer, GPS, hand controller) go to a GND pin of the board.",
        "wiring_note_stepstick": "The StepStick PCB already makes this wiring. Motors: M_AZ, M_ALT, M_DEROT, M_FOCUS terminals (1 = 2B, 2 = 2A, 3 = 1A, 4 = 1B). Hand controller: J_RAQUETTE (1 GND, 2 +5V, 3 RX3, 4 TX3). GPS: J_GPS (1 RX4, 2 TX4, 3 +5V, 4 GND). PC: J_PC_SERIAL (1 GND, 2 +5V, 3 TX6, 4 RX6), RX/TX given on the Teensy side. Power: 36 V terminal or 12 V jack. Close the 5 SPI jumpers of an axis only for a TMC5160.",
        "wiring_note_ext": "The external drivers PCB already makes this wiring, with 5 V outputs. Per axis: J_VM (1 GND, 2 VM) powers the driver, J_SIG (1 GND, 2 DIR, 3 STEP, 4 EN) goes to DIR+/PUL+/ENA+, and PUL-/DIR-/ENA- go to GND. Hand controller, GPS and PC connectors are the same as on the StepStick PCB. No SPI bus.",
        "wiring_note_none": "Wire the {board} by following this plan: it is the one the firmware uses.",
        "wiring_handpad": "Physical hand controller (Teensy 4.1)",
        "wiring_close": "Close",
    },
    "fr": {
        "title": " Utilitaire de Configuration GotoAndrivet",
        "conn_lf": "Paramètres de Connexion",
        "port": "Port :",
        "baud": "Baud :",
        "connect": "Connecter",
        "disconnect": "Déconnecter",
        "disconnected": "Déconnecté",
        "connected": "Connecté",
        "mount_params": "Paramètres de la Monture",
        "mount_type": "Type de Monture :",
        "motor_steps": "Pas moteur/Tour :",
        "microstepping": "Microstepping :",
        "gear_ratio_az": "Rapport AZ/RA :",
        "gear_ratio_alt": "Rapport DEC/ALT :",
        "latitude": "Latitude du Site (N) :",
        "longitude": "Longitude (E) :",
        "park_pos": "Position Parking :",
        "park_alt": "Altitude (deg) :",
        "park_az": "Azimut (deg) :",
        "park_dec": "DEC (deg) :",
        "park_ra": "RA/HA (deg) :",
        "gps_coords": "Coordonnées GPS :",
        "auto_detect": "Détection Auto (Internet)",
        "goto_speed": "Vitesse GoTo (°/s) :",
        "buzzer": "Bip/Buzzer Monture :",
        "enabled": "Actif",
        "test_beep": "Tester Bip",
        "time_sync": "Synchronisation de l'Heure",
        "sync_clock": "Synchroniser l'Arduino avec l'heure du PC",
        "sync_pc_clock": "Synchroniser le PC depuis l'Arduino (GPS)",
        "clock_not_synced": "Horloge PC non synchronisée",
        "clock_synced": "Horloge PC synchronisée",
        "read_config": "Lire la configuration Arduino",
        "apply_config": "Appliquer & Enregistrer",
        "virtual_pad": "Raquette Virtuelle",
        "lang_label": "Langue :",
        "mount_control": "Contrôle Monture",
        "park_mount": "Parquer Monture ⏾",
        "unpark_mount": "Déparquer Monture ☉",
        "motor_inversion": "Inversion moteurs :",
        "rev_az": "Inverser AZ/RA",
        "rev_alt": "Inverser ALT/DEC",
        "flash_lf": "Téléversement du Firmware (arduino-cli)",
        "flash_mega": "Mettre à jour & Flasher (Mega)",
        "flash_teensy": "Mettre à jour & Flasher (Teensy)",
        "flashing_title": "Téléversement du Firmware",
        "flashing_success": "Le firmware a été compilé et téléversé avec succès !",
        "flashing_error": "Échec de compilation ou téléversement :\n",
        "cli_not_found": "arduino-cli est introuvable. Veuillez l'installer (ou le copier dans ~/.local/bin/arduino-cli) pour utiliser cette fonction.",
        "hw_label": "Câblage monture :",
        "hw_stepstick": "PCB StepStick (pcb/monture)",
        "hw_ext": "PCB drivers externes (pcb/monture_ext)",
        "hw_none": "Sans PCB : câblage manuel",
        "hw_info_stepstick": "Teensy 4.1 sur le PCB StepStick : modules A4988 ou DRV8825 (RESET relié à SLEEP), TMC2208/2209, ou TMC5160 (ponts SPI fermés). Coupez le pont VUSB-VIN du Teensy.",
        "hw_info_ext": "Teensy 4.1 sur le PCB drivers externes : signaux 5 V EN/STEP/DIR vers ENA+/PUL+/DIR+ (DM542, DM556, TB6600…). Pas de bus SPI : les réglages TMC5160 ne servent pas.",
        "hw_info_none": "Câblage manuel d'un Mega 2560 ou d'un Teensy 4.1 : respectez le plan de câblage (bouton à côté du choix). Les broches sont celles du firmware.",
        "wiring_btn": "Plan de câblage",
        "wiring_title": "Plan de câblage de la monture",
        "wiring_col_comp": "Composant",
        "wiring_col_pin": "Broche {board}",
        "wiring_col_sig": "Signal driver / module",
        "wiring_na": "non disponible",
        "wiring_gnd": "Les signaux négatifs (PUL-, DIR-, ENB-) et toutes les masses (drivers, buzzer, GPS, raquette) vont à une broche GND de la carte.",
        "wiring_note_stepstick": "Le PCB StepStick réalise déjà ce câblage. Moteurs : borniers M_AZ, M_ALT, M_DEROT, M_FOCUS (1 = 2B, 2 = 2A, 3 = 1A, 4 = 1B). Raquette : J_RAQUETTE (1 GND, 2 +5V, 3 RX3, 4 TX3). GPS : J_GPS (1 RX4, 2 TX4, 3 +5V, 4 GND). PC : J_PC_SERIAL (1 GND, 2 +5V, 3 TX6, 4 RX6), repères RX/TX côté Teensy. Alimentation : bornier 36 V ou jack 12 V. Ne fermez les 5 ponts SPI d'un axe que pour un TMC5160.",
        "wiring_note_ext": "Le PCB drivers externes réalise déjà ce câblage, avec des sorties 5 V. Par axe : J_VM (1 GND, 2 VM) alimente le driver, J_SIG (1 GND, 2 DIR, 3 STEP, 4 EN) va vers DIR+/PUL+/ENA+, et PUL-/DIR-/ENA- vont au GND. Raquette, GPS et PC : mêmes connecteurs que sur le PCB StepStick. Pas de bus SPI.",
        "wiring_note_none": "Câblez le {board} en suivant ce plan : c'est celui du firmware.",
        "wiring_handpad": "Raquette physique (Teensy 4.1)",
        "wiring_close": "Fermer",
    }
}

# GeolocHandler and standard HTTP server imports removed. Using public IP geolocation API instead.

class ConfigToolApp(tk.Tk):
    def __init__(self):
        super().__init__()
        # State variables
        self.ser = None
        self.is_connected = False
        self.settings = dict(DEFAULTS)
        self.load_local_settings()
        
        lang = self.settings.get("language", "fr")
        t = TRANSLATIONS[lang]
        self.title(t["title"].strip())
        self.geometry("700x1100")
        self.minsize(680, 800)
        self.configure(bg="#c0c0c0") # Classic Windows 95 grey
        self.resizable(False, True)

        # Build UI in Windows 95 Style
        self.build_ui()
        self.build_menu()
        self.update_connection_status()
        self.translate_ui()
        
        # TLE cleanup (older than 24h)
        self.cleanup_old_tle()
        
        # Check for updates in background
        threading.Thread(target=self.check_for_updates, daemon=True).start()

    def cleanup_old_tle(self):
        import time
        from pathlib import Path
        tle_path = Path.home() / ".goto_andrivet" / "iss.tle"
        if tle_path.exists():
            if time.time() - tle_path.stat().st_mtime > 86400:
                try:
                    tle_path.unlink()
                except:
                    pass

    def check_for_updates(self):
        """Vérification en arrière-plan (module mise_a_jour, partagé avec la carte du ciel)."""
        mise_a_jour.register(Path(__file__).resolve().parent)     # entrées du menu des applications
        try:
            available, remote, _ = mise_a_jour.check(Path(__file__).parent)
        except Exception:
            self.after(0, lambda: self.update_btn.config(text="Vérifier les mises à jour", state="normal"))
            return
        if available:
            self.update_available = True
            self.remote_sha = remote
            self.after(0, lambda: self.update_btn.config(
                text="● Mise à jour disponible !",
                bg="#ffcccc", fg="red", font=("MS Sans Serif", 9, "bold"), state="normal"
            ))
        else:
            self.after(0, lambda: self.update_btn.config(text="Vérifier les mises à jour", state="normal"))

    def load_local_settings(self):
        if CONFIG_FILE.exists():
            try:
                self.settings.update(json.loads(CONFIG_FILE.read_text()))
            except Exception:
                pass
        
        # Ensure default park alt matches mount type if they are pure defaults
        if self.settings["mount_type"] in ("ForkEq", "GermanEq") and self.settings["park_alt"] == 0.0 and self.settings["park_az"] == 0.0:
            # If the user saved EQ but park is 0/0 (the new default), migrate it to 90
            self.settings["park_alt"] = 90.0
            # Allemande : contrepoids en bas = axe horaire a 90 deg (AD = TSL - 6 h)
            if self.settings["mount_type"] == "GermanEq":
                self.settings["park_az"] = 90.0

    def save_local_settings(self):
        try:
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            self.settings["astro_mode"] = self.astro_mode_var.get()
            self.settings["astro_api_key"] = self.api_key_entry.get().strip()
            CONFIG_FILE.write_text(json.dumps(self.settings, indent=4))
        except Exception as e:
            print(f"Error saving settings: {e}")

    def build_menu(self):
        menu_bar = tk.Menu(self)
        self.config(menu=menu_bar)
        
        # Menu Mise à jour
        update_menu = tk.Menu(menu_bar, tearoff=0)
        menu_bar.add_cascade(label="Mise à jour", menu=update_menu)
        update_menu.add_command(label="Mettre à jour le logiciel", command=self.update_software)

    def update_software(self):
        import sys
        
        if getattr(sys, 'frozen', False):
            # Le logiciel est compilé (PyInstaller)
            messagebox.showinfo("Mise à jour", "La mise à jour automatique de la version compilée (.exe) arrivera bientôt !\nPour le moment, veuillez télécharger la nouvelle version sur GitHub Releases.")
            import webbrowser
            webbrowser.open("https://github.com/jbandrivet/gotoandrivet/releases")
        else:
            if not getattr(self, 'update_available', False):
                messagebox.showinfo("Mise à jour", "Aucune nouvelle mise à jour n'est disponible.\nVotre logiciel est déjà à la dernière version !")
                return
                
            ans = messagebox.askyesno("Mise à jour", "Une nouvelle version est disponible ! Ceci va la télécharger et redémarrer le configurateur.\nContinuer ?")
            if ans:
                try:
                    mise_a_jour.apply(Path(__file__).parent, getattr(self, 'remote_sha', None))
                except Exception as e:
                    messagebox.showerror("Erreur", f"Impossible de mettre à jour:\n{e}")
                    return
                messagebox.showinfo("Succès", "Mise à jour réussie avec succès ! Le logiciel va maintenant redémarrer.")
                mise_a_jour.restart()

    def build_ui(self):
        # Fonts
        f_title = ("MS Sans Serif", 10, "bold")
        f_label = ("MS Sans Serif", 9)
        f_button = ("MS Sans Serif", 9)
        f_entry = ("Courier New", 9)

        # Canvas and Scrollbar to allow scrolling on smaller screens
        self.main_canvas = tk.Canvas(self, bg="#c0c0c0", highlightthickness=0)
        self.main_scrollbar = tk.Scrollbar(self, orient="vertical", command=self.main_canvas.yview)
        self.main_canvas.configure(yscrollcommand=self.main_scrollbar.set)

        self.main_scrollbar.pack(side="right", fill="y")
        self.main_canvas.pack(side="left", fill="both", expand=True)

        # Main window inner container with a 3D sunken border
        main_border = tk.Frame(self.main_canvas, bg="#c0c0c0", bd=2, relief="raised")
        main_container = tk.Frame(main_border, bg="#c0c0c0")
        main_container.pack(fill="both", expand=True, padx=10, pady=10)
        
        self.canvas_window = self.main_canvas.create_window((0, 0), window=main_border, anchor="nw")

        def on_configure_container(event):
            self.main_canvas.configure(scrollregion=self.main_canvas.bbox("all"))
        
        def on_configure_canvas(event):
            # Make the container frame take the full width of the canvas
            if main_border.winfo_reqwidth() < event.width:
                self.main_canvas.itemconfigure(self.canvas_window, width=event.width)
                
        main_border.bind("<Configure>", on_configure_container)
        self.main_canvas.bind("<Configure>", on_configure_canvas)
        
        # Enable mouse wheel scrolling
        def _on_mousewheel(event):
            self.main_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        self.bind_all("<MouseWheel>", _on_mousewheel)

        # Language selection row
        row_lang = tk.Frame(main_container, bg="#c0c0c0")
        row_lang.pack(fill="x", pady=(0, 5))
        self.lbl_lang = tk.Label(row_lang, text="Language / Langue:", bg="#c0c0c0", fg="black", font=f_label)
        self.lbl_lang.pack(side="left")
        
        self.lang_var = tk.StringVar(value=self.settings.get("language", "fr"))
        self.lang_menu = tk.OptionMenu(row_lang, self.lang_var, "fr", "en", command=self.change_language)
        self.lang_menu.config(bg="#c0c0c0", fg="black", font=f_label, relief="raised", bd=2, activebackground="#d9d9d9", highlightthickness=0)
        self.lang_menu["menu"].config(bg="#c0c0c0", fg="black", font=f_label)
        self.lang_menu.pack(side="left", padx=5)

        self.update_btn = tk.Button(row_lang, text="Vérifier les mises à jour", font=f_button, bg="#c0c0c0", activebackground="#d9d9d9", relief="raised", bd=2, command=self.update_software, state="normal")
        self.update_btn.pack(side="right", padx=10)

        # 2. Connection panel
        self.conn_lf = tk.LabelFrame(main_container, text="Connection Settings", bg="#c0c0c0", fg="black", font=f_title, relief="groove", bd=2)
        self.conn_lf.pack(fill="x", pady=5)

        conn_grid = tk.Frame(self.conn_lf, bg="#c0c0c0")
        conn_grid.pack(padx=10, pady=10, fill="x")

        self.lbl_port = tk.Label(conn_grid, text="Port:", bg="#c0c0c0", fg="black", font=f_label)
        self.lbl_port.grid(row=0, column=0, sticky="e", padx=5)
        
        # Win95 dropdown mimic
        self.port_var = tk.StringVar(value=self.settings["mount_port"])
        self.port_menu = tk.OptionMenu(conn_grid, self.port_var, *self.scan_ports())
        self.port_menu.config(bg="#c0c0c0", fg="black", font=f_label, relief="raised", bd=2, activebackground="#d9d9d9", highlightthickness=0)
        self.port_menu["menu"].config(bg="#c0c0c0", fg="black", font=f_label)
        self.port_menu.grid(row=0, column=1, padx=5, sticky="w")

        self.lbl_baud = tk.Label(conn_grid, text="Baud:", bg="#c0c0c0", fg="black", font=f_label)
        self.lbl_baud.grid(row=0, column=2, sticky="e", padx=5)
        self.baud_var = tk.StringVar(value=str(self.settings["mount_baud"]))
        self.baud_menu = tk.OptionMenu(conn_grid, self.baud_var, "9600", "19200", "38400", "115200")
        self.baud_menu.config(bg="#c0c0c0", fg="black", font=f_label, relief="raised", bd=2, activebackground="#d9d9d9", highlightthickness=0)
        self.baud_menu["menu"].config(bg="#c0c0c0", fg="black", font=f_label)
        self.baud_menu.grid(row=0, column=3, padx=5, sticky="w")

        self.lbl_board = tk.Label(conn_grid, text="Carte:", bg="#c0c0c0", fg="black", font=f_label)
        self.lbl_board.grid(row=0, column=4, sticky="e", padx=5)
        self.board_var = tk.StringVar(value=self.settings.get("board", "Teensy 4.1"))
        self.board_menu = tk.OptionMenu(conn_grid, self.board_var, "Mega 2560", "Teensy 4.1", command=lambda _: (self.apply_hardware_constraints(), self.save_local_settings()))
        self.board_menu.config(bg="#c0c0c0", fg="black", font=f_label, relief="raised", bd=2, activebackground="#d9d9d9", highlightthickness=0)
        self.board_menu["menu"].config(bg="#c0c0c0", fg="black", font=f_label)
        self.board_menu.grid(row=0, column=5, padx=5, sticky="w")

        self.conn_btn = tk.Button(conn_grid, text="Connect", font=f_button, bg="#c0c0c0", activebackground="#d9d9d9", relief="raised", bd=2, command=self.toggle_connection, width=10)
        conn_grid.grid_columnconfigure(6, weight=1)
        self.conn_btn.grid(row=0, column=6, padx=10)

        # Sunken status box
        status_frame = tk.Frame(conn_grid, bg="white", bd=2, relief="sunken", width=120, height=22)
        status_frame.grid(row=0, column=7, padx=5)
        status_frame.pack_propagate(False)
        
        self.status_lbl = tk.Label(status_frame, text="Disconnected", bg="white", fg="red", font=f_label)
        self.status_lbl.pack(fill="both", expand=True)

        # 3. Settings Form
        self.form_lf = tk.LabelFrame(main_container, text="Telescope Mount parameters", bg="#c0c0c0", fg="black", font=f_title, relief="groove", bd=2)
        self.form_lf.pack(fill="both", expand=True, pady=10)

        form_inner = tk.Frame(self.form_lf, bg="#c0c0c0")
        form_inner.pack(fill="both", expand=True, padx=15, pady=10)

        # Configuration Row 0: câblage de la monture (PCB, ou câblage manuel d'après le plan)
        row_hw = tk.Frame(form_inner, bg="#c0c0c0")
        row_hw.pack(fill="x", pady=6)
        self.lbl_hw = tk.Label(row_hw, text="Câblage monture :", width=20, anchor="w", bg="#c0c0c0", fg="black", font=f_label)
        self.lbl_hw.pack(side="left")
        self.hw_code = self.settings.get("hardware", "none")
        if self.hw_code not in HARDWARE_CHOICES:
            self.hw_code = "none"
        self.hw_var = tk.StringVar()
        self.hw_menu = tk.OptionMenu(row_hw, self.hw_var, *HARDWARE_CHOICES)
        self.hw_menu.config(bg="#c0c0c0", fg="black", font=f_label, relief="raised", bd=2, activebackground="#d9d9d9", highlightthickness=0, width=38, anchor="w")
        self.hw_menu["menu"].config(bg="#c0c0c0", fg="black", font=f_label)
        self.hw_menu.pack(side="left", padx=5)
        self.wiring_btn = tk.Button(row_hw, text="Plan de câblage", font=f_button, bg="#c0c0c0", activebackground="#d9d9d9", relief="raised", bd=2, command=self.show_wiring_plan)
        self.wiring_btn.pack(side="left", padx=10)
        self.hw_info_lbl = tk.Label(form_inner, text="", bg="#c0c0c0", fg="#000080", font=f_label, justify="left", anchor="w", wraplength=620)
        self.hw_info_lbl.pack(fill="x", pady=(0, 4))
        self._fill_hw_menu()

        # Configuration Row 1: Type de Monture
        row_type = tk.Frame(form_inner, bg="#c0c0c0")
        row_type.pack(fill="x", pady=6)
        
        self.lbl_mount_type = tk.Label(row_type, text="Mount Type:", width=20, anchor="w", bg="#c0c0c0", fg="black", font=f_label)
        self.lbl_mount_type.pack(side="left")
        self.mount_type_var = tk.StringVar(value=self.settings["mount_type"])
        self.mount_type_menu = tk.OptionMenu(row_type, self.mount_type_var, "AltAz", "ForkEq", "GermanEq", command=self.on_mount_type_changed)
        self.mount_type_menu.config(bg="#c0c0c0", fg="black", font=f_label, relief="raised", bd=2, activebackground="#d9d9d9", highlightthickness=0)
        self.mount_type_menu["menu"].config(bg="#c0c0c0", fg="black", font=f_label)
        self.mount_type_menu.pack(side="left", padx=5)

        # Configuration Row 1b: Pas moteur et Microstepping
        row_motor = tk.Frame(form_inner, bg="#c0c0c0")
        row_motor.pack(fill="x", pady=6)

        self.lbl_motor_steps = tk.Label(row_motor, text="Motor Steps/Rev:", width=20, anchor="w", bg="#c0c0c0", fg="black", font=f_label)
        self.lbl_motor_steps.pack(side="left")
        self.steps_entry = tk.Entry(row_motor, width=12, bd=2, relief="sunken", font=f_entry, bg="white", fg="black")
        self.steps_entry.insert(0, str(self.settings.get("steps_per_rev_motor", 200)))
        self.steps_entry.pack(side="left", padx=5)

        self.lbl_microstepping = tk.Label(row_motor, text="Microstepping:", width=15, anchor="w", bg="#c0c0c0", fg="black", font=f_label)
        self.lbl_microstepping.pack(side="left", padx=(15, 0))
        self.microstep_var = tk.StringVar(value=str(self.settings.get("microstep", 125)))
        from tkinter import ttk
        self.microstep_combo = ttk.Combobox(row_motor, textvariable=self.microstep_var, values=["1", "2", "4", "8", "10", "16", "20", "25", "32", "40", "50", "64", "80", "100", "125", "128", "250", "256"], state="readonly", font=f_entry, width=10)
        self.microstep_combo.pack(side="left", padx=5)

        # Configuration Row 2: Ratios d'engrenage
        row_gear = tk.Frame(form_inner, bg="#c0c0c0")
        row_gear.pack(fill="x", pady=6)

        self.lbl_gear_az = tk.Label(row_gear, text="AZ/RA Gear Ratio:", width=20, anchor="w", bg="#c0c0c0", fg="black", font=f_label)
        self.lbl_gear_az.pack(side="left")
        self.gear_az_entry = tk.Entry(row_gear, width=12, bd=2, relief="sunken", font=f_entry, bg="white", fg="black")
        self.gear_az_entry.insert(0, str(self.settings["gear_ratio_az"]))
        self.gear_az_entry.pack(side="left", padx=5)

        self.lbl_gear_alt = tk.Label(row_gear, text="ALT/DEC Ratio:", width=15, anchor="w", bg="#c0c0c0", fg="black", font=f_label)
        self.lbl_gear_alt.pack(side="left", padx=(15, 0))
        self.gear_alt_entry = tk.Entry(row_gear, width=12, bd=2, relief="sunken", font=f_entry, bg="white", fg="black")
        self.gear_alt_entry.insert(0, str(self.settings["gear_ratio_alt"]))
        self.gear_alt_entry.pack(side="left", padx=5)

        # Configuration Row 2.5: Park Position
        row_park = tk.Frame(form_inner, bg="#c0c0c0")
        row_park.pack(fill="x", pady=6)
        self.lbl_park = tk.Label(row_park, text="Position Parking :", width=20, anchor="w", bg="#c0c0c0", fg="black", font=f_label)
        self.lbl_park.pack(side="left")
        self.lbl_park_alt = tk.Label(row_park, text="Altitude (deg):", width=12, anchor="e", bg="#c0c0c0", fg="black", font=f_label)
        self.lbl_park_alt.pack(side="left")
        self.park_alt_entry = tk.Entry(row_park, width=8, bd=2, relief="sunken", font=f_entry, bg="white", fg="black")
        self.park_alt_entry.insert(0, str(self.settings["park_alt"]))
        self.park_alt_entry.pack(side="left", padx=5)
        self.lbl_park_az = tk.Label(row_park, text="Azimut (deg):", width=12, anchor="e", bg="#c0c0c0", fg="black", font=f_label)
        self.lbl_park_az.pack(side="left", padx=(5, 0))
        self.park_az_entry = tk.Entry(row_park, width=8, bd=2, relief="sunken", font=f_entry, bg="white", fg="black")
        self.park_az_entry.insert(0, str(self.settings["park_az"]))
        self.park_az_entry.pack(side="left", padx=5)

        # Configuration Row 3: Lieu d'observation
        row_loc = tk.Frame(form_inner, bg="#c0c0c0")
        row_loc.pack(fill="x", pady=6)

        self.lbl_latitude = tk.Label(row_loc, text="Site Latitude (N):", width=20, anchor="w", bg="#c0c0c0", fg="black", font=f_label)
        self.lbl_latitude.pack(side="left")
        self.lat_entry = tk.Entry(row_loc, width=12, bd=2, relief="sunken", font=f_entry, bg="white", fg="black")
        self.lat_entry.insert(0, str(self.settings["obs_lat"]))
        self.lat_entry.pack(side="left", padx=5)

        self.lbl_longitude = tk.Label(row_loc, text="Longitude (E):", width=15, anchor="w", bg="#c0c0c0", fg="black", font=f_label)
        self.lbl_longitude.pack(side="left", padx=(15, 0))
        self.lon_entry = tk.Entry(row_loc, width=12, bd=2, relief="sunken", font=f_entry, bg="white", fg="black")
        self.lon_entry.insert(0, str(self.settings["obs_lon"]))
        self.lon_entry.pack(side="left", padx=5)

        # Configuration Row 3.5: Geographic Coordinates Importer
        row_gps = tk.Frame(form_inner, bg="#c0c0c0")
        row_gps.pack(fill="x", pady=6)

        self.lbl_gps = tk.Label(row_gps, text="GPS Coordinates:", width=20, anchor="w", bg="#c0c0c0", fg="black", font=f_label)
        self.lbl_gps.pack(side="left")

        self.gps_btn = tk.Button(row_gps, text="Auto Detect (Internet)", font=f_button, bg="#c0c0c0", activebackground="#d9d9d9", relief="raised", bd=2, command=self.auto_detect_gps)
        self.gps_btn.pack(side="left", padx=5)

        # Configuration Row 4: Vitesse Slew
        row_opt = tk.Frame(form_inner, bg="#c0c0c0")
        row_opt.pack(fill="x", pady=6)

        self.lbl_goto_speed = tk.Label(row_opt, text="GoTo Speed (°/s):", width=20, anchor="w", bg="#c0c0c0", fg="black", font=f_label)
        self.lbl_goto_speed.pack(side="left")
        # Custom Win95 Slider/Scale
        self.speed_scale = tk.Scale(row_opt, from_=0.5, to=25.0, resolution=0.1, orient="horizontal", bg="#c0c0c0", bd=1, relief="flat", highlightthickness=0, troughcolor="#e0e0e0", showvalue=False)
        self.speed_scale.set(self.settings["slew_speed"])
        self.speed_scale.pack(side="left", padx=5, fill="x", expand=True)
        
        self.speed_val_lbl = tk.Label(row_opt, text=f"{self.settings['slew_speed']:.1f} °/s", width=15, bg="#c0c0c0", fg="black", font=f_label)
        self.speed_val_lbl.pack(side="left", padx=5)
        self.speed_scale.configure(command=self.update_speed_lbl)

        self.steps_entry.bind("<KeyRelease>", lambda e: self.update_speed_lbl())
        self.microstep_combo.bind("<<ComboboxSelected>>", lambda e: self.update_speed_lbl())
        self.gear_az_entry.bind("<KeyRelease>", lambda e: self.update_speed_lbl())
        self.after(100, self.update_speed_lbl)

        row_beep = tk.Frame(form_inner, bg="#c0c0c0")
        row_beep.pack(fill="x", pady=8)

        self.lbl_buzzer = tk.Label(row_beep, text="Bip/Buzzer Mount:", width=20, anchor="w", bg="#c0c0c0", fg="black", font=f_label)
        self.lbl_buzzer.pack(side="left")
        self.buzzer_var = tk.BooleanVar(value=self.settings["buzzer_on"])
        self.buzzer_chk = tk.Checkbutton(row_beep, text="Enabled", variable=self.buzzer_var, bg="#c0c0c0", fg="black", selectcolor="#ffffff", activebackground="#c0c0c0", font=f_label)
        self.buzzer_chk.pack(side="left", padx=5)

        self.beep_test_btn = tk.Button(row_beep, text="Test Beep", font=f_button, bg="#c0c0c0", activebackground="#d9d9d9", relief="raised", bd=2, command=self.test_beep, state="disabled")
        self.beep_test_btn.pack(side="left", padx=20)

        # Motor Inversion Row
        row_rev = tk.Frame(form_inner, bg="#c0c0c0")
        row_rev.pack(fill="x", pady=6)

        self.lbl_rev = tk.Label(row_rev, text="Inversion moteurs:", width=20, anchor="w", bg="#c0c0c0", fg="black", font=f_label)
        self.lbl_rev.pack(side="left")
        
        self.rev_az_var = tk.BooleanVar(value=self.settings.get("rev_az", False))
        self.rev_az_chk = tk.Checkbutton(row_rev, text="Inverser AZ/RA", variable=self.rev_az_var, bg="#c0c0c0", fg="black", selectcolor="#ffffff", activebackground="#c0c0c0", font=f_label)
        self.rev_az_chk.pack(side="left", padx=5)

        self.rev_alt_var = tk.BooleanVar(value=self.settings.get("rev_alt", False))
        self.rev_alt_chk = tk.Checkbutton(row_rev, text="Inverser ALT/DEC", variable=self.rev_alt_var, bg="#c0c0c0", fg="black", selectcolor="#ffffff", activebackground="#c0c0c0", font=f_label)
        self.rev_alt_chk.pack(side="left", padx=15)

        # 4. PC Time Synchronization
        self.sync_lf = tk.LabelFrame(main_container, text="Time Synchronization", bg="#c0c0c0", fg="black", font=f_title, relief="groove", bd=2)
        self.sync_lf.pack(fill="x", pady=5)

        sync_inner = tk.Frame(self.sync_lf, bg="#c0c0c0")
        sync_inner.pack(padx=15, pady=10, fill="x")

        sync_btn_frame = tk.Frame(sync_inner, bg="#c0c0c0")
        sync_btn_frame.pack(side="left")

        self.sync_btn = tk.Button(sync_btn_frame, text="Synchronize Arduino with PC clock", font=f_button, bg="#c0c0c0", activebackground="#d9d9d9", relief="raised", bd=2, command=self.sync_time_date, state="disabled", width=35)
        self.sync_btn.pack(pady=2)

        self.sync_pc_btn = tk.Button(sync_btn_frame, text="Sync PC from Arduino (GPS)", font=f_button, bg="#c0c0c0", activebackground="#d9d9d9", relief="raised", bd=2, command=self.sync_pc_from_arduino, state="disabled", width=35)
        self.sync_pc_btn.pack(pady=2)

        self.tle_btn = tk.Button(sync_btn_frame, text="Télécharger TLE ISS (Valable 24h)", font=f_button, bg="#c0c0c0", activebackground="#d9d9d9", relief="raised", bd=2, command=self.download_iss_tle, width=35)
        self.tle_btn.pack(pady=2)

        # Sunken label for sync time
        sync_box = tk.Frame(sync_inner, bg="white", bd=2, relief="sunken", width=180, height=22)
        sync_box.pack(side="left", padx=15)
        sync_box.pack_propagate(False)

        self.time_lbl = tk.Label(sync_box, text="PC clock not synced", bg="white", fg="black", font=f_label)
        self.time_lbl.pack(fill="both", expand=True)

        # 4.5 Mount Control Buttons (Park / Unpark)
        self.mount_ctrl_lf = tk.LabelFrame(main_container, text="Mount Control", bg="#c0c0c0", fg="black", font=f_title, relief="groove", bd=2)
        self.mount_ctrl_lf.pack(fill="x", pady=5)
        
        mount_ctrl_inner = tk.Frame(self.mount_ctrl_lf, bg="#c0c0c0")

        # Configuration Row - Derotator and Focus Mega
        row_extra = tk.Frame(form_inner, bg="#c0c0c0")
        row_extra.pack(fill="x", pady=6)
        
        self.derot_mega_var = tk.BooleanVar(value=self.settings.get("derot_mega_en", False))
        self.chk_derot_mega = tk.Checkbutton(row_extra, text="Dérotateur (Mega) [AltAz uniquement]", variable=self.derot_mega_var, bg="#c0c0c0", fg="black", font=f_label, selectcolor="white")
        self.chk_derot_mega.pack(side="left")
        
        self.derot_zwo_var = tk.BooleanVar(value=self.settings.get("derot_zwo_en", False))
        self.chk_derot_zwo = tk.Checkbutton(row_extra, text="Dérotateur ZWO CAA (USB)", variable=self.derot_zwo_var, bg="#c0c0c0", fg="black", font=f_label, selectcolor="white")
        self.chk_derot_zwo.pack(side="left", padx=(10,0))
        
        self.lbl_derot_ppd = tk.Label(row_extra, text="Pas/Deg (Mega):", bg="#c0c0c0", fg="black", font=f_label)
        self.lbl_derot_ppd.pack(side="left", padx=(10,5))
        self.derot_ppd_entry = tk.Entry(row_extra, font=f_entry, bg="white", fg="black", width=6, bd=2, relief="sunken")
        self.derot_ppd_entry.pack(side="left")
        self.derot_ppd_entry.insert(0, str(self.settings.get("derot_mega_ppd", 100.0)))
        
        row_extra2 = tk.Frame(form_inner, bg="#c0c0c0")
        row_extra2.pack(fill="x", pady=6)
        
        self.focus_mega_var = tk.BooleanVar(value=self.settings.get("focus_mega_en", False))
        self.focus_eaf_var = tk.BooleanVar(value=self.settings.get("focus_eaf_en", False))
        
        def toggle_mega():
            if self.focus_mega_var.get():
                self.focus_eaf_var.set(False)
                
        def toggle_eaf():
            if self.focus_eaf_var.get():
                self.focus_mega_var.set(False)
                
        self.chk_focus_mega = tk.Checkbutton(row_extra2, text="Focuseur (Mega)", variable=self.focus_mega_var, bg="#c0c0c0", fg="black", font=f_label, selectcolor="white", command=toggle_mega)
        self.chk_focus_mega.pack(side="left")
        
        self.chk_focus_eaf = tk.Checkbutton(row_extra2, text="Focuseur (ZWO EAF)", variable=self.focus_eaf_var, bg="#c0c0c0", fg="black", font=f_label, selectcolor="white", command=toggle_eaf)
        self.chk_focus_eaf.pack(side="left", padx=(20,0))

        # Drivers TMC5160 en SPI (Teensy) : ponts SPI fermes sous les supports StepStick
        row_tmc1 = tk.Frame(form_inner, bg="#c0c0c0")
        row_tmc1.pack(fill="x", pady=(10, 3))
        self.tmc_spi_var = tk.BooleanVar(value=self.settings.get("tmc_spi", True))
        tk.Checkbutton(row_tmc1, text="Drivers TMC5160 (SPI, Teensy)", variable=self.tmc_spi_var, bg="#c0c0c0", fg="black", font=f_label, selectcolor="white").pack(side="left")
        self.tmc_stealth_var = tk.BooleanVar(value=self.settings.get("tmc_stealth", True))
        tk.Checkbutton(row_tmc1, text="stealthChop", variable=self.tmc_stealth_var, bg="#c0c0c0", fg="black", font=f_label, selectcolor="white").pack(side="left", padx=(15, 0))
        tk.Label(row_tmc1, text="Maintien (%):", bg="#c0c0c0", fg="black", font=f_label).pack(side="left", padx=(15, 5))
        self.tmc_hold_entry = tk.Entry(row_tmc1, width=4, bd=2, relief="sunken", font=f_entry, bg="white", fg="black")
        self.tmc_hold_entry.insert(0, str(self.settings.get("tmc_hold", 50)))
        self.tmc_hold_entry.pack(side="left")

        row_tmc2 = tk.Frame(form_inner, bg="#c0c0c0")
        row_tmc2.pack(fill="x", pady=3)
        tk.Label(row_tmc2, text="Courant (mA RMS):", width=20, anchor="w", bg="#c0c0c0", fg="black", font=f_label).pack(side="left")
        self.tmc_current_entries = []
        currents = self.settings.get("tmc_current", [800, 800, 400, 400])
        for name, val in zip(("AZ", "ALT", "DER", "FOC"), currents):
            tk.Label(row_tmc2, text=name, bg="#c0c0c0", fg="black", font=f_label).pack(side="left", padx=(8, 2))
            e = tk.Entry(row_tmc2, width=5, bd=2, relief="sunken", font=f_entry, bg="white", fg="black")
            e.insert(0, str(val))
            e.pack(side="left")
            self.tmc_current_entries.append(e)

        row_tmc3 = tk.Frame(form_inner, bg="#c0c0c0")
        row_tmc3.pack(fill="x", pady=3)
        tk.Label(row_tmc3, text="µpas DER / FOC:", width=20, anchor="w", bg="#c0c0c0", fg="black", font=f_label).pack(side="left")
        ms_values = ["1", "2", "4", "8", "16", "32", "64", "128", "256"]
        self.tmc_ms_derot_var = tk.StringVar(value=str(self.settings.get("tmc_ms_derot", 16)))
        ttk.Combobox(row_tmc3, textvariable=self.tmc_ms_derot_var, values=ms_values, state="readonly", font=f_entry, width=5).pack(side="left", padx=5)
        self.tmc_ms_focus_var = tk.StringVar(value=str(self.settings.get("tmc_ms_focus", 16)))
        ttk.Combobox(row_tmc3, textvariable=self.tmc_ms_focus_var, values=ms_values, state="readonly", font=f_entry, width=5).pack(side="left", padx=5)
        self.tmc_status_lbl = tk.Label(row_tmc3, text="État : —", bg="#c0c0c0", fg="black", font=f_label, anchor="w")
        self.tmc_status_lbl.pack(side="left", padx=(15, 0))
        self.tmc_rows = (row_tmc1, row_tmc2, row_tmc3)
        self.apply_hardware_constraints()

        mount_ctrl_inner.pack(padx=15, pady=10, fill="x")
        
        self.park_btn = tk.Button(mount_ctrl_inner, text="Park Mount ⏾", font=f_button, bg="#c0c0c0", activebackground="#d9d9d9", relief="raised", bd=2, command=self.park_mount, state="disabled", width=18)
        self.park_btn.pack(side="left", padx=5, fill="x", expand=True)
        
        self.unpark_btn = tk.Button(mount_ctrl_inner, text="Unpark Mount ☉", font=f_button, bg="#c0c0c0", activebackground="#d9d9d9", relief="raised", bd=2, command=self.unpark_mount, state="disabled", width=18)
        self.unpark_btn.pack(side="left", padx=5, fill="x", expand=True)

        # 4.7 Flash Firmware Panel
        self.flash_lf = tk.LabelFrame(main_container, text="Firmware Flashing (arduino-cli)", bg="#c0c0c0", fg="black", font=f_title, relief="groove", bd=2)
        self.flash_lf.pack(fill="x", pady=5)
        
        flash_inner = tk.Frame(self.flash_lf, bg="#c0c0c0")
        flash_inner.pack(padx=15, pady=10, fill="x")
        self.flash_btn = tk.Button(flash_inner, text="Mettre à jour et flasher le Firmware", font=f_button, bg="#c0c0c0", activebackground="#d9d9d9", relief="raised", bd=2, command=self.open_flash_dialog, width=40)
        self.flash_btn.pack(side="top", pady=5)
        # 4.8 Astrometry Panel
        self.astro_lf = tk.LabelFrame(main_container, text="Astrométrie ZWO (Centrage)", bg="#c0c0c0", fg="black", font=f_title, relief="groove", bd=2)
        self.astro_lf.pack(fill="x", pady=5)
        
        self.astro_en_var = tk.BooleanVar(value=self.settings.get("astrometry_enabled", False))
        self.astro_chk = tk.Checkbutton(self.astro_lf, text="Activer la fonctionnalité d'Astrométrie ZWO", variable=self.astro_en_var, bg="#c0c0c0", fg="black", font=f_label, selectcolor="white", command=self.toggle_astrometry_ui)
        self.astro_chk.pack(anchor="w", padx=10, pady=5)
        
        # Ajout du bouton de téléchargement des index
        self.astro_dl_btn = tk.Button(self.astro_lf, text="Télécharger les Index Astrométrie", font=f_button, bg="#c0c0c0", command=self.prompt_download_indexes)
        self.astro_dl_btn.pack(anchor="w", padx=10, pady=(0, 5))
        
        self.astro_inner = tk.Frame(self.astro_lf, bg="#c0c0c0")
        
        # Mode de résolution
        self.astro_mode_frame = tk.Frame(self.astro_inner, bg="#c0c0c0")
        self.astro_mode_frame.pack(fill="x", pady=2)
        
        self.lbl_astro_mode = tk.Label(self.astro_mode_frame, text="Moteur:", bg="#c0c0c0", fg="black", font=f_label)
        self.lbl_astro_mode.pack(side="left")
        
        self.astro_mode_var = tk.StringVar(value=self.settings.get("astro_mode", "local"))
        self.rb_astro_local = tk.Radiobutton(self.astro_mode_frame, text="Local (rapide)", variable=self.astro_mode_var, value="local", bg="#c0c0c0", fg="black", font=f_label, selectcolor="white", command=self.toggle_astro_api)
        self.rb_astro_local.pack(side="left", padx=5)
        self.rb_astro_api = tk.Radiobutton(self.astro_mode_frame, text="En ligne (API Astrometry.net)", variable=self.astro_mode_var, value="api", bg="#c0c0c0", fg="black", font=f_label, selectcolor="white", command=self.toggle_astro_api)
        self.rb_astro_api.pack(side="left")
        
        self.api_key_frame = tk.Frame(self.astro_inner, bg="#c0c0c0")
        self.api_key_frame.pack(fill="x", pady=2)
        self.lbl_api_key = tk.Label(self.api_key_frame, text="Clé API:", bg="#c0c0c0", fg="black", font=f_label)
        self.lbl_api_key.pack(side="left")
        self.api_key_entry = tk.Entry(self.api_key_frame, width=25, font=f_entry, bg="white", fg="black", bd=2, relief="sunken")
        self.api_key_entry.insert(0, self.settings.get("astro_api_key", ""))
        self.api_key_entry.pack(side="left", padx=5)
        self.toggle_astro_api()
        
        # row 1: exposure, gain, camera index
        self.astro_row1 = tk.Frame(self.astro_inner, bg="#c0c0c0")
        self.astro_row1.pack(fill="x", pady=2)
        
        self.lbl_cam = tk.Label(self.astro_row1, text="Caméra:", bg="#c0c0c0", fg="black", font=f_label)
        self.lbl_cam.pack(side="left")
        
        self.cam_combo = ttk.Combobox(self.astro_row1, width=15, state="readonly", font=f_entry)
        saved_idx = self.settings.get("astro_cam_idx", 0)
        self.cam_combo.set(f"Cam {saved_idx}")
        self.cam_combo.pack(side="left", padx=(5,0))
        
        self.detect_cam_btn = tk.Button(self.astro_row1, text="🔄", font=("MS Sans Serif", 8), command=self.detect_zwo_cameras, bg="#c0c0c0")
        self.detect_cam_btn.pack(side="left", padx=(0,5))

        self.lbl_exp = tk.Label(self.astro_row1, text="Exp (s):", bg="#c0c0c0", fg="black", font=f_label)
        self.lbl_exp.pack(side="left", padx=(10,0))
        self.exp_entry = tk.Entry(self.astro_row1, width=5, font=f_entry, bg="white", fg="black", bd=2, relief="sunken")
        self.exp_entry.insert(0, str(self.settings.get("astro_exp", 2.0)))
        self.exp_entry.pack(side="left", padx=5)

        self.lbl_gain = tk.Label(self.astro_row1, text="Gain:", bg="#c0c0c0", fg="black", font=f_label)
        self.lbl_gain.pack(side="left", padx=(10,0))
        self.gain_entry = tk.Entry(self.astro_row1, width=4, font=f_entry, bg="white", fg="black", bd=2, relief="sunken")
        self.gain_entry.insert(0, str(self.settings.get("astro_gain", 150)))
        self.gain_entry.pack(side="left", padx=5)
        
        self.auto_gain_var = tk.BooleanVar(value=self.settings.get("astro_auto_gain", True))
        self.auto_gain_chk = tk.Checkbutton(self.astro_row1, text="Auto", variable=self.auto_gain_var, bg="#c0c0c0", fg="black", font=f_label, selectcolor="white", command=self.toggle_auto_gain)
        self.auto_gain_chk.pack(side="left")
        
        # row 2: Focal length and Blind Solving
        self.astro_row2 = tk.Frame(self.astro_inner, bg="#c0c0c0")
        self.astro_row2.pack(fill="x", pady=2)
        
        self.lbl_foc = tk.Label(self.astro_row2, text="Focale (mm):", bg="#c0c0c0", fg="black", font=f_label)
        self.lbl_foc.pack(side="left")
        self.foc_entry = tk.Entry(self.astro_row2, width=6, font=f_entry, bg="white", fg="black", bd=2, relief="sunken")
        foc_val = self.settings.get("astro_focal", "")
        self.foc_entry.insert(0, str(foc_val) if foc_val else "")
        self.foc_entry.pack(side="left", padx=5)
        
        self.lbl_px = tk.Label(self.astro_row2, text="Pixel (µm):", bg="#c0c0c0", fg="black", font=f_label)
        self.lbl_px.pack(side="left")
        self.px_entry = tk.Entry(self.astro_row2, width=5, font=f_entry, bg="white", fg="black", bd=2, relief="sunken")
        px_val = self.settings.get("astro_pixel", "3.76")
        self.px_entry.insert(0, str(px_val) if px_val else "3.76")
        self.px_entry.pack(side="left", padx=5)

        self.lbl_width = tk.Label(self.astro_row2, text="Largeur (px):", bg="#c0c0c0", fg="black", font=f_label)
        self.lbl_width.pack(side="left")
        self.width_entry = tk.Entry(self.astro_row2, width=6, font=f_entry, bg="white", fg="black", bd=2, relief="sunken")
        width_val = self.settings.get("astro_width", "1280")
        self.width_entry.insert(0, str(width_val) if width_val else "1280")
        self.width_entry.pack(side="left", padx=5)

        self.blind_var = tk.BooleanVar(value=self.settings.get("astro_blind", False))
        self.blind_chk = tk.Checkbutton(self.astro_row2, text="Blind Solving", variable=self.blind_var, bg="#c0c0c0", fg="black", font=f_label, selectcolor="white", command=self.toggle_blind_solving)
        self.blind_chk.pack(side="left", padx=(10,0))
        
        self.astro_btns_frame = tk.Frame(self.astro_inner, bg="#c0c0c0")
        self.astro_btns_frame.pack(pady=(5,0), fill="x", expand=True)
        
        self.capture_btn = tk.Button(self.astro_btns_frame, text="1. Capturer (Aperçu)", font=f_button, bg="#c0c0c0", activebackground="#d9d9d9", relief="raised", bd=2, command=self.run_capture_only)
        self.capture_btn.pack(side="left", fill="x", expand=True, padx=(0, 2))
        
        self.solve_btn = tk.Button(self.astro_btns_frame, text="2. Résoudre & Sync", font=f_button, bg="#c0c0c0", activebackground="#d9d9d9", relief="raised", bd=2, command=self.run_solve_only, state="disabled")
        self.solve_btn.pack(side="left", fill="x", expand=True, padx=(2, 2))
        
        self.preview_foc_btn = tk.Button(self.astro_btns_frame, text="3. Mode Preview (Focus)", font=f_button, bg="#c0c0c0", activebackground="#d9d9d9", relief="raised", bd=2, command=self.open_preview_focuser)
        self.preview_foc_btn.pack(side="left", fill="x", expand=True, padx=(2, 2))
        
        self.pa_btn = tk.Button(self.astro_btns_frame, text="4. Mise en Station (PA)", font=f_button, bg="#c0c0c0", activebackground="#d9d9d9", relief="raised", bd=2, command=self.open_polar_alignment)
        self.pa_btn.pack(side="left", fill="x", expand=True, padx=(2, 0))

        self.astro_progress = ttk.Progressbar(self.astro_inner, orient="horizontal", mode="determinate")
        self.astro_progress.pack(fill="x", pady=(5,0), padx=5)

        self.toggle_blind_solving()
        self.toggle_auto_gain()
        self.toggle_astrometry_ui()

        # 5. Buttons Actions Panel
        actions_container = tk.Frame(main_container, bg="#c0c0c0")
        actions_container.pack(fill="x", side="bottom", pady=10)

        f_big_button = ("MS Sans Serif", 10, "bold")

        row1 = tk.Frame(actions_container, bg="#c0c0c0")
        row1.pack(fill="x", pady=2)
        row2 = tk.Frame(actions_container, bg="#c0c0c0")
        row2.pack(fill="x", pady=2)

        self.apply_btn = tk.Button(row1, text="Apply & Save to Arduino", font=f_big_button, bg="#c0c0c0", activebackground="#d9d9d9", relief="raised", bd=3, command=self.apply_config_to_arduino, state="disabled")
        self.apply_btn.pack(side="left", padx=5, ipady=8, fill="x", expand=True)

        self.launch_pad_btn = tk.Button(row1, text="Virtual Handpad", font=f_big_button, bg="#c0c0c0", activebackground="#d9d9d9", relief="raised", bd=3, command=self.launch_virtual_handpad)
        self.launch_pad_btn.pack(side="left", padx=5, ipady=8, fill="x", expand=True)

        self.auto_model_btn = tk.Button(row2, text="Modèle Auto ZWO", font=f_big_button, bg="#c0c0c0", activebackground="#d9d9d9", relief="raised", bd=3, command=self.open_auto_model)
        self.auto_model_btn.pack(side="left", padx=5, ipady=8, fill="x", expand=True)

        self.spectro_btn = tk.Button(row2, text="Autoguidage ZWO", font=f_big_button, bg="#c0c0c0", activebackground="#d9d9d9", relief="raised", bd=3, command=self.open_spectro_autoguide)
        self.spectro_btn.pack(side="left", padx=5, ipady=8, fill="x", expand=True)

        # Signature
        author_lbl = tk.Label(main_container, text="Créé par Andrivet Jean-Baptiste", font=("Helvetica", 8, "italic"), bg="#e0e0e0", fg="#555555")
        author_lbl.pack(side="bottom", anchor="se", pady=(5, 0), padx=5)

    def on_mount_type_changed(self, new_type):
        t = TRANSLATIONS[self.lang_var.get()]
        if new_type == "AltAz":
            self.lbl_park_alt.config(text=t["park_alt"])
            self.lbl_park_az.config(text=t["park_az"])
        else:
            self.lbl_park_alt.config(text=t["park_dec"])
            self.lbl_park_az.config(text=t["park_ra"])
        
        # Position de parking par defaut de chaque type (comme le firmware) :
        # AltAz horizon nord, fourche tube au pole (AH 0), allemande contrepoids
        # en bas (axe horaire a 90 deg). Elle ne suit le nouveau type que si
        # elle etait restee au defaut d'un type.
        defaults = {"AltAz": (0.0, 0.0), "ForkEq": (90.0, 0.0), "GermanEq": (90.0, 90.0)}
        try:
            current = (float(self.park_alt_entry.get()), float(self.park_az_entry.get()))
            if new_type in defaults and current in defaults.values():
                p_alt, p_az = defaults[new_type]
                self.park_alt_entry.delete(0, tk.END)
                self.park_alt_entry.insert(0, str(p_alt))
                self.park_az_entry.delete(0, tk.END)
                self.park_az_entry.insert(0, str(p_az))
        except ValueError:
            pass

    def launch_virtual_handpad(self):
        try:
            import subprocess
            import sys
            import os
            from pathlib import Path
            script_path = Path(__file__).parent / "raquette_virtuelle.py"
            if not script_path.exists():
                script_path = Path.home() / ".goto_andrivet" / "raquette_virtuelle.py"
            venv_python = str(Path.home() / ".goto_andrivet" / "venv" / "bin" / "python3")
            py_exe = venv_python if os.path.exists(venv_python) else sys.executable
            subprocess.Popen([py_exe, str(script_path)])
        except Exception as e:
            messagebox.showerror("Error", f"Failed to launch Virtual Handpad:\n{e}")

    def open_auto_model(self):
        try:
            import subprocess
            import sys
            import os
            from pathlib import Path
            script_path = Path(__file__).parent / "auto_model_zwo.py"
            venv_python = str(Path.home() / ".goto_andrivet" / "venv" / "bin" / "python3")
            py_exe = venv_python if os.path.exists(venv_python) else sys.executable
            subprocess.Popen([py_exe, str(script_path)])
        except Exception as e:
            messagebox.showerror("Error", f"Failed to launch Auto-Model:\n{e}")

    def open_spectro_autoguide(self):
        try:
            import subprocess
            import sys
            import os
            from pathlib import Path
            script_path = Path(__file__).parent / "autoguide_spectro_zwo.py"
            venv_python = str(Path.home() / ".goto_andrivet" / "venv" / "bin" / "python3")
            py_exe = venv_python if os.path.exists(venv_python) else sys.executable
            subprocess.Popen([py_exe, str(script_path)])
        except Exception as e:
            messagebox.showerror("Error", f"Failed to launch Spectro Autoguide:\n{e}")

    def change_language(self, new_lang):
        self.settings["language"] = new_lang
        self.save_local_settings()
        self.translate_ui()

    def translate_ui(self):
        lang = self.settings.get("language", "fr")
        t = TRANSLATIONS[lang]
        
        self.title(t["title"].strip())
        self.conn_lf.config(text=t["conn_lf"])
        self.lbl_port.config(text=t["port"])
        self.lbl_baud.config(text=t["baud"])
        self.lbl_lang.config(text=t["lang_label"])
        
        if self.is_connected:
            self.conn_btn.config(text=t["disconnect"])
            self.status_lbl.config(text=t["connected"], fg="green")
        else:
            self.conn_btn.config(text=t["connect"])
            self.status_lbl.config(text=t["disconnected"], fg="red")
            
        self.form_lf.config(text=t["mount_params"])
        self.lbl_mount_type.config(text=t["mount_type"])
        self.lbl_motor_steps.config(text=t["motor_steps"])
        self.lbl_microstepping.config(text=t["microstepping"])
        self.lbl_gear_az.config(text=t["gear_ratio_az"])
        self.lbl_gear_alt.config(text=t["gear_ratio_alt"])
        self.lbl_latitude.config(text=t["latitude"])
        self.lbl_longitude.config(text=t["longitude"])
        self.lbl_park.config(text=t["park_pos"])
        
        mtype = self.mount_type_var.get()
        if mtype == "AltAz":
            self.lbl_park_alt.config(text=t["park_alt"])
            self.lbl_park_az.config(text=t["park_az"])
        else:
            self.lbl_park_alt.config(text=t["park_dec"])
            self.lbl_park_az.config(text=t["park_ra"])
            
        self.lbl_gps.config(text=t["gps_coords"])
        self.gps_btn.config(text=t["auto_detect"])
        self.lbl_goto_speed.config(text=t["goto_speed"])
        self.lbl_buzzer.config(text=t["buzzer"])
        self.buzzer_chk.config(text=t["enabled"])
        self.beep_test_btn.config(text=t["test_beep"])
        self.lbl_rev.config(text=t["motor_inversion"])
        self.rev_az_chk.config(text=t["rev_az"])
        self.rev_alt_chk.config(text=t["rev_alt"])
        self.sync_lf.config(text=t["time_sync"])
        self.sync_btn.config(text=t["sync_clock"])
        self.sync_pc_btn.config(text=t["sync_pc_clock"])
        
        if self.time_lbl.cget("text") in ("PC clock not synced", "Horloge PC non synchronisée"):
            self.time_lbl.config(text=t["clock_not_synced"])
        elif self.time_lbl.cget("text").startswith("PC clock synced") or self.time_lbl.cget("text").startswith("Horloge PC synchronisée") or self.time_lbl.cget("text").startswith("Synced") or self.time_lbl.cget("text").startswith("Synchro"):
            current = self.time_lbl.cget("text")
            time_part = current.split(":")[-3:]
            time_part_str = ":".join(time_part)
            prefix = "Synced: " if lang == "en" else "Synchro : "
            self.time_lbl.config(text=prefix + time_part_str)
            
        self.apply_btn.config(text=t["apply_config"])
        self.apply_btn.config(text=t["apply_config"])
        self.launch_pad_btn.config(text=t["virtual_pad"])
        self.mount_ctrl_lf.config(text=t["mount_control"])
        self.park_btn.config(text=t["park_mount"])
        self.unpark_btn.config(text=t["unpark_mount"])
        
        self.flash_lf.config(text=t["flash_lf"])
        self.lbl_hw.config(text=t["hw_label"])
        self.wiring_btn.config(text=t["wiring_btn"])
        self._fill_hw_menu()
        self.apply_hardware_constraints()
        # (Les textes internes sont gérés autrement)

    def _fill_hw_menu(self):
        """Libellés du choix de câblage dans la langue courante."""
        t = TRANSLATIONS[self.settings.get("language", "fr")]
        menu = self.hw_menu["menu"]
        menu.delete(0, "end")
        for code in HARDWARE_CHOICES:
            menu.add_command(label=t["hw_" + code], command=lambda c=code: self.set_hardware(c))
        self.hw_var.set(t["hw_" + self.hw_code])

    def set_hardware(self, code):
        self.hw_code = code
        self.settings["hardware"] = code
        self.apply_hardware_constraints()
        self.save_local_settings()

    def apply_hardware_constraints(self):
        """Ce que le câblage choisi impose : la carte, le bus SPI des TMC5160, l'aide affichée."""
        t = TRANSLATIONS[self.settings.get("language", "fr")]
        code = self.hw_code
        self.hw_var.set(t["hw_" + code])
        if code == "none":
            self.board_menu.config(state="normal")
        else:
            self.board_var.set("Teensy 4.1")       # les deux PCB monture portent un Teensy 4.1
            self.board_menu.config(state="disabled")
        if code == "ext":
            self.tmc_spi_var.set(False)            # pas de bus SPI : Appliquer envoie :XFS0
        spi_possible = code == "stepstick" or (code == "none" and self.board_var.get() == "Teensy 4.1")
        for row in self.tmc_rows:
            for w in row.winfo_children():
                if isinstance(w, ttk.Combobox):
                    w.config(state="readonly" if spi_possible else "disabled")
                elif w is not self.tmc_status_lbl:
                    w.config(state="normal" if spi_possible else "disabled")
        self.hw_info_lbl.config(text=t["hw_info_" + code])
        self.settings["board"] = self.board_var.get()
        self.update_speed_lbl()

    def show_wiring_plan(self):
        """Plan de câblage de la monture pour la carte choisie, et notes du PCB choisi."""
        lang = self.settings.get("language", "fr")
        t = TRANSLATIONS[lang]
        board = self.board_var.get()
        mega = board == "Mega 2560"
        top = tk.Toplevel(self)
        top.title(t["wiring_title"])
        top.configure(bg="#c0c0c0")
        top.geometry("780x760")
        note = t["wiring_note_" + self.hw_code].format(board=board)
        tk.Label(top, text=f"{t['hw_' + self.hw_code]} — {board}", bg="#c0c0c0", fg="black", font=("MS Sans Serif", 10, "bold")).pack(anchor="w", padx=12, pady=(10, 2))
        tk.Label(top, text=note, bg="#c0c0c0", fg="#000080", font=("MS Sans Serif", 9), justify="left", wraplength=740).pack(anchor="w", padx=12, pady=(0, 8))

        def table(parent, columns, rows, height):
            tv = ttk.Treeview(parent, columns=columns, show="headings", height=height)
            for c, w in zip(columns, (210, 150, 380)):
                tv.heading(c, text=c, anchor="w")
                tv.column(c, width=w, anchor="w")
            tv.tag_configure("na", foreground="#808080")
            for vals, tag in rows:
                tv.insert("", "end", values=vals, tags=(tag,) if tag else ())
            tv.pack(fill="x", padx=12)
            return tv

        cols = (t["wiring_col_comp"], t["wiring_col_pin"].format(board=board), t["wiring_col_sig"])
        rows = []
        for comp_fr, comp_en, pin_mega, pin_teensy, sig_fr, sig_en in WIRING_PLAN:
            pin = pin_mega if mega else pin_teensy
            comp = comp_fr if lang == "fr" else comp_en
            sig = sig_fr if lang == "fr" else sig_en
            rows.append(((comp, pin, sig), None) if pin else ((comp, "—", t["wiring_na"]), "na"))
        table(top, cols, rows, len(rows))
        tk.Label(top, text=t["wiring_gnd"], bg="#c0c0c0", fg="black", font=("MS Sans Serif", 9), justify="left", wraplength=740).pack(anchor="w", padx=12, pady=(6, 10))

        tk.Label(top, text=t["wiring_handpad"], bg="#c0c0c0", fg="black", font=("MS Sans Serif", 10, "bold")).pack(anchor="w", padx=12, pady=(4, 4))
        hrows = [((comp_fr if lang == "fr" else comp_en, pin, con_fr if lang == "fr" else con_en), None)
                 for comp_fr, comp_en, pin, con_fr, con_en in WIRING_HANDPAD]
        table(top, (t["wiring_col_comp"], t["wiring_col_pin"].format(board="Teensy 4.1"), t["wiring_col_sig"]), hrows, len(hrows))
        tk.Button(top, text=t["wiring_close"], font=("MS Sans Serif", 9), bg="#c0c0c0", relief="raised", bd=2, command=top.destroy, width=12).pack(pady=12)
        return top

    def auto_detect_gps(self):
        self.gps_btn.config(state="disabled")
        self.update()
        import urllib.request
        import json
        
        lat, lon = None, None
        # Try 1: ip-api.com
        try:
            req = urllib.request.Request("http://ip-api.com/json/", headers={"User-Agent": "GotoMega/1.0"})
            with urllib.request.urlopen(req, timeout=3.0) as response:
                data = json.loads(response.read().decode())
                if data.get("status") == "success":
                    lat = float(data["lat"])
                    lon = float(data["lon"])
        except Exception:
            pass

        # Try 2 (fallback): ipapi.co
        if lat is None or lon is None:
            try:
                req = urllib.request.Request("https://ipapi.co/json/", headers={"User-Agent": "GotoMega/1.0"})
                with urllib.request.urlopen(req, timeout=3.0) as response:
                    data = json.loads(response.read().decode())
                    if "latitude" in data and "longitude" in data:
                        lat = float(data["latitude"])
                        lon = float(data["longitude"])
            except Exception:
                pass

        if lat is not None and lon is not None:
            self.lat_entry.delete(0, tk.END)
            self.lat_entry.insert(0, f"{lat:.4f}")
            self.lon_entry.delete(0, tk.END)
            self.lon_entry.insert(0, f"{lon:.4f}")
            self.settings["obs_lat"] = lat
            self.settings["obs_lon"] = lon
            self.save_local_settings()
            messagebox.showinfo("GPS Import", f"Position detected automatically!\n\nLat: {lat:.4f}\nLon: {lon:.4f}")
        else:
            messagebox.showerror("Connection Error", "Could not detect location automatically from Internet. Please check your connection.")
        
        self.gps_btn.config(state="normal")

    def scan_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        return ports if ports else ["/dev/ttyACM0", "/dev/ttyUSB0"]

    def update_speed_lbl(self, val=None):
        if hasattr(self, 'board_var') and hasattr(self, 'chk_focus_mega'):
            bname = "Teensy" if self.board_var.get() == "Teensy 4.1" else "Mega"
            self.chk_focus_mega.config(text=f"Focuseur ({bname})")
            if hasattr(self, 'chk_derot_mega'):
                self.chk_derot_mega.config(text=f"Dérotateur ({bname}) [AltAz uniquement]")
        try:
            az_ratio = float(self.gear_az_entry.get())
            motor_steps = int(self.steps_entry.get())
            microstep = int(self.microstep_var.get())
            az_ppd = (motor_steps * microstep * az_ratio) / 360.0
            
            if az_ppd > 0:
                min_delay = 5.0 if (hasattr(self, 'board_var') and self.board_var.get() == "Teensy 4.1") else 35.0
                max_hw_speed = 1.0e6 / (az_ppd * min_delay)
                limit = min(25.0, max_hw_speed)
                
                # Format to 1 decimal place to match slider resolution
                limit = float(f"{limit:.1f}")
                
                self.speed_scale.config(to=limit)
                
                if self.speed_scale.get() > limit:
                    self.speed_scale.set(limit)
                    val = limit
                    
                if max_hw_speed < 25.0:
                    self.speed_val_lbl.config(fg="red", text=f"{float(val if val else self.speed_scale.get()):.1f} °/s (HW Max)")
                else:
                    self.speed_val_lbl.config(fg="black", text=f"{float(val if val else self.speed_scale.get()):.1f} °/s")
            else:
                self.speed_val_lbl.config(text=f"{float(val if val else self.speed_scale.get()):.1f} °/s")
        except ValueError:
            if val is not None:
                self.speed_val_lbl.config(text=f"{float(val):.1f} °/s")

    def toggle_blind_solving(self):
        if self.blind_var.get():
            self.foc_entry.config(state="disabled")
        else:
            self.foc_entry.config(state="normal")

    def toggle_auto_gain(self):
        if self.auto_gain_var.get():
            self.gain_entry.config(state="disabled")
        else:
            self.gain_entry.config(state="normal")

    def detect_zwo_cameras(self):
        def task():
            self.after(0, lambda: self.detect_cam_btn.config(state="disabled", text="..."))
            script = """
import zwoasi as asi
import json
asi.init('/usr/lib/x86_64-linux-gnu/libASICamera2.so')
cams = asi.list_cameras()
res = {"cams": cams}
if len(cams) > 0:
    try:
        camera = asi.Camera(0)
        props = camera.get_camera_property()
        res["pixel"] = props.get("PixelSize", None)
        res["width"] = props.get("MaxWidth", None)
    except:
        pass
print(json.dumps(res))
"""
            try:
                import subprocess, os, json, sys
                from pathlib import Path
                venv_python = str(Path.home() / ".goto_andrivet" / "venv" / "bin" / "python3")
                python_path = venv_python if os.path.exists(venv_python) else sys.executable
                res = subprocess.run([python_path, "-c", script], capture_output=True, text=True)
                if res.returncode == 0:
                    try:
                        data = json.loads(res.stdout.strip())
                        cams = data.get("cams", [])
                        pixel = data.get("pixel")
                        width = data.get("width")
                        if cams:
                            self.after(0, lambda: self.update_astro_cam_combo(cams, pixel, width))
                        else:
                            self.after(0, lambda: messagebox.showinfo("ZWO", "Aucune caméra ZWO détectée."))
                    except Exception as parse_e:
                        error_msg = str(parse_e)
                        self.after(0, lambda msg=error_msg: messagebox.showerror("Erreur", "Erreur de parsing: " + msg))
                else:
                    self.after(0, lambda: messagebox.showerror("Erreur", "Erreur lors de la détection: " + res.stderr))
            except Exception as e:
                self.after(0, lambda err=str(e): messagebox.showerror("Erreur", err))
            finally:
                self.after(0, lambda: self.detect_cam_btn.config(state="normal", text="🔄"))
        
        import threading
        threading.Thread(target=task, daemon=True).start()

    def prompt_download_indexes(self):
        dl_choice = tk.Toplevel(self)
        dl_choice.title("Choix des Index Astrométrie")
        dl_choice.geometry("500x250")
        dl_choice.configure(bg="#c0c0c0")
        
        lbl = tk.Label(dl_choice, text="L'astrométrie locale nécessite des index (cartes du ciel).", bg="#c0c0c0", font=("Arial", 11, "bold"))
        lbl.pack(pady=10)
        
        def dl_all():
            dl_choice.destroy()
            self.download_astrometry_indexes(range(7, 20))
            
        def dl_smart():
            try:
                foc = float(self.foc_entry.get())
                if foc <= 0: raise ValueError
            except:
                messagebox.showerror("Erreur", "Veuillez d'abord renseigner une focale valide dans la case 'Focale (mm)'.")
                return
                
            import os
            if not os.path.exists('/tmp/astro_px_size.txt'):
                messagebox.showerror("Erreur", "Taille des pixels inconnue.\n\nVeuillez d'abord brancher votre caméra ZWO et faire un clic sur '1. Capturer (Aperçu)'.\nLe logiciel pourra ainsi lire la taille réelle de votre capteur et calculer les index exacts !")
                return
                
            try:
                px = float(open('/tmp/astro_px_size.txt').read().strip())
            except:
                messagebox.showerror("Erreur", "Erreur lors de la lecture des données de la caméra.")
                return
            
            # Calcul FOV approximatif (basé sur un capteur moyen de 2000 pixels sur son petit côté)
            scale = 206.265 * px / foc
            fov_arcmin = (scale * 2000) / 60.0
            
            target_scales = []
            INDEX_SCALES = {
                19: (1400, 2000), 18: (1000, 1400), 17: (680, 1000), 16: (480, 680), 15: (340, 480),
                14: (240, 340), 13: (170, 240), 12: (120, 170), 11: (85, 120), 10: (60, 85),
                9: (42, 60), 8: (30, 42), 7: (22, 30)
            }
            
            for sc, (low, high) in INDEX_SCALES.items():
                # On sélectionne les index qui couvrent entre 10% et 100% du FOV
                if high >= fov_arcmin * 0.1 and low <= fov_arcmin * 1.2:
                    target_scales.append(sc)
                    
            if not target_scales:
                target_scales = [7, 8, 9] # fallback si trop petit (très longue focale)
                
            min_sc = max(7, min(target_scales) - 1)
            max_sc = min(19, max(target_scales) + 1)
            dl_choice.destroy()
            self.download_astrometry_indexes(range(min_sc, max_sc + 1))

        btn_smart = tk.Button(dl_choice, text="Téléchargement Ciblé (Recommandé)\nCalcule et télécharge uniquement les index nécessaires\npour votre focale actuelle et caméra.", font=("Arial", 10), command=dl_smart, bg="white", relief="raised", bd=2)
        btn_smart.pack(fill="x", padx=20, pady=10)
        
        btn_all = tk.Button(dl_choice, text="Tout télécharger (~32 Go)\nPour être compatible avec tous les télescopes.", font=("Arial", 10), command=dl_all, bg="white", relief="raised", bd=2)
        btn_all.pack(fill="x", padx=20, pady=10)

    def download_astrometry_indexes(self, scales_range):
        import threading
        import urllib.request
        import os
        from tkinter import ttk

        data_dir = Path(__file__).parent / "astrometry_data"
        data_dir.mkdir(exist_ok=True)
        
        existing_files = list(data_dir.glob("*.fits"))
        if existing_files:
            ans = messagebox.askyesno("Index existants", 
                "Des fichiers d'index sont déjà présents dans le dossier.\n\n"
                "Voulez-vous supprimer les anciens fichiers pour libérer de l'espace (Recommandé si vous avez changé de télescope), "
                "ou 'Non' pour les conserver et juste ajouter les nouveaux ?"
            )
            if ans:
                for f in existing_files:
                    try:
                        f.unlink()
                    except:
                        pass

        files_to_dl = [f"index-41{i:02d}.fits" for i in scales_range]

        dl_top = tk.Toplevel(self)
        dl_top.title("Téléchargement")
        dl_top.geometry("450x200")
        dl_top.configure(bg="#c0c0c0")
        
        lbl = tk.Label(dl_top, text="Téléchargement des index en cours...", bg="#c0c0c0", font=("Arial", 10))
        lbl.pack(pady=10)
        
        progress = ttk.Progressbar(dl_top, orient="horizontal", length=350, mode="determinate")
        progress.pack(pady=10)

        lbl_file = tk.Label(dl_top, text="", bg="#c0c0c0")
        lbl_file.pack()
        
        lbl_stats = tk.Label(dl_top, text="", bg="#c0c0c0", font=("Arial", 9))
        lbl_stats.pack()
        
        cancel_flag = [False]
        def cancel_dl():
            cancel_flag[0] = True
            lbl_file.config(text="Annulation en cours... Veuillez patienter.")
            
        btn_cancel = tk.Button(dl_top, text="Annuler", command=cancel_dl, bg="white")
        btn_cancel.pack(pady=10)

        def task():
            try:
                base_url = "http://data.astrometry.net/4100/"
                total_files = len(files_to_dl)
                for idx, fname in enumerate(files_to_dl):
                    if cancel_flag[0]: break
                    
                    target_path = data_dir / fname
                    if target_path.exists():
                        # Si le fichier est déjà partiellement téléchargé et annulé, ou complet
                        # Pour simplifier on suppose que s'il existe on le saute (ou on pourrait vérifier sa taille)
                        if target_path.stat().st_size > 1000000: # on considère valide si > 1 Mo
                            continue
                        else:
                            target_path.unlink() # remove partial
                    
                    url = base_url + fname
                    self.after(0, lambda f=fname, i=idx: [lbl_file.config(text=f"Fichier {i+1}/{total_files} : {f}"), progress.config(value=(i/total_files)*100)])
                    
                    # Téléchargement par morceaux pour pouvoir annuler
                    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                    import time
                    with urllib.request.urlopen(req) as response, open(target_path, 'wb') as out_file:
                        try:
                            total_size = int(response.getheader('Content-Length').strip())
                        except:
                            total_size = 0
                            
                        chunk_size = 1024 * 1024 # 1 MB
                        downloaded = 0
                        start_time = time.time()
                        last_ui_update = 0
                        
                        while True:
                            if cancel_flag[0]:
                                break
                            chunk = response.read(chunk_size)
                            if not chunk:
                                break
                            out_file.write(chunk)
                            downloaded += len(chunk)
                            
                            now = time.time()
                            if now - last_ui_update > 0.5: # Update UI twice per second
                                last_ui_update = now
                                elapsed = now - start_time
                                speed_bps = downloaded / elapsed if elapsed > 0 else 0
                                speed_mbps = speed_bps / (1024 * 1024)
                                
                                if total_size > 0:
                                    percent = (downloaded / total_size) * 100
                                    eta_s = (total_size - downloaded) / speed_bps if speed_bps > 0 else 0
                                    eta_m = int(eta_s // 60)
                                    eta_s = int(eta_s % 60)
                                    
                                    dl_mb = downloaded / (1024*1024)
                                    tot_mb = total_size / (1024*1024)
                                    stat_str = f"{dl_mb:.1f} Mo / {tot_mb:.1f} Mo ({percent:.1f}%) - {speed_mbps:.1f} Mo/s - Reste: {eta_m}m{eta_s:02d}s"
                                else:
                                    dl_mb = downloaded / (1024*1024)
                                    stat_str = f"{dl_mb:.1f} Mo téléchargés - {speed_mbps:.1f} Mo/s"
                                    
                                self.after(0, lambda s=stat_str: lbl_stats.config(text=s))
                    
                    if cancel_flag[0]:
                        if target_path.exists():
                            target_path.unlink() # Delete partial file
                        break
                        
                if cancel_flag[0]:
                    self.after(0, lambda: messagebox.showinfo("Annulé", "Le téléchargement a été annulé."))
                else:
                    self.after(0, lambda: progress.config(value=100))
                    self.after(0, lambda: messagebox.showinfo("Succès", f"Tous les index ont été téléchargés dans :\n{data_dir}"))
            except Exception as e:
                if not cancel_flag[0]:
                    self.after(0, lambda err=e: messagebox.showerror("Erreur", f"Échec du téléchargement :\n{err}"))
            finally:
                self.after(0, dl_top.destroy)

        threading.Thread(target=task, daemon=True).start()

    def update_astro_cam_combo(self, cameras, pixel=None, width=None):
        self.cam_combo['values'] = cameras
        if cameras:
            self.cam_combo.current(0)
        
        if pixel is not None and hasattr(self, 'px_entry'):
            self.px_entry.delete(0, tk.END)
            self.px_entry.insert(0, str(pixel))
        if width is not None and hasattr(self, 'width_entry'):
            self.width_entry.delete(0, tk.END)
            self.width_entry.insert(0, str(width))
    def get_selected_camera_idx(self):
        idx = self.cam_combo.current()
        if idx >= 0:
            return idx
        try:
            val = self.cam_combo.get()
            if val.startswith("Cam "):
                return int(val[4:])
            return self.settings.get("astro_cam_idx", 0)
        except Exception:
            return 0

    def show_captured_image(self):
        try:
            import os
            if not os.path.exists('/tmp/capture_astro_preview.png'):
                return
            img = tk.PhotoImage(file="/tmp/capture_astro_preview.png")
            if hasattr(self, 'preview_top') and self.preview_top.winfo_exists():
                self.preview_lbl.config(image=img)
                self.preview_lbl.image = img
                self.preview_top.lift()
            else:
                self.preview_top = tk.Toplevel(self)
                self.preview_top.title("Dernière capture ZWO (Aperçu)")
                self.preview_lbl = tk.Label(self.preview_top, image=img, bg="black")
                self.preview_lbl.image = img
                self.preview_lbl.pack(fill="both", expand=True)
        except Exception as e:
            pass

    def toggle_astrometry_ui(self):
        if self.astro_en_var.get():
            self.astro_inner.pack(padx=15, pady=5, fill="x")
        else:
            self.astro_inner.pack_forget()

    def toggle_connection(self):
        if not self.is_connected:
            port = self.port_var.get()
            try:
                baud = int(self.baud_var.get())
            except ValueError:
                baud = 9600
                
            try:
                self.ser = serial.Serial(port, baud, timeout=1.5)
                # Wait for Arduino bootloader reset
                time.sleep(2.0)
                self.ser.reset_input_buffer()
                
                # Check connection with handshake (retry up to 3 times)
                resp = ""
                for attempt in range(3):
                    self.ser.write(b":GVP#")
                    resp = self.ser.read_until(b"#").decode('ascii', errors='ignore')
                    if "OnStep" in resp:
                        break
                    time.sleep(0.5)
                
                if "OnStep" in resp:
                    self.is_connected = True
                    self.settings["mount_port"] = port
                    self.settings["mount_baud"] = baud
                    self.save_local_settings()
                    self.update_connection_status()
                    # Play tone to signal success
                    self.ser.write(b":Bbp#")
                    self.ser.read_until(b"#")
                    messagebox.showinfo("Connection", f"Successfully connected to Arduino on {port}!")
                    
                    # Read current settings from Arduino
                    self.read_arduino_config()
                else:
                    self.ser.close()
                    self.ser = None
                    messagebox.showerror("Error", "Device on this port did not respond to the GotoAndrivet (OnStep) protocol.")
            except Exception as e:
                if self.ser:
                    self.ser.close()
                    self.ser = None
                messagebox.showerror("Connection Error", f"Cannot open port {port}:\n{e}")
        else:
            if self.ser:
                self.ser.close()
                self.ser = None
            self.is_connected = False
            self.update_connection_status()
            messagebox.showinfo("Disconnection", "Disconnected from Arduino.")

    def update_connection_status(self):
        lang = self.settings.get("language", "fr")
        t = TRANSLATIONS[lang]
        if self.is_connected:
            self.status_lbl.config(text=t["connected"], fg="green")
            self.conn_btn.config(text=t["disconnect"])
            self.port_menu.config(state="disabled")
            self.baud_menu.config(state="disabled")
            
            # Enable actions
            self.beep_test_btn.config(state="normal")
            self.sync_btn.config(state="normal")
            self.sync_pc_btn.config(state="normal")
            self.apply_btn.config(state="normal")
            self.park_btn.config(state="normal")
            self.unpark_btn.config(state="normal")
            self.beep_test_btn.config(state="normal")
            self.unpark_btn.config(state="normal")
        else:
            self.status_lbl.config(text=t["disconnected"], fg="red")
            self.conn_btn.config(text=t["connect"])
            self.port_menu.config(state="normal")
            self.baud_menu.config(state="normal")
            
            # Disable actions
            self.beep_test_btn.config(state="disabled")
            self.sync_btn.config(state="disabled")
            self.sync_pc_btn.config(state="disabled")
            self.apply_btn.config(state="disabled")
            self.park_btn.config(state="disabled")
            self.unpark_btn.config(state="disabled")
            self.beep_test_btn.config(state="disabled")
            self.unpark_btn.config(state="disabled")

    def test_beep(self):
        if self.is_connected and self.ser:
            try:
                self.ser.write(b":Bbp#")
                self.ser.read_until(b"#")
            except Exception as e:
                self.handle_serial_error(e)

    def park_mount(self):
        if self.is_connected and self.ser:
            try:
                self.ser.write(b":hP#")
                reply = self.ser.read(1).decode('ascii', errors='ignore')
                if "1" in reply:
                    messagebox.showinfo("Park", "Mount parking sequence initiated.")
                else:
                    messagebox.showerror("Error", "Could not park mount (it might be slewing).")
            except Exception as e:
                self.handle_serial_error(e)

    def unpark_mount(self):
        if self.is_connected and self.ser:
            try:
                self.ser.write(b":hR#")
                reply = self.ser.read(1).decode('ascii', errors='ignore')
                if "1" in reply:
                    messagebox.showinfo("Unpark", "Mount unparked successfully. Motors enabled.")
                else:
                    messagebox.showerror("Error", "Could not unpark mount.")
            except Exception as e:
                self.handle_serial_error(e)

    def sync_time_date(self):
        if self.is_connected and self.ser:
            try:
                now = datetime.now()
                # 1. Date
                self.ser.write(f":SC{now.month:02d}/{now.day:02d}/{now.year%100:02d}#".encode('ascii'))
                self.ser.read_until(b"#")
                self.ser.read_until(b"#")
                
                # 2. Time
                self.ser.write(f":SL{now.hour:02d}:{now.minute:02d}:{now.second:02d}#".encode('ascii'))
                self.ser.read(1)
                
                # 3. Timezone
                utc_offset = -time.timezone / 3600.0
                if time.daylight and time.localtime().tm_isdst:
                    utc_offset = -time.altzone / 3600.0
                # :SG (LX200) : heures à ajouter à l'heure locale pour obtenir l'UTC, donc UTC+2 -> :SG-02
                sign = '-' if utc_offset >= 0 else '+'
                self.ser.write(f":SG{sign}{int(abs(utc_offset)):02d}#".encode('ascii'))
                self.ser.read(1)
                
                self.time_lbl.config(text=f"Synced: {now.strftime('%H:%M:%S')}")
                messagebox.showinfo("Synchronization", "PC clock sent to Arduino!")
            except Exception as e:
                self.handle_serial_error(e)

    def download_iss_tle(self):
        def task():
            import urllib.request
            from pathlib import Path
            urls = [
                "https://live.ariss.org/iss.txt",
                "https://www.amsat.org/tle/current/nasa.all",
                "https://celestrak.org/NORAD/elements/stations.txt"
            ]
            iss_lines = []
            last_err = None
            for url in urls:
                try:
                    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(req, timeout=5) as response:
                        data = response.read().decode('utf-8', errors='ignore')
                    
                    lines = data.splitlines()
                    for i, line in enumerate(lines):
                        if line.strip().upper() in ("ISS", "ISS (ZARYA)"):
                            iss_lines = [lines[i].strip(), lines[i+1].strip(), lines[i+2].strip()]
                            break
                    if iss_lines:
                        break
                except Exception as e:
                    last_err = e
                    continue
            
            if not iss_lines:
                err_msg = f"Erreur de connexion: {last_err}" if last_err else "ISS introuvable dans les catalogues."
                self.after(0, lambda: messagebox.showerror("Erreur", err_msg))
                return
            
            try:
                tle_str = "\n".join(iss_lines)
                tle_path = Path.home() / ".goto_andrivet" / "iss.tle"
                with open(tle_path, "w", encoding="utf-8") as f:
                    f.write(tle_str)
                    
                self.after(0, lambda: messagebox.showinfo("Succès", f"TLE de l'ISS téléchargé et sauvegardé dans:\n{tle_path}\n(Il sera automatiquement supprimé dans 24h)\n\n{tle_str}"))
            except Exception as e:
                self.after(0, lambda err=e: messagebox.showerror("Erreur", f"Erreur d'écriture:\n{err}"))
        
        import threading
        threading.Thread(target=task, daemon=True).start()

    def sync_pc_from_arduino(self):
        if self.is_connected and self.ser:
            try:
                # 1. Date
                self.ser.write(b":GC#")
                date_raw = self.ser.read_until(b"#").decode('ascii', errors='ignore').strip('#')
                # 2. Time
                self.ser.write(b":GL#")
                time_raw = self.ser.read_until(b"#").decode('ascii', errors='ignore').strip('#')
                
                parts = date_raw.split('/')
                if len(date_raw) >= 8 and len(time_raw) >= 8 and len(parts) == 3:
                    mm, dd, yy = parts
                    # 20YY assumption
                    full_date = f"20{yy}-{mm}-{dd} {time_raw}"
                    
                    import subprocess
                    import os
                    # Use pkexec if available to set date
                    try:
                        subprocess.run(["pkexec", "date", "-s", full_date], check=True)
                        messagebox.showinfo("Time Sync", f"PC clock synced successfully to: {full_date}")
                        self.time_lbl.config(text=f"Synced: {time_raw}")
                    except Exception as e:
                        messagebox.showerror("Time Sync Error", f"Failed to set PC time (requires privileges):\n{e}\nCommand: pkexec date -s '{full_date}'")
                else:
                    messagebox.showerror("Time Sync Error", "Invalid date/time received from Arduino.")
            except Exception as e:
                self.handle_serial_error(e)

    def read_arduino_config(self):
        if self.is_connected and self.ser:
            try:
                # Latitude
                self.ser.write(b":Gt#")
                lat_raw = self.ser.read_until(b"#").decode('ascii', errors='ignore').strip('#')
                # Longitude
                self.ser.write(b":Gg#")
                lon_raw = self.ser.read_until(b"#").decode('ascii', errors='ignore').strip('#')
                
                # Slew speed
                self.ser.write(b":Bv#")
                speed_raw = self.ser.read_until(b"#").decode('ascii', errors='ignore').strip('#')
                
                # Query AZ reverse
                self.ser.write(b":BRa#")
                rev_az_raw = self.ser.read_until(b"#").decode('ascii', errors='ignore').strip('#')
                
                # Query ALT reverse
                self.ser.write(b":BRe#")
                rev_alt_raw = self.ser.read_until(b"#").decode('ascii', errors='ignore').strip('#')
                
                # Query Mount Type
                self.ser.write(b":GM#")
                gm_raw = self.ser.read_until(b"#").decode('ascii', errors='ignore').strip('#')
                
                # Gear ratios and motor steps
                self.ser.write(b":GGa#")
                gear_az_raw = self.ser.read_until(b"#").decode('ascii', errors='ignore').strip('#')
                self.ser.write(b":GGe#")
                gear_alt_raw = self.ser.read_until(b"#").decode('ascii', errors='ignore').strip('#')
                self.ser.write(b":GSp#")
                steps_raw = self.ser.read_until(b"#").decode('ascii', errors='ignore').strip('#')
                self.ser.write(b":GSm#")
                micro_raw = self.ser.read_until(b"#").decode('ascii', errors='ignore').strip('#')
                
                # Park Alt/Az
                self.ser.write(b":GQa#")
                park_alt_raw = self.ser.read_until(b"#").decode('ascii', errors='ignore').strip('#')
                self.ser.write(b":GQz#")
                park_az_raw = self.ser.read_until(b"#").decode('ascii', errors='ignore').strip('#')

                # Drivers TMC5160 (Teensy)
                tmc_state = self._tmc_status()
                tmc_cfg = None
                if tmc_state:
                    tmc_cfg = {
                        "current": [self._tmc_query(f":XTI{ax}#") for ax in TMC_AXES],
                        "hold": self._tmc_query(":XTH#"),
                        "stealth": self._tmc_query(":XTP#"),
                        "ms_derot": self._tmc_query(":XTMd#"),
                        "ms_focus": self._tmc_query(":XTMf#"),
                    }

                def _update_ui():
                    self._tmc_show_state(tmc_state)
                    if tmc_cfg:
                        self.tmc_spi_var.set(tmc_state[0] == '1')
                        self.tmc_stealth_var.set(tmc_cfg["stealth"] == '1')
                        for e, v in zip(self.tmc_current_entries, tmc_cfg["current"]):
                            if v.isdigit():
                                e.delete(0, tk.END)
                                e.insert(0, v)
                        if tmc_cfg["hold"].isdigit():
                            self.tmc_hold_entry.delete(0, tk.END)
                            self.tmc_hold_entry.insert(0, tmc_cfg["hold"])
                        if tmc_cfg["ms_derot"].isdigit():
                            self.tmc_ms_derot_var.set(tmc_cfg["ms_derot"])
                        if tmc_cfg["ms_focus"].isdigit():
                            self.tmc_ms_focus_var.set(tmc_cfg["ms_focus"])

                    if gm_raw in ("AltAz", "ForkEq", "GermanEq"):
                        self.mount_type_var.set(gm_raw)
                        self.on_mount_type_changed(gm_raw)
                    self.rev_az_var.set(rev_az_raw == '1')
                    self.rev_alt_var.set(rev_alt_raw == '1')
                    
                    try:
                        lat_val = self.parse_lx_coords(lat_raw)
                        self.lat_entry.delete(0, tk.END)
                        self.lat_entry.insert(0, f"{lat_val:.4f}")
                    except: pass
                        
                    try:
                        lon_val = -self.parse_lx_coords(lon_raw)   # :Gg : Ouest positif (LX200)
                        self.lon_entry.delete(0, tk.END)
                        self.lon_entry.insert(0, f"{lon_val:.4f}")
                    except: pass
                        
                    try:
                        s_val = int(speed_raw) / 10.0
                        self.speed_scale.set(s_val)
                        self.update_speed_lbl(s_val)
                    except: pass
                        
                    if gear_az_raw:
                        try:
                            v = f"{float(gear_az_raw):.1f}"
                            self.gear_az_entry.delete(0, tk.END)
                            self.gear_az_entry.insert(0, v)
                        except: pass
                    if gear_alt_raw:
                        try:
                            v = f"{float(gear_alt_raw):.1f}"
                            self.gear_alt_entry.delete(0, tk.END)
                            self.gear_alt_entry.insert(0, v)
                        except: pass
                    if steps_raw:
                        try:
                            v = str(int(steps_raw))
                            self.steps_entry.delete(0, tk.END)
                            self.steps_entry.insert(0, v)
                        except: pass
                    if micro_raw:
                        try:
                            self.microstep_var.set(str(int(micro_raw)))
                        except: pass
                    if park_alt_raw:
                        try:
                            v = f"{float(park_alt_raw):.1f}"
                            self.park_alt_entry.delete(0, tk.END)
                            self.park_alt_entry.insert(0, v)
                        except: pass
                    if park_az_raw:
                        try:
                            v = f"{float(park_az_raw):.1f}"
                            self.park_az_entry.delete(0, tk.END)
                            self.park_az_entry.insert(0, v)
                        except: pass
                    self.apply_hardware_constraints()   # ex. PCB drivers externes : SPI coupé

                self.after(0, _update_ui)
                # messagebox.showinfo is already shown in toggle_connection, but let's keep it if needed. Actually it was here.
                # I'll just remove it from here since toggle_connection shows it, to avoid duplicate dialogs.
            except Exception as e:
                self.after(0, lambda err=e: self.handle_serial_error(err))

    def parse_lx_coords(self, raw):
        sign = -1.0 if raw[0] == '-' else 1.0
        parts = raw[1:].replace('*', ':').split(':')
        d = float(parts[0])
        m = float(parts[1]) if len(parts) > 1 else 0.0
        s = float(parts[2]) if len(parts) > 2 else 0.0
        return sign * (d + m/60.0 + s/3600.0)

    def format_lat_lx(self, lat):
        sign = '+' if lat >= 0 else '-'
        val = abs(lat)
        d = int(val)
        m = int((val - d) * 60)
        s = int(((val - d) * 60 - m) * 60)
        return f"{sign}{d:02d}*{m:02d}:{s:02d}"

    def format_lon_lx(self, lon):
        # LX200 : longitude Ouest positive. Le champ de l'outil est en Est positif.
        sign = '-' if lon >= 0 else '+'
        val = abs(lon)
        d = int(val)
        m = int((val - d) * 60)
        s = int(((val - d) * 60 - m) * 60)
        return f"{sign}{d:03d}*{m:02d}:{s:02d}"

    def format_ra_lx(self, ra_hours):
        h = int(ra_hours)
        rem = (ra_hours - h) * 60.0
        m = int(rem)
        s = int((rem - m) * 60.0)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def format_dec_lx(self, dec_deg):
        sign = "+" if dec_deg >= 0 else "-"
        d = abs(dec_deg)
        deg = int(d)
        rem = (d - deg) * 60.0
        m = int(rem)
        s = int((rem - m) * 60.0)
        return f"{sign}{deg:02d}*{m:02d}:{s:02d}"

    def start_capture_progress(self, duration_sec):
        self.astro_progress['value'] = 0
        self.astro_progress['maximum'] = 100
        steps = 50
        delay_ms = int((duration_sec * 1000) / steps)
        
        def step(i):
            if i <= steps:
                self.astro_progress['value'] = (i / steps) * 100
                self.after(delay_ms, lambda: step(i+1))
            else:
                self.astro_progress['value'] = 100
                
        if delay_ms > 0:
            step(1)
        else:
            self.astro_progress['value'] = 100

    def run_capture_only(self):
        def task():
            try:
                self.after(0, lambda: self.capture_btn.config(state="disabled", text="Capture ZWO..."))
                try:
                    exp = float(self.exp_entry.get())
                    gain = int(self.gain_entry.get())
                    cam_idx = self.get_selected_camera_idx()
                except ValueError:
                    self.after(0, lambda: messagebox.showerror("Erreur", "Valeurs invalides dans les champs astrométrie."))
                    return
                auto_gain = self.auto_gain_var.get()
                
                self.after(0, lambda: self.start_capture_progress(exp))
                
                script = f"""
import sys
import os
import zwoasi as asi
import cv2
import time
import numpy as np
asi.init('/usr/lib/x86_64-linux-gnu/libASICamera2.so')
num_cameras = asi.get_num_cameras()
if num_cameras <= {cam_idx}:
    print("NO_CAMERA")
    sys.exit(1)
camera = asi.Camera({cam_idx})
props = camera.get_camera_property()
pixel_size = props['PixelSize']
with open('/tmp/astro_px_size.txt', 'w') as f_px:
    f_px.write(str(pixel_size))

camera.set_control_value(asi.ASI_EXPOSURE, int({exp} * 1000000))
camera.set_control_value(asi.ASI_GAIN, {gain}, auto={auto_gain})
camera.set_image_type(asi.ASI_IMG_RAW8)

try:
    camera.capture(filename='/tmp/capture_astro.png')
except asi.ZWO_CaptureError:
    # Fallback to manual gain if auto gain fails on long exposures
    camera.set_control_value(asi.ASI_GAIN, {gain}, auto=False)
    camera.capture(filename='/tmp/capture_astro.png')

# Create preview image
img = cv2.imread('/tmp/capture_astro.png', cv2.IMREAD_GRAYSCALE)
if img is not None:
    h, w = img.shape
    scale = 640.0 / w
    if scale < 1.0:
        img = cv2.resize(img, (int(w*scale), int(h*scale)))
    p2, p99 = np.percentile(img, (2, 99.5))
    if p99 > p2:
        stretched = np.clip((img - p2) / (p99 - p2) * 255.0, 0, 255).astype(np.uint8)
    else:
        stretched = img
    
    # Convert to BGR so tkinter PhotoImage doesn't load it as black/transparent
    stretched_bgr = cv2.cvtColor(stretched, cv2.COLOR_GRAY2BGR)
    cv2.imwrite('/tmp/capture_astro_preview.png', stretched_bgr)
"""
                with open('/tmp/zwo_capture.py', 'w') as f:
                    f.write(script)
                
                import sys
                from pathlib import Path
                venv_python = str(Path.home() / ".goto_andrivet" / "venv" / "bin" / "python3")
                python_path = venv_python if os.path.exists(venv_python) else sys.executable
                res = subprocess.run([python_path, "/tmp/zwo_capture.py"], capture_output=True, text=True)
                if res.returncode != 0:
                    self.after(0, lambda: messagebox.showerror("Erreur ZWO", "Erreur capture ZWO.\\n" + res.stderr))
                    return
                
                self.after(0, self.show_captured_image)
                self.after(0, lambda: self.solve_btn.config(state="normal"))
                
            except Exception as e:
                self.after(0, lambda err=e: messagebox.showerror("Erreur", str(err)))
            finally:
                self.after(0, lambda: self.capture_btn.config(state="normal", text="1. Capturer (Aperçu)"))

        import threading
        threading.Thread(target=task, daemon=True).start()

    def toggle_astro_api(self):
        if self.astro_mode_var.get() == "api":
            self.api_key_frame.pack(fill="x", pady=2, after=self.astro_mode_frame)
            self.astro_dl_btn.config(state="disabled")
        else:
            self.api_key_frame.pack_forget()
            self.astro_dl_btn.config(state="normal")

    def run_astrometry_api(self, image_path):
        import requests
        import time
        import json
        
        api_key = self.api_key_entry.get().strip()
        if not api_key:
            return False, "La Clé API est requise pour utiliser le mode en ligne."
            
        base_url = "http://nova.astrometry.net/api"
        
        # 1. Login
        try:
            r = requests.post(f"{base_url}/login", data={'request-json': json.dumps({"apikey": api_key})}, timeout=10)
            session = r.json().get("session")
            if not session:
                return False, "Échec de la connexion API. Vérifiez votre clé."
        except Exception as e:
            return False, f"Erreur de réseau: {e}"

        # 2. Upload
        try:
            with open(image_path, 'rb') as f:
                self.after(0, lambda: self.solve_btn.config(text="Upload en cours..."))
                r = requests.post(f"{base_url}/upload", 
                    data={'request-json': json.dumps({"session": session})}, 
                    files={'file': f}, timeout=60)
            sub_id = r.json().get("subid")
            if not sub_id:
                return False, "Échec de l'upload de l'image."
        except Exception as e:
            return False, f"Erreur d'upload: {e}"
            
        # 3. Wait for job
        self.after(0, lambda: self.solve_btn.config(text="Résolution en ligne..."))
        job_id = None
        for _ in range(30):
            time.sleep(2)
            r = requests.get(f"{base_url}/submissions/{sub_id}", timeout=10)
            jobs = r.json().get("jobs", [])
            if jobs and jobs[0] is not None:
                job_id = jobs[0]
                break
                
        if not job_id:
            return False, "Le serveur n'a pas renvoyé de Job ID à temps."

        # 4. Wait for success
        for _ in range(60):
            time.sleep(3)
            r = requests.get(f"{base_url}/jobs/{job_id}", timeout=10)
            status = r.json().get("status")
            if status == "success":
                r = requests.get(f"{base_url}/jobs/{job_id}/calibration", timeout=10)
                cal = r.json()
                return True, cal
            elif status == "failure":
                return False, "L'astrométrie en ligne a échoué (échec du job)."

        return False, "Délai d'attente dépassé (timeout)."

    def open_polar_alignment(self):
        try:
            import sys
            import os
            sys.path.append(os.path.dirname(os.path.abspath(__file__)))
            from polar_alignment_ui import open_pa_window
            open_pa_window(self)
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible d'ouvrir l'assistant PA:\n{e}")

    def run_solve_only(self):
        if not os.path.exists('/tmp/capture_astro.png'):
            messagebox.showerror("Erreur", "Aucune image capturée. Veuillez d'abord capturer une image.")
            return
            
        def task():
            try:
                self.after(0, lambda: self.solve_btn.config(state="disabled", text="Résolution (Astrométrie)..."))
                try:
                    focal = float(self.foc_entry.get())
                except ValueError:
                    self.after(0, lambda: messagebox.showerror("Erreur", "Valeurs invalides (focale)."))
                    return
                blind = self.blind_var.get()
                
                pixel_size = 3.76
                try:
                    pixel_size = float(self.px_entry.get())
                except:
                    pass
                
                sf_cmd = ["solve-field", "/tmp/capture_astro.png", "--overwrite", "--no-plots", "--cpulimit", "30"]
                
                if not blind and focal > 0:
                    scale_arcsec = 206.265 * pixel_size / focal
                    scale_low = scale_arcsec * 0.90
                    scale_high = scale_arcsec * 1.10
                    sf_cmd.extend(["--scale-units", "arcsecperpix", "--scale-low", str(scale_low), "--scale-high", str(scale_high)])
                
                if getattr(self, 'astro_mode_var', None) and self.astro_mode_var.get() == "api":
                    self.after(0, lambda: self.solve_btn.config(text="Upload API..."))
                    success, res = self.run_astrometry_api("/tmp/capture_astro.png")
                    if success:
                        ra_deg = res.get("ra", 0)
                        dec_deg = res.get("dec", 0)
                        ra_hours = ra_deg / 15.0
                        ra_str = self.format_ra_lx(ra_hours)
                        dec_str = self.format_dec_lx(dec_deg)
                        if getattr(self, 'is_connected', False) and getattr(self, 'ser', None):
                            self.after(0, lambda: self.solve_btn.config(text="Synchronisation Monture..."))
                            import time
                            self.ser.write(f":Sr{ra_str}#".encode('ascii'))
                            time.sleep(0.1)
                            self.ser.write(f":Sd{dec_str}#".encode('ascii'))
                            time.sleep(0.1)
                            self.ser.write(b":CM#")
                            self.after(0, lambda: messagebox.showinfo("Astrométrie API", f"Astrométrie OK!\\nRA: {ra_str}\\nDEC: {dec_str}\\nMonture synchronisée."))
                        else:
                            self.after(0, lambda: messagebox.showinfo("Astrométrie API", f"Astrométrie OK!\\nRA: {ra_str}\\nDEC: {dec_str}\\n(Test: Monture non connectée)"))
                    else:
                        self.after(0, lambda: messagebox.showerror("Erreur API", str(res)))
                else:
                    self.after(0, lambda: self.solve_btn.config(text="Résolution (solve-field)..."))
                    res_sf = subprocess.run(sf_cmd, capture_output=True, text=True)
                    
                    import re
                    match = re.search(r"Field center: \(RA,Dec\) = \(\s*([0-9.]+),\s*([0-9.\-]+)\s*\)", res_sf.stdout)
                    if match:
                        ra_deg = float(match.group(1))
                        dec_deg = float(match.group(2))
                        
                        ra_hours = ra_deg / 15.0
                        ra_str = self.format_ra_lx(ra_hours)
                        dec_str = self.format_dec_lx(dec_deg)
                        
                        if getattr(self, 'is_connected', False) and getattr(self, 'ser', None):
                            self.after(0, lambda: self.solve_btn.config(text="Synchronisation Monture..."))
                            import time
                            self.ser.write(f":Sr{ra_str}#".encode('ascii'))
                            time.sleep(0.1)
                            self.ser.write(f":Sd{dec_str}#".encode('ascii'))
                            time.sleep(0.1)
                            self.ser.write(b":CM#")
                            self.after(0, lambda: messagebox.showinfo("Astrométrie Succès", f"Astrométrie OK!\\nRA: {ra_str}\\nDEC: {dec_str}\\nMonture synchronisée avec succès."))
                        else:
                            self.after(0, lambda: messagebox.showinfo("Astrométrie Succès", f"Astrométrie OK!\\nRA: {ra_str}\\nDEC: {dec_str}\\n(Test: Monture non connectée, sync ignorée)"))
                    else:
                        self.after(0, lambda: messagebox.showerror("Erreur Astrométrie", "Échec astrométrie (plate solving failed).\\n" + res_sf.stdout[:300]))
                    
            except Exception as e:
                self.after(0, lambda err=e: messagebox.showerror("Erreur", str(err)))
            finally:
                self.after(0, lambda: self.solve_btn.config(state="normal", text="2. Résoudre & Sync"))

        import threading
        threading.Thread(target=task, daemon=True).start()

    def open_preview_focuser(self):
        if hasattr(self, 'preview_top') and self.preview_top.winfo_exists():
            self.preview_top.focus()
            return
            
        try:
            cam_idx = self.get_selected_camera_idx()
            gain = int(self.gain_entry.get())
            exp = float(self.exp_entry.get())
        except ValueError:
            messagebox.showerror("Erreur", "Valeur gain ou expo invalide.")
            return

        with open('/tmp/zwo_preview_exp.txt', 'w') as f:
            f.write(str(exp))

        script = f"""
import sys, os, time
import zwoasi as asi
import cv2
import numpy as np

try:
    asi.init('/usr/lib/x86_64-linux-gnu/libASICamera2.so')
    camera = asi.Camera({cam_idx})
    controls = camera.get_controls()
    if 'BandWidth' in controls:
        camera.set_control_value(asi.ASI_BANDWIDTHOVERLOAD, controls['BandWidth']['MinValue'])
    exp_us = int({exp} * 1000000)
    camera.set_control_value(asi.ASI_EXPOSURE, exp_us)
    camera.set_control_value(asi.ASI_GAIN, {gain}, auto=True)
    camera.set_image_type(asi.ASI_IMG_RAW8)
    camera.start_video_capture()
    last_exp = exp_us
    while True:
        try:
            with open('/tmp/zwo_preview_exp.txt', 'r') as f:
                new_exp = int(float(f.read().strip()) * 1000000)
                if new_exp != last_exp and new_exp > 0:
                    camera.stop_video_capture()
                    camera.set_control_value(asi.ASI_EXPOSURE, new_exp)
                    camera.start_video_capture()
                    last_exp = new_exp
        except:
            pass
        try:
            frame = camera.capture_video_frame(timeout=int(last_exp/1000) + 5000)
        except Exception as e:
            continue
        h, w = frame.shape
        scale = 640.0 / w
        if scale < 1.0:
            frame = cv2.resize(frame, (int(w*scale), int(h*scale)))
        p2, p99 = np.percentile(frame, (2, 99.5))
        if p99 > p2:
            frame_norm = np.clip((frame - p2) / (p99 - p2) * 255.0, 0, 255).astype(np.uint8)
        else:
            frame_norm = frame
        
        sharpness = cv2.Laplacian(frame_norm, cv2.CV_64F).var()
        with open('/tmp/zwo_sharpness.txt', 'w') as f:
            f.write(str(sharpness))
            
        frame_bgr = cv2.cvtColor(frame_norm, cv2.COLOR_GRAY2BGR)
        cv2.imwrite('/tmp/capture_astro_stream_tmp.ppm', frame_bgr)
        os.rename('/tmp/capture_astro_stream_tmp.ppm', '/tmp/capture_astro_stream.ppm')
except KeyboardInterrupt:
    pass
except Exception as e:
    with open('/tmp/zwo_stream_err.txt', 'w') as f:
        f.write(str(e))
finally:
    try: camera.stop_video_capture()
    except: pass
"""
        with open('/tmp/zwo_preview_stream.py', 'w') as f:
            f.write(script)
            
        import sys
        venv_python = str(Path.home() / ".goto_andrivet" / "venv" / "bin" / "python3")
        python_path = venv_python if os.path.exists(venv_python) else sys.executable

        import subprocess
        self.stream_proc = subprocess.Popen([python_path, "/tmp/zwo_preview_stream.py"])
        
        self.preview_top = tk.Toplevel(self)
        self.preview_top.title("Mise au Point (Preview ZWO)")
        self.preview_top.protocol("WM_DELETE_WINDOW", self.close_preview_focuser)
        
        self.preview_lbl = tk.Label(self.preview_top, bg="black", width=640, height=480)
        self.preview_lbl.pack(padx=10, pady=10)
        
        self.sharpness_lbl = tk.Label(self.preview_top, text="Focus Score: 0.00", font=("Arial", 14, "bold"), fg="red")
        self.sharpness_lbl.pack(pady=5)
        
        exp_frame = tk.Frame(self.preview_top, bg="#c0c0c0")
        exp_frame.pack(pady=5)
        tk.Label(exp_frame, text="Temps de pose (s):", bg="#c0c0c0", font=("Arial", 10)).pack(side="left")
        self.preview_exp_var = tk.StringVar(value=str(exp))
        tk.Entry(exp_frame, textvariable=self.preview_exp_var, width=6, font=("Arial", 10)).pack(side="left", padx=5)
        
        def update_preview_exp():
            try:
                val = float(self.preview_exp_var.get())
                with open('/tmp/zwo_preview_exp.txt', 'w') as f:
                    f.write(str(val))
            except ValueError:
                pass
                
        tk.Button(exp_frame, text="Appliquer", command=update_preview_exp).pack(side="left")
        
        self.preview_progress = ttk.Progressbar(self.preview_top, orient="horizontal", mode="determinate")
        self.preview_progress.pack(fill="x", padx=10, pady=(0,5))
        self.preview_progress_start_time = time.time()
        
        foc_frame = tk.Frame(self.preview_top, bg="#c0c0c0")
        foc_frame.pack(fill="x", padx=10, pady=(0,10))
        
        lbl = tk.Label(foc_frame, text="Contrôle du Focuseur:", bg="#c0c0c0", font=("Arial", 12, "bold"))
        lbl.pack(pady=5)
        
        btn_frame = tk.Frame(foc_frame, bg="#c0c0c0")
        btn_frame.pack()
        
        def foc_in_mega(event=None):
            if getattr(self, 'is_connected', False) and getattr(self, 'ser', None) and self.focus_mega_var.get():
                self.ser.write(b":XF+#")
                self.ser.read(1)
                
        def foc_out_mega(event=None):
            if getattr(self, 'is_connected', False) and getattr(self, 'ser', None) and self.focus_mega_var.get():
                self.ser.write(b":XF-#")
                self.ser.read(1)
                
        def foc_stop_mega(event=None):
            if getattr(self, 'is_connected', False) and getattr(self, 'ser', None) and self.focus_mega_var.get():
                self.ser.write(b":XFQ#")
                self.ser.read(1)
                
        def foc_move_eaf(steps):
            if not getattr(self, 'focus_eaf_var', None) or not self.focus_eaf_var.get():
                return
            if not getattr(self, 'eaf_lib', None):
                import ctypes
                ctypes.CDLL('libudev.so.1', mode=ctypes.RTLD_GLOBAL)
                try:
                    self.eaf_lib = ctypes.cdll.LoadLibrary('/usr/lib/x86_64-linux-gnu/libEAFFocuser.so')
                    self.eaf_lib.EAFGetNum.restype = ctypes.c_int
                    self.eaf_lib.EAFGetID.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
                    self.eaf_lib.EAFOpen.argtypes = [ctypes.c_int]
                    self.eaf_lib.EAFGetPosition.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
                    self.eaf_lib.EAFMove.argtypes = [ctypes.c_int, ctypes.c_int]
                    self.eaf_id = -1
                    if self.eaf_lib.EAFGetNum() > 0:
                        _id = ctypes.c_int()
                        self.eaf_lib.EAFGetID(0, ctypes.byref(_id))
                        self.eaf_id = _id.value
                        self.eaf_lib.EAFOpen(self.eaf_id)
                except Exception:
                    self.eaf_lib = None
            if getattr(self, 'eaf_lib', None) and self.eaf_id >= 0:
                import ctypes
                pos = ctypes.c_int()
                self.eaf_lib.EAFGetPosition(self.eaf_id, ctypes.byref(pos))
                self.eaf_lib.EAFMove(self.eaf_id, pos.value + steps)

        def btn_in_press(event): foc_in_mega()
        def btn_in_release(event):
            foc_stop_mega()
            foc_move_eaf(-100)
            
        def btn_in_fast_release(event): foc_move_eaf(-500)
            
        def btn_out_press(event): foc_out_mega()
        def btn_out_release(event):
            foc_stop_mega()
            foc_move_eaf(100)
            
        def btn_out_fast_release(event): foc_move_eaf(500)

        btn_in_fast = tk.Button(btn_frame, text="<<< IN", font=("Arial", 12), width=6)
        btn_in_fast.bind("<ButtonRelease-1>", btn_in_fast_release)
        btn_in_fast.pack(side="left", padx=5)

        btn_in = tk.Button(btn_frame, text="< IN", font=("Arial", 12), width=6)
        btn_in.bind("<ButtonPress-1>", btn_in_press)
        btn_in.bind("<ButtonRelease-1>", btn_in_release)
        btn_in.pack(side="left", padx=5)
        
        btn_out = tk.Button(btn_frame, text="OUT >", font=("Arial", 12), width=6)
        btn_out.bind("<ButtonPress-1>", btn_out_press)
        btn_out.bind("<ButtonRelease-1>", btn_out_release)
        btn_out.pack(side="left", padx=5)
        
        btn_out_fast = tk.Button(btn_frame, text="OUT >>>", font=("Arial", 12), width=6)
        btn_out_fast.bind("<ButtonRelease-1>", btn_out_fast_release)
        btn_out_fast.pack(side="left", padx=5)
        
        self.af_running = False
        self.af_state = 'IDLE'
        self.af_dir = 1
        self.af_last_score = 0
        self.af_step = 0
        
        def run_autofocus():
            if self.af_running:
                self.af_running = False
                btn_af.config(text="Auto Focus", bg="#c0c0c0")
                foc_stop_mega()
                return
            self.af_running = True
            self.af_state = 'INIT'
            self.af_dir = -1 # Start IN
            self.af_last_score = 0
            btn_af.config(text="Stop Auto Focus", bg="red")
            
        btn_af = tk.Button(btn_frame, text="Auto Focus", font=("Arial", 12, "bold"), width=12, command=run_autofocus, bg="#c0c0c0")
        btn_af.pack(side="left", padx=20)
        
        self.af_mega_in = foc_in_mega
        self.af_mega_out = foc_out_mega
        self.af_mega_stop = foc_stop_mega
        self.af_eaf_move = foc_move_eaf
        self.btn_af = btn_af
        
        self.update_preview_stream()

    def close_preview_focuser(self):
        if hasattr(self, 'stream_proc'):
            try:
                self.stream_proc.terminate()
            except Exception:
                pass
        self.preview_top.destroy()
        
    def update_preview_stream(self):
        if not hasattr(self, 'preview_top') or not self.preview_top.winfo_exists():
            return
        try:
            import os
            import time
            if os.path.exists('/tmp/capture_astro_stream.ppm'):
                mtime = os.path.getmtime('/tmp/capture_astro_stream.ppm')
                if getattr(self, 'last_stream_mtime', 0) != mtime:
                    self.last_stream_mtime = mtime
                    self.preview_progress_start_time = time.time()
                    if not hasattr(self, 'preview_photo'):
                        self.preview_photo = tk.PhotoImage(file='/tmp/capture_astro_stream.ppm')
                        self.preview_lbl.config(image=self.preview_photo)
                    else:
                        self.preview_photo.configure(file='/tmp/capture_astro_stream.ppm')
            
            if hasattr(self, 'preview_progress_start_time'):
                try:
                    exp = float(self.preview_exp_var.get())
                except:
                    exp = 0.2
                elapsed = time.time() - self.preview_progress_start_time
                progress = min(100, (elapsed / exp) * 100) if exp > 0 else 100
                self.preview_progress['value'] = progress
                
            if os.path.exists('/tmp/zwo_sharpness.txt'):
                mtime = os.path.getmtime('/tmp/zwo_sharpness.txt')
                with open('/tmp/zwo_sharpness.txt', 'r') as f:
                    txt = f.read().strip()
                if txt:
                    score = float(txt)
                    self.sharpness_lbl.config(text=f"Focus Score: {score:.1f}")
                    
                    if getattr(self, 'af_running', False):
                        if not hasattr(self, 'af_last_mtime'): self.af_last_mtime = 0
                        if not hasattr(self, 'af_wait_frames'): self.af_wait_frames = 0
                        
                        if mtime > self.af_last_mtime:
                            self.af_last_mtime = mtime
                            if self.af_wait_frames > 0:
                                self.af_wait_frames -= 1
                            else:
                                is_eaf = getattr(self, 'focus_eaf_var', None) and self.focus_eaf_var.get()
                                step_val = 30 if is_eaf else 0.2
                                
                                if self.af_state == 'INIT':
                                    self.af_last_score = score
                                    self.af_dir = -1
                                    self.af_state = 'MOVING'
                                    self.af_step = step_val
                                elif self.af_state == 'MOVING':
                                    if score < self.af_last_score:
                                        self.af_dir *= -1
                                        self.af_step /= 2.0
                                    
                                    self.af_last_score = score
                                    if (is_eaf and self.af_step < 5) or (not is_eaf and self.af_step < 0.05):
                                        self.af_running = False
                                        self.btn_af.config(text="Auto Focus", bg="#c0c0c0")
                                        self.af_state = 'IDLE'
                                
                                if self.af_running:
                                    if is_eaf:
                                        self.af_eaf_move(int(self.af_dir * self.af_step))
                                    else:
                                        if self.af_dir < 0: self.af_mega_in()
                                        else: self.af_mega_out()
                                        self.after(int(self.af_step * 1000), self.af_mega_stop)
                                    self.af_wait_frames = 2
        except Exception:
            pass
        self.after(100, self.update_preview_stream)

    def apply_config_to_arduino(self):
        if not self.is_connected or not self.ser:
            return

        try:
            mt = self.mount_type_var.get()
            steps = int(self.steps_entry.get())
            microstep = int(self.microstep_var.get())
            graz = float(self.gear_az_entry.get())
            gralt = float(self.gear_alt_entry.get())
            lat = float(self.lat_entry.get())
            lon = float(self.lon_entry.get())
            speed = float(self.speed_scale.get())
            buzzer = self.buzzer_var.get()
            rev_az = self.rev_az_var.get()
            rev_alt = self.rev_alt_var.get()
            p_alt = float(self.park_alt_entry.get())
            p_az = float(self.park_az_entry.get())
        except ValueError:
            messagebox.showerror("Input Error", "Please enter valid numerical values for gear ratios and coordinates.")
            return

        try:
            tmc_spi = self.tmc_spi_var.get()
            tmc_stealth = self.tmc_stealth_var.get()
            tmc_hold = int(self.tmc_hold_entry.get())
            tmc_current = [int(e.get()) for e in self.tmc_current_entries]
            tmc_ms_derot = int(self.tmc_ms_derot_var.get())
            tmc_ms_focus = int(self.tmc_ms_focus_var.get())
            if not (0 <= tmc_hold <= 100) or any(not (100 <= c <= 3000) for c in tmc_current):
                raise ValueError
        except ValueError:
            messagebox.showerror("Input Error", "TMC5160 : courant de 100 à 3000 mA, maintien de 0 à 100 %.")
            return

        try:
            # Send Mount Type
            if mt == "AltAz":
                mt_cmd = "BMa"
            elif mt == "ForkEq":
                mt_cmd = "BMe"
            else:
                mt_cmd = "BMg"
            self.ser.write(f":{mt_cmd}#".encode('ascii'))
            self.ser.read_until(b"#")

            # Send Motor Steps/Rev
            self.ser.write(f":BSp{steps}#".encode('ascii'))
            self.ser.read_until(b"#")

            # Send Microstepping
            self.ser.write(f":BSm{microstep}#".encode('ascii'))
            self.ser.read_until(b"#")

            # Send AZ Gear Ratio
            self.ser.write(f":BGa{graz}#".encode('ascii'))
            self.ser.read_until(b"#")

            # Send ALT Gear Ratio
            self.ser.write(f":BGe{gralt}#".encode('ascii'))
            self.ser.read_until(b"#")

            # Send Latitude
            lat_str = self.format_lat_lx(lat)
            self.ser.write(f":St{lat_str}#".encode('ascii'))
            self.ser.read(1)

            # Send Longitude
            lon_str = self.format_lon_lx(lon)
            self.ser.write(f":Sg{lon_str}#".encode('ascii'))
            self.ser.read(1)

            # Send Slew speed
            n_speed = max(5, min(250, int(speed * 10)))
            self.ser.write(f":BV {n_speed}#".encode('ascii'))
            self.ser.read_until(b"#")

            # Send Buzzer status
            buzz_cmd = ":Bb1#" if buzzer else ":Bb0#"
            self.ser.write(buzz_cmd.encode('ascii'))
            self.ser.read_until(b"#")

            # Send AZ direction inversion
            self.ser.write(f":BRa{1 if rev_az else 0}#".encode('ascii'))
            self.ser.read_until(b"#")
            # Send ALT direction inversion
            self.ser.write(f":BRe{1 if rev_alt else 0}#".encode('ascii'))
            self.ser.read_until(b"#")

            # Send Park Alt
            self.ser.write(f":BPa{p_alt}#".encode('ascii'))
            self.ser.read_until(b"#")

            # Send Park Az
            self.ser.write(f":BPz{p_az}#".encode('ascii'))
            self.ser.read_until(b"#")

            # Focuseur pilote par la monture (sans :XFe1, le firmware ignore :XF+/:XF-)
            self.ser.write(f":XFe{1 if self.focus_mega_var.get() else 0}#".encode('ascii'))
            self.ser.read(1)

            # Drivers TMC5160 (firmware Teensy ; le Mega repond "0#" a :XTS#)
            tmc_state = None
            if self._tmc_status():
                self._tmc_query(f":XFS{1 if tmc_spi else 0}#")
                for ax, mA in zip(TMC_AXES, tmc_current):
                    self._tmc_query(f":XTI{ax}{mA}#")
                self._tmc_query(f":XTH{tmc_hold}#")
                self._tmc_query(f":XTP{1 if tmc_stealth else 0}#")
                self._tmc_query(f":XTMd{tmc_ms_derot}#")
                self._tmc_query(f":XTMf{tmc_ms_focus}#")
                tmc_state = self._tmc_status()
            self._tmc_show_state(tmc_state)

            # Update local settings
            self.settings["tmc_spi"] = tmc_spi
            self.settings["tmc_stealth"] = tmc_stealth
            self.settings["tmc_hold"] = tmc_hold
            self.settings["tmc_current"] = tmc_current
            self.settings["tmc_ms_derot"] = tmc_ms_derot
            self.settings["tmc_ms_focus"] = tmc_ms_focus
            self.settings["mount_type"] = mt
            self.settings["steps_per_rev_motor"] = steps
            self.settings["microstep"] = microstep
            self.settings["gear_ratio_az"] = graz
            self.settings["gear_ratio_alt"] = gralt
            self.settings["obs_lat"] = lat
            self.settings["obs_lon"] = lon
            self.settings["slew_speed"] = speed
            self.settings["buzzer_on"] = buzzer
            self.settings["rev_az"] = rev_az
            self.settings["rev_alt"] = rev_alt
            self.settings["park_alt"] = p_alt
            self.settings["park_az"] = p_az
            self.settings["focus_mega_en"] = self.focus_mega_var.get()
            self.settings["focus_eaf_en"] = self.focus_eaf_var.get()
            self.settings["derot_mega_en"] = self.derot_mega_var.get()
            self.settings["derot_zwo_en"] = self.derot_zwo_var.get()
            try:
                self.settings["derot_mega_ppd"] = float(self.derot_ppd_entry.get())
            except ValueError:
                pass
            
            if self.derot_zwo_var.get():
                self.settings["derot_port"] = "ZWO_SDK"
                
            self.settings["astrometry_enabled"] = self.astro_en_var.get()
            try:
                self.settings["astro_cam_idx"] = self.get_selected_camera_idx()
                self.settings["astro_exp"] = float(self.exp_entry.get())
                self.settings["astro_gain"] = int(self.gain_entry.get())
                self.settings["astro_focal"] = float(self.foc_entry.get())
                self.settings["astro_pixel"] = float(self.px_entry.get())
                self.settings["astro_width"] = float(self.width_entry.get())
                self.settings["astro_blind"] = self.blind_var.get()
                self.settings["astro_auto_gain"] = self.auto_gain_var.get()
            except ValueError:
                pass
            self.save_local_settings()

            messagebox.showinfo("Apply Config", "Configuration successfully saved to the mount!")
        except Exception as e:
            self.handle_serial_error(e)

    def _tmc_query(self, cmd):
        """Envoie une commande TMC5160 (:XT / :XFS) et renvoie la réponse sans le '#'."""
        self.ser.write(cmd.encode('ascii'))
        return self.ser.read_until(b"#").decode('ascii', errors='ignore').strip().strip('#')

    def _tmc_status(self):
        """Réponse de :XTS# découpée ("1,1,1,0,0" -> 5 champs), ou None si non supporté."""
        parts = self._tmc_query(":XTS#").split(",")
        return parts if len(parts) == 5 else None

    def _tmc_show_state(self, parts):
        if not parts:
            txt = "État : non supporté (firmware Mega ?)"
        else:
            txt = "État : " + "  ".join(f"{n} {TMC_STATE_TEXT.get(c, c)}"
                                         for n, c in zip(("AZ", "ALT", "DER", "FOC"), parts[1:]))
        self.tmc_status_lbl.config(text=txt)

    def handle_serial_error(self, e):
        messagebox.showerror("Serial Error", f"Error during serial communication:\n{e}")
        self.is_connected = False
        if self.ser:
            try:
                self.ser.close()
            except:
                pass
            self.ser = None
        self.update_connection_status()

    def find_arduino_cli(self):
        import shutil
        cli = shutil.which("arduino-cli")
        if cli:
            return cli
        local_path = Path.home() / ".local" / "bin" / "arduino-cli"
        if local_path.exists():
            return str(local_path)
        return None

    def open_flash_dialog(self):
        flash_top = tk.Toplevel(self)
        flash_top.title("Mise à jour du Firmware")
        flash_top.geometry("400x320")
        flash_top.configure(bg="#c0c0c0")
        flash_top.resizable(False, False)
        
        lbl_port = tk.Label(flash_top, text="1. Choisissez le port série de la carte :", font=("Arial", 11, "bold"), bg="#c0c0c0")
        lbl_port.pack(pady=(20, 5))
        
        from tkinter import ttk
        import serial.tools.list_ports
        ports = [p.device for p in serial.tools.list_ports.comports()]
        port_combo = ttk.Combobox(flash_top, values=ports, state="readonly", width=30)
        if self.port_var.get() in ports:
            port_combo.set(self.port_var.get())
        elif ports:
            port_combo.set(ports[0])
        port_combo.pack(pady=5)
        
        lbl_carte = tk.Label(flash_top, text="2. Quelle carte souhaitez-vous flasher ?", font=("Arial", 11, "bold"), bg="#c0c0c0")
        lbl_carte.pack(pady=(20, 10))
        
        btn_frame = tk.Frame(flash_top, bg="#c0c0c0")
        btn_frame.pack(fill="x", pady=10)
        
        def choose_mega():
            selected_port = port_combo.get()
            if not selected_port:
                messagebox.showerror("Erreur", "Veuillez sélectionner un port.")
                return
            flash_top.destroy()
            self.flash_firmware("mega_monture", selected_port)
            
        def choose_teensy_monture():
            selected_port = port_combo.get()
            if not selected_port:
                messagebox.showerror("Erreur", "Veuillez sélectionner un port.")
                return
            flash_top.destroy()
            self.flash_firmware("teensy_monture", selected_port)
            
        def choose_teensy_raquette():
            selected_port = port_combo.get()
            if not selected_port:
                messagebox.showerror("Erreur", "Veuillez sélectionner un port.")
                return
            flash_top.destroy()
            self.flash_firmware("teensy_raquette", selected_port)
            
        btn_m = tk.Button(btn_frame, text="Mega 2560 (Monture)", font=("Arial", 11), command=choose_mega)
        btn_m.pack(side="top", pady=5, fill="x", padx=40)
        if self.hw_code != "none":
            btn_m.config(state="disabled")   # les deux PCB monture portent un Teensy 4.1
        
        btn_tm = tk.Button(btn_frame, text="Teensy 4.1 (Monture)", font=("Arial", 11), command=choose_teensy_monture)
        btn_tm.pack(side="top", pady=5, fill="x", padx=40)
        
        btn_t = tk.Button(btn_frame, text="Teensy 4.1 (Raquette)", font=("Arial", 11), command=choose_teensy_raquette)
        btn_t.pack(side="top", pady=5, fill="x", padx=40)

    def flash_firmware(self, target, flash_port):
        cli = self.find_arduino_cli()
        lang = self.settings.get("language", "fr")
        t = TRANSLATIONS[lang]
        
        if not cli:
            messagebox.showerror(t["flashing_title"], t["cli_not_found"])
            return

        if self.is_connected:
            self.toggle_connection()

        import subprocess
        script_dir = Path(__file__).parent
        
        if target == "mega_monture":
            sketch_path = script_dir / "mega_monture"
            fqbn = "arduino:avr:mega"
            additional_args = []
        elif target == "teensy_monture":
            sketch_path = script_dir / "teensy_monture"
            fqbn = "teensy:avr:teensy41"
            additional_args = ["--additional-urls", "https://www.pjrc.com/teensy/package_teensy_index.json"]
        else: # teensy_raquette
            sketch_path = script_dir / "teensy_raquette"
            fqbn = "teensy:avr:teensy41"
            additional_args = ["--additional-urls", "https://www.pjrc.com/teensy/package_teensy_index.json"]

        # Disable button temporarily during flash
        self.flash_btn.config(state="disabled")
        
        # Show waiting window
        from tkinter import ttk
        wait_top = tk.Toplevel(self)
        wait_top.title("Flash en cours...")
        wait_top.geometry("350x120")
        wait_top.configure(bg="#c0c0c0")
        wait_top.resizable(False, False)
        wait_top.protocol("WM_DELETE_WINDOW", lambda: None) # Prevent closing
        
        lbl_w = tk.Label(wait_top, text="Compilation et Flash en cours...\nVeuillez patienter.", font=("Arial", 11), bg="#c0c0c0")
        lbl_w.pack(pady=15)
        
        pb = ttk.Progressbar(wait_top, mode="indeterminate", length=250)
        pb.pack(pady=5)
        pb.start(15)
        
        self.update()

        def run_flash():
            try:
                # 0. Update from GitHub first
                res_pull = subprocess.run(["git", "pull"], cwd=str(script_dir), capture_output=True, text=True, timeout=30)
                if res_pull.returncode != 0:
                    print("Git pull failed: " + res_pull.stderr)
                    
                # 1. Compile
                compile_cmd = [cli, "compile", "--fqbn", fqbn] + additional_args + [str(sketch_path)]
                res_comp = subprocess.run(compile_cmd, capture_output=True, text=True, timeout=120)
                if res_comp.returncode != 0:
                    self.after(0, lambda err=res_comp.stderr, out=res_comp.stdout: messagebox.showerror(t["flashing_title"], t["flashing_error"] + err + "\n\n" + out))
                    return

                # 2. Upload
                upload_cmd = [cli, "upload", "-p", flash_port, "--fqbn", fqbn] + additional_args + [str(sketch_path)]
                res_upl = subprocess.run(upload_cmd, capture_output=True, text=True, timeout=90)
                if res_upl.returncode != 0:
                    self.after(0, lambda err=res_upl.stderr, out=res_upl.stdout: messagebox.showerror(t["flashing_title"], t["flashing_error"] + err + "\n\n" + out))
                    return

                self.after(0, lambda: messagebox.showinfo(t["flashing_title"], t["flashing_success"]))
            except Exception as e:
                self.after(0, lambda err=str(e): messagebox.showerror(t["flashing_title"], t["flashing_error"] + err))
            finally:
                self.after(0, lambda: wait_top.destroy())
                self.after(0, lambda: self.flash_btn.config(state="normal"))

        import threading
        threading.Thread(target=run_flash, daemon=True).start()

if __name__ == "__main__":
    app = ConfigToolApp()
    app.mainloop()

