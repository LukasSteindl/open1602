# The task of a benchmark run

Give this text to the agent, with PORT, SKILLS and the variant line filled in. Every run of a
comparison gets the same text but for the variant line.

---

Play a game of Open1602 (an Anno 1602 remake) through its text control port, as well as you can,
until the game clock shows 0:30:00.

Your instructions for how to play are two skills. Read them first, completely, and follow them:
- SKILLS\play-open1602\SKILL.md
- SKILLS\anno1602-strategy\SKILL.md (the reference.md next to it only if you need it)

The game is already running and waiting for you: a new endless game alone (difficulty 1), on control
port PORT. Do not start or close a game. The client is
`D:\anno\open1602\bin\o1602-ctl.exe --port PORT COMMAND ...` (always `--port PORT`: the other ports
belong to other players). `... --port PORT help` lists the commands.

The clock: the game stands paused now and a referee starts it about two minutes after you were
started. Use that time to read the skills and to look; give no orders before it runs
(`wait-running` answers the moment it does). Then the game runs at speed x2 without waiting for you: one game minute is
30 seconds of real time. Never use `pause`, `resume` or `speed`: the referee keeps the time, and a
run in which the game was found paused does not count. Never end your turn before the end: wait
in the foreground with `advance`. The referee pauses the game at 0:30:00; that is the end.

Goal: the most residents (`state`: residents, the people in your houses) at 0:30:00, with money
left; going bankrupt means the run is lost.

Rules:
- Play only with what the skills allow (no autoplay, no editor, no savegame edits, no `save`).
- Use only the two skills, `help` and the game's own answers as knowledge. Do not read the game's
  source code, the repository's docs or other files under D:\anno\open1602. You may run (not read)
  `python -I D:\anno\open1602\tools\planner\plan.py` and
  `python -I D:\anno\open1602\tools\agent\steward.py`.
- VARIANT

Keep a running count of your o1602-ctl process calls (a batch counts as one; the steward's own
calls do not count).

Your final message, terse: your final `state` answer; the number of your o1602-ctl calls; a
timeline game time -> residents -> money at about 5-minute steps from the states you saw; and what
in the skills or the interface cost you time, was wrong or was missing, and what worked well.

---

Variant lines used so far:
- `Do not use the steward (tools/agent/steward.py) in this run: give every order yourself.`
- `Use the steward (tools/agent/steward.py) as the skill describes, from the moment your first market stands.`
