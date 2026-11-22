// Cars Race-O-Rama Online - Virtuelle WLAN-Schicht (VWM)
// Ersetzt die Nintendo-WM-API (lokaler DS-Funk) durch einen Server über UDP.
// Das Spiel glaubt weiterhin, per Multi-Card-Funk verbunden zu sein.
#include "game.h"

// ---------------- Protokoll ----------------
enum {
    M_HELLO = 1, M_WELCOME = 2, M_PING = 3, M_PONG = 4, M_RESET = 5,
    M_HOST_OPEN = 16, M_HOST_UPDATE = 17, M_HOST_CLOSE = 18, M_LIST_REQ = 19, M_LIST = 20,
    M_JOIN_REQ = 21, M_JOIN_RES = 22, M_PEER_JOIN = 23, M_PEER_LEFT = 24, M_LEAVE = 25, M_PORT = 26, M_PORT_U = 27,
    M_DS = 30
};
#define PROTO_VER 2
#define HDR 10
#define UNREL_PORTS (1u << 5)   // Port 5 = Lobby-Status, jeden Frame neu -> unzuverlässig, nur neuester zählt
#define DGRAM_MAX 640
#define REL_N 48
#define REL_DATA 520
#define OOO_N 16

struct vdbg {
    char magic[8];         // "CRNETVWM"
    u32 version, role, my_id, my_aid, conn_bm, rooms_n, welcomed;
    u32 dg_tx, dg_rx, rel_tx, rel_resend, rel_rx, rel_dup, rel_drop, relq_full;
    u32 port_tx, port_rx, ds_tx, ds_rx, ds_ok, ds_nodata, last_rtt;
    u32 init_cb, init_fail, join_res, last_api, unknown_msg;
    u16 ds_len, ds_bm;
    u32 ds_wait, ds_rebase, lost, net_restart, ds_D, start_hold, sync_fix, ds_pre, ds_grow, ds_repair, ds_repaired;
    u32 clk_hold, clk_giveup, clk_ahead;   // Netz-Uhr: angehaltene Frames, Abbrüche, letzter Vorsprung
    u32 unrel_drop, rel_defer, pu_drop;     // verworfene unzuverl. Records, aufgeschobene zuverl. Port-Nachrichten
};
__attribute__((section(".dbg2"), used)) struct vdbg g_v = { {'C','R','N','E','T','V','W','M'}, 1 };

struct relmsg { u8 used, type, sacked, pad; u16 seq, len; u32 last; u8 data[REL_DATA]; };
static struct relmsg relq[REL_N];
static struct relmsg ooo[OOO_N];          // zu früh angekommene zuverlässige Nachrichten
static u16 pu_rx_seq[16][4]; static u8 pu_rx_have[16]; static u16 pu_tx_seq[16];
static u16 tx_seq = 1, rx_expect = 1;
static u8 need_ack, hello_due;
static u32 last_rx;
static u16 session_nonce = 1;   // neue Sitzung nach Verbindungsverlust
static u8 dg[DGRAM_MAX];
static u8 unrel[DGRAM_MAX - HDR]; static u32 unrel_len;   // ausstehende unzuverlässige Records (DS, Ping) - passt immer in 1 Datagramm
static void flush(int force);

static int rel_send(u8 type, const u8 *data, u32 len) {
    if (len > REL_DATA) return 0;
    for (int i = 0; i < REL_N; i++) if (!relq[i].used) {
        struct relmsg *m = &relq[i];
        m->used = 1; m->type = type; m->sacked = 0; m->seq = tx_seq++; m->len = (u16)len; m->last = 0;
        mcpy(m->data, data, len);
        return 1;
    }
    g_v.relq_full++;
    return 0;
}
static int unrel_add_seq(u8 type, const u8 *data, u32 len, u16 seq);
// Netz-Uhr (Sync-Zähler [mgr+0xA8]): alle Konsolen tauschen ihren Zähler aus. Wer dem langsamsten
// Mitspieler voraus ist, hält seinen Zähler an (Werte werden nie übersprungen, nur wiederholt).
// So holt ein Emulator-Hänger (Shader laden usw.) nach dem Sync keinen Vorsprung mehr heraus,
// die anderen warten einfach mit, bis er wieder gleichauf ist.
#define CLK_PORT 15
#define CLK_DEAD 4        // Toleranz in Frames (kleiner: Netzschwankungen lassen alle ständig anhalten)
#define CLK_EXTRA 6       // so viele Frames wird der Stand eines Mitspielers ohne neue Nachricht hochgerechnet
#define CLK_MAXHOLD 300   // höchstens 5 s am Stück anhalten (Mitspieler hängt endgültig -> aufgeben)
static u32 clk_c[4], clk_t[4]; static u8 clk_ok[4], clk_synced; static u32 clk_run, clk_tick; static u8 clk_gaveup;
static void clk_reset(void) { for (int i = 0; i < 4; i++) clk_ok[i] = 0; clk_synced = 0; clk_run = 0; clk_gaveup = 0; }
static int unrel_add_seq(u8 type, const u8 *data, u32 len, u16 seq) {
    // Kein Platz mehr (z.B. großes DS-Paket mit Nachlieferung + Netz-Uhr + Port-5-Daten): erst Bisheriges
    // absenden statt den neuen Record still zu verwerfen. Früher ging so bei 4 Spielern das DS-Paket verloren.
    if (unrel_len && unrel_len + 6 + len > sizeof unrel) flush(0);
    if (unrel_len + 6 + len > sizeof unrel) { g_v.unrel_drop++; return 0; }
    u8 *r = unrel + unrel_len;
    r[0] = type; r[1] = 0; wr16(r + 2, seq); wr16(r + 4, (u16)len); mcpy(r + 6, data, len);
    unrel_len += 6 + len;
    return 1;
}
static void unrel_add(u8 type, const u8 *data, u32 len) { unrel_add_seq(type, data, len, 0); }
// Datagramm bauen und senden: Kopf + unzuverlässige Records + fällige zuverlässige Records
static void flush(int force) {
    if (net_status() != NET_UP) return;
    u32 now = net_frame();
    u32 n = HDR;
    dg[0] = 'C'; dg[1] = 'R'; dg[2] = PROTO_VER; dg[3] = 0;
    wr16(dg + 4, (u16)g_v.my_id); wr16(dg + 6, (u16)(rx_expect - 1));
    u16 sack = 0;   // Bit i: Nachricht (ack + 2 + i) liegt schon im Zwischenspeicher
    for (int i = 0; i < OOO_N; i++) if (ooo[i].used) { u16 k = (u16)(ooo[i].seq - rx_expect - 1); if (k < 16) sack |= 1u << k; }
    wr16(dg + 8, sack);
    u32 rto = g_v.last_rtt * 3 / 2 + 4; if (rto < 6) rto = 6;
    int payload = 0;
    if (unrel_len && n + unrel_len <= DGRAM_MAX) { mcpy(dg + n, unrel, unrel_len); n += unrel_len; payload = 1; }
    unrel_len = 0;
    // zuverlässige: in Sequenz-Reihenfolge, neu oder nach Ablauf der Wartezeit (abhängig vom Ping) unbestätigt
    for (;;) {
        struct relmsg *best = 0;
        for (int i = 0; i < REL_N; i++) {
            struct relmsg *m = &relq[i];
            if (!m->used || m->sacked) continue;
            if (m->last && now - m->last < rto) continue;
            if (!best || (s16)(m->seq - best->seq) < 0) best = m;
        }
        if (!best || n + 6 + best->len > DGRAM_MAX) break;
        u8 *r = dg + n;
        r[0] = best->type; r[1] = 1; wr16(r + 2, best->seq); wr16(r + 4, best->len);
        mcpy(r + 6, best->data, best->len);
        n += 6 + best->len;
        if (best->last) g_v.rel_resend++; else g_v.rel_tx++;
        best->last = now ? now : 1;
        payload = 1;
    }
    if (payload || need_ack || force) {
        if (net_udp_send(dg, n)) { g_v.dg_tx++; need_ack = 0; }
    }
}

