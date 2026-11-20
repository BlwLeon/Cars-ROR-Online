# Cars Race-O-Rama (EU, B6OP) – RE-Notizen

ARM9: BLZ-komprimiert, entpackt 933432 Bytes, Basis 0x02000000. Overlays: 15.
Multiplayer: nur Single-Card / Download Play, Clone Boot (RSA-signiert), Child lädt Daten per WFS.

## WM-Wrapper (Nintendo SDK)
- 0x020A2198  WM_SetLifeTime(cb, table, cam, frame, mp)
- 0x020A0514  WM_SetPortCallback(port, cb, arg)
- 0x020A1370  WM_SetMPDataToPort(cb, data, size, destBitmap, port, prio)

## Spiel-Netzwerkschicht (DSWifi_* Klassen)
- 0x0202D1A4  SetLifeTime-Aufruf (frameLifeTime=5 hart, cam/mp aus Config [obj+0x44]+2)
              aufgerufen von Parent-Start 0x0202A2B4 und Child-Start 0x0202A4F4
- 0x02032D?? Port::Open   -> WM_SetPortCallback(port=[this+6], 0x02032EC8, this)
- 0x02032DEC Port::Send(this, data, size, ?)  -> WM_SetMPDataToPort, destBitmap = [this+8] & connected
- 0x02032EC8 / 0x02032EF8 Port::Callback
     state 21 (PORT_RECV): listener->vtbl[1](listener, {port, srcAid, length, dataPtr})
     state 7  (CONNECTED):    [this+8] |= 1<<aid
     state 9  (DISCONNECTED): [this+8] &= ~(1<<aid)
- Port-Objekt: +4 id, +6 WM-Port, +8 verbundene AIDs, +0xA open-flag, +0x1C listener
- Globals: 0x020E229C (Port-Bitmap), 0x020E2254 (Wifi-Manager)

## Menü-States (WifiLobbyMenuTask)
RootMenu, ConnectionLobby, GameLobby, WaitingToStartGame, TrackSelectHost/Client, CarSelect, StartingLevel, ...

## Toolchain
Container: clang-18 --target=armv5te-none-eabi + ld.lld + llvm-objdump (reicht für Patches in C/ASM).

## WM-Befehle (ARM9 -> ARM7)
- 0x0209FE84 WMi_SendCommand(apiId, nArgs, ...)   0x0209FE14 WMi_SetCallback(apiId, cb)
- Im Spiel gelinkt: API 0,1,2,7,8,11,13,15,16,24,25,29,33
- DCF/Infrastruktur (17 START_DCF, 18 SET_DCF_DATA, 19 END_DCF) sind NICHT gelinkt, ARM7-Seite muss geprüft werden
  -> eigene Wrapper über WMi_SendCommand möglich (Milestone 0)

## Milestone 0 (Infrastruktur-WLAN)
ARM9 SDK: NitroSDK 4.2 (0x04027536). Modparams 0x02000B64, Autoload-Liste am Ende, Main-Arena-Lo Literal 0x0209C560 (=0x021147E0).
WM ARM9: WM_Initialize 0x020A0A94(sysbuf[0xF00,align32], cb, dma) | WM_Init 0x0209FB94 | WM_StartScan 0x020A0D14(cb, {scanBuf,u16 ch,u16 time,u8 bssid[6]})
         WM_EndScan 0x020A0E00 | WM_StartConnectEx 0x020A0E40(cb, bss, ssid24, powerSave, authMode) | OS_GetMacAddress 0x0209CBE4
Callback-Struct (Scan/Connect): +0 api, +2 err, +8 state (4=nicht gefunden, 5=gefunden, 6=connect start, 7=verbunden, 8=beacon lost, 9=getrennt), +10 aid
WMBssDesc: +4 bssid, +10 ssidLen, +12 ssid[32], +44 capaInfo (bit0 ESS, bit4 WEP), +64 gameInfo
ARM7 WM-Befehlstabelle 0x027F7184 (ARM7-Code autoload 0x027E0000). DCF vorhanden:
  17 START_DCF  args: recvBuf, halfSize (Doppelpuffer, 2x halfSize). CB: [4]=14 Start, [4]=15 Empfang, [8]=Puffer
  18 SET_DCF_DATA args: mac[0..3], mac[4..5], data, size. CB err [2]
  19 END_DCF
Pad::Update 0x02019740 (vtable 0x020BB728) ruft PAD_Read 0x02019754 -> Hook-Stelle 0x02019748

