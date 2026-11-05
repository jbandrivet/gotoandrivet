"""Le toucher pour les logiciels Tk sous Wayland.

Sous Wayland, un logiciel Tk ne reçoit jamais l'appui du doigt. Mesuré sur une Surface Pro 3 :
le premier doigt n'arrive ni comme clic ni comme toucher sur la fenêtre, seul le deuxième passe.
Seuls les touchers bruts d'XInput 2 voient tous les doigts : on les écoute à la racine de
l'écran et on les transforme en clics pour Tk.

Hors Wayland, le tactile marche tout seul et on ne fait rien, sinon chaque appui compterait double.
Si quelque chose manque (Windows, pas de libXi), on ne fait rien non plus.
"""
import ctypes
import os
import sys
import time
import tkinter as tk
from ctypes import POINTER, byref, c_char_p, c_double, c_int, c_ubyte, c_uint, c_ulong, c_void_p

XI_TOUCH_BEGIN, XI_TOUCH_UPDATE, XI_TOUCH_END = 18, 19, 20
XI_RAW_BEGIN, XI_RAW_UPDATE, XI_RAW_END = 22, 23, 24
ECHELLE_XWAYLAND = 65535.0      # Xwayland donne la position du doigt de 0 à 65535 sur tout l'écran
XI_ALL_MASTER_DEVICES = 1
DOIGT_PERDU = 8.0       # s : plus long que l'appui de 5 s qui ouvre les réglages
GENERIC_EVENT = 35
BOUTON1 = 0x100


class XIEventMask(ctypes.Structure):
    _fields_ = [("deviceid", c_int), ("mask_len", c_int), ("mask", POINTER(c_ubyte))]


class XGenericEventCookie(ctypes.Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", c_int), ("display", c_void_p),
                ("extension", c_int), ("evtype", c_int), ("cookie", c_uint), ("data", c_void_p)]


class XEvent(ctypes.Union):
    _fields_ = [("type", c_int), ("xcookie", XGenericEventCookie), ("pad", ctypes.c_long * 24)]


class XIDeviceEvent(ctypes.Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", c_int), ("display", c_void_p),
                ("extension", c_int), ("evtype", c_int), ("time", c_ulong), ("deviceid", c_int),
                ("sourceid", c_int), ("detail", c_int), ("root", c_ulong), ("event", c_ulong),
                ("child", c_ulong), ("root_x", c_double), ("root_y", c_double),
                ("event_x", c_double), ("event_y", c_double), ("flags", c_int)]


class XIValuatorState(ctypes.Structure):
    _fields_ = [("mask_len", c_int), ("mask", POINTER(c_ubyte)), ("values", POINTER(c_double))]


class XIRawEvent(ctypes.Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", c_int), ("display", c_void_p),
                ("extension", c_int), ("evtype", c_int), ("time", c_ulong), ("deviceid", c_int),
                ("sourceid", c_int), ("detail", c_int), ("flags", c_int), ("valuators", XIValuatorState),
                ("raw_values", POINTER(c_double))]


