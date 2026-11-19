---
name: anno1602-strategy
description: Economic strategy for Open1602 / Anno 1602 - island roles (capitals vs supply islands), build order and sizing per class up to aristocrats, how houses really rise, taxes at the edge, trade routes, money emergencies, defence and diplomacy, and how the computer opponents think. Use together with play-open1602 before and while playing, and run the planner (tools/planner/plan.py) to size each stage.
---

# Anno 1602 strategy for an agent

**No cheating (user rule).** We play only with what a human player can do and see: the same
costs, rules and refusals, and no knowledge a player would not have. No free buildings, no editor,
no savegame edits, no engine changes that give us an advantage. A new control command may only
do what a player could click or read on screen. The computers' own cheats (goods from nowhere) are
theirs. We win by playing better.

**Sources of truth:**
- `reference.md` next to this file: web research with sources.
- `tools/planner/game_data.json`: the balance extracted from the installed game's haeuser.cod.
- The engine source under `engine/sim/src` (houses.cpp, consumption.cpp, ai/) when a rule is unclear.

Where these disagree, **the game data, the engine source and `o1602-ctl cities` win**.

## 1. Plan before you build: run the planner

```powershell
python -I tools\planner\plan.py                       # default path: pioneers -> 100 merchants
python -I tools\planner\plan.py --crops grain,spices,cotton,cocoa --crops2 tobacco,sugar,wine
python -I tools\planner\plan.py --target aristocrats=1000 --csv plan.csv
```

- **Per stage it prints:** houses, demand per good (t/min), the cheapest chain per good, building
  counts, taxes against running costs, and what the stage costs to build.
- **Options:**
  - `--crops`, `--crops2`: what the home and the second island grow (from `o1602-ctl islands`).
    Never count a "(half)" crop: it grows only on a few tiles.
  - `--food`: add `hunter` only if the island has deer.
  - `--efficiency`: real buildings run at 60-80%.
- **Output:** `--csv` writes a table that opens in Excel.
- **Refresh the data:** if it is missing or the installation changed, run
  `python -I tools\planner\extract_game_data.py` with `ANNO1602_DIR` set.

## 2. The path to 100 merchants

The planner's numbers are at 75% efficiency.

| Stage | Population | Houses | What to add | Unlocks reached |
|---|---|---|---|---|
| 1 | 40 pioneers | 20 | 1 market, 2 foresters, 1-2 fishers, 2 chapels | 30 pioneers: cattle |
| 2 | 120 settlers | 20 | sheep farm + weaving hut; alcohol (winery or 2 sugar + distillery); quarry + stonemason at 15 settlers | 40: plantations; 50: tavern; 100: school, toolmaker; **120: ore mine, smelter** |
| 3 | 150 citizens | 20 | tavern + school per quarter; tobacco (2 plantations + 1 tobacco products); spices; more fish | 150 citizens: **church** |
| 4 | 210+ citizens | 25 | more citizen houses, a second cloth chain | 200: cocoa, cotton, tailor, weaving mill; **210: bathhouse** |
| 5 | 100 merchants | 29 | church + bathhouse reaching the houses; cocoa plantation | 4-5 houses at 25 merchants each |

**Totals to here:** about 190 t of tools and 300 t of bricks.

**Get your own tools early:**
- At 120 settlers, build ore mine + ore smelter + 2 toolmakers. They need a known ore deposit;
  `islands` lists the ones you know.
- Until then, buy tools from the free trader at a low price: `trade I C tools buy 30 75`.
  Bought tools would cost about 14,000 gold in all.

## 3. How a house really rises (engine, houses.cpp)

A house moves up one class only when **all** of these hold:
1. It is full.
2. Food is supplied 100%.
3. The **next** class is at satisfaction 128.
4. The next class's public buildings reach the house (`coverage I X Y`, `houses I`).
5. The materials are in the Kontor:
   - settlers: 1 t tools + 3 t wood;
   - citizens: 2 t tools + 2 t wood + 6 t bricks;
   - merchants: 3 t tools + 3 t wood + 9 t bricks;
   - aristocrats: 3 t tools + 3 t wood + 12 t bricks.

Missing tools or bricks stop every rise silently.

**Public buildings per class (every one, not a choice):**

| Class | Needs |
|---|---|
| Settlers | chapel |
| Citizens | tavern, chapel, school |
| Merchants | tavern, **church**, school, **bathhouse** |
| Aristocrats | tavern, church, **college**, bathhouse, **theatre** (the school no longer counts) |

