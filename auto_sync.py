#!/usr/bin/env python3
import sys
import serial
import time
import json
from datetime import datetime
from pathlib import Path


def lire_reponse_sc(ser):
    """Lit la réponse à :SC. Le firmware répond "1" (comme OnStep) depuis le
    2026-11-17, "1Updating#...#" avant : on lit le premier caractère puis on vide
    le reste, ce qui convient aux deux."""
    r = ser.read(1)
    time.sleep(0.15)
    ser.reset_input_buffer()
    return r

def main():
    if len(sys.argv) > 1:
        port = sys.argv[1]
    else:
        # Fallback to config tool port
        cfg_path = Path.home() / ".config" / "goto_andrivet" / "settings.json"
        port = "/dev/ttyACM0"
        if cfg_path.exists():
            try:
                cfg = json.loads(cfg_path.read_text())
                port = cfg.get("mount_port", "/dev/ttyACM0")
            except: pass

    try:
        ser = serial.Serial(port, 38400, timeout=1.0)
        time.sleep(2.5) # Wait for Arduino reset after DTR
        
        now = datetime.now()
        
        # 1. Date
        ser.write(f":SC{now.month:02d}/{now.day:02d}/{now.year%100:02d}#".encode('ascii'))
        lire_reponse_sc(ser)
        
        # 2. Heure
        ser.write(f":SL{now.hour:02d}:{now.minute:02d}:{now.second:02d}#".encode('ascii'))
        ser.read_until(b"#")
        
        # 3. Timezone
        utc_offset = -time.timezone / 3600.0
        if time.daylight and time.localtime().tm_isdst:
            utc_offset = -time.altzone / 3600.0
        # :SG (LX200) : heures à ajouter à l'heure locale pour obtenir l'UTC, donc UTC+2 -> :SG-02
        sign = '-' if utc_offset >= 0 else '+'
        ser.write(f":SG{sign}{int(abs(utc_offset)):02d}#".encode('ascii'))
        ser.read_until(b"#")
        
        ser.close()
    except Exception as e:
        print(f"Erreur de synchro: {e}")

if __name__ == "__main__":
    main()
