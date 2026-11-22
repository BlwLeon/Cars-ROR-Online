#!/usr/bin/env python3
"""Cars Race-O-Rama Online - Server (Milestone 2).

Start:   python server.py                    (UDP-Port 27015)
         python server.py 12345              (anderer Port)
         python server.py --lag 150 --jitter 30 --loss 5
                                             (schlechte Verbindung simulieren: +150 ms Ping,
                                              +-30 ms Schwankung, 5 % Paketverlust je Richtung)

Der Server verwaltet Räume (ein Host + bis zu 3 Mitspieler) und leitet
Lobby-Nachrichten (zuverlässig) und Renndaten (Data Sharing, unzuverlässig) weiter.
"""
import socket, struct, sys, time, select, argparse, heapq, random, json, subprocess, shutil, os

ap = argparse.ArgumentParser(description="Cars Race-O-Rama Online Server")
ap.add_argument("port", nargs="?", type=int, default=27015)
ap.add_argument("--name", default=None, help="Servername, der bei der Server-Suche angezeigt wird (Standard: PC-Name)")
ap.add_argument("--lag", type=float, default=0, help="zusätzlicher Ping in ms (Hin+Rück)")
ap.add_argument("--jitter", type=float, default=0, help="zufällige Schwankung in ms je Paket")
ap.add_argument("--loss", type=float, default=0, help="Paketverlust in Prozent je Richtung")
ap.add_argument("--logdir", default=None, help="Ordner für server_log.txt / server_portlog.txt")
ARGS = ap.parse_args()
PORT = ARGS.port
SIM = ARGS.lag > 0 or ARGS.jitter > 0 or ARGS.loss > 0
PROTO_VER = 2
MOD_VER = "R12"                        # Stand der Mod (ROM-Patch + Server)
SERVER_NAME = (ARGS.name or socket.gethostname())[:32]
SERVER_SID = "%08x" % random.getrandbits(32)        # erkennt denselben Server unter mehreren Adressen
INFO_REQ, INFO_RES = b"CRRO-INFO?", b"CRRO-INFO!"   # "Fußabdruck" für Server-Suche / Launcher
HIST_REQ, HIST_RES = b"CRRO-HIST?", b"CRRO-HIST!"   # Rennverlauf eines Spielers (MAC) für das Launcher-Profil
HDR = 10
M_HELLO, M_WELCOME, M_PING, M_PONG, M_RESET = 1, 2, 3, 4, 5
M_HOST_OPEN, M_HOST_UPDATE, M_HOST_CLOSE, M_LIST_REQ, M_LIST = 16, 17, 18, 19, 20
M_JOIN_REQ, M_JOIN_RES, M_PEER_JOIN, M_PEER_LEFT, M_LEAVE, M_PORT, M_PORT_U = 21, 22, 23, 24, 25, 26, 27
M_DS = 30
NAMES = {1: 'HELLO', 3: 'PING', 16: 'HOST_OPEN', 17: 'HOST_UPDATE', 18: 'HOST_CLOSE', 19: 'LIST_REQ',
         21: 'JOIN_REQ', 25: 'LEAVE', 26: 'PORT', 30: 'DS'}
RESEND_MIN = 0.15  # Sekunden bis zur Wiederholung unbestätigter Nachrichten (mindestens; sonst 1,5 x Ping)
TIMEOUT = 8.0      # Sekunden ohne Lebenszeichen -> Spieler entfernt
DGRAM_MAX = 640

# Log-Datei pro Sitzung: wird bei jedem Serverstart gelöscht und neu angelegt (liegt neben server.py)
import os
_HERE = ARGS.logdir or os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
os.makedirs(_HERE, exist_ok=True)
LOGPATH = os.path.join(_HERE, "server_log.txt")
try: LOGF = open(LOGPATH, "w", encoding="utf-8", buffering=1)
except OSError: LOGF = None
# Spielnachrichten (Lobby, Namen, Ergebnisse) für die spätere Auswertung im Launcher-Verlauf
try: PORTF = open(os.path.join(_HERE, "server_portlog.txt"), "w", encoding="utf-8", buffering=1)
except OSError: PORTF = None
def portlog(c, port, dest, payload):
    if PORTF and c.room:
        try: PORTF.write(f"{time.time():.3f} r{c.room.id} a{c.aid} p{port} d{dest:x} {bytes(payload).hex()}\n")
        except OSError: pass
