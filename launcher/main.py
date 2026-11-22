"""Race-O-Rama Online – Launcher.

Fenster: pywebview (unter Windows Edge WebView2), Oberfläche in ui/.
Start im Entwicklungsmodus:  python main.py
"""
import os, sys, threading, time


def _unblock_own_files():
    """Dateien aus einer heruntergeladenen Zip tragen unter Windows die Markierung "aus dem Internet"
    (Zone.Identifier). Das .NET-Framework lädt dann Python.Runtime.dll nicht, und pywebview startet nicht
    ("Failed to resolve Python.Runtime.Loader.Initialize"). Markierung bei den eigenen Dateien entfernen."""
    if not getattr(sys, "frozen", False) or sys.platform != "win32":
        return
    for root, _dirs, files in os.walk(os.path.dirname(sys.executable)):
        for f in files:
            try:
                os.remove(os.path.join(root, f) + ":Zone.Identifier")
            except OSError:
                pass


def _server_mode():
    """macOS-Paket: "RORM Online --server ..." startet den mitgelieferten Server statt des Launchers."""
    if "--server" not in sys.argv:
        return
    import runpy
    here = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    src = os.path.join(here, "server", "server.py")
    if not os.path.exists(src):
        src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server", "server.py")
    sys.argv = [src] + [a for a in sys.argv[1:] if a != "--server"]
    try:
        runpy.run_path(src, run_name="__main__")
    except KeyboardInterrupt:
        pass
    sys.exit(0)


_server_mode()
_unblock_own_files()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import paths, settings, rom, melon, servers, save, history, pad, i18n  # noqa: E402
from core.i18n import T  # noqa: E402

VERSION = "1.0.0-beta3"


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
        self.srv_checked = 0.0
        self._hist_lock = threading.Lock()
        threading.Thread(target=self._watch_server, daemon=True).start()

    def _watch_server(self):
        while True:
            srv = self.s["server"]
            try:
                self.srv_info = servers.probe(srv["address"], srv["port"])
            except Exception:
                self.srv_info = None
            self.srv_checked = time.time()
            n = getattr(self, "_wn", 0) + 1; self._wn = n
            if self.srv_info and n % 8 == 0:      # alle ~30 s Rennen abholen (Server merkt sie nur bis zum Neustart)
                self._sync_history()
            time.sleep(4)

    def _driver_name(self):
        try:
            p = next((p for p in save.profiles() if p.get("online") and p["used"]), None)
            if p:
                return p["name"]
        except Exception:
            pass
        return self.s.get("player_name") or ""

    def _sync_history(self):
        """Rennverlauf vom ausgewählten Server holen und in user/history.json übernehmen."""
        srv = self.s["server"]
        try:
            races = servers.fetch_history(srv["address"], srv["port"], self.s["mac"], self._driver_name())
            if races:
                with self._hist_lock:
                    return history.add(races, self.s["mac"])
        except Exception:
            pass
        return None

    # ---------- allgemein ----------
    def state(self):
        s = self.s
        crash = melon.crashed()
        if crash is not None:
            with open(os.path.join(paths.USER_DIR, "launcher_log.txt"), "a", encoding="utf-8") as f:
                f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + f"melonDS beendet mit Code {crash & 0xFFFFFFFF:#x}\n")
        return {"version": VERSION, "lang": s["lang"], "auto_nav": s.get("auto_nav", True), "unlock_all": s.get("unlock_all", True), "intro_seen": s.get("intro_seen", False), "setup_done": s["setup_done"] and rom.is_ready(),
                "server": s["server"], "server_name": s["server_name"] or os.environ.get("COMPUTERNAME", "Mein Server"),
                "mac": s["mac"], "melon": os.path.exists(paths.MELON_EXE), "playing": melon.running(),
                "hosting": servers.host_running(), "pad": pad.available(), "pad_error": pad.ERROR, "crash": crash,
                "srv_online": self.srv_info is not None, "srv_checked": self.srv_checked > 0,
                "srv_players": (self.srv_info or {}).get("players"), "srv_ping": (self.srv_info or {}).get("ping_ms")}

    def set_intro_seen(self):
        self.s["intro_seen"] = True
        settings.save(self.s)
        return True

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
        addrs = [{"ip": a, "name": n} for a, _p, n in servers.local_ifaces() if a != ip]
        return {"ok": servers.host_running(), "tailscale_ip": ip, "addrs": addrs}

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
            # dem Server den Fahrernamen zu dieser MAC nennen (für Rennverlauf/Statistik)
            nm = names[0] if names else ""
            threading.Thread(target=lambda: servers.fetch_history(srv["address"], srv["port"], self.s["mac"], nm),
                             daemon=True).start()
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
        b["pad_ok"], b["pad_error"] = bool(pad.available()), pad.ERROR
        if pad.ERROR and not getattr(self, "_pad_err_logged", False):
            self._pad_err_logged = True
            with open(os.path.join(paths.USER_DIR, "launcher_log.txt"), "a", encoding="utf-8") as f:
                f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + "Controller: " + pad.ERROR + "\n")
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
        h = self._sync_history() or history.load()
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
        os.makedirs(p, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(p)
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", p])
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


def _fatal(msg):
    """Startfehler: ins Logbuch schreiben und als normales Windows-Meldungsfenster zeigen."""
    try:
        with open(os.path.join(paths.USER_DIR, "launcher_log.txt"), "a", encoding="utf-8") as f:
            f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + "Startfehler\n" + msg + "\n")
    except OSError:
        pass
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, msg[-1500:] + "\n\n(user\\launcher_log.txt)",
                                         "Race-O-Rama Online", 0x10)
    elif sys.platform == "darwin":
        import subprocess
        txt = (msg[-800:] + "\n\n(user/launcher_log.txt)").replace("\\", "/").replace('"', "'")
        subprocess.run(["osascript", "-e", f'display alert "Race-O-Rama Online" message "{txt}" as critical'])
    else:
        print(msg, file=sys.stderr)