// ---------------- Verzögerte Callbacks an das Spiel ----------------
#define PQ_N 24
struct pend { WMCallback cb; u32 due; u8 buf[72]; };
static struct pend pq[PQ_N]; static u32 pq_w, pq_r;
static u8 *qcb(WMCallback cb, u16 api, u32 delay) {
    if (!cb || pq_w - pq_r >= PQ_N) return 0;
    struct pend *p = &pq[pq_w % PQ_N];
    p->cb = cb; p->due = net_frame() + delay; mset(p->buf, 0, sizeof p->buf);
    wr16(p->buf, api);
    pq_w++;
    return p->buf;
}
// Einzelner, separat verzögerter Callback (Start-Nachricht), blockiert die normale Warteschlange nicht
static struct pend hold_p; static u8 hold_used;
static u8 *hold_cb(WMCallback cb, u16 api, u32 delay) {
    if (!cb) return 0;
    if (hold_used) return qcb(cb, api, 0);
    hold_used = 1; hold_p.cb = cb; hold_p.due = net_frame() + delay; mset(hold_p.buf, 0, sizeof hold_p.buf);
    wr16(hold_p.buf, api);
    return hold_p.buf;
}
static void pq_run(void) {
    if (hold_used && (s32)(net_frame() - hold_p.due) >= 0) {
        static u8 tmp2[72] __attribute__((aligned(4)));
        mcpy(tmp2, hold_p.buf, sizeof tmp2); hold_used = 0; hold_p.cb(tmp2);
    }
    u32 now = net_frame();
    while (pq_r != pq_w) {
        struct pend *p = &pq[pq_r % PQ_N];
        if ((s32)(now - p->due) < 0) break;
        static u8 tmp[72] __attribute__((aligned(4)));
        WMCallback cb = p->cb; mcpy(tmp, p->buf, sizeof tmp);
        pq_r++;
        cb(tmp);
    }
}

// ---------------- Zustand ----------------
enum { R_NONE = 0, R_HOST = 1, R_CLIENT = 2 };
static u8 my_mac[6];
static WMCallback init_cb, parent_cb, connect_cb, mp_cb;
static u32 init_since;
static WMCallback port_cb[16]; static void *port_arg[16];
static u8 peer_mac[4][6];
static u8 mp_started;

// Host-Parameter (für den Raum auf dem Server)
static u32 h_ggid; static u16 h_tgid, h_pmax = 0x200, h_cmax = 0x22; static u8 h_entry, h_maxent = 3, h_attr, h_chan = 1;
static u8 h_ug[112]; static u8 h_uglen;

// Raumliste (Client)
struct room { u16 id; u8 mac[6]; u32 ggid; u16 tgid; u8 attr, uglen, chan, players; u16 pmax, cmax; u8 ug[112]; };
static struct room rooms[4]; static u32 rooms_n, rr_idx, list_req_at;
static u16 join_room;

// Port-Empfang (Server -> Spiel)
#define PR_N 24          // Port-Nachrichten für das Spiel; die letzten 8 Plätze nur für zuverlässige
struct portrx { u8 port, aid; u16 len; u8 data[520]; };
static struct portrx prx[PR_N]; static u32 prx_w, prx_r;

// Data Sharing
// Symmetrischer, verzögerter Lockstep: In Schritt N sehen ALLE Konsolen die Blöcke aller Spieler
// aus Schritt N - D (auch den eigenen). D = höchster Ping in der Runde + 3 Frames.
#define DSH 64            // Verlauf in Schritten (Potenz von 2)
#define DS_REDUN 4
#define DS_REPAIR 8   // Nachlieferung: bis zu 8 ältere Blöcke, die der langsamste Mitspieler noch braucht        // Blöcke pro Paket (Redundanz gegen Paketverlust)
static u8 ds_active; static u16 ds_len, ds_bm, ds_seq, ds_D;
static u8 ds_hist[4][DSH][40]; static u16 ds_hseq[4][DSH]; static u8 ds_hok[4][DSH];
static u8 ds_last[4][40]; static u8 ds_have;      // neuester Block je Spieler (für übersprungene Spieler)
static u16 ds_peer_seq[4]; static u8 ds_peer_rtt[4]; static s16 ds_off[4]; static u8 ds_skip[4]; static u32 ds_waitcnt;
static u32 ds_hold; static u16 ds_miss, ds_win;   // Host nach Start-Nachricht kurz anhalten (Laufzeit zum Client ausgleichen)
static void ds_store(u32 aid, u16 s, const u8 *blk) {
    u32 i = s & (DSH - 1); mcpy(ds_hist[aid][i], blk, ds_len); ds_hseq[aid][i] = s; ds_hok[aid][i] = 1;
}
// Vorpuffer: Blöcke des NÄCHSTEN Rennens, die ankommen, bevor diese Konsole StartDataSharing aufgerufen hat
#define PREH 48   // wartende Konsole sendet höchstens Schritt D (<= 40) + Redundanz
static u8 ds_pre[4][PREH][40]; static u16 ds_pre_seq[4][PREH]; static u8 ds_pre_ok[4][PREH]; static u8 ds_pre_rtt[4];
static void ds_pre_clear(void) { mset(ds_pre_ok, 0, sizeof ds_pre_ok); }
static const u8 *ds_get(u32 aid, u16 s) {
    u32 i = s & (DSH - 1); return (ds_hok[aid][i] && ds_hseq[aid][i] == s) ? ds_hist[aid][i] : 0;
}

