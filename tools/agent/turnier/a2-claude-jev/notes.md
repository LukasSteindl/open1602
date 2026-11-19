# Notes of agent 2 "ClaudeJev"

## Round 1 (game of 2026-11-09, start 0:01:44 game time)

World: 500x350, 18 islands. Start ship "Altair" (id 3) at 83,87 next to island 10 (70x60, north,
crops grain/tobacco/sugar, wine half, ore O at 22-28,40-44 and 45-48,30-38). Neighbours: Claude on
island 12 (south, 215,92), Sol on island 11 (337,75).

Driver fixes before/at start (all in my jev_driver.py copy):
- Opening hung: `ctl()` caches read-only answers; the opening loop never cleared CACHE, so the
  Kontor I founded by hand stayed invisible ("no city yet" forever). Fix: CACHE.clear() per loop.
- Exploration move +12,+6 went onto land and failed silently -> try 6 directions.
- Paused game: driver called `resume`/`speed` (referee's job, refused) -> now waits.
- CHAT_EVERY 60 -> 300 s (stream: one line every few minutes at most).
- The running opening loop does not restart on file change: kill the python process
  (Get-CimInstance ... CommandLine like '*a2-claude-jev*jev_driver.py*'), the runner restarts it.

Opening by hand (driver hung): ship-move 89,92 discovers island 10; found 3 10 5 14 (Kontor world
97,89); unload only works within 5 tiles: ship-move 95,89 first. Kontor room 30 t (40 t later).

Early mistakes of Jev: two chapels beside the Kontor before any house (10 t wood, radius 8 does
not reach the houses at 9,21..). Wood is the bottleneck from minute 6 -> Kontor buys wood
(`trade 10 0 wood buy 30 25`).

### 0:14-0:23
- Plan picked a winery for the half wine of island 10 -> setup(full, []) (skill rule: no half crops);
  now rum distillery + sugarcane. Plantations, winery, rum, tavern all need bricks (8/5/6 t):
  stonemason unlocks with settlers, so bricks before alcohol.
- Chapel rule: public buildings were built at the Kontor (cx,cy) -> now at the houses' centroid,
  none before 4 houses. Built chapel 10,29 by hand, demolished 5,13.
- Both Jev drivers answered each other's "Handel ja" chat forever -> answer each seat once, skip
  seat 0 (referee) and lines with "handel ja", no forced chat.
- Wood: 4 foresters at 26-97 %, 3 t wood in stock at 22 houses. +2 foresters (17,27 and 22,10,
  0 wood each, 50 gold) -> both 100 % at once. Forester needs no wood: the cheap answer to a wood
  crunch.
- Pioneers at tax 192 still satisfaction 128. Balance -88/min at 59 inhabitants, money 10k.
  Kontor buys alcohol 15 t at 55 to lift settlers early (cloth from sheep 24,22 + weaving 5,12).

### 0:30-0:41
- 0:38: 189 inhabitants (83 settlers) but money 8.2k -> 4.9k in 8 min: building spree plus running
  costs 180 (7 foresters, 5 chapels, 4 markets, 3 fire stations = 45/min). fix_service_gaps built a
  "second fire station" for every 6 houses beyond reach. Demolished two; service gaps now only above
  15k gold; affordable() keeps 3000 gold back for gold-costing builds while the balance is negative.
- Free trader (engine trader.cpp): he sells to a Kontor only what he bought from other Kontors (plus
  seeded tools/ore), and only if our buy price is above his average. So "buy wood/alcohol" orders do
  nothing unless some player sells it. Wood must be own production.
- Forester rule: cap 6 -> 10 while wood is short, but only at >= 35 trees (old 24). Foresters in thick
  forest (33,31; 39,20; 17,27; 22,10) run 90-100 %, the ones near town 24-26 %.
- Quarry 45,29 (on the '/' rim of the ore mountain) + stonemason 46,24: bricks for plantations,
  tavern and citizens. Unlocked once settlers came (stonemason, quarry, butcher, cattle).
- Settlers at tax 144 fall to satisfaction 111 (alcohol 0 %): stay at 128 until alcohol exists.

### 0:47-1:00 money crisis
- 0:47 food 1.8 t at 275 inhabitants with ONE fisher: houses took every ton of wood (3 t each), the
  fisher (5 t) never came. Rule: food < 20 t -> houses keep 6 t more wood. Jev then built 5 fishers
  at once (500 gold) -> money 4.2k -> 1.5k.
- 0:53 money 1641: stopped all Kontor buying (trader bought tools 10 t for 750 gold at once!),
  demolished stonemason 0 % and forester 19 %. affordable() now keeps 2500 back always (3000 with
  negative balance); tool buying only above 6000 gold; tax_down option and tune_taxes accept
  satisfaction 104 when a good is at 0 % (settlers without alcohol cannot rise anyway; falling < 88).
- Settlers at 144: satisfaction 111 (no alcohol), income +.
- Wool: one sheep farm at 50,26 for a weaving hut at the Kontor (5,12), 45 tiles of road: 13-35 %.
  Second sheep farm at 7,7 right beside the weaving hut, road 7,9-7,14 (chapel 7,14 demolished).
- Stonemason: needs the quarry inside its city and radius 7 (logistics.cpp: stonemason works the
  quarry tiles like ripe fields). 46,24 stayed 0 %, Jev rebuilt one at 41,33 - watch it.
- Other players' Kontors (Claude 12 & 9, Sol 11, SolJev 14) offer nothing yet. Treaties signed.

### 1:00-1:15
- Houses stalled with 100 t wood and 180 free places: house_site() blocked every forester's 8x8
  forest window (9 foresters) and looked at 40 places only. Fix: foresters don't block while wood
  >= 40 t, 120 places. Then 118 pioneer houses within minutes, 424 inhabitants, balance +270.
- Jev demolished my sheep farm 7,7 ("too little meadow") before it got its road. Meadow is scarce
  on island 10 (best site score 22): wool stays the cloth bottleneck; the farm at 50,26 has 5 t
  waiting that carriers fetch slowly (45 tiles to the weaving hut at the Kontor).
- Settlers fell to satisfaction 84 (cloth 61 %, alcohol 0 %): tax 112 by hand.
- Tools are the gate for everything (quarry 6 t, chapel 2, weaving 3, ore mine needs bricks):
  trader only. Kontor buys tools 15 t at 80, cloth 10 t at 50; asked in chat for tools/cloth.
- Next round: build quarry 44,32 (free land beside it, next to stonemason 41,33) as soon as 6 t
  tools lie there; then sugarcane + rum (bricks 8+5) for alcohol; weaving hut beside sheep 50,26.

### 1:15-1:28 tools famine
- Foreign Kontors (visible to any player): SolJev sells bricks 29 t at 13 (bought all, 377 gold, ship
  trip 94,89 -> 191,238 and back ~3 min game), Sol sells wood 10 and bricks 25 and BUYS tools at
  105, Claude buys tools 75. Everyone is short of tools -> our bid 110 (driver too).
- Demolishing returns nothing (tested: forester, tools unchanged).
- Jev spent every ton of tools on chapels (8 chapels in 30 min) while food was at 1 t and cloth at
  25 %; settlers fell 188 -> 128 at tax 64. New rule: tools < 10 -> food first, then wool/weaving,
  chapels only while cloth >= 95 %. No new houses while food supply < 95 % and stock < 5 t.
- Sheep/cattle farms are no longer pulled down for "too little meadow" while tools < 20.

### 1:33-1:45
- 1:42: 507 inhabitants (279 pioneers at 192, 167 settlers at 128), balance +447, money 10k.
- Fire in the north (houses 20-23,8-14 + forester 22,10) out of every fire station's reach:
  station 28,20 + road 25,21-27,21 (the road command bridges a river tile by itself, 2 t wood).
- Food stuck at 84 %: west/north fish grounds have 11-12 fish tiles per hut. East coast 56,5 has 33
  (road at row 7). Claude now bids 150 per t of tools: the trader's tools go to the best bid.

## Stand bei Spielende Tag 1 (Schiedsrichter pausiert + gespeichert bei 1:54:33)

Letzter eigener Blick 1:50: 493 Einwohner (283 Pioniere Steuer 192, 143 Siedler Steuer 80,
Zufriedenheit 67), Geld 10.8k, Bilanz +294/min (Steuern 689, Betrieb 335). 156 Pionier- und 33
Siedlerhaeuser auf Insel 10 (Worrach, Kontor 5,14). Lager: Holz 60, Ziegel 19, Werkzeug 4,
Nahrung 4 (Versorgung 100 %), Tuch 0 (35 %), Alkohol 0 %. Schiff 3 "Altair" leer am Kontor (94,89).
Kontor kauft: Werkzeug 25 t zu 110, Tuch 10 zu 50, Nahrung 20 zu 20; verkauft Holz ueber 20 t zu 15.

### Plan fuer morgen (Reihenfolge)
1. notes.md lesen; pruefen, ob der Treiber nach dem Laden wieder laeuft (state\driver.log). Laeuft
   die Eroeffnungsschleife, sie erkennt die Stadt jetzt (CACHE-Fix); sonst Python-Prozess beenden.
2. Werkzeug ist der Flaschenhals von allem (nur der Haendler bringt welches, Claude bietet 150,
   Sol 105): Gebot ggf. auf 120-150 heben, solange Geld > 8000. Eigene Werkzeugkette (Erzmine
   1000 g/10 t Werkzeug/20 Holz/5 Ziegel + Schmelze + Werkzeugmacher) sobald ~20 t Werkzeug da sind:
   Erz liegt am Berg 22-28,40-44 und 45-48,30-38 auf Insel 10.
3. Tuch: Wolle reicht nicht (eine Schaffarm 50,26, ~70 % nach Rodung). Weitere Schaffarm mit
   Rodung im Osten (Wald x55-63, y21-29 ist noch kein Stadtgebiet -> erst Markt am Rand) und eine
   Weberei neben den Schaffarmen statt am Kontor.
4. Alkohol: Zuckerrohr (2 t Werkzeug, 8 Ziegel) + Rumbrennerei (3 t, 5 Ziegel); Zuckerrohr waechst
   voll auf Insel 10. Ziegel billig bei SolJev (Insel 14, Kontor-Welt 186,238; 13 Gold/t) oder Sol.
5. Steinbruch 44,32 (freies Land daneben, Steinmetz 41,33 steht und laeuft 0 %, weil der alte
   Steinbruch 45,29 zwischen Haeusern und Berg eingeschlossen ist).
6. Nahrung: Fischer Ostkueste 56,5 (33 Fischfelder) beim naechsten Werkzeug.
7. Zweite Insel/Kolonie erst, wenn Werkzeug fliesst.

### Offene Baustellen im Treiber (meine Kopie)
- Werkzeug-Prioritaetsfilter am Ende von options() (Nahrung > Wolle/Weberei > Rest) pruefen, ob er
  nicht zu viel sperrt (bei Nahrung < 100 % bleibt nur "food"/Haeuser/Steuer).
- Schaffarm-Warnung rodet jetzt Baeume im Radius 3 statt abzureissen: beobachten.
- Haus-Sperre durch Foersterwald nur ausgesetzt bei Holz >= 40 t.
- Vier Foerster unter 20 Baeumen (49,44; 33,31; 39,20; 30,46): bei Holzueberschuss abreissen.
- Chat: SolJevs Treiber spammt Handelszeilen; meiner antwortet jedem Sitz nur einmal.
