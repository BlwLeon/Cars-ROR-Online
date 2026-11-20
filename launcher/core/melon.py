"""melonDS (1.1) steuern: melonDS.toml lesen/schreiben und den Emulator starten."""
import os, re, shutil, subprocess, sys, time
from . import paths
from .i18n import T

# Eigener kleiner TOML-Leser für das Format, das melonDS schreibt ([Abschnitt.Unter], key = Wert).
# tomllib gibt es erst ab Python 3.11 – ohne ihn wurden Einstellungen still als "leer" gelesen.
def _parse_value(v):
    v = v.strip()
    if v in ("true", "false"):
        return v == "true"
    if v.startswith('"'):
        out, i = [], 1
        while i < len(v) and v[i] != '"':
            if v[i] == "\\" and i + 1 < len(v):
                i += 1
                out.append({"n": "\n", "t": "\t"}.get(v[i], v[i]))
            else:
                out.append(v[i])
            i += 1
        return "".join(out)
    if v.startswith("["):
        inner = v[1:v.rfind("]")].strip()
        if not inner:
            return []
        parts, cur, q = [], "", False
        for ch in inner:
            if ch == '"':
                q = not q
            if ch == "," and not q:
                parts.append(cur); cur = ""
            else:
                cur += ch
        parts.append(cur)
        return [_parse_value(p) for p in parts if p.strip()]
    try:
        return int(v, 0) if not any(c in v for c in ".eE") or v.lower().startswith("0x") else float(v)
    except ValueError:
        try:
            return float(v)
        except ValueError:
            return v