Plan each quarter around the tavern, which has the smallest reach (12).

**The trap of a new class:** while a class has no inhabitants, the game resets its tax to 128
every city tick (consumption.cpp). Lowering it does nothing. So the **first** house of a new
class rises only when that class's goods are supplied at about 100% at normal tax. For
aristocrats that means alcohol, cocoa, tobacco goods and spices near 100%. Clothes and jewellery
only need to be in stock, because nobody consumes them yet.

**Falling:** a class below satisfaction 88, or a house that lost a public building, drops back a
class. Lasting shortage costs whole classes within minutes: Drisden fell from 897 to 108 merchants.

## 4. Satisfaction and taxes

- Satisfaction = goods supplied against what the tax asks, capped at 128. A class at 128 has
  headroom.
- **Taxes at the edge (user rule, high priority):** every class at the highest tax at which it
  stays fully content. Step +16 after two content readings, -16 at once when it dips below
  128 - 8.
- The game allows taxes from 64 to 192. A class short of goods needs a tax **below** normal
  (down to 64) to stay above 88 and not fall.
- Supply first, then raise the tax.
- **The balance is per game minute.** At x8 a game minute lasts about 7.5 s, so -900/min drains
  60k in about 9 real minutes.
- A castle or cathedral gives a satisfaction bonus that lowers the tax the classes feel. It fades
  over time, so it is no lasting fix.

## 5. Island roles: capitals and supply islands

**Capitals** (in game 4: Essix, Drisden):
- Houses and public buildings only. Aim: as many aristocrats as possible.
- Raw producers (farms, plantations, wineries, pastures, foresters) belong on supply islands.
- Demolish capital farms below 50% and rebuild them on supply islands.

**Supply islands:**
- They only produce raw materials and goods for the capitals.
- NO houses there, and nothing for inhabitants (chapel, tavern, school, church, bathhouse, doctor,
  fire station). Kontor, market(s) and production only.
- A player's city without houses does not dissolve, and production needs no inhabitants.
- Every free tile around a farm or plantation carries its crop (fields cost 5 gold, no tools).
- Plant only crops the island grows fully. Test a "half" crop before pulling anything down.
- One producer per field area, not three side by side sharing it.
- Roads only as long as a building needs to reach the market. Dead-end and doubled roads go;
  their tiles become fields.
- No fisher where nobody eats, and no forester without trees or while the store holds plenty of
  wood. The game's forester counts vines and crops as trees, so no forester on a plantation island.
- No stonemason without stone in reach.
- One shipyard per island at most; one in the whole realm is usually enough.

**More raw land:**
- A Kontor can be founded on an island where natives or computers already live, if
  `kontor-sites` lists free spots. Game 4: island 0 (cocoa, beside the natives) and island 14
  (tobacco, beside natives and Yellow).
- Natives sell their goods (tobacco goods, spices) and buy alcohol and cloth. A route stop at their
  Kontor (`route ... ISLAND 0 load WARE`) buys from them.
- A colony has no fire station: its first workshop burned down. Look at the colonies'
  `production` now and then.

## 6. Production and layout

- **Zones:** a dense core of houses around a few public buildings, with industry and farms at the
  edge of town or on other islands. A workshop among the houses takes the room a quarter needs.
- **Keep streets open to grow:** never put a house beyond a street end; plan quarters as a grid
  (streets every 5 tiles, two rows of 2x2 houses between).
- **Territory:** land belongs to the city only within the circles of its markets, Kontors and
  towers. Fields, farms and houses outside are refused with "outside the city". Build a
  marketplace (radius 16, 200 gold) at the edge before farming beyond it.
- **Radii in tiles** (from `game_data.json`):
  - Markets, Kontors, warehouses 16.
  - Chapel 8, tavern 12, school 12, college 15, doctor 16, fire station 15, church 21, bathhouse 20,
    theatre 20.
  - Forester 3, sheep farm 3, cattle farm 2, plantations 2, grain farm 1, fisher 5, hunter 8,
    stonemason 7.
  - Workshops (weaving, toolmaker, bakery, tailor) 15, rum distillery and tobacco products 12,
    smelter 10.
- **Farms:**
  - All fields inside the plantation's radius 2: a 6x6 window, about 30 field tiles.
  - Fewer than about 30 ripe fields means the plantation runs at a third. Below 60% in
    `production` means too few fields.
  - One road tile touching the plantation, then the way to the market.
  - Never place a plantation among houses.
