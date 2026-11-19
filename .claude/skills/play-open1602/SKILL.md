---
name: play-open1602
description: Play a running Open1602 (Anno 1602) game through the o1602-ctl control port as the human player would, alone or in a multiplayer game against other agents - found a city, build, supply, trade, let game time pass - with as few commands and as short answers as possible. Use whenever asked to play Open1602 or Anno, build up or rescue a settlement, reach a population or money goal, or join a duel or tournament. Read anno1602-strategy with it.
---

# Playing Open1602 through the control port

The game listens for text commands when started with `--control PORT`, in a game alone and in a
multiplayer game. You play the local player's slot with the same rules, costs and refusals a
person has. Every command is one call: `bin\o1602-ctl.exe [--port N] COMMAND [ARGS]`.
`o1602-ctl help` lists every command; read it once at the start, it is the reference.

**No cheating (user rule).** Use only what a person playing could click or see. No `autoplay`
(the built-in computer would play your slot), no editor, no savegame edits, no engine changes that
bend the rules, and no information a player would not have (in a game alone the port answers about
islands you have not discovered: do not ask it about them). When in doubt, ask the user.

## What costs you: turns and answer size

Every command is a turn, and every answer stays in your context for the rest of the session. A game
is won by the agent that looks little, decides once and acts in bulk.

- **A failed command answers `error: ...`** (exit code 1). A refused build names the reason and the
  tiles. Anything else worked.
- **Send the commands of one step together.** Pipe them to `o1602-ctl -`, one per line (`#` lines
  are comments). Each answer comes under `### CMD`; a failed part puts
  `error: N of M commands failed` first. `advance` cannot be part of a batch.
- **Look with the short forms.** `alerts [I]` (most urgent first) and `economy I C` (per good:
  stock, need, trend, minutes until empty) answer "what next". Then `production I idle`,
  `houses I problems 10`, `islands mine`. Ask for a part of the map (`map I X Y W H`), never the
  whole island, and only when you must see the ground.
- **Let the game find the place.** `build NAME I auto` builds at the best place you can pay for and
  lays the road; this replaces reading the map, `sites`, `build` and `road`.
  - Without X Y the place has the best catchment of the island (trees, meadow, fish), which may lie
    far from town. `build NAME I auto X Y` takes the place nearest to X Y, within 8 tiles of it: use
    it to put houses and public buildings where you want them and to spread producers.
  - The road crosses a river with a wooden bridge by itself; the answer says how many bridges, and
    they cost wood. It builds nothing when no road can reach a place, and says so.
  - Houses keep out of your foresters' windows, and a producer keeps six tiles from another of its
    kind, while another place is left. Foresters do not keep out of house land: place them with X Y
    away from where the town will grow.
  - A house's answer says what reaches it. Without `chapel` in that line it will not rise: build
    houses with X Y near a chapel, or a chapel for them.
- **Do not check what an answer already told you.** `built 1 of 1` means it stands.
- **Look ahead instead of waiting to see.** `forecast 300` runs the game five minutes ahead on a
  copy with nothing else ordered and says where money, balance and residents will stand and which
  goods run out when. It is a rough guide (no fire or plague in it, and its numbers were off by a
  third in a test), good for "does the food last" and "does this pay", and it costs no game time.

PowerShell example of one step:

```powershell
@"
say "Wood and fish first"
build forester 12 auto
build fishers_hut 12 auto
build-many house 12 7 20 10 23
"@ | bin\o1602-ctl.exe --port 7602 -
```

## Start a game

Windows (PowerShell), from the repository root; `ANNO1602_DIR` points at the installed game.

```powershell
Start-Process bin\open1602.exe -WorkingDirectory bin -ArgumentList '--new-game','1','--name','Claude','--seed','42','--control','7602','--no-videos'
```

- `--new-game D`: difficulty 0 (easy) to 3 (hard). `--seed N` repeats a world. `--load FILE.o1602`
  goes on with a save.
- `state` answers once the game is ready (before that: `error: the game is not running`).
- A game alone starts **paused**; time runs only while you `advance` or after `resume`.
- A multiplayer game (README: "Two agents against each other", `tools/agent/turnier/`) runs on
  while you think.

## Coordinates