static void port_event(u16 state, u8 aid) {     // state 7 = verbunden, 9 = getrennt
    for (int p = 0; p < 16; p++) {
        if (!port_cb[p]) continue;
        static u8 b[72] __attribute__((aligned(4)));
        mset(b, 0, sizeof b);
        wr16(b + 0, 0x82); wr16(b + 4, state); wr16(b + 6, (u16)p);
        wr16(b + 18, aid); mcpy(b + 20, peer_mac[aid & 3], 6); wr16(b + 26, 0xFFFF);
        *(void **)(b + 28) = port_arg[p];
        wr16(b + 32, (u16)g_v.my_aid); wr16(b + 34, (u16)g_v.conn_bm);
        port_cb[p](b);
    }
}

static void leave(void) {
    if (g_v.role == R_HOST) rel_send(M_HOST_CLOSE, 0, 0);
    else if (g_v.role == R_CLIENT || join_room) rel_send(M_LEAVE, 0, 0);
    g_v.role = R_NONE; g_v.conn_bm = 0; g_v.my_aid = 0; join_room = 0;
    parent_cb = connect_cb = mp_cb = 0; mp_started = 0; ds_active = 0; ds_pre_clear(); clk_reset();
    for (int p = 0; p < 16; p++) { port_cb[p] = 0; port_arg[p] = 0; }
}

static void host_send(u8 type) {
    u8 b[140]; u32 n = 0;
    wr32(b, h_ggid); wr16(b + 4, h_tgid); b[6] = h_entry; b[7] = h_maxent; b[8] = h_attr; b[9] = h_uglen;
    b[10] = h_chan; b[11] = 0; wr16(b + 12, h_pmax); wr16(b + 14, h_cmax);
    mcpy(b + 16, h_ug, h_uglen); n = 16 + h_uglen;
    rel_send(type, b, n);
}

// Verbindung zum Server verloren (Timeout, Server-Neustart, WLAN weg):
// dem Spiel alle Mitspieler als getrennt melden und Protokollzustand für Neuanmeldung zurücksetzen.
static void connection_lost(void) {
    g_v.lost++;
    if (g_v.role == R_HOST) {
        for (u32 aid = 1; aid < 4; aid++) {
            if (!(g_v.conn_bm & (1u << aid))) continue;
            g_v.conn_bm &= ~(1u << aid);
            u8 *b = qcb(parent_cb, 8, 0);
            if (b) { wr16(b + 8, 9); mcpy(b + 10, peer_mac[aid], 6); wr16(b + 16, aid); wr16(b + 18, 1); }
            port_event(9, aid);
        }
    } else if (g_v.role == R_CLIENT && (g_v.conn_bm & 1)) {
        g_v.conn_bm = 0;
        u8 *b = qcb(connect_cb, 12, 0);
        if (b) { wr16(b + 8, 9); wr16(b + 10, (u16)g_v.my_aid); }
        port_event(9, 0);
    } else if (join_room) {
        u8 *b = qcb(connect_cb, 12, 0); if (b) { wr16(b + 2, 1); wr16(b + 8, 6); }
        join_room = 0;
    }
    ds_have = 0; ds_pre_clear(); clk_reset();
    g_v.welcomed = 0; g_v.my_id = 0; hello_due = 0; session_nonce++;
    tx_seq = 1; rx_expect = 1; need_ack = 0; unrel_len = 0;
    for (int i = 0; i < REL_N; i++) relq[i].used = 0;
    for (int i = 0; i < OOO_N; i++) ooo[i].used = 0;
    for (int i = 0; i < 16; i++) { pu_rx_have[i] = 0; pu_tx_seq[i] = 0; }
    rooms_n = 0; g_v.rooms_n = 0;
}