def log(msg):
    line = time.strftime("[%H:%M:%S] ") + msg
    print(line, flush=True)
    if LOGF:
        try: LOGF.write(line + "\n")
        except OSError: pass
def mac(b): return ":".join(f"{x:02X}" for x in b)

class Client:
    def __init__(self, cid, addr, macaddr):
        self.id, self.addr, self.mac = cid, addr, macaddr
        self.nonce = None
        self.last = time.time()
        self.tx_seq, self.rx_expect = 1, 1
        self.unacked = {}          # seq -> [type, data, last_sent, sacked]
        self.unrel = []            # (type, data, seq)
        self.ooo = {}              # zu früh angekommene zuverlässige Nachrichten: seq -> (type, data)
        self.rtt = 0.0
        self.need_ack = False
        self.room = None; self.aid = None
        self.stats = {'port_in': 0, 'ds_in': 0}
    def name(self): return f"#{self.id} ({mac(self.mac)})"
    def send_rel(self, t, data):
        self.unacked[self.tx_seq] = [t, bytes(data), 0.0, False]; self.tx_seq = (self.tx_seq + 1) & 0xFFFF or 1
    def send_unrel(self, t, data, seq=0): self.unrel.append((t, bytes(data), seq))

class Room:
    def __init__(self, rid, host):
        self.id, self.host = rid, host
        self.members = {0: host}
        self.ggid = self.tgid = 0; self.entry = 1; self.maxent = 3; self.attr = 1; self.ug = b''
        self.chan = 1; self.pmax = 0x200; self.cmax = 0x22
        self.race = None           # laufendes Rennen: {"start", "last", "macs", "res"}
        self.last_race = None      # zuletzt beendetes Rennen (für nachträgliche Zielmeldungen)
        self.sel = None            # (Strecke, Runden) aus der Lobby-Auswahl des Hosts (Port 13, Typ 0x04)
    def update(self, d):
        self.ggid, self.tgid, self.entry, self.maxent, self.attr, uglen, self.chan = struct.unpack_from('<IHBBBBB', d, 0)
        self.pmax, self.cmax = struct.unpack_from('<HH', d, 12)
        self.ug = bytes(d[16:16 + uglen])

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("0.0.0.0", PORT))

# ---- Netzwerk-Simulator (Verzögerung / Schwankung / Verlust) ----
sim_q = []      # (zeit, nr, richtung, daten, adresse)
sim_n = 0
def sim_delay():
    return (ARGS.lag / 2 + random.uniform(0, ARGS.jitter)) / 1000.0
def send_dgram(data, addr):
    global sim_n
    if not SIM: sock.sendto(data, addr); return
    if random.random() * 100 < ARGS.loss: return
    sim_n += 1; heapq.heappush(sim_q, (time.time() + sim_delay(), sim_n, 'out', bytes(data), addr))
def info_reply(addr):
    info = {"game": "Cars Race-O-Rama Online", "mod": MOD_VER, "proto": PROTO_VER, "name": SERVER_NAME,
            "port": PORT, "sid": SERVER_SID, "players": len(clients),
            "rooms": [{"id": r.id, "players": len(r.members), "max": r.maxent + 1, "open": bool(r.entry)}
                      for r in rooms.values()]}
    try: sock.sendto(INFO_RES + json.dumps(info).encode("utf-8"), addr)
    except OSError: pass
# ---- Rennverlauf (für die Profil-Statistik im Launcher) ----
# Namen kommen aus der Lobby (Port 12, Typ 02: [02 00][MAC 6][6 Bytes][Name UTF-16]).
# Ein Rennen = Zeitraum, in dem Renndaten (M_DS) fließen. Platzierungen: noch offen (Ergebnis-Nachricht
# muss erst aus einem Mitschnitt bestimmt werden) -> "place": None.
names = {}         # MAC-bytes -> Fahrername
races = []         # [{"time", "server", "track", "players": [{"name","mac","place"}]}]
def learn_result(r, payload):
    """Port 13, Typ 0x0E = Zielmeldung: [0E][aid][u32 Gesamtzeit 1/100 s][u32 Runden ...].
    Der Host leitet die Meldungen der Clients an alle weiter -> pro aid nur einmal zählen."""
    p = bytes(payload)
    if len(p) < 6 or p[0] != 0x0E: return
    rc = r.race or (r.last_race if r.last_race and time.time() - r.last_race["last"] < 15 else None)
    m = r.members.get(p[1] & 3)
    if not rc or not m: return
    if m.mac not in rc["res"]:
        v = [struct.unpack_from('<I', p, o)[0] for o in range(2, len(p) - 3, 4)]   # Gesamt, beste Runde, Runden...
        rc["res"][m.mac] = v[0]
        rc["laps"][m.mac] = {"best_cs": v[1] if len(v) > 1 else None, "laps_cs": [x for x in v[2:] if x]}
        if rc is r.last_race: rc["entry_fix"](rc)
