"""Controller abfragen – mit SDL2 wie melonDS selbst, damit die Nummern identisch sind.

Kodierung (melonDS EmuInstanceInput.cpp):
  -1                         nicht belegt
  n                          Taste n
  0x100 | hat<<4 | dir       Steuerkreuz/Hat (dir 1=hoch 2=rechts 4=runter 8=links)
  0xFFFF | 0x10000 | dir<<20 | axis<<24   Achse (dir 0=positiv 1=negativ 2=Trigger)
"""
import time
from .i18n import T

import os, sys, threading, queue

ERROR = ""          # Grund, falls die Controller-Erkennung nicht verfügbar ist (wird im Launcher angezeigt)
sdl2, _ok = None, False
_q = queue.Queue()
_ready = threading.Event()


def _worker():
    """SDL läuft komplett in diesem einen Thread: Unter Windows kommen Controller-Eingaben über Nachrichten,
    die nur der Thread abholen kann, der SDL gestartet hat (sonst: Geräte sichtbar, aber keine Tastendrücke)."""
    global sdl2, _ok, ERROR
    try:
        try:                                    # SDL2.dll aus pysdl2-dll (auch in der gebauten Exe)
            import sdl2dll
            os.environ.setdefault("PYSDL2_DLL_PATH", sdl2dll.get_dllpath())
        except Exception:
            if getattr(sys, "frozen", False):
                os.environ.setdefault("PYSDL2_DLL_PATH", getattr(sys, "_MEIPASS", ""))
        import sdl2 as _s
        sdl2 = _s
        sdl2.SDL_SetHint(b"SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", b"1")
        # Keine weiteren Hints: genau dieselben Einstellungen wie melonDS, damit Controller-Nummern
        # und Tastennummern identisch sind (andere Treiber-Wahl = andere Reihenfolge!).
        # VIDEO mit starten (ohne Fenster): Erst dann pumpt SDL_PumpEvents die Windows-Nachrichten,
        # über die RawInput/WGI die Controller-Daten liefern – wie in melonDS.
        sdl2.SDL_SetHint(b"SDL_VIDEO_ALLOW_SCREENSAVER", b"1")
        # macOS: SDL-Video darf nur im Hauptthread laufen (Cocoa) -> dort nur Joystick
        flags = sdl2.SDL_INIT_JOYSTICK if sys.platform == "darwin" else sdl2.SDL_INIT_VIDEO | sdl2.SDL_INIT_JOYSTICK
        if sdl2.SDL_Init(flags) == 0 or sdl2.SDL_Init(sdl2.SDL_INIT_JOYSTICK) == 0:
            _ok = True
        else:
            ERROR = "SDL_Init: " + (sdl2.SDL_GetError() or b"?").decode("utf-8", "replace")
    except ImportError as e:
        ERROR = f"{e} – pip install pysdl2 pysdl2-dll"
    except Exception as e:
        ERROR = f"{type(e).__name__}: {e}"
    _ready.set()
    while True:
        try:
            fn, args, box, done = _q.get(timeout=0.05)
        except queue.Empty:
            if _ok:
                sdl2.SDL_PumpEvents()           # Geräte-Liste aktuell halten
            continue
        try:
            box.append(fn(*args))
        except Exception as e:
            box.append(e)
        done.set()


_started = False
_start_lock = threading.Lock()


def _ensure():
    """SDL erst starten, wenn die Controller-Seite es braucht (nicht beim Launcher-Start:
    SDL-Video parallel zum Fensteraufbau von WebView2 steht im Verdacht, gelegentliche Startabstürze auszulösen)."""
    global _started
    with _start_lock:
        if not _started:
            _started = True
            threading.Thread(target=_worker, daemon=True, name="sdl").start()
    _ready.wait(5)


def _call(fn, *args, timeout=15):
    _ensure()
    if not _ok:
        return None
    box, done = [], threading.Event()
    _q.put((fn, args, box, done))
    done.wait(timeout)
    if box and isinstance(box[0], Exception):
        raise box[0]
    return box[0] if box else None

