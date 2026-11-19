# Self-tournament 2 of 2026-11-19: the same game with the reworked skills

The same world, start positions, rules and models as the first self-tournament of the day
(`../selbstturnier-2026-11-19/`), played again after its lessons had gone into the skills and the
control port (commit 7de9e281). One game each, so the differences are a hint, not a proof.

| Place | Model | Inhabitants | First game | Gold | Balance/min | Calls of o1602-ctl | Tokens |
|---|---|---:|---:|---:|---:|---:|---:|
| 1 | Opus | 287 | 231 | 3,451 | +2 | 72 | 183 k |
| 2 | Fable | 284 | 155 | 947 | -90 | 95 | 218 k |
| 3 | Sonnet | 181 | 105 | 2,335 | -226 | about 41 | 164 k |
| 4 | Haiku | 78 | 59 | 10,246 | -80 | 50 | 178 k |

Inhabitants, gold and balance are the referee's (`scores.txt`, from the save at 0:30:10). The calls
are the agents' own counts, the tokens what the session reported for each subagent.
`timeline.log` has every player's figures once a game minute.

What changed in play, by the players' own reports:

- Sonnet settled where sheep farms worked and bought cloth from the first minutes: 98 settlers
  instead of none.
- Fable kept land for houses and moved bare foresters: 75 houses instead of 32. It again spent
  nearly all its gold on tools.
- All four still ended without bricks, so without tavern and citizens: in 30 minutes nobody
  reaches the third class.

What the players reported as still wrong or missing:

- `ship-move SHIP X Y` to a land tile answers "sailing" and the ship stays; the opening's "sail into
  the island's rectangle" led one player into exactly that.
- `sites` finds no place before the city is founded, so the island cannot be judged with it first.
- A batch of `found`, `unload` and builds fails as a whole when the ship is out of reach.
- `build house I auto` without X Y takes places outside every chapel; auto without X Y may put two
  foresters side by side.
- The wood a bridge costs is not in the answer of an auto road.
- Opus sent one `ship-move` while the game still stood paused before the start (its wait loop took
  "running costs" for "running"); the order was carried out when the clock started.

The first four of these are answered in the commit that adds this file: `ship-move` takes the
nearest sea tile, `sites` answers before a city stands, `found` sends the ship to the new Kontor,
`auto` keeps producers of a kind apart, says what reaches a house and counts the bridges.

Haiku ended its turn before the start in both games and had to be told to go on.
