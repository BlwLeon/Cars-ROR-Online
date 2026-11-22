"""Ordnerstruktur des Launchers.

Release-Ordner (neben der Exe):
  RORM Online.exe        Launcher
  server/RORM-Server.exe Server (Konsole)
  melonDS/               gebündelter Emulator (portabel, melonDS.toml liegt daneben)
  mod/net.elf            Online-Patch
  user/                  eigene Daten: gepatchte ROM, Spielstand, Einstellungen, Verlauf

Entwicklung (python launcher/main.py): Patch aus patch/net.elf, Server aus server/server.py,
melonDS im Ordner launcher/melonDS (lädt Launcher_testen.bat automatisch).
"""
import os, sys

FROZEN = getattr(sys, "frozen", False)
if FROZEN:
    BASE = os.path.dirname(sys.executable)                 # Ordner der Exe
    BUNDLE = getattr(sys, "_MEIPASS", BASE)                # eingepackte Dateien (ui/, assets/)
else:
    BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    BUNDLE = BASE

MAC = sys.platform == "darwin"
if MAC and FROZEN:
    # macOS: Das App-Paket ist schreibgeschützt (und signiert) -> eigene Daten nach ~/Library/Application Support.
    # melonDS.app liegt im Paket (Contents/Resources) und wird beim Start dorthin kopiert; der Ordner
    # "portable" daneben lässt melonDS seine melonDS.toml dort ablegen statt in ~/Library/Preferences.
    BASE = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "RORM Online")
    RESOURCES = os.path.join(os.path.dirname(os.path.dirname(sys.executable)), "Resources")
REPO = os.path.dirname(BASE)

UI_DIR = os.path.join(BUNDLE, "ui")
MELON_DIR = os.path.join(BASE, "melonDS")
if MAC:
    MELON_APP = os.path.join(MELON_DIR, "melonDS.app")
    MELON_EXE = os.path.join(MELON_APP, "Contents", "MacOS", "melonDS")
    MELON_TOML = os.path.join(MELON_DIR, "portable", "melonDS.toml")
else:
    MELON_EXE = os.path.join(MELON_DIR, "melonDS.exe")
    MELON_TOML = os.path.join(MELON_DIR, "melonDS.toml")
MELON_TEMPLATE = os.path.join(BUNDLE, "assets", "melonDS.default.toml")
if MAC and FROZEN:
    MOD_ELF = os.path.join(BUNDLE, "mod", "net.elf")
else:
    MOD_ELF = os.path.join(BASE, "mod", "net.elf") if FROZEN else os.path.join(REPO, "patch", "net.elf")
USER_DIR = os.path.join(BASE, "user")
ROM_OUT = os.path.join(USER_DIR, "Cars_RORM_Online.nds")
SAVE = os.path.join(USER_DIR, "Cars_RORM_Online.sav")
SETTINGS = os.path.join(USER_DIR, "launcher.json")
HISTORY = os.path.join(USER_DIR, "history.json")
SERVER_EXE = os.path.join(BASE, "server", "RORM-Server.exe")
SERVER_PY = os.path.join(REPO, "server", "server.py")      # Entwicklungsmodus ohne Exe

SERVER_LOG_DIR = os.path.join(BASE, "server") if MAC and FROZEN else None   # None = neben dem Server

os.makedirs(USER_DIR, exist_ok=True)


def mac_install_melon():
    """macOS: mitgelieferte melonDS.app nach MELON_DIR kopieren (einmal je Launcher-Version)."""
    if not (MAC and FROZEN):
        return
    import shutil
    src = os.path.join(RESOURCES, "melonDS.app")
    mark = os.path.join(MELON_DIR, ".version")
    try:
        ver = str(os.path.getmtime(os.path.join(src, "Contents", "Info.plist")))
    except OSError:
        return
    try:
        with open(mark) as f:
            if f.read() == ver and os.path.exists(MELON_EXE):
                return
    except OSError:
        pass
    os.makedirs(os.path.join(MELON_DIR, "portable"), exist_ok=True)
    if os.path.exists(MELON_APP):
        shutil.rmtree(MELON_APP, ignore_errors=True)
    shutil.copytree(src, MELON_APP, symlinks=True)
    with open(mark, "w") as f:
        f.write(ver)
