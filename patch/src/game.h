// Adressen im Spiel (Cars Race-O-Rama EU, B6OP)
#pragma once
typedef unsigned char u8; typedef unsigned short u16; typedef unsigned int u32;
typedef signed int s32; typedef signed short s16;
typedef void (*WMCallback)(void *arg);

#define G_PAD_READ          ((u16 (*)(void))0x02019754)
#define G_OS_GETMAC         ((void (*)(u8 *))0x0209CBE4)
#define G_WM_INITIALIZE     ((s32 (*)(void *, WMCallback, u16))0x020A0A94)
#define G_WM_STARTSCAN      ((s32 (*)(WMCallback, void *))0x020A0D14)
#define G_WM_ENDSCAN        ((s32 (*)(WMCallback))0x020A0E00)
#define G_WM_STARTCONNECTEX ((s32 (*)(WMCallback, void *, void *, s32, s32))0x020A0E40)
#define G_WMI_SETCALLBACK   ((void (*)(s32, WMCallback))0x0209FE14)
#define G_WMI_SENDDIRECT    ((s32 (*)(void *, u32))0x0209FF30)
#define G_WMI_SENDCOMMAND   ((s32 (*)(s32, s32, ...))0x0209FE84)

#define WM_ERR_SUCCESS   0
#define WM_ERR_OPERATING 2
#define API_START_SCAN_EX 38
#define API_START_DCF    17
#define API_SET_DCF_DATA 18
#define REG_KEYINPUT_MASK 0x03FF

#define G_OS_DISABLE_IRQ   ((u32 (*)(void))0x0209CAC4)
#define G_OS_RESTORE_IRQ   ((void (*)(u32))0x0209CAD8)
#define G_WMI_SENDDIRECT2  G_WMI_SENDDIRECT
static inline void mcpy(void *d, const void *s, u32 n) { u8 *a = d; const u8 *b = s; while (n--) *a++ = *b++; }
static inline void mset(void *d, u8 v, u32 n) { u8 *a = d; while (n--) *a++ = v; }
static inline int mcmp(const void *x, const void *y, u32 n) { const u8 *a = x, *b = y; while (n--) { if (*a != *b) return 1; a++; b++; } return 0; }
static inline u16 rd16(const u8 *p) { return (u16)(p[0] | (p[1] << 8)); }
static inline u32 rd32(const u8 *p) { return p[0] | (p[1] << 8) | (p[2] << 16) | ((u32)p[3] << 24); }
static inline void wr16(u8 *p, u16 v) { p[0] = (u8)v; p[1] = (u8)(v >> 8); }
static inline void wr32(u8 *p, u32 v) { p[0] = (u8)v; p[1] = (u8)(v >> 8); p[2] = (u8)(v >> 16); p[3] = (u8)(v >> 24); }

// net.c (Transport)
enum { NET_OFF = 0, NET_BUSY = 1, NET_UP = 2, NET_FAIL = 3 };
void net_start(void);
int  net_status(void);
u32  net_frame(void);
int  net_udp_send(const u8 *data, u32 len);   // 1 = gesendet/eingereiht
void net_tick(void);
extern void vwm_on_udp(const u8 *data, u32 len);   // von net.c bei UDP-Empfang aufgerufen
extern void vwm_tick(void);

// qol.c (Komfort: automatisch ins Mehrspieler-Menü, Single-Card-Knopf ausblenden)
void qol_tick(u8 auto_mode, u8 auto_profile);
