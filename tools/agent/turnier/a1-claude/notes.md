# Notes of agent 1 "Claude"

## Map knowledge (tournament game, seed of 2026-11-09)
- Start: ship 2 "Wikkinger" at 250,87 with 50 tools, 50 wood, 10 food. 15000 gold.
- Island 12 (215,92, 70x60, south): HOME "Lavaschkiri", Kontor 21,15. Crops grain spices cotton cocoa;
  ore big at 49,9, gold small at 16,44. Lots of forest, ore mountains in the NE.
- Island 9 (259,21, 70x60, north): my 2nd Kontor "Zurich" at 42,50. grain tobacco sugar wine(half).
  Big open land around 40-60 x 40-52. Ship anchor 297,77.
- Island 15 (305,197, 70x60, north): free, grain tobacco sugar WINE (full), ore big 14,33. Very forested.
- Island 1 (244,186, 40x40, north): free, not explored yet.
- Neighbours: ClaudeJev island 10 (west), Sol island 11 (east), SolJev island 14 (SW).

## Round 1 (0:00 - 0:15)
- Founded home at ~2:30 game time. Order: market 21,17, 2 foresters, fisher 27,9, roads, 9 houses with
  the starting wood. Then 2nd Kontor on island 9 (100 g, 3 tools, 6 wood from the ship).
- Wood was THE bottleneck: 4 foresters by 0:08, still only ~2-14 t in stock. Kontor buys wood at 30 from
  the free trader (works, it bought some). Tools bought at 75 up to 40 t, then switched off.
- In this build settlers need cloth AND alcohol, but houses rise to settlers with cloth 100% and
  alcohol 0% (satisfaction stays 128). First settlers at 0:13 after sheep farm + weaving hut + chapel.
- Discovery radius is small: sailing at 292,192 did NOT discover island 15 (bbox 305,197);
  had to sail into the island's bounding box (308,214). Sail close to the coast.
- `explore SHIP` only works when the ship lies still at an undiscovered-content island.
- Kontor room is 40 t per good here (not 30).
- Chat is flooded by the Jev bots' treaty echoes; ignore.
- State at 0:15: 59 inhabitants (30 pioneers, 11 settlers), 19 houses, money 11.4k, balance -106/min
  (wood purchases), 2 fishers, 4 foresters, sheep+weaving, chapel.

## Round 2 (0:15 - 0:33)
- 0:17 quarry 29,15 + stonemason 28,10 (unlocked at 15 settlers). Bricks come slowly (~2 t/min).
- 0:21 at 40 settlers sugarcane + rum distillery unlocked; 0:23 sugarcane plantation 9:42,45 (22 fields,
  some tiles "does not grow here" even on a sugar island), 0:27 rum distillery 9:45,49.
  Route ship 2: load alcohol 3 at 9 -> unload at 12. First 2 t alcohol at home 0:32.
- TRAP: a plantation next to a road diagonally is NOT connected; the road tile must touch an edge.
- TRAP: roads cannot cross slope '/' or beach 'b'. Fisher 33,6 had no possible road -> demolished (lost).
  Check that a road path exists BEFORE placing a coastal building (lay the road first).
- Fish grounds on island 12 are poor: 2nd fisher right next to the first got only 38% (shared water);
  demolished. Hunter 16,20 instead (cheap: 50 g, 2 tools, 2 wood).
- BIG LESSON: foresters showed "idle, stock 2-3 t" = full, nobody collecting. One market's carts are not
  enough for 5 foresters + fisher + stonemason. Built a 2nd market 21,30 right among the foresters at 0:32.
  Build the 2nd market EARLY (after ~4 foresters).
- Tax test: settlers at 144 with alcohol 0% -> satisfaction 111 -> back to 128. Pioneers at 144 stay 128.
- 100 settlers at 0:28 unlocked: spices, tavern, fire station, warehouse_2, grain/bakery (school, toolmaker
  were not in the list yet). Next unlock: 150 citizens.
- 0:33 spice plantation 12:35,32 with 29 fields.
- State 0:33: 160 inhabitants (6 pioneers, 126 settlers), 26 houses, money 6.4k, balance about -80
  (free trader wood purchases at 30), taxes 196 vs running costs 140.