class Tactile:
    def __init__(self, root):
        self.root = root
        self.doigt = None       # le premier doigt posé ; les autres sont ignorés
        self.depuis = 0.0
        self.positions = {}     # dernière position de chaque doigt : un toucher brut ne redit que ce qui change
        self.cible = None
        self.actif = False
        try:
            self._brancher()
        except (OSError, AttributeError, TypeError, tk.TclError) as e:
            print("tactile :", e, file=sys.stderr)

    def _brancher(self):
        x = ctypes.CDLL("libX11.so.6")
        xi = ctypes.CDLL("libXi.so.6")
        x.XOpenDisplay.restype = c_void_p
        x.XOpenDisplay.argtypes = [c_char_p]
        x.XQueryExtension.argtypes = [c_void_p, c_char_p, POINTER(c_int), POINTER(c_int), POINTER(c_int)]
        x.XSync.argtypes = [c_void_p, c_int]
        x.XPending.argtypes = [c_void_p]
        x.XNextEvent.argtypes = [c_void_p, POINTER(XEvent)]
        x.XGetEventData.argtypes = [c_void_p, POINTER(XGenericEventCookie)]
        x.XFreeEventData.argtypes = [c_void_p, POINTER(XGenericEventCookie)]
        x.XConnectionNumber.argtypes = [c_void_p]
        xi.XIQueryVersion.argtypes = [c_void_p, POINTER(c_int), POINTER(c_int)]
        xi.XISelectEvents.argtypes = [c_void_p, c_ulong, POINTER(XIEventMask), c_int]
        x.XDefaultRootWindow.restype = c_ulong
        x.XDefaultRootWindow.argtypes = [c_void_p]
        self.x = x
        d = self.d = x.XOpenDisplay(None)
        if not d:
            raise OSError("pas d'affichage X")
        op, ev, er = c_int(), c_int(), c_int()
        if not x.XQueryExtension(d, b"XInputExtension", byref(op), byref(ev), byref(er)):
            raise OSError("pas de XInput")
        self.opcode = op.value
        maj, mi = c_int(2), c_int(2)
        if xi.XIQueryVersion(d, byref(maj), byref(mi)) != 0 or (maj.value, mi.value) < (2, 2):
            raise OSError("XInput trop ancien")

        if not (os.environ.get("WAYLAND_DISPLAY")
                or x.XQueryExtension(d, b"XWAYLAND", byref(op), byref(ev), byref(er))):
            return
        self.xi = xi
        self.fenetres = set()
        self.root.update_idletasks()
        if not self._selectionner(x.XDefaultRootWindow(d), (XI_RAW_BEGIN, XI_RAW_UPDATE, XI_RAW_END)):
            raise OSError("abonnement refusé")
        self.abonner(self.root)
        self.actif = True
        # Les fenêtres de dialogue s'abonnent en s'ouvrant
        self.root.bind_class("Toplevel", "<Map>", lambda e: self.abonner(e.widget.winfo_toplevel()), add="+")
        self.root.tk.createfilehandler(x.XConnectionNumber(d), tk.READABLE, self._lire)
        self._lire()

    def abonner(self, fenetre):
        """Prend les touchers de la fenêtre, sans s'en servir : le système ne les change plus en clics."""
        fid = fenetre.winfo_id()
        if fid not in self.fenetres and self._selectionner(fid, (XI_TOUCH_BEGIN, XI_TOUCH_UPDATE, XI_TOUCH_END)):
            self.fenetres.add(fid)

    def _selectionner(self, fid, evenements):
        x, d = self.x, self.d
        # Une erreur X tuerait le programme : on l'attrape le temps de s'abonner
        erreurs = []
        rappel = ctypes.CFUNCTYPE(c_int, c_void_p, c_void_p)(lambda _d, _e: erreurs.append(1) or 0)
        x.XSetErrorHandler.restype = c_void_p
        x.XSetErrorHandler.argtypes = [c_void_p]
        ancien = x.XSetErrorHandler(ctypes.cast(rappel, c_void_p))
        octets = (c_ubyte * 4)()
        for t in evenements:
            octets[t >> 3] |= 1 << (t & 7)
        masque = XIEventMask(XI_ALL_MASTER_DEVICES, 4, ctypes.cast(octets, POINTER(c_ubyte)))
        self.xi.XISelectEvents(d, fid, byref(masque), 1)
        x.XSync(d, 0)
        x.XSetErrorHandler(ancien)
        return not erreurs

    def _lire(self, *_):
        x, d = self.x, self.d
        while x.XPending(d):
            e = XEvent()
            x.XNextEvent(d, byref(e))
            c = e.xcookie
            if c.type == GENERIC_EVENT and c.extension == self.opcode and x.XGetEventData(d, byref(c)):
                try:
                    if XI_RAW_BEGIN <= c.evtype <= XI_RAW_END:
                        self._brut(c.evtype, ctypes.cast(c.data, POINTER(XIRawEvent)).contents)
                finally:
                    x.XFreeEventData(d, byref(c))

    def _brut(self, quoi, t):
        pos = self.positions.setdefault(t.detail, [0.0, 0.0])
        rang = 0
        for axe in range(t.valuators.mask_len * 8):
            if t.valuators.mask[axe >> 3] & (1 << (axe & 7)):
                if axe < 2:
                    pos[axe] = t.valuators.values[rang]
                rang += 1
        rx = int(pos[0] / ECHELLE_XWAYLAND * self.root.winfo_screenwidth())
        ry = int(pos[1] / ECHELLE_XWAYLAND * self.root.winfo_screenheight())
        if quoi == XI_RAW_END:
            del self.positions[t.detail]
        self._toucher(quoi - XI_RAW_BEGIN + XI_TOUCH_BEGIN, t.detail, rx, ry)

    def nous_sommes_devant(self):
        """Les touchers bruts viennent de tout l'écran, y compris des autres logiciels."""
        return bool(self.root.tk.call("focus", "-displayof", ".")) or bool(self.root.attributes("-fullscreen"))

    def _toucher(self, quoi, doigt, rx, ry):
        maintenant = time.monotonic()
        if quoi == XI_TOUCH_BEGIN and self.doigt is not None and maintenant - self.depuis > DOIGT_PERDU:
            self.doigt = self.cible = None      # sa fin s'est perdue : il ne doit pas tout bloquer
        if doigt == self.doigt:
            self.depuis = maintenant
        if quoi == XI_TOUCH_BEGIN and self.doigt is None:
            # Par son nom Tcl : les boîtes de message et les listes déroulantes n'existent pas côté Python
            w = str(self.root.tk.call("winfo", "containing", rx, ry))
            if not w or not self.nous_sommes_devant():
                return
            self.doigt, self.cible, self.depuis = doigt, w, maintenant
            self._envoyer("<Motion>", rx, ry, 0)
            self._envoyer("<ButtonPress-1>", rx, ry, 0)
        elif doigt == self.doigt and quoi == XI_TOUCH_UPDATE:
            self._envoyer("<Motion>", rx, ry, BOUTON1)
        elif doigt == self.doigt and quoi == XI_TOUCH_END:
            self._envoyer("<ButtonRelease-1>", rx, ry, BOUTON1)
            self.doigt = self.cible = None

    def _envoyer(self, sequence, rx, ry, etat):
        tcl = self.root.tk.call
        w = self.cible
        try:
            tcl("event", "generate", w, sequence, "-x", rx - int(tcl("winfo", "rootx", w)),
                "-y", ry - int(tcl("winfo", "rooty", w)), "-rootx", rx, "-rooty", ry, "-state", etat)
        except tk.TclError:             # le widget a disparu entre-temps
            self.doigt = self.cible = None


def brancher(root):
    """À appeler une fois, juste après la création de la fenêtre principale."""
    if sys.platform.startswith("linux"):
        root.update_idletasks()
        root._tactile = Tactile(root)
