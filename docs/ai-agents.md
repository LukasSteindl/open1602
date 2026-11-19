# Playing Open1602 with AI agents

This fork of [x4rd4s/open1602](https://github.com/x4rd4s/open1602) makes the game playable by AI
agents: a language model (Claude Code, ChatGPT, a small local model) plays a slot as a human player
would, by text commands and under the same rules. Two or four agents can play one multiplayer game
against each other, side by side on a stream; there each agent also sees only what the game shows
its player (see "Multiplayer for agents"). In a game alone the port hides nothing: it answers
about islands the player has not discovered yet.

Everything below is additional. Nothing changes for a person who plays without `--control`.

## Overview

```
 agent (LLM)  ──text──▶  o1602-ctl  ──TCP 127.0.0.1:PORT──▶  open1602 --control PORT
     ▲                                                          │
     └──────────────────── answer as text ◀─────────────────────┘
```

| Part | Where | What it does |
|---|---|---|
| Control port | `engine/app/src/control_server.*`, `control_commands.cpp` | The game listens for text commands and answers in text. |
| `o1602-ctl` | `tools/o1602-ctl/` | A command-line client: one command in, the answer out. |
| Watching aids | `engine/app/src/map_viewer.*`, key bindings | The camera follows the agent, an overlay shows its plan and steps, and autoplay is available. |
| Multiplayer for agents | `engine/app/src/multiplayer.cpp`, `control_commands.cpp` | Several agents share one game, fog of war applies, and they can chat. |
| Agent skills | `.claude/skills/` | Instructions for Claude Code: how to play through the port, and economic strategy. |
| Planner | `tools/planner/` | Expansion plan computed from the game's own balance data. |
| Jev driver | `tools/agent/jev_driver.py`, `strategy.py` | A small decision model plays turn by turn, and a coach LLM improves its rules. |
| Duel and tournament | `tools/agent/start_duel.ps1`, `tools/agent/turnier/` | Two or four agents in one game, with a referee and a live stats panel. |

## The control port

```powershell
bin\open1602.exe --new-game 1 --control 7602      # the game starts paused and listens on 127.0.0.1:7602
bin\o1602-ctl.exe --port 7602 help                # every command
bin\o1602-ctl.exe --port 7602 state               # time, money, balance, cities, ships
```

- **Protocol.** One TCP connection carries one line, the command. The answer comes back as text
  and then the connection closes. The port listens on `127.0.0.1` only. The game's own thread
  carries out the commands, once per frame. The network thread only passes lines in and answers
  out.
- **Same rules as a person.** Every order goes through the same path as the interface
  (`Simulation::execute` for the local player). It costs the same, and it is refused for the same
  reasons as a click would be.
- **Errors.** A command that fails answers `error: ...`, and `o1602-ctl` then exits with 1. A
  refused build names the reason and the tiles. A `batch` with a failed part starts with
  `error: N of M commands failed`.
- **Time.** With `--control` the game starts paused. `advance N` lets N seconds of game time pass
  and leaves the game as it was before, paused or running. It ends early at an urgent message
  (fire, plague, attack, eruption) unless `nostop` is given, and `advance N until ship ID` also
  ends when that ship has arrived. It answers after 100 s of real time at the latest, with a
  first line that says the wait was partial. `pause`, `resume` and `speed 1-8` work as in the game.
- **Messages.** The game's messages come with the `advance` answer, or from `events`; `state`
  says when new ones wait. Each has the text the game shows and the place it happened.
- **`o1602-ctl`** takes the port from `--port N`, else from `O1602_CONTROL_PORT`, else 7602. Exit
  code 0 means an answer, 1 an answer that starts with `error`, 2 that no game is listening, 3
  that no answer came within `--timeout SECONDS` (default 130). `batch CMD ; CMD ; ...` sends
  several commands in one connection; `o1602-ctl -` reads them from standard input instead, one
  per line (empty lines and `#` lines skipped), as one batch (`advance` cannot be part of it).

### Commands

`help` prints the full list with arguments. In groups:

| Group | Commands |
|---|---|
| Look | `state`, `islands [mine]`, `map`, `cities`, `ships`, `buildings`, `goods`, `production [ISLAND] [idle]`, `houses ISLAND [problems]`, `coverage`, `threats`, `units`, `screenshot` |
| Find places | `kontor-sites`, `find-site`, `sites` (scored by what the catchment holds), `house-sites` |
| Diagnose | `alerts` (most urgent first: money, fire, plague, short supply, then question marks with their likely cause, missing roads …), `economy ISLAND CITY` (per good: stock, need, trend, minutes until empty), `unconnected`, `events` |
| Build | `found`, `build`, `build NAME ISLAND auto` (best place, with a road), `build-many`, `road` (dirt or stone), `fix-roads`, `demolish` (a tile or a rectangle), `off`, `on` |
| Ships and trade | `ship-move` (to a tile or to a city's Kontor), `ship-stop`, `load`, `unload` (a good or `all`), `route` (trade routes), `trade` (Kontor offers), `explore` |
| Economy | `tax` |
| Military | `shipyard`, `recruit`, `arm`, `attack`, `release`, `units-go`, `units-attack`, `board`, `units-land` |
| Diplomacy | `diplomacy`, `tribute`, `gesture`, `chat` |
| Game | `advance`, `pause`, `resume`, `speed`, `save`, `autoplay` |
| For viewers | `camera`, `camera follow`, `camera hold`, `plan`, `say` |

Answers stay in an agent's context for the rest of its session, so the short forms pay: `alerts`
and `economy` first, `houses ISLAND problems` and `production ISLAND idle` instead of the full
lists, a part of the `map` instead of the whole island, and several commands as one batch.

`map ISLAND` draws the island as text, one character per tile. The legend is at the end of
`help`: `~` sea, `.` free land, `:` your land, `=` road, uppercase letters are your buildings,
lowercase letters other players'.

## Watching an agent play

These were added for a person or a stream watching the agent:

- **Camera follows.** By default the camera jumps to every building, road, demolition and ship
  order of the agent. The agent turns this off with `camera follow off`. The person watching takes
  over with **Ctrl+Shift+C** (`camera hold`), and the agent then no longer moves the camera.
- **Agent overlay.** `plan STEP | STEP | ...` shows the agent's plan over the map, and `say TEXT`
  shows what it is doing now (the last six lines stay). **Ctrl+Shift+P** cycles between the last
  action as one line, plan and steps, and nothing.
- **Autoplay.** `--autoplay` or **Ctrl+Shift+A** lets the built-in computer opponent play your own
  slot, and the same key gives it back. The agent can do the same with `autoplay on|off`. It only
  works in a game alone.
- **Sound for a stream.** `O1602_AUDIO_DEVICE=<part of a device name>` plays the game's sound on
  that output device, for example a virtual cable that OBS captures.

## Multiplayer for agents

Several games on one computer, each with its own control port, can play one multiplayer game. The
README has the walk-through ("Two agents against each other"). What differs from a game alone:

- **Player identity.** `O1602_PLAYER_ID` (16 hex digits) gives a second game on the same computer
  its own player ID for that run. Otherwise the host would take it for its own player coming back
  and give it the host's slot.
- **Orders in lockstep.** An order first runs on a copy of the game, which produces the usual
  answer. The order then goes to the session, so that every computer carries it out in the same
  tick. The answer waits until the shared game has done so (about 2.5 s of game time), so the next
  command already sees the result. A `batch` waits once for all its orders, so an agent should
  send the orders of one step together.
- **No cheating.** A player learns only what the game shows them. Islands that player has not
  discovered come without crops and cities, `map` and the site searches refuse them, and other
  players' cities come without their number of inhabitants.
- **Time belongs to everyone.** The game does not pause for an agent, and `advance N` only waits.
  With `O1602_CONTROL_NO_SPEED` set, a port refuses `pause`, `speed` and `autoplay` (used for the
  tournament agents).
- **Chat.** `chat TEXT` writes to every player, and the line appears in every window's chat box.
  `chat` alone returns what the others wrote. `state` mentions when there are new lines.

## Agent skills (Claude Code)

`.claude/skills/` holds the skills that Claude Code loads when asked to play:

- **`play-open1602`** covers how to play through the port with few commands and short answers:
  one round as look, decide, act and wait, the opening, the facts that cost agents whole rounds,
  ships and trade, and what differs in a multiplayer game.
- **`anno1602-strategy`** covers the economics: the first half hour, the mistakes every agent made
  in the tournament, island roles, build order and sizing per class up to aristocrats, how houses
  really rise, taxes, trade routes, money emergencies, defence and diplomacy, and how the computer
  opponents think. `reference.md` has the numbers.
- **`stream-open1602`** is for the operator of a stream: what it may show, OBS, sound, ending a
  session.

The rule the playing skills share: play only with what a human player can do and see.

A first measurement (2026-11-19, one run each, the same world, 30 minutes of game time, the same
build of the game): an agent with the reworked skills reached 240 inhabitants with 60 calls of
`o1602-ctl`; one with the skills as they were before reached 139 with 119 calls. What both runs
reported as missing went into the skills afterwards.

## Planner

`tools/planner/` computes an expansion path from the game's own balance data:

- `extract_game_data.py` reads `haeuser.cod` and `figuren.cod` of an installation (through
  `o1602-tool`) and writes `game_data.json`. That file holds production chains, needs per class,
  costs and running costs, and it cites the engine code each value comes from.
- `plan.py` turns that data into stages up to a target such as `--target merchants=100`. For each
  stage it lists the production buildings (the cheapest chain per good), the houses and public
  buildings, the building materials, and running costs against taxes, so the balance stays
  positive at every stage.

## The Jev driver: a small model with a coach

`tools/agent/jev_driver.py` plays continuously without a large model in the loop:

1. Every few seconds it reads the game through `o1602-ctl` and builds a short list of legal
   actions.
2. A small decision model picks the action that helps most. By default that is a local model
   through Ollama; with `--hosted` it is the hosted Jev API, which needs `TYPESAFE_API_KEY` in the
   environment and is capped by `--max-calls-per-min`.
3. The driver carries out the action and logs state, options, probabilities and result to
   `jev_log.jsonl`.
4. A coach (Claude Code, following `tools/agent/REVIEW.md`) reads the log every few minutes and
   changes the driver's rules: which actions are offered, how they are worded, and which are
   filtered out.

`strategy.py` turns the planner's stages into the gaps of the current stage. The driver offers a
building only while the plan still misses it, and it shows the stage and its gaps over the map.

The other scripts in `tools/agent/` (`embark.py`, `explore_all.py`, `arm_fleet.py`,
`wall_island.py`, …) are one-off helpers from playing sessions. The `*.log` files and
`reviews.md` / `critique.md` are records of those sessions, kept for reference.

## Duel and tournament

- **Duel.** `tools/agent/start_duel.ps1` starts two windows of one multiplayer game: a host at port
  7602 (for example the Jev driver) and a second player at port 7603 (for example Claude Code).
  `-Load NAME` continues a saved game.
- **Tournament.** `tools/agent/turnier/` runs a four-player game. A referee hosts at port 7601 on a
  slot nobody plays, and only the operator pauses, resumes and sets the speed there. Four agents
  join at ports 7602–7605: two Claude Code agents and two ChatGPT agents, each pair once on its own
  and once with a Jev driver. Their ports refuse pause and speed.
  - `setup_turnier.py` gives each agent its own folder from `AGENT_TEMPLATE.md`: rules, goal, fair
    play, its own copy of the skills, and notes.
  - `start_turnier.ps1` starts the five windows (`-Load NAME` continues a game), and `run_jev.ps1`
    starts a Jev driver again whenever its coach saves a change.
  - `CHATGPT_PROMPTS.md` holds the prompts for the ChatGPT agents, and `FORTSETZEN.md` describes how
    to continue a paused tournament.
  - `stats/` is a live scoreboard for the stream: inhabitants, gold, balance and tokens used per
    agent, as a browser source in OBS. `o1602-tool state GAME.o1602 --scores` gives the human players'
    figures from a saved game, one line each.
  - The goal is the most inhabitants when the referee ends the game, with money breaking a tie. An
    agent that goes bankrupt is out.
- **Self-tournament.** `tools/agent/selbstturnier-2026-11-19/` records a game of four Claude models
  against each other, each a subagent of one session with the same skills: after 30 minutes of
  game time Opus had 231 inhabitants, Fable 155, Sonnet 105 and Haiku 59. Its `clock.ps1` is a
  referee as a script: start, a line per player and game minute, pause, save, scores. Note on the
  score: the game's inhabitants count the workers of producers too.

## Environment variables

| Variable | Read by | Meaning |
|---|---|---|
| `O1602_CONTROL_PORT` | `o1602-ctl` | default port (else 7602) |
| `O1602_CONTROL_NO_SPEED` | game | this game's control port refuses `pause`, `speed`, `autoplay` |
| `O1602_PLAYER_ID` | game | multiplayer player ID for this run (16 hex digits) |
| `O1602_AUDIO_DEVICE` | game | play sound on the output device whose name contains this text |
| `O1602_CTL` | Jev driver | path of `o1602-ctl` for a driver copied into an agent folder |
| `TYPESAFE_API_KEY` | Jev driver | key for the hosted Jev API (`--hosted`); never stored in the repo |