// ---------------- Empfang vom Server ----------------
// Zuverlässige Nachricht jetzt annehmen? Port-Nachrichten nur, wenn die Warteschlange zum Spiel Platz hat.
static int rx_ok(u8 type) { return type != M_PORT || prx_w - prx_r < PR_N; }
static void handle(u8 type, const u8 *d, u32 len, u16 rseq) {
    switch (type) {
    case M_RESET:      // Server kennt uns nicht (Neustart): Verbindung als verloren behandeln
        // nur wenn es die aktuelle Sitzung betrifft (verspätete RESETs für alte Pakete ignorieren)
        if (g_v.welcomed && len >= 2 && rd16(d) == (u16)g_v.my_id) connection_lost();
        break;
    case M_WELCOME:
        if (len >= 2) { g_v.my_id = rd16(d); g_v.welcomed = 1; last_rx = net_frame(); }
        break;
    case M_PONG:
        if (len >= 4) { u32 r = net_frame() - rd32(d); if (r < 600) g_v.last_rtt = r; }
        break;
    case M_LIST: {
        u32 n = len ? d[0] : 0, o = 1; rooms_n = 0;
        for (u32 i = 0; i < n && rooms_n < 4; i++) {
            if (o + 24 > len) break;
            struct room *r = &rooms[rooms_n];
            r->id = rd16(d + o); mcpy(r->mac, d + o + 2, 6); r->ggid = rd32(d + o + 8); r->tgid = rd16(d + o + 12);
            r->attr = d[o + 14]; r->uglen = d[o + 15]; r->chan = d[o + 16]; r->players = d[o + 17];
            r->pmax = rd16(d + o + 18); r->cmax = rd16(d + o + 20);
            if (r->uglen > 112 || o + 24 + r->uglen > len) break;
            mcpy(r->ug, d + o + 24, r->uglen);
            o += 24 + r->uglen; rooms_n++;
        }
        g_v.rooms_n = rooms_n;
        break;
    }
    case M_JOIN_RES: {
        u8 res = d[0], aid = d[1];
        g_v.join_res = res;
        u8 *b = qcb(connect_cb, 12, 0);
        if (res == 0) {
            g_v.role = R_CLIENT; g_v.my_aid = aid; g_v.conn_bm = 1 | (1u << aid); ds_pre_clear(); clk_reset();
            mcpy(peer_mac[0], d + 2, 6); mcpy(peer_mac[aid & 3], my_mac, 6);
            if (b) { wr16(b + 8, 7); wr16(b + 10, aid); mcpy(b + 12, d + 2, 6); wr16(b + 18, 0x200); wr16(b + 20, 0x22); }
        } else {
            join_room = 0;
            if (b) { wr16(b + 2, res == 1 ? 11 : (res == 2 ? 12 : 1)); wr16(b + 8, 6); }
        }
        break;
    }
    case M_PEER_JOIN: {
        u8 aid = d[0] & 3;
        mcpy(peer_mac[aid], d + 1, 6);
        g_v.conn_bm |= 1u << aid;
        if (g_v.role != R_HOST) break;   // Client: anderen Client nur für Data Sharing merken (wie echtes WM)
        u8 *b = qcb(parent_cb, 8, 0);
        if (b) { wr16(b + 8, 7); mcpy(b + 10, d + 1, 6); wr16(b + 16, aid); mcpy(b + 20, d + 7, 24); wr16(b + 44, h_pmax); wr16(b + 46, h_cmax); }
        port_event(7, aid);
        break;
    }
    case M_PEER_LEFT: {
        u8 aid = d[0] & 3;
        if (!(g_v.conn_bm & (1u << aid))) break;
        g_v.conn_bm &= ~(1u << aid); ds_have &= ~(1u << aid);
        if (g_v.role == R_HOST) {
            u8 *b = qcb(parent_cb, 8, 0);
            if (b) { wr16(b + 8, 9); mcpy(b + 10, peer_mac[aid], 6); wr16(b + 16, aid); wr16(b + 18, 1); }
            port_event(9, aid);
        } else if (aid == 0) {
            u8 *b = qcb(connect_cb, 12, 0);
            if (b) { wr16(b + 8, 9); wr16(b + 10, (u16)g_v.my_aid); }
            port_event(9, 0);
        }
        break;
    }
    case M_PORT_U: {   // unzuverlässig: nur neuere Nachrichten je (Port, Absender) annehmen
        if (len < 6) break;
        u8 pt = d[0] & 15, a = d[1] & 3;
        if ((pu_rx_have[pt] & (1u << a)) && (s16)(rseq - pu_rx_seq[pt][a]) <= 0) break;
        pu_rx_have[pt] |= 1u << a; pu_rx_seq[pt][a] = rseq;
        if (pt == CLK_PORT) {   // Netz-Uhr eines Mitspielers: [u32 Zähler][synced] - nicht ans Spiel
            if (len >= 11) {
                u32 now = net_frame(), s = rd32(d + 6) + (g_v.last_rtt + d[4]) / 2 + 1;   // + Laufzeit = sein Stand jetzt
                u32 age = now - clk_t[a]; if (age > CLK_EXTRA) age = CLK_EXTRA;
                // Verspätete Pakete (Schwankung im Netz) liefern einen zu kleinen Stand -> ignorieren, solange die
                // Hochrechnung des letzten guten Werts noch gilt. Sonst hält jeder ständig an (Test: ~45 % der Frames).
                if (!clk_ok[a] || !d[10] || (s32)(s - (clk_c[a] + age)) >= 0 || now - clk_t[a] > CLK_EXTRA) {
                    clk_c[a] = s; clk_t[a] = now;
                }
                clk_ok[a] = d[10] ? 1 : 0;
            }
            break;
        }
    }   /* fall through */
    case M_PORT: {
        if (len < 6) break;
        if (type == M_PORT_U && prx_w - prx_r >= PR_N - 8) { g_v.pu_drop++; break; }   // Platz für zuverlässige lassen
        if (prx_w - prx_r >= PR_N) { g_v.rel_drop++; break; }   // (zuverlässige werden vorher zurückgehalten, s. rx_ok)
        struct portrx *p = &prx[prx_w % PR_N];
        p->port = d[0]; p->aid = d[1]; p->len = (u16)(len - 6);
        if (p->len > sizeof p->data) break;
        mcpy(p->data, d + 6, p->len);
        // Sync-Zähler des Spiels (Port 4, Typ 0x05, u32 ab Byte 1): Der Host zählt jeden Frame hoch,
        // der Client übernimmt den Wert. Netzlaufzeit in Frames dazurechnen, sonst läuft der Client
        // um die Laufzeit hinterher (z.B. späterer Rennstart). Byte 4 vom Server = Ping des Absenders.
        if ((p->port & 15) == 4 && p->len >= 5 && p->data[0] == 0x05) {
            u32 oneway = (g_v.last_rtt + d[4]) / 2 + 1;
            wr32(p->data + 1, rd32(p->data + 1) + oneway);
            g_v.sync_fix = oneway; clk_synced = 1;
        }
        prx_w++; g_v.port_rx++;
        break;
    }
    case M_DS: {   // [aid][ping][seq u16][anzahl][0][Block seq][Block seq-1]...
        if (len < 6) break;
        u8 aid = d[0] & 3; u16 seq = rd16(d + 2); u32 n = d[4];
        u32 rn = d[5];
        if (aid == (g_v.my_aid & 3) || n == 0 || n > DS_REDUN || rn > DS_REPAIR) break;
        if (!ds_active || (ds_seq >= 2 * DSH && ds_seq < 0xFFFF - 2 * DSH && seq < PREH)) {
            // Rennen N+1 hat beim Absender schon begonnen, hier noch nicht: zwischenspeichern statt verwerfen
            u32 bl = 0, hb = rn ? 8 : 6; while (bl < 40 && (bl + 1) * (n + rn) <= len - hb) bl++;   // Blocklänge ohne Division
            if (seq >= PREH + DS_REDUN) break;      // Nachzügler vom alten Rennen
            for (u32 j = 0; j < n; j++) {
                u16 s2 = (u16)(seq - j); if (s2 >= PREH) continue;
                mcpy(ds_pre[aid][s2], d + 6 + j * bl, bl); ds_pre_seq[aid][s2] = s2; ds_pre_ok[aid][s2] = 1;
            }
            ds_pre_rtt[aid] = d[1]; g_v.ds_pre++;
            break;
        }
        if (6 + n * ds_len + (rn ? 2 + rn * ds_len : 0) > len) break;
        if (rn) {   // nachgelieferte ältere Blöcke
            const u8 *o = d + 6 + n * ds_len; u16 rs = rd16(o); o += 2;
            for (u32 j = 0; j < rn; j++) {
                u16 s2 = (u16)(rs + j);
                if (!ds_get(aid, s2)) { ds_store(aid, s2, o + j * ds_len); g_v.ds_repaired++; }
            }
        }
        ds_peer_rtt[aid] = d[1];
        int newer = !(ds_have & (1u << aid)) || (s16)(seq - ds_peer_seq[aid]) > 0;
        if (ds_skip[aid] && newer) {      // übersprungener Spieler ist zurück: auf aktuellen Stand ausrichten
            ds_off[aid] = (s16)((s16)(ds_seq - ds_D) - (s16)seq); ds_skip[aid] = 0;
        }
        for (u32 j = 0; j < n; j++) ds_store(aid, (u16)(seq - j), d + 6 + j * ds_len);
        if (newer) { mcpy(ds_last[aid], d + 6, ds_len); ds_peer_seq[aid] = seq; ds_have |= 1u << aid; }
        g_v.ds_rx++;
        break;
    }
    default: g_v.unknown_msg++;
    }
}

