# Self-tournament 2026-11-19: four Claude models, one game

One multiplayer endless game (difficulty 1, seed 2026, speed x2), a referee at control port 7701 and
four agents at 7702 to 7705, each a subagent of one Claude Code session with the skills of that day
(`.claude/skills/play-open1602`, `anno1602-strategy`) and nothing else. Two minutes to read, then
30 minutes of game time. The goal: the most inhabitants at the end.

| Place | Model | Inhabitants | Gold | Balance/min | Calls of o1602-ctl | Tokens |
|---|---|---:|---:|---:|---:|---:|
| 1 | Opus | 231 | 6,415 | +6 | 69 | 175 k |
| 2 | Fable | 155 | 343 | -220 | 105 | 205 k |
| 3 | Sonnet | 105 | 9,797 | -22 | about 110 | 160 k |
| 4 | Haiku | 59 | 11,881 | -29 | 45 | 175 k |

Inhabitants, gold and balance are the referee's (`scores.txt`, from the save at 0:30:46: the clock
paused 46 s late). The calls are the agents' own counts, the tokens what the session reported for
each subagent. `timeline.log` has every player's figures once a game minute.

What decided it, by the players' own reports:

- Opus spread fishers and foresters, got cloth and chapels early and had 173 settlers at the end.
- Fable bought tools and wood the whole game and ended 343 gold from bankruptcy; a script of its
  own hid `error:` answers for four minutes. 27 of its 155 inhabitants were workers of producers.
- Sonnet settled an island without meadow: no cloth, so no settlers, 83 pioneers.
- Haiku was slow: 29 inhabitants after 15 minutes, wood at the room limit, houses not built.

What the players reported went into the skills and the control port afterwards (the commit that
adds this file): the opening when nothing is discovered, foresters that cut their window bare,
land kept for the town, meadow before settling, `build ... auto` with bridges and away from
foresters' windows.

`clock.ps1` is the referee's script (start after the reading time, log, pause, save, scores).