## M0 ERFOLGREICH (v3, 19.11.2026)
- WM_StartScan (API 10) findet nur DS-Parents -> fuer APs WM_StartScanEx (API 38) per WMi_SendCommandDirect 0x0209FF30, Req 56 Byte:
  +2 channelList(bit0=ch1) +4 scanBuf +8 bufSize(>=64) +10 maxChTime +12 bssid +18 scanType +20 ssidLen +22 ssid[32] +54 matchLen
  Ergebnis: gepackte WMBssDesc, Laenge [+0] in Halbworten. melonAP: 00:F0:77:77:77:77, SSID "melonAP", Kanal 6.
- DCF-Rahmen: Nutzdaten = LLC/SNAP(AA AA 03 00 00 00) + Ethertype + Payload; ARM7 setzt ToDS selbst (Template 0x0108).
- DCF-Empfangspuffer: 12 B RX-Header, 802.11-Header ab +12, SNAP ab +36.
- melonDS-slirp-Netz: 10.64.0.0/24, Gateway/Host-PC 10.64.0.1 (MAC 52:55:0a:40:00:01), DHCP ab 10.64.0.16, DNS 10.64.0.2.
- Ergebnis: ARP ok, UDP Hallo/Pong zum Server ok, Ping lokal 1 Frame.

## M1a: Mitschnitt Port-Schicht (lokales 1v1, Host)
- Download Play mit Header-Restore (0x027FFE00: arm9 off/size, romsize, crc) funktioniert, Child verbindet (AID 1).
- Ports: 4/12 Verbindungsaufbau, 5 = Lobby-Status vom Host jede Frame (03 09 xx 00 03 yy), 13 = Lobby/Ereignisse,
  14 = DSWifi_MPComms (Paket-/Blocktransfer-Lib 0x020A9EF0.., vermutlich WFS-Dateistreaming fuer Download-Play-Child).
- Port 13 Nachrichten: 09 xx Keepalive (alle 10 Frames), 0a xx, 04 Lobby-Wahl, 05 Bestaetigung, 14 Start, 0c Rennstart (Seed?),
  0d 01/02/03 Rundenereignisse, 0e Ergebnisse (Zeiten), 0f Ende.
- ECHTZEIT-RENNDATEN laufen NICHT ueber die Port-Schicht, sondern ueber **WM Data Sharing** (Lockstep):
  Wrapper-Klasse 0x0202DC..0x0202E2E8, WM_StartDataSharing 0x020A1510 (Aufruf 0x0202DE7C),
  WM_StepDataSharing 0x020A17AC (Aufruf 0x0202E230 jede Frame).
  -> Ziel fuer Online-Netcode: Data Sharing durch Server-Lockstep mit Eingabeverzoegerung ersetzen.
- Nach Rennende: Child stuerzte ab / Host haengt im Ladebildschirm (Ursache offen).

## M1b: WM Data Sharing im Rennen (lokales 1v1, Host)
- WM_StartDataSharing: port 14, aidBitmap 0xF (4 Spieler-Slots), dataLength 20, doubleMode 0. 1866 Steps, alle ret 0 (lokal nie Wartezeit).
- Empfangssatz: [u16 aidBitmap][u16 receivedBitmap][Block aid0 20B][Block aid1 20B]...; eigener Block erscheint 1 Frame verzoegert.
- 20-Byte-Block = KOMPRIMIERTER FAHRZEUGZUSTAND des eigenen Autos (keine reinen Tasten):
  u16 [0]: niedrige Bits Zaehler + Flags | u16 [2] | u32 [4] (langsam veraenderlich, Position/Ausrichtung?) |
  u32 [8] (Flags 0x0e.. beim Fahren) | u32 [12] (steigt monoton waehrend der Fahrt -> Streckenfortschritt?) | u32 [16] (stark veraenderlich).
  -> Jede Konsole simuliert ihr eigenes Auto, die anderen werden aus den Bloecken dargestellt.
  -> Online kann StepDataSharing NICHT-blockierend ersetzt werden: immer "Erfolg" mit dem neuesten bekannten Block der Gegner.

## M2a: Ablaufsteuerung (statisch)
- WM-API im Spiel: 0x020A0B04 WM_Reset(1), 0x020A0B3C WM_End(2), 0x020A0B7C WM_SetParentParameter(7), 0x020A0D04 WM_StartParent,
  0x020A0D14 WM_StartScan(10), 0x020A0E00 WM_EndScan(11), 0x020A0E40 WM_StartConnectEx(12), 0x020A1208 WM_StartMP, 0x020A12E4 WM_SetMPFrequency,
  0x020A1328 (MP-Param), 0x020A1370 WM_SetMPDataToPort, 0x020A0514 WM_SetPortCallback, 0x020A1510/17AC/1764 DataSharing Start/Step/End,
  0x020A200C WM_GetSharedDataAddress, 0x020A2090 WM_SetGameInfo(24), 0x020A21F8 WM_MeasureChannel(30), 0x020A2270 WM_SetEntry(33), 0x020A2198 WM_SetLifeTime(29)
