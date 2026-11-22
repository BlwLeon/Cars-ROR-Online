"""Rennverlauf (user/history.json).

Eintrag: {"time": "2026-11-20 18:04", "server": "...", "track": "...", "place": 2,
          "players": [{"name": "gwt", "place": 1, "me": false}, ...]}
Die Einträge liefert der Server (CRRO-HIST?): Er erkennt Rennen am Datenaustausch und kennt die
Fahrernamen aus der Lobby. Platzierungen ("place") fehlen, bis die Ergebnis-Nachricht ausgewertet wird.
"""
import json, os
from . import paths


def load():
    try:
        with open(paths.HISTORY, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _key(e):
    return (e.get("time"), e.get("server"), tuple(sorted(p.get("mac") or p.get("name") or "" for p in e.get("players", []))))


def add(entries, my_mac=None):
    """Neue Einträge übernehmen. my_mac: markiert den eigenen Fahrer ("me") und setzt "place"."""
    data = load()
    known = {_key(e): i for i, e in enumerate(data)}
    new = 0
    for e in entries:
        if my_mac:
            for p in e.get("players", []):
                p["me"] = (p.get("mac") or "").upper() == my_mac.upper()
                if p["me"] and p.get("place"):
                    e["place"] = p["place"]
        k = _key(e)
        if k not in known:
            known[k] = len(data); data.append(e); new += 1
        elif data[known[k]] != e:          # Server kennt inzwischen Platz/Namen -> aktualisieren
            data[known[k]] = e; new += 1
    if new:
        data.sort(key=lambda e: e.get("time") or "")
        tmp = paths.HISTORY + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data[-2000:], f, indent=1, ensure_ascii=False)
        os.replace(tmp, paths.HISTORY)
    return data


def summary(data=None):
    data = load() if data is None else data
    races = len(data)
    wins = sum(1 for e in data if e.get("place") == 1)
    podium = sum(1 for e in data if e.get("place") in (1, 2, 3))
    placed = [e["place"] for e in data if e.get("place")]
    avg = round(sum(placed) / len(placed), 1) if placed else None
    rivals = {}
    for e in data:
        for p in e.get("players", []):
            if p.get("me"):
                continue
            # nach MAC (Online-ID) zusammenfassen, damit ein umbenannter Spieler nur einmal auftaucht;
            # angezeigt wird sein neuester Name (Einträge sind nach Zeit sortiert)
            key = (p.get("mac") or "").upper() or p.get("name")
            r = rivals.setdefault(key, {"name": p.get("name"), "races": 0, "ahead": 0, "placed": 0})
            if p.get("name") and not (p["name"].count(":") == 5 and r["name"]):   # MAC als Ersatzname nicht bevorzugen
                r["name"] = p["name"]
            r["races"] += 1
            if e.get("place") and p.get("place"):
                r["placed"] += 1
                if e["place"] < p["place"]:
                    r["ahead"] += 1
    top = sorted(rivals.values(), key=lambda r: -r["races"])[:8]
    return {"races": races, "wins": wins, "podium": podium, "avg_place": avg, "rivals": top}