- **Workshops fetch only within their own radius.** A market or Kontor inside that radius must be
  linked to the workshop by road; a road to some market far away is not enough.
- **Sheep farms** need 24 or more meadow tiles in radius 3.
- **Roads:**
  - Every house needs a road at its side, or doctor and fire brigade cannot reach it. Lay streets
    between rows of houses: blocks two houses wide at most.
  - `unconnected I` and `fix-roads I` find and mend gaps.
  - Paved roads (`road ... stone`) are faster.
- **Rotate before demolishing:** buildings take rotations 0-3; try every one in a gap first.
- **Never pull houses down** for a building before its materials (bricks!) lie on that island. A
  failed build after the demolition just loses the inhabitants.
- **Clearing a field window** with demolish also removes your own fresh road. Reconnect after
  planting.
- **Demolish inefficient buildings:** a producer below 50% for minutes only costs upkeep.

## 7. Logistics and routes

- **Plan the second island from the start** and link it with a `route`, not by hand.
- **A route ship waits at a load stop until the full amount is aboard.** Set load amounts to what
  the source produces, or the whole route stalls there.
- **A small Kontor holds 30 t per good.** When it is full, the producers stop ("nobody collects").
  Add a second ship, or load more per trip.
- **A standing material route** keeps every supply island at a minimum of tools, wood and bricks,
  so fields and producers can always be built there.
- **Check all routes every ~5 reviews:**
  - Source still produces, target still needs it, nobody waits forever.
  - Stop routes that became useless, and park the ship near a capital as a reserve.
- **Ships get lost.** When an island suddenly starves, check first that its supplier still exists
  (`ships`, `route SHIP show`).
- **Priorities:** scarce luxury goods go to the capital closest to the next class. Shifting them
  lifts one capital but can crash the other, so **add production before you redistribute**.
- The Kontor trades through limited slots (Kontor I: 4 buy and 3 sell). Use them for what you
  cannot make, set prices below the AI's (tools 75, not 105), and never sell what a class consumes.
- Ships cost no upkeep. Running costs come from buildings, military costs from units.

## 8. Aristocrats (goal 1000, game 4)

- **They need** food, alcohol, cocoa, tobacco goods, spices, clothes and jewellery, plus all six
  public buildings (section 3). A house holds up to 40 aristocrats.
- **Unlocks:** college and goldsmith at 250 merchants in one city, theatre at 300 merchants.
  Tailor and weaving mill open at 200 citizens.
- **Jewellery:** gold mine plus goldsmith. Gold deposits are rare. In game 4 the only one lay on a
  computer's island (Keln), which the user took.
- **Sizing for 1000 aristocrats** (`plan.py --target aristocrats=1000`): about 8 tobacco
  plantations, 4 tobacco products, 7 wineries, 5 cocoa, 5 spice, 3 tailors, 2 goldsmiths and
  2 gold mines.
- **Citizens and merchants eat most of the luxury goods first.** Drisden's 749 citizens alone
  needed about 3.3 t tobacco goods a minute; one plantation gives far less.
- **Cloth is contested:** tailors turn cloth into clothes and starve the classes that need cloth.
  Build cloth capacity before a tailor.
- **Game 4 result:** the first 240 aristocrats came once Essix had cocoa 100%, alcohol 89%,
  spices 57% and tobacco 21%. That was enough because the merchants' goods were full and clothes
  and jewellery were in stock. They grew to 667 within about 15 game minutes.
- **Symptom of a short chain:** `cities` shows a class at 5-6% for a good while the plantation is
  "working". Fix supply first, then build the next class.

## 9. Money

- **Warning sign:** a negative balance in two checks in a row. Act before the cash runs out.
- **The Crown pays once** when you fall deep into debt; a second time the game is over. Never go
  below about -1000 a second time.
- **In an emergency, in this order:**
  1. Stop new building and money-losing routes.
  2. Sell surplus: bricks, spices, cloth, sugar (`trade ... sell TONS PRICE`).
  3. Switch off unprofitable buildings (`off ISLAND X Y`); switch them on again later.
  4. Raise the tax of classes with satisfaction to spare.
  5. Buy food only if people starve.
- **Never** build what the standing houses cannot pay. Buildings for a class you cannot reach yet
  (a theatre without jewellery) are pure cost.
