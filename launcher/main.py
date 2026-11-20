"""Race-O-Rama Online – Launcher.

Fenster: pywebview (unter Windows Edge WebView2), Oberfläche in ui/.
Start im Entwicklungsmodus:  python main.py
"""
import os, sys, threading, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import paths, settings, rom, melon, servers, save, history, pad, i18n  # noqa: E402
from core.i18n import T  # noqa: E402

VERSION = "1.0.0-beta1"


class Api:
    def __init__(self):
        self.s = settings.load()
        i18n.set_lang(self.s["lang"] or "en")
        self.window = None
        self.srv_info = None          # letzter Stand des ausgewählten Servers (None = nicht erreichbar)
        def _plog(m):
            with open(os.path.join(paths.USER_DIR, "launcher_log.txt"), "a", encoding="utf-8") as f:
                f.write(time.strftime("[%H:%M:%S] ") + m + "\n")
        pad.LOG = _plog
        if pad.ERROR:
            with open(os.path.join(paths.USER_DIR, "launcher_log.txt"), "a", encoding="utf-8") as f:
                f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + "Controller: " + pad.ERROR + "\n")
        self.srv_checked = 0.0
        threading.Thread(target=self._watch_server, daemon=True).start()

    def _watch_server(self):
        while True:
            srv = self.s["server"]
            try:
                self.srv_info = servers.probe(srv["address"], srv["port"])
            except Exception:
                self.srv_info = None
            self.srv_checked = time.time()
            time.sleep(4)

    # ---------- allgemein ----------
    def state(self):
        s = self.s
        crash = melon.crashed()
        if crash is not None:
            with open(os.path.join(paths.USER_DIR, "launcher_log.txt"), "a", encoding="utf-8") as f:
                f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + f"melonDS beendet mit Code {crash & 0xFFFFFFFF:#x}\n")
        return {"version": VERSION, "lang": s["lang"], "auto_nav": s.get("auto_nav", True), "unlock_all": s.get("unlock_all", True), "setup_done": s["setup_done"] and rom.is_ready(),
                "server": s["server"], "server_name": s["server_name"] or os.environ.get("COMPUTERNAME", "Mein Server"),
                "mac": s["mac"], "melon": os.path.exists(paths.MELON_EXE), "playing": melon.running(),
                "hosting": servers.host_running(), "pad": pad.available(), "pad_error": pad.ERROR, "crash": crash,
                "srv_online": self.srv_info is not None, "srv_checked": self.srv_checked > 0,
                "srv_players": (self.srv_info or {}).get("players"), "srv_ping": (self.srv_info or {}).get("ping_ms")}

    def set_unlock_all(self, on):
        self.s["unlock_all"] = bool(on)
        settings.save(self.s)
        return self.s["unlock_all"]

    def set_auto_nav(self, on):
        self.s["auto_nav"] = bool(on)
        settings.save(self.s)
        return self.s["auto_nav"]

    def set_lang(self, lang):
        self.s["lang"] = lang if lang in ("en", "de") else "en"
        i18n.set_lang(self.s["lang"])
        settings.save(self.s)
        return self.s["lang"]

    # ---------- Ersteinrichtung ----------
    def pick_rom(self):
        import webview
        kind = getattr(getattr(webview, "FileDialog", None), "OPEN", None) or webview.OPEN_DIALOG
        try:
            r = self.window.create_file_dialog(kind, allow_multiple=False,
                                               file_types=("Nintendo DS ROM (*.nds)", "All files (*.*)"))
        except ValueError:          # ältere/neuere pywebview-Versionen mit anderer Filter-Prüfung
            r = self.window.create_file_dialog(kind, allow_multiple=False)
        if not r:
            return None
        return r if isinstance(r, str) else r[0]

    def setup_rom(self, path):
        res = rom.patch(path)
        if res["ok"]:
            self.s["setup_done"] = True
            self.s["rom_source"] = path
            self.s["elf_hash"] = rom.elf_hash()
            settings.save(self.s)
        return res

    # ---------- Server ----------
    def search_servers(self):
        try:
            return {"ok": True, **servers.search()}
        except Exception as e:
            return {"ok": False, "msg": str(e), "servers": []}

    def select_server(self, name, address, port=27015):
        try:
            rom.resolve(address)
        except OSError:
            return {"ok": False, "msg": T("addr_unknown", a=address)}
        self.s["server"] = {"name": name or address, "address": address.strip(), "port": int(port)}
        settings.save(self.s)
        self.srv_info = servers.probe(address, port)
        return {"ok": True, "online": self.srv_info is not None}

    def host(self, name):
        self.s["server_name"] = name
        settings.save(self.s)
        servers.start_host(name)
        time.sleep(0.8)
        ip = servers.tailscale_ip()
        if not self.s["server"]["address"] or self.s["server"]["address"] in ("", "127.0.0.1"):
            self.s["server"] = {"name": name or "Mein Server", "address": "127.0.0.1", "port": 27015}
            settings.save(self.s)
        return {"ok": servers.host_running(), "tailscale_ip": ip}

    def stop_host(self):
        servers.stop_host()
        return {"ok": True}

    def my_tailscale_ip(self):
        return servers.tailscale_ip()

    # ---------- Spielen ----------
    def play(self, mode="join"):
        if melon.running():
            return {"ok": False, "msg": T("already_running")}
        try:
            # neue Mod-Version mitgeliefert -> ROM aus der eigenen Original-ROM neu erstellen
            h = rom.elf_hash()
            if h and h != self.s.get("elf_hash") and self.s.get("rom_source") and os.path.exists(self.s["rom_source"]):
                r = rom.patch(self.s["rom_source"])
                if not r["ok"]:
                    return r
                self.s["elf_hash"] = h
                settings.save(self.s)
            srv = self.s["server"]
            info = servers.probe(srv["address"], srv["port"], timeout=2.0)
            self.srv_info = info
            if info is None:
                return {"ok": False, "offline": True,
                        "msg": T("server_offline", n=srv.get("name") or srv["address"], a=f'{srv["address"]}:{srv["port"]}')}
            ip = rom.set_server(srv["address"], srv["port"])
            profs = save.profiles() if os.path.exists(paths.SAVE) else []
            used = [p for p in profs if p["used"]]
            slot = used[0]["slot"] if used else None
            if self.s.get("unlock_all", True):
                # Online-Profil (Platz 3, alles freigeschaltet) mit dem Fahrernamen
                name = self.s.get("player_name") or next((p["name"] for p in used if not p.get("online")), "") \
                    or next((p["name"] for p in used), "") or os.environ.get("USERNAME", "")
                slot = save.ensure_online_profile(name)
                if not self.s.get("player_name"):
                    self.s["player_name"] = save.profiles()[slot]["name"]
                    settings.save(self.s)
                used = [p for p in save.profiles() if p["used"]]
            auto = {"host": 2, "join": 3}.get(mode, 1) if self.s.get("auto_nav", True) else 0
            rom.set_auto(auto, slot)
            names = [p["name"] for p in used if p["slot"] == slot] or [p["name"] for p in used]
            melon.prepare(self.s["mac"], names[0] if names else "")
            melon.start(paths.ROM_OUT, melon.get_display().get("fullscreen", False))
            return {"ok": True, "ip": ip}
        except OSError as e:
            return {"ok": False, "msg": T("server_unresolvable", e=e)}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    # ---------- Einstellungen ----------
    def get_bindings(self):
        b = melon.get_bindings()
        b["keys"] = melon.DS_KEYS
        b["hotkeys"] = list(melon.HOTKEYS)
        b["pads"] = pad.list_pads()
        b["joy_labels"] = {k: pad.label(v) for k, v in b["joystick"].items()}
        return b

    def set_key(self, name, value):
        melon.set_bindings(keyboard={name: value})
        return True

    def set_joy(self, name, value):
        melon.set_bindings(joystick={name: value})
        return pad.label(value)

    def set_joystick_id(self, idx):
        melon.set_bindings(joystick_id=idx)
        return True

    def capture_pad(self, idx=None):
        v, which = pad.capture(None if idx is None else int(idx))
        if which is not None:                      # an diesem Controller wurde gedrückt -> für melonDS übernehmen
            melon.set_bindings(joystick_id=which)
        return {"value": v, "label": pad.label(v), "pad": which}

    def reset_keys(self):
        melon.set_bindings(keyboard={k: v for k, v in melon.DEFAULT_KEYS.items()})
        return self.get_bindings()

    def get_display(self):
        return melon.get_display()

    def set_display(self, d):
        melon.set_display(d)
        return True

    # ---------- Profil ----------
    def profile(self):
        try:
            prof = save.profiles()
            err = None
        except Exception as e:
            prof, err = [], str(e)
        h = history.load()
        online = next((p for p in prof if p.get("online")), None)
        story = next((p["name"] for p in prof if p["used"] and not p.get("online")), "")
        return {"profiles": prof, "error": err, "summary": history.summary(h), "history": h[-50:][::-1],
                "driver": (online or {}).get("name") or self.s.get("player_name") or story,
                "mac": self.s["mac"], "name_max": save.NAME_MAX}

    def set_driver_name(self, name):
        """Online-Fahrername: steht im Online-Profil (Platz 3) und wird beim nächsten Start dafür benutzt."""
        name = (name or "").strip()
        if not name or len(name) > save.NAME_MAX:
            return {"ok": False, "msg": T("name_len", n=save.NAME_MAX)}
        if any(c not in save.ALLOWED for c in name):
            return {"ok": False, "msg": T("name_chars")}
        if os.path.exists(paths.SAVE) and any(p.get("online") for p in save.profiles()):
            r = self.set_name(save.ONLINE_SLOT, name)
            if not r.get("ok"):
                return r
        self.s["player_name"] = name
        settings.save(self.s)
        return {"ok": True}

    def set_name(self, slot, name):
        if melon.running():
            return {"ok": False, "msg": T("close_game_first")}
        try:
            save.set_name(int(slot), name)
            if int(slot) == save.ONLINE_SLOT:
                self.s["player_name"] = name.strip()
                settings.save(self.s)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def open_folder(self, which):
        p = {"user": paths.USER_DIR, "melon": paths.MELON_DIR}.get(which, paths.BASE)
        if sys.platform == "win32":
            os.startfile(p)
        return True


def _log_errors(cls):
    """Jede API-Methode: Fehler ins Logbuch (user/launcher_log.txt) schreiben und sichtbar zurückgeben."""
    import functools, traceback
    def wrap(fn):
        @functools.wraps(fn)
        def inner(*a, **kw):
            try:
                return fn(*a, **kw)
            except Exception as e:
                try:
                    with open(os.path.join(paths.USER_DIR, "launcher_log.txt"), "a", encoding="utf-8") as f:
                        f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + fn.__name__ + "\n" + traceback.format_exc() + "\n")
                except OSError:
                    pass
                return {"ok": False, "error": True, "msg": f"{type(e).__name__}: {e}"}
        return inner
    for name, fn in list(vars(cls).items()):
        if callable(fn) and not name.startswith("_"):
            setattr(cls, name, wrap(fn))
    return cls


_log_errors(Api)


def main():
    import webview
    api = Api()
    win = webview.create_window("Race-O-Rama Online", os.path.join(paths.UI_DIR, "index.html"), js_api=api,
                                width=1100, height=700, min_size=(940, 600), background_color="#0E1014")
    api.window = win
    webview.start(debug="--debug" in sys.argv)


if __name__ == "__main__":
    main()
