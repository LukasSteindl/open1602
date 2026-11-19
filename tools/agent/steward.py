#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Standing orders for an agent that plays Open1602: carries out a few rules round by round, so
that the agent spends its turns on decisions and not on repeating the same builds.

The agent writes the rules into a policy file (JSON) and may change it while the steward runs; the
steward reads it again every round. Every round it looks once (state, cities, economy, production),
then gives one batch of orders: producers and public buildings up to the counts wanted, houses
while wood and food allow, and each class's tax at the edge of contentment. It only uses the
control port, as the agent itself does, and it never waits inside the game: between rounds it
sleeps and looks at the clock, so the agent's own commands are not held up.

    python -I tools/agent/steward.py --port 7602 --policy my-policy.json
    python -I tools/agent/steward.py --port 7602 --policy my-policy.json --once --dry   # show, do nothing

The policy (see steward.example.json):
    island, city      the city the rules are for
    interval          game seconds between rounds (default 30)
    stop_at           game time "H:MM:SS" after which the steward ends (optional)
    enabled           false: look on, give no orders
    reserve           {"wood": 10, "tools": 6}: stock the steward leaves untouched
    houses            {"max": 60, "per_round": 4, "near": [x, y], "min_food_supply": 95, "min_food_stock": 5}
    producers         [{"kind": "forester", "count": 8, "near": [x, y]}, {"kind": "chapel", "count": 2}, ...]
                      built with `build KIND ISLAND auto [X Y]`, at most one of each kind a round
    taxes             {"pioneers": 192, "settlers": 144}: the highest rate to try per class; the rate goes
                      up 16 after two content readings and down 16 at once when satisfaction falls

What it prints: one line a round, and every `error:` answer in full. Nothing is hidden.
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import time
from pathlib import Path

CLASSES = ("pioneers", "settlers", "citizens", "merchants", "aristocrats")
TAX_STEP = 16
TAX_MIN, TAX_MAX = 64, 192
CONTENT = 128


def ctl(port: int, line: str, timeout: float = 130.0) -> str:
    """One command line to the game, its answer as text ('' when no game listens)."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
            s.settimeout(timeout)
            s.sendall((line + "\n").encode("utf-8"))
            parts = []
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                parts.append(chunk)
    except OSError:
        return ""
    return b"".join(parts).decode("utf-8", errors="replace")


def batch(port: int, commands: list[str]) -> dict[str, str]:
    """Several commands in one connection: the answer of each, by command."""
    if not commands:
        return {}
    text = ctl(port, "batch " + " ; ".join(commands))
    answers: dict[str, str] = {}
    current = None
    for row in text.splitlines():
        if row.startswith("### "):
            current = row[4:].strip()
            answers[current] = ""
        elif current is not None:
            answers[current] += row + "\n"
    return answers


def game_seconds(state: str) -> int | None:
    m = re.search(r"time (\d+):(\d+):(\d+)", state)
    return int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3]) if m else None


def parse_clock(text: str) -> int:
    h, m, s = (int(x) for x in text.split(":"))
    return h * 3600 + m * 60 + s


def look(port: int, island: int, city: int) -> dict:
    """What a round needs to know, from one batch."""
    a = batch(port, ["state", f"cities {island} {city}", f"economy {island} {city}", f"production {island}"])
    state = a.get("state", "")
    cities = a.get(f"cities {island} {city}", "")
    economy = a.get(f"economy {island} {city}", "")
    production = a.get(f"production {island}", "")
    s: dict = {"time": game_seconds(state), "running": " running " in (state.splitlines() or [""])[0] + " "}
    m = re.search(r"money (-?\d+).*balance (-?\d+); inhabitants (\d+)(?:, residents (\d+))?", state)
    if m:
        s.update(money=int(m[1]), balance=int(m[2]), inhabitants=int(m[3]), residents=int(m[4] or m[3]))
    m = re.search(r"food supplied (\d+)%", cities)
    s["food_supply"] = int(m[1]) if m else None
    m = re.search(r"houses by class: ([\d/]+)", cities)
    s["houses"] = sum(int(x) for x in m[1].split("/")) if m else 0
    s["classes"] = {}
    for name in CLASSES:
        m = re.search(rf"^{name}: (\d+) inhabitants, satisfaction (\d+).*?tax (\d+)", cities, re.M)
        if m:
            s["classes"][name] = {"people": int(m[1]), "satisfaction": int(m[2]), "tax": int(m[3])}
    s["stock"] = {}
    for m in re.finditer(r"^([a-z_]+) ([\d.]+)/([\d.]+) t", economy, re.M):
        s["stock"][m[1]] = float(m[2])
    s["have"] = {}
    for m in re.finditer(r"^([a-z_0-9]+) at \d+,\d+ \(\d+\):", production, re.M):
        s["have"][m[1]] = s["have"].get(m[1], 0) + 1
    s["known"] = bool(cities.strip()) and not cities.startswith("error")
    return s


def tax_orders(s: dict, policy: dict, memory: dict) -> list[str]:
    """Each class's tax at the edge: up after two content readings, down at once when it dips."""
    orders = []
    island, city = policy["island"], policy.get("city", 0)
    for name, cap in (policy.get("taxes") or {}).items():
        c = s["classes"].get(name)
        if c is None or c["people"] == 0:
            memory.pop(("content", name), None)
            continue
        cap = max(TAX_MIN, min(TAX_MAX, int(cap)))
        if c["satisfaction"] < CONTENT - 8:
            memory[("content", name)] = 0
            if c["tax"] > TAX_MIN:
                orders.append(f"tax {island} {city} {name} {max(TAX_MIN, c['tax'] - TAX_STEP)}")
        elif c["satisfaction"] >= CONTENT:
            memory[("content", name)] = memory.get(("content", name), 0) + 1
            if memory[("content", name)] >= 2 and c["tax"] < cap:
                orders.append(f"tax {island} {city} {name} {min(cap, c['tax'] + TAX_STEP)}")
                memory[("content", name)] = 0
        if c["tax"] > cap:
            orders.append(f"tax {island} {city} {name} {cap}")
    return orders


