---
name: stream-open1602
description: Operate a live stream or recording of an Open1602 game played by agents - OBS scenes, what the stream may show, sound, game settings for viewers, ending a session. Use whenever a game is streamed or recorded, OBS is started or changed, a stream is restarted, or a streamed session is ended. Not needed to play (play-open1602).
---

# Streaming an Open1602 game

## What the stream may show (user rule, top priority)

The stream may show only the Open1602 game windows and the tournament statistics panel. Never
anything else: no other application, no taskbar, no desktop. A monitor capture once showed the
taskbar and the recording had to be deleted.

- Never use a monitor or display capture in OBS.
- Use one `window_capture` per game window (`open1602.exe`, the player's name in the title), plus a
  browser or text source for the panel (`tools/agent/turnier/stats/`).
- Before every stream start, take a shot of the scene (`obsctl.py shot`) and look at it. When in
  doubt, do not stream.

## Setup

The stream tools live outside the repository on the operator's computer (`D:\anno\stream`: the OBS
scene generator, `status.ps1` for the status bar, `obsctl.py`); run them with that folder's
`.venv\Scripts\python.exe`.

- **Sound:** set `$env:O1602_AUDIO_DEVICE` to part of the name of an output nobody listens to
  (the stream captures it, the person at the computer hears nothing) before starting the game.
  Keep the music on: no `--no-music`.
- **Start for a stream:** `--load <save> --control 7602 --size 1600x900 --zoom 1 --no-videos`.
- **settings.cfg** is set for the stream; leave it so: `effects = off` (music only), `speech = 0`
  (no voice warnings), `video = 0` (no message videos), `display.event_speed = keep` (events do
  not slow the game).
- **While streaming** keep the game running at x8: `resume` once, `speed 8`. `advance` leaves a
  running game running.
- **Camera:** by default it jumps to every build, road, demolition and ship order of the agent, so
  viewers see each action. `camera ISLAND X Y` looks somewhere on purpose, `camera follow off`
  stops the jumping, and the person watching can hold the camera with Ctrl+Shift+C.
- **What the agent is doing:** `plan "A | B | C"` and `say "..."` show over the map
  (Ctrl+Shift+P cycles the box). ASCII only: the game's font has no umlauts.

## Ending a session

1. Stop the driver: Ctrl-C in its terminal tab.
2. `pause`, then `save NAME` (a new name; the file goes to `%APPDATA%\Open1602\saves\`).
3. Stop the stream and the recording through obs-websocket (`StopStream`, `StopRecord`): port 4455,
   the password is in `%APPDATA%\obs-studio\plugin_config\obs-websocket\config.json`; protocol v5
   (Hello, Identify with the SHA-256 auth, Request). Recordings land in the folder `RecFilePath`
   of the OBS profile (`basic.ini`).
4. Close the game window (`CloseMainWindow` on `open1602`).
5. Cancel the periodic review job (`CronList`, `CronDelete`).