- MB-Lib (Download Play Host): 0x020A69F8 MB_Init, 0x020A6C4C MB_SetParentCommParam, 0x020A6F9C MB_StartParentFromIdle, 0x020A35C0 MB_ReadSegment, 0x020A3AB0 MB_RegisterFile
- Wifi-Manager (Mgr): BeginScan 0x02029458, BeginChild 0x02029544, BeginParent 0x02029684, ToggleGameEntry 0x02029770, FinaliseGroup 0x020297E4,
  BeginMBParent 0x02029858, BeginMBChild 0x02029990 (prueft 0x027FFC40==2 = MB-Boot), EndWifi 0x02029C38
- Statische Einstiege fuer die UI (TGWifi): BeginScan 0x0202E77C, BeginChild 0x0202E798, BeginParent 0x0202E7B4, BeginMBParent 0x0202E804, BeginMBChild 0x0202E820, EndWifi 0x0202E8E0
- UI (WifiLobbyMenuTask, 0x0204A8xx-0x0204ADxx) ruft BeginScan, BeginChild UND BeginParent auf -> normaler Mehrkarten-Modus (Host/Join ohne Download Play) scheint im Code vorhanden.

## M2b: WM-Trace Multi-Card (Host + Client) -> Ablauf
Host: Initialize -> SetLifeTime -> MeasureChannel(1,7,13) -> MP-Param(api35 @0x020A1328) -> SetParentParameter -> StartParent(cb state0, BEACON_SENT state2 ...)
      -> SetPortCallback(5,13,4,12) -> StartMP(cb state 10) -> [Child verbindet: Parent-cb state 7 {mac@10, aid@16, ssid24@20}] -> SetGameInfo/SetEntry -> Port-Nachrichten -> DataSharing
Client: Initialize -> StartScan(1/7/13; cb state 4/5, bss in scanBuf) -> EndScan -> SetLifeTime -> StartConnectEx(cb state 6, dann 7 {aid@10})
      -> SetPortCallback x4 -> StartMP -> Port-Nachrichten -> DataSharing
WMParentParam: ug ptr@0, uglen@4, ggid@8, tgid@12, entry@14, maxEntry@16, beaconPeriod@24, channel@50, parentMax@52, childMax@54
WMBssDesc (echt): len 0x35, rssi 0x80, capa 0x21, rate 3/3, beacon 0xD1, dtim 2, gameInfoLength 16+uglen, gameInfo{1,1,0,ggid,tgid,uglen,attr,pmax,cmax,ug}
Port-Callback-Struct: 0x82,err,state@4,port@6,recvBuf@8,data@12,len@16,aid@18,mac@20,seq@26,arg@28,myAid@32,connBm@34 (PORT_INIT state 25)
MP-Callback: state @4 (10 = MP_START). Sende-Bestaetigung (0x2033008): port@10,dest@12,rest@14,sent@16,data@20,arg@32
GetSharedDataAddress: Offset = popcount(aidBitmap & ((1<<aid)-1)) * [info+0x810]

## M2c: Virtuelle WLAN-Schicht (mod/online)
- Alle oben genannten WM-Funktionen durch vwm.c ersetzt (Einsprung-Patch), DataSharing an den Aufrufstellen 0x0202DE7C/E230/DF74.
- Transport (net.c): echtes WM im Infrastrukturmodus (DCF) -> UDP -> server.py. Zuverlaessiger Kanal (Seq/Ack, Wiederholung 12 Frames).
- Server: Raeume (Host aid0 + bis 3 Clients), LIST/JOIN/PORT/DS-Weiterleitung.

## M2d/e (19.11.)
- M2d: eigene IP/Port je DS aus MAC (melonDS-Instanzen teilen sich ein slirp-Netz) -> Lobby + Rennen ueber Server funktionieren!
- Problem: Client startete 2 s vor Host. M2e: begrenzter Vorlauf im Data Sharing (Schrittnummer je Block, max. Ping+4 Schritte Vorsprung).

