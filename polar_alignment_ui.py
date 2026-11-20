import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import os
import math

class PolarAlignmentWindow(tk.Toplevel):
    def __init__(self, parent_app):
        super().__init__(parent_app)
        self.app = parent_app
        self.title("Assistant de Mise en Station (Polar Alignment)")
        self.geometry("600x500")
        self.configure(bg="#c0c0c0")
        
        self.points = [] # list of (ra, dec)
        self.cor = None # (ra, dec)
        self.p3 = None
        
        f_title = ("Arial", 12, "bold")
        self.lbl_step = tk.Label(self, text="Étape 1/4: Initialisation", bg="#c0c0c0", font=f_title)
        self.lbl_step.pack(pady=10)
        
        self.txt_info = tk.Text(self, height=10, width=60, bg="white", fg="black")
        self.txt_info.pack(pady=10)
        
        self.btn_action = tk.Button(self, text="Démarrer (Prendre Image 1)", command=self.do_action, font=("Arial", 11, "bold"))
        self.btn_action.pack(pady=10)
        
        self.lbl_error = tk.Label(self, text="", bg="#c0c0c0", fg="red", font=("Arial", 14, "bold"))
        self.lbl_error.pack(pady=10)
        
        self.step = 1
        self.update_info("Pointez le télescope n'importe où dans le ciel (vers le Sud, l'Est ou l'Ouest si le Nord est caché).\nLa méthode à 3 points calculera le pôle automatiquement.\nCliquez sur Démarrer pour prendre la première image.")

    def update_info(self, text):
        self.txt_info.insert(tk.END, text + "\n")
        self.txt_info.see(tk.END)

    def do_action(self):
        if self.step == 1:
            self.take_and_solve(1)
        elif self.step == 2:
            self.take_and_solve(2)
        elif self.step == 3:
            self.take_and_solve(3)
        elif self.step == 4:
            self.live_refresh()

    def take_and_solve(self, step_num):
        self.btn_action.config(state="disabled", text="Capture et Résolution en cours...")
        def task():
            try:
                cam_idx = self.app.get_selected_camera_idx()
                exp = float(self.app.exp_entry.get())
                gain = int(self.app.gain_entry.get())
                
                script = f"""
import sys
import time
try:
    import zwoasi as asi
    asi.init('/usr/lib/x86_64-linux-gnu/libASICamera2.so')
    cams = asi.list_cameras()
    if not cams:
        sys.stderr.write("Erreur: Aucune caméra ZWO détectée par asi.list_cameras().\\n")
        sys.exit(1)
    c = asi.Camera({cam_idx})
    c.set_control_value(asi.ASI_EXPOSURE, int({exp} * 1000000))
    c.set_control_value(asi.ASI_GAIN, {gain}, auto=False)
    c.set_image_type(asi.ASI_IMG_RAW8)
    
    time.sleep(0.2)
    try:
        c.capture(filename='/tmp/capture_pa.png')
    except asi.ZWO_CaptureError:
        time.sleep(0.5)
        c.capture(filename='/tmp/capture_pa.png')
except Exception as e:
    sys.stderr.write("Erreur ZWO: " + str(e) + "\\n")
    sys.exit(1)
"""
                import subprocess
                import sys
                import os
                from pathlib import Path
                venv_python = str(Path.home() / ".goto_andrivet" / "venv" / "bin" / "python3")
                py_exe = venv_python if os.path.exists(venv_python) else sys.executable
                
                res = subprocess.run([py_exe, "-c", script], capture_output=True, text=True)
                if res.returncode != 0:
                    self.after(0, lambda err=res.stderr: messagebox.showerror("Erreur", "Echec capture: " + err))
                    return
                
                self.after(0, lambda step=step_num: self.update_info(f"Image {step} capturée. Résolution Astrométrique..."))
                
                # Solve
                sf_cmd = ["solve-field", "/tmp/capture_pa.png", "--overwrite", "--no-plots", "--cpulimit", "30"]
                try:
                    foc = float(self.app.foc_entry.get())
                    px = 3.76
                    if os.path.exists('/tmp/astro_px_size.txt'):
                        px = float(open('/tmp/astro_px_size.txt').read().strip())
                    sc = 206.265 * px / foc
                    sf_cmd.extend(["--scale-units", "arcsecperpix", "--scale-low", str(sc*0.9), "--scale-high", str(sc*1.1)])
                except:
                    pass
                
                res = subprocess.run(sf_cmd, capture_output=True, text=True)
                
                ra, dec = None, None
                for line in res.stdout.split('\n'):
                    if "Field center: (RA,Dec) =" in line:
                        parts = line.split('=')[1].strip().split()
                        ra = float(parts[0].replace('(', '').replace(',', ''))
                        dec = float(parts[1].replace(')', '').replace('.', '.', 1)) # handle negative correctly
                        break
                
                if ra is None or dec is None:
                    # Retry with API if enabled
                    if self.app.astro_mode_var.get() == "api":
                        self.after(0, lambda: self.update_info("Essai avec l'API en ligne..."))
                        succ, data = self.app.run_astrometry_api("/tmp/capture_pa.png")
                        if succ:
                            ra = data.get("ra", 0)
                            dec = data.get("dec", 0)
                
                if ra is None or dec is None:
                    self.after(0, lambda: self.update_info(f"Echec de la résolution pour l'image {step_num}. Veuillez réessayer."))
                    self.after(0, lambda: self.btn_action.config(state="normal", text=f"Réessayer Image {step_num}"))
                    return
                
                self.points.append((ra, dec))
                self.after(0, lambda: self.update_info(f"Succès ! RA: {ra:.4f}°, DEC: {dec:.4f}°"))
                
                def automated_rotation(next_step):
                    if not self.app.is_connected or not getattr(self.app, 'ser', None):
                        self.after(0, lambda: self.update_info("\nMonture non connectée au PC. Veuillez tourner l'axe AD manuellement d'environ 30° puis cliquez sur Continuer."))
                        self.after(0, lambda: self.btn_action.config(state="normal", text=f"Continuer (Prendre Image {next_step})"))
                        return
                    
                    try:
                        self.after(0, lambda: self.update_info("\nRotation automatique de la monture en cours (30°)... Veuillez patienter."))
                        
                        # Demander la vitesse actuelle
                        self.app.ser.write(b":Bv#")
                        speed_raw = self.app.ser.read_until(b"#").decode('ascii', errors='ignore').strip('#')
                        speed = 2.0
                        if speed_raw.isdigit():
                            speed = int(speed_raw) / 10.0
                            if speed <= 0: speed = 2.0
                        
                        slew_time = 30.0 / speed
                        self.app.ser.write(b":Me#") # Move East on RA
                        time.sleep(slew_time)
                        self.app.ser.write(b":Q#")  # Stop
                        time.sleep(2) # Settle time for vibrations
                        
                        self.after(0, lambda: self.take_and_solve(next_step))
                    except Exception as e:
                        try: self.app.ser.write(b":Q#")
                        except: pass
                        self.after(0, lambda msg=str(e): self.update_info(f"Erreur lors de la rotation automatique : {msg}"))
                        self.after(0, lambda: self.btn_action.config(state="normal", text=f"Continuer (Prendre Image {next_step})"))

                if step_num == 1:
                    self.step = 2
                    self.after(0, lambda: self.lbl_step.config(text="Étape 2/4: Première Rotation"))
                    threading.Thread(target=automated_rotation, args=(2,), daemon=True).start()
                elif step_num == 2:
                    self.step = 3
                    self.after(0, lambda: self.lbl_step.config(text="Étape 3/4: Deuxième Rotation"))
                    threading.Thread(target=automated_rotation, args=(3,), daemon=True).start()
                elif step_num == 3:
                    self.p3 = (ra, dec)
                    self.calculate_cor()
                    
            except Exception as e:
                self.after(0, lambda err=str(e): messagebox.showerror("Erreur", err))
                self.after(0, lambda: self.btn_action.config(state="normal", text="Réessayer"))

        threading.Thread(target=task, daemon=True).start()

    def calculate_cor(self):
        import numpy as np
        def sph2cart(ra, dec):
            r = math.radians(ra)
            d = math.radians(dec)
            return np.array([math.cos(d)*math.cos(r), math.cos(d)*math.sin(r), math.sin(d)])
        
        v1 = sph2cart(self.points[0][0], self.points[0][1])
        v2 = sph2cart(self.points[1][0], self.points[1][1])
        v3 = sph2cart(self.points[2][0], self.points[2][1])
        
        n = np.cross(v2 - v1, v3 - v1)
        norm = np.linalg.norm(n)
        if norm == 0:
            self.after(0, lambda: self.update_info("Erreur mathématique: Les points sont alignés. Rotation insuffisante ?"))
            return
            
        n = n / norm
        try:
            is_south = float(self.app.lat_entry.get().replace(",", ".")) < 0
        except (AttributeError, ValueError):
            is_south = False
        if is_south and n[2] > 0: n = -n
        elif not is_south and n[2] < 0: n = -n
        
        dec_cor = math.degrees(math.asin(max(-1.0, min(1.0, n[2]))))
        ra_cor = math.degrees(math.atan2(n[1], n[0]))
        if ra_cor < 0: ra_cor += 360
        
        self.cor = (ra_cor, dec_cor)
        error_arcmin = (90.0 - dec_cor) * 60.0
        
        self.step = 4
        self.after(0, lambda: [self.lbl_step.config(text="Étape 4/4: Réglage des vis Alt/Az"),
                               self.lbl_error.config(text=f"Erreur d'alignement polaire : {error_arcmin:.1f} arcmin"),
                               self.update_info(f"\nCentre de rotation calculé ! Erreur totale: {error_arcmin:.1f} arcmin.\nUtilisez les vis de votre monture pour réduire l'erreur.\nCliquez sur 'Actualiser' pour prendre une nouvelle image et recalculer l'erreur en direct."),
                               self.btn_action.config(state="normal", text="Actualiser (Live Update)")])

    def live_refresh(self):
        self.btn_action.config(state="disabled", text="Actualisation...")
        def task():
            try:
                # Capture
                cam_idx = self.app.get_selected_camera_idx()
                exp = float(self.app.exp_entry.get())
                gain = int(self.app.gain_entry.get())
                
                script = f"""
import sys
import time
try:
    import zwoasi as asi
    asi.init('/usr/lib/x86_64-linux-gnu/libASICamera2.so')
    cams = asi.list_cameras()
    if not cams:
        sys.stderr.write("Erreur: Aucune caméra ZWO détectée par asi.list_cameras().\\n")
        sys.exit(1)
    c = asi.Camera({cam_idx})
    c.set_control_value(asi.ASI_EXPOSURE, int({exp} * 1000000))
    c.set_control_value(asi.ASI_GAIN, {gain}, auto=False)
    c.set_image_type(asi.ASI_IMG_RAW8)
    
    time.sleep(0.2)
    try:
        c.capture(filename='/tmp/capture_pa.png')
    except asi.ZWO_CaptureError:
        time.sleep(0.5)
        c.capture(filename='/tmp/capture_pa.png')
except Exception as e:
    sys.stderr.write("Erreur ZWO: " + str(e) + "\\n")
    sys.exit(1)
"""
                import subprocess
                import sys
                import os
                from pathlib import Path
                venv_python = str(Path.home() / ".goto_andrivet" / "venv" / "bin" / "python3")
                py_exe = venv_python if os.path.exists(venv_python) else sys.executable
                res = subprocess.run([py_exe, "-c", script], capture_output=True, text=True)
                if res.returncode != 0:
                    self.after(0, lambda err=res.stderr: messagebox.showerror("Erreur", "Echec capture: " + err))
                    self.after(0, lambda: self.btn_action.config(state="normal", text="Actualiser (Live Update)"))
                    return
                
                sf_cmd = ["solve-field", "/tmp/capture_pa.png", "--overwrite", "--no-plots", "--cpulimit", "30"]
                try:
                    foc = float(self.app.foc_entry.get())
                    px = 3.76
                    if os.path.exists('/tmp/astro_px_size.txt'): px = float(open('/tmp/astro_px_size.txt').read().strip())
                    sc = 206.265 * px / foc
                    sf_cmd.extend(["--scale-units", "arcsecperpix", "--scale-low", str(sc*0.9), "--scale-high", str(sc*1.1)])
                except:
                    pass
                    
                res = subprocess.run(sf_cmd, capture_output=True, text=True)
                
                ra, dec = None, None
                for line in res.stdout.split('\n'):
                    if "Field center: (RA,Dec) =" in line:
                        parts = line.split('=')[1].strip().split()
                        ra = float(parts[0].replace('(', '').replace(',', ''))
                        dec = float(parts[1].replace(')', '').replace('.', '.', 1))
                        break
                        
                if ra is None or dec is None:
                    self.after(0, lambda: self.lbl_error.config(text="Echec résolution. Patientez ou vérifiez la mise au point.", fg="orange"))
                else:
                    # New position p4
                    # cor_new = cor_old + (p4 - p3) approx in tangent space
                    delta_ra = ra - self.p3[0]
                    delta_dec = dec - self.p3[1]
                    new_cor_ra = self.cor[0] + delta_ra
                    new_cor_dec = self.cor[1] + delta_dec
                    
                    # Update references for next iteration
                    self.p3 = (ra, dec)
                    self.cor = (new_cor_ra, new_cor_dec)
                    
                    error_arcmin = (90.0 - new_cor_dec) * 60.0
                    color = "green" if abs(error_arcmin) < 2.0 else "red"
                    
                    self.after(0, lambda e=error_arcmin, c=color: self.lbl_error.config(text=f"Erreur polaire : {e:.1f}'", fg=c))
                    
            finally:
                self.after(0, lambda: self.btn_action.config(state="normal", text="Actualiser (Live Update)"))

        threading.Thread(target=task, daemon=True).start()

def open_pa_window(app):
    PolarAlignmentWindow(app)
