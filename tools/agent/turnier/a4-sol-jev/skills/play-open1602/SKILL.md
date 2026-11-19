---
name: play-open1602
description: Play a running Open1602 (Anno 1602) game as the human player through the o1602-ctl control port - look at islands, found a city, build, trade, advance time turn by turn. Use when asked to play Open1602/Anno, build up a settlement, or reach a population goal.
---

# Playing Open1602 through the control port

The game listens for text commands when started with `--control PORT`. This works in games
played alone only, not in multiplayer games. You play the local
player's slot with the same rules, costs and refusals a person has. The game starts **paused**;
time only runs when you `advance` it, so you play in turns.

**No cheating (user rule).** Use only what a person playing could click or see. Never use:
- `autoplay`, the editor, free builds or savegame edits;
- engine changes that bend the rules for us;
- information a player would not have, such as undiscovered islands or other players' hidden
  stock.

A new control command must stay fair the same way. When in doubt, ask the user.

## Start a game

Windows (PowerShell), from the repository root. The original game data must be installed
(`ANNO1602_DIR` points at it).

```powershell
Start-Process bin\open1602.exe -WorkingDirectory bin -ArgumentList '--new-game','1','--name','Claude','--seed','42','--control','7602'
```

- `--new-game D`: difficulty 0 (easy) to 3 (hard). `--seed N` makes the world repeatable.
- Load a save instead: `--load <file.o1602> --control 7602`.
- Wait a few seconds, then `bin\o1602-ctl.exe state` must answer.

Every command is one call: `bin\o1602-ctl.exe <command> [args]`. It exits with 1 on an `error:`
answer and 2 when no game listens. `bin\o1602-ctl.exe help` lists all commands and the map legend.

## Coordinates

