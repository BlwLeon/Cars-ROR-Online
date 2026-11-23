"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
let api = null, ST = {};

function toast(msg, bad) {
  const t = $("#toast"); t.textContent = msg; t.className = "toast on" + (bad ? " bad" : "");
  clearTimeout(t._h); t._h = setTimeout(() => t.className = "toast", 3200);
}
function msg(el, text, kind) { el.textContent = text; el.className = "msg on " + kind; }

// ---------------- Navigation ----------------
$$(".nav button").forEach(b => b.onclick = () => {
  $$(".nav button").forEach(x => x.classList.toggle("on", x === b));
  $$(".page").forEach(p => p.classList.toggle("on", p.id === "p-" + b.dataset.p));
  ({ server: loadServer, settings: loadSettings, profile: loadProfile }[b.dataset.p] || (() => 0))();
});
$$("#setTabs button").forEach(b => b.onclick = () => {
  $$("#setTabs button").forEach(x => x.classList.toggle("on", x === b));
  $$(".sub-page").forEach(p => p.classList.toggle("on", p.id === "s-" + b.dataset.s));
});

// ---------------- Zustand ----------------
let refreshing = false;
async function refresh() {
  if (refreshing) return;          // nicht stapeln, wenn ein langer Aufruf (Suche, Tastenaufnahme) läuft
  refreshing = true;
  try { ST = await api.state(); } finally { refreshing = false; }
  $("#ver").textContent = t("version") + " " + ST.version;
  $("#aboutVer").textContent = t("version") + " " + ST.version;
  if (ST.lang && ST.lang !== LANG) applyLang(ST.lang);
  $("#setup").classList.toggle("on", !ST.setup_done || !ST.lang);
  if (ST.setup_done && ST.lang && !ST.intro_seen && !introShown) showIntro();
  $("#setupLang").style.display = ST.lang ? "none" : "";
  $("#setupRom").style.display = ST.lang ? "" : "none";
  const s = ST.server;
  $("#srvName").textContent = s.name || s.address;
  $("#srvDot").className = "dot " + (!ST.srv_checked ? "warn" : ST.srv_online ? "ok" : "bad");
  $("#srvState").textContent = !ST.srv_checked ? "…" : ST.srv_online ? t("srv_online", { p: ST.srv_ping }) : t("srv_offline");
  $("#heroServer").textContent = s.name || "–";
  $("#heroAddr").textContent = `${s.address}:${s.port}`;
  $("#hostPill").style.display = ST.hosting ? "" : "none";
  $("#hostName").textContent = ST.server_name;
  $("#btnStopHost").style.display = ST.hosting ? "" : "none";
  $("#btnHost").disabled = ST.hosting;
  if (!$("#hostNameIn").value) $("#hostNameIn").value = ST.server_name;
  $("#playState").textContent = ST.playing ? t("play_running") : (ST.melon ? "" : t("play_nomelon"));
  $("#btnHostPlay").disabled = $("#btnJoinPlay").disabled = ST.playing || !ST.melon;
  $("#autoNav").checked = ST.auto_nav;
  $("#unlockAll").checked = ST.unlock_all;
  if (ST.crash != null) toast(t("play_crash", { c: ST.crash >>> 0 }), true);
}

// ---------------- Erste Schritte ----------------
let introShown = false;
function showIntro() { introShown = true; $("#intro").classList.add("on"); }
async function closeIntro() { $("#intro").classList.remove("on"); await api.set_intro_seen(); ST.intro_seen = true; }
$("#btnIntro").onclick = showIntro;
$("#btnIntroOk").onclick = closeIntro;
$$("#intro [data-go]").forEach(b => b.onclick = async () => { await closeIntro(); $(`.nav button[data-p="${b.dataset.go}"]`).click(); });

// ---------------- Ersteinrichtung ----------------
$("#btnPickRom").onclick = async () => {
  const p = await api.pick_rom();
  if (p && p.error) return msg($("#setupMsg"), p.msg, "bad");
  if (!p) return;
  $("#romPath").textContent = p.split(/[\\/]/).pop();
  msg($("#setupMsg"), t("setup_patching"), "info");
  const r = await api.setup_rom(p);
  msg($("#setupMsg"), r.msg, r.ok ? "ok" : "bad");
  if (r.ok) setTimeout(() => { refresh(); loadDriver(); }, 1200);
};

