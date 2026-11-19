# Anno 1602 economy reference (web research, 2026-11-07)

Sources:
- `[BID]` <https://anno-capsu.netlify.app/1602/building_industry_data>
- `[PPI]` <https://anno-capsu.netlify.app/1602/population_per_industry>
- `[PE]` <https://anno-capsu.netlify.app/1602/production_efficiency>
- `[IP]` <https://anno-capsu.netlify.app/1602/industry_planning>
- `[CM]` <https://anno-capsu.netlify.app/1602/colony_management>
- `[CP]` <https://anno-capsu.netlify.app/1602/colony_planning>
- `[EC]` <https://anno-capsu.netlify.app/1602/essential_concepts>
- `[TD]` <https://anno-capsu.netlify.app/1602/trade_diplomacy>
- `[AP]` <https://anno-capsu.netlify.app/1602/ai_trade_prices>
- `[RES]` <https://anno-capsu.netlify.app/1602/resources>
- `[GS98]` GameStar 06/1998: <https://download.gamestar.de/public/33500/33587/06_1998_tipps_anno1602.pdf>

The fan FAQ and GameStar 1998 disagree in places. **The engine's own data wins.**
- Run `python tools/planner/plan.py` (it reads `tools/planner/game_data.json`, extracted from
  haeuser.cod).
- Check `o1602-ctl cities` ("next class ... will need") in the running game.

## Classes

| Class | People per full house | Taxes per person per minute | Rises with (FAQ; GS98 differs) |
|---|---|---|---|
| Pioneers | 2 | 1.95 | cloth, chapel, market |
| Settlers | 6 | 2.11 | tobacco or spices, alcohol, tavern, school |
| Citizens | 15 | 2.44 | cocoa, church, bathhouse |
| Merchants | 25 | 2.53 | jewellery, clothes, college, theatre |
| Aristocrats | 40 | 2.65 | (top class) |

Public buildings in the Open1602 engine (`sim/src/houses.cpp` kServiceNeeds, authoritative):
- Pioneers: market or Kontor.
- Settlers: market, chapel or church.
- Citizens: market, tavern, chapel or church, school or college.
- Merchants: market, tavern, **church**, school or college, **bathhouse**.
- Aristocrats: market, tavern, church, college, bathhouse, theatre.

A house rises only when:
- it is full;
- food is supplied 100%;
- the next class is at satisfaction 128;
- the next class's public buildings reach it;
- the materials of the new house are in the Kontor.

Goods eaten per 80 inhabitants per minute `[PPI]`:
- Food: 0.95 for every class.
- Cloth: settlers 0.45, citizens 0.50, merchants 0.55.
- Alcohol: settlers 0.35, citizens 0.45, merchants 0.50, aristocrats 0.55.
- Spices: citizens 0.35, merchants 0.45.
- Tobacco goods: citizens 0.35, merchants 0.45.
- Cocoa: merchants 0.50.
- Clothes: aristocrats 0.35.

## Unlocks (FAQ; the game's `state` shows the next one)

- 15 settlers: quarry, stonemason, fire station. GS98 says 50 pioneers.
- 40 settlers: sugar, tobacco, winery.
- 75 settlers: spices.
- 100 settlers: toolmaker, school.
- 120 settlers: iron mine, ore smelter, small shipyard.
- 150 citizens: church.
- 200 or 210 citizens: bathhouse, cotton, tailor, cocoa.
- 250 merchants: college.
- 300 merchants: theatre.

In this game the unlock steps were 100 settlers, then 150 citizens, then 210 citizens.

## Chains at full speed (t/min) and setups

| Chain | Setup | t/min | People fed (hungriest class) |
|---|---|---|---|
| Fish | fisher | 0.75 | ~63–70 |
| Hunter | hunter | 2.0 | ~168 |
| Cattle | 2 cattle farms + butcher | 2.3 | ~200 |
| Cloth | 2 sheep farms + weaving hut | 1.95 | ~283 |
| Rum | 2 sugarcane plantations + distillery | 2.5 | ~350 |
| Wine | winery with ~24 vines | 1.15 | ~167 |
| Tobacco | 2 plantations + tobacco products | 1.9 | ~340 |
| Spices | 1 plantation | 1.4 | ~248 |
| Cocoa | 1 plantation | 1.4 | ~248 |
| Tools | 1 ore mine + 1 smelter + 2 toolmakers | — | — |

- Tools: ore + wood make iron, 1 iron makes 2 tools.
- Bricks: a quarry next to a mountain plus a stonemason. The quarry costs nothing to run.
- Rule of thumb: 2 raw producers per workshop. Below 75% utilisation a building wastes money.

## Money (what went wrong in the first game)

- Keep taxes above running costs at every step. Build houses before you build luxury.
- Build a tavern, school or bathhouse only when the goods for the next class are already flowing.
  Built too early, they cost running costs for nothing.
- The free trader sells tools at about 70–75 per ton. Kontor buy settings default to the AI
  price of 105, so set a lower price: `trade ... buy TONS PRICE`.
  - Buy tools early, while gold is plentiful.
  - Stop buying once you make your own tools.
- Kontor trade slots (buy/sell): Kontor I 4/3, II 7/4, III 8/6, IV 11/8. When all are used, a
  new trade setting is refused.
- Never sell goods a class consumes. Keep 10 t of food and alcohol when selling.
- Raising the tax above 128 cost inhabitants without raising income (settlers at 150: −26
  people). Raise it only for classes with spare satisfaction.

## Layout

- Market reach 15, church 20, bathhouse 19, school 12, tavern 11–12 (the smallest), chapel 8.
- Plan a quarter around a central tavern: everything else reaches farther.
- Working ranges:
  - Forester 3: needs trees; plant `forest` around it.
  - Sheep farm 3: needs open grass.
  - Plantations 2: fields right around them.
  - Fisher 6: needs open water.
  - Weaving hut, toolmaker, bakery 15.
- Farms that carts serve need a road; `find-site` reports `road` or `no-road`.
- Special crops (tobacco, vines, sugar, spices, cocoa, cotton) die on islands below 100%
  fertility. "(half)" in `islands` means 50%: avoid those.
