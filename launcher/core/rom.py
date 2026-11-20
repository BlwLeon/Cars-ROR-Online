"""Ersteinrichtung: eigene ROM prüfen, patchen, Server eintragen.

Die Original-ROM wird nie verändert oder weitergegeben – der Launcher erzeugt nur
eine gepatchte Kopie im eigenen user/-Ordner.
"""
import hashlib, os, runpy, shutil, socket, struct, sys, io, contextlib
from . import paths
from .i18n import T

GAME_CODE = b"B6OP"   # Cars Race-O-Rama (Europe)
KNOWN_SHA1 = {"ca684323eb12ded29b24276824a3d888fa347069": "Cars - Race-O-Rama (Europe) (En,Es,It)"}


def check(path):
    """-> dict(ok, msg, verified)"""
    try:
        with open(path, "rb") as f:
            head = f.read(0x200)
            f.seek(0)
            sha1 = hashlib.sha1(f.read()).hexdigest()
    except OSError as e:
        return {"ok": False, "msg": T("rom_unreadable", e=e)}
    if len(head) < 0x200 or head[0x0C:0x10] != GAME_CODE:
        code = "".join(chr(c) if 32 <= c < 127 else "?" for c in head[0x0C:0x10]) if len(head) >= 0x10 else "?"
        return {"ok": False, "msg": T("rom_wrong", code=code)}
    if sha1 in KNOWN_SHA1:
        return {"ok": True, "verified": True, "msg": T("rom_ok", name=KNOWN_SHA1[sha1])}
    return {"ok": True, "verified": False,
            "msg": T("rom_unknown_dump")}


def patch(src):
    """Original-ROM -> user/Cars_RORM_Online.nds. -> dict(ok, msg)"""
    c = check(src)
    if not c["ok"]:
        return c
    tool = os.path.join(os.path.dirname(os.path.abspath(__file__)), "patch_rom.py")
    tmp = paths.ROM_OUT + ".tmp"
    old_argv, out = sys.argv, io.StringIO()
    try:
        sys.argv = [tool, src, paths.MOD_ELF, tmp]
        with contextlib.redirect_stdout(out):
            runpy.run_path(tool, run_name="__main__")
    except AssertionError as e:
        return {"ok": False, "msg": T("patch_mismatch", e=e)}
    except Exception as e:
        return {"ok": False, "msg": T("patch_failed", e=e)}
    finally:
        sys.argv = old_argv
    os.replace(tmp, paths.ROM_OUT)
    # vorhandenen Spielstand des Originals übernehmen (nur beim ersten Mal)
    sav = os.path.splitext(src)[0] + ".sav"
    if os.path.exists(sav) and not os.path.exists(paths.SAVE):
        shutil.copyfile(sav, paths.SAVE)
    return {"ok": True, "msg": c["msg"], "verified": c.get("verified", False)}


def is_ready():
    return os.path.exists(paths.ROM_OUT)


def resolve(address):
    """Hostname/IP -> IPv4 aus Sicht von melonDS. Eigener PC = 10.64.0.1 (libslirp)."""
    ip = socket.gethostbyname(address.strip())
    if ip.startswith("127."):
        ip = "10.64.0.1"
    return ip


def elf_hash():
    try:
        with open(paths.MOD_ELF, "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()
    except OSError:
        return ""


def set_auto(mode, profile):
    """mode: 0 aus, 1 bis Mehrspieler-Menü, 2 direkt Host, 3 direkt Beitreten; profile: 0..2 oder None."""
    with open(paths.ROM_OUT, "r+b") as f:
        rom = f.read()
        i = rom.find(b"CRNETCFG")
        if i < 0:
            raise RuntimeError(T("cfg_missing"))
        f.seek(i + 56)
        f.write(bytes([int(mode) & 0xFF, 0xFF if profile is None else int(profile) & 0xFF]))


def set_server(address, port):
    """Trägt den Server in die gepatchte ROM ein (vor jedem Start, damit Hostnamen neu aufgelöst werden)."""
    ip = resolve(address)
    with open(paths.ROM_OUT, "r+b") as f:
        rom = f.read()
        i = rom.find(b"CRNETCFG")
        if i < 0:
            raise RuntimeError(T("cfg_missing"))
        f.seek(i + 16)
        f.write(socket.inet_aton(ip) + struct.pack("<H", int(port)))
    return ip