def parse_toml(text):
    root, cur = {}, None
    cur = root
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]") and not line.startswith("[["):
            cur = root
            for part in line[1:-1].strip().split("."):
                cur = cur.setdefault(part.strip(), {})
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            cur[k.strip().strip('"')] = _parse_value(v)
        else:
            raise ValueError(f"Ungültige Zeile: {raw!r}")
    return root

# DS-Tasten in der Reihenfolge, wie sie im Launcher angezeigt werden
DS_KEYS = ["A", "B", "X", "Y", "L", "R", "Start", "Select", "Up", "Down", "Left", "Right"]
HOTKEYS = {"HK_FullscreenToggle": "Vollbild", "HK_SwapScreens": "Bildschirme tauschen",
           "HK_FastForward": "Vorspulen (halten)"}

# Standardbelegung (Qt-Tastencodes): Pfeile, X/Y/A/S wie melonDS, Q/W = L/R
QT = {"Left": 0x01000012, "Up": 0x01000013, "Right": 0x01000014, "Down": 0x01000015,
      "Return": 0x01000004, "Backspace": 0x01000003, "Tab": 0x01000001, "F11": 0x0100003A}
DEFAULT_KEYS = {"A": ord("X"), "B": ord("Z"), "X": ord("S"), "Y": ord("A"), "L": ord("Q"), "R": ord("W"),
                "Start": QT["Return"], "Select": QT["Backspace"], "Up": QT["Up"], "Down": QT["Down"],
                "Left": QT["Left"], "Right": QT["Right"], "HK_FullscreenToggle": QT["F11"],
                "HK_SwapScreens": QT["Tab"], "HK_FastForward": -1}


def load():
    _ensure_file()
    if os.path.exists(paths.MELON_TOML):
        try:
            with open(paths.MELON_TOML, encoding="utf-8") as f:
                return parse_toml(f.read())
        except Exception:
            pass
    return {}


def _val(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, list):
        return "[" + ", ".join(_val(x) for x in v) + "]"
    s = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def _ensure_file():
    """Fehlt melonDS.toml oder ist sie leer/kaputt -> vollständige melonDS-1.1-Vorlage verwenden.
    (Eine knappe, selbst erzeugte Datei hat melonDS beim Zurückschreiben abstürzen lassen.)"""
    ok = False
    if os.path.exists(paths.MELON_TOML) and os.path.getsize(paths.MELON_TOML) > 0:
        try:
            with open(paths.MELON_TOML, encoding="utf-8") as f:
                ok = bool(parse_toml(f.read()))
        except Exception:
            ok = False
    if not ok:
        os.makedirs(paths.MELON_DIR, exist_ok=True)
        shutil.copyfile(paths.MELON_TEMPLATE, paths.MELON_TOML)


def apply(changes):
    """changes: {"Abschnitt.Unter": {key: value}, "": {key: value}} – ändert nur diese Zeilen,
    der Aufbau der Datei bleibt so, wie melonDS ihn selbst schreibt."""
    _ensure_file()
    with open(paths.MELON_TOML, encoding="utf-8") as f:
        lines = f.read().split("\n")
    while lines and lines[-1] == "":
        lines.pop()
    for section, kv in changes.items():
        # Bereich des Abschnitts suchen
        if section == "":
            start, end = 0, next((i for i, l in enumerate(lines) if l.strip().startswith("[")), len(lines))
        else:
            hdr = f"[{section}]"
            start = next((i + 1 for i, l in enumerate(lines) if l.strip() == hdr), None)
            if start is None:
                lines += ["", hdr]
                start = len(lines)
            end = next((i for i in range(start, len(lines)) if lines[i].strip().startswith("[")), len(lines))
        for k, v in kv.items():
            line = f"{k} = {_val(v)}"
            for i in range(start, end):
                if re.match(rf"^\s*{re.escape(k)}\s*=", lines[i]):
                    lines[i] = line
                    break
            else:
                ins = end
                while ins > start and lines[ins - 1].strip() == "":
                    ins -= 1
                lines.insert(ins, line)
                end += 1
    tmp = paths.MELON_TOML + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, paths.MELON_TOML)


def sub(cfg, *keys):
    for k in keys:
        cfg = cfg.setdefault(k, {})
    return cfg


def get_bindings():
    cfg = load()
    kb = sub(cfg, "Instance0", "Keyboard")
    js = sub(cfg, "Instance0", "Joystick")
    names = DS_KEYS + list(HOTKEYS)
    return {"keyboard": {k: kb.get(k, DEFAULT_KEYS.get(k, -1)) for k in names},
            "joystick": {k: js.get(k, -1) for k in names},
            "joystick_id": sub(cfg, "Instance0").get("JoystickID", 0)}


def set_bindings(keyboard=None, joystick=None, joystick_id=None):
    ch = {}
    if keyboard is not None:
        ch["Instance0.Keyboard"] = {k: int(v) for k, v in keyboard.items()}
    if joystick is not None:
        ch["Instance0.Joystick"] = {k: int(v) for k, v in joystick.items()}
    if joystick_id is not None:
        ch["Instance0"] = {"JoystickID": int(joystick_id)}
    apply(ch)


DISPLAY_DEFAULTS = {"layout": 0, "sizing": 0, "swap": False, "integer": False, "filter": True, "gap": 0,
                    "renderer": 0, "scale": 1, "fullscreen": False}


def get_display():
    cfg = load()
    w = sub(cfg, "Instance0", "Window0")
    gl = sub(cfg, "3D", "GL")
    d = dict(DISPLAY_DEFAULTS)
    d.update(layout=w.get("ScreenLayout", 0), sizing=w.get("ScreenSizing", 0), swap=w.get("ScreenSwap", False),
             integer=w.get("IntegerScaling", False), filter=w.get("ScreenFilter", True), gap=w.get("ScreenGap", 0),
             renderer=sub(cfg, "3D").get("Renderer", 0), scale=gl.get("ScaleFactor", 1),
             fullscreen=os.path.exists(os.path.join(paths.USER_DIR, "fullscreen")))
    return d


def set_display(d):
    r = int(d["renderer"])
    apply({"Instance0.Window0": dict(ScreenLayout=int(d["layout"]), ScreenSizing=int(d["sizing"]), ScreenSwap=bool(d["swap"]),
                                     IntegerScaling=bool(d["integer"]), ScreenFilter=bool(d["filter"]), ScreenGap=int(d["gap"])),
           "3D": {"Renderer": r}, "3D.GL": {"ScaleFactor": max(1, min(8, int(d["scale"])))},
           "Screen": {"UseGL": r != 0}})
    paths_full = os.path.join(paths.USER_DIR, "fullscreen")    # Launcher-eigene Option, nicht in melonDS.toml
    if d["fullscreen"]:
        open(paths_full, "w").close()
    elif os.path.exists(paths_full):
        os.remove(paths_full)


def prepare(mac, nickname):
    """Feste Einstellungen vor jedem Start: Online über libslirp, eigene MAC, Nickname."""
    fw = {"MAC": mac}
    if nickname:
        fw["Username"] = nickname[:10]
    apply({"": {"PauseLostFocus": False}, "LAN": {"DirectMode": False}, "Emu": {"DirectBoot": True},
           "Instance0.Firmware": fw})


_proc = None
_started = 0.0


def start(rom, fullscreen=False):
    global _proc, _started
    if not os.path.exists(paths.MELON_EXE):
        raise RuntimeError(T("melon_missing", p=paths.MELON_EXE))
    args = [paths.MELON_EXE, rom]
    if fullscreen:
        args.append("--fullscreen")
    flags = 0x08000000 if sys.platform == "win32" else 0   # CREATE_NO_WINDOW (keine Extra-Konsole)
    _proc = subprocess.Popen(args, cwd=paths.MELON_DIR, creationflags=flags)
    _started = time.time()
    return _proc.pid


def crashed():
    """Ist melonDS innerhalb von 15 s nach dem Start mit Fehler beendet worden? (meldet nur einmal)"""
    global _proc
    if _proc is None or _proc.poll() is None:
        return None
    code, early = _proc.returncode, time.time() - _started < 15
    if early and code != 0:
        _proc = None
        return code
    return None


def running():
    return _proc is not None and _proc.poll() is None
