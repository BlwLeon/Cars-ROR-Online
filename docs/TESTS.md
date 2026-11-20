# Testszenarien Robustheit (Version R1)

Alle Tests lokal mit zwei melonDS-Instanzen. Host = Instanz 1, Client = Instanz 2.
Nach jedem Test kurz notieren: OK / was ist passiert. Bei Auffälligkeiten Savestate
(Host Shift+F1, Client Shift+F2) und Server-Fenster kopieren.

| Nr | Server starten mit | Szenario | Erwartung |
|----|-------------------|----------|-----------|
| A | Server_starten.bat | Client tritt bei, geht in der Lobby wieder raus (zurück/B) | Host sieht Spieler verschwinden, kann weiter hosten; Client kann erneut beitreten |
| B | Server_starten.bat | Host verlässt die Lobby, während der Client drin ist | Client bekommt Verbindungsfehler/zurück ins Menü, kein Hänger |
| C | Server_starten.bat | Im Rennen Client ca. 5 s pausieren (melonDS Pause) | Host stockt höchstens ~2 s und fährt dann weiter (Client-Auto steht); nach dem Fortsetzen fahren beide normal |
| D | Server_starten.bat | Im Rennen Client-Instanz komplett schließen | Host fährt nach ~2 s weiter, nach ~8 s meldet das Spiel den Spieler als getrennt (wie reagiert das Spiel?) |
| E | Server_starten.bat | Während der Lobby den Server-Fenster schließen und neu starten | Beide bekommen nach ~8 s eine Trennung; danach neu hosten/beitreten möglich |
| F | Server_starten_LAG_TEST.bat | Normales Rennen mit simuliert schlechter Verbindung | Synchroner Start, eigenes Auto flüssig, Gegner evtl. etwas ruckelig, keine Abbrüche |
| G | Server_starten.bat | Grand Prix / mehrere Rennen hintereinander | Jedes Rennen startet synchron, keine Hänger zwischen den Rennen |

Hinweis zu D/E: Was das SPIEL dann anzeigt (Fehlermeldung, zurück ins Menü, ...), entscheidet das Spiel selbst –
genau das wollen wir herausfinden.
