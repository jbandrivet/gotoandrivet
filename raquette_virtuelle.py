#!/usr/bin/env python3
# Auteur : Andrivet Jean-Baptiste
import tkinter as tk
import tactile_wayland

import serial
import serial.tools.list_ports
import time
import math
import sys
import os
from datetime import datetime, timezone

# Ajouter le répertoire courant au chemin d'importation
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from goto_andrivet import ALL_CATALOGS, Astro, Settings
import ephem

class VirtualTeensyApp(tk.Tk):
    def __init__(self):
        super().__init__()
        # Charger les paramètres globaux (coordonnées GPS du site)
        self.cfg = Settings()
        lang = self.cfg.get("language", "fr")
        if lang == "en":
            self.title("Virtual T4.1 Hand Controller")
        else:
            self.title("Raquette T4.1 Virtuelle")
        self.geometry("420x620")
        self.configure(bg="#c0c0c0")
        self.resizable(False, False)
        
        self.lat = self.cfg.get("latitude", 45.764)
        self.lon = self.cfg.get("longitude", 4.836)
        self.alt_min = self.cfg.get("alt_min_deg", 2.0)
        
        # Connexion série
        self.ser = None
        self.port = ""
        self.sim_mode = False
        
        # Coordonnées simulées (utilisées si sim_mode est True)
        self.sim_ra = 12.0      # Heures
        self.sim_dec = 45.0     # Degrés
        self.sim_slewing = False
        self.sim_tracking = True
        
        # Variables de télémétrie courantes (affichées à l'écran)
        self.current_ra = "12:00:00"
        self.current_dec = "+45*00:00"
        self.current_alt = 0.0
        self.current_az = 0.0
        self.is_slewing = False
        self.target_ra = None
        self.target_dec = None
        
        # Chargement de la base de données céleste
        self.db_cat = {}
        self.load_db()
        
        # États de l'interface graphique (raquette)
        self.UI_MAIN = 0
        self.UI_CAT_SELECT = 1
        self.UI_OBJECT_LIST = 2
        self.UI_OBJECT_INFO = 3
        self.UI_SLEWING = 4
        self.UI_SETTINGS = 5
        self.UI_SPEED = 6
        self.UI_MESSAGE = 7
        self.UI_BEEP = 8
        self.UI_MOTOR_POWER = 9
        self.UI_LANGUAGE = 10
        self.UI_MOUNT = 11
        self.UI_RATIO_AZ = 12
        self.UI_RATIO_ALT = 13
        self.UI_ALIGN_CENTER = 14
        self.UI_GPS = 15
        self.UI_EDIT_TIME = 16
        self.UI_EDIT_LOCATION = 17
        
        self.motor_power = True
        self.temp_motor_power = True
        self.temp_gps_enabled = True
        self.temp_lang = "fr"
        self.temp_mount_type = 0
        self.temp_ratio_az = self.cfg.get("gear_ratio_az", 750.0)
        self.temp_ratio_alt = self.cfg.get("gear_ratio_alt", 750.0)
        
        self.state = self.UI_MAIN
        self.is_align_workflow = False
        self.is_parking_workflow = False
        
        self.catalogs = ["Messier", "NGC", "IC", "Caldwell", "Systeme Solaire", "Étoiles", "ISS"]
        self.cat_idx = 0
        
        self.obj_list = []
        self.obj_idx = 0
        self.current_cat_name = None
        
        self.settings_sel = 0
        self.current_speed = 2.0
        self.buzzer_on = True
        self.temp_speed = 2.0
        self.temp_buzzer_on = True
        
        self.msg_until = 0
        self.msg_return_state = 0
        self.is_connected = False
        
        # File d'attente pour commandes asynchrones (GoTo)
        self.cmd_queue = []
        
        # États des touches clavier / boutons souris pour le déplacement continu (slew)
        self.press_active = {"UP": False, "DOWN": False, "LEFT": False, "RIGHT": False}
        self.key_release_timers = {"UP": None, "DOWN": None, "LEFT": None, "RIGHT": None}
        
        # Construction de l'interface graphique
        self.build_ui()
        
        # Bindings clavier locaux et globaux (pour garantir la capture sous tout gestionnaire de fenêtres)
        self.bind("<KeyPress>", self.on_key_press)
        self.bind("<KeyRelease>", self.on_key_release)
        self.bind_all("<KeyPress>", self.on_key_press)
        self.bind_all("<KeyRelease>", self.on_key_release)
        
        # Liaison clavier supplémentaire sur tous les boutons pour intercepter les touches s'ils prennent le focus
        for btn in (self.b_up, self.b_down, self.b_left, self.b_right):
            btn.bind("<KeyPress>", self.on_key_press)
            btn.bind("<KeyRelease>", self.on_key_release)
        
        # Permettre le défilement par molette de souris sur l'application
        self.bind("<MouseWheel>", self.on_mouse_wheel)  # Windows/macOS
        self.bind("<Button-4>", self.on_mouse_wheel)    # Linux scroll up
        self.bind("<Button-5>", self.on_mouse_wheel)    # Linux scroll down
        
        # Forcer le rendu de la fenêtre et réclamer le focus clavier immédiatement après affichage
        self.update()
        self.focus_force()
        self.after(150, lambda: self.focus_set())
        
        # Démarrage des boucles d'arrière-plan
        self.check_connection_loop()
        self.telemetry_loop()
        self.update_lcd()

    def load_db(self):
        try:
            now = datetime.now(timezone.utc)
            obs = ephem.Observer()
            obs.lat = str(self.lat)
            obs.lon = str(self.lon)
            obs.date = now
            
            planets = [
                ("Soleil", ephem.Sun()),
                ("Lune", ephem.Moon()),
                ("Mercure", ephem.Mercury()),
                ("Venus", ephem.Venus()),
                ("Mars", ephem.Mars()),
                ("Jupiter", ephem.Jupiter()),
                ("Saturne", ephem.Saturn()),
                ("Uranus", ephem.Uranus()),
                ("Neptune", ephem.Neptune()),
            ]
            
            sys_sol = []
            for i, (name, p) in enumerate(planets):
                p.compute(obs)
                ra = float(p.ra) * 12.0 / math.pi
                dec = float(p.dec) * 180.0 / math.pi
                mag = getattr(p, 'mag', 0)
                sys_sol.append({"id": i, "ra": ra, "dec": dec, "mag": round(mag,1), "type": "Planete", "name": name, "cat": "SysSol", "num": name})
                
            self.db_cat = {}
            for k, v in ALL_CATALOGS.items():
                self.db_cat[k] = v
            self.db_cat["Systeme Solaire"] = sys_sol
            
        except Exception as e:
            print(f"Erreur chargement base de donnees: {e}")
            self.db_cat = {}
            self.catalogs = ["Erreur DB"]

    def build_ui(self):
        # Fonts
        
        f_label = ("MS Sans Serif", 9)
        f_lcd = ("Courier New", 13, "bold")
        
        # Main window inner container with a 3D sunken border
        main_border = tk.Frame(self, bg="#c0c0c0", bd=2, relief="raised")
        main_border.pack(fill="both", expand=True, padx=4, pady=(0, 4))

        main_container = tk.Frame(main_border, bg="#c0c0c0")
        main_container.pack(fill="both", expand=True, padx=10, pady=10)

        # Connection status in a sunken box
        conn_frame = tk.Frame(main_container, bg="white", bd=2, relief="sunken", height=24)
        conn_frame.pack(fill="x", pady=(0, 5))
        conn_frame.pack_propagate(False)
        self.conn_lbl = tk.Label(conn_frame, text="Connexion monture", bg="white", fg="red", font=f_label, anchor="w", padx=5)
        self.conn_lbl.pack(fill="both", expand=True)
        
        # Boîtier de l'écran LCD (sunken border)
        lcd_case = tk.Frame(main_container, bg="#c0c0c0", bd=2, relief="sunken")
        lcd_case.pack(pady=10, fill="x")
        
        # Écran LCD matriciel retro couleur (simule Grove RGB)
        self.lcd_frame = tk.Frame(lcd_case, bg="#ff0000", padx=10, pady=10)
        self.lcd_frame.pack(fill="both", expand=True)
        
        self.lcd_lines = []
        for i in range(4):
            lbl = tk.Label(
                self.lcd_frame, 
                text=" "*20, 
                bg="#ff0000", 
                fg="#000000", 
                font=f_lcd, 
                width=20, 
                anchor="w", 
                padx=2, 
                pady=1
            )
            lbl.pack(fill="x")
            self.lcd_lines.append(lbl)
            
        # Clavier physique (Boutons)
        pad_frame = tk.Frame(main_container, bg="#c0c0c0")
        pad_frame.pack(pady=10, fill="both", expand=True)
        
        # Grid D-Pad (Direction)
        dpad_container = tk.Frame(pad_frame, bg="#c0c0c0")
        dpad_container.pack(side="top", pady=5)
        
        # Décoration D-Pad
        dpad_bg = tk.Frame(dpad_container, bg="#c0c0c0", bd=2, relief="sunken")
        dpad_bg.pack(padx=5, pady=5)
        
        # Boutons D-Pad
        btn_style = {
            "font": ("MS Sans Serif", 12, "bold"),
            "bg": "#c0c0c0",
            "fg": "black",
            "activebackground": "#d9d9d9",
            "activeforeground": "black",
            "bd": 2,
            "relief": tk.RAISED,
            "width": 4,
            "height": 2,
            "highlightthickness": 0,
            "takefocus": False
        }
        
        # UP
        self.b_up = tk.Button(dpad_bg, text="▲", **btn_style)
        self.b_up.grid(row=0, column=1, padx=4, pady=4)
        
        # LEFT
        self.b_left = tk.Button(dpad_bg, text="◀", **btn_style)
        self.b_left.grid(row=1, column=0, padx=4, pady=4)
        
        # CENTER (Bouton central faisant office de touche validation ENTER)
        self.b_center = tk.Button(dpad_bg, text="◆", **btn_style)
        self.b_center.configure(command=lambda: self.handle_btn("ENTER"))
        self.b_center.grid(row=1, column=1, padx=4, pady=4)
        
        # RIGHT
        self.b_right = tk.Button(dpad_bg, text="▶", **btn_style)
        self.b_right.grid(row=1, column=2, padx=4, pady=4)
        
        # DOWN
        self.b_down = tk.Button(dpad_bg, text="▼", **btn_style)
        self.b_down.grid(row=2, column=1, padx=4, pady=4)
        
        # Liaison des événements souris (clic et relâchement) pour le déplacement manuel
        self.b_up.bind("<ButtonPress-1>", lambda e: self.on_press("UP"))
        self.b_up.bind("<ButtonRelease-1>", lambda e: self.on_release("UP"))
        
        self.b_down.bind("<ButtonPress-1>", lambda e: self.on_press("DOWN"))
        self.b_down.bind("<ButtonRelease-1>", lambda e: self.on_release("DOWN"))
        
        self.b_left.bind("<ButtonPress-1>", lambda e: self.on_press("LEFT"))
        self.b_left.bind("<ButtonRelease-1>", lambda e: self.on_release("LEFT"))
        
        self.b_right.bind("<ButtonPress-1>", lambda e: self.on_press("RIGHT"))
        self.b_right.bind("<ButtonRelease-1>", lambda e: self.on_release("RIGHT"))
        
        # Ajout d'effet hover interactif pour les boutons
        for btn in (self.b_up, self.b_down, self.b_left, self.b_right, self.b_center):
            btn.bind("<Enter>", lambda e, b=btn: self.on_btn_hover(b))
            btn.bind("<Leave>", lambda e, b=btn: self.on_btn_leave(b))
            
        # Signature
        author_lbl = tk.Label(main_container, text="Créé par Andrivet Jean-Baptiste", font=("Helvetica", 8, "italic"), bg="#c0c0c0", fg="#555555")
        author_lbl.pack(side="bottom", anchor="se", pady=(5, 0), padx=5)

    def on_btn_hover(self, btn):
        btn.configure(bg="#d9d9d9")

    def on_btn_leave(self, btn):
        btn.configure(bg="#c0c0c0")

    # Mappage des touches du clavier PC (insensible à la casse)
    def keysym_to_btn(self, keysym):
        k = keysym.lower()
        if k == "up": return "UP"
        if k == "down": return "DOWN"
        if k == "left": return "LEFT"
        if k == "right": return "RIGHT"
        if k in ("return", "kp_enter", "space", "enter"): return "ENTER"
        if k in ("escape", "backspace"): return "BACK"
        return None

    def on_key_press(self, event):
        btn = self.keysym_to_btn(event.keysym)
        if not btn: return
        
        # Si c'est une touche de direction
        if btn in ("UP", "DOWN", "LEFT", "RIGHT"):
            if self.state == self.UI_MAIN:
                # Annuler le timer de relâchement s'il y en a un (anti-rebond du repeat OS)
                if self.key_release_timers[btn] is not None:
                    self.after_cancel(self.key_release_timers[btn])
                    self.key_release_timers[btn] = None
                
                # Déclencher l'action si elle n'est pas déjà active
                if not self.press_active[btn]:
                    self.on_press(btn)
            else:
                # Dans les menus, la navigation se fait par impulsion simple
                if not self.press_active[btn]:
                    self.press_active[btn] = True
                    self.handle_btn(btn)
        elif btn == "ENTER":
            self.handle_btn("ENTER")
        elif btn == "BACK":
            self.handle_btn("LEFT")
            
        return "break"

    def on_key_release(self, event):
        btn = self.keysym_to_btn(event.keysym)
        if not btn: return
        
        if btn in ("UP", "DOWN", "LEFT", "RIGHT"):
            if self.state == self.UI_MAIN:
                # Anti-rebond (debounce) : attend 50ms pour confirmer le relâchement réel
                if self.key_release_timers[btn] is not None:
                    self.after_cancel(self.key_release_timers[btn])
                self.key_release_timers[btn] = self.after(50, lambda b=btn: self.trigger_key_release(b))
            else:
                self.press_active[btn] = False
                
        return "break"

    def trigger_key_release(self, btn):
        self.key_release_timers[btn] = None
        self.on_release(btn)

    def on_mouse_wheel(self, event):
        # Gestion du scroll molette souris sur les listes (Catalogs, Objects, Settings)
        if self.state in (self.UI_CAT_SELECT, self.UI_OBJECT_LIST, self.UI_SETTINGS):
            if event.num == 4 or event.delta > 0:
                self.handle_btn("UP")
            elif event.num == 5 or event.delta < 0:
                self.handle_btn("DOWN")

    def check_connection_loop(self):
        if not hasattr(self, 'conn_state'):
            self.conn_state = "disconnected"
            self.conn_start_time = 0
            self.conn_port = ""

        if not self.is_connected:
            if self.conn_state == "disconnected":
                ports = serial.tools.list_ports.comports()
                
                # Chercher spécifiquement l'Arduino Mega (VID 2341) et éviter la Teensy (VID 16C0)
                mega_ports = [p.device for p in ports if "2341:" in (p.hwid or "")]
                if not mega_ports:
                    # Fallback si clone Arduino avec un autre VID, mais on exclut explicitement la Teensy
                    mega_ports = [p.device for p in ports if ("USB" in p.device or "ACM" in p.device) and "16C0:" not in (p.hwid or "")]
                    
                if mega_ports:
                    port = mega_ports[0]
                    try:
                        self.ser = serial.Serial(port, 38400, timeout=0.5)
                        self.conn_state = "connecting"
                        self.conn_start_time = time.time()
                        self.conn_port = port
                        self.conn_lbl.config(text=f"Connexion: {port}...", fg="#ffcc00")
                    except Exception:
                        if hasattr(self, 'ser') and self.ser:
                            try: self.ser.close()
                            except: pass
                        self.ser = None
                else:
                    # Mode simulation automatique si aucun matériel physique n'est détecté
                    self.is_connected = True
                    self.sim_mode = True
                    self.port = "SIMULATEUR"
                    self.conn_lbl.config(text="Connecte: SIMULATEUR", fg="#00e5ff")
                    self.update_lcd()
            
            elif self.conn_state == "connecting":
                # Attendre 2.2 secondes pour que l'Arduino ait terminé sa phase de reboot
                if time.time() - self.conn_start_time > 2.2:
                    try:
                        self.ser.reset_input_buffer()
                        self.ser.write(b":GVP#")
                        resp = self.ser.read_until(b"#").decode('ascii', errors='ignore')
                        if "OnStep" in resp or "On-Step" in resp or "GotoMega" in resp or resp.strip():
                            self.is_connected = True
                            self.sim_mode = False
                            self.port = self.conn_port
                            self.conn_lbl.config(text=f"Connecte: {self.conn_port}", fg="#39ff14")
                            self.conn_state = "connected"
                            self.sync_clock()
                            self.update_lcd()
                        else:
                            self.ser.close()
                            self.ser = None
                            self.conn_state = "disconnected"
                    except Exception:
                        if self.ser:
                            try: self.ser.close()
                            except: pass
                        self.ser = None
                        self.conn_state = "disconnected"

        # Relancer la boucle toutes les 250ms pendant la phase de connexion pour rester réactif
        if not self.is_connected or self.conn_state == "connecting":
            self.after(250, self.check_connection_loop)
        elif not self.sim_mode:
            self.after(2000, self.check_connection_loop)

    def sync_clock(self):
        if self.is_connected and self.ser and not self.sim_mode:
            try:
                now = datetime.now()
                # 1. Date
                self.ser.write(f":SC{now.month:02d}/{now.day:02d}/{now.year%100:02d}#".encode('ascii'))
                self.ser.read_until(b"#")
                
                # 2. Time
                self.ser.write(f":SL{now.hour:02d}:{now.minute:02d}:{now.second:02d}#".encode('ascii'))
                self.ser.read_until(b"#")
                
                # 3. Timezone
                utc_offset = -time.timezone / 3600.0
                if time.daylight and time.localtime().tm_isdst:
                    utc_offset = -time.altzone / 3600.0
                # :SG (LX200) : heures à ajouter à l'heure locale pour obtenir l'UTC, donc UTC+2 -> :SG-02
                sign = '-' if utc_offset >= 0 else '+'
                self.ser.write(f":SG{sign}{int(abs(utc_offset)):02d}#".encode('ascii'))
                self.ser.read_until(b"#")
                
                # 3.5 Sync Mechanical Settings FROM Mega to PC
                self.ser.write(b":BGa#")
                time.sleep(0.05)
                if self.ser.in_waiting:
                    try:
                        self.temp_ratio_az = float(self.ser.read_until(b"#").decode('ascii', errors='ignore').strip('#'))
                        self.cfg.set("gear_ratio_az", self.temp_ratio_az)
                    except: pass
                
                self.ser.write(b":BGe#")
                time.sleep(0.05)
                if self.ser.in_waiting:
                    try:
                        self.temp_ratio_alt = float(self.ser.read_until(b"#").decode('ascii', errors='ignore').strip('#'))
                        self.cfg.set("gear_ratio_alt", self.temp_ratio_alt)
                    except: pass
                    
                self.ser.write(b":Bb#")
                time.sleep(0.05)
                if self.ser.in_waiting:
                    try: self.buzzer_on = (int(self.ser.read_until(b"#").decode('ascii', errors='ignore').strip('#')) > 0)
                    except: pass
                    
                self.cfg.save()
                
                
                # 4. Slew speed
                self.ser.write(b":Bv#")
                time.sleep(0.1)
                if self.ser.in_waiting:
                    speed_raw = self.ser.read_until(b"#").decode('ascii', errors='ignore').strip('#')
                    try:
                        self.current_speed = int(speed_raw) / 10.0
                        print(f"Slew speed synchronized from Arduino EEPROM: {self.current_speed} deg/s")
                    except:
                        pass
                
                # Vider le tampon de réception
                if self.ser.in_waiting:
                    self.ser.read(self.ser.in_waiting)
                    
                # 5. Sync Mount Type
                self.ser.write(b":GM#")
                time.sleep(0.1)
                if self.ser.in_waiting:
                    gm = self.ser.read_until(b"#").decode('ascii', errors='ignore').strip('#')
                    if "AltAz" in gm:
                        self.cfg.set("mount_type", "AltAz")
                    elif "ForkEq" in gm:
                        self.cfg.set("mount_type", "ForkEq")
                    elif "GermanEq" in gm:
                        self.cfg.set("mount_type", "GermanEq")
                    self.cfg.save()

                print("PC clock synchronized with Arduino OnStep.")
            except Exception as e:
                print(f"Error synchronizing clock: {e}")

    def telemetry_loop(self):
        if self.is_connected:
            import time
            import math
            import ephem
            if getattr(self, 'pending_iss_track_time', 0) > 0 and time.time() >= self.pending_iss_track_time:
                self.pending_iss_track_time = 0
                self.iss_tracking_active = True
                if not self.sim_mode:
                    try: self.ser.write(b":Te#")
                    except: pass
                lang = self.cfg.get("language", "fr")
                self.set_msg(" SUIVI ISS... " if lang=="fr" else " TRACKING ISS... ", "", "", "", 2000, self.UI_MAIN)
            if getattr(self, 'iss_tracking_active', False) and getattr(self, 'iss_obj', None) and getattr(self, 'iss_obs', None):
                self.iss_obs.date = ephem.now()
                self.iss_obj.compute(self.iss_obs)
                if float(self.iss_obj.alt) > 0:
                    t_ra = float(self.iss_obj.ra) * 12.0 / math.pi
                    t_dec = float(self.iss_obj.dec) * 180.0 / math.pi
                    if not self.sim_mode:
                        try:
                            self.ser.write(f":Sr{Astro.fmt_ra_lx(t_ra)}#".encode())
                            self.ser.write(f":Sd{Astro.fmt_dec_lx(t_dec)}#".encode())
                            self.ser.write(b":MS#")
                        except: pass
                    else:
                        self.target_ra = t_ra
                        self.target_dec = t_dec
                        self.is_slewing = True
                else:
                    self.iss_tracking_active = False
            
            if self.sim_mode:
                # Boucle de simulation locale de la monture
                if self.is_slewing and self.target_ra is not None:
                    # Distances par axe, en DEGRÉS (AD ×15), les 2 axes bougent en parallèle
                    dra_deg = (self.target_ra - self.sim_ra) * 15.0
                    if dra_deg > 180.0: dra_deg -= 360.0
                    elif dra_deg < -180.0: dra_deg += 360.0
                    ddec_deg = self.target_dec - self.sim_dec
                    
                    step_deg = self.current_speed * 0.5   # tick réel = 500ms
                    axis_max = max(abs(dra_deg), abs(ddec_deg))  # axe le plus long = facteur limitant
                    
                    if axis_max <= step_deg:
                        self.sim_ra = self.target_ra
                        self.sim_dec = self.target_dec
                        self.is_slewing = False
                        if self.state == self.UI_SLEWING:
                            self.state = self.UI_MAIN
                    else:
                        ratio = step_deg / axis_max
                        self.sim_ra = (self.sim_ra + (dra_deg * ratio) / 15.0) % 24.0
                        self.sim_dec = max(-90.0, min(90.0, self.sim_dec + (ddec_deg * ratio)))
                
                # Déplacement manuel continu simulé
                man_step = 0.5 # Degrés par pas de 100ms
                if self.press_active["UP"]: self.sim_dec = min(90.0, self.sim_dec + man_step)
                if self.press_active["DOWN"]: self.sim_dec = max(-90.0, self.sim_dec - man_step)
                if self.press_active["LEFT"]: self.sim_ra = (self.sim_ra + man_step/15.0) % 24.0
                if self.press_active["RIGHT"]: self.sim_ra = (self.sim_ra - man_step/15.0) % 24.0
                
                # Formatage des données de simulation
                self.current_ra = Astro.fmt_ra_lx(self.sim_ra)
                self.current_dec = Astro.fmt_dec_lx(self.sim_dec)
                self.update_lcd()
            else:
                # Mode réel série
                if not self.cmd_queue and self.state in (self.UI_MAIN, self.UI_SLEWING):
                    try:
                        self.ser.write(b":GR#")
                        resp = self.ser.read_until(b"#").decode('ascii', errors='ignore').strip('#')
                        if resp: self.current_ra = resp
                        
                        self.ser.write(b":GD#")
                        resp = self.ser.read_until(b"#").decode('ascii', errors='ignore').strip('#')
                        if resp: self.current_dec = resp
                        
                        self.ser.write(b":GBE#")
                        resp = self.ser.read_until(b"#").decode('ascii', errors='ignore').strip('#')
                        if resp:
                            parts = resp.split(',')
                            if len(parts) >= 8:
                                self.is_tracking = (parts[0] == '1')
                                self.is_slewing = (parts[1] == '1')
                                try:
                                    raw_speed = float(parts[3]) / 10.0
                                    ppd = self.cfg.get("gear_ratio_az", 750.0) * self.cfg.get("steps_per_rev_motor", 200) * self.cfg.get("microstep", 125) / 360.0
                                    max_phys_speed = 1000000.0 / (ppd * 35.0) if ppd > 0 else raw_speed
                                    self.current_speed = min(raw_speed, max_phys_speed)
                                    self.current_alt = float(parts[4])
                                    self.current_az = float(parts[5])
                                except ValueError:
                                    pass
                                if self.is_slewing:
                                    if self.state != self.UI_SLEWING:
                                        self.state = self.UI_SLEWING
                                    # Recouvrer les coordonnées cibles depuis le Mega
                                    # Recouvrer les coordonnées cibles depuis le Mega seulement si on ne les connait pas
                                    if getattr(self, 'target_ra', None) is None:
                                        try:
                                            self.ser.write(b":Gr#")
                                            t_ra = self.ser.read_until(b"#").decode('ascii', errors='ignore').strip('#')
                                            if t_ra:
                                                self.target_ra = Astro.parse_ra(t_ra)
                                            
                                            self.ser.write(b":Gd#")
                                            t_dec = self.ser.read_until(b"#").decode('ascii', errors='ignore').strip('#')
                                            if t_dec:
                                                self.target_dec = Astro.parse_dec(t_dec)
                                        except Exception:
                                            pass
                                elif not self.is_slewing and self.state == self.UI_SLEWING:
                                    if getattr(self, "is_align_workflow", False):
                                        self.state = self.UI_ALIGN_CENTER
                                        self.is_align_workflow = False
                                    else:
                                        self.state = self.UI_MAIN
                                        self.is_parking_workflow = False
                                    self.slew_stopwatch_active = False
                        
                        self.update_lcd()
                    except Exception:
                        pass
                
        self.after(500, self.telemetry_loop) # Vitesse de rafraîchissement 500ms pour éviter de saturer l'Arduino
        
    def finish_sim_slew(self):
        self.is_slewing = False
        self.slew_stopwatch_active = False
        if getattr(self, "is_align_workflow", False):
            self.state = self.UI_ALIGN_CENTER
            self.is_align_workflow = False
        else:
            self.state = self.UI_MAIN
            self.is_parking_workflow = False
        self.update_lcd()
        
    def process_queue(self):
        if not self.is_connected: return
        if self.sim_mode:
            is_goto = any(":MS#" in c or ":hP#" in c for c in self.cmd_queue)
            self.cmd_queue.clear()
            if is_goto:
                self.is_slewing = True
                if getattr(self, "is_align_workflow", False) or getattr(self, "is_parking_workflow", False):
                    self.after(3000, self.finish_sim_slew)  # Simulate slew delay
                if self.state != self.UI_MESSAGE:
                    self.state = self.UI_SLEWING
            self.update_lcd()
            return

        if not self.cmd_queue: return
        cmd = self.cmd_queue.pop(0)
        try:
            self.ser.write(cmd.encode('ascii'))
            self.after(150, self.finish_queue_cmd)
        except Exception:
            self.is_connected = False
            self.cmd_queue.clear()

    def finish_queue_cmd(self):
        if not self.is_connected: return
        try:
            if self.ser.in_waiting:
                self.ser.read(self.ser.in_waiting)
        except:
            pass
        if self.cmd_queue:
            self.process_queue()
        else:
            if self.state != self.UI_MESSAGE:
                self.state = self.UI_SLEWING
            self.update_lcd()

    def send_cmd(self, cmd):
        if self.is_connected:
            try:
                while self.ser.in_waiting:
                    self.ser.read()
            except:
                pass
            if self.sim_mode:
                # Traiter les commandes manuelles du simulateur
                if cmd == ":Mn#": self.press_active["UP"] = True
                elif cmd == ":Ms#": self.press_active["DOWN"] = True
                elif cmd == ":Me#": self.press_active["LEFT"] = True
                elif cmd == ":Mw#": self.press_active["RIGHT"] = True
                elif cmd in (":Q#", ":Qn#", ":Qs#", ":Qe#", ":Qw#"):
                    if cmd in (":Q#", ":Qn#"): self.press_active["UP"] = False
                    if cmd in (":Q#", ":Qs#"): self.press_active["DOWN"] = False
                    if cmd in (":Q#", ":Qe#"): self.press_active["LEFT"] = False
                    if cmd in (":Q#", ":Qw#"): self.press_active["RIGHT"] = False
                    self.is_slewing = False
                    self.slew_stopwatch_active = False
            else:
                try:
                    self.ser.write(cmd.encode('ascii'))
                except Exception:
                    self.is_connected = False
                    self.conn_lbl.config(text="Deconnecte", fg="#ff3b30")

    def on_press(self, btn):
        if self.state in (self.UI_MAIN, self.UI_ALIGN_CENTER):
            if self.is_connected:
                if not self.press_active.get(btn, False):
                    self.press_active[btn] = True
                    # Configurer l'aspect visuel pressé du bouton
                    if btn == "UP":
                        self.b_up.configure(relief=tk.SUNKEN, bg="#d9d9d9")
                        self.send_cmd(":Mn#")
                    elif btn == "DOWN":
                        self.b_down.configure(relief=tk.SUNKEN, bg="#d9d9d9")
                        self.send_cmd(":Ms#")
                    elif btn == "LEFT":
                        self.b_left.configure(relief=tk.SUNKEN, bg="#d9d9d9")
                        self.send_cmd(":Me#")
                    elif btn == "RIGHT":
                        self.b_right.configure(relief=tk.SUNKEN, bg="#d9d9d9")
                        self.send_cmd(":Mw#")
        else:
            # Dans les autres états, un clic équivaut à handle_btn
            self.handle_btn(btn)

    def on_release(self, btn):
        if self.state in (self.UI_MAIN, self.UI_ALIGN_CENTER):
            # Rétablir le relief des boutons
            if btn == "UP": self.b_up.configure(relief=tk.RAISED, bg="#c0c0c0")
            elif btn == "DOWN": self.b_down.configure(relief=tk.RAISED, bg="#c0c0c0")
            elif btn == "LEFT": self.b_left.configure(relief=tk.RAISED, bg="#c0c0c0")
            elif btn == "RIGHT": self.b_right.configure(relief=tk.RAISED, bg="#c0c0c0")
            
            if self.is_connected and self.press_active.get(btn, False):
                self.press_active[btn] = False
                if btn == "UP": self.send_cmd(":Qn#")
                elif btn == "DOWN": self.send_cmd(":Qs#")
                elif btn == "LEFT": self.send_cmd(":Qe#")
                elif btn == "RIGHT": self.send_cmd(":Qw#")
        else:
            self.press_active[btn] = False

    def set_msg(self, l0, l1, l2, l3, duration_ms, return_state):
        self.lcd_lines[0].config(text=f"{l0:<20}"[:20])
        self.lcd_lines[1].config(text=f"{l1:<20}"[:20])
        self.lcd_lines[2].config(text=f"{l2:<20}"[:20])
        self.lcd_lines[3].config(text=f"{l3:<20}"[:20])
        
        self.state = self.UI_MESSAGE
        self.msg_return_state = return_state
        self.msg_until = time.time() + duration_ms/1000.0
        self.after(duration_ms, self.check_msg_timeout)
        
    def check_msg_timeout(self):
        if self.state == self.UI_MESSAGE and time.time() >= self.msg_until:
            self.state = self.msg_return_state
            self.update_lcd()


    def update_lcd(self):
        if self.state == self.UI_MESSAGE: return
        
        l0 = l1 = l2 = l3 = " "*20
        lang = self.cfg.get("language", "fr")
        
        if self.state == self.UI_MAIN:
            is_altaz = (self.cfg.get("mount_type", "AltAz") == "AltAz")
            if is_altaz and hasattr(self, 'current_alt') and hasattr(self, 'current_az'):
                az = abs(self.current_az)
                az_d = int(az)
                az_m = int((az - az_d) * 60)
                az_s = int((az - az_d - az_m/60.0) * 3600.0)
                
                alt = abs(self.current_alt)
                alt_d = int(alt)
                alt_m = int((alt - alt_d) * 60)
                alt_s = int((alt - alt_d - alt_m/60.0) * 3600.0)
                
                l0 = f"AZ: {az_d:03d}°{az_m:02d}'{az_s:02d}\""[:20]
                sign = '-' if self.current_alt < 0 else '+'
                l1 = f"AL: {sign}{alt_d:02d}°{alt_m:02d}'{alt_s:02d}\""[:20]
            else:
                ra_parts = self.current_ra.split(':')
                if len(ra_parts) >= 3:
                    ra_str = f"{ra_parts[0]}h{ra_parts[1]}m{ra_parts[2]}s"
                else:
                    ra_str = self.current_ra
                
                dec_str = self.current_dec.replace('*', '°').replace(':', '\'') + '"'
                l0 = f"RA: {ra_str}"[:20]
                l1 = f"DE: {dec_str}"[:20]
            if self.is_connected:
                mnt_type = self.cfg.get("mount_type", "AltAz")
                if mnt_type == "AltAz": mnt_str = "ALTZ"
                elif mnt_type == "ForkEq": mnt_str = "FORK"
                else: mnt_str = "GERM"
                
                if self.sim_mode:
                    stat_str = "SIMULATEUR"
                else:
                    if not getattr(self, "motor_power", True):
                        stat_str = "MOT.OFF"
                    elif getattr(self, "is_slewing", False):
                        stat_str = "GOTO"
                    elif getattr(self, "is_tracking", False):
                        stat_str = "SUIVI"
                    else:
                        stat_str = "STOP"
                        
                stat = f"{mnt_str} - {stat_str}"
                l2 = f"ETAT: {stat}"[:20]
                l3 = "[ENT] = Menu   "[:20]
                
                try:
                    c_ra = Astro.parse_ra(self.current_ra)
                    c_dec = Astro.parse_dec(self.current_dec)
                    if getattr(self, 'target_ra', None) is not None:
                        dist = Astro.angular_dist(c_ra, c_dec, self.target_ra, self.target_dec)
                        if dist > 0.05:
                            l3 = f"Cible dist: {dist:.1f}°"[:20]
                except:
                    pass
                if getattr(self, 'pending_iss_track_time', 0) > 0:
                    rem = int(self.pending_iss_track_time - time.time())
                    if rem > 0:
                        mins, secs = divmod(rem, 60)
                        hrs, mins = divmod(mins, 60)
                        if hrs > 0:
                            l3 = f"ISS:-{hrs}h{mins:02d}m{secs:02d}s".ljust(20)
                        else:
                            l3 = f"ISS:-{mins}m{secs:02d}s".ljust(20)
                elif getattr(self, 'iss_tracking_active', False):
                    l3 = ">>> SUIVI ISS <<<".ljust(20)
            else:
                l2 = "ETAT: HORS LIGNE"[:20]
                l3 = ""[:20]
            
        elif self.state == self.UI_CAT_SELECT:
            l0 = "[ CHOIX CATALOGUE ]" if lang == "fr" else "[ SELECT CATALOG  ]"
            cat_name = self.catalogs[self.cat_idx]
            count = len(self.db_cat.get(cat_name, []))
            disp_cat = cat_name
            if lang == "en":
                if cat_name == "Systeme Solaire": disp_cat = "Solar System"
                elif cat_name == "Étoiles": disp_cat = "Stars"
            l1 = f"> {disp_cat[:15]}"[:20]
            l2 = f"  ({count} objets)" if lang == "fr" else f"  ({count} objects)"
            l3 = "  [HAUT/BAS] Choisir" if lang == "fr" else "  [UP/DOWN] Select"
            
        elif self.state == self.UI_OBJECT_LIST:
            cat_name = self.catalogs[self.cat_idx]
            disp_cat = cat_name
            if lang == "en":
                if cat_name == "Systeme Solaire": disp_cat = "Sol"
                elif cat_name == "Étoiles": disp_cat = "Star"
            else:
                disp_cat = disp_cat[:3]
                
            l0 = f"[{disp_cat.upper()}] {len(self.obj_list)} objets"[:20]
            
            if len(self.obj_list) == 0:
                l1 = " Aucun objet trouve" if lang == "fr" else " No object found"
            else:
                o = self.obj_list[self.obj_idx]
                name = o.get('name', f"{o.get('cat')} {o.get('num')}")
                if name == f"{o.get('cat')} {o.get('num')}": name = f"{disp_cat} {o.get('num')}"
                vis_star = "*" if o.get("visible", False) else ""
                mag_str = f" Mag: {o.get('mag')}" if o.get('mag') else ""
                l1 = f"> {name[:12]}{vis_star}"[:20]
                l2 = mag_str[:20]
                if 'ra' in o and 'dec' in o:
                    ra_str = Astro.fmt_ra_lx(o['ra'])[:5].replace(':','h')
                    dec_str = Astro.fmt_dec_lx(o['dec'])[:6].replace('*','°')
                    l3 = f"  {ra_str} {dec_str}"[:20]
                else:
                    l3 = ""
                
        elif self.state == self.UI_OBJECT_INFO:
            o = self.obj_list[self.obj_idx]
            name = o.get('name', f"{o.get('cat')} {o.get('num')}")
            vis_star = "*" if o.get("visible", False) else ""
            l0 = f"OBJET: {name[:12]}{vis_star}"[:20]
            if 'ra' in o and 'dec' in o:
                l1 = f"RA: {Astro.fmt_ra_lx(o['ra'])[:8]}"[:20]
                l2 = f"DE: {Astro.fmt_dec_lx(o['dec'])[:9]}"[:20]
            l3 = "[ENT]=GOTO  [>]=SYNC"
            
        elif self.state == self.UI_SLEWING:
            anim_chars = ['*', '+', 'x', '+']
            anim = anim_chars[int(time.time() * 4) % 4]
            if getattr(self, "is_parking_workflow", False):
                l0 = f"PARKING EN COURS {anim}" if lang == "fr" else f"PARKING IN PROG. {anim}"
                l1 = "Moteurs en route..." if lang == "fr" else "Motors running..."
                l2 = "Veuillez patienter" if lang == "fr" else "Please wait"
                l3 = "[<] Annuler" if lang == "fr" else "[<] Cancel"
            else:
                l0 = f"GOTO EN COURS... {anim}" if lang == "fr" else f"SLEWING TO CCT... {anim}"
                
                # Try to show target
                if getattr(self, 'target_ra', None) is not None:
                    try:
                        c_ra = Astro.parse_ra(self.current_ra)
                        c_dec = Astro.parse_dec(self.current_dec)
                        
                        # Distance par axe, pas grand cercle
                        ra_diff = abs(c_ra - self.target_ra) * 15.0
                        if ra_diff > 180.0: ra_diff = 360.0 - ra_diff
                        dec_diff = abs(c_dec - self.target_dec)
                        dist = max(ra_diff, dec_diff)
                        
                        v_max = self.current_speed if getattr(self, "current_speed", 2.0) > 0 else 2.0
                        
                        # Modèle rampe 5s (trapèze/triangle)
                        d_ramp = (v_max * 5.0) / 2.0
                        if not getattr(self, "slew_stopwatch_active", False):
                            self.slew_stopwatch_active = True
                            self.slew_start_time = time.time()
                            if dist >= 2 * d_ramp:
                                coasting_dist = dist - 2 * d_ramp
                                coasting_time = coasting_dist / v_max
                                self.initial_eta = 10.0 + coasting_time
                            else:
                                self.initial_eta = 2.0 * math.sqrt(5.0 * dist / v_max) if v_max > 0 else 0.0
                        
                        elapsed = time.time() - getattr(self, "slew_start_time", time.time())
                        eta = max(0, int(getattr(self, "initial_eta", 0) - elapsed))
                        
                        gc_dist = Astro.angular_dist(c_ra, c_dec, self.target_ra, self.target_dec)
                        l1 = f"Dist restante: {gc_dist:.1f}°"[:20]
                        l2 = ""
                        l3 = "[<] Annuler GOTO" if lang == "fr" else "[<] Cancel GOTO"
                    except:
                        l1 = "Calcul en cours..."
                else:
                    l1 = "Calcul en cours..."
                
        elif self.state == self.UI_ALIGN_CENTER:
            o = self.obj_list[self.obj_idx]
            name = o.get('name', f"{o.get('cat')} {o.get('num')}")
            l0 = "CENTREZ L'OBJET:" if lang == "fr" else "CENTER OBJECT:"
            l1 = f"> {name[:17]}"[:20]
            l2 = "Utilisez les fleches" if lang == "fr" else "Use arrow keys"
            l3 = "[ENT] Valider Sync" if lang == "fr" else "[ENT] Confirm Sync"
            
        elif self.state == self.UI_SETTINGS:
            l0 = "[ MENU REGLAGES ]" if lang == "fr" else "[ SETTINGS MENU ]"
            az_str = "Ratio AZ" if self.cfg.get("mount_type", "AltAz") == "AltAz" else "Ratio RA"
            alt_str = "Ratio ALT" if self.cfg.get("mount_type", "AltAz") == "AltAz" else "Ratio DEC"
            if lang == "en":
                az_str = "AZ Ratio" if self.cfg.get("mount_type", "AltAz") == "AltAz" else "RA Ratio"
                alt_str = "ALT Ratio" if self.cfg.get("mount_type", "AltAz") == "AltAz" else "DEC Ratio"
            opts = ["Catalogues", "Pause Moteurs", "Vitesse", "Bips", "Alignement", "Parking", "Type Monture", az_str, alt_str, "Alim Moteurs", "Date/Heure", "Lieu Obs.", "Langue", "GPS Auto"] if lang == "fr" else ["Catalogs", "Pause Motors", "Speed", "Beeps", "Alignment", "Parking", "Mount Type", az_str, alt_str, "Motor Power", "Date/Time", "Location", "Language", "GPS Auto"]
            l1 = f"> {opts[self.settings_sel]}"[:20]
            l2 = "  " + (opts[self.settings_sel+1] if self.settings_sel+1 < len(opts) else "")[:18]
            l3 = "  [HAUT/BAS] Choisir" if lang == "fr" else "  [UP/DOWN] Select"
            
        elif self.state == self.UI_SPEED:
            l0 = "[ VITESSE GOTO ]" if lang == "fr" else "[ GOTO SPEED ]"
            l1 = f"> {self.temp_speed:.1f} deg/s"[:20]
            l2 = ""
            l3 = "[ENT] Valider" if lang == "fr" else "[ENT] Confirm"
            
        elif self.state == self.UI_BEEP:
            l0 = "[ BIP BUZZER ]" if lang == "fr" else "[ BEEP BUZZER ]"
            state_str = "ACTIVE" if self.temp_buzzer_on else "DESACTIVE"
            l1 = f"> {state_str}"[:20]
            l2 = ""
            l3 = "[ENT] Valider" if lang == "fr" else "[ENT] Confirm"
            
        elif self.state == self.UI_MOTOR_POWER:
            l0 = "[ ALIM MOTEURS ]" if lang == "fr" else "[ MOTOR POWER ]"
            status = ("ACTIVE" if self.temp_motor_power else "OFF") if lang == "fr" else ("ON" if self.temp_motor_power else "OFF")
            l1 = f"> {status}"[:20]
            l2 = "Coupe le courant" if lang == "fr" else "Cuts motor power"
            l3 = "[ENT] Valider" if lang == "fr" else "[ENT] Confirm"
                

        elif self.state == self.UI_LANGUAGE:
            l0 = "[ LANGUE / LANG ]"
            l1 = f"> {'FRANCAIS' if self.temp_lang == 'fr' else 'ENGLISH'}"[:20]
            l2 = ""
            l3 = "[ENT] Valider" if lang == "fr" else "[ENT] Confirm"
            
        elif self.state == self.UI_EDIT_TIME:
            l0 = "[ REGLAGE HEURE ]" if lang == "fr" else "[ SET TIME ]"
            l1 = f" {time.strftime('%H:%M:%S')} (PC)"
            import ephem
            import math
            obs = ephem.Observer()
            obs.lat = str(self.lat)
            obs.lon = str(self.lon)
            obs.date = ephem.now()
            lst_rad = obs.sidereal_time()
            lst_hours = lst_rad * 12.0 / math.pi
            lst_h = int(lst_hours)
            lst_m = int((lst_hours - lst_h) * 60)
            l2 = f" LST: {lst_h:02d}h{lst_m:02d}m"
            l3 = "[ENT] Sync PC" if lang == "fr" else "[ENT] Sync PC"
            
        elif self.state == self.UI_EDIT_LOCATION:
            l0 = "[ LIEU / LOCATION ]"
            l1 = f" Lat: {self.cfg.get('latitude', 0):.2f}"
            l2 = f" Lon: {self.cfg.get('longitude', 0):.2f}"
            l3 = "[ENT] Sync PC" if lang == "fr" else "[ENT] Sync PC"

        elif self.state == self.UI_GPS:
            l0 = "[ GPS ]"
            status = ("Auto activé" if self.temp_gps_enabled else "Désactivé") if lang == "fr" else ("Auto enabled" if self.temp_gps_enabled else "Disabled")
            l1 = f"> {status}"[:20]
            l2 = ""
            l3 = "[ENT] Valider" if lang == "fr" else "[ENT] Confirm"
            
        elif self.state == self.UI_MOUNT:
            l0 = "[ TYPE MONTURE ]" if lang == "fr" else "[ MOUNT TYPE ]"
            mount_str = "Alt-Azimutale" if self.temp_mount_type == 0 else ("Fourche Equato" if self.temp_mount_type == 1 else "Equatoriale All.")
            l1 = f"> {mount_str}"[:20]
            l2 = ""
            l3 = "[ENT] Valider" if lang == "fr" else "[ENT] Confirm"
            
        elif self.state == self.UI_RATIO_AZ:
            is_altaz = (self.cfg.get("mount_type", "AltAz") == "AltAz")
            lbl = "RATIO AZ" if is_altaz else "RATIO RA"
            if lang == "en": lbl = "AZ RATIO" if is_altaz else "RA RATIO"
            l0 = f"[ {lbl} ]"[:20]
            l1 = f" 1:{int(self.temp_ratio_az)}"[:20]
            rs = getattr(self, 'ratio_step', 1.0)
            l2 = f"  Pas: {int(rs)}"
            l3 = "[<>]=Pas [^v]=Edit "
            
        elif self.state == self.UI_RATIO_ALT:
            is_altaz = (self.cfg.get("mount_type", "AltAz") == "AltAz")
            lbl = "RATIO ALT" if is_altaz else "RATIO DEC"
            if lang == "en": lbl = "ALT RATIO" if is_altaz else "DEC RATIO"
            l0 = f"[ {lbl} ]"[:20]
            l1 = f" 1:{int(self.temp_ratio_alt)}"[:20]
            rs = getattr(self, 'ratio_step', 1.0)
            l2 = f"  Pas: {int(rs)}"
            l3 = "[<>]=Pas [^v]=Edit "

        self.lcd_lines[0].config(text=f"{l0:<20}")
        self.lcd_lines[1].config(text=f"{l1:<20}")
        self.lcd_lines[2].config(text=f"{l2:<20}")
        self.lcd_lines[3].config(text=f"{l3:<20}")

    def get_visible_stars(self):
        try:
            now = datetime.now(timezone.utc)
            obs = ephem.Observer()
            obs.lat = str(self.lat)
            obs.lon = str(self.lon)
            obs.date = now
            stars = self.db_cat.get("Étoiles", [])
            visible = []
            for s in stars:
                body = ephem.FixedBody()
                body._ra = s['ra'] * math.pi / 12.0
                body._dec = s['dec'] * math.pi / 180.0
                body.compute(obs)
                alt = float(body.alt) * 180.0 / math.pi
                if 15.0 < alt < 80.0:
                    visible.append(s)
            visible.sort(key=lambda x: x.get('mag', 10.0))
            return visible if visible else stars
        except:
            return self.db_cat.get("Étoiles", [])

    def get_catalog_with_visibility(self, cat_name):
        try:
            now = datetime.now(timezone.utc)
            obs = ephem.Observer()
            obs.lat = str(self.lat)
            obs.lon = str(self.lon)
            obs.date = now
            raw_list = self.db_cat.get(cat_name, [])
            enriched = []
            for s in raw_list:
                s_copy = s.copy()
                body = ephem.FixedBody()
                body._ra = s['ra'] * math.pi / 12.0
                body._dec = s['dec'] * math.pi / 180.0
                body.compute(obs)
                alt_deg = float(body.alt) * 180.0 / math.pi
                with open("/tmp/rv_debug.txt", "a") as f:
                    f.write(f"{s.get('name')}: alt={alt_deg:.2f}, min={self.alt_min}\n")
                if alt_deg > self.alt_min:
                    s_copy['visible'] = True
                else:
                    s_copy['visible'] = False
                enriched.append(s_copy)
            
            if cat_name not in ("Systeme Solaire", "Étoiles"):
                enriched.sort(key=lambda x: int(x.get('num', 0)) if str(x.get('num','0')).isdigit() else 0)
                
            return enriched
        except Exception as e:
            with open("/tmp/rv_debug.txt", "a") as f:
                f.write(f"ERROR: {e}\n")
            print(f"ERROR in get_catalog_with_visibility: {e}")
            return self.db_cat.get(cat_name, [])

    def handle_btn(self, btn):
        if self.state == self.UI_MESSAGE:
            self.state = self.msg_return_state
            self.msg_until = 0
            self.update_lcd()
            return
            
        if self.state == self.UI_MAIN:
            if btn == "ENTER":
                self.settings_sel = 0
                self.state = self.UI_SETTINGS
                
        elif self.state == self.UI_CAT_SELECT:
            if btn == "LEFT":
                self.state = self.UI_MAIN
            elif btn == "UP":
                self.cat_idx = (self.cat_idx - 1) % len(self.catalogs)
            elif btn == "DOWN":
                self.cat_idx = (self.cat_idx + 1) % len(self.catalogs)
            elif btn in ("ENTER", "RIGHT"):
                cat_name = self.catalogs[self.cat_idx]
                if cat_name == "Étoiles":
                    stars = self.get_visible_stars()
                    for s in stars: s['visible'] = True
                    self.obj_list = stars
                elif cat_name == "ISS":
                    self.obj_list = []
                    lang = self.cfg.get("language", "fr")
                    import time, math
                    from pathlib import Path
                    tle_path = Path.home() / ".goto_andrivet" / "iss.tle"
                    if tle_path.exists() and (time.time() - tle_path.stat().st_mtime < 86400):
                        try:
                            import ephem
                            with open(tle_path, 'r') as f:
                                lines = f.read().splitlines()
                            iss = ephem.readtle(lines[0], lines[1], lines[2])
                            
                            # Use observer location if connected to get apparent RA/DEC and visibility
                            if self.is_connected:
                                self.sync_clock() # Basic sync to ensure observer is setup
                            obs = ephem.Observer()
                            obs.lat = str(self.cfg.get('latitude', 45.0))
                            obs.lon = str(self.cfg.get('longitude', 0.0))
                            obs.elevation = self.cfg.get('elevation', 100)
                            iss.compute(obs)
                            
                            visible = float(iss.alt) > 0
                            next_pass = ""
                            rise_ra = 0
                            rise_dec = 0
                            rise_time = 0
                            if not visible:
                                try:
                                    pass_info = obs.next_pass(iss)
                                    rise_dt = ephem.localtime(pass_info[0])
                                    next_pass = rise_dt.strftime("%d/%m %H:%M")
                                    obs.date = pass_info[0]
                                    iss.compute(obs)
                                    rise_ra = float(iss.ra) * 12.0 / math.pi
                                    rise_dec = float(iss.dec) * 180.0 / math.pi
                                    rise_time = pass_info[0]
                                except Exception:
                                    pass
                            self.iss_obj = iss
                            self.iss_obs = obs
                            self.obj_list = [{'name': 'ISS (ZARYA)', 'type': 'S', 'mag': -2.0, 'ra': float(iss.ra)*12.0/math.pi, 'dec': float(iss.dec)*180.0/math.pi, 'const': 'LEO', 'visible': visible, 'next_pass': next_pass, 'rise_ra': rise_ra, 'rise_dec': rise_dec, 'rise_time': rise_time}]
                            self.set_msg(" TLE BON ! " if lang=="fr" else " TLE GOOD! ", "                ", "", "", 1500, self.UI_OBJECT_LIST)
                        except Exception:
                            self.set_msg(" TLE CORROMPU ! " if lang=="fr" else " TLE CORRUPTED! ", "                ", "", "", 2000, self.UI_CAT_SELECT)
                            return
                    else:
                        self.set_msg(" TLE ABSENT/PERIME " if lang=="fr" else " TLE MISSING/OLD ", " Utiliser Config. " if lang=="fr" else " Use Config Tool ", "", "", 2000, self.UI_CAT_SELECT)
                        return
                else:
                    self.obj_list = self.get_catalog_with_visibility(cat_name)
                self.obj_idx = 0
                if self.obj_list:
                    self.state = self.UI_OBJECT_LIST
                
        elif self.state == self.UI_OBJECT_LIST:
            if btn == "UP":
                self.obj_idx = (self.obj_idx - 1) % len(self.obj_list) if self.obj_list else 0
            elif btn == "DOWN":
                self.obj_idx = (self.obj_idx + 1) % len(self.obj_list) if self.obj_list else 0
            elif btn == "LEFT":
                self.state = self.UI_CAT_SELECT
            elif btn in ("RIGHT", "ENTER"):
                if self.obj_list:
                    self.state = self.UI_OBJECT_INFO
                    
        elif self.state == self.UI_OBJECT_INFO:
            if btn == "LEFT":
                self.is_align_workflow = False
                self.state = self.UI_OBJECT_LIST
            elif btn == "UP":
                self.obj_idx = (self.obj_idx - 1) % len(self.obj_list) if self.obj_list else 0
            elif btn == "DOWN":
                self.obj_idx = (self.obj_idx + 1) % len(self.obj_list) if self.obj_list else 0
            elif btn == "RIGHT":
                if self.is_connected:
                    o = self.obj_list[self.obj_idx]
                    if not o.get('visible', False):
                        lang = self.cfg.get("language", "fr")
                        msg2 = "                "
                        if o.get('name') == 'ISS (ZARYA)' and o.get('next_pass'):
                            msg2 = f"PASS: {o['next_pass']}"[:16].ljust(16)
                        self.set_msg(" SOUS HORIZON ! " if lang=="fr" else " BELOW HORIZON! ", msg2, "", "", 3000, self.UI_OBJECT_INFO)
                        return
                        
                    self.target_ra = o['ra']
                    self.target_dec = o['dec']
                    ra_str = Astro.fmt_ra_lx(o['ra'])
                    dec_str = Astro.fmt_dec_lx(o['dec'])
                    
                    self.cmd_queue = [f":Sr{ra_str}#", f":Sd{dec_str}#", ":CM#"]
                    self.process_queue()
                    
                    lang = self.cfg.get("language", "fr")
                    if lang == "en":
                        self.set_msg("  SYNCHRONIZED  ", "                ", "", "", 1500, self.UI_MAIN)
                    else:
                        self.set_msg("  SYNCHRONISE   ", "                ", "", "", 1500, self.UI_MAIN)
                else:
                    lang = self.cfg.get("language", "fr")
                    if lang == "en":
                        self.set_msg(" ERROR: ", " NOT CONNECTED ", "", "", 2000, self.UI_OBJECT_INFO)
                    else:
                        self.set_msg(" ERREUR: ", " NON CONNECTE ", "", "", 2000, self.UI_OBJECT_INFO)
                    return
            elif btn == "ENTER":
                if self.is_connected:
                    o = self.obj_list[self.obj_idx]
                    if not o.get('visible', False):
                        if o.get('name') == 'ISS (ZARYA)' and o.get('rise_time'):
                            import ephem
                            import math
                            pass_info = self.iss_obs.next_pass(self.iss_obj)
                            self.iss_obs.date = ephem.now()
                            cur_ra, cur_dec = self.iss_obs.radec_of(pass_info[1], 0)
                            
                            self.target_ra = float(cur_ra) * 12.0 / math.pi
                            self.target_dec = float(cur_dec) * 180.0 / math.pi
                            ra_str = Astro.fmt_ra_lx(self.target_ra)
                            dec_str = Astro.fmt_dec_lx(self.target_dec)
                            self.cmd_queue = [f":Sr{ra_str}#", f":Sd{dec_str}#", ":MS#", ":Td#"]
                            self.process_queue()
                            
                            self.pending_iss_track_time = ephem.localtime(o['rise_time']).timestamp()
                            lang = self.cfg.get("language", "fr")
                            self.set_msg(" ATTENTE ISS... " if lang=="fr" else " WAITING ISS... ", f" {o.get('next_pass','')} "[:16].ljust(16), "", "", 3000, self.UI_MAIN)
                            return
                        else:
                            lang = self.cfg.get("language", "fr")
                            msg2 = "                "
                            if o.get('name') == 'ISS (ZARYA)' and o.get('next_pass'):
                                msg2 = f"PASS: {o['next_pass']}"[:16].ljust(16)
                            self.set_msg(" SOUS HORIZON ! " if lang=="fr" else " BELOW HORIZON! ", msg2, "", "", 3000, self.UI_OBJECT_INFO)
                            return
                        
                    self.target_ra = o['ra']
                    self.target_dec = o['dec']
                    ra_str = Astro.fmt_ra_lx(o['ra'])
                    dec_str = Astro.fmt_dec_lx(o['dec'])
                    
                    self.cmd_queue = [f":Sr{ra_str}#", f":Sd{dec_str}#", ":MS#"]
                    self.process_queue()
                else:
                    lang = self.cfg.get("language", "fr")
                    if lang == "en":
                        self.set_msg(" ERROR: ", " NOT CONNECTED ", "", "", 2000, self.UI_OBJECT_INFO)
                    else:
                        self.set_msg(" ERREUR: ", " NON CONNECTE ", "", "", 2000, self.UI_OBJECT_INFO)
                    return
                    
        elif self.state == self.UI_ALIGN_CENTER:
            if btn == "LEFT":
                self.state = self.UI_MAIN
            elif btn == "ENTER":
                if self.is_connected:
                    o = self.obj_list[self.obj_idx]
                    self.target_ra = o['ra']
                    self.target_dec = o['dec']
                    ra_str = Astro.fmt_ra_lx(o['ra'])
                    dec_str = Astro.fmt_dec_lx(o['dec'])
                    
                    self.cmd_queue = [f":Sr{ra_str}#", f":Sd{dec_str}#", ":CM#"]
                    self.process_queue()
                    
                    lang = self.cfg.get("language", "fr")
                    if lang == "en":
                        self.set_msg("  SYNCHRONIZED  ", "                ", "", "", 1500, self.UI_MAIN)
                    else:
                        self.set_msg("  SYNCHRONISE   ", "                ", "", "", 1500, self.UI_MAIN)
                    
        elif self.state == self.UI_SLEWING:
            if btn in ("LEFT", "ENTER"):
                self.send_cmd(":Q#")
                self.cmd_queue.clear()
                self.state = self.UI_MAIN
                
        elif self.state == self.UI_SETTINGS:
            if btn == "LEFT":
                self.state = self.UI_MAIN
            elif btn == "UP":
                self.settings_sel = (self.settings_sel - 1) % 14
            elif btn == "DOWN":
                self.settings_sel = (self.settings_sel + 1) % 14
            elif btn in ("ENTER", "RIGHT"):
                lang = self.cfg.get("language", "fr")
                if self.settings_sel == 0:
                    self.cat_idx = 0
                    self.state = self.UI_CAT_SELECT
                elif self.settings_sel == 1:
                    is_paused = getattr(self, 'iss_tracking_active', False)
                    if not is_paused:
                        self.send_cmd(":Td#")
                        self.iss_tracking_active = True
                        if lang == "en":
                            self.set_msg(" MOTORS PAUSED  ", "                ", "", "", 1500, self.UI_MAIN)
                        else:
                            self.set_msg(" MOTEURS EN PAUSE ", "                ", "", "", 1500, self.UI_MAIN)
                    else:
                        if hasattr(self, 'target_ra') and hasattr(self, 'target_dec') and self.target_ra is not None and self.target_dec is not None and self.target_ra >= 0 and self.target_dec >= -90:
                            ra_str = Astro.fmt_ra_lx(self.target_ra)
                            dec_str = Astro.fmt_dec_lx(self.target_dec)
                            self.send_cmd(f":Sr{ra_str}#")
                            self.send_cmd(f":Sd{dec_str}#")
                            self.send_cmd(":MS#")
                            self.iss_tracking_active = False
                            if lang == "en":
                                self.set_msg(" RESUMING TRACK ", "                ", "", "", 1500, self.UI_SLEWING)
                            else:
                                self.set_msg(" REPRISE SUIVI... ", "                ", "", "", 1500, self.UI_SLEWING)
                        else:
                            self.send_cmd(":Te#")
                            self.iss_tracking_active = False
                            if lang == "en":
                                self.set_msg(" RESUMING TRACK ", " No Target...   ", "", "", 1500, self.UI_MAIN)
                            else:
                                self.set_msg(" REPRISE SUIVI... ", " Sans cible...  ", "", "", 1500, self.UI_MAIN)
                elif self.settings_sel == 2:
                    self.temp_speed = self.current_speed
                    self.state = self.UI_SPEED
                elif self.settings_sel == 3:
                    self.temp_buzzer_on = self.buzzer_on
                    self.state = self.UI_BEEP
                elif self.settings_sel == 4:
                    # Alignment: Propose best star
                    stars = self.get_visible_stars()
                    if stars:
                        for s in stars: s['visible'] = True
                        self.obj_list = stars
                        self.obj_idx = 0
                        self.state = self.UI_OBJECT_INFO
                        self.is_align_workflow = True
                    else:
                        lang = self.cfg.get("language", "fr")
                        self.set_msg(" AUCUNE ETOILE  " if lang=="fr" else " NO STAR FOUND  ", " VISIBLE        ", "", "", 1500, self.UI_SETTINGS)
                elif self.settings_sel == 5:
                    self.is_parking_workflow = True
                    self.cmd_queue.append(":hP#")
                    self.process_queue()
                elif self.settings_sel == 6:
                    mt = self.cfg.get("mount_type", "AltAz")
                    self.temp_mount_type = 0 if mt == "AltAz" else (1 if mt == "ForkEq" else 2)
                    self.state = self.UI_MOUNT
                elif self.settings_sel == 7:
                    self.temp_ratio_az = float(self.cfg.get("gear_ratio_az", 2000.0))
                    self.state = self.UI_RATIO_AZ
                elif self.settings_sel == 8:
                    self.temp_ratio_alt = float(self.cfg.get("gear_ratio_alt", 2000.0))
                    self.state = self.UI_RATIO_ALT
                elif self.settings_sel == 9:
                    self.temp_motor_power = getattr(self, "motor_power", True)
                    self.state = self.UI_MOTOR_POWER
                elif self.settings_sel == 10:
                    self.state = self.UI_EDIT_TIME
                elif self.settings_sel == 11:
                    self.state = self.UI_EDIT_LOCATION
                elif self.settings_sel == 12:
                    self.temp_lang = lang
                    self.state = self.UI_LANGUAGE
                elif self.settings_sel == 13:
                    self.temp_gps_enabled = self.cfg.get("gps_enabled", True)
                    self.state = self.UI_GPS
                    
        elif self.state == self.UI_SPEED:
            if btn == "LEFT":
                self.state = self.UI_SETTINGS
            elif btn == "UP":
                self.temp_speed += 0.5
                if self.temp_speed > 25.0: self.temp_speed = 25.0
            elif btn == "DOWN":
                self.temp_speed -= 0.5
                if self.temp_speed < 0.5: self.temp_speed = 0.5
            elif btn == "ENTER":
                self.current_speed = self.temp_speed
                self.send_cmd(f":BV {int(self.current_speed * 10)}#")
                lang = self.cfg.get("language", "fr")
                if lang == "en":
                    self.set_msg("  SPEED ADJUSTED ", f"   {self.current_speed:.1f} deg/s OK  ", "", "", 1200, self.UI_SETTINGS)
                else:
                    self.set_msg("  VITESSE REGL.  ", f"   {self.current_speed:.1f} deg/s OK  ", "", "", 1200, self.UI_SETTINGS)
                
        elif self.state == self.UI_MOUNT:
            if btn == "LEFT":
                self.state = self.UI_SETTINGS
            elif btn in ("UP", "DOWN"):
                self.temp_mount_type = (self.temp_mount_type + 1) % 3
            elif btn == "ENTER":
                mt = "AltAz" if self.temp_mount_type == 0 else ("ForkEq" if self.temp_mount_type == 1 else "GermanEq")
                self.cfg.set("mount_type", mt)
                self.cfg.save()
                if mt == "AltAz": self.send_cmd(":BMa#")
                elif mt == "ForkEq": self.send_cmd(":BMe#")
                else: self.send_cmd(":BMg#")
                lang = self.cfg.get("language", "fr")
                if lang == "en":
                    self.set_msg(" MOUNT TYPE SET  ", "", "", "", 1200, self.UI_SETTINGS)
                else:
                    self.set_msg(" MONTURE REGLEE  ", "", "", "", 1200, self.UI_SETTINGS)

        elif self.state == self.UI_RATIO_AZ:
            if not hasattr(self, 'ratio_step'): self.ratio_step = 1.0
            if btn == "LEFT":
                self.state = self.UI_SETTINGS
            elif btn == "RIGHT":
                self.ratio_step *= 10.0
                if self.ratio_step > 1000.0: self.ratio_step = 1.0
            elif btn == "UP":
                self.temp_ratio_az += self.ratio_step
            elif btn == "DOWN":
                self.temp_ratio_az -= self.ratio_step
                if self.temp_ratio_az < 1.0: self.temp_ratio_az = 1.0
            elif btn == "ENTER":
                self.cfg.set("gear_ratio_az", self.temp_ratio_az)
                self.cfg.save()
                self.send_cmd(f":BGa{self.temp_ratio_az}#")
                lang = self.cfg.get("language", "fr")
                is_altaz = (self.cfg.get("mount_type", "AltAz") == "AltAz")
                if lang == "en":
                    self.set_msg("  AZ RATIO SET   " if is_altaz else "  RA RATIO SET   ", "", "", "", 1200, self.UI_SETTINGS)
                else:
                    self.set_msg(" RATIO AZ REGLE  " if is_altaz else " RATIO RA REGLE  ", "", "", "", 1200, self.UI_SETTINGS)

        elif self.state == self.UI_RATIO_ALT:
            if not hasattr(self, 'ratio_step'): self.ratio_step = 1.0
            if btn == "LEFT":
                self.state = self.UI_SETTINGS
            elif btn == "RIGHT":
                self.ratio_step *= 10.0
                if self.ratio_step > 1000.0: self.ratio_step = 1.0
            elif btn == "UP":
                self.temp_ratio_alt += self.ratio_step
            elif btn == "DOWN":
                self.temp_ratio_alt -= self.ratio_step
                if self.temp_ratio_alt < 1.0: self.temp_ratio_alt = 1.0
            elif btn == "ENTER":
                self.cfg.set("gear_ratio_alt", self.temp_ratio_alt)
                self.cfg.save()
                self.send_cmd(f":BGe{self.temp_ratio_alt}#")
                lang = self.cfg.get("language", "fr")
                is_altaz = (self.cfg.get("mount_type", "AltAz") == "AltAz")
                if lang == "en":
                    self.set_msg("  ALT RATIO SET  " if is_altaz else "  DEC RATIO SET  ", "", "", "", 1200, self.UI_SETTINGS)
                else:
                    self.set_msg(" RATIO ALT REGLE " if is_altaz else " RATIO DEC REGLE ", "", "", "", 1200, self.UI_SETTINGS)
                
        elif self.state == self.UI_BEEP:
            if btn == "LEFT":
                self.state = self.UI_SETTINGS
            elif btn in ("UP", "DOWN"):
                self.temp_buzzer_on = not self.temp_buzzer_on
            elif btn == "ENTER":
                self.buzzer_on = self.temp_buzzer_on
                cmd = ":Bb1#" if self.buzzer_on else ":Bb0#"
                self.send_cmd(cmd)
                lang = self.cfg.get("language", "fr")
                if lang == "en":
                    self.set_msg("    BEEP SET.    ", "", "", "", 1200, self.UI_SETTINGS)
                else:
                    self.set_msg("    BIP REGL.    ", "", "", "", 1200, self.UI_SETTINGS)
                    
        elif self.state == self.UI_MOTOR_POWER:
            if btn == "LEFT":
                self.state = self.UI_SETTINGS
            elif btn in ("UP", "DOWN"):
                self.temp_motor_power = not self.temp_motor_power
            elif btn == "ENTER":
                self.motor_power = self.temp_motor_power
                lang = self.cfg.get("language", "fr")
                if self.motor_power:
                    self.send_cmd(":ME#")
                    if lang == "en":
                        self.set_msg(" MOTORS ENABLED  ", "", "", "", 1200, self.UI_SETTINGS)
                    else:
                        self.set_msg(" MOTEURS ACTIFS  ", "", "", "", 1200, self.UI_SETTINGS)
                else:
                    self.send_cmd(":MD#")
                    if lang == "en":
                        self.set_msg(" MOTORS DISABLED ", "", "", "", 1200, self.UI_SETTINGS)
                    else:
                        self.set_msg(" ALIM COUPEE     ", "", "", "", 1200, self.UI_SETTINGS)
                        
        elif self.state == self.UI_LANGUAGE:
            if btn == "LEFT":
                self.state = self.UI_SETTINGS
            elif btn in ("UP", "DOWN"):
                self.temp_lang = "fr" if self.temp_lang == "en" else "en"
            elif btn == "ENTER":
                self.cfg.set("language", self.temp_lang)
                self.cfg.save()
                if self.temp_lang == "en":
                    self.title("Virtual T4.1 Hand Controller")
                    self.set_msg(" LANGUAGE SAVED  ", "", "", "", 1200, self.UI_SETTINGS)
                else:
                    self.title("Raquette T4.1 Virtuelle")
                    self.set_msg(" LANGUE ENREG.   ", "", "", "", 1200, self.UI_SETTINGS)
                    
        elif self.state == self.UI_EDIT_TIME:
            if btn == "LEFT":
                self.state = self.UI_SETTINGS
            elif btn == "ENTER":
                import time
                t = time.localtime()
                self.send_cmd(f":SC{time.strftime('%m/%d/%y', t)}#")
                self.send_cmd(f":SL{time.strftime('%H:%M:%S', t)}#")
                offset = -time.timezone // 3600
                if time.daylight and t.tm_isdst: offset = -time.altzone // 3600
                # :SG (LX200) : heures à ajouter à l'heure locale pour obtenir l'UTC, donc UTC+2 -> :SG-02
                self.send_cmd(f":SG{-offset:+03d}#")
                lang = self.cfg.get("language", "fr")
                self.set_msg("    HEURE SYNC   " if lang=="fr" else "    TIME SYNC    ", "       (PC)     ", "", "", 1200, self.UI_SETTINGS)
                
        elif self.state == self.UI_EDIT_LOCATION:
            if btn == "LEFT":
                self.state = self.UI_SETTINGS
            elif btn == "ENTER":
                lat = self.cfg.get("latitude", 0)
                lon = self.cfg.get("longitude", 0)
                lat_deg, lat_m = int(abs(lat)), int((abs(lat) - int(abs(lat))) * 60)
                lon_deg, lon_m = int(abs(lon)), int((abs(lon) - int(abs(lon))) * 60)
                lat_str = f"{'+' if lat >= 0 else '-'}{lat_deg:02d}*{lat_m:02d}"
                lon_str = f"{'-' if lon >= 0 else '+'}{lon_deg:03d}*{lon_m:02d}"   # LX200 : Ouest positif
                self.send_cmd(f":St{lat_str}#")
                self.send_cmd(f":Sg{lon_str}#")
                lang = self.cfg.get("language", "fr")
                self.set_msg("    LIEU SYNC    " if lang=="fr" else "    LOC SYNC     ", "   (Config PC)  ", "", "", 1200, self.UI_SETTINGS)
                
        elif self.state == self.UI_GPS:
            if btn == "LEFT":
                self.state = self.UI_SETTINGS
            elif btn in ("UP", "DOWN"):
                self.temp_gps_enabled = not self.temp_gps_enabled
            elif btn == "ENTER":
                self.cfg.set("gps_enabled", self.temp_gps_enabled)
                self.cfg.save()
                self.send_cmd(":bg1#" if self.temp_gps_enabled else ":bg0#")
                lang = self.cfg.get("language", "fr")
                if lang == "en":
                    self.set_msg("    GPS SAVED    ", "", "", "", 1200, self.UI_SETTINGS)
                else:
                    self.set_msg("    GPS REGL.    ", "", "", "", 1200, self.UI_SETTINGS)
        
        elif self.state == self.UI_MOUNT:
            if btn == "LEFT":
                self.state = self.UI_SETTINGS
            elif btn in ("UP", "DOWN"):
                self.temp_mount_type = (self.temp_mount_type + 1) % 3
            elif btn == "ENTER":
                if self.temp_mount_type == 0: self.send_cmd(":BMa#")
                elif self.temp_mount_type == 1: self.send_cmd(":BMe#")
                else: self.send_cmd(":BMg#")
                self.cfg.set("mount_type", ["AltAz", "ForkEq", "GermanEq"][self.temp_mount_type])
                self.cfg.save()
                lang = self.cfg.get("language", "fr")
                if lang == "en":
                    self.set_msg(" MOUNT SET      ", "                ", "", "", 1500, self.UI_SETTINGS)
                else:
                    self.set_msg(" MONTURE REGLEE ", "                ", "", "", 1500, self.UI_SETTINGS)
                    
        elif self.state == self.UI_RATIO_AZ:
            if btn == "LEFT":
                self.state = self.UI_SETTINGS
            elif btn == "UP":
                self.temp_ratio_az += 10.0
            elif btn == "DOWN":
                self.temp_ratio_az -= 10.0
                if self.temp_ratio_az < 10.0: self.temp_ratio_az = 10.0
            elif btn == "ENTER":
                self.send_cmd(f":BGa{self.temp_ratio_az}#")
                self.cfg.set("gear_ratio_az", self.temp_ratio_az)
                self.cfg.save()
                lang = self.cfg.get("language", "fr")
                is_altaz = (self.cfg.get("mount_type", "AltAz") == "AltAz")
                lbl = "RATIO AZ" if is_altaz else "RATIO RA"
                if lang == "en": lbl = "AZ RATIO" if is_altaz else "RA RATIO"
                self.set_msg(f" {lbl} OK".ljust(20), "", "", "", 1500, self.UI_SETTINGS)
                
        elif self.state == self.UI_RATIO_ALT:
            if btn == "LEFT":
                self.state = self.UI_SETTINGS
            elif btn == "UP":
                self.temp_ratio_alt += 10.0
            elif btn == "DOWN":
                self.temp_ratio_alt -= 10.0
                if self.temp_ratio_alt < 10.0: self.temp_ratio_alt = 10.0
            elif btn == "ENTER":
                self.send_cmd(f":BGe{self.temp_ratio_alt}#")
                self.cfg.set("gear_ratio_alt", self.temp_ratio_alt)
                self.cfg.save()
                lang = self.cfg.get("language", "fr")
                is_altaz = (self.cfg.get("mount_type", "AltAz") == "AltAz")
                lbl = "RATIO ALT" if is_altaz else "RATIO DEC"
                if lang == "en": lbl = "ALT RATIO" if is_altaz else "DEC RATIO"
                self.set_msg(f" {lbl} OK".ljust(20), "", "", "", 1500, self.UI_SETTINGS)
                
        self.update_lcd()

if __name__ == "__main__":
    app = VirtualTeensyApp()
    tactile_wayland.brancher(app)
    app.mainloop()