## Round 3 (0:33 - 0:48)
- Alcohol 100% at 0:34 -> settlers tax 144, then 160: satisfaction stays 128 with cloth 57-100% and
  alcohol 100%. Pioneers at 160 also fine. Income 196 -> 335/min.
- Food got short (fishers poor). Cattle: 2 cattle farms 36,25 / 38,20 + butcher 32,31. Butcher only ~25%.
  Free trader sells food at 26 (`trade ... food buy 15 40` -> price capped at 26).
- CARRIER LESSON (again): workshops take raw goods from the market/Kontor stock, not straight from the
  farm. Weaving hut said "no wool in the Kontor" while the sheep farm held 1.8 t. Each production
  cluster needs a market (carts) close by. 3rd market 34,27 at 0:45 next to the farms.
- warehouse_1 can not be placed inland (0 sites): it is coastal like a Kontor. Use a marketplace.
- FORESTER LESSON: foresters packed together (5 within 10 tiles) dropped to 12-26% after ~30 min.
  New foresters in untouched forest (28,35 / 25,38) ran at 82-96% at once. Spread foresters >= 6 tiles
  apart and move them into fresh forest when they fall below 30%.
- Mystery: the weaving hut was "switched off" and the Kontor got a bricks buy order (33) that I never
  set. Somebody/something clicks in my window. Check `production` for "switched off" every review.
- ROUTE TRAP: a route "load wood 4" at a Kontor that has no wood blocks the ship forever. Only load
  what the source has, and remove one-time material loads after one trip.
- Bricks: 2nd quarry 33,15 + stonemason 36,15 (95%). Bricks now pile up (31 t).
- 0:42 tobacco plantation 9:48,49 (33 fields), 0:47 tobacco products 9:46,52.
- State 0:47: 232 inhabitants (179 settlers), money 2.5k and falling ~100/min (purchases). Cut buying.

## Round 4 (0:48 - 1:03)
- 0:49 tavern 23,27 (demolished a weak forester in the centre) + school 24,30: 23 of 30 houses covered.
- 0:52 first citizens (needs tobacco goods 100%, spices 100%, alcohol 100%; cloth can be low).
  Citizens 8 -> 45 by 0:57. Citizens tax 144 ok (sat 124-128).
- MONEY CRISIS: 7.5k at 0:30 -> 539 at 1:02. Causes: free-trader purchases (wood 30, tools 75, food
  26, about 100-180/min!) + running costs of plantations (35 each) before they paid. The "balance"
  in `state` includes purchases and lags ~1 min.
  Fix that worked: stop tools/wood buying, switch off spice plantation (stock 18 t), both stonemasons
  (bricks 46 t), tobacco plantation + products (stock 10 t). Money rises again.
  RULE: never let money fall below ~3000; plan purchases; switch off producers whose stock is > 10 t.
- Pioneers' tax resets to 128 when the class empties (it did); set it again after.
- PLAGUE at 1:00 (city > 200 settlers): spread to 5 houses, citizens 45 -> 19. Doctor still locked
  (no unlock shown). Plague ends per house after its duration; did not demolish.
- Tools are needed for every rise (citizens 2 t each). Tools 0 stopped rises silently.
- More houses: 43 houses by 0:58 (3rd chapel 36,31 for the east).
- Food: 2nd butcher 39,26; 4 cattle farms (2 with poor meadow removed). Food stock 13 and rising.

## Round 5 (1:03 - 1:17)
- Plague destroyed 7 houses (they vanish, sites become free). Rebuilt them + 4th chapel 20,33 and
  8 more houses (51 houses at 1:06). Plague returned at 1:16 (31,22). Doctor stays locked.
- Rises are slow (~1 house per 30-60 s) but steady once tools/wood/bricks are in stock.
- 1:10-1:12 balance turned positive (+59, +123) with 320 inhabitants (167 settlers, 60 citizens).
- Wasted trip: sailed 140 tiles to ClaudeJev (Worrach 10:5,14, sea 94,90) to buy wood at 15;
  by arrival they had stopped selling. Kontor offers change fast: don't sail far for them.
- Everybody wants tools (Sol, ClaudeJev 80, SolJev 75). An own tool chain would sell well.
  Ore mine: 0 sites on island 12 - the ore mountain (45-55, 7-21) is outside my territory;
  needs a market near 44,12 first. Chain cost ~1550 gold, 20 tools, 33 wood, 14 bricks.
