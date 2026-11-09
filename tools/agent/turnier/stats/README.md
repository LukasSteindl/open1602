# Turnier-Stats: live scoreboard for the stream

One card per agent over its game window in the OBS scene `Live`: inhabitants, gold, balance per
minute, the tokens its language model has used so far (input with its cached share, output), and
how much that bought: inhabitants and gold per million tokens (input with cache + output).
For the operator only; the agents are not told about it.

| File | What |
|---|---|
| `stats_panel.py` | collector + web server on `http://127.0.0.1:7690/` (`/stats.json`, page `/`) |
| `panel.html` | the page OBS shows (transparent, 1920x1080) |
| `start_stats.ps1` | starts the collector in a PowerShell window of its own |
| `obs_panel.py` | puts the page into the scene `Live` as browser source `Turnier-Stats` (add / remove / shot) |

## Start

From a normal PowerShell (not the Terminal panel of the Claude desktop app, see below), with
`ANNO1602_DIR` set:

```powershell
.\tools\agent\turnier\stats\start_stats.ps1
D:\anno\stream\.venv\Scripts\python.exe -I tools\agent\turnier\stats\obs_panel.py add
```

The server answers only with `?key=…` (else 404), so an agent on this computer cannot simply fetch
the others' numbers. The key is made at the first start and kept in
`%USERPROFILE%\.open1602-turnier-stats-key` (outside the repository); the collector's window prints
the full URL, and `obs_panel.py` puts it into the browser source. A bar, not a wall: whoever reads
that file or the OBS scene still finds it.

`obs_panel.py add` creates the browser source on top of the game windows, under the `Titel` text,
muted (the page plays nothing; the stream's sound stays the single `Desktop-Audio`). Run it again
after changing the URL; `remove` takes it out; `shot OUT.png` is an image of the scene as streamed.
The window of `start_stats.ps1` can be closed at any time; the cards then dim and keep the last numbers.

Page options (append to the URL in the browser source, beside `key=`): `?layout=center` (the four cards as one
block in the middle), `?layout=list` (one below the other, for a browser window), `?x=10&y=368`
(position of each card inside its 960x540 window; default: bottom left of the map, above the game's
bottom bar, beside the player list), `?scale=1.2`.

## Where the numbers come from

- **Game** (every 15 s): only the referee's port 7601. The referee saves the running game as
  `turnier-stats.o1602` (about 50 ms, the game goes on) and `o1602-tool state FILE --scores` reads,
  per human player, the figures each player's own `state` shows: money, inhabitants, taxes, running
  costs, military, trade and the balance per minute (`sim::player_figures`, the same as the game's
  "Player status" panel). The file is deleted right after reading, so no agent finds the others'
  numbers in the savegame folder. The agents' ports 7602-7605 are never queried. No change to the
  game itself, so no restart: `--scores` is new in `o1602-tool` only.
- **Opus** (Claude, ClaudeJev): the Claude Code transcripts in
  `%USERPROFILE%\.claude\projects\*\<id>.jsonl` (plus `<id>\subagents\*.jsonl`), found by the
  session title "Turnier-Agent 1" / "Turnier-Agent 2" in `<id>\custom-title.json`. Every assistant
  message counts once (by message id). Input = `input_tokens + cache_creation_input_tokens +
  cache_read_input_tokens`, so it means the same as Codex's input; "Cache" is the cache-read share.
- **Sol** (Sol, SolJev): the Codex rollouts `%USERPROFILE%\.codex\sessions\**\rollout-*.jsonl` of
  the ChatGPT desktop app, per rollout the last cumulative `token_count` (`total_token_usage`;
  `input_tokens` already includes `cached_input_tokens`, `output_tokens` includes reasoning). A
  rollout belongs to Sol or SolJev by the agent folder it names most (`a3-sol` / `a4-sol-jev`; the
  `cwd` in its header is not the agent folder). Rollouts started before the Claude agents (minus
  10 minutes) are left out (`--since` to change that); a restarted Codex thread adds its own rollout.

A model without a readable log shows "n/a".

## Pitfalls

- The Terminal panel of the Claude desktop app runs in the app's package container: it sees a
  redirected `%APPDATA%` and never finds the referee's savegame ("the referee saved, but … is not
  there"). `start_stats.ps1` from any other shell works.
- `o1602-tool` must be the one with `--scores`: `cmake --build build\vcpkg --target o1602-tool`
  (only that target: building everything would relink the running `open1602.exe`).