void vwm_on_udp(const u8 *data, u32 len) {
    if (len < HDR || data[0] != 'C' || data[1] != 'R' || data[2] != PROTO_VER) return;
    g_v.dg_rx++; last_rx = net_frame();
    u16 ack = rd16(data + 6), sack = rd16(data + 8);
    for (int i = 0; i < REL_N; i++) {
        struct relmsg *m = &relq[i];
        if (!m->used) continue;
        s16 d = (s16)(m->seq - ack);
        if (d <= 0) m->used = 0;
        else if (d >= 2 && d < 18 && (sack & (1u << (d - 2)))) m->sacked = 1;
    }
    u32 o = HDR;
    while (o + 6 <= len) {
        u8 type = data[o], rel = data[o + 1]; u16 seq = rd16(data + o + 2), l = rd16(data + o + 4);
        if (o + 6 + l > len) break;
        const u8 *pl = data + o + 6;
        if (rel) {
            need_ack = 1;
            s16 d = (s16)(seq - rx_expect);
            if (d == 0 && !rx_ok(type)) {
                // Port-Warteschlange voll: NICHT annehmen (kein rx_expect++). Der Server schickt die Nachricht
                // erneut. Früher wurde sie bestätigt und verworfen -> Spielnachricht fehlte für immer
                // ("Warten auf andere Spieler" endlos, Positionen eingefroren - v.a. bei 4 Spielern).
                g_v.rel_defer++;
            } else if (d == 0) {
                rx_expect++; g_v.rel_rx++; handle(type, pl, l, seq);
                // zwischengespeicherte Nachfolger ausliefern
                for (int again = 1; again; ) {
                    again = 0;
                    for (int i = 0; i < OOO_N; i++) if (ooo[i].used && ooo[i].seq == rx_expect && rx_ok(ooo[i].type)) {
                        ooo[i].used = 0; rx_expect++; g_v.rel_rx++;
                        handle(ooo[i].type, ooo[i].data, ooo[i].len, ooo[i].seq); again = 1;
                    }
                }
            } else if (d < 0) g_v.rel_dup++;
            else if (d <= 16 && l <= REL_DATA) {
                int dup = 0, fr = -1;
                for (int i = 0; i < OOO_N; i++) { if (ooo[i].used && ooo[i].seq == seq) dup = 1; if (!ooo[i].used && fr < 0) fr = i; }
                if (!dup && fr >= 0) { struct relmsg *m = &ooo[fr]; m->used = 1; m->type = type; m->seq = seq; m->len = l; mcpy(m->data, pl, l); }
                else if (!dup) g_v.rel_drop++;
            } else g_v.rel_drop++;
        } else handle(type, pl, l, seq);
        o += 6 + l;
    }
    // veraltete Zwischenspeicher-Einträge freigeben (Nachricht kam inzwischen in Reihenfolge an)
    for (int i = 0; i < OOO_N; i++) if (ooo[i].used && (s16)(ooo[i].seq - rx_expect) < 0) ooo[i].used = 0;
}

// ---------------- Pro Frame ----------------
static u32 net_retry_at;
void vwm_tick(void) {
    int st = net_status();
    u32 now = net_frame();
    // Server antwortet 8 s nicht mehr -> getrennt
    if (g_v.welcomed && now - last_rx > 480) connection_lost();
    // WLAN-Verbindung verloren -> melden und alle 2 s neu versuchen
    if (st == NET_FAIL && g_v.welcomed) connection_lost();
    if (st == NET_FAIL && !init_cb && (g_v.role != R_NONE || mp_started)) {
        if (!net_retry_at) net_retry_at = now + 120;
        else if ((s32)(now - net_retry_at) >= 0) { net_retry_at = 0; g_v.net_restart++; net_start(); }
    }
    if (st == NET_UP) {
        if (!g_v.welcomed && (hello_due++ % 30) == 0) {
            u8 h[10]; mcpy(h, my_mac, 6); h[6] = PROTO_VER; h[7] = 0; wr16(h + 8, session_nonce); unrel_add(M_HELLO, h, 10);
        }
        if (g_v.welcomed && (now % 15) == 0) { u8 p[5]; wr32(p, now); p[4] = (u8)(g_v.last_rtt > 255 ? 255 : g_v.last_rtt); unrel_add(M_PING, p, 5); }
    }
    // ausstehendes WM_Initialize beantworten
    if (init_cb) {
        if (g_v.welcomed) { u8 *b = qcb(init_cb, 0, 0); (void)b; init_cb = 0; g_v.init_cb++; }
        else if (st == NET_FAIL || now - init_since > 900) {
            u8 *b = qcb(init_cb, 0, 0); if (b) wr16(b + 2, 1); init_cb = 0; g_v.init_fail++;
        }
    }
    pq_run();
    // Port-Daten ans Spiel
    while (prx_r != prx_w) {
        struct portrx *p = &prx[prx_r % PR_N];
        u8 port = p->port & 15;
        if (port_cb[port]) {
            static u8 b[72] __attribute__((aligned(4)));
            mset(b, 0, sizeof b);
            wr16(b + 0, 0x82); wr16(b + 4, 21); wr16(b + 6, port);
            *(u8 **)(b + 8) = p->data; *(u8 **)(b + 12) = p->data;
            wr16(b + 16, p->len); wr16(b + 18, p->aid); mcpy(b + 20, peer_mac[p->aid & 3], 6);
            *(void **)(b + 28) = port_arg[port];
            wr16(b + 32, (u16)g_v.my_aid); wr16(b + 34, (u16)g_v.conn_bm);
            port_cb[port](b);
        }
        prx_r++;
    }
    flush(0);
}

