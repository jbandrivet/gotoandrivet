# -*- mode: python -*-
# Trois .exe, une seule analyse. SRC = copie exacte du dépôt, préparée par preparer_vm.sh et fabriquer.bat.
import os
SRC = os.environ["SRC"]
ICI = os.path.dirname(os.path.abspath(SPEC))
a = Analysis([os.path.join(ICI, "lanceur.py")], pathex=[SRC],
             datas=[(os.path.join(SRC, d), d) for d in ("mega_monture", "teensy_monture", "teensy_raquette", "icons")]
                   + [(os.path.join(ICI, "version_git.txt"), ".")],
             hiddenimports=["goto_andrivet", "goto_andrivet_config_tool", "raquette_virtuelle", "guidage", "photo", "ciel_donnees",
                            "mise_a_jour", "tactile_wayland", "zwocaa", "zwoeaf", "serial.tools.list_ports", "ephem", "requests",
                            "PIL.ImageTk"],
             excludes=["cv2", "zwoasi", "matplotlib", "pandas", "scipy", "IPython", "pytest"])
pyz = PYZ(a.pure)
for nom, icone in (("GotoAndrivet_Carte_du_ciel", "carte.ico"), ("GotoAndrivet_Configurateur", "config.ico"), ("GotoAndrivet_Raquette", "carte.ico")):
    EXE(pyz, a.scripts, a.binaries, a.datas, name=nom, console=False, upx=False, icon=os.path.join(ICI, icone))
