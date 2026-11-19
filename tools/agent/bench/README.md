# A fixed test game for agents

To tell whether a change to the skills, the control port or an agent's tools helps, play the same
game several times with and without it. `bench.ps1` starts identical games alone (the same seed),
a clock starts and ends them alike, and every run adds one line to `results.csv`.

```powershell
.\tools\agent\bench\bench.ps1 -Mode start -Runs 6          # six games, paused, ports 7801..7806
# start one agent per port with the text of PROMPT.md (PORT, SKILLS and the variant line filled in)
.\tools\agent\bench\bench.ps1 -Mode clock -Runs 6 -Labels plain,plain,plain,steward,steward,steward
.\tools\agent\bench\bench.ps1 -Mode stop
```

The score is `residents` at 0:30:00: the people in the houses, without the workers of producers.
The games run at speed x2, so a run takes fifteen minutes and the agent has about 25 turns.

## What one run is worth

Three runs of the same variant ended at 178, 203 and 244 residents: the same agent with the same
skills in the same world differs by a third. One run per variant shows nothing below that; plan
three, and read a difference only when the ranges do not overlap.

## Results

### 2026-11-19: standing orders (steward) against playing by hand

Claude Opus, skills as of that day, 30 minutes at x2, seed 42.

| Variant | Residents | Mean | Money | Calls of o1602-ctl | Tokens |
|---|---|---:|---|---|---|
| plain: every order by the agent | 203, 244, 178 | 208 | 8,389 / 3,689 / 7,869 | 70, 121, 95 | 175 k, 180 k, 180 k |
| steward: `tools/agent/steward.py` from the first market on | 186, 187, 157 | 177 | 5,557 / 5,399 / 9,006 | 84, 81, 100 | 183 k, 187 k, 183 k |

The steward did not help: fewer residents on average, the same number of calls and tokens. The
ranges overlap (178 to 244 against 157 to 187), so "worse" is not proven either; "no gain" is.
The calls include 20 to 63 looks at `state` per agent while it waited for the start.

Why, from the agents' reports and the stewards' logs:

- **The steward stood still while the agent waited.** The control port serves one connection at a
  time and an `advance` holds it until its time has passed, so the steward got 30 rounds in 30
  minutes instead of 60, and none during a long advance.
- **It spent the early wood on producers before houses** (two houses after eight minutes in one run).
- **With `near` it packed producers together**: foresters two tiles apart, bare within minutes; it
  also built again on a place the agent had just cleared.
- **It built about one house a round**, as wood allowed, while the agents built in bulk when the
  trader had delivered.
- What it did well: taxes (pioneers at 192 from the start) and money (never below 4,700).

Since then the port serves every connection in its own thread, so an `advance` holds only its
caller, and `wait-running` replaces the looks at `state` before the start. What would still have to
change in the steward before measuring again (the first point is done): an `advance` that does not hold the port (or a
steward that does the waiting), houses before wood-costing producers, spacing that also holds with
`near`, and bulk building when wood has piled up.