// ---------------- Virtuelle WM-API (ersetzt die Originalfunktionen) ----------------
#define OPERATING 2
s32 vwm_hook_020A0A94(void *sysbuf, WMCallback cb, u16 dma) {            // WM_Initialize
    (void)sysbuf; (void)dma; g_v.last_api = 0;
    G_OS_GETMAC(my_mac);
    if (g_v.welcomed && net_status() == NET_UP) { qcb(cb, 0, 1); return OPERATING; }
    init_cb = cb; init_since = net_frame();
    net_start();
    return OPERATING;
}
s32 vwm_hook_020A0B04(WMCallback cb) { leave(); qcb(cb, 1, 1); return OPERATING; }   // WM_Reset
s32 vwm_hook_020A0B3C(WMCallback cb) { leave(); qcb(cb, 2, 1); return OPERATING; }   // WM_End
s32 vwm_hook_020A2198(WMCallback cb) { qcb(cb, 29, 1); return OPERATING; }           // WM_SetLifeTime
s32 vwm_hook_020A21F8(WMCallback cb, u16 cca, u16 ed, u16 ch) {                   // WM_MeasureChannel
    (void)cca; (void)ed;
    u8 *b = qcb(cb, 30, 2); if (b) { wr16(b + 8, ch); wr16(b + 10, ch == 1 ? 0 : 10); }
    return OPERATING;
}
s32 vwm_hook_020A0B7C(WMCallback cb, const u8 *pp) {                              // WM_SetParentParameter
    const u8 *ug = *(const u8 **)pp; u16 uglen = rd16(pp + 4);
    h_uglen = uglen > 112 ? 112 : (u8)uglen; if (ug) mcpy(h_ug, ug, h_uglen);
    h_ggid = rd32(pp + 8); h_tgid = rd16(pp + 12); h_entry = (u8)rd16(pp + 14); h_maxent = (u8)rd16(pp + 16);
    h_attr = h_entry ? 1 : 0; h_chan = (u8)rd16(pp + 50); h_pmax = rd16(pp + 52); h_cmax = rd16(pp + 54);
    qcb(cb, 7, 1); return OPERATING;
}
s32 vwm_hook_020A0D04(WMCallback cb) {                                            // WM_StartParent
    g_v.role = R_HOST; g_v.my_aid = 0; g_v.conn_bm = 1; ds_pre_clear(); clk_reset(); mcpy(peer_mac[0], my_mac, 6);
    parent_cb = cb;
    host_send(M_HOST_OPEN);
    qcb(cb, 8, 1);   // state 0 = PARENT_START
    return OPERATING;
}
s32 vwm_hook_020A2090(WMCallback cb, const u8 *ug, u16 size, u32 ggid, u16 tgid, u8 attr) { // WM_SetGameInfo
    h_uglen = size > 112 ? 112 : (u8)size; if (ug) mcpy(h_ug, ug, h_uglen);
    h_ggid = ggid; h_tgid = tgid; h_attr = attr; h_entry = attr & 1;
    if (g_v.role == R_HOST) host_send(M_HOST_UPDATE);
    qcb(cb, 24, 1); return OPERATING;
}
s32 vwm_hook_020A2270(WMCallback cb, u16 enabled) {                               // WM_SetEntry
    h_entry = enabled ? 1 : 0; h_attr = (h_attr & ~1) | h_entry;
    if (g_v.role == R_HOST) host_send(M_HOST_UPDATE);
    qcb(cb, 33, 1); return OPERATING;
}
s32 vwm_hook_020A1328(WMCallback cb) { qcb(cb, 35, 1); return OPERATING; }        // MP-Parameter
s32 vwm_hook_020A12E4(WMCallback cb) { qcb(cb, 34, 1); return OPERATING; }        // WM_SetMPFrequency
s32 vwm_hook_020A1208(WMCallback cb) {                                            // WM_StartMP
    mp_cb = cb; mp_started = 1;
    u8 *b = qcb(cb, 14, 1); if (b) wr16(b + 4, 10);   // MP_START
    if (g_v.role == R_CLIENT) port_event(7, 0);       // Parent für alle Ports als verbunden melden
    return OPERATING;
}
s32 vwm_hook_020A1370(WMCallback cb, void *arg, const u8 *data, u16 size, u16 dest, u16 port, u16 prio) { // WM_SetMPDataToPortEx
    (void)prio;
    u16 sent = 0;
    if (g_v.role != R_NONE && size <= 512) {
        u8 b[520];
        b[0] = (u8)port; b[1] = (u8)g_v.my_aid; wr16(b + 2, dest); wr16(b + 4, size); mcpy(b + 6, data, size);
        if (((UNREL_PORTS >> (port & 15)) & 1) && unrel_add_seq(M_PORT_U, b, 6 + size, ++pu_tx_seq[port & 15])) { sent = dest; g_v.port_tx++; }
        else if (rel_send(M_PORT, b, 6 + size)) { sent = dest; g_v.port_tx++; }
    }
    u32 cdelay = 0;
    if (0 && g_v.role == R_HOST && port == 13 && size >= 1 && data[0] == 0x0C) {   // (R4, ersetzt durch Zähler-Korrektur)
        // Rennstart: der Host reagiert sofort, die Clients erst nach der Netzlaufzeit -> Host so lange anhalten
        u32 mx = 0;
        for (u32 a = 1; a < 4; a++) if ((g_v.conn_bm & (1u << a)) && ds_peer_rtt[a] > mx) mx = ds_peer_rtt[a];
        ds_hold = (g_v.last_rtt + mx) / 2 + 2; cdelay = ds_hold; g_v.start_hold = ds_hold;
    }
    u8 *c = cdelay ? hold_cb(cb, 15, cdelay) : qcb(cb, 15, 0);
    if (c) {
        wr16(c + 2, sent ? 0 : 1); wr16(c + 10, port); wr16(c + 12, dest); wr16(c + 14, dest & ~sent); wr16(c + 16, sent);
        *(const u8 **)(c + 20) = data; *(void **)(c + 32) = arg;
    }
    return OPERATING;
}
s32 vwm_hook_020A0514(u16 port, WMCallback cb, void *arg) {                        // WM_SetPortCallback
    port &= 15; port_cb[port] = cb; port_arg[port] = arg;
    if (cb) {
        static u8 b[72] __attribute__((aligned(4)));
        mset(b, 0, sizeof b);
        wr16(b, 0x82); wr16(b + 4, 25); wr16(b + 6, port); mcpy(b + 20, my_mac, 6); wr16(b + 26, 0xFFFF);
        *(void **)(b + 28) = arg; wr16(b + 32, (u16)g_v.my_aid); wr16(b + 34, (u16)g_v.conn_bm);
        cb(b);
    }
    return 0;
}
static void dc_store(void *p, u32 n) {
    u32 a = (u32)p & ~31u, e = (u32)p + n;
    for (; a < e; a += 32) __asm__ volatile("mcr p15,0,%0,c7,c10,1" ::"r"(a));
    __asm__ volatile("mcr p15,0,%0,c7,c10,4" ::"r"(0));
}
s32 vwm_hook_020A0D14(WMCallback cb, const u8 *param) {                           // WM_StartScan
    u8 *buf = *(u8 **)param; u16 ch = rd16(param + 4);
    u32 now = net_frame();
    if (!list_req_at || now - list_req_at > 20) { u8 g[4]; wr32(g, 0); rel_send(M_LIST_REQ, g, 4); list_req_at = now; }
    u8 *b = qcb(cb, 10, 3);
    if (!b) return OPERATING;
    wr16(b + 16, ch);
    if (rooms_n && buf) {
        if (rr_idx >= rooms_n) rr_idx = 0;
        struct room *r = &rooms[rr_idx++];
        u8 *e = buf; mset(e, 0, 0xC0);
        u32 gil = 16 + r->uglen;
        wr16(e + 0, (u16)((64 + gil + 1) / 2)); wr16(e + 2, 0x80); mcpy(e + 4, r->mac, 6);
        wr16(e + 44, 0x0021); wr16(e + 46, 3); wr16(e + 48, 3); wr16(e + 50, 0xD1); wr16(e + 52, 2);
        wr16(e + 54, ch); wr16(e + 60, (u16)gil);
        u8 *gi = e + 64;
        wr16(gi, 1); gi[2] = 1; gi[3] = 0; wr32(gi + 4, r->ggid); wr16(gi + 8, r->tgid);
        gi[10] = r->uglen; gi[11] = r->attr; wr16(gi + 12, r->pmax); wr16(gi + 14, r->cmax);
        mcpy(gi + 16, r->ug, r->uglen);
        dc_store(e, 0xC0);
        wr16(b + 8, 5); mcpy(b + 10, r->mac, 6); wr16(b + 18, 3);
    } else wr16(b + 8, 4);
    return OPERATING;
}
s32 vwm_hook_020A0E00(WMCallback cb) { u8 *b = qcb(cb, 11, 1); if (b) wr16(b + 8, 4); return OPERATING; } // WM_EndScan
s32 vwm_hook_020A0E40(WMCallback cb, const u8 *bss, const u8 *ssid, s32 ps, s32 auth) {             // WM_StartConnectEx
    (void)ps; (void)auth;
    connect_cb = cb;
    u16 room = 0;
    for (u32 i = 0; i < rooms_n; i++) if (!mcmp(rooms[i].mac, bss + 4, 6)) room = rooms[i].id;
    u8 *b = qcb(cb, 12, 0); if (b) wr16(b + 8, 6);   // CONNECT_START
    if (!room) { u8 *f = qcb(cb, 12, 2); if (f) { wr16(f + 2, 1); wr16(f + 8, 6); } return OPERATING; }
    join_room = room;
    u8 r[26]; wr16(r, room); if (ssid) mcpy(r + 2, ssid, 24); else mset(r + 2, 0, 24);
    rel_send(M_JOIN_REQ, r, 26);
    return OPERATING;
}