- **Island tiles** (X Y from the island's top left corner) for everything on land: `build`, `road`,
  `demolish`, `map`, `find-site`.
- **World tiles** for ship positions and `ship-move SHIP X Y`. World = the island's position
  (`islands`) + island tile. You rarely need this: `ship-move SHIP city I C` sails to a Kontor.
- In `map` output read the column from the two header lines (tens, then ones) and the row from the
  number at the left. Off-by-one reading was the most common mistake; `auto` and `find-site`
  avoid it.

## One round

1. **Look**, as one batch: `state`, `alerts I`, `economy I C` for each city that has inhabitants.
   Every few rounds also `production I idle` and the routes (`route SHIP show`).
2. **Decide** the worst bottleneck (anno1602-strategy, "A healthy round"). One or two things, not ten.
3. **Act**, as one batch. Start it with `say "..."` so the person watching reads what you do, and
   update `plan "A | B | C"` when the plan changes (ASCII only: ae, oe, ue).
4. **Wait**: `advance N`. It ends early at a fire, plague or attack and says why, so long waits are
   safe: 60 to 120 s while the town is small, 300 to 600 s later. `advance N until ship ID` ends
   when that ship has arrived. It leaves the game as it was, paused or running. The game's messages
   come with the answer (`events` reads them without waiting).

`speed 8` once makes time pass faster in real time. When a person watches, `resume` once and keep
the game running at x8.

## Opening

1. `islands` and `ships`: pick a big free island near your ship whose crops fit your plan (north:
   tobacco, wine, sugar; south: spices, cotton, cocoa). An island counts as discovered when your
   ship has been inside its bounding box; `explore SHIP` (a still ship beside it) shows crops and
   ore. In a game alone `islands` prints crops even for islands marked `not discovered`: leave
   those lines unread until your ship has been there (the no-cheating rule).
   - **At the start no island is discovered**, and `kontor-sites` refuses an island you have not
     seen. First `ship-move SHIP X Y` to a tile of the nearest big island (`islands` gives each
     island's world position and size; for a land tile the ship takes the sea tile nearest to it),
     `advance 60 until ship SHIP`, then go on.
   - Before you settle, look at what the island gives: `sites sheep_farm I 3` (meadow for cloth;
     without cloth there are no settlers), `sites forester I 3`, `sites fishers_hut I 3`. On a
     discovered island they answer before you have a city there.
2. `kontor-sites SHIP I`: an `ok` place with free land and forest behind it. "the ship is too far
   away": sail closer (within 16 tiles). `ok` means founding works from there; unloading needs
   the ship within 5 tiles.
3. `found SHIP I X Y`. The answer names the city (island and city number); a ship out of reach
   sails to the new Kontor by itself.
4. `advance 60 until ship SHIP`, then, in the next batch, `unload SHIP all` and the first buildings.
   A batch carries on after a failed part, so builds sent together with a `found` whose ship has
   not arrived all fail for want of materials. Building materials must lie in the Kontor, not on
   the ship. The city's room per good is
   limited (30 to 40 t at first, `cities I C` says it; every market adds room) and the answer says
   what stayed on board. Unload the rest when room is free.
5. One batch: `build marketplace I auto X Y` beside the Kontor, `build fishers_hut I auto`, and
   foresters: wood is what the first half hour runs on. `sites forester I 12` lists places with
   their tree score; build six or more over the first rounds, spread out, each with
   `build forester I auto X Y` at one of those places. Then houses near the market:
   `build house I auto` or a block with `build-many house I X1 Y1 X2 Y2`.
6. `advance 120`, then a normal round. Houses fill with pioneers and taxes start.

## Facts that cost agents whole rounds

**Roads and reach**
- A building is connected when a road tile, a market or the Kontor touches its edge (not
  diagonally). Carriers walk on roads. `alerts` lists `[ROAD]` for unconnected producers;
  `fix-roads I` mends houses.
- Roads cannot cross slopes `/`, beach `b` or rock. Over a river `road` and `auto` lay a wooden
  bridge. `road` answers "no road path" when there is
  no way. Place a coastal building only where a road can reach it.
- Land belongs to your city only within the circles of its markets, Kontors and towers. "outside
  the city" means: build a `marketplace` at the edge first (it reaches 16 tiles). `warehouse_1`
  stands on the coast only.
- A producer that shows "idle" with stock waiting has nobody collecting: put a market within reach
  of every production cluster (the second market after about four foresters, another by the
  pastures).

**Producers**
- A quarry is a mine (`E` on the map) and missing from `production`. The stonemason's worker walks
  to it: it needs free land beside the quarry and no river between. The score of `sites` counts
  the quarry in reach, not the way to it.
- A plantation or winery needs free land for its fields around it (`sites` scores that); on the
  beach it stays at 0 %. Plant with `build-many <crop>_field I X1 Y1 X2 Y2`; "does not grow here"
  on many tiles means the island grows that crop only in patches.
- `build-many forest ...` answers `built 4 of 64, refused: terrain`: trees fit only on free land
  of yours, not on tiles that hold stumps or young trees. That is no failure, and it means you
  cannot replant beside a forester that has cut its window bare: build the next one elsewhere.
- A Kontor alone collects slowly. A second island that produces needs a market of its own beside
  the producers, or the goods wait in them.
- Clearing a field window with `demolish` also takes your own road through it; lay it again.
- Fishers' huts stand on the beach and need a land tile beside them that can take a road.
- A building can be switched off and on (`off I X Y`, `on I X Y`): no running cost for work it does
  not do. Check `production I idle` for "switched off" you forgot.

**Building and demolishing**
- Buildings take rotations 0 to 3; try them before you demolish for room. A listed size 4x3 stands
  as 3x4 when rotated.
- Demolishing gives nothing back. `demolish I X1 Y1 X2 Y2` clears a rectangle of roads, fields
  and trees; houses and workshops in it stay unless nothing else is in it.
- Never demolish houses for a building before its materials lie on that island.

**Cities and islands**
- On an island where natives or another player live, your city has a number other than 0 (island 14
  city 2). Use it in `cities I C`, `economy I C`, `route ... stop N I C`.
- `threats` lists foreign soldiers on your islands, natives' guards included. Only soldiers of a
  player at war (`diplomacy`) are a danger.
- `state` gives two counts. `residents` are the people in your houses, the classes of `cities`
  added up: this is what a tournament scores. `inhabitants` is the game's own figure and adds the
  workers of your producers, so a forester raises it by one and scores nothing.
- `economy` shows the trend of the whole stock: purchases and building count too, so "wood +6"
  can hide foresters that give nothing. `production I idle` tells which producers stand.

## Ships and trade

- `load` and `unload` work within 5 tiles of a Kontor: `ship-move SHIP city I C` first. At another
  player's Kontor they buy and sell at its prices and need a trade treaty
  (`diplomacy PLAYER trade offer`).
- `trade I C WARE buy|sell|none [TONS] [PRICE]` sets what your Kontor buys from and sells to ships
  that call. The slots are few: set another good to `none` first. The game clamps prices to a
  range per good; the answer says the values in force. For `buy`, TONS is the stock up to which
  the Kontor buys, so TONS times PRICE is what one visit can cost you (40 t tools at 100: 4,000).
  `purchases` in `state` is an average over the last minutes and stays up after you stop buying.
- **The free trader** is the only early source of goods you lack: set `trade I C wood buy 40` (and
  cloth, tools) in the first minutes. He sells only what he bought at other Kontors, and he sails
  to the Kontor that promises him the most profit. Cheap surplus on sale (bricks 15, wood 8) and a good buy price for
  what you need bring him within a minute or two; without that he may stay away for ten.
- Other players' offers change within minutes: check `cities I C` right before a long trip. In the
  first half hour the computer players' Kontors sell nothing; only the free trader brings goods.
- **Routes:** `route SHIP clear`, one `route SHIP stop N I C load|unload WARE TONS ...` per stop,
  then `route SHIP start`; `route SHIP show` checks it. At a load stop the ship takes what lies
  there (until TONS are on board) and sails on; it does not wait for more. "Verify your trading
  routes!" in the messages means a ship found nothing to load or no room to unload. A load at your
  home stop takes those goods out of the home Kontor on every trip: remove one-off loads.

## Multiplayer

- The game does not wait for you. `advance N` only waits; pause and speed belong to the host (in
  a tournament to the referee, and your port refuses them).
- **Count your turns.** At speed x2 a game minute lasts 30 s, so thirty game minutes are about
  25 of your turns. Read the skills before the clock starts and give no order while the game
  stands (test the first line of `state` for `running`: the word is also in "running costs");
  when it runs, sail at once. Per turn send one batch that looks and acts, then one `advance`
  (one per call: at x2 `advance 120` takes a minute of real time). If you script several rounds
  in one shell command, never filter the answers: a hidden `error:` cost one player four minutes.
- An order answers after about 2.5 s of game time, so that the next command sees its result. A
  batch waits once for all its orders: batching is how you keep up.
- The answer comes from a copy of the game. When another player changed the same place in between,
  the real game may differ: read again rather than trust an old answer.
- You see what the game shows your player: islands you have not discovered come without crops and
  cities, and `map` and the site searches refuse them.
- `chat TEXT` writes to every player, `chat` reads what the others wrote; `state` says when new
  lines wait. Players sell surplus cheaply there.

## When a command fails

- `terrain`, `overlaps`, `outside the city`: wrong place; the answer names the tiles. Use `auto` or
  `find-site`.
- `not enough wood|tools|bricks`, `(short: wood)` in a list of places: unload the ship, wait for
  production or buy. `economy I C` shows the stock.
- `locked`: not unlocked yet; `state` names the next unlock, `buildings` what you may build.
- `error: nothing moved`: the ship is not within 5 tiles, the Kontor is full, or the good is missing.
- `error: the game is not running`: a menu is open or the game still loads.

## Other

- `save NAME` writes `%APPDATA%\Open1602\saves\NAME.o1602`. Use a new name; never overwrite a
  save you did not make.
- `bin\o1602-tool.exe state SAVE --towns` shows a save's inhabitants per class without the game.
- `tools/agent/jev_driver.py` reads city 0 of its island; on a shared island it reads the wrong
  city. Check shared islands by hand.
- `tools/agent/steward.py` carries out standing orders from a JSON file (houses, producers, taxes).
  In its first measurement agents with it had fewer residents than agents who gave every order
  themselves (`tools/agent/bench/README.md`): do not rely on it until that has changed.
- While the game stands before a referee starts it, wait with a sleep of a few seconds between
  looks at the first line of `state`, in one shell command; do not spend a call per look.
- Streaming a game: the `stream-open1602` skill (its rule on what the stream may show comes first).
