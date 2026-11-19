"""Long-term plan for the Jev driver: the stages of tools/planner/plan.py (the Gozintograph of the
game's own balance data: which chain makes each good, how many buildings per stage, what they cost)
turned into the gaps of the current stage.

    stage, gaps = strategy.current(population, have)
    gaps = {"winery": 1, "tavern": 1, "houses": 6, ...}   # still missing for this stage

The driver offers a building only while the plan still misses it, and shows the stage, its goal,
the goods chains and the gaps over the map and to the model.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# A copy of this file elsewhere (a tournament agent's folder) finds the planner through O1602_PLANNER.
PLANNER = Path(os.environ["O1602_PLANNER"]) if os.environ.get("O1602_PLANNER") else \
    Path(__file__).resolve().parents[1] / "planner"
sys.path.insert(0, str(PLANNER))
import plan as planner  # noqa: E402

CLASSES = planner.CLASSES
_DATA = planner.load(PLANNER / "game_data.json")
_PLANS: list = []


def setup(crops_full: list[str], crops_half: list[str], food: str = "fish,hunter") -> list:
    """Computes the stages for the home island's crops (full fertility first, half as the fallback,
    as plan.py's --crops / --crops2)."""
    args = argparse.Namespace(efficiency=0.75, forest_efficiency=0.35, fish_efficiency=0.85, tool_price=75.0,
                              crops=",".join(crops_full) or "grain", crops2=",".join(crops_half) or "grain",
                              food=food)
    _PLANS.clear()
    prev = None
    for stage in planner.DEFAULT_PATH:
        prev = planner.plan_stage(_DATA, stage, args, prev)
        _PLANS.append(prev)
    return _PLANS


def _reached(stage, population: dict[str, int]) -> bool:
    """A stage is reached when, for every class it names, the city has that many of the class or
    higher (a settler house that rose to citizens still counts for the settlers' goal)."""
    for i, cls in enumerate(CLASSES):
        want = sum(stage.population.get(c, 0) for c in CLASSES[i:])
        have = sum(population.get(c, 0) for c in CLASSES[i:])
        if want and have < want:
            return False
    return True


def current(population: dict[str, int], have: dict[str, int], houses: int):
    """The first stage not yet reached, and what it still misses: buildings (plan count minus
    standing ones) and houses."""
    if not _PLANS:
        raise RuntimeError("strategy.setup() first")
    plan = next((p for p in _PLANS if not _reached(p.stage, population)), _PLANS[-1])
    gaps = {b: n - have.get(b, 0) for b, n in plan.buildings.items() if n - have.get(b, 0) > 0}
    want_houses = sum(plan.houses.values())
    if want_houses > houses:
        gaps["houses"] = want_houses - houses
    return plan, gaps


# ---------------------------------------------------------------------------------------------
# Building materials: the second half of the Gozintograph. Every building and every house that
# rises consumes tools, wood and bricks; they come from foresters, the brickworks (quarry +
# stonemason) and the toolmaker chain (ore mine -> smelter -> toolmaker), or from traders.

MATERIALS = ("tools", "wood", "bricks")
# Own producers of each material, t per minute each at the planning efficiency (the forester waits
# for trees to regrow).
PRODUCER = {"wood": ("forester", 3.16 * 0.35), "bricks": ("stonemason", 3.0 * 0.75),
            "tools": ("toolmaker", 1.71 * 0.75)}
# The chain to build when a material runs short (in this order).
CHAIN = {"wood": ["forester"], "bricks": ["quarry", "stonemason"],
         "tools": ["ore_mine", "ore_smelter", "toolmaker"]}


def build_cost(name: str) -> dict[str, float]:
    c = _DATA["buildings"][name]["build_cost"]
    return {"gold": c["gold"], "tools": c["tools_t"], "wood": c["wood_t"], "bricks": c["bricks_t"]}