def _crash_logging():
    """Abstürze ohne Python-Fehlermeldung (z.B. in WebView2/.NET/SDL) landen in user/crash_log.txt."""
    try:
        os.makedirs(paths.USER_DIR, exist_ok=True)
        p = os.path.join(paths.USER_DIR, "crash_log.txt")
        if os.path.exists(p) and os.path.getsize(p) > 512 * 1024:
            os.replace(p, p + ".old")
        f = open(p, "a", encoding="utf-8", buffering=1)
        f.write(time.strftime("\n=== Start %Y-%m-%d %H:%M:%S ") + f"v{VERSION} pid {os.getpid()} ===\n")
        import faulthandler
        faulthandler.enable(file=f, all_threads=True)
        def hook(a):
            import traceback
            f.write(time.strftime("[%H:%M:%S] ") + f"Fehler im Thread {a.thread.name if a.thread else '?'}:\n")
            f.write("".join(traceback.format_exception(a.exc_type, a.exc_value, a.exc_traceback)))
        threading.excepthook = hook
        return f
    except Exception:
        return None


def main():
    log = _crash_logging()
    try:
        _run()
        if log:
            log.write(time.strftime("[%H:%M:%S] ") + "normal beendet\n")
    except Exception:
        import traceback
        _fatal(traceback.format_exc())


def _run():
    import webview
    paths.mac_install_melon()
    api = Api()
    win = webview.create_window("Race-O-Rama Online", os.path.join(paths.UI_DIR, "index.html"), js_api=api,
                                width=1100, height=700, min_size=(940, 600), background_color="#0E1014")
    api.window = win
    # Eigener WebView2-Datenordner je Installation: zwei Launcher gleichzeitig (z.B. zwei Testordner)
    # oder ein noch laufender WebView2-Rest der letzten Sitzung blockieren sich so nicht gegenseitig.
    store = os.path.join(paths.USER_DIR, "webview")
    try:
        webview.start(debug="--debug" in sys.argv, storage_path=store)
    except TypeError:          # ältere pywebview-Version ohne storage_path
        webview.start(debug="--debug" in sys.argv)


if __name__ == "__main__":
    main()
