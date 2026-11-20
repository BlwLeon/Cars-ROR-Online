"""Texte des Python-Teils (Meldungen). Die Oberfläche hat ihre eigenen Texte in ui/app.js."""
LANG = "en"

TEXT = {
    "en": {
        "rom_unreadable": "The file cannot be read: {e}",
        "rom_wrong": "This is not Cars Race-O-Rama (Europe). Game code: {code}, expected B6OP.",
        "rom_ok": "ROM recognised: {name}",
        "rom_unknown_dump": "Game code matches, but the file differs from the known dump. Patching anyway.",
        "patch_mismatch": "Patching failed (ROM does not match): {e}",
        "patch_failed": "Patching failed: {e}",
        "cfg_missing": "Configuration block missing – please set up the ROM again.",
        "save_format": "Unknown save file format",
        "name_len": "Name must be 1–{n} characters long",
        "name_chars": "Only letters A–Z and digits 0–9 are allowed",
        "save_checksum": "Save checksum does not match – file was not changed",
        "addr_unknown": "Address “{a}” not found.",
        "already_running": "The game is already running.",
        "server_unresolvable": "Server address cannot be reached/resolved: {e}",
        "close_game_first": "Please close the game first (it would overwrite the save file).",
        "slot3_used": "Profile slot 3 is used by a story profile – the online profile needs that slot. Free it in the game or switch off “Unlock everything”.",
        "server_offline": "Server “{n}” ({a}) is not reachable. Is the server running and are you connected (Tailscale)?",
        "melon_missing": "melonDS is missing: {p}",
        "pad_button": "Button {n}", "pad_hat": "D-pad {d}", "pad_axis": "Axis {n}{d}", "pad_trigger": " (trigger)",
        "hat_1": "up", "hat_2": "right", "hat_4": "down", "hat_8": "left",
    },
    "de": {
        "rom_unreadable": "Datei kann nicht gelesen werden: {e}",
        "rom_wrong": "Das ist nicht Cars Race-O-Rama (Europa). Spielcode: {code}, erwartet B6OP.",
        "rom_ok": "ROM erkannt: {name}",
        "rom_unknown_dump": "Spielcode stimmt, aber die Datei weicht vom bekannten Dump ab. Patchen wird trotzdem versucht.",
        "patch_mismatch": "Patchen fehlgeschlagen (ROM passt nicht): {e}",
        "patch_failed": "Patchen fehlgeschlagen: {e}",
        "cfg_missing": "Konfigurationsblock fehlt – ROM bitte neu einrichten.",
        "save_format": "Unbekanntes Spielstand-Format",
        "name_len": "Der Name muss 1–{n} Zeichen lang sein",
        "name_chars": "Erlaubt sind nur Buchstaben A–Z und Ziffern 0–9",
        "save_checksum": "Spielstand-Prüfsumme stimmt nicht – Datei wird nicht verändert",
        "addr_unknown": "Adresse „{a}“ nicht gefunden.",
        "already_running": "Das Spiel läuft bereits.",
        "server_unresolvable": "Server-Adresse nicht erreichbar/auflösbar: {e}",
        "close_game_first": "Bitte zuerst das Spiel schließen (es würde den Spielstand überschreiben).",
        "slot3_used": "Profilplatz 3 ist von einem Story-Profil belegt – das Online-Profil braucht diesen Platz. Im Spiel freimachen oder „Alles freischalten“ ausschalten.",
        "server_offline": "Server „{n}“ ({a}) ist nicht erreichbar. Läuft der Server, und bist du verbunden (Tailscale)?",
        "melon_missing": "melonDS fehlt: {p}",
        "pad_button": "Taste {n}", "pad_hat": "Kreuz {d}", "pad_axis": "Achse {n}{d}", "pad_trigger": " (Trigger)",
        "hat_1": "hoch", "hat_2": "rechts", "hat_4": "runter", "hat_8": "links",
    },
}


def set_lang(lang):
    global LANG
    LANG = lang if lang in TEXT else "en"


def T(key, **kw):
    s = TEXT.get(LANG, TEXT["en"]).get(key) or TEXT["en"].get(key, key)
    return s.format(**kw) if kw else s