## R1 (20.11.): Robustheit
- RX-Ring 32. Data Sharing: Wartezeit auf haengende Spieler max. 2 s (in den ersten 600 Schritten unbegrenzt fuer synchronen Start),
  danach wird der Spieler uebersprungen (ds_skip) und beim naechsten Paket neu ausgerichtet (ds_off).
- Verbindungsverlust (8 s ohne Server-Paket, WLAN weg, Server-RESET): dem Spiel Trennung aller Mitspieler melden, Protokoll zuruecksetzen, Neuanmeldung (HELLO mit Sitzungs-Nonce).
- Server: Timeout 8 s, RESET (Typ 5) bei unbekannter ID, Adresswechsel per ID, Sitzungswechsel per Nonce, Simulator --lag/--jitter/--loss.
- R2: Lag-Test (150 ms, 5 % Verlust) -> Communication Error: zuverlaessige Warteschlange voll (Port 5 sendet jeden Frame).
  Fix: Protokoll v2 (Kopf 10 B mit SACK-Bitmaske), Zwischenspeicher fuer vorzeitige Nachrichten (DS 16, Server unbegrenzt),
  Port 5 unzuverlaessig mit Reihenfolgenummer (M_PORT_U=27), Wiederholzeit = 1,5 x Ping + Reserve, REL_N 48.
- R3: Startversatz 0,3-0,5 s bei Lag (Host frueher): Ursache asymmetrische Verzoegerung (eigener Block nach 1 Frame, fremde nach Netzlaufzeit).
  Fix: symmetrischer verzoegerter Lockstep: Schritt N verarbeitet Bloecke ALLER Spieler aus N-D (D = max Ping + 3, waechst nur),
  Verlauf 64 Schritte, jedes Paket enthaelt die letzten 4 eigenen Bloecke (Redundanz). Ausfall-Logik (2 s, Start 10 s) bleibt.
  Simulation (/tmp/dssim.py): Startversatz 0-3 Frames, Desync max 4 Frames bei 150 ms/5 % Verlust.
- R4: Host wird nach Senden der Startnachricht 0x0C (Port 13) um (Ping_Host+Ping_Client)/2+2 Frames angehalten (DS-Schritte + Sendebestaetigung), damit beide Countdowns gleichzeitig laufen. Test A: letzter Client verlaesst Lobby -> Host 'alle Spieler weg' = Originalverhalten (AllPlayersLeftLostParent).
- Test A (3 Instanzen) bestanden: Client 2 geht -> verschwindet, Rest faehrt weiter; letzter Client geht -> Lobby zu (Original).
- R5: Startversatz-Ursache = Sync-Zaehler des Wifi-Managers ([mgr+0xA8], +1 pro Frame in 0x02028F70, aufgerufen aus TGWifi-Update 0x0202ED44).
  Host sendet Port 4 Typ 0x05 {u32 Zaehler} (Sender 0x0202CF20), Client uebernimmt (0x0202C9F0). 0x0C (Port 13) = Rennstart bei Zaehlerstand?
  Fix: Client addiert beim Empfang (Ping_eigen + Ping_Sender)/2 + 1 Frames; Server schreibt Ping des Absenders in Byte 4 der PORT-Nachricht.
  R4-Halt (ds_hold) deaktiviert.
- Test B ok (Host geht -> Clients Communication Error = Original). Test C (5 s Pause) mit R5: beide haengen dauerhaft -> 2-s-Ueberspringen war falsch
  (Spieler faellt aus dem Verlaufsfenster, Spiel bekommt inkonsistente Zeiten). R6: wieder unbegrenzt warten wie Original-Lockstep, Ausfall regelt Server-Timeout (8 s).
- R5 sync_fix war nur 1 Frame: Ping beim Beitreten noch nicht gemessen. R6: Ping alle 15 Frames.
- R6 Tests: Start synchron (sync_fix=8) -> Rennstart haengt am Sync-Zaehler, Fix bestaetigt. Test C (Pause) ok, Test D (Instanz schliessen) ok, Test E ok.
- R7: RESET traegt die betroffene ID, DS ignoriert verspaetete RESETs alter Sitzungen (vorher 11-13 Verbindungsverluste beim Server-Neustart).

## R8 (Test G: 2. Grand-Prix-Rennen desynchron)
- Ursache: Server meldete PEER_JOIN nur an den Host -> Clients hatten conn_bm = Host+selbst und
  gaben die Blöcke des anderen Clients nie an das Spiel weiter (echtes WM liefert allen alle aids).