// ---------------- Data Sharing (Rennsynchronisation) ----------------
static u32 popc(u32 x) { u32 c = 0; while (x) { c += x & 1; x >>= 1; } return c; }
s32 vwm_call_0202DE7C(u8 *info, u16 port, u16 bitmap, u16 datalen, s32 dbl) {      // WM_StartDataSharing
    (void)port; (void)dbl;
    ds_active = 1; ds_len = datalen > 40 ? 40 : datalen; ds_bm = bitmap; ds_have = 0; ds_seq = 0; ds_waitcnt = 0; ds_hold = 0;
    mset(ds_hok, 0, sizeof ds_hok);
    for (int i = 0; i < 4; i++) { ds_peer_seq[i] = 0; ds_peer_rtt[i] = 0; ds_off[i] = 0; ds_skip[i] = 0; }
    for (u32 a = 0; a < 4; a++) {
        s32 best = -1;
        for (u32 i = 0; i < PREH; i++) if (ds_pre_ok[a][i]) { ds_store(a, ds_pre_seq[a][i], ds_pre[a][i]); best = (s32)i; }
        if (best >= 0) {
            mcpy(ds_last[a], ds_pre[a][best], ds_len); ds_peer_seq[a] = (u16)best; ds_have |= 1u << a; ds_peer_rtt[a] = ds_pre_rtt[a];
        }
    }
    ds_pre_clear();
    ds_miss = 0; ds_win = 0;
    ds_D = (u16)(g_v.last_rtt + 1); if (ds_D < 3) ds_D = 3; if (ds_D > 40) ds_D = 40;
    *(u16 *)(info + 0x810) = datalen;
    g_v.ds_len = ds_len; g_v.ds_bm = ds_bm;
    return 0;
}
s32 vwm_call_0202E230(u8 *info, const u8 *send, u8 *set) {                         // WM_StepDataSharing
    (void)info;
    if (!ds_active) return 3;
    u32 me = g_v.my_aid & 3;
    // eigenen Block für diesen Schritt merken und mit den letzten Blöcken senden
    ds_store(me, ds_seq, send);
    u8 m[6 + DS_REDUN * 40 + 2 + DS_REPAIR * 40]; u32 n = 0;
    for (u32 j = 0; j < DS_REDUN; j++) {
        const u8 *b = ds_get(me, (u16)(ds_seq - j)); if (!b) break;
        mcpy(m + 6 + n * ds_len, b, ds_len); n++;
    }
    m[0] = (u8)me; m[1] = (u8)(g_v.last_rtt > 255 ? 255 : g_v.last_rtt); wr16(m + 2, ds_seq); m[4] = (u8)n; m[5] = 0;
    u32 mlen = 6 + n * ds_len;
    // Nachlieferung: ältester Block, den ein Mitspieler laut seinem letzten Paket noch braucht (sein Schritt - D - 1).
    // Ohne das bleibt das Rennen stehen, wenn alle 4 Kopien eines Blocks verloren gehen.
    if (n == DS_REDUN && ds_seq >= DS_REDUN + 1) {
        s32 low = (s32)ds_seq - DS_REDUN;            // erster Schritt, der NICHT mehr in den 4 Kopien steckt
        s32 need = low + 1;
        for (u32 a = 0; a < 4; a++) {
            if (a == me || !(g_v.conn_bm & (1u << a)) || !(ds_have & (1u << a))) continue;
            s32 nd = (s32)ds_peer_seq[a] - (s32)ds_D - 4;   // -4: D des anderen kann (durch Nachwachsen) etwas größer sein
            if (nd < need) need = nd;
        }
        s32 lim = (s32)ds_seq - (DSH - 2); if (lim < 0) lim = 0;
        if (need < lim) need = lim;
        if (need <= low) {
            u32 rn = 0; u8 *o = m + mlen + 2;
            for (s32 k = need; k <= low && rn < DS_REPAIR; k++) {
                const u8 *b = ds_get(me, (u16)k); if (!b) break;
                mcpy(o + rn * ds_len, b, ds_len); rn++;
            }
            if (rn) { wr16(m + mlen, (u16)need); m[5] = (u8)rn; mlen += 2 + rn * ds_len; g_v.ds_repair++; }
        }
    }
    unrel_add(M_DS, m, mlen); g_v.ds_tx++;
    flush(0);
    if (ds_hold) { ds_hold--; g_v.ds_wait++; return 4; }
    // Verzögerung D: höchster Ping der Runde + 1 (Weg über den Server ~ Ping), mindestens 3.
    // Wächst nur. Kommen Daten wiederholt knapp zu spät (kurze Wartephasen), wächst D um 1.
    u32 mx = g_v.last_rtt;
    for (u32 aid = 0; aid < 4; aid++) if ((g_v.conn_bm & (1u << aid)) && aid != me && ds_peer_rtt[aid] > mx) mx = ds_peer_rtt[aid];
    if (mx + 1 > ds_D) ds_D = (u16)(mx + 1 > 40 ? 40 : mx + 1);
    g_v.ds_D = ds_D;
    // Datensatz für Schritt t = N - D bauen
    s32 t = (s32)ds_seq - ds_D;
    u32 recv = 0, missing = 0;
    for (u32 aid = 0; aid < 4; aid++) {
        if (!(ds_bm & (1u << aid))) continue;
        u8 *dst = set + 4 + popc(ds_bm & ((1u << aid) - 1)) * ds_len;
        if (t < 0 || !(g_v.conn_bm & (1u << aid))) continue;     // Anfang: noch leer
        const u8 *b;
        if (aid == me) b = ds_get(me, (u16)t);
        else if (ds_skip[aid]) b = (ds_have & (1u << aid)) ? ds_last[aid] : 0;
        else b = ds_get(aid, (u16)(t - ds_off[aid]));
        if (b) { mcpy(dst, b, ds_len); recv |= 1u << aid; }
        else if (aid != me) missing |= 1u << aid;
    }
    if (missing) {
        // Immer warten wie im Original-Lockstep (Hänger/Pause: alle stehen kurz, danach synchron weiter).
        // Ist ein Spieler wirklich weg, meldet ihn der Server nach 8 s ab -> er fällt aus conn_bm.
        u32 limit = 0xFFFFFFFFu;
        if (++ds_waitcnt < limit) { g_v.ds_wait++; return 4; }
        for (u32 aid = 0; aid < 4; aid++) if (missing & (1u << aid)) {
            ds_skip[aid] = 1; g_v.ds_rebase++;
            if (ds_have & (1u << aid)) {
                mcpy(set + 4 + popc(ds_bm & ((1u << aid) - 1)) * ds_len, ds_last[aid], ds_len); recv |= 1u << aid;
            }
        }
    }
    wr16(set, ds_bm); wr16(set + 2, (u16)recv);
    dc_store(set, 4 + 4 * ds_len);
    if (ds_seq >= 120) {      // Startphase (Einpendeln) nicht bewerten
        if (ds_waitcnt > 0 && ds_waitcnt <= 8) ds_miss++;   // kurz gewartet = D knapp; lange Wartephase = Pause/Hänger, ignorieren
        if (ds_miss >= 3) { if (ds_D < 40) { ds_D++; g_v.ds_grow++; } ds_miss = 0; ds_win = 0; }
        else if (++ds_win >= 120) { ds_win = 0; ds_miss = 0; }
    }
    ds_waitcnt = 0; ds_seq++; g_v.ds_ok++;
    return 0;
}
s32 vwm_call_0202DF74(u8 *info) { (void)info; ds_active = 0; return 0; }             // WM_EndDataSharing

