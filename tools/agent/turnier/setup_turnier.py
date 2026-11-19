"""Makes the four agents' folders of the tournament from what is known today (README: "Two agents
against each other"; tools/agent/turnier/start_turnier.ps1). Each agent gets its own copy of the
skills and, for the Jev agents, of the driver, its plan and the planner, and learns on from there.
An existing folder is left as it is (its agent's learning is kept); --fresh makes it new.

    python -I tools/agent/turnier/setup_turnier.py [--fresh]
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
AGENTS = [
    # n, folder, name, port, who, jev
    (1, "a1-claude", "Claude", 7602, "Claude Opus 5.5 alone", False),
    (2, "a2-claude-jev", "ClaudeJev", 7603, "Claude Opus 5.5 as the coach of a Jev driver", True),
    (3, "a3-sol", "Sol", 7604, "ChatGPT Sol 6.1 alone", False),
    (4, "a4-sol-jev", "SolJev", 7605, "ChatGPT Sol 6.1 as the coach of a Jev driver", True),
]

JEV = """
## Your Jev driver

A small local model ("Jev", `jev_driver.py` in your folder) plays your slot turn by turn. It runs
in its own terminal (the operator starts `run_jev.ps1 -Port {port}`), founds your first Kontor by
itself (`--island auto`) and prints every decision; `state\\driver.log` has the same lines,
`state\\jev_log.jsonl` the full record (state, options, choice, result) and the chat.

You are its coach. Every 10 game minutes:

1. Look: `batch state ; cities ISLAND 0 ; alerts ISLAND` and the last 40 lines of `state\\driver.log`.
2. Check: danger (fire, money falling, negative balance), stuck (the same option or `wait` again and
   again: why is nothing else offered?), waste (buildings at low use), supply below 90%.
3. Act: small fixes in the game through your port; a rule that would fail again gets fixed in your
   copy of `jev_driver.py` / `strategy.py` (numbers of the plan: `planner\\`). Saving the file restarts
   the driver within seconds; then check `state\\driver.log` that it runs (a syntax error stops it
   until you fix it).
4. Note it in `notes.md`. `REVIEW_original.md` is how the coach worked in the last game alone (its
   island numbers belong to that game).

You may also act in the game yourself through your port: it is the same player.
"""


def make(n: int, folder: str, name: str, port: int, who: str, jev: bool, fresh: bool) -> None:
    d = HERE / folder
    if d.exists() and not fresh:
        print(f"{folder}: kept")
        return
    if d.exists():
        shutil.rmtree(d)
    (d / "skills").mkdir(parents=True)
    for skill in ("play-open1602", "anno1602-strategy"):
        shutil.copytree(ROOT / ".claude" / "skills" / skill, d / "skills" / skill)
    text = (HERE / "AGENT_TEMPLATE.md").read_text(encoding="utf-8")
    jev_text = JEV.format(port=port) if jev else ""
    for key, value in {"N": str(n), "NAME": name, "WHO": who, "PORT": str(port), "DIR": str(d),
                       "ROOT": str(HERE), "JEV": jev_text}.items():
        text = text.replace("{{" + key + "}}", value)
    (d / "AGENT.md").write_text(text, encoding="utf-8")
    (d / "notes.md").write_text(f"# Notes of agent {n} \"{name}\"\n\n(nothing learnt yet)\n", encoding="utf-8")
    if jev:
        for f in ("jev_driver.py", "strategy.py"):
            shutil.copy2(ROOT / "tools" / "agent" / f, d / f)
        shutil.copy2(ROOT / "tools" / "agent" / "REVIEW.md", d / "REVIEW_original.md")
        (d / "planner").mkdir()
        for f in ("plan.py", "game_data.json"):
            shutil.copy2(ROOT / "tools" / "planner" / f, d / "planner" / f)
        shutil.copy2(HERE / "run_jev.ps1", d / "run_jev.ps1")
        (d / "state").mkdir()
    print(f"{folder}: made")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fresh", action="store_true", help="make every folder new (the agents' learning is lost)")
    args = ap.parse_args()
    for a in AGENTS:
        make(*a, fresh=args.fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
