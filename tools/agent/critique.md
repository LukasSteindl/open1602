# Critique (game 4:47 - 5:19, money -43 -> 578, balance -15 -> +160, 254 -> 374 inhabitants)

Observed with state/cities/production/alerts/houses/map/sites plus screenshots of island 17 (north, centre, west, SE, south coast) and island 9. The game ran at x8 during the review, so a few numbers moved; the latest values are given.

## 1. The trade route carries the one good the colony doesn't have, and leaves behind the goods home is short of
- Evidence: route 1 = "island 9 load wood 25 / island 17 unload wood 25". Colony wood is 0.0 t ([MATERIAL]), so the ship sails empty. Meanwhile the colony holds **food 49 t (storage full, both fishers 20,30 and 30,32 FULL, stopped)**, **wool 29-42 t** and **tools 19 t**. Home is running out at the same time: the plan shows `[RUNOUT] food 1.2 t, empty in 0.7 min`, the weaving hut 20,23 is at 0-15% with "no wool delivered", and home tools are 4-12 t of the 56 the plan needs.
- Two Kontor orders work against home: the colony **sells wool above 20 t at 12** (the cheapest wool on the market goes to traders), and it **buys tools up to 20 t at 75** while it builds nothing.
- Fix now: route stop 0 (island 9): load food 40, wool 40, tools down to 5 t. Stop 1 (island 17): unload all of it. On the colony set `trade 9 0 wool none` and `trade 9 0 tools none`.
- Driver: rebuild the route's cargo list every review from (colony surplus or full store) x (home shortfall or RUNOUT), for every good, not only wood. Drop a leg whose good the colony doesn't produce. Never let one own Kontor sell a good another own city lacks, or buy a good another own city holds.

## 2. 57-69 houses lack a chapel; only 2 chapels exist, both in the far west, while a school and a tavern got built
- Evidence: chapels at 16,19 and 19,28. `houses 17` reports "54-69 lack chapel for the next class", all in the north row (y 10-16, x 26-49) and the whole SE (x 27-48, y 27-45). Those are pioneer houses with 1 inhabitant each; settler houses hold 3-4. In the same window the driver built a **school at 38,30 (300 gold, 30/min)** and a **tavern at 22,36**, although no house can become a citizen yet.
- Measured chapel reach is about 10 tiles (19,28 reaches 27,32 and 22,36 but not 30,32 or 24,38). A chapel on the free 2x1 at **35,35** would cover **25** of the uncovered houses, and one at **33,16 / 34,16** about **13** more (north row and east).
- Fix now: build a chapel at 35,35 (100 gold, 5/min), then one at 33,16.
- Driver (`options`, services block ~l.1345): the site is found with `find-site` around the centroid of all missing houses. The north and SE groups average out over the bay/river, so the pick is poor or fails. Score candidate places by the number of uncovered houses within 10 tiles and take the best. The comment says "chapel 8"; the measured reach is ~10. Hold tavern/school (`citizens_next`) back until fewer than ~10% of houses lack a chapel.

## 3. Alcohol is sold to traders while it is about to run out
- Evidence: home Kontor "sells alcohol above 15 t at 40". The plan shows `[RUNOUT] alcohol 13.9 t, falling 6.3 t/min, empty in 2.2 min`. The 2 wineries run at 20-28% (25,35 has 5 vines among houses, 35,40 has 12), together about 1.1 t/min.
- Fix now: `trade 17 0 alcohol none`.
- Driver: the "storage full -> sell above X" fix must be undone when the good's trend is falling or a RUNOUT is shown. Sell only while production exceeds consumption.

## 4. Cloth chain: the home island has no meadow, and the only home sheep farm stands on the beach
- Evidence: sheep farm 29,45 has 5 meadow and 5 forest tiles (alert) and runs at 6-20%; the screenshot shows it on the south shore between beach and houses. The best home sheep site scores only 2 (`sites sheep_farm 17`). The colony farm 9,14 runs at 13%; the colony's best site is **28,8 (score 11)**. Home buys cloth from traders up to 15 t at 37.
- Fix now: demolish 29,45. Wool reaches home by ship (item 1). Move the colony farm to 28,8 (needs a road).
- Driver: never build a sheep farm with a pasture score below ~8. Don't count farms under 30% toward the "3 per weaving hut" ratio. For more wool, scout an empty northern island with open meadow (island 2, 4 or 12) for a wool colony.