def learn_selection(r, payload):
    """Port 13, Typ 0x04 vom Host: [04][09][Strecke][00][Runden]... (vor jedem Rennen)."""
    p = bytes(payload)
    if len(p) >= 5 and p[0] == 0x04:
        if r.sel != (p[2], p[4]):
            log(f"Raum {r.id}: Host hat gewählt: STRECKE {p[2]} ({p[4]} Runde{'n' if p[4] != 1 else ''})")
        r.sel = (p[2], p[4])
def learn_name(payload):
    p = bytes(payload)
    if len(p) >= 16 and p[0] == 0x02:
        raw = p[14:14 + 20]
        n = raw.decode("utf-16-le", "replace").split("\0")[0].strip()
        if n and n.isprintable(): names[p[2:8]] = n[:10]
def race_tick(now):
    for r in rooms.values():
        rc = r.race
        if rc and now - rc["last"] > 4.0:
            r.race = None
            dur = rc["last"] - rc["start"]
            if dur >= 20 and len(rc["macs"]) >= 2:
                e = {"time": time.strftime("%Y-%m-%d %H:%M", time.localtime(rc["start"])), "server": SERVER_NAME,
                     "track": rc["track"], "laps": rc["nlaps"], "duration": int(dur), "players": []}
                rc["entry"] = e
                def fix(rc):        # Plätze aus den Zielzeiten (spät eintreffende Meldungen werden nachgetragen)
                    order = sorted(rc["res"], key=lambda m: rc["res"][m])
                    best = min(rc["res"].values()) if rc["res"] else 0
                    rc["entry"]["players"] = [dict({"mac": mac(m), "place": (order.index(m) + 1) if m in rc["res"] else None,
                                               "time_cs": rc["res"].get(m),
                                               # Letzter wird vom Spiel ausgezählt, sobald alle anderen im Ziel sind
                                               # -> unsinnig hohe Zeit statt echter Zielzeit
                                               "dnf": m not in rc["res"] or (len(rc["res"]) > 1 and rc["res"][m] > 2.5 * best)},
                                              **rc["laps"].get(m, {})) for m in rc["macs"]]
                rc["entry_fix"] = fix; fix(rc)
                r.last_race = rc
                races.append(e); del races[:-500]
                log(f"Raum {r.id}: Rennen beendet ({int(dur)} s, " + ", ".join(
                    f"{names.get(bytes.fromhex(p['mac'].replace(':', ''))) or p['mac']} Platz {p['place'] or '-'}" for p in e["players"]) + ")")
            if PORTF: PORTF.write(f"{now:.3f} r{r.id} RACE END {dur:.1f}s\n")
def hist_reply(data, addr):
    # Anfrage: "CRRO-HIST?" + MAC [+ "|" + Fahrername]. Der Launcher kennt den Namen seines Online-Profils;
    # aus dem Spiel kommt nur der Name des Hosts (Port 12), Clients schicken ihren nicht über einen Port.
    q = data[len(HIST_REQ):].decode("utf-8", "replace").strip()
    want, _, nm = q.partition("|")
    want = want.strip().upper()
    try:
        mb = bytes.fromhex(want.replace(":", ""))
        nm = "".join(ch for ch in nm if ch.isalnum())[:10]
        if len(mb) == 6 and nm: names[mb] = nm
    except ValueError:
        pass
    res = []
    for e in races:
        if any(p["mac"] == want for p in e["players"]):
            e2 = dict(e); e2["players"] = [dict(p, name=names.get(bytes.fromhex(p["mac"].replace(":", ""))) or p["mac"])
                                           for p in e["players"]]
            res.append(e2)
    res = res[-100:]
    try: sock.sendto(HIST_RES + json.dumps({"sid": SERVER_SID, "races": res}).encode("utf-8"), addr)
    except OSError: pass
