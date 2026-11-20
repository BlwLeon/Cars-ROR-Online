"""Server finden (Tailnet + dieser PC) und eigenen Server in einem Konsolenfenster starten."""
import json, os, socket, subprocess, sys, time
from . import paths
from .server_suche import search as _search, tailscale_exe, INFO_REQ, INFO_RES

_host = None


def search(extra=()):
    res, devs = _search(27015, list(extra))
    return {"tailscale": devs is not None, "servers": res}


def probe(address, port, timeout=1.2):
    """Fragt einen Server nach seinem Fußabdruck. -> Info-dict (mit ping_ms) oder None, wenn er nicht antwortet."""
    try:
        ip = socket.gethostbyname(address.strip())
    except OSError:
        return None
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0.3)
    try:
        t0 = time.time()
        end = t0 + timeout
        while time.time() < end:
            try:
                s.sendto(INFO_REQ, (ip, int(port)))
                data, _ = s.recvfrom(4096)
            except (socket.timeout, OSError):
                continue        # Windows meldet "Port nicht erreichbar" als OSError -> nochmal versuchen
            if data.startswith(INFO_RES):
                try:
                    info = json.loads(data[len(INFO_RES):].decode("utf-8"))
                except ValueError:
                    return None
                info["ping_ms"] = int((time.time() - t0) * 1000)
                return info
        return None
    finally:
        s.close()


def host_running():
    return _host is not None and _host.poll() is None


def start_host(name):
    """Öffnet den Server in einer eigenen Konsole (wie Server_starten.bat)."""
    global _host
    if host_running():
        return _host.pid
    args = ["--name", name] if name else []
    if os.path.exists(paths.SERVER_EXE):
        cmd, cwd = [paths.SERVER_EXE] + args, os.path.dirname(paths.SERVER_EXE)
    else:
        cmd, cwd = [sys.executable, paths.SERVER_PY] + args, os.path.dirname(paths.SERVER_PY)
    flags = 0x00000010 if sys.platform == "win32" else 0     # CREATE_NEW_CONSOLE
    _host = subprocess.Popen(cmd, cwd=cwd, creationflags=flags)
    return _host.pid


def stop_host():
    global _host
    if host_running():
        _host.terminate()
    _host = None


def tailscale_ip():
    exe = tailscale_exe()
    if not exe:
        return None
    try:
        flags = 0x08000000 if sys.platform == "win32" else 0
        out = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, timeout=5, creationflags=flags).stdout.split()
        return out[0] if out else None
    except Exception:
        return None