- **Produce rather than buy; sell surpluses.** Buy only what is truly important; tools may be bought
  when missing.
- **Stopping purchases a class lives on drops that class at once** (750 merchants to 0). Build your
  own production first, then stop buying.
- Pioneer houses are the cheapest income (3 t wood each). Food first: a house pays only when fed.

## 10. Military and diplomacy

- **Never shoot first.** An attack order on ANY ship or building of a player at peace declares war
  at once. Computers' trade ships carry 1 cannon, so an armed ship is no sign of hostility.
- **Tribute repairs mistakes:** up to 10,000 gold plus a friendly gesture restored peace within
  seconds.
- **One soldier on a foreign island means war.**
- **Units and ships:**
  - One land unit fits per ship hold.
  - A castle holds its trained units until released; a full castle trains nothing more.
  - A ship needs a free hold to load cannons: land soldiers aboard for a moment.
  - A trade treaty turns a right-click on a foreign Kontor into trade; attacking needs the attack
    cursor (F).
- **Shared islands:** natives' guards and a computer's garrison on an island you share are not
  invaders. Only soldiers of a player at war count as a threat.
- **Defence:**
  - Spread cannons (about 4 per island) and swords to every island, so towers can go up when an
    attack comes.
  - Watch the computers' towers and ships (`islands`, `ships`, `threats`).
  - Cheap first: a palisade (10 gold, 2 t wood) on the coast facing the enemy.
  - Watchtowers need cannons; the stone one needs 6 t tools.
  - Weapons need iron: ore mine, smelter, then swordsmith; later musket maker and cannon foundry.
- **Conquest facts:**
  - A computer's city dissolves when its Kontor, market, towers and houses are gone.
  - A neutral building is captured whole; anything else is destroyed.
  - Conquest decisions and attacks are the user's call. The agent prepares, and the user starts
    the attack.

## 11. How the computer opponents think

The original's AI, rebuilt in `engine/sim/src/ai/`, is **rule-based**: no search, no Monte Carlo,
no minimax. It does not plan ahead.

- **A task stack per computer:** develop city, settle, logistics, military, diplomacy. The city
  planner runs every 5.1 s, diplomacy every 30 s in six phases of 5 s. Everything is re-initialised
  about every 3600 s.
- **Fixed build lists per city stage** (founded, colony, pioneers, settlers, ..., aristocrats).
  It builds the first entry that is missing ("market, 2 woodcutters, 2 sheep, weaving hut,
  2 fishers, 18 houses ...").
  - The lists are data: `computers.toml`, documented in `docs/modding/computer-players.md`.
  - The thresholds are in `balance.toml` `[computer_stages]`, e.g. settlers at 22 inhabitants.
- **Site search by rules of thumb:** workshops near the Kontor or a market, farms where the crop
  grows. A failed site is retried a few times, then it waits.
- **It gets some goods from nowhere** (values in `balance.toml`).
- **Military and diplomacy are if-then rules.** City walls only at war with a human, or at peace
  from the citizens on. It reacts to a founding on its island (event 0x0E).

**What follows for us:**
- Its growth is predictable and slow in long games. It does not adapt to our strategy.
- Its trade windows show what it wants; selling there is safe income.
- It will not sell what its own build list needs (game 4: Keln never sold gold).
- Its mood (`diplomacy`) drops when we crowd it. Keep peace and trade treaties; a war costs far
  more than any tribute.

## 12. Choosing islands

- **Check ownership right before sailing:** `islands` shows "cities of: N"; confirm with
  `cities I 0`. Never trust a stale list.
- **Home island:** the largest free island with ore mountains (`O` in `map I`); count ore and rock
  tiles. Then crops.
- **North islands for alcohol and tobacco** (wine, sugar, tobacco); **south islands for spices,
  cotton, cocoa**. You need one of each at full fertility.

## 13. A healthy turn / review

1. `state`: money and balance. If the balance is negative twice in a row, act (section 9).
2. `alerts I` per capital: fires, plague, full storage, houses that cannot rise.
3. `cities I C` per capital: what each class lacks, below 90%? Then find the chain's weak link with
   `production`: raw producer, fields, road, carrier reach, Kontor full, ship gone.
4. Taxes at the edge (section 4).
5. Every few reviews: routes (section 7) and the colonies' production.
6. Fix the worst bottleneck first; rerun the planner for the current stage.
7. Update `plan` and `say` for the viewers; keep the game running at x8.
