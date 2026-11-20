// Cars Race-O-Rama Online - Transport: DS-WLAN (Infrastruktur/DCF) -> UDP -> Server
#include "game.h"

struct netcfg {
    char magic[8];     // "CRNETCFG" (vom Launcher patchbar)
    u8 my_ip[4], gw_ip[4], srv_ip[4];
    u16 srv_port, my_port;
    char ssid[32];     // leer = erster offener Access Point
    u8 auto_mode;      // Launcher: 0 = aus, 1 = bis Mehrspieler-Menü, 2 = direkt Host, 3 = direkt Beitreten
    u8 auto_profile;   // Launcher: Profil-Platz 0..2 (0xFF = nicht automatisch wählen)
    u8 rsv[2];
};
__attribute__((section(".cfg"), used)) struct netcfg g_cfg = {
    {'C','R','N','E','T','C','F','G'},
    {10,64,0,16}, {10,64,0,1}, {10,64,0,1}, 27015, 27015, {0}, 0, 0xFF, {0, 0}
};

struct netdbg {
    char magic[8];                 // "CRNETDBG"
    u32 version, state, frame, fail_step;
    s32 ret_init, ret_scan, ret_conn, ret_dcf, ret_send;
    u16 cb_api, cb_err, cb_w4, cb_w6, cb_state, cb_pad;
    u32 cb_count, scan_count, rsv0, found;
    u8 mymac[6], apmac[6], gwmac[6], pad0[2];
    u32 tx_count, tx_cb_err, rx_count, rx_nosnap, rx_arp, rx_ip, rx_udp, rx_drop;
    u32 txq_full, rsv1, aid;
    u8 ap_ssid[32];
};
__attribute__((section(".dbg"), used)) struct netdbg g_dbg = { {'C','R','N','E','T','D','B','G'}, 6 };

struct orighdr { u32 magic, arm9_off, arm9_size, rom_size; u16 crc, pad; };
__attribute__((section(".cfg"), used)) struct orighdr g_orighdr = { 0x4844524F };

enum { ST_IDLE = 0, ST_INIT, ST_INIT_WAIT, ST_SCAN, ST_SCAN_WAIT, ST_ENDSCAN_WAIT,
       ST_CONNECT, ST_CONNECT_WAIT, ST_DCF, ST_DCF_WAIT, ST_ARP, ST_UP, ST_FAIL = 0x80 };

#define DCF_HALF 0x700
#define SCANBUF_SIZE 1024
#define PKT 704
static u8 wm_sysbuf[0xF00] __attribute__((aligned(32)));
static u8 bssdesc[256] __attribute__((aligned(32)));
static u8 scanbuf[SCANBUF_SIZE] __attribute__((aligned(32)));
static u8 dcf_recv[DCF_HALF * 2] __attribute__((aligned(32)));
static u8 txbuf[PKT + 64] __attribute__((aligned(32)));
static u8 ssid24[24] __attribute__((aligned(4)));
struct scanexreq { u16 apiid, channelList; u32 scanBuf; u16 scanBufSize, maxChannelTime;
                   u8 bssid[6]; u16 scanType, ssidLength; u8 ssid[32]; u16 ssidMatchLength; };
static struct scanexreq scanreq __attribute__((aligned(32)));

// Empfangs-Ring (IRQ -> Thread) und Sende-Warteschlange
#define RXN 32
static u8 rxq[RXN][PKT]; static u16 rxlen[RXN]; static volatile u32 rx_w, rx_r;
#define TXN 10
static u8 txq[TXN][PKT]; static u16 txqlen[TXN]; static u16 txqet[TXN]; static u8 txqdst[TXN][6];
static volatile u32 tx_w, tx_r, tx_busy;