// ---------------- Spielen ----------------
async function play(mode) {
  $("#btnHostPlay").disabled = $("#btnJoinPlay").disabled = true;
  let r = await api.play(mode);
  if (!r.ok && r.need_rom) {          // Original-ROM für den neuen Patch erneut auswählen, dann nochmal starten
    toast(r.msg, true);
    const p = await api.pick_rom();
    if (p) {
      const s = await api.setup_rom(p);
      r = s.ok ? await api.play(mode) : s;
    }
  }
  if (!r.ok) { toast(r.msg, true); if (r.offline) refresh(); } else toast(t("play_started"));
  setTimeout(refresh, 1500);
}
$("#btnHostPlay").onclick = () => play("host");
$("#btnJoinPlay").onclick = () => play("join");
$("#autoNav").onchange = async () => { await api.set_auto_nav($("#autoNav").checked); toast(t("saved")); };
$("#unlockAll").onchange = async () => { await api.set_unlock_all($("#unlockAll").checked); toast(t("saved")); };
async function loadDriver() {
  const p = await api.profile();
  const used = p.profiles.filter(x => x.used);
  $("#heroDriver").textContent = p.driver || t("play_noprofile");
}

// ---------------- Server ----------------
let found = [];
function srvRow(s, i) {
  const rooms = (s.rooms || []);
  const rtxt = rooms.length ? rooms.map(r => t("srv_room", { p: r.players, m: r.max }) + (r.open ? "" : t("srv_room_running"))).join(", ") : t("srv_no_room");
  const sel = ST.server && (ST.server.address === (s.local ? "127.0.0.1" : s.ip));
  return `<div class="srv ${sel ? "sel" : ""}" data-i="${i}">
    <div class="ic"><svg><use href="#i-server"/></svg></div>
    <div class="nm"><b>${esc(s.name)}</b><span>${s.local ? t("srv_this_pc") : esc(s.device) + " · " + esc(s.ip)} · ${esc(rtxt)}</span></div>
    <span class="tag">Mod ${esc(s.mod || "?")}</span>
    <span class="tag ${s.ping_ms < 60 ? "ok" : "warn"}">${s.ping_ms} ms</span>
    <button class="btn">${sel ? t("srv_selected") : t("srv_select")}</button></div>`;
}
async function search() {
  const b = $("#btnSearch"); b.disabled = true; b.innerHTML = '<span class="spin"></span>' + esc(t("srv_searching"));
  const r = await api.search_servers();
  b.disabled = false; b.innerHTML = '<svg><use href="#i-search"/></svg>' + esc(t("srv_search"));
  found = r.servers || [];
  $("#srvList").innerHTML = found.length ? found.map(srvRow).join("") :
    `<div class="empty">${esc(t("srv_none"))}</div>`;
  const h = $("#tsHint");
  if (!r.tailscale) msg(h, t("srv_no_ts"), "info");
  else h.className = "msg";
  bindSrv();
}
function bindSrv() {
  $$("#srvList .srv").forEach(el => el.onclick = async () => {
    const s = found[+el.dataset.i];
    const r = await api.select_server(s.name, s.local ? "127.0.0.1" : s.ip, s.port || 27015);
    if (!r.ok) return toast(r.msg, true);
    toast(t("srv_selected_toast", { n: s.name }), r.online === false); await refresh();
    $("#srvList").innerHTML = found.map(srvRow).join(""); bindSrv();
  });
}
async function loadServer() { await refresh(); if (!found.length) search(); }
$("#btnSearch").onclick = search;
$("#btnManual").onclick = async () => {
  const a = $("#manAddr").value.trim(); if (!a) return;
  const r = await api.select_server(a, a, +$("#manPort").value || 27015);
  if (!r.ok) return toast(r.msg, true);
  toast(r.online === false ? t("srv_applied_off") : t("srv_applied"), r.online === false); refresh();
};
$("#btnHost").onclick = async () => {
  const r = await api.host($("#hostNameIn").value.trim());
  if (r.tailscale_ip) $("#hostInfo").innerHTML = t("host_running_ts", { ip: esc(r.tailscale_ip) });
  else $("#hostInfo").textContent = t("host_running_nots");
  if (r.addrs && r.addrs.length) $("#hostInfo").innerHTML += "<br>" + t("host_addrs", { list: r.addrs.map(x => "<b>" + esc(x.ip) + "</b>" + (x.name ? " (" + esc(x.name) + ")" : "")).join(", ") });
  toast(r.ok ? t("host_started") : t("host_failed"), !r.ok);
  setTimeout(() => { refresh(); search(); }, 900);
};
$("#btnStopHost").onclick = async () => { await api.stop_host(); toast(t("host_stopped")); refresh(); $("#hostInfo").innerHTML = t("host_info"); };