HAT_NAMES = {1: "hoch", 2: "rechts", 4: "runter", 8: "links"}


def available():
    """None = noch nicht geprüft (SDL läuft erst, wenn die Einstellungen geöffnet werden)."""
    return _ok if _started and _ready.is_set() else None


def list_pads():
    return _call(_list_pads) or []


def _list_pads():
    sdl2.SDL_PumpEvents()
    sdl2.SDL_JoystickUpdate()
    return [{"id": i, "name": (sdl2.SDL_JoystickNameForIndex(i) or b"Controller").decode("utf-8", "replace")}
            for i in range(sdl2.SDL_NumJoysticks())]


def label(v):
    v = int(v)
    if v == -1:
        return "—"
    parts = []
    if (v & 0xFFFF) != 0xFFFF:
        if v & 0x100:
            parts.append(T("pad_hat", d=T(f"hat_{v & 0xF}")))
        else:
            parts.append(T("pad_button", n=v & 0xFFFF))
    if v & 0x10000:
        axis, d = (v >> 24) & 0xF, (v >> 20) & 0xF
        parts.append(T("pad_axis", n=axis, d="+" if d == 0 else "-" if d == 1 else T("pad_trigger")))
    return " + ".join(parts)


LOG = None   # wird vom Launcher gesetzt: Funktion zum Schreiben ins Logbuch


def _log(msg):
    if LOG:
        try:
            LOG(msg)
        except Exception:
            pass


# ---- XInput direkt (Rückfall, falls SDL in diesem Prozess keine Eingaben bekommt) ----
_xi = None
if sys.platform == "win32":
    import ctypes
    class _GP(ctypes.Structure):
        _fields_ = [("buttons", ctypes.c_ushort), ("lt", ctypes.c_ubyte), ("rt", ctypes.c_ubyte),
                    ("lx", ctypes.c_short), ("ly", ctypes.c_short), ("rx", ctypes.c_short), ("ry", ctypes.c_short)]
    class _XS(ctypes.Structure):
        _fields_ = [("packet", ctypes.c_uint), ("pad", _GP)]
    for _dll in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
        try:
            _xi = getattr(ctypes.windll, _dll).XInputGetState
            break
        except (OSError, AttributeError):
            continue

# XInput-Taste -> SDL-Joystick-Wert (SDL ordnet Xbox-Controller so an: A0 B1 X2 Y3 LB4 RB5 Back6 Start7 LS8 RS9)
_XI_BTN = {0x1000: 0, 0x2000: 1, 0x4000: 2, 0x8000: 3, 0x0100: 4, 0x0200: 5, 0x0020: 6, 0x0010: 7, 0x0040: 8, 0x0080: 9,
           0x0001: 0x100 | 1, 0x0008: 0x100 | 2, 0x0002: 0x100 | 4, 0x0004: 0x100 | 8}


def _xi_state(slot):
    st = _XS()
    if _xi(slot, ctypes.byref(st)) != 0:
        return None
    g = st.pad
    return g.buttons, g.lt, g.rt, g.lx, g.ly, g.rx, g.ry


def _xi_value(old, new):
    """Unterschied zwischen zwei XInput-Zuständen -> melonDS-Wert oder None."""
    for bit, v in _XI_BTN.items():
        if new[0] & bit and not old[0] & bit:
            return v
    if new[1] > 128 and old[1] <= 128: return 0xFFFF | 0x10000 | (2 << 20) | (2 << 24)      # LT = Achse 2
    if new[2] > 128 and old[2] <= 128: return 0xFFFF | 0x10000 | (2 << 20) | (5 << 24)      # RT = Achse 5
    for ax, i in ((0, 3), (1, 4), (3, 5), (4, 6)):                                           # LX LY RX RY
        if abs(new[i]) > 20000 and abs(old[i]) <= 20000:
            v = new[i] if i in (3, 5) else -new[i]                                           # SDL: Y nach unten positiv
            return 0xFFFF | 0x10000 | ((0 if v > 0 else 1) << 20) | (ax << 24)
    return None


