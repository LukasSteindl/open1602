#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Expansion planner for Open1602 (Anno 1602) from the game's own balance data.

Reads game_data.json (extract_game_data.py, from haeuser.cod) and computes, for each stage of an
expansion path:
- the production buildings the population needs, choosing per good the cheapest chain;
- the houses and public buildings;
- the one-off building materials (gold, tools, wood, bricks) of the new buildings and of the houses
  rising;
- running costs against taxes, so that every stage keeps the balance positive.

Usage:
    python -I tools/planner/plan.py                         # the default path to 100 merchants
    python -I tools/planner/plan.py --target merchants=100 --csv plan.csv
    python -I tools/planner/plan.py --crops grain,spices,cotton,cocoa --crops2 tobacco,sugar,wine
    python -I tools/planner/plan.py --efficiency 0.7 --food fish,hunter,cattle,grain

The numbers are planning figures: buildings rarely run at full speed (fields grow, carriers walk),
so production is scaled by --efficiency (default 0.75; the forester by --forest-efficiency, default
0.35, since it waits for trees to regrow).
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent

CLASSES = ["pioneers", "settlers", "citizens", "merchants", "aristocrats"]

# Production chains per consumed good: the final building, then the raw producers it feeds on.
# Each option is (name, [(building, role)]) with role "final" or a raw ware it supplies.
CHAINS: dict[str, list[tuple[str, list[str]]]] = {
    "food": [
        ("fish", ["fishers_hut"]),
        ("hunter", ["hunters_hut"]),
        ("cattle", ["butcher", "cattle_farm"]),
        ("grain", ["bakery", "grain_mill", "grain_farm"]),
    ],
    "cloth": [
        ("sheep", ["weaving_hut", "sheep_farm"]),
        ("cotton", ["weaving_mill", "cotton_plantation"]),
    ],
    "alcohol": [
        ("rum", ["rum_distillery", "sugarcane_plantation"]),
        ("wine", ["winery"]),
    ],
    "tobacco_goods": [("tobacco", ["tobacco_products", "tobacco_plantation"])],
    "spices": [("spices", ["spice_plantation"])],
    "cocoa": [("cocoa", ["cocoa_plantation"])],
    "clothes": [("tailor", ["tailor", "weaving_hut", "sheep_farm"])],
    "jewellery": [("gold", ["goldsmith", "gold_mine"])],
}
# Which crop an island must grow for a building (fertility).
CROP_OF = {
    "tobacco_plantation": "tobacco",
    "spice_plantation": "spices",
    "sugarcane_plantation": "sugar",
    "winery": "wine",
    "cotton_plantation": "cotton",
    "cocoa_plantation": "cocoa",
}
# Hunters live off the deer of an island: at most this many per island in practice.
MAX_HUNTERS = 2

# Public buildings: how many houses one of them serves in a compact town (its radius covers
# about this many 2x2 houses with roads; tavern 11, school 12, chapel 8, market 15).
PUBLIC_PER_HOUSES = {
    "marketplace": 30,
    "chapel": 14,
    "tavern": 22,
    "school": 26,
    "church": 60,
    "bathhouse": 55,
}


@dataclass
class Stage:
    name: str
    population: dict[str, int]
    goal: str