// ---------------- Einstellungen: Tasten ----------------
const QT = { ArrowLeft: 0x01000012, ArrowUp: 0x01000013, ArrowRight: 0x01000014, ArrowDown: 0x01000015, Enter: 0x01000004,
  NumpadEnter: 0x21000005, Backspace: 0x01000003, Tab: 0x01000001, Space: 32, ShiftLeft: 0x01000020, ShiftRight: 0x01000020,
  ControlLeft: 0x01000021, ControlRight: 0x01000021, AltLeft: 0x01000023, AltRight: 0x01001103, Insert: 0x01000006,
  Delete: 0x01000007, Home: 0x01000010, End: 0x01000011, PageUp: 0x01000016, PageDown: 0x01000017, Minus: 45, Equal: 61,
  Comma: 44, Period: 46, Slash: 47, Semicolon: 59, Quote: 39, BracketLeft: 91, BracketRight: 93, Backslash: 92, Backquote: 96 };
const QT_NAMES = { 0x01000012: "←", 0x01000013: "↑", 0x01000014: "→", 0x01000015: "↓", 0x01000004: "q_enter", 0x21000005: "q_numenter",
  0x01000003: "q_back", 0x01000001: "q_tab", 32: "q_space", 0x01000020: "q_shift", 0x01000021: "q_ctrl", 0x01000023: "q_alt",
  0x01001103: "q_altgr", 0x01000006: "q_ins", 0x01000007: "q_del", 0x01000010: "q_home", 0x01000011: "q_end", 0x01000016: "q_pgup", 0x01000017: "q_pgdn" };
function qtFromEvent(e) {
  const c = e.code;
  // Buchstaben nach der Tastaturbelegung (wie Qt/melonDS): QWERTZ-Z/Y und Ä/Ö/Ü richtig erkennen.
  // Qt-Tastencodes für Buchstaben = Großbuchstabe (Unicode), z.B. Ä = 0xC4.
  if (e.key && e.key.length === 1 && /\p{L}/u.test(e.key) && !/^Numpad/.test(c)) {
    const u = e.key.toUpperCase();
    return (u.length === 1 ? u : e.key).codePointAt(0);
  }
  if (/^Key[A-Z]$/.test(c)) return c.charCodeAt(3);
  if (/^Digit\d$/.test(c)) return 48 + +c[5];
  if (/^Numpad\d$/.test(c)) return (48 + +c[6]) | 0x20000000;
  if (/^F([1-9]|1[0-2])$/.test(c)) return 0x01000030 + (+c.slice(1) - 1);
  return QT[c] ?? null;
}
function qtName(v) {
  if (v == null || v < 0) return "—";
  if (QT_NAMES[v]) return t(QT_NAMES[v]);
  if ((v & 0x20000000) && (v & 0x0F000000) === 0x01000000 && QT_NAMES[v & ~0x20000000]) return t(QT_NAMES[v & ~0x20000000]);   // macOS: Pfeile mit Keypad-Bit
  if (v >= 0x01000030 && v <= 0x0100003B) return "F" + (v - 0x01000030 + 1);
  if (v & 0x20000000) return "Num " + String.fromCharCode(v & 0xFFFF);
  if ((v >= 32 && v < 127) || (v >= 0xA0 && v < 0x250)) return String.fromCharCode(v);
  return "#" + v;
}
const DS_ICON = { A: "", B: "", X: "", Y: "", L: "sq", R: "sq", Start: "wide", Select: "wide", Up: "sq", Down: "sq", Left: "sq", Right: "sq" };
const DS_LBL = { Up: "↑", Down: "↓", Left: "←", Right: "→", Start: "START", Select: "SELECT" };
let B = null, waiting = null;

