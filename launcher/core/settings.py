"""Launcher-Einstellungen (user/launcher.json)."""
import json, os, random
from . import paths

DEFAULTS = {
    "setup_done": False,
    "rom_source": "",
    "server": {"name": "", "address": "127.0.0.1", "port": 27015},
    "server_name": "",               # Name beim eigenen Hosten
    "mac": "",                       # eigene, feste MAC-Adresse (unterscheidet Spieler)
    "player_name": "",
    "lang": "",
    "elf_hash": "",                  # Stand des Patches, mit dem die ROM erstellt wurde
    "auto_nav": True,
    "unlock_all": True,              # eigenes Online-Profil mit allem freigeschaltet benutzen                # im Spiel automatisch zu Host/Beitreten springen                      # "" = beim ersten Start fragen
}


def load():
    s = json.loads(json.dumps(DEFAULTS))
    try:
        with open(paths.SETTINGS, encoding="utf-8") as f:
            data = json.load(f)
        for k, v in data.items():
            if isinstance(v, dict) and isinstance(s.get(k), dict):
                s[k].update(v)
            else:
                s[k] = v
    except (OSError, ValueError):
        pass
    if not s["mac"]:
        # Nintendo-OUI 00:09:BF wie bei melonDS, Rest zufällig -> jeder Spieler hat eine eigene Kennung
        s["mac"] = "00:09:BF:" + ":".join(f"{random.randrange(256):02X}" for _ in range(3))
        save(s)
    return s


def save(s):
    tmp = paths.SETTINGS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2, ensure_ascii=False)
    os.replace(tmp, paths.SETTINGS)