def recv_dgram(data, addr):
    global sim_n
    if data[:len(INFO_REQ)] == INFO_REQ: info_reply(addr); return      # Server-Suche: nicht durch den Lag-Simulator
    if data[:len(HIST_REQ)] == HIST_REQ: hist_reply(data, addr); return
    if not SIM: on_datagram(data, addr); return
    if random.random() * 100 < ARGS.loss: return
    sim_n += 1; heapq.heappush(sim_q, (time.time() + sim_delay(), sim_n, 'in', bytes(data), addr))
def sim_run():
    now = time.time()
    while sim_q and sim_q[0][0] <= now:
        _, _, d, data, addr = heapq.heappop(sim_q)
        if d == 'out': sock.sendto(data, addr)
        else: on_datagram(data, addr)
clients = {}       # addr -> Client
rooms = {}         # id -> Room
next_cid, next_rid = 1, 1

def leave_room(c, why=""):
    r = c.room
    if not r: return
    if c.aid == 0:
        log(f"Raum {r.id} geschlossen (Host {c.name()} {why})")
        for aid, m in list(r.members.items()):
            if m is not c:
                m.send_rel(M_PEER_LEFT, bytes([0])); m.room = None; m.aid = None
        rooms.pop(r.id, None)
    else:
        log(f"{c.name()} verlässt Raum {r.id} (aid {c.aid}) {why}")
        r.members.pop(c.aid, None)
        for m in r.members.values(): m.send_rel(M_PEER_LEFT, bytes([c.aid]))
    c.room = None; c.aid = None

def handle(c, t, d, rseq=0):
    global next_rid
    if t == M_PING:
        if len(d) >= 5: c.rtt = d[4] / 60.0
        c.send_unrel(M_PONG, d)
    elif t in (M_HOST_OPEN, M_HOST_UPDATE):
        if t == M_HOST_OPEN or not c.room or c.aid != 0:
            leave_room(c, "(neuer Raum)")
            r = Room(next_rid, c); next_rid += 1
            rooms[r.id] = r; c.room = r; c.aid = 0
            r.update(d)
            log(f"{c.name()} hostet Raum {r.id} (GGID {r.ggid:#x}, TGID {r.tgid:#x}, max {r.maxent + 1} Spieler)")
        else:
            c.room.update(d)
    elif t == M_HOST_CLOSE:
        leave_room(c, "(beendet)")
    elif t == M_LIST_REQ:
        out = bytearray([0])
        for r in list(rooms.values())[:4]:
            if r is c.room: continue
            out[0] += 1
            out += struct.pack('<H6sIHBBBBHH2x', r.id, r.host.mac, r.ggid, r.tgid, r.attr, len(r.ug), r.chan,
                               len(r.members), r.pmax, r.cmax) + r.ug
        c.send_rel(M_LIST, out)
    elif t == M_JOIN_REQ:
        rid = struct.unpack_from('<H', d)[0]; ssid = bytes(d[2:26])
        r = rooms.get(rid)
        if not r: res = 3
        elif not r.entry: res = 2
        elif len(r.members) > r.maxent: res = 1
        else: res = 0
        if res:
            log(f"{c.name()} -> Raum {rid}: abgelehnt ({['', 'voll', 'geschlossen', 'nicht gefunden'][res]})")
            c.send_rel(M_JOIN_RES, bytes([res, 0]) + b'\0' * 6); return
        leave_room(c)
        aid = next(a for a in (1, 2, 3) if a not in r.members)
        r.members[aid] = c; c.room = r; c.aid = aid
        log(f"{c.name()} tritt Raum {rid} bei (aid {aid})")
        c.send_rel(M_JOIN_RES, bytes([0, aid]) + r.host.mac)
        r.host.send_rel(M_PEER_JOIN, bytes([aid]) + c.mac + ssid)
        # Clients kennen sich gegenseitig (für Data Sharing, wie beim echten WM)
        for oaid, m in r.members.items():
            if oaid in (0, aid): continue
            m.send_rel(M_PEER_JOIN, bytes([aid]) + c.mac + bytes(24))
            c.send_rel(M_PEER_JOIN, bytes([oaid]) + m.mac + bytes(24))
    elif t == M_LEAVE:
        leave_room(c, "(beendet)")
    elif t == M_PORT:
        r = c.room
        if not r or len(d) < 6: return
        c.stats['port_in'] += 1
        port, _, dest = d[0], d[1], struct.unpack_from('<H', d, 2)[0]
        portlog(c, port, dest, d[6:])
        if (port & 15) == 12: learn_name(d[6:])
        elif (port & 15) == 13:
            learn_result(r, d[6:])
            if c.aid == 0: learn_selection(r, d[6:])
        fwd = bytes([port, c.aid]) + bytes(d[2:4]) + bytes([min(255, int(c.rtt * 60 + 0.5)), 0]) + bytes(d[6:])   # Byte 4 = Ping des Absenders (Frames)
        for aid, m in r.members.items():
            if m is not c and (dest >> aid) & 1: m.send_rel(M_PORT, fwd)
    elif t == M_PORT_U:
        r = c.room
        if not r or len(d) < 6: return
        c.stats['port_in'] += 1
        dest = struct.unpack_from('<H', d, 2)[0]
        fwd = bytes([d[0], c.aid]) + bytes(d[2:4]) + bytes([min(255, int(c.rtt * 60 + 0.5)), 0]) + bytes(d[6:])
        for aid, m in r.members.items():
            if m is not c and (dest >> aid) & 1: m.send_unrel(M_PORT_U, fwd, rseq)
    elif t == M_DS:
        r = c.room
        if not r: return
        c.stats['ds_in'] += 1
        if len(d) > 1: c.rtt = d[1] / 60.0
        now = time.time()
        if not r.race:
            r.race = {"start": now, "last": now, "macs": [], "res": {}, "laps": {},
                      "track": r.sel[0] if r.sel else None, "nlaps": r.sel[1] if r.sel else None}
            if PORTF: PORTF.write(f"{now:.3f} r{r.id} RACE START\n")
            log(f"Raum {r.id}: Rennen startet auf STRECKE {r.sel[0] if r.sel else '?'}")
        r.race["last"] = now
        if c.mac not in r.race["macs"]: r.race["macs"].append(c.mac)
        fwd = bytes([c.aid]) + bytes(d[1:])
        for m in r.members.values():
            if m is not c: m.send_unrel(M_DS, fwd)
            flush(m)   # Renndaten sofort weitergeben