function bindRow(k, val, kind, hot) {
  const icon = hot ? `<span class="ds wide" style="font-size:10px">HK</span>` :
    `<span class="ds ${DS_ICON[k]}">${DS_LBL[k] || k}</span>`;
  const name = hot ? t("hk_" + k) : t("key_" + k);
  const lbl = kind === "kb" ? qtName(val) : (B.joy_labels[k] || "—");
  const unused = !hot && (k === "Y" || k === "Up");
  return `<div class="bind"><div class="k">${icon}<span class="${unused ? "unused" : ""}">${esc(name)}</span></div>
    <div class="key ${val < 0 ? "none" : ""}" data-k="${k}" data-kind="${kind}">${esc(lbl)}</div></div>`;
}
function renderBinds() {
  const keys = [...B.keys, ...B.hotkeys];
  $("#kbBinds").innerHTML = keys.map(k => bindRow(k, B.keyboard[k], "kb", !B.keys.includes(k))).join("");
  $("#padBinds").innerHTML = keys.map(k => bindRow(k, B.joystick[k], "pad", !B.keys.includes(k))).join("");
  $$(".key").forEach(el => {
    el.onclick = () => startCapture(el);
    el.oncontextmenu = async e => {
      e.preventDefault();
      if (el.dataset.kind === "kb") { await api.set_key(el.dataset.k, -1); B.keyboard[el.dataset.k] = -1; }
      else { B.joy_labels[el.dataset.k] = await api.set_joy(el.dataset.k, -1); B.joystick[el.dataset.k] = -1; }
      renderBinds();
    };
  });
}
async function startCapture(el) {
  if (waiting) return;
  waiting = el; el.classList.add("wait");
  if (el.dataset.kind === "kb") { el.textContent = t("kb_press"); return; }
  if (!ST.pad) { toast(t("pad_missing"), true); return stopCapture(); }
  el.textContent = t("pad_press");
  const r = await api.capture_pad(+$("#padSel").value || 0);
  if (r.value >= 0 || r.value < -1) {
    B.joystick[el.dataset.k] = r.value; B.joy_labels[el.dataset.k] = await api.set_joy(el.dataset.k, r.value);
    if (r.pad != null && +$("#padSel").value !== r.pad) { $("#padSel").value = r.pad; B.joystick_id = r.pad; }
  }
  else toast(t("pad_noinput"));
  stopCapture();
}
function stopCapture() { waiting = null; renderBinds(); }
document.addEventListener("keydown", async e => {
  if (!waiting || waiting.dataset.kind !== "kb") return;
  e.preventDefault();
  if (e.code === "Escape") return stopCapture();
  const v = qtFromEvent(e);
  if (v == null) { toast(t("kb_unsupported")); return; }
  B.keyboard[waiting.dataset.k] = v; await api.set_key(waiting.dataset.k, v); stopCapture();
});
$("#btnResetKeys").onclick = async () => { B = await api.reset_keys(); renderBinds(); toast(t("kb_default_done")); };

async function loadSettings() {
  B = await api.get_bindings();
  const sel = $("#padSel");
  sel.innerHTML = B.pads.length ? B.pads.map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join("") : `<option value="0">${esc(t("pad_none"))}</option>`;
  sel.value = B.joystick_id;
  sel.onchange = () => api.set_joystick_id(+sel.value);
  ST.pad = B.pad_ok; ST.pad_error = B.pad_error;
  if (!ST.pad) msg($("#padHint"), t("pad_missing") + (ST.pad_error ? " (" + ST.pad_error + ")" : ""), "bad");
  else if (!B.pads.length) msg($("#padHint"), t("pad_plug"), "info");
  else $("#padHint").className = "msg";
  renderBinds();
  const d = await api.get_display();
  $("#gLayout").value = d.layout; $("#gSizing").value = d.sizing; $("#gSwap").checked = d.swap; $("#gInt").checked = d.integer;
  $("#gFilter").checked = d.filter; $("#gRend").value = d.renderer; $("#gScale").value = d.scale; $("#gFull").checked = d.fullscreen;
  gfxUi();
}
function gfxUi() {
  const gl = $("#gRend").value !== "0", sc = +$("#gScale").value;
  $("#gScale").disabled = !gl;
  $("#gScaleTxt").textContent = gl ? `${sc}× (${256 * sc}×${192 * sc})` : "1× (256×192)";
  $("#gScaleHint").style.display = gl ? "none" : "";
  $("#gGlWarn").style.display = gl ? "" : "none";
}
["#gLayout", "#gSizing", "#gSwap", "#gInt", "#gFilter", "#gRend", "#gScale", "#gFull"].forEach(id => $(id).onchange = async () => {
  gfxUi();
  await api.set_display({ layout: +$("#gLayout").value, sizing: +$("#gSizing").value, swap: $("#gSwap").checked, integer: $("#gInt").checked,
    filter: $("#gFilter").checked, gap: 0, renderer: +$("#gRend").value, scale: +$("#gScale").value, fullscreen: $("#gFull").checked });
  toast(t("saved"));
});
$("#gScale").oninput = gfxUi;

