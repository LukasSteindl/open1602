# Turnier fortsetzen (Stand 2026-11-09, Spielzeit 1:54:33)

Spielstand: `%APPDATA%\Open1602\saves\Turnier-2026-11-09.o1602` (Kopie: `Turnier-2026-11-09-backup.o1602`),
gespeichert vom Schiedsrichter (Port 7601), das Spiel stand pausiert.

## Reihenfolge

1. Spielfenster laden (bleibt pausiert, bis alle drin sind):
   ```powershell
   .\tools\agent\turnier\start_turnier.ps1 -Load Turnier-2026-11-09
   ```
2. Jev-Treiber starten, je ein eigenes PowerShell-Fenster:
   ```powershell
   cd D:\anno\open1602\tools\agent\turnier\a2-claude-jev; .\run_jev.ps1 -Port 7603
   ```
   ```powershell
   cd D:\anno\open1602\tools\agent\turnier\a4-sol-jev; .\run_jev.ps1 -Port 7605
   ```
3. OBS starten; Szene `Live` (vier Fensteraufnahmen + `Titel` + `Turnier-Stats`). Nur Anno und das
   Stats-Panel im Stream, keine Bildschirmaufnahme.
4. Stats-Panel: `.\tools\agent\turnier\stats\start_stats.ps1` (aus normaler PowerShell), dann
   `D:\anno\stream\.venv\Scripts\python.exe -I tools\agent\turnier\stats\obs_panel.py add`.
5. Die vier Agenten mit den Texten unten weitermachen lassen.
6. Spiel starten: `bin\o1602-ctl.exe --port 7601 resume`, danach `bin\o1602-ctl.exe --port 7601 speed 2`.

## Texte für die Agenten

Am besten in derselben Session/demselben Chat wie gestern (der Verlauf ist dort). In einer neuen
Session zuerst den ursprünglichen Start-Text (Claude: wie gestern; Sol: `CHATGPT_PROMPTS.md`)
und direkt danach diesen Text.

### Agent 1 "Claude" (Port 7602)

```
Weiter im Turnier: Das Spiel ist aus dem Spielstand "Turnier-2026-11-09" geladen (Spielzeit 1:54:33) und steht pausiert, bis der Schiedsrichter startet. Lies zuerst deine notes.md in tools/agent/turnier/a1-claude/ und prüfe mit "state" und "alerts", ob alles so ist wie notiert. Es gelten unverändert die Regeln aus AGENT.md: nur --port 7602, schreiben nur in deinen Ordner, nichts von den anderen lesen, kein Pause/Tempo, Frieden halten. Spiele dann Runde um Runde (je ~15 Spielminuten, danach notes.md aktualisieren), ohne auf mich zu warten, bis ich "Stopp" sage. Chat auf Deutsch, kurz.
```

### Agent 2 "ClaudeJev" (Port 7603)

```
Weiter im Turnier: Das Spiel ist aus dem Spielstand "Turnier-2026-11-09" geladen (Spielzeit 1:54:33) und steht pausiert, bis der Schiedsrichter startet. Dein Jev-Treiber läuft wieder (run_jev.ps1 -Port 7603, Ausgabe in state/driver.log). Lies zuerst deine notes.md in tools/agent/turnier/a2-claude-jev/, prüfe mit "state" und in driver.log, ob alles so ist wie notiert. Es gelten unverändert die Regeln aus AGENT.md: nur --port 7603, schreiben nur in deinen Ordner, nichts von den anderen lesen, kein Pause/Tempo, Frieden halten. Coache Jev weiter alle ~10 Spielminuten, ohne auf mich zu warten, bis ich "Stopp" sage. Chat auf Deutsch, kurz.
```

### Agent 3 "Sol" (Port 7604, ChatGPT-App, Ordner a3-sol)

```
Weiter im Turnier: Das Spiel ist aus dem Spielstand "Turnier-2026-11-09" geladen (Spielzeit 1:54:33) und steht pausiert, bis der Schiedsrichter startet. Lies zuerst D:\anno\open1602\tools\agent\turnier\a3-sol\notes.md und prüfe mit "D:\anno\open1602\bin\o1602-ctl.exe --port 7604 state" und "alerts", ob alles so ist wie notiert. Es gelten unverändert die Regeln aus AGENT.md: nur --port 7604, schreiben nur in deinen Ordner, nichts von den anderen lesen, kein Pause/Tempo, Frieden halten. Spiele Runde um Runde (je ~15 Spielminuten, danach notes.md aktualisieren), ohne auf mich zu warten, bis ich "Stopp" sage. Chat auf Deutsch, kurz.
```

### Agent 4 "SolJev" (Port 7605, ChatGPT-App, Ordner a4-sol-jev)

```
Weiter im Turnier: Das Spiel ist aus dem Spielstand "Turnier-2026-11-09" geladen (Spielzeit 1:54:33) und steht pausiert, bis der Schiedsrichter startet. Dein Jev-Treiber läuft wieder (run_jev.ps1 -Port 7605, Ausgabe in state\driver.log). Lies zuerst D:\anno\open1602\tools\agent\turnier\a4-sol-jev\notes.md, prüfe mit "D:\anno\open1602\bin\o1602-ctl.exe --port 7605 state" und in driver.log, ob alles so ist wie notiert. Es gelten unverändert die Regeln aus AGENT.md: nur --port 7605, schreiben nur in deinen Ordner, nichts von den anderen lesen, kein Pause/Tempo, Frieden halten. Coache Jev weiter alle ~10 Spielminuten, ohne auf mich zu warten, bis ich "Stopp" sage. Chat auf Deutsch, kurz.
```

## Heute Abend stoppen (für Sol und SolJev in der ChatGPT-App)

```
Stopp: Das Turnier endet für heute, das Spiel ist pausiert, gespeichert und geschlossen. Gib keine Befehle mehr ans Spiel. Aktualisiere nur noch notes.md in deinem Ordner (Stand, Plan für morgen, offene Baustellen) und höre dann auf.
```