def material_need(plan, gaps: dict[str, int], population: dict[str, int]) -> dict[str, float]:
    """Materials the stage still needs: its missing buildings, its missing houses (built as pioneer
    houses) and the houses that must rise to the stage's classes."""
    need = {m: 0.0 for m in ("gold", *MATERIALS)}
    for b, n in gaps.items():
        if b == "houses" or b not in _DATA["buildings"]:
            continue
        for m, v in build_cost(b).items():
            need[m] += v * n
    classes = {c["name"]: c for c in _DATA["classes"]}
    need["wood"] += gaps.get("houses", 0) * classes["pioneers"]["cost_to_reach_this_class"]["wood_t"]
    # Houses rising: per class the houses the stage wants above what the town has of that class.
    for i, cls in enumerate(CLASSES[1:], start=1):
        c = classes[cls]
        want = plan.houses.get(cls, 0)
        have = -(-population.get(cls, 0) // c["max_inhabitants_per_house"])
        if want > have:
            cost = c["cost_to_reach_this_class"]
            need["tools"] += (want - have) * cost["tools_t"]
            need["wood"] += (want - have) * cost["wood_t"]
            need["bricks"] += (want - have) * cost["bricks_t"]
    # Looking ahead: the next stage's materials, so the brickworks and the foresters stand before
    # its buildings are due (stage 3 alone wants about 100 t of bricks).
    nxt = next_stage(plan)
    if nxt is not None:
        for m in MATERIALS:
            need[m] += nxt.build_cost.get(f"{m}_t", 0.0) * 0.5
    return need


def next_stage(plan):
    i = next((k for k, p in enumerate(_PLANS) if p is plan), None)
    return _PLANS[i + 1] if i is not None and i + 1 < len(_PLANS) else None


def material_plan(need: dict[str, float], stock: dict[str, float], have: dict[str, int],
                  unlocked: set[str]) -> list[dict]:
    """Per material: need, stock, own production, minutes until the stock covers the need, and what
    to do about it (most urgent first)."""
    rows = []
    for m in MATERIALS:
        short = max(0.0, need[m] - stock.get(m, 0.0))
        name, per = PRODUCER[m]
        rate = have.get(name, 0) * per
        minutes = short / rate if rate > 0 else (0.0 if short == 0 else float("inf"))
        if short <= 0:
            action = "enough"
        elif m == "tools":
            chain_ok = all(_DATA["buildings"][b].get("unlock_level_name") in (None, "none") or
                           _DATA["buildings"][b].get("unlock_level_name") in unlocked for b in CHAIN["tools"])
            action = "buy from traders" + (" and build the toolmaker chain" if chain_ok and rate == 0 else "")
        elif rate == 0:
            action = "build " + " + ".join(CHAIN[m])
        elif minutes > 10:
            action = f"more {name}s ({minutes:.0f} min at {rate:.1f} t/min)"
        else:
            action = f"wait {minutes:.0f} min ({rate:.1f} t/min)"
        rows.append({"material": m, "need": need[m], "stock": stock.get(m, 0.0), "short": short, "rate": rate,
                     "minutes": minutes, "action": action})
    rows.sort(key=lambda r: -r["minutes"] if r["short"] > 0 else 1)
    return rows


def material_lines(rows: list[dict]) -> list[str]:
    return [f"{r['material']} {r['stock']:.0f}/{r['need']:.0f} t: {r['action']}" for r in rows]


def upstream(building: str) -> str | None:
    """The building that supplies this one's raw material in the planner's chains (tobacco_products
    <- tobacco_plantation, weaving_hut <- sheep_farm, rum_distillery <- sugarcane_plantation), or None."""
    for options in planner.CHAINS.values():
        for _, chain in options:
            if building in chain:
                i = chain.index(building)
                return chain[i + 1] if i + 1 < len(chain) else None
    # Chains the planner's consumer goods do not list (user: no own tool production yet).
    return {"toolmaker": "ore_smelter", "ore_smelter": "ore_mine", "stonemason": None}.get(building)


def gozinto(plan) -> list[str]:
    """The goods chains of the stage as lines: demand per minute <- final building <- raw producers."""
    lines = []
    for ware, chain_name in sorted(plan.chains.items()):
        name = chain_name.split()[0]  # "hunter x2" -> "hunter"
        chain = next((c for n, c in planner.CHAINS.get(ware, []) if n == name), [])
        parts = [f"{plan.buildings.get(b, 0)} {b}" for b in chain]
        lines.append(f"{ware} {plan.demand.get(ware, 0):.2f} t/min <- " + " <- ".join(parts))
    return lines


def summary(plan, gaps: dict[str, int]) -> str:
    """One line for the model's state and the overlay."""
    missing = ", ".join(f"{k} {v}" for k, v in sorted(gaps.items())) or "nothing: the next stage follows"
    return f"stage {plan.stage.name} ({plan.stage.goal}); missing: {missing}"


if __name__ == "__main__":
    setup(["grain", "tobacco", "wine"], ["sugar"])
    p, g = current({"pioneers": 20, "settlers": 2}, {"marketplace": 1, "forester": 8, "fishers_hut": 3}, 11)
    print(summary(p, g))
    for line in gozinto(p):
        print("  ", line)
    pop = {"pioneers": 18, "settlers": 83}
    need = material_need(p, g, pop)
    rows = material_plan(need, {"tools": 0, "wood": 11, "bricks": 0},
                         {"forester": 6, "stonemason": 0}, set())
    for line in material_lines(rows):
        print("   material:", line)
