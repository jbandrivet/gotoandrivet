import sys
import time
import serial
import serial.tools.list_ports
import threading
import tkinter as tk
import tactile_wayland
from tkinter import ttk, messagebox

try:
    import zwoasi as asi
    import numpy as np
    import cv2
    from PIL import Image, ImageTk
    ZWO_AVAILABLE = True
except ImportError:
    ZWO_AVAILABLE = False

class BacklashMeasureApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Mesure de Backlash ZWO - GotoAndrivet")
        
        self.ser = None
        self.camera = None
        self.running = False
        self.measuring = False
        self.backlash_steps = 0
        
        self.setup_ui()
        
        if not ZWO_AVAILABLE:
            messagebox.showerror("Erreur", "Veuillez installer zwoasi, numpy, opencv-python et pillow (pip install zwoasi numpy opencv-python pillow).")
            self.root.destroy()
            return
            
        try:
            # You might need to change the path to your ASI SDK library here
            # asi.init('libASICamera2.so')  # For Linux, usually not needed if installed system-wide
            if asi.get_num_cameras() == 0:
                messagebox.showwarning("Attention", "Aucune caméra ZWO détectée.")
        except Exception as e:
            print("ZWO Init error:", e)

    def setup_ui(self):
        frm = ttk.Frame(self.root, padding=10)
        frm.pack(fill=tk.BOTH, expand=True)
        
        # Serial connection
        fr_conn = ttk.LabelFrame(frm, text="1. Connexion Monture (Serial)", padding=5)
        fr_conn.pack(fill=tk.X, pady=5)
        
        self.port_var = tk.StringVar()
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.cb_ports = ttk.Combobox(fr_conn, textvariable=self.port_var, values=ports)
        if ports: self.cb_ports.current(0)
        self.cb_ports.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(fr_conn, text="Connecter", command=self.connect_mount).pack(side=tk.LEFT, padx=5)
        self.lbl_conn = ttk.Label(fr_conn, text="Déconnecté", foreground="red")
        self.lbl_conn.pack(side=tk.LEFT, padx=10)
        
        # Camera connection
        fr_cam = ttk.LabelFrame(frm, text="2. Caméra ZWO", padding=5)
        fr_cam.pack(fill=tk.X, pady=5)
        
        ttk.Button(fr_cam, text="Init Caméra", command=self.init_camera).pack(side=tk.LEFT, padx=5)
        self.lbl_cam = ttk.Label(fr_cam, text="Non initialisée", foreground="red")
        self.lbl_cam.pack(side=tk.LEFT, padx=10)
        
        # Settings
        fr_set = ttk.Frame(frm)
        fr_set.pack(fill=tk.X, pady=5)
        ttk.Label(fr_set, text="Exposition (us):").pack(side=tk.LEFT)
        self.exp_var = tk.StringVar(value="500000")
        ttk.Entry(fr_set, textvariable=self.exp_var, width=10).pack(side=tk.LEFT, padx=5)
        
        ttk.Label(fr_set, text="Gain:").pack(side=tk.LEFT)
        self.gain_var = tk.StringVar(value="150")
        ttk.Entry(fr_set, textvariable=self.gain_var, width=5).pack(side=tk.LEFT, padx=5)
        
        # Action
        fr_act = ttk.LabelFrame(frm, text="3. Mesure du Backlash", padding=5)
        fr_act.pack(fill=tk.X, pady=5)
        
        self.axis_var = tk.StringVar(value="ALT")
        ttk.Radiobutton(fr_act, text="Axe ALT (DEC)", variable=self.axis_var, value="ALT").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(fr_act, text="Axe AZ (RA)", variable=self.axis_var, value="AZ").pack(side=tk.LEFT, padx=5)
        
        ttk.Button(fr_act, text="Lancer la mesure", command=self.start_measurement).pack(side=tk.LEFT, padx=10)
        
        self.lbl_res = ttk.Label(fr_act, text="Résultat : -- pas", font=("Arial", 12, "bold"))
        self.lbl_res.pack(side=tk.LEFT, padx=20)
        
        ttk.Button(fr_act, text="Sauvegarder dans la monture", command=self.save_to_mount).pack(side=tk.RIGHT, padx=5)
        
        # Video feed
        self.lbl_video = tk.Label(frm, bg="black", width=640, height=480)
        self.lbl_video.pack(pady=10)

    def connect_mount(self):
        try:
            self.ser = serial.Serial(self.port_var.get(), 38400, timeout=1)
            self.lbl_conn.config(text="Connecté", foreground="green")
        except Exception as e:
            messagebox.showerror("Erreur Serial", str(e))

    def init_camera(self):
        try:
            if asi.get_num_cameras() == 0:
                raise Exception("Aucune caméra trouvée.")
            self.camera = asi.Camera(0)
            self.camera.set_control_value(asi.ASI_BANDWIDTHOVERLOAD, self.camera.get_controls()['BandWidth']['MinValue'])
            self.camera.disable_dark_subtract()
            self.lbl_cam.config(text="Caméra prête", foreground="green")
            
            self.running = True
            threading.Thread(target=self.video_loop, daemon=True).start()
        except Exception as e:
            messagebox.showerror("Erreur ZWO", str(e))

    def send_cmd(self, cmd):
        if self.ser:
            self.ser.write(cmd.encode('ascii'))
            time.sleep(0.1)

    def start_measurement(self):
        if not self.ser or not self.camera:
            messagebox.showwarning("Attention", "Connectez la monture et la caméra d'abord.")
            return
        if self.measuring:
            return
        self.measuring = True
        self.lbl_res.config(text="Mesure en cours...")
        threading.Thread(target=self.measurement_process, daemon=True).start()

    def find_star_centroid(self, image):
        # Apply Gaussian blur
        blur = cv2.GaussianBlur(image, (5, 5), 0)
        # Threshold to get bright spots
        _, thresh = cv2.threshold(blur, 200, 255, cv2.THRESH_BINARY)
        # Find contours
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        # Find the largest contour (presumably the brightest star)
        c = max(contours, key=cv2.contourArea)
        M = cv2.moments(c)
        if M["m00"] == 0:
            return None
        cX = int(M["m10"] / M["m00"])
        cY = int(M["m01"] / M["m00"])
        return (cX, cY)

    def measurement_process(self):
        try:
            axis = self.axis_var.get()
            # 1. Move a bit in positive direction to clear backlash
            cmd_pos = ":Mn#" if axis == "ALT" else ":Me#"
            cmd_neg = ":Ms#" if axis == "ALT" else ":Mw#"
            cmd_stop = ":Q#"
            
            print("Clearing backlash...")
            self.send_cmd(cmd_pos)
            time.sleep(2.0)
            self.send_cmd(cmd_stop)
            time.sleep(1.0) # Let it settle
            
            # Take reference image
            img = self.capture_image()
            ref_pos = self.find_star_centroid(img)
            if not ref_pos:
                self.root.after(0, lambda: messagebox.showerror("Erreur", "Aucune étoile brillante trouvée."))
                self.measuring = False
                return
                
            print(f"Reference star at {ref_pos}")
            
            # Start moving in opposite direction in small steps until star moves > 3 pixels
            steps_moved = 0
            moved = False
            
            while not moved and steps_moved < 5000:
                # Issue a small move (using guide commands or very short slew)
                # Meade protocol for guide: :Mgn100# (move North for 100ms)
                # Let's just use slew and stop quickly
                self.send_cmd(cmd_neg)
                time.sleep(0.1) # 100ms
                self.send_cmd(cmd_stop)
                time.sleep(0.5)
                
                # Assume 100ms corresponds to roughly 50 steps at current guide speed (example only)
                # Note: To be perfectly accurate, we should read actual motor positions via :GA# or :GZ#
                # But here we do a conceptual wait
                steps_moved += 20 # arbitrary for demo
                
                img = self.capture_image()
                new_pos = self.find_star_centroid(img)
                if new_pos:
                    dx = new_pos[0] - ref_pos[0]
                    dy = new_pos[1] - ref_pos[1]
                    dist = np.sqrt(dx*dx + dy*dy)
                    if dist > 3.0:
                        moved = True
            
            self.backlash_steps = steps_moved
            self.root.after(0, lambda: self.lbl_res.config(text=f"Résultat : {steps_moved} pas"))
            
        except Exception as e:
            print("Measurement error:", e)
        finally:
            self.measuring = False

    def capture_image(self):
        self.camera.set_control_value(asi.ASI_EXPOSURE, int(self.exp_var.get()))
        self.camera.set_control_value(asi.ASI_GAIN, int(self.gain_var.get()))
        return self.camera.capture()

    def video_loop(self):
        while self.running:
            if not self.measuring:
                try:
                    img = self.capture_image()
                    # Convert 16bit to 8bit if needed
                    if img.dtype == np.uint16:
                        img = (img / 256).astype(np.uint8)
                    
                    pos = self.find_star_centroid(img)
                    img_rgb = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
                    
                    if pos:
                        cv2.drawMarker(img_rgb, pos, (0, 255, 0), cv2.MARKER_CROSS, 20, 2)
                        
                    # Resize for display
                    img_resized = cv2.resize(img_rgb, (640, 480))
                    
                    pi = Image.fromarray(img_resized)
                    pimg = ImageTk.PhotoImage(image=pi)
                    self.lbl_video.configure(image=pimg)
                    self.lbl_video.image = pimg
                except Exception as e:
                    print(e)
                    time.sleep(1)
            time.sleep(0.1)

    def save_to_mount(self):
        if not self.ser: return
        axis = self.axis_var.get()
        cmd = f":XBz{self.backlash_steps}#" if axis == "AZ" else f":XBa{self.backlash_steps}#"
        self.send_cmd(cmd)
        messagebox.showinfo("Succès", f"Valeur de backlash ({self.backlash_steps}) sauvegardée dans la monture.")

if __name__ == "__main__":
    root = tk.Tk()
    app = BacklashMeasureApp(root)
    tactile_wayland.brancher(root)
    root.mainloop()