- **World tiles** are used for ship positions and `ship-move`.
- **Island tiles** (X Y from the island's top left corner) are used for everything you build:
  `map`, `build`, `road`, `found`, `demolish`, `find-site`.
- `islands` gives each island's world position of its tile 0,0. World = island position + island tile.
- In `map` output, read the column from the two header lines (tens, then ones) and the row from
  the number at the left. Off-by-one reading is the most common mistake; verify with `find-site`
  before building.

## Show the person watching what you do

The person usually watches the game window. Keep two things up to date over the map:

- **The plan:** `plan "Wood and food | More houses | Chapel and cloth for settlers | ..."`.
  Items are separated by `|`. Update it whenever the plan changes; `plan clear` removes it.
- **The current step:** `say "Building a second forester at 17,22: wood is short"`. Do this
  before each batch of actions. The last six steps stay visible.

Write ASCII only (ae/oe/ue instead of umlauts): the game's font has no UTF-8.

## The turn loop

1. Look: `state`, `cities ISLAND CITY` (stock, needs, satisfaction), `map ISLAND X Y W H` around
   your town.
2. Act: build, road, trade.
3. Run time: `advance 60` (game seconds, up to 3600). `speed 8` first makes it pass faster in
   real time. `advance` answers with `state` once the time has passed.
4. Repeat. Save now and then: `save NAME`.

## Opening, step by step (what worked)

1. `islands`: pick a big island near the ship (`state` shows the ship's world position) whose
   crops fit your plans. North islands grow tobacco and wine; south islands grow spices, cotton
   and cocoa.
2. `ship-move SHIP X Y` to a sea tile next to the island, `advance 30` to `60`.
3. `kontor-sites SHIP ISLAND`: pick an `ok` site that has plenty of free land (`.`) and forest
   behind it. `ship_too_far` means sail closer (within 16 tiles).
4. `found SHIP ISLAND X Y`. The Kontor (warehouse) is paid from the ship's cargo.
5. **Unload the ship at once.** Building materials must be in the Kontor, not on the ship:
   `unload SHIP tools 40`, `unload SHIP wood 30`, `unload SHIP food 10`.
   - The Kontor's room per good is limited ("room ... t per good" in `cities`). The answer
     says how much really moved, and the rest stays on board.
   - Check the stock with `cities ISLAND CITY`, and unload the rest later.
6. Marketplace (4x3) next to the Kontor, then roads.
   - Connect the Kontor, the market and all production buildings with roads. Carriers walk on
     roads.
   - Roads need land at both ends: not beach `b`, rock or buildings.
7. Production for the first class (pioneers):
   - `forester` (the woodcutter, 2x2) in the forest `t/T`.
   - `fishers_hut` (1x1) on the beach. `find-site fishers_hut ISLAND X Y` finds the spots.
8. Houses (2x2) within the market's reach: `build-many house ISLAND X1 Y1 X2 Y2`. Each costs 3 t
   of wood, so wood is the first bottleneck.
9. `advance 60` to `120`, then check `cities`. Houses fill with pioneers, taxes start.

## Growing to the higher classes

- `cities ISLAND CITY` lists for each class its inhabitants, satisfaction (128 = content) and how
  well each good it needs is supplied (100% = fully).
- Houses rise to the next class only when all of these hold:
  - the house is full;
  - food is supplied 100%;
  - the next class's satisfaction is 128;
  - the public buildings the **next** class needs are in reach of that house. For settlers this
    is a chapel: build one near every market quarter.
  - building materials for the new house are in stock.
- "lacking public buildings" in `cities` counts only the needs of the current class, not the
  next one.
- `production` shows each production building's utilisation. A forester (woodcutter) below 30%
  has too few trees around it: plant `forest` tiles nearby (`build-many forest ...`). Goods that
  wait in a building ("stock") with nobody fetching them mean it has no road to a market or the
  Kontor.
- Unlocks: `state` names the next one (for example "100 settlers or higher in one city").
  `buildings` lists what you may build now, with size and costs (`buildings all`: also the locked
  ones).
- Typical chain in Anno 1602:
  - Pioneers need food (fish, hunters, later cattle and bakery).
  - Settlers also need cloth (sheep_farm, then weaving_hut) and a chapel.
  - Citizens also want alcohol, tobacco goods and spices; tobacco and wine need fertile islands.
  - Merchants also want cocoa and clothes.
  - Bricks (stone quarry) and tools (ore mine, iron smelter, toolmaker) become necessary for
    bigger buildings.
  - Look at `cities` for what is short. Never build blind.
- Money: keep the balance (`state`, per minute) positive. Every production building has a
  running cost.
- Goods you lack can be bought from the free trader or other Kontors by ship:
  - `ship-move` to their Kontor, then `load SHIP WARE TONS`, which buys at their prices.
  - This needs a trade treaty with computer players.

## Checks after each action

- Every answer that starts with `error:` failed. Read the reason:
  - `terrain`: wrong ground; check the map.
  - `not enough wood` or `not enough tools`: unload the ship or wait for production.
  - `the ship is too far away`.
  - `locked`: not unlocked yet.
- `build-many` reports `built N of M` and why the rest failed.
- After building, look at the `map` again to see where things really stand.

## Switching buildings off and on

- `off ISLAND X Y`: stops a production building (its running cost stops being charged for work it
  does not do). `on ISLAND X Y` starts it again. X Y is the building's origin, as `production`
  lists it.
- Use it in a money emergency, not as a permanent fix. Switch on again when the balance is positive.
- Needs the new build of the game (this command was added in game 2).

## Strategy

- Read the `anno1602-strategy` skill before founding a city.
- Run `python -I tools\planner\plan.py` to size every stage.

## Overview commands (one call instead of dozens)

All of them show only what a human player also sees (map, catchment previews, question marks,
the house panel), so they are fair.

- **`alerts [I]`**: everything wrong at once: question marks with their likely cause, fires, full
  buildings, missing roads, houses without market or the next class's public buildings, short
  supply, full storage, low materials, money. Read it first every turn.
- **`houses I`**: every own house: road, market, public buildings in reach, what the next class
  lacks.
- **`house-sites I [MAX]`**: every free house place with a road at its side and a market in reach,
  nearest to a market first.
- **`sites NAME I [MAX]`**: the best places on the whole island, scored by the catchment: trees
  (forester, hunter), meadow minus forest (sheep, cattle), open water (fisher), free field land
  (plantations, winery, farms), quarry tiles (stonemason).
- **`batch CMD ; CMD ; ...`**: several commands in one connection (`o1602-ctl batch state ";"
  alerts 17`), each answer under `### CMD`.

Traps the agent fell into: a quarry is a mine (`E` on the map) and missing from `production`; a
stonemason's worker walks to the quarry, so no river between them; a plantation or winery needs
free land for its fields (`sites` scores it), on the beach it stays at 0%.

## Commands added after the first game

- **`production`**: each building's state and utilisation. Find bottlenecks here.
- **`find-site NAME I X Y [R]`**:
  - It lists places with a road next to them first (`road`).
  - For houses it says which markets and public buildings reach the place.
  - Build production buildings only at `road` places.
- **`coverage I X Y`**: what reaches a house at X Y (market, chapel, tavern, school, church,
  bathhouse).
- **`trade I C WARE buy|sell|none [TONS] [PRICE]`**: Kontor trading with ships that call (the
  free trader).
  - The slots are limited: set another ware to `none` first.
  - Give a price (tools: 75) or you pay the AI price.
- **`route SHIP stop N I C load|unload WARE TONS ...`**, then `route SHIP start`: automatic
  shuttles between your islands. Check with `route SHIP show`.
- **`tax I C CLASS RATE`**: 128 is normal. Only raise it for a class with satisfaction to spare.
- **`advance` answers list the game's messages**: fires, plagues, attacks, new classes. Such
  events set the speed back to x1.
- **Fishers' huts** stand on the beach: they need a land tile beside them that can take a road.

## Camera and streaming

- By default the camera jumps to every successful build, Kontor, road, demolition and ship order,
  so people watching (a stream) see each action.
- `camera ISLAND X Y` looks somewhere on purpose.
- `camera follow off` stops the jumping.
- Stream setup (outside the repo):
  - `D:\anno\stream`: OBS scene generator, `status.ps1` for the status bar, and `obsctl.py`.
  - Run the scripts with `D:\anno\stream\.venv\Scripts\python.exe`.
  - When restarting the game for a stream, first set `$env:O1602_AUDIO_DEVICE='Realtek Digital'`
    (the sound goes to an unused output: the stream hears it, the person at the computer does
    not), then start with `--load <save> --control 7602 --size 1600x900 --zoom 1 --no-videos`.
  - Keep the music on: no `--no-music`.
  - settings.cfg is set for the stream; leave it so:
    - `effects = off`: background music only, no effects.
    - `speech = 0 ...`: no voice warnings.
    - `video = 0 ...`: no message videos.
    - `display.event_speed = keep`: events do not slow the game.
  - Keep the game running at x8 while streaming. Do not pause between turns.

## Other commands

- **`advance` leaves the game paused.** After every `advance N`, run `resume` (or `speed 8`) at once.
  Game 4: the game sat paused for a whole round after an advance, and the person watching saw nothing
  move. The answer line `paused` in `advance` means this.
- **`batch` takes each command as its own argument**, e.g. `batch say "text" ";" build X ISLAND X Y ";"
  state`. A single quoted string fails with "unknown command". `advance` cannot run inside a batch.
- **Ship routes that worked (game 4):** `route SHIP clear`, then one `route SHIP stop N ISLAND CITY load|unload WARE TONS` per stop, then `route SHIP start`. Several stops in a row carry several goods (tobacco goods and alcohol on one ship). Load and unload only work within about 5 tiles of the Kontor: the Kontor's world position is the island's world position plus its tile (island 17 at 220,80 with Kontor 14,24 is 234,104), so `ship-move` to the sea tile next to it (e.g. 232,102) before unloading. An ordinary `ship-move` to the island's corner is too far.
- `autoplay on/off` exists, but it is off limits (no cheating, see the top): the built-in AI would
  play our slot.
- `pause` and `resume`: stop or run the game. `resume` runs it without a limit, until `pause`.
- To check a save outside the game: `bin\o1602-tool.exe state <save> --towns` shows
  inhabitants per class.

## Shared islands and city numbers (game 4)

- A Kontor can be founded on an island where natives or a computer already live, if `kontor-sites`
  lists `ok` places. Our city then has a number other than 0: island 0 city 1, island 14 city 2,
  island 3 city 1. Use that number in `cities I C` and in `route ... stop N I C`.
- `tools/agent/jev_driver.py`'s `read_state(island)` assumes city 0. On such islands it reads the
  natives' city. Check shared islands by hand.
- After `found`, the rest of the cargo stays on the ship. `unload` fails while the ship lies
  further than 5 tiles from the new Kontor: move it closer first, then `unload`.
- The natives' Kontor (`cities I 0`) shows what they sell and buy. A route stop there with `load`
  buys from them.
- `threats` lists foreign soldiers on islands where we live, natives' guards included. Only
  soldiers of a player at war (`diplomacy`: "peace none") are a danger.

## Fields and roads

- Clearing a plantation's 6x6 window with `demolish` also removes our own road through it. After
  `build-many <crop>_field`, run `connect` (driver) or lay the road again, then check `production`.
- `[FULL] ... nobody collects` on a farm means: no road, a workshop or market out of reach, or the
  Kontor's room for that good is full (`room N t per good` in `cities`). A full Kontor needs
  a ship that loads more often.

## Ending a session (stream)

1. Stop the driver: Ctrl-C in its terminal tab.
2. `pause`, then `save NAME`. The file goes to `%APPDATA%\Open1602\saves\NAME.o1602`.
3. Stop the stream and the recording through obs-websocket: `StopStream`, `StopRecord`.
   - Port 4455, password in `%APPDATA%\obs-studio\plugin_config\obs-websocket\config.json`.
   - A small Python client with `websockets` does it (protocol v5: Hello, Identify with the
     SHA-256 auth, Request).
   - Recordings land in the folder `RecFilePath` of the OBS profile (`basic.ini`); in game 4 that
     was `D:\Users\LukasSteindl\Videos`.
4. Close the game window (`CloseMainWindow` on `open1602`).
5. Cancel the periodic review job (`CronList`, `CronDelete`).

## Turnier SolJev (Vorrang vor Einzelspielerhinweisen)
Nur Port 7605; keine Pause, Resume, Tempo, Save, Autoplay oder Angriffe. Keine Engine- oder Fremddateien lesen/aendern. Opening-Lese-Cache bei jedem Versuch leeren. ships hat vor cargo optional eine lies-Zeile; diese muss beim Entladen-Parsing beruecksichtigt werden. Bestaetigt im Turnier: 101t blieben sonst nach Gruendung auf dem Schiff.