def flush(c, force=False):
    now = time.time()
    sack = 0
    for seq in c.ooo:
        k = (seq - c.rx_expect - 1) & 0xFFFF
        if k < 16: sack |= 1 << k
    out = bytearray(b'CR' + bytes([PROTO_VER, 0]) + struct.pack('<HHH', c.id, (c.rx_expect - 1) & 0xFFFF, sack))
    payload = False
    while c.unrel and len(out) + 6 + len(c.unrel[0][1]) <= DGRAM_MAX:
        t, d, sq = c.unrel.pop(0); out += struct.pack('<BBHH', t, 0, sq, len(d)) + d; payload = True
    rto = max(RESEND_MIN, c.rtt * 1.5 + 0.07)
    for seq in sorted(c.unacked, key=lambda s: (s - c.tx_seq) & 0xFFFF):
        t, d, last, sacked = c.unacked[seq]
        if sacked or (last and now - last < rto): continue
        if len(out) + 6 + len(d) > DGRAM_MAX: break
        out += struct.pack('<BBHH', t, 1, seq, len(d)) + d
        c.unacked[seq][2] = now; payload = True
    if payload or c.need_ack or force:
        send_dgram(out, c.addr); c.need_ack = False

def reset_session(c):
    leave_room(c, "(neue Sitzung)")
    c.tx_seq, c.rx_expect = 1, 1
    c.unacked.clear(); c.unrel.clear(); c.ooo.clear(); c.need_ack = False