def capture(index=None, timeout=6.0):
    """Wartet auf die nächste Eingabe an IRGENDEINEM Controller.
    -> (melonDS-Wert, Controller-Nummer) oder (-1, None), wenn nichts gedrückt wurde."""
    r = _call(_capture, timeout, index, timeout=timeout + 3)
    return r if r else (-1, None)


def _capture(timeout, selected=None):
    n = sdl2.SDL_NumJoysticks()
    pads = []
    for i in range(n):
        js = sdl2.SDL_JoystickOpen(i)
        if not js:
            _log(f"Controller {i}: SDL_JoystickOpen fehlgeschlagen: {(sdl2.SDL_GetError() or b'').decode('utf-8', 'replace')}")
            continue
        pads.append([i, js])
    if not pads:
        _log("Kein Controller zum Abfragen gefunden")
        return None
    # Xbox-Spielernummer je SDL-Controller (für den XInput-Rückfall)
    player = {}
    for i, js in pads:
        try:
            player[sdl2.SDL_JoystickGetPlayerIndex(js)] = i
        except Exception:
            pass
    xi_old = {k: _xi_state(k) for k in range(4)} if _xi else {}
    try:
        for _ in range(10):                      # Startzustand einlesen
            sdl2.SDL_PumpEvents(); sdl2.SDL_JoystickUpdate(); time.sleep(0.015)
        for p in pads:
            js = p[1]
            nb, nh, na = (sdl2.SDL_JoystickNumButtons(js), sdl2.SDL_JoystickNumHats(js), sdl2.SDL_JoystickNumAxes(js))
            rest = [sdl2.SDL_JoystickGetAxis(js, a) for a in range(na)]   # Ruhelage (Trigger stehen oft auf -32768)
            held = {b for b in range(nb) if sdl2.SDL_JoystickGetButton(js, b)}
            p += [nb, nh, na, rest, held]
            try:
                pl = sdl2.SDL_JoystickGetPlayerIndex(js)
            except Exception:
                pl = "?"
            _log(f"Controller {p[0]}: {(sdl2.SDL_JoystickName(js) or b'?').decode('utf-8', 'replace')} | "
                 f"Spieler {pl} | {nb} Tasten, {nh} Hats, {na} Achsen | Ruhe {rest}")
        end = time.time() + timeout
        while time.time() < end:
            sdl2.SDL_PumpEvents(); sdl2.SDL_JoystickUpdate()
            for i, js, nb, nh, na, rest, held in pads:
                for b in range(nb):
                    if sdl2.SDL_JoystickGetButton(js, b) and b not in held:
                        return b, i
                for h in range(nh):
                    hv = sdl2.SDL_JoystickGetHat(js, h)
                    for d in (1, 2, 4, 8):
                        if hv & d:
                            return 0x100 | (h << 4) | d, i
                for a in range(na):
                    v = sdl2.SDL_JoystickGetAxis(js, a)
                    if rest[a] < -16000:                     # Trigger: Ruhe bei -32768
                        if v > 0:
                            return 0xFFFF | 0x10000 | (2 << 20) | (a << 24), i
                    elif abs(v - rest[a]) > 20000:
                        return 0xFFFF | 0x10000 | ((0 if v > 0 else 1) << 20) | (a << 24), i
            for k, old in xi_old.items():                # Rückfall: SDL sieht nichts, XInput schon
                if old is None:
                    continue
                new = _xi_state(k)
                if new is None:
                    continue
                v = _xi_value(old, new)
                if v is not None:
                    # Welcher melonDS-Controller das ist, lässt sich über XInput nicht sicher sagen ->
                    # Controller aus der Auswahlliste (gleiche Namen/Reihenfolge wie melonDS) verwenden.
                    idx = selected if selected is not None else pads[0][0]
                    _log(f"Eingabe nur über XInput erkannt (Spieler {k + 1}) -> ausgewählter Controller {idx}")
                    return v, None if selected is None else idx
                xi_old[k] = new
            time.sleep(0.01)
        _log("Keine Eingabe an einem der Controller erkannt")
        return None
    finally:
        for p in pads:
            sdl2.SDL_JoystickClose(p[1])
