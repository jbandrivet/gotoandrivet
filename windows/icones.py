"""Convertit les deux icônes SVG du dépôt en .ico pour Windows."""
import sys
from pathlib import Path
import gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf
from PIL import Image
src, dst = Path(sys.argv[1]), Path(sys.argv[2])
for svg, ico in (("goto_andrivet.svg", "carte.ico"), ("goto_andrivet_config.svg", "config.ico")):
    p = GdkPixbuf.Pixbuf.new_from_file_at_size(str(src / svg), 256, 256)
    mode = "RGBA" if p.get_has_alpha() else "RGB"
    im = Image.frombytes(mode, (p.get_width(), p.get_height()), p.get_pixels(), "raw", mode, p.get_rowstride())
    im.save(dst / ico, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
