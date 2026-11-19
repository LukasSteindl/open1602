#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Extracts the economic balance of Anno 1602 for an expansion planner into game_data.json.

Sources:
  * haeuser.cod / figuren.cod of the installation (ANNO1602_DIR), decoded and interpreted by
    bin/o1602-tool.exe (`cod-dump --predefined ...` for the resolved records, `cod` for the plain
    text, needed for BGRUPPE_WARE whose repeated `Ware:` lines cod-dump collapses to the last one).
  * The engine's interpretation, re-implemented here and cited per value:
      engine/assets/src/building_table.cpp   (units: 1/32 t, needs trunc(v*8192)/600, tax trunc(Steuer*16/3))
      engine/assets/src/figure_table.cpp     (Speed, Worktime)
      engine/sim/src/production_cycle.cpp    (full_speed_seconds)
      engine/sim/src/consumption.cpp         (consume, tax_income, unlock_levels, running costs)
      engine/sim/src/houses.cpp              (kServiceNeeds, max_inhabitants64)
      engine/sim/include/o1602/sim/growth.hpp (growth_period_ms)
      engine/sim/src/pathfinding.cpp         (circle_half_widths, catchment)
      engine/assets/src/original_names.cpp   (stable names)
      engine/assets/include/o1602/assets/game_data.hpp (kBasePrices)

Usage: python -I extract_game_data.py [--game DIR] [--tool PATH] [--out PATH]
The engine code is only read, never changed.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

# --------------------------------------------------------------------------------------------
# Small readers for the engine's C++ sources (so names and tables stay in step with the code).
# --------------------------------------------------------------------------------------------


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def original_names() -> dict[str, list[tuple[str, int]]]:
    """kBuildings, kWares, kLevels, kClasses of original_names.cpp, each as [(name, number)]."""
    src = read(REPO / "engine/assets/src/original_names.cpp")
    out: dict[str, list[tuple[str, int]]] = {}
    for array in ("kBuildings", "kWares", "kLevels", "kClasses"):
        m = re.search(r"constexpr std::array " + array + r"\{(.*?)\};", src, re.S)
        if not m:
            raise SystemExit(f"original_names.cpp: {array} not found")
        out[array] = [(n, int(v)) for n, v in re.findall(r'OriginalName\{"(\w+)",\s*(\d+)', m.group(1))]
    # Build-menu section of each building (comment lines `// [SECTION]` before its entries).
    m = re.search(r"constexpr std::array kBuildings\{(.*?)\};", src, re.S)
    section = None
    sections: dict[str, str] = {}
    for line in m.group(1).splitlines():
        s = re.search(r"//\s*\[(\w+)\]", line)
        if s:
            section = s.group(1)
        for n, _ in re.findall(r'OriginalName\{"(\w+)",\s*(\d+)', line):
            sections[n] = section
    out["sections"] = sections  # type: ignore[assignment]
    return out


def base_prices() -> list[int]:
    src = read(REPO / "engine/assets/include/o1602/assets/game_data.hpp")
    m = re.search(r"kBasePrices\s*=\s*\{([^}]*)\}", src)
    return [int(x) for x in re.findall(r"\d+", m.group(1))]


def predefined_haeuser() -> dict[str, int]:
    """The symbols the original defines before parsing haeuser.cod (later ones overwrite)."""
    src = read(REPO / "engine/assets/src/cod_predefined.cpp")
    m = re.search(r"kHaeuser\[\]\s*=\s*\{(.*?)\};", src, re.S)
    syms: dict[str, int] = {}
    for name, value in re.findall(r'\{"(\w+)",\s*(-?\d+)\}', m.group(1)):
        syms[name] = int(value)
    return syms


# --------------------------------------------------------------------------------------------
# cod-dump reader
# --------------------------------------------------------------------------------------------


def number(text: str):
    text = text.strip()
    try:
        return int(text)
    except ValueError:
        try:
            return float(text)
        except ValueError:
            return text


def parse_dump(text: str) -> dict:
    """cod-dump output -> {"fields": {...}, "<TYPE>": {nummer: node}}; node = same shape."""
    root: dict = {"fields": {}}
    stack: list[tuple[int, dict]] = [(-1, root)]
    for raw in text.splitlines():
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]
        m = re.fullmatch(r"\[(\w+) #(-?\d+)\]", line)
        if m:
            node: dict = {"fields": {}}
            parent.setdefault(m.group(1), {})[int(m.group(2))] = node
            stack.append((indent, node))
            continue
        key, _, value = line.partition(":")
        parent["fields"][key.strip()] = [number(v) for v in value.split(",")]
    return root


def f(node: dict, key: str, index: int = 0, default=0):
    values = node["fields"].get(key)
    if not values or index >= len(values):
        return default
    return values[index]


def sub(node: dict, kind: str) -> dict | None:
    recs = node.get(kind)
    if not recs:
        return None
    return recs[min(recs)]