def build_orders(s: dict, policy: dict) -> list[str]:
    """Producers and public buildings up to their counts, then houses while wood and food allow."""
    orders = []
    island = policy["island"]
    reserve = policy.get("reserve") or {}
    wood = s["stock"].get("wood", 0.0) - float(reserve.get("wood", 0))
    tools = s["stock"].get("tools", 0.0) - float(reserve.get("tools", 0))
    for rule in policy.get("producers") or []:
        kind, count = rule["kind"], int(rule.get("count", 0))
        if s["have"].get(kind, 0) >= count or tools < 1:
            continue
        near = rule.get("near")
        orders.append(f"build {kind} {island} auto" + (f" {near[0]} {near[1]}" if near else ""))
        tools -= 2  # most producers take 2 to 4 t; the game refuses what cannot be paid
    houses = policy.get("houses") or {}
    if houses:
        food_ok = (s["food_supply"] is None or s["food_supply"] >= int(houses.get("min_food_supply", 95)) or
                   s["stock"].get("food", 0.0) >= float(houses.get("min_food_stock", 5)))
        room = int(houses.get("max", 0)) - s["houses"]
        n = min(int(houses.get("per_round", 4)), int(wood // 3), room) if food_ok else 0
        near = houses.get("near")
        for _ in range(max(0, n)):
            orders.append(f"build house {island} auto" + (f" {near[0]} {near[1]}" if near else ""))
    return orders


def round_once(port: int, policy: dict, memory: dict, dry: bool) -> str:
    s = look(port, policy["island"], policy.get("city", 0))
    if not s["known"] or s["time"] is None:
        return "no city to look at yet (island and city of the policy?)"
    orders = tax_orders(s, policy, memory) + build_orders(s, policy) if policy.get("enabled", True) else []
    clock = f"{s['time'] // 3600}:{s['time'] // 60 % 60:02d}:{s['time'] % 60:02d}"
    head = (f"{clock} residents {s.get('residents')} money {s.get('money')} balance {s.get('balance')} "
            f"houses {s['houses']} wood {s['stock'].get('wood', 0):.0f} tools {s['stock'].get('tools', 0):.0f} "
            f"food {s['food_supply']}%")
    if not orders:
        return head + " | nothing to do"
    if dry:
        return head + " | would: " + "; ".join(orders)
    answers = batch(port, orders)
    done, waiting, errors = 0, 0, []
    for order, answer in answers.items():
        first = (answer.strip().splitlines() or [""])[0]
        if not answer.startswith("error"):
            done += 1
        elif "short:" in answer or "not enough" in answer or "no place you can pay" in answer:
            waiting += 1  # materials are missing: the next round tries again
        else:
            errors.append(f"{order} -> {first}")
    line = head + f" | {done} done" + (f", {waiting} wait for materials" if waiting else "")
    return line + "".join("\n  " + e for e in errors)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", type=int, default=7602)
    ap.add_argument("--policy", required=True, help="the rules, a JSON file; read again every round")
    ap.add_argument("--once", action="store_true", help="one round, then end")
    ap.add_argument("--dry", action="store_true", help="say what it would order, order nothing")
    ap.add_argument("--log", default="", help="also append every line to this file")
    args = ap.parse_args()
    path = Path(args.policy)
    memory: dict = {}
    last_round = None
    while True:
        try:
            policy = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"policy {path}: {e}; waiting for a valid file", flush=True)
            if args.once:
                return 2
            time.sleep(3)
            continue
        state = ctl(args.port, "state", timeout=20)
        now = game_seconds(state)
        if now is None:
            print("no game answers on port %d" % args.port, flush=True)
            if args.once:
                return 2
            time.sleep(3)
            continue
        if policy.get("stop_at") and now >= parse_clock(policy["stop_at"]):
            print(f"stop_at {policy['stop_at']} reached: the steward ends", flush=True)
            return 0
        if args.once or last_round is None or now - last_round >= int(policy.get("interval", 30)):
            line = round_once(args.port, policy, memory, args.dry)
            print(line, flush=True)
            if args.log:
                with open(args.log, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            last_round = now
            if args.once:
                return 0
        time.sleep(1.5)


if __name__ == "__main__":
    sys.exit(main())
