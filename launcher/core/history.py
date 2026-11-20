"""Rennverlauf (user/history.json).

Eintrag: {"time": "2026-11-20 18:04", "server": "...", "track": "...", "place": 2,
          "players": [{"name": "gwt", "place": 1, "me": false}, ...]}
Die Einträge liefert der Server (Ergebnis-Nachricht des Hosts), sobald diese
ausgewertet wird. Bis dahin bleibt die Liste leer.
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


def add(entries):
    data = load()
    known = {(e.get("time"), e.get("server")) for e in data}
    for e in entries:
        if (e.get("time"), e.get("server")) not in known:
            data.append(e)
    with open(paths.HISTORY, "w", encoding="utf-8") as f:
        json.dump(data[-2000:], f, indent=1, ensure_ascii=False)
    return data


def summary(data=None):
    data = load() if data is None else data
    races = len(data)
    wins = sum(1 for e in data if e.get("place") == 1)
    podium = sum(1 for e in data if e.get("place") in (1, 2, 3))
    rivals = {}
    for e in data:
        for p in e.get("players", []):
            if p.get("me"):
                continue
            r = rivals.setdefault(p["name"], {"name": p["name"], "races": 0, "ahead": 0})
            r["races"] += 1
            if e.get("place") and p.get("place") and e["place"] < p["place"]:
                r["ahead"] += 1
    top = sorted(rivals.values(), key=lambda r: -r["races"])[:8]
    return {"races": races, "wins": wins, "podium": podium, "rivals": top}