# --------------------------------------------------------------------------------------------
# Engine arithmetic (each mirrors a line of the engine, see the module docstring)
# --------------------------------------------------------------------------------------------

STOCK_UNITS_PER_TON = 32  # game_data.hpp kStockUnitsPerTon
SUPPLY_UNITS_PER_TON = 8192  # consumption.cpp: demand in 1/256 of 1/32 t
CITY_TICK_S = 10  # consumption.hpp kCityTickMs = 10'000
FULL = 128  # kFullSupply / normal tax rate


def tons_units(v) -> int:
    """building_table.cpp `tons`: saturating_cast<uint32>(v * 32) (truncation)."""
    return max(0, int(float(v) * STOCK_UNITS_PER_TON))


def need_per_tick(v: float) -> int:
    """building_table.cpp per_tick: trunc(trunc(v * 8192) / 600), in 1/8192 t per inhabitant and 10 s."""
    return int(int(float(v) * 8192.0) // 600)


def per_tick_to_t_per_100_min(k: int) -> float:
    # k/8192 t per inhabitant per 10 s -> x 100 inhabitants x 6 ticks per minute.
    return k * 100 * (60 // CITY_TICK_S) / SUPPLY_UNITS_PER_TON


def full_speed_seconds(b: dict, figures: dict) -> int:
    """production_cycle.cpp full_speed_seconds."""
    if b["prod_kind"] not in (2, 5, 6):  # kFarm, kHunter, kFisher
        return b["interval"]
    fig = figures.get(b["worker_figure"])
    if fig is None or fig["speed"] == 0:
        return b["interval"]
    r = b["radius"]
    reach = 22 if r <= 1 else 30 if r == 2 else 40 if r == 3 else 50
    walk = (reach * 20000 // fig["speed"] + fig["work_time_ms"]) // 1000
    return ((walk * b["raw_amount"]) >> 5) + b["interval"]


def growth_class(interval: int, anim_count: int) -> int:
    """building_table.cpp: count of k in 1..32 with 40 s + 7 s * k <= Interval / AnimAnz, max 31."""
    if anim_count <= 0:
        return 0
    stage_ms = interval * 1000 // anim_count
    return min(31, sum(1 for k in range(1, 33) if 40000 + 7000 * k <= stage_ms))


def growth_period_s(cls: int) -> float:
    """growth.hpp growth_period_ms."""
    return (40000 + 7000 * cls) / 1000.0


def circle_half_widths(radius: int) -> list[int]:
    """pathfinding.cpp circle_half_widths."""
    half = [0] * (radius + 1)
    x, y = 0, radius
    d = 1 - y
    while x <= y:
        half[y] = max(half[y], x)
        half[x] = max(half[x], y)
        if d < 0:
            d += 2 * x + 3
        else:
            d += 2 * (x - y) + 5
            y -= 1
        x += 1
    if radius == 1:
        half[1] = 1
    return half


def catchment_tiles(radius: int, w: int, h: int) -> int:
    """Tiles of the catchment circle (pathfinding.cpp PathFinder::begin with catchment_of)."""
    half = circle_half_widths(radius)
    px, py = (w - 1) & 1, (h - 1) & 1
    total = 0
    for dy_raw in range(-radius, radius + py + 1):
        dy = dy_raw - py if dy_raw > 0 else dy_raw
        if abs(dy) > radius:
            continue
        hw = half[abs(dy)]
        total += 2 * hw + 1 + px
    return total


# --------------------------------------------------------------------------------------------


def run_tool(tool: Path, *args: str) -> str:
    res = subprocess.run([str(tool), *args], capture_output=True, text=True, encoding="cp1252", errors="replace")
    if res.returncode != 0:
        raise SystemExit(f"{tool} {' '.join(args)} failed: {res.stderr or res.stdout}")
    return res.stdout


def bgruppe_needs(cod_text: str, syms: dict[str, int]) -> dict[int, list[tuple[int, float, str]]]:
    """The `Ware: SYMBOL, value` lines of each BGRUPPE (all of them, as building_table.cpp reads
    list.history), from the plain text of haeuser.cod."""
    start = re.search(r"Objekt:\s*BGRUPPE\b", cod_text).end()
    end = start + re.search(r"Objekt:\s*BAUINFRA\b", cod_text[start:]).start()
    block = cod_text[start:end]
    needs: dict[int, list[tuple[int, float, str]]] = {}
    current = None
    for line in block.splitlines():
        line = line.split(";", 1)[0].strip()
        mm = re.match(r"Nummer:\s*(\d+)", line)
        if mm:
            current = int(mm.group(1))
            needs.setdefault(current, [])
            continue
        mm = re.match(r"Ware:\s*(\w+)\s*,\s*([\d.]+)", line)
        if mm and current is not None:
            sym = mm.group(1)
            ware = syms[sym] if sym in syms else int(sym)
            needs[current].append((ware, float(mm.group(2)), sym))
    return needs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", default=os.environ.get("ANNO1602_DIR"))
    ap.add_argument("--tool", default=str(REPO / "bin" / "o1602-tool.exe"))
    ap.add_argument("--out", default=str(HERE / "game_data.json"))
    args = ap.parse_args()
    if not args.game:
        raise SystemExit("set ANNO1602_DIR or pass --game")
    game = Path(args.game)
    tool = Path(args.tool)

    names = original_names()
    sections: dict[str, str] = names["sections"]  # type: ignore[assignment]
    prices = base_prices()
    syms = predefined_haeuser()

    haeuser = parse_dump(run_tool(tool, "cod-dump", str(game / "haeuser.cod"), "--predefined", "haeuser"))
    figuren = parse_dump(run_tool(tool, "cod-dump", str(game / "figuren.cod"), "--predefined", "figuren"))
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        txt = Path(tmp) / "haeuser.txt"
        run_tool(tool, "cod", str(game / "haeuser.cod"), str(txt))
        haeuser_text = txt.read_text(encoding="cp1252", errors="replace")

    # ---- figures (figure_table.cpp) ----
    figures: dict[int, dict] = {}
    for nummer, node in figuren.get("FIGUR", {}).items():
        figures[nummer] = {
            "speed": max(0, int(f(node, "Speed"))),
            "work_time_ms": int(float(f(node, "Worktime")) * 1000 + 0.5),
            "max_carry_t": max(0, int(f(node, "Maxtrag"))),
        }
    figure_names = {}
    src = read(REPO / "engine/assets/src/original_names.cpp")
    for n, v, c in re.findall(r'OriginalName\{"(\w+)",\s*(\d+)(?:,\s*(\d+))?\}', src.split("kFigures")[1].split("};")[0]):
        figure_names[int(v)] = n
    # Figures original_names.cpp does not name: the grazing animals (figuren.cod RIND, SCHAF).
    figure_names.setdefault(87, "cattle_animal")
    figure_names.setdefault(88, "sheep_animal")

    # ---- buildings (building_table.cpp from_cod) ----
    by_id: dict[int, dict] = {}
    by_record: dict[int, dict] = {}
    for nummer, node in haeuser.get("HAUS", {}).items():
        bid = int(f(node, "Id"))
        if bid == 0:
            continue
        b = {
            "id": bid,
            "record": nummer,
            "kind": int(f(node, "Kind")),
            "size": [max(1, int(f(node, "Size", 0, 1))), max(1, int(f(node, "Size", 1, 1)))],
            "anim_count": max(0, int(f(node, "AnimAnz"))),
            "prod_kind": 0,
            "ware": 0, "raw_ware": 0, "raw2_ware": 0,
            "produce_amount": 0, "raw_amount": 0, "raw2_amount": 0,
            "interval": 0, "radius": 0, "worker_figure": 0, "worker_count": 0,
            "max_stock": 0, "infra": 0, "workers": 0, "running_cost": 0, "idle_cost": 0,
            "resident_class": 0,
            "cost": {"gold": 0, "tools": 0, "wood": 0, "bricks": 0, "cannons": 0},
        }
        prod = sub(node, "HAUS_PRODTYP")
        if prod is not None:
            b.update(
                prod_kind=int(f(prod, "Kind")),
                ware=int(f(prod, "Ware")),
                raw_ware=int(f(prod, "Rohstoff")),
                raw2_ware=int(f(prod, "Workstoff")),
                produce_amount=tons_units(f(prod, "Prodmenge")),
                raw_amount=tons_units(f(prod, "Rohmenge")),
                raw2_amount=tons_units(f(prod, "Workmenge")),
                interval=max(0, int(f(prod, "Interval"))),
                radius=min(255, max(0, int(f(prod, "Radius")))),
                worker_figure=int(f(prod, "Figurnr")),
                worker_count=int(f(prod, "Figuranz")),
                max_stock=max(0, int(f(prod, "Maxlager"))) * STOCK_UNITS_PER_TON,
                infra=max(0, int(f(prod, "Bauinfra"))),
                workers=max(0, int(f(prod, "Arbeiter"))),
                running_cost=max(0, int(f(prod, "Kosten", 0))),
                idle_cost=max(0, int(f(prod, "Kosten", 1))),
                resident_class=max(0, int(f(prod, "BGruppe"))),
            )
        cost = sub(node, "HAUS_BAUKOST")
        if cost is not None:
            b["cost"] = {
                "gold": int(f(cost, "Money")),
                "tools": tons_units(f(cost, "Werkzeug")),
                "wood": tons_units(f(cost, "Holz")),
                "bricks": tons_units(f(cost, "Ziegel")),
                "cannons": tons_units(f(cost, "Kanon")),
            }
        by_id.setdefault(bid, b)  # the first record wins the id
        by_record[nummer] = b

    # ---- wares ----
    ware_names = dict((v, n) for n, v in names["kWares"])
    # Ware symbols 0..58 are the block NOWARE..SCHATZ of cod_predefined.cpp.
    src = read(REPO / "engine/assets/src/cod_predefined.cpp")
    block = src[src.index('{"NOWARE", 0}'): src.index('{"SCHATZ", 58}') + 20]
    ware_symbols = {int(v): n for n, v in re.findall(r'\{"(\w+)",\s*(\d+)\}', block)}

    def ware_name(w: int) -> str | None:
        if w == 0:
            return None
        if w in ware_names:
            return ware_names[w]
        return {45: "grain_crop", 46: "tobacco_crop", 47: "spice_crop", 48: "sugarcane_crop", 49: "cotton_crop",
                50: "grapes_crop", 51: "cocoa_crop", 52: "grass", 53: "tree", 54: "stone", 55: "ore_deposit",
                56: "game", 57: "fish", 58: "treasure"}.get(w, f"ware_{w}")

    wares = {}
    for w in range(2, 25):
        wares[ware_names[w]] = {"id": w, "symbol": ware_symbols.get(w), "base_price": prices[w], "trade_good": True}
    for w in range(45, 58):
        wares[ware_name(w)] = {"id": w, "symbol": ware_symbols.get(w), "base_price": 0, "trade_good": False,
                               "note": "raw resource on the map (field, tree, grass, rock, deposit, game, fish), "
                                       "harvested 1 t per ripe tile by the building's worker"}

    # ---- unlock levels (BAUINFRA) ----
    level_names = dict((v, n) for n, v in names["kLevels"])
    infra_levels = {}
    for nummer, node in sorted(haeuser.get("BAUINFRA", {}).items()):
        infra_levels[nummer] = (int(f(node, "BGruppe")), int(f(node, "Minwohn")))
    max_infra = max([*infra_levels, *(b["infra"] for b in by_id.values())])

    # ---- classes ----
    first_house: dict[int, dict] = {}  # BuildingTable::first_house: first WOHNUNG record of a class
    for b in sorted(by_record.values(), key=lambda b: b["record"]):
        if b["prod_kind"] == 13:
            first_house.setdefault(b["resident_class"], b)
    class_names = dict((v, n) for n, v in names["kClasses"])
    raw_needs = bgruppe_needs(haeuser_text, {**syms})
    food = float(f(haeuser, "Nahrung"))
    food_k = need_per_tick(food)
    service_choice = [
        # houses.cpp kServiceNeeds: each entry a choice of buildings, any one of which will do.
        [["marketplace", "warehouse"]],
        [["marketplace"], ["chapel", "church"]],
        [["marketplace"], ["tavern"], ["chapel", "church"], ["school", "college"]],
        [["marketplace"], ["tavern"], ["church"], ["school", "college"], ["bathhouse"]],
        [["marketplace"], ["tavern"], ["church"], ["college"], ["bathhouse"], ["theatre"]],
    ]
    # Verify the table above against houses.cpp so it cannot silently drift.
    houses_src = read(REPO / "engine/sim/src/houses.cpp")
    m = re.search(r"kServiceNeeds = \{\{(.*?)\}\};", houses_src, re.S)
    rows = re.findall(r"\{([^{}]*)\},\s*//\s*(\w+)", m.group(1))
    bit_name = {"kMarketNeed": "marketplace", "hs::kKontor": "warehouse", "hs::kKapelle": "chapel",
                "hs::kKirche": "church", "hs::kWirtshaus": "tavern", "hs::kSchule": "school",
                "hs::kHochschule": "college", "hs::kBadehaus": "bathhouse", "hs::kTheater": "theatre"}
    parsed = [[[bit_name[t.strip()] for t in entry.split("|")] for entry in row.split(",") if entry.strip()]
              for row, _ in rows]
    if parsed != service_choice:
        raise SystemExit(f"houses.cpp kServiceNeeds changed: {parsed}")

    buildings_by_infra: dict[int, list[str]] = {}
    named = {n: v for n, v in names["kBuildings"]}
    landscape = {n for n, s in sections.items() if s == "LANDSCHAFT"}
    for n, bid in names["kBuildings"]:
        if n in landscape:
            continue
        b = by_id.get(bid)
        if b is not None:
            buildings_by_infra.setdefault(b["infra"], []).append(n)

    classes = []
    for c in sorted(class_names):
        node = haeuser["BGRUPPE"][c]
        steuer = float(f(node, "Steuer"))
        tax = int(steuer * 16.0 / 3.0)
        needs = []
        merged: dict[int, tuple[float, str]] = {}
        for ware, value, sym in raw_needs.get(c, []):
            if ware == 0 or need_per_tick(value) == 0:
                continue
            merged[ware] = (value, sym)  # a later line replaces an earlier one, keeps its place
        needs.append({
            "ware": ware_name(14), "ware_id": 14, "is_food": True, "cod_value_t_per_100_per_min": food,
            "engine_units_per_inhabitant_per_10s": food_k,
            "t_per_100_inhabitants_per_min": round(per_tick_to_t_per_100_min(food_k), 6),
        })
        for ware, (value, sym) in merged.items():
            k = need_per_tick(value)
            needs.append({
                "ware": ware_name(ware), "ware_id": ware, "is_food": False, "cod_value_t_per_100_per_min": value,
                "engine_units_per_inhabitant_per_10s": k,
                "t_per_100_inhabitants_per_min": round(per_tick_to_t_per_100_min(k), 6),
            })
        unlocks = []
        for lvl, (cls, minwohn) in sorted(infra_levels.items()):
            if cls == c:
                unlocks.append({
                    "infra": lvl, "name": level_names.get(lvl), "min_inhabitants_of_this_class_or_higher": minwohn,
                    "buildings": buildings_by_infra.get(lvl, []),
                })
        house = first_house.get(c)
        classes.append({
            "id": c,
            "name": class_names[c],
            "house_building": "house",
            "house_record_id": house["id"] if house else None,
            "house_size": house["size"] if house else None,
            # houses.cpp pay_materials: a house rising into class c pays the build cost of the
            # class's first house record (BuildingTable::first_house); the pioneers' is the cost of
            # placing a house.
            "cost_to_reach_this_class": None if house is None else {
                "gold": house["cost"]["gold"], "tools_t": house["cost"]["tools"] / 32,
                "wood_t": house["cost"]["wood"] / 32, "bricks_t": house["cost"]["bricks"] / 32},
            "max_inhabitants_per_house": int(f(node, "Maxwohn")),
            "tax_value_engine": tax,
            "cod_steuer": steuer,
            "tax_gold_per_inhabitant_per_min_at_normal_rate": tax * 6 / 32,
            "satisfaction_share_engine": int(f(node, "Prozent")) * 128 // 100,
            "cod_prozent": int(f(node, "Prozent")),
            "needs": needs,
            "required_public_buildings": service_choice[c],
            "unlock_levels": unlocks,
        })

    # Levels reached at once (no BAUINFRA entry: {class 0, 0 inhabitants}).
    always = []
    for lvl in range(0, max_infra + 1):
        if lvl == 0 or lvl not in infra_levels:
            always.append({"infra": lvl, "name": level_names.get(lvl, "none" if lvl == 0 else None),
                           "buildings": buildings_by_infra.get(lvl, [])})

    # ---- crops: growing record -> ripe record (next record) ----
    def ripe_after(growing: dict) -> dict | None:
        nxt = by_record.get(growing["record"] + 1)
        return nxt if nxt is not None and nxt["prod_kind"] == 9 else None

    field_name_of_id = {bid: n for n, bid in names["kBuildings"] if sections.get(n) == "FARM"}
    # Where no buildable field exists, the tiles a worker harvests are terrain.
    terrain_crop_name = {52: "meadow (natural grass ground)", 57: "open sea (fish)"}
    crop_by_ware: dict[int, dict] = {}
    for b in sorted(by_record.values(), key=lambda b: b["record"]):
        if b["prod_kind"] == 10 and b["anim_count"] > 0:
            ripe = ripe_after(b)
            if ripe is None or ripe["ware"] == 0:
                continue
            # The buildable field (original_names.cpp) wins over terrain variants of the same crop.
            if ripe["ware"] not in crop_by_ware or (b["id"] in field_name_of_id
                                                    and crop_by_ware[ripe["ware"]]["id"] not in field_name_of_id):
                crop_by_ware[ripe["ware"]] = b

    # ---- buildings ----
    buildings = {}
    for n, bid in names["kBuildings"]:
        if n in landscape:
            continue
        b = by_id.get(bid)
        if b is None:
            continue
        kind_name = {1: "workshop", 2: "farm", 3: "mine", 4: "pasture", 5: "hunter", 6: "fisher", 7: "market",
                     8: "warehouse", 9: "ripe_crop", 10: "growing_crop", 11: "quarry", 13: "house", 14: "shipyard",
                     15: "military", 16: "tower", 17: "tavern", 18: "chapel", 19: "church", 20: "bathhouse",
                     21: "theatre", 22: "doctor", 23: "school", 24: "college", 25: "gallows", 26: "fire_station",
                     27: "palace", 28: "monument", 29: "triumphal_arch", 30: "castle_hq"}.get(b["prod_kind"])
        entry = {
            "id": bid,
            "record": b["record"],
            "menu_section": sections.get(n),
            "production_kind": b["prod_kind"],
            "production_kind_name": kind_name,
            "size": b["size"],
            "build_cost": {
                "gold": b["cost"]["gold"],
                "tools_t": b["cost"]["tools"] / 32,
                "wood_t": b["cost"]["wood"] / 32,
                "bricks_t": b["cost"]["bricks"] / 32,
                **({"cannons_t": b["cost"]["cannons"] / 32} if b["cost"]["cannons"] else {}),
            },
            "running_cost_gold_per_min": b["running_cost"],
            "idle_cost_gold_per_min": b["idle_cost"],
            "radius_tiles": b["radius"],
            "workers": b["workers"],
            "unlock_level": b["infra"],
            "unlock_level_name": level_names.get(b["infra"], "none" if b["infra"] == 0 else None),
            "unlock_requires": (
                None if b["infra"] not in infra_levels else
                {"class": class_names.get(infra_levels[b["infra"]][0]),
                 "min_inhabitants_of_class_or_higher": infra_levels[b["infra"]][1]}),
        }
        # Producers: workshops, farms/plantations, mines, pastures, hunters, fishers. The quarry
        # (STEINBRUCH) is a site the stonemason harvests, it runs no cycle of its own.
        produces = b["prod_kind"] in (1, 2, 3, 4, 5, 6) and b["ware"] != 0
        if b["prod_kind"] == 11:
            entry["resource_site"] = {"ware": ware_name(b["ware"]), "harvested_by": "stonemason",
                                      "note": "the stonemason's worker takes 1 t of stone per visit; quarries never run out"}
        if produces:
            cycle = full_speed_seconds(b, figures)
            prod_t = b["produce_amount"] / 32
            raw = []
            if b["raw_ware"]:
                raw.append({"ware": ware_name(b["raw_ware"]), "ware_id": b["raw_ware"],
                            "t_per_cycle": b["raw_amount"] / 32,
                            "t_per_min_at_full_speed": round(b["raw_amount"] / 32 * 60 / cycle, 6) if cycle else None})
            if b["raw2_ware"]:
                raw.append({"ware": ware_name(b["raw2_ware"]), "ware_id": b["raw2_ware"],
                            "t_per_cycle": b["raw2_amount"] / 32,
                            "t_per_min_at_full_speed": round(b["raw2_amount"] / 32 * 60 / cycle, 6) if cycle else None})
            entry["production"] = {
                "ware": ware_name(b["ware"]),
                "ware_id": b["ware"],
                "t_per_cycle": prod_t,
                "raw": raw,
                "interval_s": b["interval"],
                "cycle_s_at_full_speed": cycle,
                "t_per_min_at_full_speed": round(prod_t * 60 / cycle, 6) if cycle else None,
                "max_stock_t": b["max_stock"] / 32,
                "worker_figure": figure_names.get(b["worker_figure"], b["worker_figure"] or None),
                "cod_figuranz": b["worker_count"],
            }
            if b["prod_kind"] in (2, 5, 6):
                # logistics.cpp send_worker: one worker per farm, hunter or fisher (Figuranz ignored).
                entry["production"]["workers_out"] = 1
            elif b["prod_kind"] == 4:
                # ... pastures keep up to Figuranz animals out (at least 1).
                entry["production"]["workers_out"] = max(1, b["worker_count"])
                fig = figures.get(b["worker_figure"])
                if fig:
                    entry["production"]["animal_max_carry_t"] = fig["max_carry_t"]
            if b["prod_kind"] in (2, 5, 6):
                fig = figures.get(b["worker_figure"])
                entry["production"]["cycle_formula"] = (
                    "interval + (walk_s * raw_units >> 5), walk_s = (reach*20000/speed + worktime_ms) // 1000, "
                    f"reach={22 if b['radius'] <= 1 else 30 if b['radius'] == 2 else 40 if b['radius'] == 3 else 50}, "
                    f"speed={fig['speed'] if fig else None}, worktime_ms={fig['work_time_ms'] if fig else None}")
            # Fields: the crop that grows on the map for this building's raw ware.
            crop = crop_by_ware.get(b["raw_ware"]) if b["raw_ware"] else None
            if crop is not None and b["prod_kind"] in (1, 2, 4, 6):
                cls = growth_class(crop["interval"], crop["anim_count"])
                period = growth_period_s(cls)
                regrow_max = crop["anim_count"] * period
                regrow_avg = (crop["anim_count"] - 0.5) * period
                harvests_per_min = (b["raw_amount"] / 32) * 60 / cycle if cycle else 0
                w, h = b["size"]
                area = catchment_tiles(b["radius"], w, h) - w * h
                entry["fields"] = {
                    "field_building": field_name_of_id.get(crop["id"]),
                    "field_terrain": None if crop["id"] in field_name_of_id else terrain_crop_name.get(b["raw_ware"]),
                    "field_building_id": crop["id"],
                    "crop_ware": ware_name(b["raw_ware"]),
                    "t_per_harvested_tile": 1.0,
                    "growth_stages": crop["anim_count"],
                    "growth_class": cls,
                    "stage_s": period,
                    "regrow_s_avg": regrow_avg,
                    "regrow_s_max": regrow_max,
                    "fields_for_full_speed": math.ceil(harvests_per_min * regrow_avg / 60 - 1e-9),
                    "fields_for_full_speed_worst_case": math.ceil(harvests_per_min * regrow_max / 60 - 1e-9),
                    "t_per_min_per_field": round(60 / regrow_avg, 6),
                    "catchment_tiles_excluding_building": area,
                }
                if b["prod_kind"] in (2, 4) or (b["prod_kind"] == 1 and b["ware"] == 23):
                    # ai_build.cpp: the fields the computers keep around a farm.
                    entry["fields"]["computer_player_plants"] = 7 if b["ware"] == 8 else 14
        buildings[n] = entry

    out = {
        "source": {
            "haeuser_cod": str(game / "haeuser.cod"),
            "figuren_cod": str(game / "figuren.cod"),
            "extractor": "tools/planner/extract_game_data.py",
            "engine_files": [
                "engine/assets/src/building_table.cpp", "engine/assets/src/figure_table.cpp",
                "engine/sim/src/production_cycle.cpp", "engine/sim/src/consumption.cpp",
                "engine/sim/src/houses.cpp", "engine/sim/include/o1602/sim/growth.hpp",
                "engine/sim/src/pathfinding.cpp", "engine/assets/src/original_names.cpp",
                "engine/assets/include/o1602/assets/game_data.hpp",
            ],
        },
        "units": {
            "time": "game seconds (s) / game minutes (min); the city tick is 10 s, production advances once per game second",
            "goods": "tons (t); the engine stores 1/32 t (stock units) and the demand of residents in 1/8192 t",
            "money": "gold",
            "build_cost": "gold and tons of tools/wood/bricks(/cannons)",
            "running_cost_gold_per_min": "gold per game minute while switched on; idle_cost_gold_per_min while switched off",
            "t_per_100_inhabitants_per_min": "tons per 100 inhabitants of that class per game minute, as the engine computes it",
            "t_per_min_at_full_speed": "tons per game minute when the building never waits for raw material, carriers or room",
            "radius_tiles": "catchment radius in tiles around the building's centre",
            "tax_gold_per_inhabitant_per_min_at_normal_rate": "gold per inhabitant per game minute at the normal tax rate (128/128)",
            "base_price": "gold per ton (the price traders base buying and selling on)",
        },
        "notes": [
            "Goods amounts in haeuser.cod (Prodmenge, Rohmenge, Workmenge, Maxlager, build costs) are tons; the engine multiplies by 32 and truncates (1/32 t units). All values in haeuser.cod are exact multiples of 1/32, so the tons here are exact.",
            "Residents' needs: haeuser.cod gives t per 100 inhabitants per minute (BGRUPPE_WARE `Ware: W, v`, global `Nahrung` for food). The engine converts each to k = trunc(trunc(v*8192)/600) in 1/8192 t per inhabitant per 10 s city tick (building_table.cpp per_tick); the effective rate is k*600/8192 t per 100 inhabitants per minute, a little below v because of the two truncations (e.g. food 1.3 -> 17 -> 1.2451 t). t_per_100_inhabitants_per_min is that effective value; cod_value_t_per_100_per_min the file's.",
            "Every class eats food (NAHRUNG). consumption.cpp adds k * inhabitants of each class (whole inhabitants) to the demand every 10 s; demand and supply both decay by 15/16 per tick, and each tick, when demand is ahead of supply, takes (demand-supplied)/256 + 1 stock units (1/32 t) from the warehouse. The '+1' only rounds up: over time the use equals the nominal rate (the overshoot is bounded and decays). The supply ratio (0..128) per ware drives satisfaction, growth and rising to the next class.",
            "A house rises into the next class only when the city's food supply and the next class's satisfaction are full (128), the house has the next class's public buildings in reach, the city is not material-locked, and the warehouse holds the next class's house cost (cost_to_reach_this_class, houses.cpp pay_materials: tools/wood/bricks and gold).",
            "Inhabitants of a class consume from the moment a house is queued to rise into that class (n_eff in consumption.cpp).",
            "Pioneers (class 0) have no wares besides food in this haeuser.cod (History Edition values; the cod comments 'ORG/SUN' list the older values).",
            "Tax: the engine keeps trunc(Steuer*16/3) and pays tax*inhabitants*6/32 gold per minute at the normal rate (consumption.cpp tax_income); the money of a city changes every 10 s by (taxes - running costs)/6, truncated toward zero.",
            "Required public buildings (houses.cpp kServiceNeeds): each inner list is a choice; any one building of it in reach of the house will do. Pioneers need a marketplace OR a warehouse (Kontor) in reach. The cathedral counts as a church. Without them a house does not rise to the next class and loses inhabitants.",
            "Unlock levels (BAUINFRA): level n is reached by a player when one of their cities has at least min_inhabitants inhabitants of the level's class or any higher class (consumption.cpp unlock_levels, per city, not summed over cities). Levels without a BAUINFRA entry (1 market, 2 chapel) and level 0 are available from the start. Levels 13 (triumphal arch) and 14 (monument) are, besides, granted by special rules; 11 castle/palace and 12 cathedral are one per player.",
            "cycle_s_at_full_speed is production_cycle.cpp full_speed_seconds: Interval for workshops, mines, pastures and quarries; for farms/plantations (PLANTAGE), hunters and fishers Interval + the worker's walk out to the catchment edge and back, walk_s = (reach*20000/Speed + Worktime_ms) // 1000 with reach 22/30/40/50 tenths of a tile for radius <=1/2/3/>=4, times the raw tons per cycle (raw_units >> 5). It is an upper bound on output: real production also needs raw material in the building (carriers bring it from the warehouse/market for workshops) and room in the store.",
            "A cycle runs at a rate of fill/128 of full speed when the building holds less raw material than a full cycle needs (production_cycle.cpp cycle_rate): output and time scale together, and below half a cycle's raw material (rate < 64) it does not start. Without raw material it waits 11 s and checks again.",
            "Farms (grain_farm, plantations, winery, forester's woodcutter) get 1 t per harvested ripe field tile (logistics.cpp finish_work). A harvested field becomes its growing record again and needs growth_stages stages of 40 s + 7 s*growth_class each (growth.hpp; growth_class from the field's Interval/AnimAnz, building_table.cpp). The global stage clocks make the first stage last 0..1 stage, so regrow_s_avg = (stages-0.5)*stage_s and regrow_s_max = stages*stage_s. fields_for_full_speed = ceil(harvest rate at full speed * regrow time); newly planted fields start with a random +0..2 growth class (slower). Fields must lie inside the catchment circle (catchment_tiles_excluding_building).",
            "computer_player_plants is the number of fields the computer players keep around their farms (ai_build.cpp: 7 for grain, 14 otherwise): a practical reference, not a rule.",
            "Pastures (sheep_farm, cattle_farm, WEIDETIER) send Figuranz animals that graze ripe grass tiles (1 t each) until they carry Maxtrag; their cycle at full speed is just Interval (full_speed_seconds does not add a walk for them). Hunters shoot game, fishers' boats fish shoals (raw ware 'game'/'fish' on the map).",
            "Running costs are charged per minute for every production building, warehouse, market and public building while switched on (running_cost), idle_cost while switched off (consumption.cpp for_each_cost). Houses cost nothing. Castles (castle, large_castle, fortress) cost their running_cost only for human players.",
            "Farms/plantations, hunters and fishers send exactly one worker (production.workers_out; logistics.cpp send_worker ignores Figuranz, which is 0 for the plantations in haeuser.cod: cod_figuranz). Pastures keep up to Figuranz animals out.",
            "All values are the haeuser.cod defaults as the engine loads them; data_fixes.cpp changes no economic field. A scenario's balance (sim/balance.cpp apply_building_values) and content packages (classes.toml, levels.toml, own buildings) can override them per game.",
            "Verification: the Python full_speed_seconds reproduces the engine's unit-test oracle (tests/unit/test_goods_statistics.cpp: fisher Speed 400, Worktime 2 s, radius 3, 1 t raw, Interval 30 -> 34 s; without figures 30 s; workshop -> its Interval 20 s). Real example: grain_farm = 8 + ((22*20000/220 + 8000) // 1000) * 32 >> 5 = 18 s.",
            "Mines (ore_mine, deep_ore_mine, gold_mine) take no raw ware: they dig 1 t per Interval from the deposit of the mountain slot they stand on (ore deposits are finite; a deep mine replaces an ore mine in place). Hunters shoot game (deer) in their radius, whose numbers are not modelled here: their cycle_s_at_full_speed assumes game is always found.",
            "Fishers: every open sea tile in reach carries fish; a fished tile regrows in 6 stages (growth class 5, 75 s each). The fisher's catchment counts land tiles too, so the number of sea tiles is what matters.",
            "Fertility: a field only grows on islands whose climate/fertility allows that crop; not modelled here.",
            "Building ids are the HAUS Id of haeuser.cod (island tiles store id - 20000); names are the stable names of engine/assets/src/original_names.cpp (package 'anno1602:').",
        ],
        "food": {"ware": "food", "ware_id": 14, "cod_nahrung_t_per_100_per_min": food,
                 "engine_units_per_inhabitant_per_10s": food_k,
                 "t_per_100_inhabitants_per_min": round(per_tick_to_t_per_100_min(food_k), 6)},
        "classes": classes,
        "levels_available_from_start": always,
        "unlock_levels": [
            {"infra": lvl, "name": level_names.get(lvl), "class": class_names.get(c), "class_id": c,
             "min_inhabitants_of_class_or_higher": mw, "buildings": buildings_by_infra.get(lvl, [])}
            for lvl, (c, mw) in sorted(infra_levels.items())
        ],
        "buildings": buildings,
        "wares": wares,
    }
    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out}: {len(classes)} classes, {len(buildings)} buildings, {len(wares)} wares")
    return 0


if __name__ == "__main__":
    sys.exit(main())
