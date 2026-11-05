import sys
import time
import threading
import math
import tkinter as tk
import tactile_wayland
from tkinter import ttk, messagebox
import cv2
import numpy as np
from PIL import Image, ImageTk

try:
    import zwoasi as asi
    ZWO_AVAILABLE = True
except ImportError:
    ZWO_AVAILABLE = False

import serial
import serial.tools.list_ports

class AutoguideSpectroApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Autoguidage ZWO - GotoAndrivet")
        
        self.ser = None
        self.camera = None
        
        self.running = False
        self.guiding = False
        
        # Coordonnées
        self.target_x = 320  # Position de la fente/fibre (défaut au centre)
        self.target_y = 240
        
        self.star_x = None   # Position de l'étoile suivie
        self.star_y = None
        
        # Paramètres de guidage
        self.agressivite_x = 0.5
        self.agressivite_y = 0.5
        self.ms_per_pixel_x = 50  # ms de guidage pour 1 pixel d'erreur
        self.ms_per_pixel_y = 50
        
        self.setup_ui()
        
    def setup_ui(self):
        frm = ttk.Frame(self.root, padding=10)
        frm.pack(fill=tk.BOTH, expand=True)
        
        # --- Ligne 1: Connexion ---
        fr_conn = ttk.LabelFrame(frm, text="1. Matériel", padding=5)
        fr_conn.pack(fill=tk.X, pady=5)
        
        self.port_var = tk.StringVar()
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.cb_ports = ttk.Combobox(fr_conn, textvariable=self.port_var, values=ports, width=15)
        if ports: self.cb_ports.current(0)
        self.cb_ports.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(fr_conn, text="Connecter Monture", command=self.connect_mount).pack(side=tk.LEFT, padx=5)
        ttk.Button(fr_conn, text="Init Caméra ZWO", command=self.init_camera).pack(side=tk.LEFT, padx=20)
        
        # --- Ligne 2: Paramètres Caméra & Guidage ---
        fr_param = ttk.LabelFrame(frm, text="2. Paramètres", padding=5)
        fr_param.pack(fill=tk.X, pady=5)
        
        ttk.Label(fr_param, text="Exp (ms):").pack(side=tk.LEFT)
        self.exp_var = tk.StringVar(value="500")
        ttk.Entry(fr_param, textvariable=self.exp_var, width=5).pack(side=tk.LEFT, padx=5)
        
        ttk.Label(fr_param, text="Gain:").pack(side=tk.LEFT)
        self.gain_var = tk.StringVar(value="150")
        ttk.Entry(fr_param, textvariable=self.gain_var, width=5).pack(side=tk.LEFT, padx=5)
        
        self.spectro_mode_var = tk.BooleanVar(value=False)
        self.chk_spectro = ttk.Checkbutton(fr_param, text="Mode Spectro", variable=self.spectro_mode_var, command=self.toggle_spectro_mode)
        self.chk_spectro.pack(side=tk.LEFT, padx=5)

        self.spectro_frame = ttk.Frame(fr_param)
        ttk.Button(self.spectro_frame, text="Détecter Fente Auto", command=self.auto_detect_slit).pack(side=tk.LEFT, padx=2)
        ttk.Button(self.spectro_frame, text="Centrage Astrométrie", command=self.center_via_astrometry).pack(side=tk.LEFT, padx=2)
        
        self.btn_start = ttk.Button(fr_param, text="Démarrer Guidage", command=self.start_guiding)
        self.btn_start.pack(side=tk.LEFT, padx=10)
        self.btn_stop = ttk.Button(fr_param, text="Stop", command=self.stop_guiding)
        self.btn_stop.pack(side=tk.LEFT, padx=5)
        
        self.lbl_status = ttk.Label(fr_param, text="Prêt.", foreground="blue")
        self.lbl_status.pack(side=tk.RIGHT, padx=10)
        
        # --- Video Feed ---
        self.canvas = tk.Canvas(frm, width=640, height=480, bg="black", cursor="cross")
        self.canvas.pack(pady=10)
        self.canvas.bind("<Button-1>", self.on_click_set_target)
        self.canvas.bind("<Button-3>", self.on_click_set_star)
        
        # Nudge keys
        self.root.bind("<Up>", self.nudge_up)
        self.root.bind("<Down>", self.nudge_down)
        self.root.bind("<Left>", self.nudge_left)
        self.root.bind("<Right>", self.nudge_right)
        
        self.lbl_info = ttk.Label(frm, text="Mode Normal : Clic Gauche = Sélectionner l'étoile guide (verrouille la cible)")
        self.lbl_info.pack()

    def toggle_spectro_mode(self):
        if self.spectro_mode_var.get():
            self.spectro_frame.pack(side=tk.LEFT, before=self.btn_start, padx=5)
            self.lbl_info.config(text="Mode Spectro : Clic Gauche = Placer cible (Fente) | Clic Droit = Sélectionner étoile guide")
        else:
            self.spectro_frame.pack_forget()
            self.lbl_info.config(text="Mode Normal : Clic Gauche = Sélectionner l'étoile guide (verrouille la cible)")
            self.target_x = None
            self.target_y = None

    def connect_mount(self):
        try:
            self.ser = serial.Serial(self.port_var.get(), 38400, timeout=1)
            self.lbl_status.config(text="Monture connectée", foreground="green")
        except Exception as e:
            messagebox.showerror("Erreur", str(e))

    def init_camera(self):
        if not ZWO_AVAILABLE:
            messagebox.showerror("Erreur", "Module zwoasi manquant.")
            return
        try:
            if asi.get_num_cameras() == 0:
                raise Exception("Aucune caméra ZWO détectée.")
            self.camera = asi.Camera(0)
            self.camera.set_control_value(asi.ASI_BANDWIDTHOVERLOAD, self.camera.get_controls()['BandWidth']['MinValue'])
            self.camera.disable_dark_subtract()
            self.lbl_status.config(text="Caméra ZWO initialisée", foreground="green")
            
            self.running = True
            threading.Thread(target=self.video_loop, daemon=True).start()
        except Exception as e:
            messagebox.showerror("Erreur ZWO", str(e))

    def send_cmd(self, cmd):
        if self.ser:
            self.ser.write(cmd.encode('ascii'))
            time.sleep(0.05)

    def read_resp(self):
        resp = b""
        if self.ser:
            while True:
                c = self.ser.read(1)
                if not c or c == b'#':
                    break
                resp += c
        return resp.decode('ascii')

    def ra_to_meade(self, hours):
        h = int(hours)
        m = int((hours - h) * 60)
        s = int((hours - h - m/60.0) * 3600)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def dec_to_meade(self, deg):
        sign = '+' if deg >= 0 else '-'
        deg = abs(deg)
        d = int(deg)
        m = int((deg - d) * 60)
        s = int((deg - d - m/60.0) * 3600)
        return f"{sign}{d:02d}*{m:02d}'{s:02d}"

    def auto_detect_slit(self):
        """Tente de trouver la fente/fibre (trait noir ou cercle noir)"""
        if not hasattr(self, 'last_img') or self.last_img is None:
            messagebox.showwarning("Erreur", "Aucune image disponible.")
            return
            
        blur = cv2.GaussianBlur(self.last_img, (5, 5), 0)
        # Seuil sur les pixels les plus sombres (on inverse pour que le noir devienne blanc)
        min_val = np.min(blur)
        _, thresh = cv2.threshold(blur, min_val + 30, 255, cv2.THRESH_BINARY_INV)
        
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            c = max(contours, key=cv2.contourArea)
            if cv2.contourArea(c) > 10:
                M = cv2.moments(c)
                if M["m00"] != 0:
                    self.target_x = int(M["m10"] / M["m00"])
                    self.target_y = int(M["m01"] / M["m00"])
                    self.lbl_status.config(text=f"Fente trouvée ({self.target_x}, {self.target_y}).", foreground="green")
                    return
                    
        self.lbl_status.config(text="Échec détection. Cliquez sur l'image pour placer la cible.", foreground="red")

    def center_via_astrometry(self):
        """Centre l'objet actuel sur la fente via astrométrie"""
        if not self.ser or not hasattr(self, 'last_img'):
            messagebox.showwarning("Attention", "Connectez la monture et attendez une image.")
            return
        if self.target_x is None:
            messagebox.showwarning("Attention", "Définissez d'abord la position de la fente.")
            return
            
        self.lbl_status.config(text="Centrage Astrométrique en cours...", foreground="red")
        threading.Thread(target=self.astrometry_center_process, daemon=True).start()

    def astrometry_center_process(self):
        try:
            img_path = "/tmp/spectro_astro.png"
            cv2.imwrite(img_path, self.last_img)
            
            # Lire la cible actuelle de la monture (où est censé être l'objet)
            self.send_cmd(":Gr#")
            ra_str = self.read_resp()
            self.send_cmd(":Gd#")
            dec_str = self.read_resp()
            
            import subprocess, re
            cmd = ["solve-field", img_path, "--overwrite", "--no-plots", "--cpulimit", "30"]
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            match = re.search(r"Field center: \(RA,Dec\) = \(([\d.]+),\s*([-\d.]+)\)", result.stdout)
            match_scale = re.search(r"pixel scale: ([\d.]+) arcsec/pix", result.stdout)
            match_rot = re.search(r"Up is ([\d.]+) degrees E of N", result.stdout)
            
            if match and match_scale:
                ra_center = float(match.group(1))
                dec_center = float(match.group(2))
                scale = float(match_scale.group(1)) / 3600.0 # deg/pixel
                rot = float(match_rot.group(1)) if match_rot else 0.0
                rot_rad = math.radians(rot)
                
                h, w = self.last_img.shape
                # Différence centre -> fente
                dx = self.target_x - w/2.0
                dy = -(self.target_y - h/2.0) # Inversé car l'axe y de l'image descend
                
                # Rotation du champ
                delta_ra = (dx * math.cos(rot_rad) - dy * math.sin(rot_rad)) * scale
                delta_dec = (dx * math.sin(rot_rad) + dy * math.cos(rot_rad)) * scale
                
                slit_ra_deg = ra_center + delta_ra / math.cos(math.radians(dec_center))
                slit_dec_deg = dec_center + delta_dec
                
                # Sync sur la fente
                s_ra_str = self.ra_to_meade(slit_ra_deg / 15.0)
                s_dec_str = self.dec_to_meade(slit_dec_deg)
                
                self.send_cmd(f":Sr{s_ra_str}#")
                self.send_cmd(f":Sd{s_dec_str}#")
                self.send_cmd(":CM#")
                time.sleep(0.5)
                
                # GoTo vers l'objet
                if ra_str and dec_str:
                    self.send_cmd(f":Sr{ra_str}#")
                    self.send_cmd(f":Sd{dec_str}#")
                    self.send_cmd(":MS#")
                
                self.root.after(0, lambda: self.lbl_status.config(text="Centrage terminé.", foreground="green"))
            else:
                self.root.after(0, lambda: self.lbl_status.config(text="Échec résolution astrométrique.", foreground="red"))
        except Exception as e:
            print("Erreur astrometrie:", e)
            self.root.after(0, lambda: self.lbl_status.config(text="Erreur astrométrie.", foreground="red"))

    def nudge_up(self, event):
        if self.target_y is not None: self.target_y -= 1
    def nudge_down(self, event):
        if self.target_y is not None: self.target_y += 1
    def nudge_left(self, event):
        if self.target_x is not None: self.target_x -= 1
    def nudge_right(self, event):
        if self.target_x is not None: self.target_x += 1

    def on_click_set_target(self, event):
        if getattr(self, 'spectro_mode_var', None) and self.spectro_mode_var.get():
            """Clic gauche pour positionner la cible de la fente/fibre"""
            self.target_x = event.x
            self.target_y = event.y
            self.lbl_status.config(text=f"Cible Fente définie sur: ({self.target_x}, {self.target_y})")
        else:
            """Mode Normal: Clic gauche sélectionne l'étoile ET fixe la cible ici"""
            self.star_x = event.x
            self.star_y = event.y
            self.target_x = event.x
            self.target_y = event.y
            self.lbl_status.config(text=f"Cible verrouillée sur: ({self.target_x}, {self.target_y})")

    def on_click_set_star(self, event):
        if getattr(self, 'spectro_mode_var', None) and self.spectro_mode_var.get():
            """Clic droit pour sélectionner manuellement l'étoile guide"""
            self.star_x = event.x
            self.star_y = event.y
            self.lbl_status.config(text=f"Étoile guide définie sur: ({self.star_x}, {self.star_y})")

    def start_guiding(self):
        if not self.ser or not self.camera:
            messagebox.showwarning("Attention", "Connectez la monture et la caméra.")
            return
        if self.target_x is None:
            messagebox.showwarning("Attention", "Veuillez définir la position de la fente (clic gauche).")
            return
        self.guiding = True
        self.lbl_status.config(text="Guidage en cours...", foreground="red")

    def stop_guiding(self):
        self.guiding = False
        self.lbl_status.config(text="Guidage arrêté.", foreground="blue")

    def track_star(self, img_gray):
        """Trouve l'étoile guide proche de l'ancienne position"""
        if self.star_x is None or self.star_y is None:
            # Cherche l'étoile la plus brillante si pas définie
            blur = cv2.GaussianBlur(img_gray, (5, 5), 0)
            _, thresh = cv2.threshold(blur, 200, 255, cv2.THRESH_BINARY)
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if contours:
                c = max(contours, key=cv2.contourArea)
                M = cv2.moments(c)
                if M["m00"] != 0:
                    self.star_x = int(M["m10"] / M["m00"])
                    self.star_y = int(M["m01"] / M["m00"])
            return

        # Tracking local autour de star_x, star_y
        h, w = img_gray.shape
        r = 25 # Rayon de recherche plus serré pour éviter les autres étoiles
        x1, x2 = max(0, self.star_x - r), min(w, self.star_x + r)
        y1, y2 = max(0, self.star_y - r), min(h, self.star_y + r)
        
        roi = img_gray[y1:y2, x1:x2].astype(np.float32)
        
        # Soustraction du fond de ciel (médiane) pour ne garder que le signal de l'étoile
        bg = np.median(roi)
        roi_clean = np.maximum(roi - bg, 0)
        
        # Calcul du Centre de Gravité (Centroid) directement sur les intensités
        # C'est la méthode de CCDCiel : très stable même si l'étoile est coupée en deux par la fente !
        M = cv2.moments(roi_clean)
        
        if M["m00"] > 0:
            cx = M["m10"] / M["m00"]
            cy = M["m01"] / M["m00"]
            self.star_x = int(x1 + cx)
            self.star_y = int(y1 + cy)

    def apply_guiding_pulse(self, dx, dy):
        """Envoie les commandes de guidage LX200 à la monture"""
        # dx, dy = Erreur en pixels (Target - Star)
        pulse_x = int(abs(dx) * self.ms_per_pixel_x * self.agressivite_x)
        pulse_y = int(abs(dy) * self.ms_per_pixel_y * self.agressivite_y)
        
        # Limite max de pulse (ex: 2000 ms)
        pulse_x = min(pulse_x, 2000)
        pulse_y = min(pulse_y, 2000)
        
        if pulse_x > 50:
            if dx > 0:
                self.send_cmd(f":Mge{pulse_x}#") # Est (à adapter selon orientation caméra)
            else:
                self.send_cmd(f":Mgw{pulse_x}#") # Ouest
                
        if pulse_y > 50:
            if dy > 0:
                self.send_cmd(f":Mgn{pulse_y}#") # Nord
            else:
                self.send_cmd(f":Mgs{pulse_y}#") # Sud

    def video_loop(self):
        while self.running:
            try:
                exp_us = int(self.exp_var.get()) * 1000
                self.camera.set_control_value(asi.ASI_EXPOSURE, exp_us)
                self.camera.set_control_value(asi.ASI_GAIN, int(self.gain_var.get()))
                
                img = self.camera.capture()
                if img.dtype == np.uint16:
                    img = (img / 256).astype(np.uint8)
                self.last_img = img
                
                if self.guiding:
                    self.track_star(img)
                    if self.star_x is not None:
                        dx = self.target_x - self.star_x
                        dy = self.target_y - self.star_y
                        self.apply_guiding_pulse(dx, dy)
                else:
                    # En mode non-guidage, on peut quand même tracker l'étoile pour voir si on la perd pas
                    self.track_star(img)
                    
                # Affichage RGB pour dessiner les croix
                img_rgb = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
                
                # Dessin Cible Fente/Lock
                if self.target_x is not None:
                    if getattr(self, 'spectro_mode_var', None) and self.spectro_mode_var.get():
                        cv2.drawMarker(img_rgb, (self.target_x, self.target_y), (0, 0, 255), cv2.MARKER_CROSS, 20, 2)
                        cv2.circle(img_rgb, (self.target_x, self.target_y), 10, (0, 0, 255), 1)
                    else:
                        cv2.drawMarker(img_rgb, (self.target_x, self.target_y), (0, 255, 255), cv2.MARKER_CROSS, 15, 1)
                    
                # Dessin Etoile (Carré Vert)
                if self.star_x is not None:
                    cv2.rectangle(img_rgb, (self.star_x - 10, self.star_y - 10), (self.star_x + 10, self.star_y + 10), (0, 255, 0), 2)
                
                img_resized = cv2.resize(img_rgb, (640, 480))
                pi = Image.fromarray(img_resized)
                pimg = ImageTk.PhotoImage(image=pi)
                
                self.canvas.create_image(0, 0, anchor=tk.NW, image=pimg)
                self.canvas.image = pimg
                
            except Exception as e:
                print(e)
                time.sleep(1)
            time.sleep(0.1)

if __name__ == "__main__":
    root = tk.Tk()
    app = AutoguideSpectroApp(root)
    tactile_wayland.brancher(root)
    root.mainloop()