## 5. Wood: one working forester for the whole economy
- Evidence: home wood 0-12 t of the 56 the plan needs ("more foresters"). Producers: 50,28 at 97%, 49,12 at 0-35% (sat on 10 t uncollected until the piers at 42-43,11 went in), and colony 10,22 at 1% (12 trees, wants ~40). Colony wood is 0, so the wood leg of the route is empty.
- Fix now: foresters at **48,27** and **51,37** (40 trees each, road at the side, in the big eastern forest). Demolish colony forester 10,22.
- Driver: build a forester only where `sites forester` scores 30 or more. Remove "load wood" from the route once the colony produces none.

## 6. A new fisher at 23,8 with 6 fish-ground tiles
- Evidence: alert "[?] fishers_hut at 23,8: 6 fish-ground tiles in reach". This was built after the "threshold 10 fish-ground tiles" rule (review 16:5x). Fisher 42,45 also showed 0% right after it was built.
- Fix now: demolish 23,8 and build at **48,7** or **38,8** (score 25, road).
- Driver: some fisher path (probably the food RUNOUT / chain path) bypasses the threshold. Enforce it in every place that builds a fishers_hut.

## 7. Road links over a river silently do nothing
- Evidence: the log repeats "Netz: forester at 49,12: road of 0 new tiles over 13 / 9 tiles" (292:17, 307:49) and "fishers_hut at 35,8: road of 0 new tiles over 9 tiles". `road_path` crosses 'w' at cost 3, then `lay_path` sends `road` over river tiles, which fails, and still reports success. `find-site wooden_bridge 17 42 12` gives 0 places, so this river mouth can't be bridged at all. The links were finally made with piers (34,9-10 and 42-43,11), which means a ~30-tile cart detour for the east cluster.
- Driver: in `lay_path`, build `wooden_bridge` on 'w' tiles and check the result. Where no bridge fits, exclude those tiles from `road_path` (cost None), so it falls back to piers right away. Log "FAILED" when laid == 0 and the path isn't already road.

## 8. About 13 ruined house plots are left standing in town
- Evidence: 51 'x' tiles on `map 17`, for example 20-23,38-39; 37-38,27-31; 43-45,29-37; 47-48,37-40; 38-43,38-41. They come from fires (log: [FIRE] at 23,13 and 20,38) and demolitions, and are never cleared or rebuilt. House count fell from 92 to 80, while the driver keeps hunting for house places on the outskirts.
- Fix now: demolish the ruins and rebuild houses there (3 wood each, inside existing market, school and tavern reach).
- Driver: add a `clear_ruins` option. House-site search should treat ruins as free after demolition.

## 9. Bricks: the plan wants 130 t though the Kontor holds 80
- Evidence: bricks have stood at 80/80 for most of the run ([STORE] full), sold above 40 t at 22. The plan still says "bricks 57-79/130: more stonemasons". Stonemason 40,14 stands on a river islet and runs 5-79%.
- Driver: cap every material target at the Kontor's room (80 t). Don't offer stonemasons while bricks are at 50% or more of room.

## 10. Running costs with no current benefit
- Evidence: school 38,30 (30/min, no citizens possible yet, see item 2) and fire station 35,27 (15/min). Home has 5 marketplaces (50/min); 37,41 and 40,35 are 6 tiles apart. The colony has 2 marketplaces (18,13 and 10,24) for 17 houses. Running costs are 310-325 against taxes of 297-541.
- Fix: no new market or public building until the chapel gap is closed. Check `coverage` on the colony before dropping market 10,24 (the Kontor 29,26 already serves the east).

## 11. Next stage: tobacco at home, spices from abroad
- Island 17 has tobacco (full): a tobacco plantation plus tobacco_products belongs at the east edge (x 50-60, y 15-25, where the free '.' land lies beyond the forest; claim it with a market first). Spices only grow in the south: natives on island 3 (170,210, spices full, treaty yes) take cloth and alcohol. Both are scarce, so fix items 1, 3 and 4 first. Island 7 (280,280) is free, with spices full, for a later plantation colony.