static u32 timer;
extern s32 orig_StartConnectEx(WMCallback, void *, void *, s32, s32);
__asm__(".arm\n.global orig_StartConnectEx\norig_StartConnectEx:\n  push {r3, r4, r5, r6, r7, lr}\n  ldr pc, =0x020A0E44\n  .ltorg\n");
static volatile u32 ev_flag;
static const u8 BCAST[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

u32 net_frame(void) { return g_dbg.frame; }
int net_status(void) {
    if (g_dbg.state == ST_UP) return NET_UP;
    if (g_dbg.state == ST_FAIL) return NET_FAIL;
    if (g_dbg.state == ST_IDLE) return NET_OFF;
    return NET_BUSY;
}

static void dc_flush(void *p, u32 n) {
    u32 a = (u32)p & ~31u, e = (u32)p + n;
    for (; a < e; a += 32) __asm__ volatile("mcr p15,0,%0,c7,c14,1" ::"r"(a));
    __asm__ volatile("mcr p15,0,%0,c7,c10,4" ::"r"(0));
}
static void dc_inval(void *p, u32 n) {
    u32 a = (u32)p & ~31u, e = (u32)p + n;
    for (; a < e; a += 32) __asm__ volatile("mcr p15,0,%0,c7,c6,1" ::"r"(a));
}
static u16 be16(const u8 *p) { return (u16)((p[0] << 8) | p[1]); }
static void wbe16(u8 *p, u16 v) { p[0] = v >> 8; p[1] = (u8)v; }
static u16 ip_csum(const u8 *p, u32 n) {
    u32 s = 0;
    for (u32 i = 0; i + 1 < n; i += 2) s += (p[i] << 8) | p[i + 1];
    if (n & 1) s += p[n - 1] << 8;
    while (s >> 16) s = (s & 0xFFFF) + (s >> 16);
    return (u16)~s;
}
static void fail(u32 step) { g_dbg.fail_step = step; g_dbg.state = ST_FAIL; }

// ---- WM-Callbacks (Interrupt) ----
static void note_cb(void *arg) {
    u16 *c = arg;
    g_dbg.cb_api = c[0]; g_dbg.cb_err = c[1]; g_dbg.cb_w4 = c[2]; g_dbg.cb_w6 = c[3]; g_dbg.cb_state = c[4];
    g_dbg.cb_count++;
}
static void cb_init(void *arg) { note_cb(arg); u16 *c = arg; ev_flag = c[1] == 0 ? 1 : 2; }
static void cb_scan(void *arg) { note_cb(arg); u16 *c = arg; if (c[1]) { ev_flag = 2; return; } if (c[4] == 4 || c[4] == 5) ev_flag = 3; }
static void cb_endscan(void *arg) { note_cb(arg); ev_flag = 1; }
static void cb_conn(void *arg) {
    note_cb(arg); u16 *c = arg;
    if (c[1] != 0) { ev_flag = 2; return; }
    if (c[4] == 7) { g_dbg.aid = c[5]; ev_flag = 1; }
    else if (c[4] == 9 || c[4] == 8) { ev_flag = 5; if (g_dbg.state == ST_UP) fail(20); }
}
static void tx_kick(void);
static void cb_send(void *arg) {
    u16 *c = arg;
    if (c[1] != 0) g_dbg.tx_cb_err++;
    tx_busy = 0;
    tx_kick();
}
static void cb_dcf(void *arg) {
    u16 *c = arg;
    if (c[0] != API_START_DCF) return;
    if (c[1] != 0) { note_cb(arg); ev_flag = 2; return; }
    if (c[2] == 14) { note_cb(arg); ev_flag = 1; return; }
    if (c[2] != 15) return;
    u8 *buf = *(u8 **)(c + 4);
    g_dbg.rx_count++;
    dc_inval(buf, DCF_HALF);
    for (u32 i = 0; i < 80; i += 2) {
        if (buf[i] == 0xAA && buf[i + 1] == 0xAA && buf[i + 2] == 0x03 && buf[i + 3] == 0 && buf[i + 4] == 0 && buf[i + 5] == 0) {
            u8 *pl = buf + i + 6;
            u16 et = be16(pl); u32 len = 0;
            if (et == 0x0806) len = 2 + 28;
            else if (et == 0x0800) len = 2 + be16(pl + 4);
            if (len < 2 || len > PKT) { g_dbg.rx_drop++; return; }
            if (rx_w - rx_r >= RXN) { g_dbg.rx_drop++; return; }
            u32 s = rx_w % RXN;
            mcpy(rxq[s], pl, len); rxlen[s] = (u16)len; rx_w++;
            return;
        }
    }
    g_dbg.rx_nosnap++;
}

// ---- Senden ----
static void tx_kick(void) {        // nächsten Rahmen an ARM7 übergeben (Thread oder IRQ)
    u32 irq = G_OS_DISABLE_IRQ();
    if (!tx_busy && tx_r != tx_w) {
        u32 s = tx_r % TXN;
        u8 *f = txbuf;
        f[0] = 0xAA; f[1] = 0xAA; f[2] = 0x03; f[3] = 0; f[4] = 0; f[5] = 0;
        wbe16(f + 6, txqet[s]);
        mcpy(f + 8, txq[s], txqlen[s]);
        u32 len = 8 + txqlen[s];
        const u8 *m = txqdst[s];
        tx_r++;
        dc_flush(txbuf, len);
        tx_busy = 1;
        G_WMI_SETCALLBACK(API_SET_DCF_DATA, cb_send);
        s32 r = G_WMI_SENDCOMMAND(API_SET_DCF_DATA, 4, m[0] | (m[1] << 8) | (m[2] << 16) | ((u32)m[3] << 24),
                                  m[4] | (m[5] << 8), (u32)txbuf, len);
        g_dbg.ret_send = r;
        if (r != WM_ERR_OPERATING && r != WM_ERR_SUCCESS) tx_busy = 0; else g_dbg.tx_count++;
    }
    G_OS_RESTORE_IRQ(irq);
}
static int queue_frame(const u8 *dst, u16 et, const u8 *pl, u32 len) {
    if (len > PKT) return 0;
    u32 irq = G_OS_DISABLE_IRQ();
    if (tx_w - tx_r >= TXN) { g_dbg.txq_full++; G_OS_RESTORE_IRQ(irq); return 0; }
    u32 s = tx_w % TXN;
    mcpy(txq[s], pl, len); txqlen[s] = (u16)len; txqet[s] = et; mcpy(txqdst[s], dst, 6);
    tx_w++;
    G_OS_RESTORE_IRQ(irq);
    tx_kick();
    return 1;
}
static void send_arp(u16 op, const u8 *tmac, const u8 *tip, const u8 *dst) {
    u8 a[28];
    wbe16(a, 1); wbe16(a + 2, 0x0800); a[4] = 6; a[5] = 4; wbe16(a + 6, op);
    mcpy(a + 8, g_dbg.mymac, 6); mcpy(a + 14, g_cfg.my_ip, 4);
    mcpy(a + 18, tmac, 6); mcpy(a + 24, tip, 4);
    queue_frame(dst, 0x0806, a, 28);
}
static u8 ippkt[PKT];
static u16 ip_id;
int net_udp_send(const u8 *data, u32 n) {
    if (g_dbg.state != ST_UP || n + 28 > PKT) return 0;
    u8 *ip = ippkt; u32 tot = 28 + n;
    mset(ip, 0, 28);
    ip[0] = 0x45; wbe16(ip + 2, (u16)tot); wbe16(ip + 4, ip_id++);
    ip[8] = 64; ip[9] = 17;
    mcpy(ip + 12, g_cfg.my_ip, 4); mcpy(ip + 16, g_cfg.srv_ip, 4);
    wbe16(ip + 10, ip_csum(ip, 20));
    u8 *udp = ip + 20;
    wbe16(udp, g_cfg.my_port); wbe16(udp + 2, g_cfg.srv_port); wbe16(udp + 4, (u16)(8 + n));
    mcpy(udp + 8, data, n);
    return queue_frame(g_dbg.gwmac, 0x0800, ip, tot);
}

// ---- Empfang verarbeiten (Thread) ----
static void process_rx(void) {
    while (rx_r != rx_w) {
        u32 s = rx_r % RXN;
        u8 *p = rxq[s]; u32 len = rxlen[s];
        u16 et = be16(p); u8 *d = p + 2;
        if (et == 0x0806) {
            g_dbg.rx_arp++;
            u16 op = be16(d + 6);
            if (op == 2 && !mcmp(d + 14, g_cfg.gw_ip, 4)) mcpy(g_dbg.gwmac, d + 8, 6);
            else if (op == 1 && !mcmp(d + 24, g_cfg.my_ip, 4)) send_arp(2, d + 8, d + 14, d + 8);
        } else if (et == 0x0800 && len >= 2 + 28) {
            g_dbg.rx_ip++;
            u32 ihl = (d[0] & 15) * 4;
            if (d[9] == 17 && !mcmp(d + 16, g_cfg.my_ip, 4)) {
                u8 *u = d + ihl;
                if (be16(u + 2) == g_cfg.my_port) {
                    u32 ul = be16(u + 4);
                    if (ul >= 8 && ihl + ul <= len - 2) { g_dbg.rx_udp++; vwm_on_udp(u + 8, ul - 8); }
                }
            }
        }
        rx_r++;
    }
}

void net_start(void) {
    if (g_dbg.state != ST_IDLE && g_dbg.state != ST_FAIL) return;
    if (g_dbg.state == ST_FAIL && g_dbg.ret_init == WM_ERR_OPERATING) { // WM lief schon: nur neu verbinden
        g_dbg.fail_step = 0; g_dbg.scan_count = 0; g_dbg.state = ST_SCAN; return;
    }
    g_dbg.fail_step = 0; g_dbg.scan_count = 0;
    G_OS_GETMAC(g_dbg.mymac);
    // Eigene IP/Port aus der MAC ableiten: mehrere DS (z.B. melonDS-Instanzen) im selben
    // virtuellen Netz dürfen nicht dieselbe Adresse haben.
    if (g_cfg.my_ip[3] == 16) g_cfg.my_ip[3] = (u8)(20 + (g_dbg.mymac[5] ^ g_dbg.mymac[4]) % 200);
    if (g_cfg.my_port == 27015) g_cfg.my_port = (u16)(27100 + g_dbg.mymac[5]);
    g_dbg.state = ST_INIT;
}

void net_tick(void) {
    u32 st = g_dbg.state, ev = ev_flag;
    if (timer) timer--;
    switch (st) {
    case ST_INIT:
        ev_flag = 0;
        g_dbg.ret_init = ((s32 (*)(void *, WMCallback, u16, u32))0x020A0AA4)(wm_sysbuf, cb_init, 2, 0);  // WMi_InitCore (WM_Initialize ist virtualisiert)
        if (g_dbg.ret_init != WM_ERR_OPERATING) { fail(1); break; }
        g_dbg.state = ST_INIT_WAIT; break;
    case ST_INIT_WAIT:
        if (ev == 1) g_dbg.state = ST_SCAN; else if (ev == 2) fail(2);
        break;
    case ST_SCAN:
        ev_flag = 0;
        mset(scanbuf, 0, SCANBUF_SIZE); dc_flush(scanbuf, SCANBUF_SIZE);
        mset(&scanreq, 0, sizeof scanreq);
        scanreq.apiid = API_START_SCAN_EX; scanreq.channelList = 0x1FFF;
        scanreq.scanBuf = (u32)scanbuf; scanreq.scanBufSize = SCANBUF_SIZE; scanreq.maxChannelTime = 120;
        mset(scanreq.bssid, 0xFF, 6);
        G_WMI_SETCALLBACK(API_START_SCAN_EX, cb_scan);
        g_dbg.ret_scan = G_WMI_SENDDIRECT(&scanreq, sizeof scanreq);
        if (g_dbg.ret_scan != WM_ERR_OPERATING && g_dbg.ret_scan != 0) { fail(3); break; }
        g_dbg.scan_count++; timer = 600; g_dbg.state = ST_SCAN_WAIT; break;
    case ST_SCAN_WAIT:
        if (ev == 3) {
            dc_inval(scanbuf, SCANBUF_SIZE);
            u32 off = 0, picked = 0;
            while (off + 64 <= SCANBUF_SIZE) {
                u8 *e = scanbuf + off; u32 len = *(u16 *)e * 2;
                if (len < 64 || off + len > SCANBUF_SIZE) break;
                u16 capa = *(u16 *)(e + 44), sl = *(u16 *)(e + 10);
                int ok = (capa & 1) && !(capa & 0x10) && sl <= 32;
                if (ok && g_cfg.ssid[0]) ok = !mcmp(e + 12, g_cfg.ssid, sl) && g_cfg.ssid[sl] == 0;
                if (ok && !picked) {
                    picked = 1;
                    mcpy(bssdesc, e, len < sizeof bssdesc ? len : sizeof bssdesc);
                    mcpy(g_dbg.apmac, e + 4, 6); mset(g_dbg.ap_ssid, 0, 32); mcpy(g_dbg.ap_ssid, e + 12, sl);
                }
                off += (len + 3) & ~3u;
            }
            if (picked) { g_dbg.found++; ev_flag = 0; G_WMI_SETCALLBACK(11, cb_endscan); G_WMI_SENDCOMMAND(11, 0); g_dbg.state = ST_ENDSCAN_WAIT; }
            else if (g_dbg.scan_count >= 15) fail(4);
            else g_dbg.state = ST_SCAN;
        } else if (ev == 2) fail(5); else if (timer == 0) fail(12);
        break;
    case ST_ENDSCAN_WAIT:
        if (ev == 1) g_dbg.state = ST_CONNECT; break;
    case ST_CONNECT:
        ev_flag = 0; mset(ssid24, 0, 24); dc_flush(bssdesc, sizeof bssdesc);
        g_dbg.ret_conn = orig_StartConnectEx(cb_conn, bssdesc, ssid24, 0, 0);
        if (g_dbg.ret_conn != WM_ERR_OPERATING) { fail(6); break; }
        timer = 600; g_dbg.state = ST_CONNECT_WAIT; break;
    case ST_CONNECT_WAIT:
        if (ev == 1) g_dbg.state = ST_DCF; else if (ev == 2 || ev == 5) fail(7); else if (timer == 0) fail(8);
        break;
    case ST_DCF:
        ev_flag = 0;
        G_WMI_SETCALLBACK(API_START_DCF, cb_dcf);
        dc_flush(dcf_recv, sizeof dcf_recv);
        g_dbg.ret_dcf = G_WMI_SENDCOMMAND(API_START_DCF, 2, (u32)dcf_recv, DCF_HALF);
        if (g_dbg.ret_dcf != WM_ERR_OPERATING && g_dbg.ret_dcf != 0) { fail(9); break; }
        timer = 300; g_dbg.state = ST_DCF_WAIT; break;
    case ST_DCF_WAIT:
        if (ev == 1) { g_dbg.state = ST_ARP; timer = 0; } else if (ev == 2) fail(10); else if (timer == 0) fail(11);
        break;
    case ST_ARP: {
        static const u8 zero[6] = {0};
        if (mcmp(g_dbg.gwmac, zero, 6)) { g_dbg.state = ST_UP; break; }
        if (timer == 0) {
            if (++g_dbg.rsv1 > 20) { fail(13); break; }
            send_arp(1, zero, g_cfg.gw_ip, BCAST); timer = 30;
        }
        break;
    }
    }
    process_rx();
    tx_kick();
}

static void restore_header(void) {
    volatile u8 *h = (volatile u8 *)0x027FFE00;
    if (!g_orighdr.arm9_off) return;
    *(volatile u32 *)(h + 0x20) = g_orighdr.arm9_off;
    *(volatile u32 *)(h + 0x2C) = g_orighdr.arm9_size;
    *(volatile u32 *)(h + 0x80) = g_orighdr.rom_size;
    *(volatile u16 *)(h + 0x15E) = g_orighdr.crc;
}

// Ersetzt den PAD_Read-Aufruf in Pad::Update (0x02019748) - läuft einmal pro Frame
u16 hook_pad_read(void) {
    u16 k = G_PAD_READ();
    restore_header();
    g_dbg.frame++;
    net_tick();
    vwm_tick();
    qol_tick(g_cfg.auto_mode, g_cfg.auto_profile);
    return k;
}
