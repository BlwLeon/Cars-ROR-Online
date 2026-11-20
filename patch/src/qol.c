// Komfortfunktionen im Menü (Cars Race-O-Rama EU, B6OP)
//
// Menüknöpfe werden im Spiel per Name an ein Callback-Objekt der Menü-Logik gebunden:
//   btn = Bind(uiRoot, "Name", &task->slot, typ, 0, 0, 0)      (0x02057598 Hauptmenü, 0x0204E43C Lobby)
// Beim Drücken ruft das Spiel  cb = *(btn+0x0C); cb->vtable[0](cb)  auf (0x0203D1DC).
// Wir leiten einzelne Bind-Aufrufe um, merken uns die Knöpfe und "drücken" sie selbst:
//   Press Start -> Profil -> Mehrspieler -> (Host | Beitreten)
// Knopf-Felder: +0x00 Grafik-Knoten, +0x08 Beschriftung (Knoten bei +0x4C), +0x0C Callback,
//               +0x41 markiert, +0x42 aktiv, +0x43 anwählbar.  Knoten: +0x04 Zeichenliste, +0x20 Bit6 = eingehängt.
#include "game.h"

typedef u8 *(*bind_fn)(void *, const char *, void *, s32, s32, s32, s32);
#define MENU_BIND  ((bind_fn)0x02057598)
#define LOBBY_BIND ((bind_fn)0x0204E43C)
#define BTN_SET_SELECTABLE ((void (*)(u8 *, s32))0x0203D290)
#define LIST_UNLINK ((void (*)(void *))0x020053F8)

enum { K_START, K_PROFILE, K_MP, K_HOST, K_JOIN, K_N };
#define DELAY 40          // Frames nach dem Aufbau des Menüs, bevor gedrückt wird (Einblenden abwarten)
#define GIVE_UP 60 * 90   // nach 90 s nicht mehr eingreifen

struct qol {
    char magic[8];        // "CRQOLDBG"
    u32 step, presses, hidden, last_kind;
    u8 *btn[K_N]; void *slot[K_N]; u32 at[K_N];
};
__attribute__((used)) struct qol g_q = {{'C','R','Q','O','L','D','B','G'}, 0, 0, 0, 0xFF, {0}, {0}, {0}};
static u32 frame;
static u8 done, prof_slot = 0xFF;

static void note(u32 k, u8 *btn, void *slot) {
    if (!btn) return;
    g_q.btn[k] = btn; g_q.slot[k] = slot; g_q.at[k] = frame; g_q.last_kind = k;
}

// --- Hauptmenü ---
u8 *vwm_call_02057260(void *r, const char *n, void *s, s32 t, s32 a, s32 b, s32 c) {   // PressStartButton
    u8 *x = MENU_BIND(r, n, s, t, a, b, c); note(K_START, x, s); return x;
}
static u8 *prof(u32 i, void *r, const char *n, void *s, s32 t, s32 a, s32 b, s32 c) {
    u8 *x = MENU_BIND(r, n, s, t, a, b, c);
    if (i == prof_slot) note(K_PROFILE, x, s);
    return x;
}
u8 *vwm_call_02056C80(void *r, const char *n, void *s, s32 t, s32 a, s32 b, s32 c) { return prof(0, r, n, s, t, a, b, c); }
u8 *vwm_call_02056CA8(void *r, const char *n, void *s, s32 t, s32 a, s32 b, s32 c) { return prof(1, r, n, s, t, a, b, c); }
u8 *vwm_call_02056CD0(void *r, const char *n, void *s, s32 t, s32 a, s32 b, s32 c) { return prof(2, r, n, s, t, a, b, c); }
u8 *vwm_call_0205659C(void *r, const char *n, void *s, s32 t, s32 a, s32 b, s32 c) {   // MPButton
    u8 *x = MENU_BIND(r, n, s, t, a, b, c); note(K_MP, x, s); return x;
}

// --- Mehrspieler-Menü ---
u8 *vwm_call_0204DBC8(void *r, const char *n, void *s, s32 t, s32 a, s32 b, s32 c) {   // MultiCardHostButton
    u8 *x = LOBBY_BIND(r, n, s, t, a, b, c); note(K_HOST, x, s); return x;
}
u8 *vwm_call_0204DBEC(void *r, const char *n, void *s, s32 t, s32 a, s32 b, s32 c) {   // MultiCardJoinButton
    u8 *x = LOBBY_BIND(r, n, s, t, a, b, c); note(K_JOIN, x, s); return x;
}
static void node_hide(u8 *node) {
    if (!node) return;
    LIST_UNLINK(node + 4);                 // aus der Zeichenliste nehmen (die Liste verlinkt sich danach selbst)
    node[0x20] &= (u8)~0x40;               // "eingehängt" löschen, damit Ebenen-Änderungen ihn nicht zurückholen
}
u8 *vwm_call_0204DC10(void *r, const char *n, void *s, s32 t, s32 a, s32 b, s32 c) {   // SingleCardHostButton
    u8 *x = LOBBY_BIND(r, n, s, t, a, b, c);
    if (x) {                               // Download Play wird online nicht benutzt -> ausblenden + nicht anwählbar
        BTN_SET_SELECTABLE(x, 0);
        node_hide(*(u8 **)x);
        u8 *lbl = *(u8 **)(x + 8);
        if (lbl) node_hide(*(u8 **)(lbl + 0x4C));
        g_q.hidden++;
    }
    return x;
}

static int press(u32 k) {
    u8 *x = g_q.btn[k];
    if (!x || *(void **)(x + 0x0C) != g_q.slot[k] || !x[0x42]) return 0;   // Menü inzwischen gewechselt / Knopf inaktiv
    void **cb = g_q.slot[k];
    ((void (*)(void *))(*(void ***)cb)[0])(cb);
    g_q.btn[k] = 0; g_q.presses++;
    return 1;
}

void qol_tick(u8 auto_mode, u8 auto_profile) {
    frame++;
    prof_slot = auto_profile;
    if (done || !auto_mode) return;
    if (frame > GIVE_UP) { done = 1; return; }
    // Der jeweils zuletzt aufgebaute Bildschirm bestimmt den nächsten Schritt
    u32 k = g_q.last_kind;
    if (k >= K_N || !g_q.btn[k] || frame - g_q.at[k] < DELAY) return;
    if (k == K_HOST || k == K_JOIN) {   // Mehrspieler-Menü steht (Host/Join werden direkt nacheinander gebunden)
        u32 want = auto_mode == 2 ? K_HOST : auto_mode == 3 ? K_JOIN : K_N;
        if (want != K_N && !press(want)) return;
        g_q.step = 5; done = 1;
        return;
    }
    if (press(k)) g_q.step = k + 1;
}