def on_datagram(data, addr):
    global next_cid
    if len(data) < HDR or data[:2] != b'CR' or data[2] != PROTO_VER: return
    hdr_id = struct.unpack_from('<H', data, 4)[0]
    c = clients.get(addr)
    hello = None
    o = HDR
    while o + 6 <= len(data):
        t, rel, seq, l = struct.unpack_from('<BBHH', data, o)
        if t == M_HELLO and l >= 6: hello = bytes(data[o + 6:o + 6 + l])
        o += 6 + l
    if c is None and hdr_id:
        # bekannte ID von neuer Adresse (z.B. NAT-Port gewechselt) -> umziehen
        old = next((x for x in clients.values() if x.id == hdr_id), None)
        if old:
            log(f"{old.name()} Adresse geändert: {old.addr[0]}:{old.addr[1]} -> {addr[0]}:{addr[1]}")
            clients.pop(old.addr, None); old.addr = addr; clients[addr] = old; c = old
    if c is None:
        if hello is None:
            if hdr_id:   # Server kennt die ID nicht (Neustart) -> DS soll sich neu anmelden
                send_dgram(b'CR' + bytes([PROTO_VER, 0]) + struct.pack('<HHH', 0, 0, 0) + struct.pack('<BBHHH', M_RESET, 0, 0, 2, hdr_id), addr)
            return
        c = Client(next_cid, addr, hello[:6]); next_cid += 1
        clients[addr] = c
        log(f"Neuer Spieler {c.name()} von {addr[0]}:{addr[1]}")
    if hello is not None:
        nonce = struct.unpack_from('<H', hello, 8)[0] if len(hello) >= 10 else 0
        if c.nonce is not None and nonce != c.nonce:
            log(f"{c.name()} meldet sich neu an (Verbindung war unterbrochen)")
            reset_session(c)
        c.nonce = nonce
    c.last = time.time()
    ack, sack = struct.unpack_from('<HH', data, 6)
    for seq in list(c.unacked):
        dd = (seq - ack) & 0xFFFF
        if dd == 0 or dd & 0x8000: c.unacked.pop(seq)
        elif 2 <= dd < 18 and (sack >> (dd - 2)) & 1: c.unacked[seq][3] = True
    o = HDR
    while o + 6 <= len(data):
        t, rel, seq, l = struct.unpack_from('<BBHH', data, o)
        d = data[o + 6:o + 6 + l]
        if len(d) < l: break
        if t == M_HELLO:
            c.send_unrel(M_WELCOME, struct.pack('<H', c.id))
        elif rel:
            c.need_ack = True
            dd = (seq - c.rx_expect) & 0xFFFF
            if dd == 0:
                c.rx_expect = (c.rx_expect + 1) & 0xFFFF or 1
                handle(c, t, d)
                while c.rx_expect in c.ooo:          # zwischengespeicherte Nachfolger
                    t2, d2 = c.ooo.pop(c.rx_expect)
                    c.rx_expect = (c.rx_expect + 1) & 0xFFFF or 1
                    handle(c, t2, d2)
            elif dd < 0x8000 and dd <= 16:
                c.ooo.setdefault(seq, (t, bytes(d)))
        else:
            handle(c, t, d, seq)
        o += 6 + l
    flush(c)

log(f"Cars Race-O-Rama Online Server lauscht auf UDP-Port {PORT}  (Strg+C beendet)")
log(time.strftime("Sitzung gestartet %d.%m.%Y") + f", Log-Datei: {LOGPATH}")
log(f"Servername: {SERVER_NAME}  (Mod {MOD_VER})")
def tailscale_exe():
    for c in (shutil.which("tailscale"), r"C:\Program Files\Tailscale\tailscale.exe", "/Applications/Tailscale.app/Contents/MacOS/Tailscale"):
        if c and os.path.exists(c): return c
    return None
try:
    _ts = tailscale_exe()
    _ip = subprocess.run([_ts, "ip", "-4"], capture_output=True, text=True, timeout=5).stdout.split() if _ts else []
    if _ip: log(f"Tailscale-IP dieses PCs: {_ip[0]}  -> diese IP den Mitspielern geben (oder sie nutzen Server_suchen.bat)")
    else: log("Tailscale nicht gefunden/nicht angemeldet - nur lokale Spieler bzw. Portfreigabe möglich")
except Exception:
    log("Tailscale-Abfrage fehlgeschlagen")
if SIM: log(f"SIMULATION aktiv: +{ARGS.lag:.0f} ms Ping, +-{ARGS.jitter:.0f} ms Schwankung, {ARGS.loss:.1f} % Verlust je Richtung")
last_status = time.time()
while True:
    r, _, _ = select.select([sock], [], [], 0.002)
    if r:
        try:
            data, addr = sock.recvfrom(2048)
            recv_dgram(data, addr)
        except ConnectionResetError:
            pass
    sim_run()
    now = time.time()
    race_tick(now)
    for addr, c in list(clients.items()):
        if now - c.last > TIMEOUT:
            leave_room(c, "(Zeitüberschreitung)"); clients.pop(addr); log(f"{c.name()} getrennt (Zeitüberschreitung)")
            continue
        flush(c)
    if now - last_status > 30 and rooms:
        last_status = now
        for r in rooms.values():
            log(f"Raum {r.id}: " + ", ".join(f"aid{a}={m.name()} Ping {m.rtt * 1000:.0f} ms DS {m.stats['ds_in']} Port {m.stats['port_in']}" for a, m in r.members.items()))