- Foresters: utilisation swings a lot (96% -> 3% for the same building within minutes). They need
  ~40 grown trees in radius 3; houses built into their window ruin them.

## Round 6 (1:17 - 1:31)
- Balance steady +120..+156/min with taxes settlers 152, citizens 144, pioneers 160. Citizens at 160
  fell to satisfaction 104 (cloth 54%) -> back to 144.
- 2nd sugar plantation 9:43,40: only 14 fields, "does not grow here" on 14 tiles. Island 9's
  sugar fertility is patchy; try fields before choosing the plantation spot.
- Bought 40 t wood from Sol (Zaustaden 11:61,21, sea tile 402,97) at 10 each = 400 gold. Trip from
  island 9 ~45 s, back home ~70 s game time. Worked; check `cities 11 0` just before sailing.
- TOOLS are everyone's bottleneck: ClaudeJev pays 110, Sol 105. The free trader seldom brings them.
  Every citizen rise needs 2 t, every sheep farm / fisher / forester 2-3 t. Tools at 0 for minutes
  stalled cloth, food and rises at once.
- Prepared the tool chain: road 36,19 -> 43,16; market site 43,13 (then ore mine on the mountain
  45-55 x 7-21, deposit 49,9).
- State 1:30: 390 inhabitants (239 settlers, 75 citizens), money 2.6k, cloth 60%, food 9.8 t.

## Round 7 (1:31 - 1:46)
- Free trader stopped visiting for ~10 min; food ran out (0.4 t) and tools stayed 0, inhabitants
  404 -> 361 (starvation). Every player wants tools (Sol 140, ClaudeJev 110).
- Engine (trader.cpp): the free trader sails to the Kontor (of the 12 nearest) that PROMISES HIM
  THE MOST PROFIT: cheap sell offers of mine + high buy prices of mine. After setting sell offers
  cheap (bricks 15, wood 8, tobacco goods 30) and tools buy 140, he came within a minute and
  brought tools + food. Use cheap surplus offers as bait.
- Demolishing gives nothing back (no tools refund).
- Food math: demand 0.95 t per 80 inhabitants per minute -> 360 people need ~4.3 t/min. My fishers
  + 2 butchers make ~2 t/min. Cattle farms make little (14-63%); butchers sit idle.
  The deficit is cheaper to buy (26/t = ~60 gold/min) than to starve.
- 1:42 cattle farms 43,32 + 46,35 (1 tool each), sheep farm 44,38 (meadow 53), roads 40,29->45,37.

## Round 8 (1:46 - 1:53, game ended)
- Island 9 has far better fishing grounds (fisher sites score 25-34 vs 12-22 at home). Fisher 9:45,54
  ran at 80% at once; route ship 2 now also carries food home (load food 2 at island 9).
- Hunter 44,35 (30%, but its stock lay uncollected) -> 4th market 41,35 among hunter, cattle, sheep.
- Bait confirmed again: the trader bought 10 t bricks at 15 and brought tools/food.
- Citizens recovered 59 -> 90 within 3 minutes once food and tools came.
- The game was ended at ~1:54 (all windows closed). Last state 1:53: 395 inhabitants
  (226 settlers, 90 citizens, 0 merchants), money 4862, balance +131/min, 51 houses, 4 markets.

## What I would do differently next game
1. 2nd market after 4 foresters; one market per production cluster from the start.
2. Plan the tool chain at 100 settlers: market at the ore mountain, ore mine + smelter +
   2 toolmakers. Tools are the scarcest good for every player and sell at 110-140.
3. Food: count 0.95 t per 80 inhabitants per minute and build ahead; look for fishing grounds
   on other islands early (`sites fishers_hut I`).
4. Keep money >= 3000; never run open-ended purchase orders.
5. Keep cheap surplus sell offers in the Kontor all the time, so the free trader keeps coming.
6. Don't build houses into forester windows; spread foresters.

## Next steps
- 15 settlers -> quarry/stonemason (stone near ^ at 30-34,11-16 behind the Kontor).
- Then bricks -> sugar plantation + rum distillery on island 9 (route ship), tavern.
- More houses as wood allows; 3rd fisher at ~80 people.