- Fix: Server schickt PEER_JOIN auch zwischen Clients; Client setzt nur conn_bm/peer_mac (keine parent_cb).
- Zusätzlich: DS-Vorpuffer (ds_pre, PREH=48) für Blöcke des nächsten Rennens, die vor dem eigenen
  StartDataSharing ankommen; wird in StartDS übernommen. Debugfeld g_v.ds_pre.
- Test G mit 3 Instanzen, 2 Rennen: OK. ds_rx ~ 2x ds_tx auf allen, lost=0.

## R9 (weniger Versatz)
- ds_D = max(Ping aller, Frames) + 1 statt + 3, Minimum 3. Adaptiv: 3 kurze Wartephasen (1–8 Frames)
  innerhalb von 120 Schritten -> D + 1 (g_v.ds_grow). Lange Wartephasen (Pause/Hänger) zählen nicht,
  die ersten 120 Schritte (Einpendeln) auch nicht. Bei 17–33 ms Ping: D 5 -> 3 Frames.

## R10 (Hänger bei Paketverlust)
- R9-Lagtest (150 ms, 5 % Verlust): Verklemmung. Client 2 bei Schritt 751 wartete auf Block 742 der anderen,
  alle 4 redundanten Kopien verloren -> nie wieder gesendet (Fehler bestand schon seit R3, R9 nur Zufall).
- Fix: DS-Paket Byte 5 = Anzahl Nachlieferblöcke rn, danach u16 Startschritt + rn Blöcke (aufsteigend).
  Sender liefert ab min(peer_seq - D - 4) bis seq-4 nach (max 8 Blöcke). unrel-Puffer 256 -> 512.
  Simulation (3 Konsolen, 10 % Verlust, 3–6 Frames Laufzeit, 40 Rennen): ohne 9/40 ok, mit 40/40.

## Menü-Automatik + Single-Card-Knopf (qol.c)
- Menüs: UI/HUD/**/*.ui.bxml (RBHF-Container, PACK-komprimiert). Knöpfe werden per Name gebunden:
  btn = Bind(root, name, &task->slot, typ, 0,0,0) – Hauptmenü 0x02057598, Lobby 0x0204E43C (gleiche Funktion).
  Element suchen: 0x02042114(root, name). Knopf: +0 Grafikknoten, +8 Label (Knoten +0x4C), +0xC Callback-Objekt,
  +0x41 markiert, +0x42 aktiv, +0x43 anwählbar (0x0203D290 setzt +0x43). Drücken (0x0203D1DC): cb->vtable[0](cb).
- Knoten: +4 Zeichenliste (Unlink 0x020053F8), +0x20 Bit6 = eingehängt; 0x02020A8C setzt Ebene (+0xC).
- MenuTask-Zustände: 8 PressStart (Bind 0x02057260), 0 ProfileSelect (Profil1/2/3: 0x02056C80/CA8/CD0),
  9 MainMenu (MPButton 0x0205659C). WifiLobbyMenuTask RootMenu: MultiCardHost 0x0204DBC8, Join 0x0204DBEC,
  SingleCardHost 0x0204DC10 (wird ausgeblendet).
- CRNETCFG +56 auto_mode (0 aus, 1 MP-Menü, 2 Host, 3 Join), +57 auto_profile (0xFF = keins). Debug "CRQOLDBG".

## Freischaltungen / Spielstand-Profil (0x9C Byte, im RAM: Spielobjekt 0x0203E738() + 0x0C + i*0x9C, aktiv: +0x31C)
- +0x00 0x12345678, +0x04 u16 0x01A7, +0x06+i Medaille Story-Ereignis i (21; 1 Gold/6P, 2 Silber/4P, 3 Bronze/2P)
- +0x1B+g*3+e Postkarten-Aufgaben (4x2 Bit, 3 = erfüllt; Gruppen-Größen 0x020B79B4: 2,3,1,2,3,3,3)
- +0x30/+0x34/+0x38/+0x3C Ereignis-Bits je Typ (Overlay 0 ab 0x0210B3AC), +0x40 Bonus-Bits, +0x44 17 Bits,
  +0x48 POP-Bits (17*6), +0x55 Zähler, +0x78 Name UTF-16, +0x90/+0x94 Bitfelder, +0x99 Schwierigkeit
- IsUnlocked(item) 0x02038F28: Tabelle 0x020B75B8 {Mindestpunkte, Bonus-Bits, Bedingung}; Bedingungen 0x020B798C.
  Lobby fragt über 0x0203F278 ab (0x02050B08/E20/FB0).
- Launcher: Online-Profil auf Platz 3 mit allem freigeschaltet (save.ensure_online_profile).