// ---------------- Profil ----------------
async function loadProfile() {
  const p = await api.profile();
  $("#profMac").textContent = p.mac;
  const inp = $("#driverName");
  inp.maxLength = p.name_max;
  if (document.activeElement !== inp) inp.value = p.driver || "";
  inp.oninput = () => { inp.value = inp.value.replace(/[^A-Za-z0-9]/g, "").slice(0, p.name_max); };
  if (p.error) msg($("#profErr"), p.error, "bad"); else $("#profErr").className = "msg";
  $("#btnDriver").onclick = async () => {
    const r = await api.set_driver_name(inp.value);
    toast(r.ok ? t("prof_saved") : r.msg, !r.ok); if (r.ok) loadDriver();
  };
  const s = p.summary;
  $("#stRaces").textContent = s.races; $("#stWins").textContent = s.wins;
  $("#stAvg").textContent = s.avg_place == null ? "–" : String(s.avg_place).replace(".", ST.lang === "de" ? "," : ".");
  $("#rivals").innerHTML = s.rivals.length ? s.rivals.map(r => `<div class="bind"><div class="k"><span class="ds">${esc(r.name[0] || "?")}</span>${esc(r.name)}</div>
      <span class="tag">${esc(t(r.placed ? "prof_ahead" : "prof_together", { a: r.ahead, r: r.races }))}</span></div>`).join("") : `<div class="empty">${esc(t("prof_norivals"))}</div>`;
  $("#histBox").innerHTML = p.history.length ? `<p class="muted small">${esc(t("hist_click"))}</p><table class="hist"><tr><th>${t("th_place")}</th><th>${t("th_rivals")}</th><th>${t("th_track")}</th><th>${t("th_time")}</th><th>${t("th_date")}</th></tr>${p.history.map((h, i) => {
      const me = (h.players || []).find(x => x.me) || {};
      return `<tr class="hrow" data-h="${i}"><td><span class="place p${h.place}">${h.place || "–"}</span></td>
      <td>${esc((h.players || []).filter(x => !x.me).map(x => x.name).join(", "))}</td>
      <td class="muted">${esc(trackName(h))}</td><td>${me.dnf ? esc(t("dnf")) : esc(fmtCs(me.time_cs))}</td><td class="muted">${esc(h.time)}</td></tr>
      <tr class="hdet" id="hdet${i}" hidden><td colspan="5">${raceDetail(h)}</td></tr>`; }).join("")}</table>`
    : `<div class="empty">${esc(t("prof_nohist"))}</div>`;
  $$("#histBox .hrow").forEach(el => el.onclick = () => {
    const d = $("#hdet" + el.dataset.h); d.hidden = !d.hidden; el.classList.toggle("open", !d.hidden);
  });
}
function fmtCs(cs) {
  if (cs == null) return "–";
  const m = Math.floor(cs / 6000), s = Math.floor(cs / 100) % 60, c = cs % 100;
  return `${m}:${String(s).padStart(2, "0")}.${String(c).padStart(2, "0")}`;
}
function trackName(h) {
  if (h.track == null) return "–";
  let n = (TRACKS[h.track] || t("track_n", { n: h.track }));
  if (h.variant != null && !NO_VARIANTS.has(h.track)) n += " " + (h.variant + 1);
  return h.laps ? `${n} · ${h.laps === 1 ? t("laps_1") : t("laps_n", { n: h.laps })}` : n;
}
// Strecken-Nummer aus der Lobby-Auswahl -> Ort. Die Varianten 1-3 einer Strecke haben dieselbe Nummer.
const TRACKS = { 0: "Autovia", 1: "Tailfin Pass", 2: "Radiator Springs Speedway", 3: "Motoropolis",
                 4: "Ornament Valley", 5: "Santa Carburera", 6: "Radiator Springs", 9: "Mine Shaft" };
