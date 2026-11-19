# Strategy review (Claude Code, every 10 minutes)

The Jev driver (`jev_driver.py`, terminal tab "Jev-Agent") plays turn by turn. This review looks
at the game from above and changes the rules where the driver is stuck, wastes money or misses
something. Goal: as much gold per minute as possible, a growing town, no bankruptcy.

## 1. Look (one batch, no camera moves)

```
bin/o1602-ctl.exe batch state ";" cities 17 0 ";" alerts 17 ";" houses 17 ";" alerts 9
```

and the last 30 lines of `tools/agent/jev_log.jsonl` (decisions, results) plus the terminal tab.

## 2. Check

- **Danger first:** `[FIRE]`, `[PLAGUE]`, money below 500 or falling, balance negative. Act at once
  (fire station or firebreak, demolish idle buildings with running costs, sell surpluses).
- **Stuck:** the same option (or `wait`) for many turns while the plan still misses buildings: why
  is nothing offered? (materials, money brake, no site, a filter too strict)
- **Waste:** buildings at 0-20% for minutes, running costs above taxes, goods bought dearly.
- **Supply:** the present classes' needs (food, cloth, alcohol, ...) below 90%: is the chain there,
  does its raw producer stand and reach its raw material?
- **Plan:** does the stage advance? Is a stage blocked by one missing thing (a material, a site)?
- **Local optima:** something the rules forbid that would unlock progress (a pier with bricks from
  home, a market next to cut-off buildings, a colony that needs supplies).

## 3. Act

- Small, direct fixes in the game via `o1602-ctl` (it is fair: what a player could click).
- Rule changes in `jev_driver.py` / `strategy.py` when the same mistake would come again; restart
  the driver in the terminal tab afterwards.
- **Fundamental errors get a real fix in the driver**, not a one-off click: a missing rule, a wrong
  model of the game (check the engine source under `engine/sim` when unsure how something works),
  a missing game command (add it to `engine/app/src/control_commands.cpp`, fair only: what a player
  can see). Test the change against the running game before restarting the driver.
- **Research**: every 10th review (or whenever the driver is stuck and the cause is a strategy
  question), look up Anno 1602 strategy online (WebSearch: build orders, production ratios, island
  choice, money management, fire and plague, trade) and turn good ideas into rules or planner
  numbers. Note the source in `reviews.md`. Update `.claude/skills/anno1602-strategy` when a finding
  holds.
- Never pause the game for long (viewers watch), keep the camera rule (moves only on actions).

## 3b. The critic

Every 15th review (and whenever a user remark shows a blind spot), start a critic subagent in the
background (Agent tool, general-purpose): it looks at every district through
`o1602-ctl screenshot ISLAND X Y` (read the PNG) plus `production`, `alerts`, `houses`, and
writes a ranked list of concrete mistakes with coordinates and fixes to
`tools/agent/critique.md`, read-only otherwise. When it reports, turn each valid finding into a
game action and, if it would recur, a driver rule; note in `reviews.md` which findings you took.

## 4. Log

Append three lines to `tools/agent/reviews.md`: time, what was wrong, what changed.

## Selbstreflexion für die Zuschauer (jede Review)

Nach dem Protokollieren 1-2 Sätze auf Deutsch in `tools/agent/reflection.txt` schreiben (überschreiben):
was gerade schiefläuft oder gelungen ist und was daraus folgt, ehrlich und in Ich-Form, ohne Technik-Jargon,
höchstens ~200 Zeichen. Der Fahrer zeigt den Text oben im Plan-Overlay und sagt ihn einmal an, sobald er sich ändert.
Wenn sich nichts Neues ergeben hat, den alten Text stehen lassen.


## Schiffsrouten (Nutzer, gelegentlich)
Etwa jede 5. Review alle Routen prüfen (`route SHIP show`, `ships`): Stimmen Quelle und Ziel noch (Ware vorhanden, wird am Ziel gebraucht)? Wartet ein Schiff ewig an einer leeren Quelle? Ist eine Route unnötig geworden, wird sie gestoppt und das Schiff wartet in der Nähe einer Hauptstadt (Drisden/Essix) als Reserve.
