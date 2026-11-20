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
REPO = os.path.dirname(BASE)

UI_DIR = os.path.join(BUNDLE, "ui")
MELON_DIR = os.path.join(BASE, "melonDS")
MELON_EXE = os.path.join(MELON_DIR, "melonDS.exe")
MELON_TOML = os.path.join(MELON_DIR, "melonDS.toml")
MELON_TEMPLATE = os.path.join(BUNDLE, "assets", "melonDS.default.toml")
MOD_ELF = os.path.join(BASE, "mod", "net.elf") if FROZEN else os.path.join(REPO, "patch", "net.elf")
USER_DIR = os.path.join(BASE, "user")
ROM_OUT = os.path.join(USER_DIR, "Cars_RORM_Online.nds")
SAVE = os.path.join(USER_DIR, "Cars_RORM_Online.sav")
SETTINGS = os.path.join(USER_DIR, "launcher.json")
HISTORY = os.path.join(USER_DIR, "history.json")
SERVER_EXE = os.path.join(BASE, "server", "RORM-Server.exe")
SERVER_PY = os.path.join(REPO, "server", "server.py")      # Entwicklungsmodus ohne Exe

os.makedirs(USER_DIR, exist_ok=True)
