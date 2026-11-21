#!/usr/bin/env python3
"""Cars Race-O-Rama Online - Server-Suche.

Sucht Cars-RORM-Server auf diesem PC, bei allen Geräten im eigenen Tailnet (Tailscale)
und per Broadcast in allen lokalen Netzen (LAN, Radmin VPN, ZeroTier, Hamachi ...).

  python server_suche.py                         Server auflisten
  python server_suche.py --json                  Ergebnis als JSON (für den Launcher)
  python server_suche.py --ip 100.1.2.3          zusätzlich diese Adresse prüfen
"""
import argparse, json, os, shutil, socket, subprocess, sys, time

INFO_REQ, INFO_RES = b"CRRO-INFO?", b"CRRO-INFO!"
HERE = os.path.dirname(os.path.abspath(__file__))


def tailscale_exe():
    for c in (shutil.which("tailscale"), r"C:\Program Files\Tailscale\tailscale.exe",
              "/Applications/Tailscale.app/Contents/MacOS/Tailscale"):
        if c and os.path.exists(c):
            return c
    return None


def tailnet_devices():
    """[(ip, gerätename, online, ist_dieser_pc)] aus 'tailscale status --json'."""
    exe = tailscale_exe()
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=8,
                             creationflags=0x08000000 if sys.platform == "win32" else 0).stdout
        st = json.loads(out)
    except Exception:
        return None
    devs = []
    def add(node, me):
        ips = [i for i in node.get("TailscaleIPs") or [] if "." in i]
        if ips:
            name = node.get("HostName") or (node.get("DNSName") or "?").split(".")[0]
            devs.append((ips[0], name, bool(node.get("Online", me)), me))
    if st.get("Self"):
        add(st["Self"], True)
    for p in (st.get("Peer") or {}).values():
        add(p, False)
    return devs


_if_cache = (0.0, [])


def _flags():
    return 0x08000000 if sys.platform == "win32" else 0


def local_ifaces():
    """[(ip, präfixlänge, name)] aller IPv4-Adressen dieses PCs (ohne Loopback). 60 s gecacht."""
    global _if_cache
    if time.time() - _if_cache[0] < 60:
        return _if_cache[1]
    res = []
    try:
        if sys.platform == "win32":
            ps = ("Get-NetIPAddress -AddressFamily IPv4 | Select-Object IPAddress,PrefixLength,InterfaceAlias"
                  " | ConvertTo-Json -Compress")
            out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                                 capture_output=True, text=True, timeout=6, creationflags=_flags()).stdout
            data = json.loads(out or "[]")
            for e in data if isinstance(data, list) else [data]:
                res.append((e["IPAddress"], int(e["PrefixLength"]), e.get("InterfaceAlias") or ""))
        else:
            out = subprocess.run(["ip", "-4", "-o", "addr"], capture_output=True, text=True, timeout=4).stdout
            for line in out.splitlines():
                p = line.split()
                if "inet" in p:
                    ip, pre = p[p.index("inet") + 1].split("/")
                    res.append((ip, int(pre), p[1]))
    except Exception:
        pass
    if not res:      # Notlösung: Adressen des Rechnernamens, Netz /24 annehmen
        try:
            for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
                res.append((ip, 24, ""))
        except OSError:
            pass
    res = [r for r in res if not r[0].startswith(("127.", "169.254."))]
    _if_cache = (time.time(), res)
    return res


def _ip_int(ip):
    return int.from_bytes(socket.inet_aton(ip), "big")


def _is_tailscale(ip):
    return (_ip_int(ip) & 0xFFC00000) == 0x64400000      # 100.64.0.0/10


def _is_tailscale_safe(ip):
    try:
        return _is_tailscale(ip)
    except OSError:
        return False


def broadcast_targets():
    """{Broadcast-Adresse: Netzname} für jedes lokale Netz (Tailscale kann kein Broadcast)."""
    out = {}
    for ip, pre, name in local_ifaces():
        if pre >= 31 or pre < 8 or _is_tailscale(ip):
            continue
        mask = (0xFFFFFFFF << (32 - pre)) & 0xFFFFFFFF
        bc = socket.inet_ntoa(((_ip_int(ip) | (~mask & 0xFFFFFFFF))).to_bytes(4, "big"))
        out[bc] = name
    return out


