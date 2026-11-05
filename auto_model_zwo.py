import sys
import time
import math
import subprocess
import threading
import tkinter as tk
import tactile_wayland
from tkinter import ttk, messagebox
import re
from datetime import datetime

try:
    import zwoasi as asi
    import numpy as np
    import cv2
    from PIL import Image, ImageTk
    ZWO_AVAILABLE = True
except ImportError:
    ZWO_AVAILABLE = False

try:
    import ephem
    EPHEM_AVAILABLE = True
except ImportError:
    EPHEM_AVAILABLE = False

import serial
import serial.tools.list_ports

class AutoModelApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Création Modèle de Pointage (Auto-Align) ZWO - GotoAndrivet")
        
        self.ser = None
        self.camera = None
        self.running = False
        self.modeling = False
        
        # Load config to prefill values
        self.settings = {}
        import json
        from pathlib import Path
        config_path = Path.home() / ".config" / "goto_andrivet" / "config_tool_settings.json"
        if config_path.exists():
            try:
                self.settings = json.loads(config_path.read_text())
            except:
                pass
        
        self.setup_ui()
        
        if not ZWO_AVAILABLE or not EPHEM_AVAILABLE:
            messagebox.showerror("Erreur", "Modules manquants: zwoasi, numpy, opencv-python, pillow, ephem.")
            return

    def setup_ui(self):
        frm = ttk.Frame(self.root, padding=10)
        frm.pack(fill=tk.BOTH, expand=True)
        
        # 1. Hardware Connection
        fr_conn = ttk.LabelFrame(frm, text="1. Matériel (Monture & Caméra)", padding=5)
        fr_conn.pack(fill=tk.X, pady=5)
        
        self.port_var = tk.StringVar()
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.cb_ports = ttk.Combobox(fr_conn, textvariable=self.port_var, values=ports, width=15)
        if ports: self.cb_ports.current(0)
        self.cb_ports.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(fr_conn, text="Connecter Monture", command=self.connect_mount).pack(side=tk.LEFT, padx=5)
        self.lbl_conn = ttk.Label(fr_conn, text="Déconnectée", foreground="red")
        self.lbl_conn.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(fr_conn, text="Init Caméra ZWO", command=self.init_camera).pack(side=tk.LEFT, padx=20)
        self.lbl_cam = ttk.Label(fr_conn, text="Non initialisée", foreground="red")
        self.lbl_cam.pack(side=tk.LEFT, padx=5)
        
        # 2. Optics & Field of View
        fr_optics = ttk.LabelFrame(frm, text="2. Optique et Astrometry.net", padding=5)
        fr_optics.pack(fill=tk.X, pady=5)
        
        ttk.Label(fr_optics, text="Focale (mm):").grid(row=0, column=0, padx=5, pady=2)
        self.focale_var = tk.StringVar(value=str(self.settings.get("astro_focal", 400)))
        ttk.Entry(fr_optics, textvariable=self.focale_var, width=8).grid(row=0, column=1, padx=5, pady=2)
        
        ttk.Label(fr_optics, text="Taille Pixel (um):").grid(row=0, column=2, padx=5, pady=2)
        self.pixel_var = tk.StringVar(value=str(self.settings.get("astro_pixel", 3.75)))
        ttk.Entry(fr_optics, textvariable=self.pixel_var, width=8).grid(row=0, column=3, padx=5, pady=2)
        
        ttk.Label(fr_optics, text="Largeur Capteur (px):").grid(row=0, column=4, padx=5, pady=2)
        self.width_var = tk.StringVar(value=str(self.settings.get("astro_width", 1280)))
        ttk.Entry(fr_optics, textvariable=self.width_var, width=8).grid(row=0, column=5, padx=5, pady=2)
        
        ttk.Button(fr_optics, text="Calculer FOV & Index", command=self.calc_fov).grid(row=0, column=6, padx=10, pady=2)
        ttk.Button(fr_optics, text="Télécharger Index", command=self.download_indexes).grid(row=0, column=7, padx=5, pady=2)
        
        self.lbl_fov = ttk.Label(fr_optics, text="FOV: -- arcmin", font=("Arial", 10, "bold"))
        self.lbl_fov.grid(row=1, column=0, columnspan=3, padx=5, pady=5)
        
        self.lbl_index = ttk.Label(fr_optics, text="Index recommandés: --", foreground="blue")
        self.lbl_index.grid(row=1, column=3, columnspan=4, padx=5, pady=5)
        
        # 3. Model Generation
        fr_model = ttk.LabelFrame(frm, text="3. Modèle de Pointage Automatique", padding=5)
        fr_model.pack(fill=tk.X, pady=5)
        
        ttk.Label(fr_model, text="Nombre d'étoiles/points:").grid(row=0, column=0, padx=5, pady=5)
        self.pts_var = tk.StringVar(value="50")
        tk.Spinbox(fr_model, from_=3, to=100, textvariable=self.pts_var, width=5).grid(row=0, column=1, padx=5, pady=5)
        
        ttk.Label(fr_model, text="Exposition (ms):").grid(row=0, column=2, padx=5, pady=5)
        self.exp_var = tk.StringVar(value="2000")
        ttk.Entry(fr_model, textvariable=self.exp_var, width=8).grid(row=0, column=3, padx=5, pady=5)
        
        ttk.Button(fr_model, text="Démarrer Auto-Model", command=self.start_modeling).grid(row=0, column=4, padx=20, pady=5)
        ttk.Button(fr_model, text="Stopper", command=self.stop_modeling).grid(row=0, column=5, padx=5, pady=5)
        
        self.txt_log = tk.Text(frm, height=15, width=80)
        self.txt_log.pack(pady=10)

    def log(self, msg):
        self.txt_log.insert(tk.END, msg + "\n")
        self.txt_log.see(tk.END)
        self.root.update()

    def connect_mount(self):
        try:
            self.ser = serial.Serial(self.port_var.get(), 38400, timeout=1)
            self.lbl_conn.config(text="Connectée", foreground="green")
            self.log(f"Monture connectée sur {self.port_var.get()}")
        except Exception as e:
            messagebox.showerror("Erreur Serial", str(e))

    def init_camera(self):
        try:
            if asi.get_num_cameras() == 0:
                raise Exception("Aucune caméra trouvée.")
            self.camera = asi.Camera(0)
            self.camera.set_control_value(asi.ASI_BANDWIDTHOVERLOAD, self.camera.get_controls()['BandWidth']['MinValue'])
            self.camera.disable_dark_subtract()
            
            # Fetch properties to auto-fill pixel size and sensor width
            props = self.camera.get_camera_property()
            if 'PixelSize' in props:
                self.pixel_var.set(str(props['PixelSize']))
            if 'MaxWidth' in props:
                self.width_var.set(str(props['MaxWidth']))
            
            self.lbl_cam.config(text="Caméra prête", foreground="green")
            self.log(f"Caméra ZWO initialisée: Pixel {self.pixel_var.get()}µm, Largeur {self.width_var.get()}px.")
        except Exception as e:
            messagebox.showerror("Erreur ZWO", str(e))

    def calc_fov(self):
        try:
            focale = float(self.focale_var.get())
            pixel = float(self.pixel_var.get())
            width = float(self.width_var.get())
            
            # Taille du capteur en mm
            sensor_w_mm = (pixel * width) / 1000.0
            
            # FOV en degrés = 2 * arctan(d / (2*f))
            fov_deg = math.degrees(2 * math.atan(sensor_w_mm / (2 * focale)))
            fov_arcmin = fov_deg * 60.0
            
            self.lbl_fov.config(text=f"FOV (largeur): {fov_arcmin:.1f} arcmin ({fov_deg:.2f}°)")
            
            # Astrometry.net recommande des index couvrant 10% à 100% du FOV
            min_index = fov_arcmin * 0.1
            max_index = fov_arcmin * 1.0
            
            self.lbl_index.config(text=f"Index recommandés: de {min_index:.1f}' à {max_index:.1f}' (ex: index-41xx ou 42xx)")
            self.log(f"Calcul FOV: {fov_arcmin:.1f} arcmin. Index utiles: {min_index:.1f}' à {max_index:.1f}'.")
            
        except ValueError:
            messagebox.showerror("Erreur", "Valeurs optiques invalides.")

    def download_indexes(self):
        try:
            focale = float(self.focale_var.get())
            pixel = float(self.pixel_var.get())
            width = float(self.width_var.get())
            sensor_w_mm = (pixel * width) / 1000.0
            fov_deg = math.degrees(2 * math.atan(sensor_w_mm / (2 * focale)))
            fov_arcmin = fov_deg * 60.0
            min_index = fov_arcmin * 0.1
            max_index = fov_arcmin * 1.0
        except ValueError:
            messagebox.showerror("Erreur", "Calculez d'abord le FOV.")
            return

        target_scales = []
        scales_map = {
            19: [1400, 2000], 18: [970, 1400], 17: [680, 1000], 16: [470, 680],
            15: [330, 480], 14: [230, 340], 13: [160, 240], 12: [110, 170],
            11: [80, 120], 10: [55, 85], 9: [40, 60], 8: [28, 42], 7: [20, 30]
        }
        for sc, r in scales_map.items():
            if r[1] >= min_index and r[0] <= max_index:
                target_scales.append(sc)
        if not target_scales: target_scales = [11,12,13]
        
        min_sc = max(7, min(target_scales) - 1)
        max_sc = min(19, max(target_scales) + 1)
        scales = list(range(min_sc, max_sc + 1))
        
        script = f"""
import tkinter as tk
from goto_andrivet_config_tool import ConfigToolApp
app = ConfigToolApp()
app.withdraw()
app.download_astrometry_indexes({scales})
def check_toplevels():
    if not any(isinstance(w, tk.Toplevel) for w in app.winfo_children()):
        app.destroy()
    else:
        app.after(500, check_toplevels)
app.after(500, check_toplevels)
app.mainloop()
"""
        import subprocess, os
        from pathlib import Path
        venv_python = str(Path.home() / ".goto_andrivet" / "venv" / "bin" / "python3")
        python_path = venv_python if os.path.exists(venv_python) else sys.executable
        subprocess.Popen([python_path, "-c", script], cwd=str(Path(__file__).parent))

    def send_cmd(self, cmd, wait_resp=False):
        if self.ser:
            self.ser.write(cmd.encode('ascii'))
            if wait_resp:
                return self.ser.read_until(b'#').decode('ascii').strip('#')
            time.sleep(0.1)
        return ""

    def start_modeling(self):
        if not self.ser or not self.camera:
            messagebox.showwarning("Attention", "Connectez la monture et la caméra d'abord.")
            return
        if self.modeling:
            return
        
        self.modeling = True
        threading.Thread(target=self.modeling_process, daemon=True).start()

    def stop_modeling(self):
        self.modeling = False
        self.log("Arrêt demandé...")

    def dec_to_meade(self, deg):
        sign = '+' if deg >= 0 else '-'
        deg = abs(deg)
        d = int(deg)
        m = int((deg - d) * 60)
        s = int((deg - d - m/60.0) * 3600)
        return f"{sign}{d:02d}*{m:02d}'{s:02d}"

    def ra_to_meade(self, hours):
        h = int(hours)
        m = int((hours - h) * 60)
        s = int((hours - h - m/60.0) * 3600)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def parse_solve_output(self, output):
        # Cherche "Field center: (RA,Dec) = (12.34, -56.78)" dans la sortie de solve-field
        match = re.search(r"Field center: \(RA,Dec\) = \(([\d.]+),\s*([-\d.]+)\)", output)
        if match:
            ra_deg = float(match.group(1))
            dec_deg = float(match.group(2))
            return (ra_deg / 15.0, dec_deg) # RA en heures, Dec en degrés
        return None

    def capture_image(self, filename):
        exp_us = int(self.exp_var.get()) * 1000
        self.camera.set_control_value(asi.ASI_EXPOSURE, exp_us)
        img = self.camera.capture()
        if img.dtype == np.uint16:
            img = (img / 256).astype(np.uint8)
        cv2.imwrite(filename, img)

    def modeling_process(self):
        try:
            num_pts = int(self.pts_var.get())
            self.log(f"--- Démarrage Auto-Model avec {num_pts} points ---")
            
            # Position locale
            obs = ephem.Observer()
            obs.lat = ephem.degrees(str(self.cfg.get('latitude', '45.0')))
            obs.lon = ephem.degrees(str(self.cfg.get('longitude', '0.0')))
            
            success_count = 0
            
            for i in range(num_pts):
                if not self.modeling:
                    break
                    
                self.log(f"\nPoint {i+1}/{num_pts}")
                
                # Génération d'un point au hasard (Alt > 30°, Az 0-360)
                alt = 30 + (i * (50.0 / num_pts)) + (np.random.rand() * 10) # Repartition altitude 30-80
                az = (i * (360.0 / num_pts)) % 360
                
                obs.date = ephem.now()
                # Convert Alt/Az -> RA/Dec
                ra_rad, dec_rad = obs.radec_of(ephem.degrees(str(az)), ephem.degrees(str(alt)))
                ra_h = float(ra_rad) * 12.0 / math.pi
                dec_d = float(dec_rad) * 180.0 / math.pi
                
                ra_str = self.ra_to_meade(ra_h)
                dec_str = self.dec_to_meade(dec_d)
                
                self.log(f" Cible générée Alt:{alt:.1f} Az:{az:.1f} -> RA:{ra_str} Dec:{dec_str}")
                
                # Slew
                self.send_cmd(f":Sr{ra_str}#")
                self.send_cmd(f":Sd{dec_str}#")
                self.log(" Pointage en cours...")
                self.send_cmd(":MS#")
                
                # Attente dynamique de fin de mouvement (Slewing)
                while self.modeling:
                    time.sleep(1.0)
                    resp = self.send_cmd(":D#", wait_resp=True)
                    if resp != "|":
                        break
                
                if not self.modeling: break
                
                # Prise de vue
                self.log(" Capture image ZWO...")
                img_path = "/tmp/automodel_capture.png"
                self.capture_image(img_path)
                
                # Astrométrie
                self.log(" Résolution (Astrometry.net)...")
                # On limite le temps de CPU et on ajoute le paramètre --guess pour accélérer si on connait à peu près
                # mais ici c'est un pointage aveugle potentiellement donc on laisse chercher large
                cmd = ["solve-field", img_path, "--overwrite", "--no-plots", "--cpulimit", "30", "--scale-units", "arcminwidth"]
                
                # Optionnel : restreindre l'échelle si FOV calculé
                try:
                    fov = float(self.lbl_fov.cget("text").split()[2])
                    cmd.extend(["--scale-low", str(fov*0.8), "--scale-high", str(fov*1.2)])
                except:
                    pass

                result = subprocess.run(cmd, capture_output=True, text=True)
                
                coords = self.parse_solve_output(result.stdout)
                if coords:
                    solved_ra_h, solved_dec_d = coords
                    s_ra_str = self.ra_to_meade(solved_ra_h)
                    s_dec_str = self.dec_to_meade(solved_dec_d)
                    
                    self.log(f" Résolu ! RA: {s_ra_str} Dec: {s_dec_str}")
                    
                    # Sync Monture
                    self.send_cmd(f":Sr{s_ra_str}#")
                    self.send_cmd(f":Sd{s_dec_str}#")
                    self.send_cmd(":CM#")
                    self.log(" Monture synchronisée avec ce point.")
                    success_count += 1
                else:
                    self.log(" Échec de la résolution astrométrique.")
                    
                time.sleep(1)
                
            self.log(f"--- Terminé ! Modèle créé avec {success_count}/{num_pts} points. ---")
            
        except Exception as e:
            self.log(f"Erreur: {str(e)}")
        finally:
            self.modeling = False

if __name__ == "__main__":
    root = tk.Tk()
    app = AutoModelApp(root)
    tactile_wayland.brancher(root)
    root.mainloop()