const NO_VARIANTS = new Set([2, 9]);   // Speedway und Mine Shaft gibt es nur einmal
function raceDetail(h) {
  const ps = [...(h.players || [])].sort((a, b) => (a.place || 99) - (b.place || 99));
  return `<table class="det"><tr><th>${t("th_place")}</th><th>${t("th_driver")}</th><th>${t("th_time")}</th><th>${t("th_best")}</th><th>${t("th_laps")}</th></tr>${ps.map(x => `
    <tr class="${x.me ? "me" : ""}"><td><span class="place p${x.place}">${x.place || "–"}</span></td><td><b>${esc(x.name || "?")}</b></td>
    <td>${x.dnf ? esc(t("dnf")) : esc(fmtCs(x.time_cs))}</td><td class="muted">${x.dnf ? "–" : esc(fmtCs(x.best_cs))}</td>
    <td class="muted">${x.dnf ? "–" : (x.laps_cs || []).map(fmtCs).map(esc).join(" · ") || "–"}</td></tr>`).join("")}</table>`;
}
$("#btnUserDir").onclick = () => api.open_folder("user");

// ---------------- Start ----------------
async function setLang(l) {
  const v = await api.set_lang(l); applyLang(v); await refresh(); loadDriver();
  const p = $(".nav button.on"); if (p) p.click();
}
function langUi() {
  $("#langBtns").innerHTML = Object.entries(LANGS).map(([k, n]) => `<button class="btn ${k === "en" ? "primary" : ""}" data-l="${k}">${n}</button>`).join("");
  $$("#langBtns button").forEach(b => b.onclick = () => setLang(b.dataset.l));
  $("#langSel").innerHTML = Object.entries(LANGS).map(([k, n]) => `<option value="${k}">${n}</option>`).join("");
  $("#langSel").onchange = () => setLang($("#langSel").value);
}
// Alle Aufrufe an Python nacheinander statt gleichzeitig. Unter Windows (pywebview/.NET) kann sich das Fenster
// sonst gegenseitig blockieren, wenn ein Ergebnis zurückkommt, während schon der nächste Aufruf startet
// ("Programm reagiert nicht" beim Start, wenn viele Aufrufe auf einmal laufen).
function serialApi(raw) {
  let chain = Promise.resolve();
  return new Proxy({}, { get: (_, name) => (...args) => {
    const p = chain.then(() => raw[name](...args));
    chain = p.catch(() => {});
    return p;
  } });
}
async function boot() {
  api = location.hash.includes("mock") ? MOCK : serialApi(window.pywebview.api);
  langUi();
  const st = await api.state(); applyLang(st.lang || "en"); $("#langSel").value = LANG;
  await refresh(); loadDriver();
  setInterval(refresh, 4000);
}
// Fehler nie stillschweigend schlucken
window.addEventListener("unhandledrejection", e => toast(String(e.reason && (e.reason.message || e.reason)), true));
window.addEventListener("error", e => toast(String(e.message), true));
let booted = false;
function bootOnce() { if (!booted) { booted = true; boot(); } }
if (window.pywebview && window.pywebview.api && window.pywebview.api.state) bootOnce();
else window.addEventListener("pywebviewready", bootOnce);
// Vorschau im Browser (ohne Python): Beispieldaten
const MOCK = (() => {
  const P = { state: { version: "1.0.0-beta1", setup_done: !location.hash.includes("setup"), server: { name: "DESKTOP-NICO", address: "127.0.0.1", port: 27015 },
    lang: location.hash.includes("setup") ? "" : (location.hash.includes("de") ? "de" : "en"), auto_nav: true, unlock_all: true, intro_seen: !location.hash.includes("intro"), server_name: "DESKTOP-NICO", srv_online: !location.hash.includes("off"), srv_checked: true, srv_ping: 12, mac: "00:09:BF:4A:91:2C", melon: true, playing: false, hosting: location.hash.includes("host"), pad: true } };
  const keys = ["A", "B", "X", "Y", "L", "R", "Start", "Select", "Up", "Down", "Left", "Right"];
  const kb = { A: 88, B: 90, X: 83, Y: 65, L: 81, R: 87, Start: 0x01000004, Select: 0x01000003, Up: 0x01000013, Down: 0x01000015, Left: 0x01000012, Right: 0x01000014, HK_FullscreenToggle: 0x0100003A, HK_SwapScreens: 0x01000001 };
  const pl = (n, p, tm, me) => ({ name: n, place: p, me, time_cs: tm, best_cs: Math.round(tm / 3.2), laps_cs: [Math.round(tm / 3), Math.round(tm / 3.1), Math.round(tm / 2.9)], dnf: p === 4 });
  const hist = [
    { time: "2026-11-20 18:42", place: 1, track: 6, laps: 3, players: [pl("Nico", 1, 9238, true), pl("Max", 2, 9410), pl("Lea", 3, 9877), pl("Tom", 4, 1050109)] },
    { time: "2026-11-20 18:37", place: 3, track: 3, laps: 1, players: [pl("Max", 1, 10371), pl("Lea", 2, 10520), pl("Nico", 3, 10690, true)] },
    { time: "2026-11-20 18:31", place: 2, track: 6, laps: 3, players: [pl("Max", 1, 5400), pl("Nico", 2, 5502, true)] }];
  return {
    state: async () => P.state, pick_rom: async () => "F:/Spiele/cars.nds", setup_rom: async () => ({ ok: true, msg: "ROM erkannt: Cars - Race-O-Rama (Europe) (En,Es,It)" }),
    search_servers: async () => (await new Promise(r => setTimeout(r, 300)), { ok: true, tailscale: true, servers: [
      { name: "DESKTOP-NICO", ip: "127.0.0.1", local: true, device: "dieser PC", ping_ms: 2, mod: "R10", port: 27015, rooms: [{ players: 2, max: 4, open: true }] },
      { name: "Max-PC", ip: "100.92.38.1", local: false, device: "max-pc", ping_ms: 24, mod: "R10", port: 27015, rooms: [] }] }),
    select_server: async () => ({ ok: true }), host: async () => ({ ok: true, tailscale_ip: "100.110.179.120" }), stop_host: async () => ({ ok: true }),
    play: async () => ({ ok: true }),
    get_bindings: async () => ({ keyboard: kb, joystick: Object.fromEntries([...keys, "HK_FullscreenToggle", "HK_SwapScreens"].map((k, i) => [k, i < 6 ? i : -1])),
      joy_labels: Object.fromEntries([...keys, "HK_FullscreenToggle", "HK_SwapScreens"].map((k, i) => [k, i < 6 ? "Taste " + i : "—"])),
      joystick_id: 0, keys, hotkeys: ["HK_FullscreenToggle", "HK_SwapScreens"],
      pads: [{ id: 0, name: "Xbox Wireless Controller" }] }),
    set_key: async () => true, set_joy: async (k, v) => v < 0 ? "—" : "Taste " + v, set_joystick_id: async () => true, capture_pad: async () => ({ value: 3, label: "Taste 3", pad: 0 }),
    reset_keys: async () => MOCK.get_bindings(), get_display: async () => ({ layout: 0, sizing: 0, swap: false, integer: false, filter: true, renderer: 1, scale: 3, fullscreen: false }),
    set_display: async () => true,
    profile: async () => ({ driver: "Nico", profiles: [{ slot: 0, name: "gwt", used: true }, { slot: 2, name: "Nico", used: true, online: true }], mac: "00:09:BF:4A:91:2C", name_max: 9, history: hist,
      summary: { races: 3, wins: 1, podium: 3, avg_place: 2, rivals: [{ name: "Max", races: 4, ahead: 2 }, { name: "Lea", races: 4, ahead: 3 }, { name: "Tom", races: 2, ahead: 2 }] } }),
    set_name: async () => ({ ok: true }), set_driver_name: async () => ({ ok: true }), open_folder: async () => true, set_lang: async l => (P.state.lang = l, l), set_auto_nav: async v => v, set_unlock_all: async v => v, set_intro_seen: async () => true,
  };
})();
if (location.hash.includes("mock")) setTimeout(bootOnce, 50);   // Vorschau im Browser: index.html#mock