def _net_name(ip):
    """Name des lokalen Netzes (z.B. 'Radmin VPN'), in dem eine Adresse liegt."""
    try:
        x = _ip_int(ip)
    except OSError:
        return None
    for mine, pre, name in local_ifaces():
        mask = (0xFFFFFFFF << (32 - pre)) & 0xFFFFFFFF
        if (x & mask) == (_ip_int(mine) & mask):
            return name or "LAN"
    return None


def search(port, extra_ips=(), timeout=1.5):
    devs = tailnet_devices()
    targets = {"127.0.0.1": ("dieser PC", True)}
    for ip, _pre, name in local_ifaces():
        targets.setdefault(ip, ("dieser PC", True))
    for ip, name, online, me in devs or []:
        if online:
            targets[ip] = (name, me)
    for ip in extra_ips:
        targets.setdefault(ip, (ip, False))
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.setblocking(False)
    sent = {}
    t_bc = time.time()
    for ip in list(targets) + list(broadcast_targets()) + ["255.255.255.255"]:
        try:
            s.sendto(INFO_REQ, (ip, port)); sent.setdefault(ip, time.time())
        except OSError:
            pass
    found, end = {}, time.time() + timeout
    while time.time() < end:
        try:
            data, (ip, _) = s.recvfrom(4096)
        except (BlockingIOError, InterruptedError):
            time.sleep(0.003); continue
        except OSError:          # Windows: ICMP "Port nicht erreichbar" -> ignorieren
            time.sleep(0.003); continue
        if not data.startswith(INFO_RES) or ip in found:
            continue
        try:
            info = json.loads(data[len(INFO_RES):].decode("utf-8"))
        except Exception:
            continue
        dev, me = targets.get(ip) or (_net_name(ip) or ip, False)
        info.update(ip=ip, device=dev, local=(ip == "127.0.0.1" or me),
                    ping_ms=int((time.time() - sent.get(ip, t_bc)) * 1000))
        found[ip] = info
    # derselbe Server kann über 127.0.0.1 UND eigene Adressen (Tailscale, LAN, VPN) antworten -> nur einmal zeigen
    res = list(found.values())
    if any(i["ip"] == "127.0.0.1" for i in res):
        res = [i for i in res if not (i["local"] and i["ip"] != "127.0.0.1")]
    # Server-Kennung (sid): dieselbe Instanz nur einmal - bevorzugt dieser PC, dann Tailscale, dann Rest
    res.sort(key=lambda i: (i["ip"] != "127.0.0.1", not i["local"], not _is_tailscale_safe(i["ip"]), i["ping_ms"]))
    seen, uniq = set(), []
    for i in res:
        k = i.get("sid")
        if k and k in seen:
            continue
        seen.add(k); uniq.append(i)
    res = uniq
    res.sort(key=lambda i: (not i["local"], i["ping_ms"]))
    return res, devs


def main():
    ap = argparse.ArgumentParser(description="Cars Race-O-Rama Online - Server-Suche")
    ap.add_argument("--port", type=int, default=27015)
    ap.add_argument("--ip", action="append", default=[], help="zusätzliche Adresse prüfen")
    ap.add_argument("--json", action="store_true", help="Ergebnis als JSON ausgeben")
    a = ap.parse_args()

    res, devs = search(a.port, a.ip)
    if a.json:
        print(json.dumps({"tailscale": devs is not None, "servers": res}, ensure_ascii=False)); return

    print()
    if devs is None:
        print(" Hinweis: Tailscale nicht gefunden - suche auf diesem PC und per Broadcast in lokalen Netzen/VPNs.")
    else:
        print(f" Tailnet: {sum(1 for d in devs if d[2])} Geräte online geprüft.")
    if not res:
        print(" Kein Server gefunden.")
        print(" - Läuft beim Host Server_starten.bat?")
        print(" - Ist der Host-PC im selben Tailnet (bzw. mit dir geteilt)?")
        print(" - Hat der Host die Windows-Firewall für Python erlaubt (privat UND öffentlich)?")
        return 1
    print()
    for n, i in enumerate(res, 1):
        rooms = i.get("rooms") or []
        rtxt = ", ".join(f"Raum {r['players']}/{r['max']}{'' if r['open'] else ' (läuft)'}" for r in rooms) or "kein offener Raum"
        where = "dieser PC" if i["local"] else f"{i['device']} {i['ip']}"
        print(f"  [{n}] {i['name']:<20} {where:<28} {i['ping_ms']:>4} ms   Mod {i.get('mod', '?')}   {rtxt}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