// Aufruf der Zähler-Erhöhung im WLAN-Manager-Takt (0x0202ED54: bl 0x02028F70, r0 = Manager)
#define G_MGR_TICK ((void (*)(u8 *))0x02028F70)
void vwm_call_0202ED54(u8 *mgr) {
    u32 *ctr = (u32 *)(mgr + 0xA8);
    u32 me = g_v.my_aid & 3, others = g_v.conn_bm & ~(1u << me);
    if (g_v.role == R_HOST) clk_synced = 1;
    if (g_v.role != R_NONE && others) {
        if (++clk_tick >= 3) {   // alle 3 Frames eigenen Stand senden
            clk_tick = 0;
            u8 b[11]; b[0] = CLK_PORT; b[1] = (u8)me; wr16(b + 2, (u16)others); wr16(b + 4, 5);
            wr32(b + 6, *ctr); b[10] = clk_synced;
            unrel_add_seq(M_PORT_U, b, 11, ++pu_tx_seq[CLK_PORT]);
        }
        s32 ahead = -0x7FFFFFFF; u32 now = net_frame();
        if (clk_synced) for (u32 a = 0; a < 4; a++) {
            if (!(others & (1u << a)) || !clk_ok[a]) continue;
            u32 age = now - clk_t[a]; if (age > 240) continue;      // 4 s nichts gehört: nicht auf ihn warten
            s32 d = (s32)(*ctr - (clk_c[a] + (age < CLK_EXTRA ? age : CLK_EXTRA)));
            if (d > ahead) ahead = d;
        }
        g_v.clk_ahead = (u32)ahead;
        if (ahead > CLK_DEAD && !clk_gaveup) {
            if (++clk_run <= CLK_MAXHOLD) { (*ctr)--; g_v.clk_hold++; }
            else { clk_gaveup = 1; g_v.clk_giveup++; }
        } else if (ahead <= CLK_DEAD) { clk_run = 0; clk_gaveup = 0; }
    }
    G_MGR_TICK(mgr);
}