@dataclass
class Plan:
    stage: Stage
    houses: dict[str, int] = field(default_factory=dict)
    buildings: dict[str, int] = field(default_factory=dict)
    chains: dict[str, str] = field(default_factory=dict)
    demand: dict[str, float] = field(default_factory=dict)
    taxes: float = 0.0
    running: float = 0.0
    build_cost: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def load(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def rate(b: dict, efficiency: float) -> float:
    """t per minute a building makes at the planning efficiency."""
    return b["production"]["t_per_min_at_full_speed"] * efficiency


def raw_per_min(b: dict, efficiency: float) -> list[tuple[str, float]]:
    return [(r["ware"], r["t_per_min_at_full_speed"] * efficiency) for r in b["production"].get("raw", [])]


def chain_buildings(data: dict, chain: list[str], tons: float, eff: dict) -> dict[str, int]:
    """Buildings of a chain for `tons` per minute of its final good: the final building, then each
    raw producer for what the one above needs (counts rounded up)."""
    blds = data["buildings"]
    out: dict[str, int] = {}
    need = tons
    for i, name in enumerate(chain):
        b = blds[name]
        e = eff.get(name, eff["default"])
        n = max(1, math.ceil(need / rate(b, e) - 1e-9)) if need > 0 else 0
        out[name] = out.get(name, 0) + n
        if i + 1 < len(chain):
            # What the next building down the chain must deliver: the raw input of this one at
            # the rate the final good needs (not at full capacity of every building).
            raws = raw_per_min(b, 1.0)
            per_t = raws[0][1] / b["production"]["t_per_min_at_full_speed"] if raws else 0
            need = need * per_t
    return out


def chain_cost_per_t(data: dict, chain: list[str], eff: dict, tool_price: float) -> float:
    """Gold per ton of the final good: running costs plus build costs spread over two hours."""
    total = 0.0
    counts = chain_buildings(data, chain, 1.0, eff)
    for name, n in counts.items():
        b = data["buildings"][name]
        c = b["build_cost"]
        once = c["gold"] + c["tools_t"] * tool_price + c["wood_t"] * 15 + c["bricks_t"] * 22
        total += n * (b["running_cost_gold_per_min"] + once / 120.0)
    return total


def available(data: dict, building: str, unlocked: set[str]) -> bool:
    b = data["buildings"][building]
    return b.get("unlock_level") in (None, 0) or b.get("unlock_level_name") in unlocked


def unlocked_levels(data: dict, population: dict[str, int]) -> set[str]:
    """Levels a city of this population has reached (class or higher counts)."""
    out = {lv["name"] for lv in data["levels_available_from_start"]}
    for lv in data["unlock_levels"]:
        cls = lv["class_id"]
        n = sum(population.get(c, 0) for c in CLASSES[cls:])
        if n >= lv["min_inhabitants_of_class_or_higher"]:
            out.add(lv["name"])
    return out


def plan_stage(data: dict, stage: Stage, args, prev: Plan | None) -> Plan:
    p = Plan(stage)
    classes = {c["name"]: c for c in data["classes"]}
    eff = {"default": args.efficiency, "forester": args.forest_efficiency, "fishers_hut": args.fish_efficiency}
    crops = set(args.crops.split(",")) | set(args.crops2.split(","))
    # Demand of every good, t per minute.
    for cls, n in stage.population.items():
        c = classes[cls]
        p.houses[cls] = math.ceil(n / c["max_inhabitants_per_house"]) if n else 0
        p.taxes += n * c["tax_gold_per_inhabitant_per_min_at_normal_rate"]
        for need in c["needs"]:
            p.demand[need["ware"]] = p.demand.get(need["ware"], 0.0) + n / 100.0 * need["t_per_100_inhabitants_per_min"]
    # Unlocks: what the previous stage reached (a city keeps its levels).
    reached = unlocked_levels(data, stage.population)
    if prev is not None:
        reached |= unlocked_levels(data, prev.stage.population)
    # Choose the cheapest chain per good among the buildable ones.
    food_allowed = set(args.food.split(","))
    for ware, demand in sorted(p.demand.items()):
        options = []
        for label, chain in CHAINS.get(ware, []):
            if ware == "food" and label not in food_allowed:
                continue
            if any(CROP_OF.get(b) and CROP_OF[b] not in crops for b in chain):
                continue
            options.append((chain_cost_per_t(data, chain, eff, args.tool_price), label, chain))
        if not options:
            p.notes.append(f"{ware}: no chain possible here ({demand:.2f} t/min): buy it (Kontor 'trade ... buy')")
            continue
        options.sort()
        if ware == "food" and "hunter" in food_allowed:
            # Hunters first, up to the deer an island carries, then the cheapest other chain.
            hunter = data["buildings"]["hunters_hut"]
            from_hunters = min(demand, MAX_HUNTERS * rate(hunter, args.efficiency))
            n = math.ceil(from_hunters / rate(hunter, args.efficiency) - 1e-9)
            p.buildings["hunters_hut"] = p.buildings.get("hunters_hut", 0) + n
            demand -= from_hunters
            options = [o for o in options if o[1] != "hunter"]
            p.chains[ware] = f"hunter x{n}" + (" + " + options[0][1] if demand > 0 else "")
        else:
            p.chains[ware] = options[0][1]
        if demand <= 0:
            continue
        _, label, chain = options[0]
        locked = [b for b in chain if not available(data, b, reached)]
        if locked:
            p.notes.append(f"{ware}: {label} chain still locked ({', '.join(locked)}): buy {demand:.2f} t/min meanwhile")
        for b, n in chain_buildings(data, chain, demand, eff).items():
            p.buildings[b] = p.buildings.get(b, 0) + n
    # Wood for the smelter and the houses: foresters. Bricks: stonemason + quarry. Tools: bought.
    wood = 0.0
    if "ore_smelter" in p.buildings:
        wood += p.buildings["ore_smelter"] * 2.07 * args.efficiency
    houses = sum(p.houses.values())
    # Houses rising and new buildings need wood once; keep a steady supply of ~1 t/min per 10 houses.
    wood += houses / 10.0
    p.buildings["forester"] = max(p.buildings.get("forester", 0),
                                   math.ceil(wood / rate(data["buildings"]["forester"], eff["forester"]) - 1e-9))
    if any(c in stage.population and stage.population[c] > 0 for c in ("citizens", "merchants", "aristocrats")):
        p.buildings["stonemason"] = max(1, math.ceil(houses / 25))
        p.buildings["quarry"] = p.buildings["stonemason"]
    # Public buildings.
    p.buildings["marketplace"] = max(1, math.ceil(houses / PUBLIC_PER_HOUSES["marketplace"]))
    needed_public = set()
    for cls, n in stage.population.items():
        if n <= 0:
            continue
        for group in classes[cls]["required_public_buildings"]:
            needed_public.add(group[0])
    for cls in CLASSES[CLASSES.index(max((c for c in stage.population if stage.population[c] > 0),
                                         key=CLASSES.index)) + 1:][:1]:
        # The class the houses rise to next: its public buildings must stand before they can rise.
        for group in classes[cls]["required_public_buildings"]:
            needed_public.add(group[0])
    for pub in sorted(needed_public):
        if pub in PUBLIC_PER_HOUSES and pub != "marketplace":
            if not available(data, pub, reached):
                lv = data["buildings"][pub].get("unlock_requires", {})
                p.notes.append(f"{pub} for the next class is locked until {lv.get('min_inhabitants_of_class_or_higher')} "
                               f"{lv.get('class')}: houses cannot rise further before")
                continue
            p.buildings[pub] = max(1, math.ceil(houses / PUBLIC_PER_HOUSES[pub]))
    p.buildings["warehouse_1"] = max(1, len(args.islands) if hasattr(args, "islands") else 1)
    # Running costs.
    for b, n in p.buildings.items():
        p.running += n * data["buildings"][b]["running_cost_gold_per_min"]
    # One-off costs: buildings new against the previous stage, houses rising.
    cost = {"gold": 0.0, "tools_t": 0.0, "wood_t": 0.0, "bricks_t": 0.0}
    before = prev.buildings if prev else {}
    for b, n in p.buildings.items():
        new = max(0, n - before.get(b, 0))
        c = data["buildings"][b]["build_cost"]
        for k in cost:
            cost[k] += new * c[k]
    prev_houses = prev.houses if prev else {}
    for i, cls in enumerate(CLASSES):
        # Houses that rise into this class (or are built new as pioneer houses).
        gained = max(0, p.houses.get(cls, 0) - prev_houses.get(cls, 0))
        c = classes[cls]["cost_to_reach_this_class"]
        for k in cost:
            cost[k] += gained * c.get(k, 0)
        if i == 0:
            continue
    p.build_cost = cost
    return p


DEFAULT_PATH = [
    Stage("1 pioneers", {"pioneers": 40}, "20 houses at the first market, food, wood"),
    Stage("2 settlers", {"settlers": 120}, "chapel, cloth: 100 settlers unlock school and toolmaker"),
    Stage("3 citizens 150", {"settlers": 60, "citizens": 150}, "tavern, school, tobacco goods, spices, alcohol: 150 citizens unlock the church"),
    Stage("4 citizens 210", {"settlers": 60, "citizens": 225}, "more citizen houses: 200 unlock cocoa, 210 the bathhouse"),
    Stage("5 merchants 100", {"settlers": 60, "citizens": 225, "merchants": 100}, "church, bathhouse, cocoa: 4-5 houses rise to merchants"),
]


def parse_target(text: str) -> list[Stage]:
    pop = {}
    for part in text.split(","):
        k, v = part.split("=")
        pop[k.strip()] = int(v)
    return [Stage("target", pop, "as given")]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", default=str(HERE / "game_data.json"))
    ap.add_argument("--target", help="one stage, e.g. settlers=60,citizens=225,merchants=100")
    ap.add_argument("--efficiency", type=float, default=0.75)
    ap.add_argument("--forest-efficiency", type=float, default=0.35)
    ap.add_argument("--fish-efficiency", type=float, default=0.85)
    ap.add_argument("--tool-price", type=float, default=75.0, help="gold per t of tools when bought")
    ap.add_argument("--crops", default="grain,spices,cotton,cocoa", help="crops of the home island")
    ap.add_argument("--crops2", default="tobacco,sugar,wine", help="crops of the second island")
    ap.add_argument("--food", default="fish,cattle,grain",
                    help="food chains allowed; add 'hunter' only where the island has deer")
    ap.add_argument("--csv", help="write the stages as a table (opens in Excel)")
    args = ap.parse_args()

    data = load(Path(args.data))
    stages = parse_target(args.target) if args.target else DEFAULT_PATH
    plans: list[Plan] = []
    prev = None
    tools_total = 0.0
    for s in stages:
        prev = plan_stage(data, s, args, prev)
        tools_total += prev.build_cost["tools_t"]
        own = sum(data["buildings"][b]["build_cost"]["gold"] for b in ("ore_mine", "ore_smelter", "toolmaker"))
        if tools_total * args.tool_price > own * 1.5 and "toolmaker" not in prev.buildings:
            prev.notes.append(f"tools bought so far ~{tools_total:.0f} t (~{tools_total * args.tool_price:.0f} gold): an own "
                              f"chain (ore_mine + ore_smelter + toolmaker, {own} gold, 120 settlers, a known ore "
                              f"deposit) pays off now")
        plans.append(prev)

    for p in plans:
        pop = ", ".join(f"{n} {c}" for c, n in p.stage.population.items() if n)
        houses = ", ".join(f"{n} {c}" for c, n in p.houses.items() if n)
        print(f"== Stage {p.stage.name}: {pop}")
        print(f"   goal: {p.stage.goal}")
        print(f"   houses: {houses} ({sum(p.houses.values())} in all)")
        print("   demand t/min: " + ", ".join(f"{w} {t:.2f}" for w, t in sorted(p.demand.items())))
        print("   chains: " + ", ".join(f"{w}: {c}" for w, c in sorted(p.chains.items())))
        print("   buildings: " + ", ".join(f"{b} {n}" for b, n in sorted(p.buildings.items())))
        bal = p.taxes - p.running
        print(f"   taxes {p.taxes:.0f}/min, running costs {p.running:.0f}/min, balance {bal:+.0f}/min"
              + ("  << NEGATIVE: more houses or fewer buildings" if bal < 0 else ""))
        c = p.build_cost
        print(f"   to build from the stage before: gold {c['gold']:.0f}, tools {c['tools_t']:.0f} t, "
              f"wood {c['wood_t']:.0f} t, bricks {c['bricks_t']:.0f} t "
              f"(tools bought: ~{c['tools_t'] * args.tool_price:.0f} gold)")
        for n in p.notes:
            print(f"   note: {n}")
        print()

    if args.csv:
        names = sorted({b for p in plans for b in p.buildings})
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["stage", *CLASSES, "houses", "taxes", "running", "balance", "gold", "tools_t", "wood_t",
                        "bricks_t", *names])
            for p in plans:
                w.writerow([p.stage.name, *[p.stage.population.get(c, 0) for c in CLASSES], sum(p.houses.values()),
                            round(p.taxes), round(p.running), round(p.taxes - p.running),
                            *[round(p.build_cost[k]) for k in ("gold", "tools_t", "wood_t", "bricks_t")],
                            *[p.buildings.get(b, 0) for b in names]])
        print(f"wrote {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
