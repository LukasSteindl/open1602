#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Plays Open1602 with a Jev-style decision model (System One API), local through Ollama.

The split of work (as in the Pokemon Red setup of Jev with a coaching LLM):
- this script, every few seconds: reads the game through o1602-ctl, builds a short list of legal
  actions, asks the decision model which one helps most, carries it out and logs it;
- a coach (Claude Code) reads the log every few minutes and changes the rules below: which
  actions are offered, how they are worded, which are filtered out.

Usage (the game started with --control 7602):
    python -I tools/agent/jev_driver.py                 # loop, one decision every 8 s
    python -I tools/agent/jev_driver.py --once --dry    # one decision, show it, do nothing
    python -I tools/agent/jev_driver.py --model nimble --interval 5 --island 10

Every decision goes to tools/agent/jev_log.jsonl (state, options, probabilities, result).
"""
from __future__ import annotations

import argparse
import heapq
import json
import os
import re
import threading
import subprocess
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import strategy  # noqa: E402  the long-term plan (planner stages, Gozintograph)

HERE = Path(__file__).resolve().parent
# A copy of this driver elsewhere (a tournament agent's folder) finds the tool through O1602_CTL.
CTL = Path(os.environ["O1602_CTL"]) if os.environ.get("O1602_CTL") else \
    HERE.parent.parent / "bin" / ("o1602-ctl.exe" if sys.platform == "win32" else "o1602-ctl")
LOG = HERE / "jev_log.jsonl"


VERBOSE = False  # --verbose: every game query and every Jev request on the terminal
GREY, CYAN, YELLOW, GREEN, RESET = "\033[90m", "\033[96m", "\033[93m", "\033[92m", "\033[0m"


UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss", "–": "-", "„": "\"", "“": "\""})
READ_ONLY = {"state", "cities", "map", "production", "alerts", "houses", "house-sites", "sites", "unconnected",
             "buildings", "islands", "coverage", "find-site", "kontor-sites", "goods", "help"}  # not ships: they move
CACHE: dict[tuple, tuple[int, str]] = {}  # read answers of this round; any other command clears it

# Decisions per game minute, shown over the map (user: how many decisions do you and Jev make per
# game minute?). Events carry the game clock, so the rate does not depend on the game speed.
STATS: list[tuple[float, str]] = []  # (game seconds, kind): rule, hosted, local, cmd, review
STAT_WINDOW = 30 * 60                # average over the last 30 game minutes
GAME_T = {"now": 0.0, "start": None}
REVIEWS = HERE / "reviews.md"        # Claude Code appends one entry per strategy review
REFLECTION = HERE / "reflection.txt"  # Claude Code's self-reflection after each review, shown to viewers
REFLECTION_SHOWN = {"text": ""}


def reflection_line() -> str | None:
    """Claude Code's latest self-reflection (user: build self-reflection into the stream as a
    comment): first line of the overlay, and said once in the comment lines when it changes."""
    try:
        text = REFLECTION.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    if text != REFLECTION_SHOWN["text"]:
        REFLECTION_SHOWN["text"] = text
        ctl("say", f"Claude denkt nach: {text[:150]}")
    return f"Selbstreflexion (Claude Code): {text}"
REVIEW_MTIME = {"t": None}
NOT_ACTIONS = {"say", "plan", "speed", "camera", "screenshot", "chat"}


def stat(kind: str) -> None:
    STATS.append((GAME_T["now"], kind))


def tick_game_clock() -> None:
    """Reads the game clock (time H:MM:SS) and notes a new Claude Code review (reviews.md changed)."""
    m = re.search(r"time (\d+):(\d+):(\d+)", ctl("state")[1])
    if m:
        GAME_T["now"] = int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3])
        if GAME_T["start"] is None:
            GAME_T["start"] = GAME_T["now"]
    try:
        mt = REVIEWS.stat().st_mtime
    except OSError:
        return
    if REVIEW_MTIME["t"] is not None and mt != REVIEW_MTIME["t"]:
        stat("review")
    REVIEW_MTIME["t"] = mt


def rate_line() -> str:
    """One line for the overlay: decisions and game commands per game minute."""
    t = GAME_T["now"]
    STATS[:] = [e for e in STATS if t - e[0] < STAT_WINDOW]
    span = max(1.0, min(STAT_WINDOW, t - (GAME_T["start"] or t)) / 60)
    c = Counter(k for _, k in STATS)
    f = lambda k: f"{c[k] / span:.1f}".replace(".", ",")  # noqa: E731
    reviews = f"Claude Code 1 Review alle {span / c['review']:.0f} Spielmin" if c["review"] else "Claude Code: noch keine Review"
    return (f"Pro Spielminute: {f('rule')} Regel, {f('hosted')} Jev hosted, {f('local')} Jev lokal, "
            f"{f('cmd')} Spielbefehle; {reviews} (Schnitt {span:.0f} Spielmin)")


def ctl(*args: str) -> tuple[int, str]:
    key = tuple(map(str, args))
    if args and args[0] in READ_ONLY:
        if key in CACHE:
            return CACHE[key]
    elif args and args[0] not in ("say", "plan"):
        CACHE.clear()  # the game changed: read everything afresh
        if args[0] not in NOT_ACTIONS and not (args[0] == "diplomacy" and len(args) == 1):
            stat("cmd")
        if args[0] == "demolish" and len(args) >= 4:
            DEMOLISHED.add((int(args[1]), int(args[2]), int(args[3])))  # not a fire: no rebuild
    if args and args[0] in ("say", "plan"):
        # The game's font reads bytes as Latin-1: umlauts came out as "BÃ¼rger" on the stream.
        args = tuple(str(a).translate(UMLAUTS) for a in args)
    r = subprocess.run([str(CTL), *map(str, args)], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120)
    if args and args[0] in READ_ONLY:
        CACHE[key] = (r.returncode, r.stdout)
    if VERBOSE and args and args[0] != "say":
        first = (r.stdout.strip().splitlines() or [""])[0]
        lines = len(r.stdout.strip().splitlines())
        more = f"  (+{lines - 1} lines)" if lines > 1 else ""
        print(f"{GREY}  game> {' '.join(map(str, args))}{RESET}  {first[:110]}{GREY}{more}{RESET}", flush=True)
    return r.returncode, r.stdout


# ---------------------------------------------------------------------------------------------
# Reading the game


def read_state(island: int) -> dict:
    _, st = ctl("state")
    _, city = ctl("cities", island, 0)
    s: dict = {"island": island}
    m = re.search(r"money (-?\d+).*taxes (-?\d+), running costs (-?\d+).*balance (-?\d+); inhabitants (\d+)", st)
    if m:
        s.update(money=int(m[1]), taxes=int(m[2]), running=int(m[3]), balance=int(m[4]), inhabitants=int(m[5]))
    m = re.search(r"next unlock: (.*)", st)
    s["next_unlock"] = m[1].strip() if m else ""
    s["classes"] = {}
    for line in city.splitlines():
        m = re.match(r"(pioneers|settlers|citizens|merchants|aristocrats): (\d+) inhabitants, satisfaction (\d+).*?"
                     r"tax (\d+), supplied:(.*)", line)
        if m:
            supply = {w: int(p) for w, p in re.findall(r"(\w+) (\d+)%", m[5])}
            s["classes"][m[1]] = {"people": int(m[2]), "satisfaction": int(m[3]), "tax": int(m[4]),
                                  "supply": supply}
        m = re.match(r"taxes -?\d+, food supplied (\d+)%", line)
        if m:
            s["food_supply"] = int(m[1])
        if line.startswith("stock:"):
            s["stock"] = {w: float(t) for w, t in re.findall(r"(\w+) ([\d.]+);", line)}
        m = re.match(r"houses by class: ([\d/]+); without market (\d+)", line)
        if m:
            s["houses"] = [int(x) for x in m[1].split("/")]
            s["houses_without_market"] = int(m[2])
        if line.startswith("Kontor trade:"):
            s["buying"] = re.findall(r"buys (\w+)", line)
            s["selling"] = re.findall(r"sells (\w+)", line)
    s.setdefault("stock", {})
    return s


def read_buildings() -> dict[str, dict]:
    _, out = ctl("buildings")
    b = {}
    for line in out.splitlines():
        m = re.match(r"(\w+): \d+, (\d+)x(\d+), (-?\d+)/([\d.]+)/([\d.]+)/([\d.]+), (\d+)", line)
        if m:
            b[m[1]] = {"gold": int(m[4]), "tools": float(m[5]), "wood": float(m[6]), "bricks": float(m[7]),
                       "running": int(m[8]), "size": (int(m[2]), int(m[3]))}
    return b


def house_site(island: int) -> tuple[int, int, int] | None:
    """The best house place: one 'house-sites' call lists every free place on the island with a
    road at its side and a market in reach, nearest to a market first (it replaced ~25 find-site
    calls along the road network). Never on the way a street would grow on (user: houses at the
    street ends made dead ends the network could not be extended from)."""
    grid = island_map(island)
    blocked = street_extensions(grid)
    # Never on a farm's field window: the game lets a house replace a field, the text map shows
    # fields like forest, and houses ate the fields of the tobacco plantation 56,17 (26 -> 4), the
    # Prahag sugar plantations and a winery on Ackstedt within an hour.
    bl = read_buildings()
    for name, fx, fy, _u in production(island):
        if field_of(name, bl):
            rr = int(PLAN_DATA["buildings"].get(name, {}).get("radius_tiles", 2) or 2)
            blocked |= {(i, k) for i in range(fx - rr, fx + 2 + rr) for k in range(fy - rr, fy + 2 + rr)}
    _, out = ctl("house-sites", island, 40)
    cands = []
    for line in out.splitlines()[1:]:
        p = line.split()
        if len(p) >= 2 and p[0].isdigit():
            x, y = int(p[0]), int(p[1])
            if not ({(x, y), (x + 1, y), (x, y + 1), (x + 1, y + 1)} & blocked):
                cands.append((x, y))
    if not cands:
        return None
    # Dense: the free place closest to the houses there are, so a chapel, tavern or bathhouse
    # reaches as many houses as possible (user: build the houses close together).
    hs = house_origins(grid)
    if hs:
        hx = sum(x for x, _ in hs) / len(hs)
        hy = sum(y for _, y in hs) / len(hs)
        cands.sort(key=lambda c: abs(c[0] - hx) + abs(c[1] - hy))
    return cands[0][0], cands[0][1], 0


def street_extensions(grid: dict, reach: int = 4) -> set[tuple[int, int]]:
    """The tiles straight beyond every street end (a road tile with one road neighbour), `reach`
    tiles far: kept free so the street can be extended later."""
    road = {p for p, v in grid.items() if v in ROAD}
    out: set[tuple[int, int]] = set()
    for (x, y) in road:
        nbrs = [(dx, dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)) if (x + dx, y + dy) in road]
        if len(nbrs) != 1:
            continue
        dx, dy = -nbrs[0][0], -nbrs[0][1]  # onward, away from the street
        for k in range(1, reach + 1):
            t = (x + dx * k, y + dy * k)
            if grid.get(t) not in FREE:
                break  # sea, river, a building: the street cannot go on there anyway
            out.add(t)
    return out


def best_site(name: str, island: int, x: int, y: int, radius: int) -> tuple[int, int, int] | None:
    """The nearest place with a road at its side (houses: also reached by a market)."""
    if name == "house":
        return house_site(island)
    _, out = ctl("find-site", name, island, x, y, radius)
    for line in out.splitlines()[1:]:
        p = line.split()
        if len(p) >= 4 and p[3] == "road":
            if name == "house" and "marketplace" not in line and "warehouse" not in line:
                continue
            return int(p[0]), int(p[1]), int(p[2])
    return None


def island_map(island: int) -> dict[tuple[int, int], str]:
    """The island as text tiles (x, y) -> legend character (o1602-ctl map)."""
    _, out = ctl("map", island)
    grid: dict[tuple[int, int], str] = {}
    lines = out.splitlines()
    x0 = 0
    m = re.search(r"tiles x (\d+)\.\.", lines[0]) if lines else None
    if m:
        x0 = int(m[1])
    for line in lines[3:]:
        m = re.match(r"\s*(\d+) (.*)$", line)
        if m:
            y = int(m[1])
            for i, ch in enumerate(m[2]):
                grid[(x0 + i, y)] = ch
    return grid


def trees_around(grid: dict, x: int, y: int, size: int = 2, radius: int = 3) -> int:
    """Forest tiles a forester at (x, y) can cut (radius 3 around its 2x2 footprint)."""
    return sum(1 for dy in range(-radius, size + radius) for dx in range(-radius, size + radius)
               if grid.get((x + dx, y + dy)) in ("T", "t"))


def pasture_around(grid: dict, x: int, y: int, size: int = 2, radius: int = 3) -> int:
    """Open meadow minus forest around a sheep farm at (x, y): sheep graze grass, not trees."""
    tiles = [grid.get((x + dx, y + dy)) for dy in range(-radius, size + radius)
             for dx in range(-radius, size + radius)]
    return sum(t == ":" for t in tiles) - sum(t in ("T", "t") for t in tiles)


def ranked_sites(name: str, island: int, grid: dict, gap: int = 7, n: int = 20) -> list[tuple[tuple[int, int, int], int]]:
    """The game's own ranking of the whole island for a building ('sites': trees, meadow, water,
    free field land or quarry tiles in its catchment), keeping only places a road can link to a
    market and that are away from another building of the same kind (catchments would overlap)."""
    rows = production(island)
    hs = house_origins(grid)
    _, out = ctl("sites", name, island, n)
    picked = []
    for line in out.splitlines()[1:]:
        p = line.split()
        if len(p) < 5 or not p[0].isdigit():
            continue
        x, y, rot, score = int(p[0]), int(p[1]), int(p[2]), int(p[4])
        if not far_from(rows, name, x, y, gap):
            continue
        if p[3] != "road" and not reachable(grid, x, y, 2, 2):
            continue  # no road, bridge or pier could ever link it: its goods would never arrive
        # Fishers may stand a little further out (Essix: the best fish ground, score 45, lay 15 tiles
        # from the Kontor, and 84 pioneers starved on one fisher).
        if not near_market(grid, x, y, 18 if name == "fishers_hut" else 14):
            continue  # its goods must reach a market or the Kontor quickly (user: the wool road was long)
        # Never inside a block of houses (user: "you seriously built a sheep farm where the weaver
        # stood?" - the freed plot in the town centre had 9 meadow tiles and the farm took it).
        # Farms, plantations, foresters and fishers belong at the edge of town; that plot is for houses.
        # Fishers excepted: they stand on the shore, take no room a house could use, and the dense
        # colonies starved when the filter left them no fisher place (Prahag 0.1 t food, 234 settlers).
        if name != "fishers_hut" and sum(1 for hx, hy in hs if abs(hx - x) <= 5 and abs(hy - y) <= 5) >= 4:
            continue
        picked.append(((x, y, rot), score))
    return picked


def near_market(grid: dict, x: int, y: int, reach: int = 14) -> bool:
    """A market or Kontor within `reach` tiles: raw goods go there, and the processors fetch them
    from there (user: the goods must be in the Kontor or market, the workshops take them from it)."""
    return any(abs(hx - x) + abs(hy - y) <= reach for (hx, hy), v in grid.items() if v in HUBS)


def forest_site(island: int, grid: dict) -> tuple[tuple[int, int, int], int] | None:
    """The place where a forester finds the most trees (the game's 'sites forester')."""
    best = ranked_sites("forester", island, grid)
    # critic: only one forester really produced below 30; but Essix's best places had 26-29 trees
    # and 57 houses waited for wood to rise, with one forester at 32%: 24 (the forest is planted too).
    return best[0] if best and best[0][1] >= 24 else None


def pasture_site(island: int, grid: dict) -> tuple[tuple[int, int, int], int] | None:
    """The place where a sheep farm finds the most open meadow and the least forest."""
    best = ranked_sites("sheep_farm", island, grid)
    # User: "without fields a sheep farm's efficiency is practically 0" - the farm in town had 9
    # meadow tiles; the sheep graze open meadow in radius 3 (up to ~60 tiles): ask for at least 24.
    return best[0] if best and best[0][1] >= 24 else None


def field_site(island: int, grid: dict, name: str) -> tuple[tuple[int, int, int], int] | None:
    """The place where a plantation or farm has the most free own land for its fields."""
    best = ranked_sites(name, island, grid, gap=5)
    # A winery wants 26 vines for full speed: no fewer than 20 free tiles (two wineries among the
    # houses got 7 vines each and ran at 26-41%).
    # A grain farm reaches only radius 1 (12 field tiles at most).
    need = 20 if name == "winery" else 9 if name == "grain_farm" else 14
    return best[0] if best and best[0][1] >= need else None


def water_site(island: int, grid: dict) -> tuple[tuple[int, int, int], int] | None:
    """A fisher's place with the most open sea, away from other fishers (radius 5 overlaps)."""
    best = ranked_sites("fishers_hut", island, grid, gap=9)
    return best[0] if best and best[0][1] >= 10 else None  # fish-ground tiles (engine counts only those now)


PAVED: set = set()


def pave(island: int, grid: dict, max_runs: int = 3, dry: bool = False):
    """Turns the busiest dirt roads into paved roads (faster carts; 1 t of bricks per tile): the
    straight road runs of the network that touch a market or the Kontor first."""
    net = network(grid)
    runs = []
    for (x, y) in net:
        if (x - 1, y) not in net and (x + 1, y) in net:   # start of a horizontal run
            x2 = x
            while (x2 + 1, y) in net:
                x2 += 1
            runs.append((x, y, x2, y))
        if (x, y - 1) not in net and (x, y + 1) in net:   # start of a vertical run
            y2 = y
            while (x, y2 + 1) in net:
                y2 += 1
            runs.append((x, y, x, y2))
    def near_hub(r):
        return any(grid.get((r[0] + dx, r[1] + dy)) in HUBS for dx in range(-2, 3) for dy in range(-2, 3))
    runs.sort(key=lambda r: (not near_hub(r), -(abs(r[2] - r[0]) + abs(r[3] - r[1]))))
    # Each run is tried once: paved or refused (bridge, square), it is not offered again.
    runs = [r for r in runs if (island, r) not in PAVED]
    if dry:
        return len(runs)
    done = []
    for r in runs[:max_runs]:
        PAVED.add((island, r))
        code, out = ctl("road", island, *r, "stone")
        done.append(out.strip().splitlines()[-1] if out.strip() else f"exit {code}")
    return "; ".join(done)


def road_to_network(grid: dict, x: int, y: int) -> tuple[int, int, int, int] | None:
    """A road from beside a 2x2 building at (x, y) to the nearest road tile (for o1602-ctl road)."""
    roads = [k for k, v in grid.items() if v in ("=", "#", "+")]
    if not roads:
        return None
    starts = [(x - 1, y), (x + 2, y), (x, y - 1), (x, y + 2), (x - 1, y + 1), (x + 2, y + 1)]
    best = None
    for sx, sy in starts:
        if grid.get((sx, sy)) not in (":", "T", "t", ".", "="):
            continue
        for rx, ry in roads:
            d = abs(rx - sx) + abs(ry - sy)
            if best is None or d < best[0]:
                best = (d, sx, sy, rx, ry)
    return best[1:] if best else None


ROAD = ("=", "#", "+", "p")  # p: pier, carts walk on it
FREE = (":", "T")          # own land a road or a house may take (forest is cleared)
HUBS = ("M", "K")          # markets and Kontors: their carts start here


def network(grid: dict) -> set[tuple[int, int]]:
    """Road tiles connected to a market or Kontor (the network the carts and the fire brigade use)."""
    start = [k for k, v in grid.items() if v in ROAD and any(
        grid.get((k[0] + dx, k[1] + dy)) in HUBS for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))]
    seen = set(start)
    todo = list(start)
    while todo:
        x, y = todo.pop()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (x + dx, y + dy)
            if n not in seen and grid.get(n) in ROAD:
                seen.add(n)
                todo.append(n)
    # A building standing next to a hub is served directly.
    return seen


def touches(net: set, grid: dict, x: int, y: int, w: int, h: int) -> bool:
    """Whether the footprint has a side tile on the network (or right next to a market/Kontor)."""
    for i in range(w):
        for p in ((x + i, y - 1), (x + i, y + h)):
            if p in net or grid.get(p) in HUBS:
                return True
    for j in range(h):
        for p in ((x - 1, y + j), (x + w, y + j)):
            if p in net or grid.get(p) in HUBS:
                return True
    return False


def isolated(island: int, grid: dict, buildings: dict) -> list[tuple[str, int, int, int, int]]:
    """Own production buildings and houses no network road reaches."""
    net = network(grid)
    out = []
    _, prod = ctl("production")
    for line in prod.splitlines():
        m = re.match(r"(\w+) at (\d+),(\d+) \((\d+)\)", line)
        if not m or int(m[4]) != island or m[1] in ("warehouse_1", "warehouse_2", "warehouse_3", "warehouse_4",
                                                  "marketplace", "quarry"):
            continue
        w, h = buildings.get(m[1], {}).get("size", (2, 2))
        if m[1] in ("fishers_hut", "hunters_hut"):
            w, h = 1, 1
        if not touches(net, grid, int(m[2]), int(m[3]), w, h):
            out.append((m[1], int(m[2]), int(m[3]), w, h))
    _, unc = ctl("unconnected", island)
    for m in re.finditer(r"house at (\d+),(\d+)", unc):
        out.append(("house", int(m[1]), int(m[2]), 2, 2))
    return out


def road_path(grid: dict, starts: list[tuple[int, int]], net: set,
              through_houses: bool = False, hub_goal: bool = True) -> list[tuple[int, int]] | None:
    """The shortest way over land a road may take from one of `starts` to a network road or a tile
    beside a market or Kontor (breadth-first search on the island's tiles)."""
    def goal(p):
        # hub_goal=False: only a real road link counts (firefighters and doctors walk roads; a
        # marketplace between two road pieces joins them for carts, not for them).
        return p in net or (hub_goal and any(grid.get((p[0] + dx, p[1] + dy)) in HUBS
                                             for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))))
    # Cost per tile: own land 1, river (a bridge) 3, beach 4 (a pier: 2 t bricks; coach: the
    # Kontor on island 3 stood in a pocket of beach and mountain, piers link it to the island).
    cost = {**{c: 1 for c in FREE + ROAD}, "w": 3}
    if PIER_BRICKS.get("ok", False):  # piers only with bricks in the Kontor (coach: no bricks, no pier)
        # Dear enough that the road crosses the beach where it is narrowest (coach: three piers ran
        # along the long side of a beach where one across the short side would have done).
        cost["b"] = 10
    if through_houses:
        # A new quarter may cost a house or two in its way (user: "pull houses down and plan whole
        # quarters anew"); dear, so the link goes through as few as possible.
        cost["H"] = 15
    prev = {s: None for s in starts if grid.get(s) in cost}
    dist = {s: cost[grid[s]] for s in prev}
    heap = [(d, s) for s, d in dist.items()]
    heapq.heapify(heap)
    while heap:
        d, p = heapq.heappop(heap)
        if d > dist.get(p, 1 << 30):
            continue
        if goal(p):
            path = []
            while p is not None:
                path.append(p)
                p = prev[p]
            return path
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (p[0] + dx, p[1] + dy)
            c = cost.get(grid.get(n))
            if c is not None and d + c < dist.get(n, 1 << 30):
                dist[n] = d + c
                prev[n] = p
                heapq.heappush(heap, (d + c, n))
    return None


WALK = (".", ":", "T", "t", "=", "#", "+", "/", "^", "E")  # land a worker walks on (rivers and buildings not)


def worker_reaches(grid: dict, x: int, y: int, w: int, h: int, goal: str, radius: int) -> bool:
    """Whether the worker of a building at (x, y) can walk over land to a tile marked `goal`
    within `radius` (coach: the stonemason stood across a river from the quarry; its worker walks,
    the bridge lay behind the market, and no stone ever came)."""
    start = [(x + i, y - 1) for i in range(w)] + [(x + i, y + h) for i in range(w)] + \
            [(x - 1, y + j) for j in range(h)] + [(x + w, y + j) for j in range(h)]
    inside = lambda p: x - radius <= p[0] < x + w + radius and y - radius <= p[1] < y + h + radius  # noqa: E731
    seen = {p for p in start if grid.get(p) in WALK and inside(p)}
    todo = list(seen)
    while todo:
        p = todo.pop()
        if grid.get(p) == goal:
            return True
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (p[0] + dx, p[1] + dy)
            if n not in seen and inside(n) and grid.get(n) in WALK:
                seen.add(n)
                todo.append(n)
    return False


def reachable(grid: dict, x: int, y: int, w: int, h: int) -> bool:
    """A road (with bridges and piers where needed) can link the place to a market or Kontor:
    checked before building, so no forester stands where its wood can never be fetched."""
    return not connect_check(grid, x, y, w, h)


def lay_path(island: int, grid: dict, path: list[tuple[int, int]]) -> str:
    """Lays a road on every tile of the path that has none yet, in straight runs."""
    # Beach tiles get a pier (carts walk on piers), the rest a road.
    piers = [p for p in path if grid.get(p) == "b"]
    laid_piers = 0
    for p in piers:
        c, _ = ctl("build", "pier", island, p[0], p[1], 0)
        laid_piers += c == 0
    # River tiles get a wooden bridge, trying each rotation (critic and review: a road over a river
    # "succeeded" with nothing built; the ore mine got its access by a bridge at 44,15).
    for p in [p for p in path if grid.get(p) == "w"]:
        for rot in range(4):
            c, _ = ctl("build", "wooden_bridge", island, p[0], p[1], rot)
            if c == 0:
                break
    todo = [p for p in path if grid.get(p) not in ROAD and grid.get(p) not in ("b", "w")]
    laid = 0
    i = 0
    while i < len(todo):
        j = i
        # A straight run of consecutive tiles goes in one command.
        while j + 1 < len(todo) and (todo[j + 1][0] == todo[i][0] or todo[j + 1][1] == todo[i][1]) and \
                abs(todo[j + 1][0] - todo[j][0]) + abs(todo[j + 1][1] - todo[j][1]) == 1 and j - i < 6:
            j += 1
        code, _ = ctl("road", island, todo[i][0], todo[i][1], todo[j][0], todo[j][1])
        if code != 0:
            # Tile by tile where the drag path would go another way.
            for k in range(i, j + 1):
                c2, _ = ctl("road", island, todo[k][0], todo[k][1], todo[k][0], todo[k][1])
                laid += c2 == 0
        else:
            laid += j - i + 1
        i = j + 1
    pier_note = f", {laid_piers} of {len(piers)} piers (2 t bricks each)" if piers else ""
    return f"road of {laid} new tiles over {len(path)} tiles to the network{pier_note}"


PIER_BRICKS: dict = {"ok": False}


def update_pier_bricks(island: int) -> None:
    """Piers (2 t bricks each) are planned only while the island's Kontor holds at least 6 t."""
    _, out = ctl("cities", island, 0)
    m = re.search(r"bricks ([\d.]+);", out)
    PIER_BRICKS["ok"] = bool(m and float(m[1]) >= 6)


def connect(island: int, grid: dict, name: str, x: int, y: int, w: int, h: int) -> str:
    """Lays a road from beside a building along the shortest way to a road that reaches a market."""
    net = network(grid)
    sides = [(x + i, y - 1) for i in range(w)] + [(x + i, y + h) for i in range(w)] + \
            [(x - 1, y + j) for j in range(h)] + [(x + w, y + j) for j in range(h)]
    path = road_path(grid, sides, net)
    if path is None:
        return f"{name} at {x},{y}: no way to a market road over free land"
    return f"{name} at {x},{y}: " + lay_path(island, grid, path)


N4 = ((1, 0), (-1, 0), (0, 1), (0, -1))


def market_link(island: int, grid: dict, name: str, x: int, y: int, w: int, h: int, r: int) -> str | None:
    """A workshop's carrier fetches only from a market or Kontor within the workshop's radius, over
    roads (review: smelter, toolmaker and tobacco plantation at 54-59,22 sat on a road piece that
    reached a market 20 tiles away; market 56,28 lay in reach, a chapel and a house between - all
    three idle for hours with 20 t of ore in the Kontor). Links the building to the roads of a
    market in its reach, through a house if need be; None when it is linked or no market is near."""
    inside = lambda p: x - r <= p[0] < x + w + r and y - r <= p[1] < y + h + r  # noqa: E731
    hubs = {p for p, v in grid.items() if v in HUBS and inside(p)}
    if not hubs:
        return None
    start = [p for p, v in grid.items() if v in ROAD and inside(p) and any((p[0] + dx, p[1] + dy) in hubs for dx, dy in N4)]
    comp, todo = set(start), list(start)
    while todo:
        p = todo.pop()
        for dx, dy in N4:
            n = (p[0] + dx, p[1] + dy)
            if n not in comp and inside(n) and grid.get(n) in ROAD:
                comp.add(n)
                todo.append(n)
    sides = [(x + i, y - 1) for i in range(w)] + [(x + i, y + h) for i in range(w)] + \
            [(x - 1, y + j) for j in range(h)] + [(x + w, y + j) for j in range(h)]
    if any(s in comp or s in hubs for s in sides):
        return None
    # Goal: a road of those markets, or free land right beside one of them.
    goal = comp | {(hx + dx, hy + dy) for hx, hy in hubs for dx, dy in N4 if grid.get((hx + dx, hy + dy)) in FREE}
    path = road_path(grid, sides, goal, through_houses=True, hub_goal=False)
    if path is None:
        return f"{name} at {x},{y}: no market in its reach ({r} tiles) by road, and no way to link one"
    hs = house_origins(grid)
    gone = {(hx, hy) for px, py in path if grid.get((px, py)) == "H"
            for hx, hy in hs if hx <= px <= hx + 1 and hy <= py <= hy + 1}
    for hx, hy in gone:
        ctl("demolish", island, hx, hy)
    return f"{name} at {x},{y}: linked to a market in its reach ({len(gone)} houses made way): " + \
        lay_path(island, island_map(island), path)


def relieve_full_stores(island: int) -> list[str]:
    """A ware at the store's limit blocks the carts that bring it in (review: Prahag fishers and
    foresters, Kap Crus tobacco and Ackstedt wine stood uncollected while food, wood or bricks sat
    at the limit). Such a ware is sold down to 60% of the room."""
    _, out = ctl("cities", island, 0)
    m = re.search(r"room (\d+) t", out)
    if not m:
        return []
    room = int(m[1])
    st = re.search(r"^stock: (.*)$", out, re.M)
    done = []
    for ware, amount in re.findall(r"(\w+) ([\d.]+);", st[1] if st else ""):
        if float(amount) >= room - 3 and ware not in ("alcohol", "tobacco_goods", "cloth", "spices", "cocoa"):
            ctl("trade", island, 0, ware, "sell", int(room * 0.6))
            done.append(f"{ware} at the limit ({amount}/{room} t): sold above {int(room * 0.6)} t")
    return done


def free_enclosed_hubs(island: int) -> list[str]:
    """A market walled in by houses sends no cart out (review: on Essix markets 31,31 and 33,10
    had houses on every side; foresters, farms and bakeries stood full with nobody collecting, the
    town had 2 t of wood while 40 t waited). Links each such market to the road network through
    the fewest houses."""
    grid = island_map(island)
    done = []
    seen: set = set()
    for p, v in list(grid.items()):
        if v != "M" or p in seen:
            continue
        comp, k = [p], 0
        seen.add(p)
        while k < len(comp):
            x, y = comp[k]
            k += 1
            for dx, dy in N4:
                n = (x + dx, y + dy)
                if n not in seen and grid.get(n) == "M":
                    seen.add(n)
                    comp.append(n)
        sides = sorted({(x + dx, y + dy) for x, y in comp for dx, dy in N4} - set(comp))
        if any(grid.get(s) in ROAD for s in sides):
            continue
        net = network(grid)
        # Around rivers, not over them: the game refused the bridges there (market 33,10).
        dry = {t: ("~" if c == "w" else c) for t, c in grid.items()}
        path = road_path(dry, sides, net, through_houses=True, hub_goal=False)
        if path is None:
            done.append(f"market at {min(comp)} is walled in and no way out could be found")
            continue
        hs = house_origins(grid)
        gone = {(hx, hy) for px, py in path if grid.get((px, py)) == "H"
                for hx, hy in hs if hx <= px <= hx + 1 and hy <= py <= hy + 1}
        for hx, hy in gone:
            ctl("demolish", island, hx, hy)
        res = lay_path(island, island_map(island), path)
        done.append(f"market at {min(comp)} was walled in: {len(gone)} houses made way, {res}")
        grid = island_map(island)
    return done


def plan_quarter(island: int, grid: dict) -> dict | None:
    """A whole new quarter on free land (user: "plan whole quarters"): vertical streets every 5
    tiles with two rows of 2x2 houses between them, a cross street on top that joins the network.
    The streets' far ends stay open, so the quarter can grow. Returns roads, house plots and the
    connection, or None when no free rectangle lies in a market's reach near the network."""
    hubs = [p for p, v in grid.items() if v in ("M", "K")]
    net = network(grid)
    if not hubs or not net:
        return None
    free = {p for p, v in grid.items() if v == ":"}  # open own land only (forest stays for foresters)

    def near_hub(x, y):
        return any(abs(hx - x) <= 13 and abs(hy - y) <= 13 for hx, hy in hubs)

    best = None
    for (x0, y0) in free:
        for w in (16, 11, 6):  # 4, 3 or 2 streets
            for h in (11, 9, 7, 5):
                tiles = [(x, y) for y in range(y0, y0 + h) for x in range(x0, x0 + w)]
                if not all(t in free for t in tiles):
                    continue
                if not (near_hub(x0, y0) and near_hub(x0 + w - 1, y0 + h - 1)):
                    continue
                streets = [x0 + k for k in range(0, w, 5)]
                plots = [(sx + dx, y) for sx in streets[:-1] for dx in (1, 3) for y in range(y0 + 1, y0 + h - 1, 2)]
                score = len(plots)
                if best is None or score > best[0]:
                    best = (score, x0, y0, w, h, streets, plots)
                break
            if best and best[3] == w:
                break
    if best is None:
        return None
    score, x0, y0, w, h, streets, plots = best
    roads = [(x0, y0, x0 + w - 1, y0)] + [(sx, y0, sx, y0 + h - 1) for sx in streets]
    top = [(x, y0) for x in range(x0, x0 + w)]
    link = road_path(grid, top, net) or road_path(grid, top, net, through_houses=True)  # to the network
    if link is None:
        return None
    return {"roads": roads, "link": link, "plots": plots, "area": (x0, y0, w, h)}


def build_quarter(island: int, q: dict, wood: float) -> str:
    """Lays the quarter's streets and its link, then as many houses as the wood allows (3 t each);
    the rest of the plots the normal house rule fills later."""
    grid = island_map(island)
    torn = {t for t in q["link"] if grid.get(t) == "H"}
    for (hx, hy) in torn:  # the houses in the way of the link go first
        ctl("demolish", island, hx, hy)
    grid = island_map(island)
    laid = lay_path(island, grid, q["link"])
    for r in q["roads"]:
        ctl("road", island, *r)
    built = 0
    for (x, y) in q["plots"][: int(wood // 3)]:
        code, _ = ctl("build", "house", island, x, y, 0)
        built += code == 0
    x0, y0, w, h = q["area"]
    ctl("say", f"Neues Stadtviertel bei {x0},{y0} ({w}x{h}): {built} Haeuser, Platz fuer {len(q['plots'])}")
    return (f"quarter at {x0},{y0} ({w}x{h}): {len(q['roads'])} streets, link {laid}" +
            (f", {len(torn)} house tiles cleared" if torn else "") + f"; {built} of {len(q['plots'])} houses")


def plan_street(island: int, grid: dict, length: int = 8) -> tuple[list[int], int] | None:
    """A new street from the network into free own land, with room for houses on both sides:
    from a network tile, straight on for up to `length` tiles. Score: free 2x2 house places beside
    it (two tiles deep on each side)."""
    net = network(grid)
    # Starts: beside a network road, or right beside a market or Kontor (its carts start there).
    starts = set(net)
    for (hx, hy), v in grid.items():
        if v in HUBS:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                if grid.get((hx + dx, hy + dy)) in FREE:
                    starts.add((hx, hy))
    best = None
    for (x, y) in starts:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            tiles = []
            for k in range(1, length + 1):
                p = (x + dx * k, y + dy * k)
                if grid.get(p) not in FREE:
                    break
                # Two free rows of houses on each side, and no road in the third row (coach: it laid
                # streets right beside streets).
                side = [grid.get((p[0] + dy * sgn * d, p[1] + dx * sgn * d)) for sgn in (1, -1) for d in (1, 2)]
                third = [grid.get((p[0] + dy * sgn * 3, p[1] + dx * sgn * 3)) for sgn in (1, -1)]
                if any(t in ROAD for t in side) or (k > 1 and any(t in ROAD for t in third)):
                    break
                tiles.append(p)
            if len(tiles) < 4:
                continue
            # Free tiles two deep on both sides of the street.
            free = 0
            for (tx, ty) in tiles:
                for side in (1, -1):
                    for depth in (1, 2):
                        q = (tx + dy * side * depth, ty + dx * side * depth)
                        free += grid.get(q) in FREE
            houses = free // 4
            if best is None or houses > best[1]:
                best = ([x + dx, y + dy, tiles[-1][0], tiles[-1][1]], houses)
    return best


def any_site(name: str, island: int, x: int, y: int, radius: int) -> tuple[int, int, int] | None:
    """The nearest place a market reaches, road or not (fix-roads connects it afterwards)."""
    _, out = ctl("find-site", name, island, x, y, radius)
    for line in out.splitlines()[1:]:
        p = line.split()
        if len(p) >= 3 and ("marketplace" in line or "warehouse" in line or name != "house"):
            return int(p[0]), int(p[1]), int(p[2])
    return None


# ---------------------------------------------------------------------------------------------
# The options (the coach edits these rules)

# What produces what a class needs, and where to look for a place (around the town centre).
PRODUCERS = {
    "food": ["fishers_hut"],  # no hunters: one without game ran at 0% (user)
    "cloth": ["weaving_hut"],
    "alcohol": ["rum_distillery"],
    "wood": ["forester"],
}
SELL_ABOVE_T = 35      # sell what lies in the Kontor above this
KEEP_T = 20            # ... and keep this much
MIN_STOCK = {"tools": 8, "wood": 15, "bricks": 10}


def affordable(cost: dict, s: dict) -> bool:
    st = s["stock"]
    return (cost["gold"] <= max(0, s.get("money", 0)) and cost["tools"] <= st.get("tools", 0)
            and cost["wood"] <= st.get("wood", 0) and cost["bricks"] <= st.get("bricks", 0))


def production(island: int) -> list[tuple[str, int, int, int]]:
    """Own production buildings on the island: (name, x, y, utilisation %)."""
    _, out = ctl("production")
    rows = []
    for line in out.splitlines():
        m = re.match(r"(\w+) at (\d+),(\d+) \((\d+)\): \w[\w ]*, (\d+)%", line)
        if m and int(m[4]) == island:
            rows.append((m[1], int(m[2]), int(m[3]), int(m[5])))
    return rows


def far_from(rows: list, name: str, x: int, y: int, gap: int = 7) -> bool:
    """No building of the same kind within `gap` tiles (their catchments would overlap)."""
    return all(not (n == name and abs(bx - x) < gap and abs(by - y) < gap) for n, bx, by, _ in rows)


FIRST_SEEN: dict[tuple[str, int, int], float] = {}


PROCESSORS = ("weaving_hut", "weaving_mill", "tailor", "tobacco_products", "rum_distillery", "ore_smelter",
              "toolmaker", "grain_mill", "bakery", "butcher")


def repair(island: int) -> list[str]:
    """Coach's rule: a forester, sheep farm, fisher or hunter that has run below 20% for more than
    four minutes (a question mark over it in the game) has the wrong place: down with it; the
    normal rules build a new one where the trees, the meadow or the water are."""
    done = []
    now = time.time()
    grid = island_map(island)
    for name, x, y, util in production(island):
        key = (name, x, y)
        FIRST_SEEN.setdefault(key, now)
        # Relocate (user: "sometimes pulling down and planning anew beats stone roads"): a producer
        # far from every market that runs below 40% for four minutes moves to the best place in a
        # market's reach, a plantation with its fields - also the last of its kind.
        if util < 40 and now - FIRST_SEEN[key] > 240 and not near_market(grid, x, y) \
                and name in ("sheep_farm", "cattle_farm", "forester", "winery", "sugarcane_plantation",
                             "tobacco_plantation", "cotton_plantation", "spice_plantation", "cocoa_plantation"):
            bl = read_buildings()
            field = field_of(name, bl) if name != "forester" else None
            if name in ("sheep_farm", "cattle_farm"):
                found = pasture_site(island, grid)
            elif name == "forester":
                found = forest_site(island, grid)
            else:
                found = field_site(island, grid, name)
            if found and affordable(bl.get(name, {"gold": 1e9}), read_state(island)):
                (nx, ny, nr), _score = found
                ctl("demolish", island, x, y)
                code, _ = ctl("build", name, island, nx, ny, nr)
                if code == 0:
                    if field:
                        ctl("build-many", field, island, nx - 2, ny - 2, nx + 3, ny + 3)
                    connect(island, island_map(island), name, nx, ny, 2, 2)
                    done.append(f"{name} at {x},{y} ({util}%, far from any market) moved to {nx},{ny}")
                FIRST_SEEN.pop(key, None)
                grid = island_map(island)
                continue
        # A workshop with no raw producer on its island idles for good (user: "this weaver hut has had
        # no workload for a long time, why don't you pull it down?" - 0% for hours in the town
        # centre, no sheep farm on the island, cloth bought instead). Down with it, even the last of
        # its kind: it costs upkeep and takes room the houses need; the chain rules build a new one
        # only once its raw producer stands.
        if name in PROCESSORS and util < 10 and now - FIRST_SEEN[key] > 480:
            up = strategy.upstream(name)
            if up and not any(n_ == up for n_, *_ in production(island)):
                code, _ = ctl("demolish", island, x, y)
                if code == 0:
                    done.append(f"{name} at {x},{y} ran at {util}% with no {up} on the island: demolished")
                    FIRST_SEEN.pop(key, None)
                continue
        if name == "forester":
            # A forester waits for its planted trees: down only where few trees can ever grow.
            if trees_around(island_map(island), x, y) >= 12:
                continue
        # The last one of its kind stays (coach: the only sheep farms went, the weaving hut got no
        # wool, cloth fell to 4% and the settlers moved out); only a spare one goes.
        if sum(1 for n_, *_ in production(island) if n_ == name) <= 1:
            continue
        if name in ("forester", "sheep_farm", "fishers_hut", "hunters_hut", "stonemason") and util < 20 \
                and now - FIRST_SEEN[key] > 240:
            code, _ = ctl("demolish", island, x, y)
            if code == 0:
                done.append(f"{name} at {x},{y} ran at {util}%: demolished, a better place follows")
                FIRST_SEEN.pop(key, None)
    return done


def alerts(island: int) -> list[tuple[str, str]]:
    """The game's own warnings (o1602-ctl alerts): question marks with their cause, fires, full
    buildings, missing roads, houses without market or public buildings, short supply, full storage,
    low materials, money. Returns (tag, text) pairs, e.g. ("?", "forester at 14,27 (island 9): ...")."""
    _, out = ctl("alerts", island)
    rows = []
    for line in out.splitlines():
        m = re.match(r"\[(\S+)\] (.*)", line)
        if m:
            rows.append((m[1], m[2]))
    return rows


def handle_alerts(island: int, buildings: dict) -> list[str]:
    """Deterministic fixes for the alerts that have one obvious answer; the rest goes to Jev as state."""
    done = []
    for tag, text in alerts(island):
        m = re.match(r"(\w+) at (\d+),(\d+)", text)
        if tag == "ROAD" and m:
            w, h = buildings.get(m[1], {}).get("size", (1, 1))
            done.append(connect(island, island_map(island), m[1], int(m[2]), int(m[3]), w, h))
        elif tag == "HOUSE" and "no road" in text:
            _, out = ctl("fix-roads", island)
            done.append("houses without road: " + out.strip().splitlines()[0][:80] if out.strip() else "fix-roads")
        elif tag == "?" and m:
            # A question mark: the building finds no raw material (user: "so many buildings with
            # alerts: pull them down, or give them the supply chain or the fields they need").
            name, bx, by = m[1], int(m[2]), int(m[3])
            key = (island, name, bx, by)
            if time.time() - QM_DONE.get(key, 0) < 300:
                continue
            QM_DONE[key] = time.time()
            money = read_state(island).get("money", 0)
            same = sum(1 for n_, *_ in production(island) if n_ == name)
            field = field_of(name, buildings)
            r = int(PLAN_DATA["buildings"].get(name, {}).get("radius_tiles", 2) or 2)
            in_kontor = re.search(r"no \w+ delivered \(([\d.]+) t in the Kontor\)", text)
            linked = market_link(island, island_map(island), name, bx, by, 2, 2, r) \
                if in_kontor and float(in_kontor[1]) > 0 and money >= 300 else None
            if linked:
                done.append(f"? {linked}")
            elif name == "forester":
                if money >= 200:
                    _, out = ctl("build-many", "forest", island, bx - 3, by - 3, bx + 4, by + 4)
                    done.append(f"? forester {bx},{by}: planted forest ({out.strip().splitlines()[-1][:60]})")
                elif same > 1:
                    ctl("demolish", island, bx, by)
                    done.append(f"? forester {bx},{by}: too few trees, no gold to plant: demolished")
            elif name == "fishers_hut":
                fish = re.search(r"(\d+) fish-ground tiles", text)
                if fish and int(fish[1]) < 10 and same > 1:
                    ctl("demolish", island, bx, by)
                    done.append(f"? fisher {bx},{by}: only {fish[1]} fish-ground tiles: demolished")
            elif name in ("sheep_farm", "cattle_farm"):
                if same > 1:
                    ctl("demolish", island, bx, by)
                    done.append(f"? {name} {bx},{by}: too little meadow: demolished (a better place follows)")
            elif field and money >= 100:
                _, out = ctl("build-many", field, island, bx - r, by - r, bx + 1 + r, by + 1 + r)
                done.append(f"? {name} {bx},{by}: planted {field} ({out.strip().splitlines()[-1][:60]})")
        elif tag == "FIRE":
            # Burning houses: the fire station puts them out; without one, build it next to the fire
            # if gold and materials allow, else pull the burning houses down before the fire spreads
            # (coach: four houses burned down with no fire station on the island).
            burning = [(int(a), int(b)) for a, b in re.findall(r"(\d+),(\d+)", text.split(":", 2)[-1])]
            if counts(island).get("fire_station", 0) > 0 or not burning:
                continue
            fx, fy = burning[0]
            cost = buildings.get("fire_station")
            st = read_state(island)
            if cost and affordable(cost, st):
                _, out = ctl("find-site", "fire_station", island, fx, fy, 8)
                site = next((ln.split() for ln in out.splitlines()[1:] if len(ln.split()) >= 4), None)
                if site:
                    code, o2 = ctl("build", "fire_station", island, site[0], site[1], site[2])
                    if code == 0:
                        done.append(f"fire: fire station at {site[0]},{site[1]}")
                        continue
            for (hx, hy) in burning:
                ctl("demolish", island, hx, hy)
            done.append(f"fire: no fire station, pulled down {len(burning)} burning houses (firebreak)")
        elif tag == "STORE":
            ware = re.search(r": (\w+) storage full", text)
            if not ware:
                continue
            # Stone roads are faster but cost 5 gold a tile: only with gold to spare (review: paving on
            # every full brick store took the money from 240 down to 50 again and again).
            rich = read_state(island).get("money", 0) >= 800
            paved = pave(island, island_map(island), max_runs=1) if ware[1] == "bricks" and rich else ""
            if paved:
                done.append(paved)
            elif ware[1] not in ("wood", "tools", "food"):
                ctl("trade", island, 0, ware[1], "sell", 40)
                done.append(f"{ware[1]} storage full: selling above 40 t")
    return [d for d in done if d]


def house_origins(grid: dict) -> list[tuple[int, int]]:
    """Top-left tiles of the own houses on the text map (2x2 blocks of H)."""
    seen: set = set()
    out = []
    for (x, y), v in sorted(grid.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        if v == "H" and (x, y) not in seen and grid.get((x + 1, y)) == "H" and grid.get((x, y + 1)) == "H":
            out.append((x, y))
            seen.update({(x, y), (x + 1, y), (x, y + 1), (x + 1, y + 1)})
    return out


def houses_without(island: int, grid: dict, service: str) -> list[tuple[int, int]]:
    """Houses the given public building (chapel, tavern, school, church, ...) does not reach: one
    'houses' call (it replaced a 'coverage' call per house)."""
    _, out = ctl("houses", island)
    missing = []
    for line in out.splitlines()[2:]:
        p = line.split()
        if len(p) >= 7 and p[0].isdigit():
            have = p[6].split(":", 1)[1] if p[6].startswith("have:") else ""
            got = set(have.split(","))
            # A church serves settlers and citizens as a chapel does (houses.cpp: Kapelle | Kirche;
            # user: chapels can go where a church stands).
            if service not in got and not (service == "chapel" and "church" in got):
                missing.append((int(p[0]), int(p[1])))
    return missing


BUILDING_CHARS = set("HMKBCESLFWhmkbceslfw")


def double_roads(grid: dict) -> list[tuple[int, int]]:
    """Road tiles that only widen a road: part of a 2x2 block of roads and next to no building
    (coach: double-wide roads waste land)."""
    out = []
    for (x, y), v in grid.items():
        if v not in ROAD:
            continue
        in_block = any(all(grid.get((x + ax, y + ay)) in ROAD for ax in (0, dx) for ay in (0, dy))
                       for dx in (1, -1) for dy in (1, -1))
        near_building = any(grid.get((x + dx, y + dy)) in BUILDING_CHARS
                            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
        if in_block and not near_building:
            out.append((x, y))
    return out


def thin_roads(island: int, buildings: dict, limit: int = 30) -> str:
    """Removes double-road tiles one by one, keeping every building and house on the network."""
    removed = 0
    for _ in range(limit):
        grid = island_map(island)
        cands = double_roads(grid)
        if not cands:
            break
        before = len(isolated(island, grid, buildings))
        x, y = cands[0]
        code, _ = ctl("demolish", island, x, y)
        if code != 0:
            break
        grid2 = island_map(island)
        if len(isolated(island, grid2, buildings)) > before:
            ctl("road", island, x, y, x, y)  # it was needed after all: put it back
            continue
        removed += 1
    return f"removed {removed} tiles of double-wide road"


def counts(island: int) -> dict[str, int]:
    """How many of each production or public building the player has on the island."""
    n: dict[str, int] = {}
    for name, _, _, _ in production(island):
        n[name] = n.get(name, 0) + 1
    return n


# ---------------------------------------------------------------------------------------------
# Expansion to other islands (coach: the user wants fast expansion and many settler houses)

LIVE_ISLANDS: list[int] = []


ME = {"id": None}  # this player's number (0 in a game alone; a multiplayer game's joiners have others)


def my_id() -> int:
    if ME["id"] is None:
        m = re.search(r"^you: player (\d+)", ctl("state")[1], re.M)
        ME["id"] = int(m[1]) if m else 0
    return ME["id"]


def kontor_pos(island: int) -> tuple[int, int] | None:
    _, out = ctl("cities", island, 0)
    m = re.search(rf"owner {my_id()}, Kontor at (\d+),(\d+)", out)  # own Kontor only, not another's
    return (int(m[1]), int(m[2])) if m else None


def opening() -> tuple[int, int, int] | None:
    """A new game (--island auto): the home island is the one with the own city; without one, the
    start ship sails a little (an island counts as discovered once a ship has come within 5 tiles),
    founds the first Kontor on the nearest discovered island with land for a town, and unloads all
    it carries there. Returns (island, Kontor x, Kontor y), or None when that did not work yet."""
    CACHE.clear()  # called again and again before the main loop: read the game afresh each time
    _, out = ctl("cities")
    m = re.search(r"^island (\d+) city \d+ .*\(you\)", out, re.M)
    if m and (pos := kontor_pos(int(m[1]))):
        return int(m[1]), pos[0], pos[1]
    if re.search(r"^time \S+\s+paused", ctl("state")[1], re.M):
        return None  # a tournament waits for every player: no orders before it runs
    ship = my_ship()
    if ship is None:
        return None
    _, out = ctl("islands")
    found = []
    for line in out.splitlines():
        mm = re.match(r"island (\d+): world (\d+),(\d+) size (\d+)x(\d+), \w+, discovered, .*cities of: nobody", line)
        if mm:
            cx, cy = int(mm[2]) + int(mm[4]) // 2, int(mm[3]) + int(mm[5]) // 2
            d2 = (cx - ship["x"]) ** 2 + (cy - ship["y"]) ** 2
            found.append((int(mm[4]) * int(mm[5]) < 1600, d2, int(mm[1])))  # 40x40 and more first
    if not found:
        # Nothing discovered yet: a short trip in the open sea lets the ship see the islands around.
        ctl("ship-move", ship["id"], ship["x"] + 12, ship["y"] + 6)
        return None
    for _, _, isl in sorted(found)[:3]:
        _, sites = ctl("kontor-sites", ship["id"], isl)
        m = re.search(r"\(world (\d+),(\d+)\)", sites)
        if not m or not sail_to(ship["id"], int(m[1]), int(m[2])):
            continue
        _, sites = ctl("kontor-sites", ship["id"], isl)
        ok = re.search(r"\n\s+(\d+) (\d+): ok \(world (\d+),(\d+)\)", sites)
        if not ok:
            continue
        code, out = ctl("found", ship["id"], isl, ok[1], ok[2])
        if code != 0:
            continue
        sail_to(ship["id"], int(ok[3]), int(ok[4]), timeout=60)
        _, ships = ctl("ships")
        cargo = re.search(rf"ship {ship['id']} .*\n\s+cargo: (.*)", ships)
        for w, t in re.findall(r"(\w+) ([\d.]+) t", cargo[1] if cargo else ""):
            ctl("unload", ship["id"], w, int(float(t) + 0.99))
        ctl("chat", f"Jev: mein erster Kontor steht auf Insel {isl}.")
        return isl, int(ok[1]), int(ok[2])
    return None


def free_islands() -> list[dict]:
    """Islands nobody has settled, with their world position, size and crops, nearest first later."""
    _, out = ctl("islands")
    res = []
    for line in out.splitlines():
        m = re.match(r"island (\d+): world (\d+),(\d+) size (\d+)x(\d+), (\w+), .*crops:(.*); cities of: nobody", line)
        if m:
            res.append({"island": int(m[1]), "x": int(m[2]), "y": int(m[3]), "w": int(m[4]), "h": int(m[5]),
                        "climate": m[6], "crops": m[7].strip()})
    return res


def my_ship() -> dict | None:
    _, out = ctl("ships")
    m = re.search(r"ship (\d+) \"[^\"]*\" figure \d+ at world (\d+),(\d+) (\w+)", out)
    if not m:
        return None
    return {"id": int(m[1]), "x": int(m[2]), "y": int(m[3]), "idle": m[4] == "idle",
            "at_home": "lies at the Kontor" in out and "(yours)" in out}


def colony_target(home: int) -> dict | None:
    """The nearest free island of at least 30x30 (a short trip, so the colony grows soon)."""
    ship = my_ship()
    if ship is None:
        return None
    cands = [i for i in free_islands() if i["w"] >= 30 and i["island"] not in LIVE_ISLANDS]
    if not cands:
        return None
    return min(cands, key=lambda i: abs(i["x"] + i["w"] // 2 - ship["x"]) + abs(i["y"] + i["h"] // 2 - ship["y"]))


def sail_to(ship: int, wx: int, wy: int, timeout: float = 180.0) -> bool:
    """Sends the ship to a sea tile near (wx, wy) and waits until it lies still."""
    for r in range(0, 8):
        for dx, dy in ((-r, 0), (r, 0), (0, -r), (0, r), (-r, -r), (r, r), (-r, r), (r, -r)):
            code, _ = ctl("ship-move", ship, wx + dx, wy + dy)
            if code == 0:
                t0 = time.time()
                time.sleep(3)
                while time.time() - t0 < timeout:
                    s = my_ship()
                    if s and s["idle"]:
                        return True
                    time.sleep(2)
                return False
    return False


FAILED_AT: dict = {}                   # option key -> when it last failed for want of a place
QM_DONE: dict = {}                     # question-mark buildings handled lately (once per 5 minutes)
SHIP_BUSY = {"on": False, "what": ""}  # a supply run in the background holds the ship
ROUTE = {"on": False}                  # the ship runs a standing trade route between supply runs


def world_kontor(island: int) -> tuple[int, int] | None:
    """World position of the own Kontor of an island (island origin + Kontor tile)."""
    _, out = ctl("islands")
    m = re.search(rf"island {island}: world (\d+),(\d+)", out)
    k = kontor_pos(island)
    return (int(m[1]) + k[0], int(m[2]) + k[1]) if m and k else None


def supply_run(home: int, colony: int, loads: list[tuple[str, int]]) -> str:
    """The ship fetches goods at home and brings them to the colony, in the background so the
    driver plays on meanwhile (coach: the colony's forester needed piers, piers need bricks, the
    bricks lay at home and the ship idled: a local optimum)."""
    ship = my_ship()
    src, dst = world_kontor(home), world_kontor(colony)
    # A ship on the standing trade route may be taken for the run (the route starts again after it).
    if ship is None or not (ship["idle"] or ROUTE["on"]) or src is None or dst is None or SHIP_BUSY["on"]:
        return "no supply run: ship busy or no Kontor"
    what = ", ".join(f"{t} t {w}" for w, t in loads)
    SHIP_BUSY.update(on=True, what=f"{what} to island {colony}")

    def trip() -> None:
        try:
            ctl("say", f"Versorgungsfahrt: {what} von Insel {home} nach Insel {colony}")
            ctl("route", ship["id"], "stop")
            if not sail_to(ship["id"], *src):
                return
            loaded = []
            for w, t in loads:
                code, _ = ctl("load", ship["id"], w, t)
                if code == 0:
                    loaded.append((w, t))
            if not loaded or not sail_to(ship["id"], *dst):
                return
            for w, t in loaded:
                ctl("unload", ship["id"], w, t)
            ctl("say", f"Versorgung angekommen auf Insel {colony}: {what}")
        finally:
            SHIP_BUSY["on"] = False
            if ROUTE["on"]:
                ctl("route", ship["id"], "start")  # back to the trade route

    threading.Thread(target=trip, daemon=True).start()
    return f"supply run started: {what} from island {home} to island {colony}"


def s_home_stock(home: int) -> dict:
    return read_state(home)["stock"]


def arm_ships() -> list[str]:
    """Every ship lying at an own Kontor gets cannons from that Kontor's store (user: equip all
    ships with cannons): load what fits, mount, put back what could not be mounted."""
    _, out = ctl("ships")
    done = []
    for m in re.finditer(r'^ship (\d+) "[^"]*" figure \d+ at world \d+,\d+ \w+, health \d+, cannons (\d+)\n'
                         r'  lies at the Kontor of island (\d+) city 0 \(yours\)', out, re.M):
        sid, cannons, isl = int(m[1]), int(m[2]), int(m[3])
        if cannons >= 8:
            continue
        have = read_state(isl)["stock"].get("cannons", 0)
        if have < 1:
            continue
        code, _ = ctl("load", sid, "cannons", int(min(have, 8 - cannons)))
        if code != 0:
            continue  # holds full (cargo or soldiers)
        _, a = ctl("arm", sid)
        ctl("unload", sid, "cannons", 10)
        done.append(f"ship {sid}: {a.strip()[:50]}")
    return done


WEAPON_KEEP = {"cannons": 4, "swords": 4}  # per island: towers in an attack, recruits at a castle


def distribute_weapons() -> str | None:
    """Cannons on every own island, swords on the islands with a castle (user: spread the swords
    and cannons so that cannon towers go up at once when someone attacks, and castles can train).
    The island holding the most sends one supply run to the island lacking most."""
    try:
        castles = {int(k) for k in json.load(open(CASTLE_FILE, encoding="utf-8"))}
    except (OSError, ValueError):
        castles = set()
    stocks = {i: read_state(i)["stock"] for i in LIVE_ISLANDS}
    for ware, keep in WEAPON_KEEP.items():
        wanting = [i for i in LIVE_ISLANDS if (ware == "cannons" or i in castles) and stocks[i].get(ware, 0) < keep]
        if not wanting:
            continue
        src = max(LIVE_ISLANDS, key=lambda i: stocks[i].get(ware, 0))
        spare = stocks[src].get(ware, 0) - (keep if (ware == "cannons" or src in castles) else 0)
        dst = min((i for i in wanting if i != src), key=lambda i: stocks[i].get(ware, 0), default=None)
        if dst is None or spare < 2:
            continue
        tons = int(min(spare, keep - stocks[dst].get(ware, 0)))
        if tons >= 1:
            return supply_run(src, dst, [(ware, tons)])
    return None


def colony_needs(colony: int, home: int, buildings: dict) -> list[tuple[str, int]]:
    """What a colony needs from home: bricks for the piers its cut-off buildings wait for, wood and
    tools when it has almost none and home has plenty."""
    grid = island_map(colony)
    allowed = PIER_BRICKS.get("ok", False)
    PIER_BRICKS["ok"] = True  # how many piers would the roads need?
    piers = 0
    try:
        for name, x, y, w, h in isolated(colony, grid, buildings):
            sides = [(x + i, y - 1) for i in range(w)] + [(x + i, y + h) for i in range(w)] + \
                    [(x - 1, y + j) for j in range(h)] + [(x + w, y + j) for j in range(h)]
            path = road_path(grid, sides, network(grid))
            piers += sum(1 for t in path or [] if grid.get(t) == "b")
    finally:
        PIER_BRICKS["ok"] = allowed
    there, here = read_state(colony)["stock"], read_state(home)["stock"]
    loads = []
    bricks = 2 * piers + 2
    if piers and there.get("bricks", 0) < bricks and here.get("bricks", 0) >= bricks + 10:
        loads.append(("bricks", bricks))
    if colony in GROW:
        # A second main town builds a whole city: full loads (Essix sat at 8 t of wood and 0 houses
        # while home had 100+ t of bricks and plenty of tools).
        for ware, low, load, spare in (("wood", 40, 40, 30), ("tools", 15, 20, 20), ("bricks", 20, 30, 40)):
            if there.get(ware, 0) < low and here.get(ware, 0) >= load + spare:
                loads.append((ware, load))
        return loads
    if there.get("wood", 0) < 8 and here.get("wood", 0) >= 30:
        loads.append(("wood", 15))
    if there.get("tools", 0) < 5 and here.get("tools", 0) >= 15:
        loads.append(("tools", 8))
    return loads


KEY_BUILDINGS = ("marketplace", "chapel", "fire_station", "doctor", "tavern", "school", "church")
KNOWN_KEY: dict = {}   # island -> {(name, x, y, rotation)} seen standing
DEMOLISHED: set = set()  # (island, x, y) the driver pulled down itself


def rebuild_burnt(island: int) -> list[str]:
    """A marketplace, chapel, fire station ... that vanished without the driver pulling it down
    burnt: rebuild it on the spot at once (user: a burnt marketplace must be rebuilt quickly, else
    the whole area is lost)."""
    now = {(n_, x, y) for n_, x, y, _ in production(island) if n_ in KEY_BUILDINGS}
    known = KNOWN_KEY.setdefault(island, set())
    done = []
    grid = island_map(island) if known - now else {}
    for (n_, x, y) in sorted(known - now):
        # Only a fire leaves a ruin ('x'); a building pulled down by hand (or by another tool than
        # this driver) leaves bare ground - that one stays gone (review: four schools/taverns I
        # demolished on Essix were "rebuilt" at once, as the chapel at 17:53,23 before).
        if (island, x, y) in DEMOLISHED or grid.get((x, y)) != "x":
            known.discard((n_, x, y))
            continue
        code, out = ctl("build", n_, island, x, y, 0)
        if code == 0:
            done.append(f"{n_} at {x},{y} burnt down: rebuilt")
            known.discard((n_, x, y))
        else:
            done.append(f"{n_} at {x},{y} burnt down, rebuild refused: {out.strip()[-60:]}")
    known |= now
    try:  # kept across driver restarts, so a fire while the driver was down is seen too
        KEY_FILE.write_text(json.dumps({str(i): sorted(v) for i, v in KNOWN_KEY.items()}), encoding="utf-8")
    except OSError:
        pass
    return done


KEY_FILE = Path(__file__).with_name("key_buildings.json")
try:
    KNOWN_KEY.update({int(i): {tuple(e) for e in v} for i, v in json.loads(KEY_FILE.read_text(encoding="utf-8")).items()})
except (OSError, ValueError):
    pass


def upgrade_kontor(island: int, buildings: dict) -> str | None:
    """The next Kontor level over the old one (user: more trade slots, more room, and selling
    brings the gold that is short): warehouse_1 -> 2 -> 3 -> 4 when unlocked and affordable with
    300 gold to spare."""
    k = kontor_pos(island)
    if not k:
        return None
    level = next((int(n_[-1]) for n_, x, y, _ in production(island)
                  if n_.startswith("warehouse_") and (x, y) == k), None)
    if level is None or level >= 4:
        return None
    nxt = f"warehouse_{level + 1}"
    cost = buildings.get(nxt)
    st = read_state(island)
    if not cost or not affordable(cost, st) or st.get("money", 0) < cost["gold"] + 300:
        return None
    code, out = ctl("build", nxt, island, k[0], k[1], 0)
    return f"Kontor on island {island} upgraded to {nxt}" if code == 0 else None


SHIP_ORDER_AT = {"t": 0.0}


def shipyard_pos(island: int) -> tuple[int, int] | None:
    """The top-left tile of the own shipyard ('S' on the map; 'production' does not list it, so
    neither trade ships nor warships were ever ordered by the driver)."""
    g = island_map(island)
    tiles = [p for p, v in g.items() if v == "S"]
    return min(tiles, key=lambda p: (p[1], p[0])) if tiles else None


def order_ships(home: int, money: int) -> str | None:
    """More ships (user: get more ships): one trade ship per own island; the shipyard at home
    builds the next when there are fewer, with 2000 gold, at most every 5 minutes."""
    if money < 2000 or time.time() - SHIP_ORDER_AT["t"] < 300:
        return None
    yard = shipyard_pos(home)
    _, out = ctl("ships")
    own = len(re.findall(r"^ship \d+ ", out, re.M))
    if not yard or own >= len(LIVE_ISLANDS):
        return None
    SHIP_ORDER_AT["t"] = time.time()
    ctl("shipyard", home, yard[0], yard[1], "build", "trade1")
    return f"trade ship ordered at the shipyard {yard[0]},{yard[1]} ({own} ships, {len(LIVE_ISLANDS)} islands)"


DEFEND_AT = {"t": 0.0}
CASTLE_FILE = HERE / "castle.json"  # where the home castle stands (the map shows it only as B)


WAR = {"on": False, "since": 0.0}


def war_response() -> list[str]:
    """Fixed, fast answers to an attack (no model in the loop): castles send their units out, the
    units on that island march at the nearest intruder, a watchtower goes up beside it where
    cannons lie, armed ships of ours (without troops aboard) go for armed foreign ships."""
    _, out = ctl("threats")
    # Never a first shot (an attack on a ship of somebody at peace with us declares war: the first
    # version of this rule attacked the computers' trade ships, one cannon each, and started wars
    # with Blue and Yellow). Only warships (4+ cannons) of players already at war with us.
    _, dip = ctl("diplomacy")
    at_war = {int(m[1]) for m in re.finditer(r"^\s+(\d+): [^,]+, \w+, peace none,", dip, re.M)}
    # Soldiers count only for players at war with us (review: on the shared islands 0, 3 and 14 the
    # natives' guards and Yellow's garrison were taken for invaders - speed x2, units marched at them).
    soldiers = [(int(m[1]), int(m[3]), int(m[4]), int(m[5])) for m in
                re.finditer(r"soldier (\d+) of player (\d+) figure \d+ on island (\d+) at (-?\d+),(-?\d+)", out)
                if int(m[2]) in at_war]
    ships = [(int(m[1]), int(m[2])) for m in re.finditer(r"ship (\d+) of player (\d+) cannons (\d+)", out)
             if int(m[2]) in at_war and int(m[3]) >= 4]
    if not soldiers and not ships:
        if WAR["on"]:
            WAR["on"] = False
            return ["no threat any more - back to normal speed"]
        return []
    done = []
    # Only an invasion slows the game (pirate ships roam near our islands all the time).
    if soldiers and not WAR["on"]:
        WAR.update(on=True, since=time.time())
        ctl("speed", 2)
        done.append(f"{len(soldiers)} soldiers on our islands - speed x2")
    elif not soldiers and WAR["on"]:
        WAR["on"] = False
        done.append("no intruders any more - back to normal speed")
    try:
        castles = json.loads(CASTLE_FILE.read_text())
    except (OSError, ValueError):
        castles = {}
    _, u_out = ctl("units")
    mine = [(int(m[1]), int(m[2]), int(m[3]), int(m[4]), bool(m[5])) for m in re.finditer(
        r"unit (\d+) figure \d+ island (-?\d+) at (-?\d+),(-?\d+) health \d+( \(on the move\))?", u_out)]
    for isl in sorted({i for _, i, _, _ in soldiers}):
        if str(isl) in castles:
            ctl("release", isl, *castles[str(isl)])
        foes = [(x, y) for _, i, x, y in soldiers if i == isl]
        idle = [u for u, i, x, y, moving in mine if i == isl and not moving]
        if idle:
            fx, fy = foes[0]
            ctl("units-go", isl, fx, fy, *idle)
            done.append(f"island {isl}: {len(idle)} units against the intruders at {fx},{fy}")
        st = read_state(isl)["stock"]
        if st.get("cannons", 0) >= 2 and st.get("bricks", 0) >= 6:
            fx, fy = foes[0]
            _, fs = ctl("find-site", "watchtower", isl, fx, fy, 5)
            row = next((ln.split() for ln in fs.splitlines()[1:] if len(ln.split()) >= 3), None)
            if row:
                _, b = ctl("build", "watchtower", isl, row[0], row[1])
                done.append(f"island {isl}: watchtower at {row[0]},{row[1]}: {b.strip()[:40]}")
    if ships:
        _, s_out = ctl("ships")
        for m in re.finditer(r"^ship (\d+) \"[^\"]*\" figure \d+ at world \d+,\d+ (\w+), health \d+, cannons (\d+)\n"
                             r"(?:  lies[^\n]*\n)?  cargo:([^\n]*)", s_out, re.M):
            sid, cannons, cargo = int(m[1]), int(m[3]), m[4]
            # Ships with a trade route never join a fight (review: once every ship carried cannons,
            # this rule sent all 13 traders after one enemy ship and the main towns starved).
            if "stop 0:" in ctl("route", sid, "show")[1]:
                continue
            if cannons >= 4 and not re.search(r"\b2[4-9] \d", cargo):  # no troops aboard (unit wares 24+)
                ctl("attack", sid, "ship", ships[0][0])
                done.append(f"ship {sid} attacks ship {ships[0][0]}")
    return done


def defend(home: int, money: int) -> list[str]:
    """Defence (user: "you still have no warships at all", "or cannons", "a castle, swords and
    soldiers would be good", "make sure you can defend yourself when attacked" - the computer players
    have weapon production, walls and warships). With a full treasury, every 5 minutes, one step at
    a time: the Kontor buys swords and cannons; a castle at home (houses make way); swordsmen trained
    in it; warships from the shipyard (one per two trade ships); cannons mounted on ships at home."""
    if money < RICH:
        # Weapons are dear (12 t of cannons = 1800 gold): the orders wait while the treasury is low.
        if DEFEND_AT.get("buying"):
            for ware in ("swords", "cannons"):
                ctl("trade", home, 0, ware, "none")
            DEFEND_AT["buying"] = False
            return ["weapon orders paused (treasury below the growth line)"]
        return []
    if time.time() - DEFEND_AT["t"] < 300:
        return []
    DEFEND_AT["buying"] = True
    DEFEND_AT["t"] = time.time()
    done = []
    st = read_state(home)
    stock, buying = st["stock"], st.get("buying", ())
    # Only while all islands together hold too little (review: the orders cost ~1000 gold a minute
    # while the own foundry already delivered and the treasury fell).
    total = {w: sum(read_state(i)["stock"].get(w, 0) for i in LIVE_ISLANDS or [home]) for w in ("swords", "cannons")}
    for ware, tons, price in (("swords", 10, 90), ("cannons", 12, 150)):
        if True or total[ware] >= tons:  # user: produce, do not buy
            ctl("trade", home, 0, ware, "none")
            continue
        if stock.get(ware, 0) < tons and ware not in buying:
            ctl("trade", home, 0, ware, "buy", tons, price)
            done.append(f"the Kontor buys {ware} (up to {tons} t at {price})")
    castle = tuple(CASTLE_FILE.exists() and json.loads(CASTLE_FILE.read_text()).get(str(home), ()) or ()) or None
    if castle is None:
        bl = read_buildings()
        if "castle" in bl and affordable(bl["castle"], st):
            site = best_site("castle", home, *(kontor_pos(home) or (0, 0)), 14)
            if site:
                code, out = ctl("build", "castle", home, *site)
                done.append(f"castle at {site[0]},{site[1]}: {out.strip().splitlines()[-1] if out.strip() else code}")
                if code == 0:
                    CASTLE_FILE.write_text(json.dumps({str(home): [site[0], site[1]]}))
            else:
                msg = make_room(home, "castle", bl)
                done.append(msg)
                m_c = re.search(r"at (\d+),(\d+) for the castle: castle: built 1", msg)
                if m_c:
                    CASTLE_FILE.write_text(json.dumps({str(home): [int(m_c[1]), int(m_c[2])]}))
    # Every castle: trained units out (a castle holds 3; full, it trains nothing more), then train
    # again where swords lie (user: swords to the islands with castles).
    try:
        all_castles = json.loads(CASTLE_FILE.read_text())
    except (OSError, ValueError):
        all_castles = {}
    for isl_c, (cx_c, cy_c) in all_castles.items():
        ctl("release", isl_c, cx_c, cy_c)
        if read_state(int(isl_c))["stock"].get("swords", 0) >= 2:
            _, out = ctl("recruit", isl_c, cx_c, cy_c, "swordsman", 3)
            done.append(f"island {isl_c}: {out.strip()[:60]}")
    _, ships = ctl("ships")
    figures = re.findall(r"^ship (\d+) \"[^\"]*\" figure (\d+) .*cannons (\d+)", ships, re.M)
    war = sum(1 for _, f, _ in figures if f in ("25", "27"))
    trade = len(figures) - war
    # War economy (user: count on losing many ships): every own shipyard keeps a warship on the
    # stocks while the money lasts; the order is refused while one is still being built.
    # A warship without cannons is none (user: "they are all empty"): order one only while no
    # unarmed warship waits and 8 t of cannons lie ready to arm it.
    _, s_all = ctl("ships")
    unarmed = len(re.findall(r'^ship \d+ "[^"]*" figure 25 [^\n]*cannons 0\n', s_all, re.M))
    cannons_ready = sum(read_state(i)["stock"].get("cannons", 0) for i in LIVE_ISLANDS or [home])
    if money >= RICH and unarmed == 0 and cannons_ready >= 8:
        for isl_y in LIVE_ISLANDS or [home]:
            yard = shipyard_pos(isl_y)
            if yard:
                _, out = ctl("shipyard", isl_y, yard[0], yard[1], "build", "war1")
                if "order given" in out:
                    done.append(f"warship ordered at island {isl_y} shipyard {yard[0]},{yard[1]}")
    if stock.get("cannons", 0) >= 2:
        for sid, f, c in figures:
            block = ships.split(f"ship {sid} ")[1].split("\nship ")[0]
            if f"Kontor of island {home}" in block:
                ctl("load", sid, "cannons", min(4, int(stock.get("cannons", 0))))
                _, out = ctl("arm", sid)
                done.append(f"ship {sid}: {out.strip()}")
    return done


def colony_established(island: int) -> bool:
    """A colony that stands on its own. Supply islands keep no houses any more (user: raw
    materials only), so a producing colony counts: a Kontor and some production."""
    st = read_state(island)
    if island not in MAIN_TOWNS:
        return bool(production(island))
    return sum(st.get("houses", [0])) >= 8 and st.get("houses_without_market", 0) == 0


def colonize(target: int, home: int) -> str:
    """Loads wood and tools at home, sails to the target island, founds a Kontor and unloads."""
    ship = my_ship()
    if ship is None:
        return "no ship"
    ctl("route", ship["id"], "stop")
    ctl("load", ship["id"], "wood", 20)
    ctl("load", ship["id"], "tools", 15)
    ctl("load", ship["id"], "food", 10)
    isl = next((i for i in free_islands() if i["island"] == target), None)
    if isl is None:
        return f"island {target} is no longer free"
    _, sites = ctl("kontor-sites", ship["id"], target)
    m = re.search(r"\(world (\d+),(\d+)\)", sites)
    if not m:
        return f"no Kontor site on island {target}"
    if not sail_to(ship["id"], int(m[1]), int(m[2])):
        return f"the ship did not reach island {target}"
    _, sites = ctl("kontor-sites", ship["id"], target)
    ok = re.search(r"\n\s+(\d+) (\d+): ok \(world (\d+),(\d+)\)", sites)
    if not ok:
        return f"no Kontor site within reach on island {target}"
    code, out = ctl("found", ship["id"], target, ok[1], ok[2])
    if code != 0:
        return f"founding refused: {out.strip()}"
    sail_to(ship["id"], int(ok[3]), int(ok[4]), timeout=60)
    for w, t in (("wood", 20), ("tools", 15), ("food", 10)):
        ctl("unload", ship["id"], w, t)
    LIVE_ISLANDS.append(target)
    ctl("say", f"Neue Kolonie auf Insel {target} gegruendet!")
    return f"founded a colony on island {target} (Kontor at {ok[1]},{ok[2]})"


# Option key -> the buildings it puts up (to match the plan's gaps).
OPT_OF = {
    "forester": ["forester"], "food": ["fishers_hut", "hunters_hut"], "sheep": ["sheep_farm"],
    "weaving": ["weaving_hut"], "sugar": ["sugarcane_plantation"], "rum": ["rum_distillery"],
    "chapel": ["chapel"], "tavern": ["tavern"], "school": ["school"], "market": ["marketplace"],
    "bricks": ["quarry", "stonemason"], "quarry": ["quarry"], "stonemason": ["stonemason"],
}
PLAN_DATA = strategy._DATA


PUBLIC = {"chapel", "church", "tavern", "school", "college", "bathhouse", "theatre", "doctor", "fire_station",
          "marketplace"}


def outskirts_site(name: str, island: int) -> tuple[int, int, int] | None:
    """A place for industry or a farm at the edge of town: at least 8 tiles from the middle of the
    houses, in a market's reach (the game's 'sites' ranks by distance to a market), linked by road.
    The town centre stays for houses and public buildings."""
    grid = island_map(island)
    hs = house_origins(grid)
    hx = sum(x for x, _ in hs) / len(hs) if hs else 0
    hy = sum(y for _, y in hs) / len(hs) if hs else 0
    _, out = ctl("sites", name, island, 40)
    for line in out.splitlines()[1:]:
        p = line.split()
        if len(p) < 5 or not p[0].isdigit():
            continue
        x, y, rot = int(p[0]), int(p[1]), int(p[2])
        if hs and abs(x - hx) + abs(y - hy) < 8:
            continue
        if any(abs(x - a) < 3 and abs(y - b) < 3 for a, b in hs):
            continue  # not wedged between houses either
        if not near_market(grid, x, y, 12):
            continue  # the workshop fetches its raw goods from a market: close to one
        if p[3] == "road" or reachable(grid, x, y, 2, 2):
            return x, y, rot
    return None


STOCK_HIST: dict = {}  # island -> [(time, stock dict)] of the last minutes


def runout_warnings(island: int, s: dict) -> list[str]:
    """Goods about to run out (user: "do you see when goods run out, food above all?"): the stock
    of the last minute gives the trend; under 5 minutes left is a warning. Food also gets an
    emergency buy order at the Kontor."""
    now = time.time()
    hist = STOCK_HIST.setdefault(island, [])
    hist.append((now, dict(s.get("stock", {}))))
    del hist[:-40]
    old = next(((t, st) for t, st in hist if now - t >= 45), None)
    if old is None:
        return []
    t0, st0 = old
    minutes = (now - t0) / 60
    out = []
    for ware in ("food", "cloth", "alcohol", "tools", "wood", "tobacco_goods", "spices"):
        then, cur = st0.get(ware, 0.0), s.get("stock", {}).get(ware, 0.0)
        rate = (cur - then) / minutes if minutes > 0 else 0
        if rate < -0.05 and cur / -rate < 5:
            out.append(f"[RUNOUT] {ware}: {cur:.1f} t left, falling {-rate:.1f} t/min, empty in {cur / -rate:.1f} min")
    # Never sell what runs out (critic: alcohol was sold above 15 t while it would be empty in 2 min).
    for w in out:
        ware = w.split()[1].rstrip(":")
        if ware in s.get("selling", ()):
            ctl("trade", island, 0, ware, "none")
    # The emergency food order ends once the store has recovered (review: a colony still bought food
    # at 20 while the trade route carried its food home).
    if not any(w.startswith("[RUNOUT] food") for w in out) and "food" in s.get("buying", ()) \
            and s.get("stock", {}).get("food", 0) > 40:
        ctl("trade", island, 0, "food", "none")
    if any(w.startswith("[RUNOUT] food") for w in out) and s.get("money", 0) > 200 \
            and "food" not in s.get("buying", ()):
        ctl("trade", island, 0, "food", "buy", 20, 20)
        out.append("[RUNOUT] food: emergency buy order at the Kontor (20 t at 20)")
    return out


TAX_AT: dict = {}  # (island, class) -> when its tax last went up
TAX_DOWN: dict = {}  # (island, class) -> when its tax last went down
TAX_OK: dict = {}  # (island, class) -> fully content readings in a row
CLASSES = ["pioneers", "settlers", "citizens", "merchants", "aristocrats"]


def tune_taxes(island: int, s: dict) -> str | None:
    """Every class at the edge (user, high priority: taxes always where the people are still
    content but squeezed as hard as possible). The game's satisfaction is the goods supplied
    against what the tax asks (consumption.cpp), capped at 128: a class at 128 has headroom.
    So: +16 after two fully content readings in a row (30 s apart at least), up to 192; -16 at
    once on any dip below 128 (pioneers: 120), down to 80; after a step down the class must be
    content twice again before the next step up - it settles at the highest tax it bears.
    A house rises into a class only while that class is fully content, so the edge also keeps
    growth going."""
    done = []
    for name, c in s.get("classes", {}).items():
        if not c["people"] or name not in CLASSES:
            continue
        idx = CLASSES.index(name)
        content = 120 if name == "pioneers" else 128
        key = (island, name)
        TAX_OK[key] = TAX_OK.get(key, 0) + 1 if c["satisfaction"] >= content else 0
        new = None
        # A short dip is no reason (review: every dip cut 16, raises came slowly, the citizens fell
        # to 80 while fully content): down only below content - 8, at most once a minute, not
        # below 96.
        if c["satisfaction"] < content - 8 and c["tax"] > 64 and time.time() - TAX_DOWN.get(key, 0) >= 20:
            new = max(64, c["tax"] - 16)
            TAX_DOWN[key] = time.time()
        elif TAX_OK[key] >= 2 and c["tax"] < 192 and time.time() - TAX_AT.get(key, 0) >= 30:
            new = min(192, c["tax"] + 16)
            TAX_AT[key] = time.time()
            TAX_OK[key] = 0
        if new is not None:
            ctl("tax", island, 0, idx, new)
            done.append(f"{name} {c['tax']}->{new} (satisfaction {c['satisfaction']})")
    return f"island {island}: " + ", ".join(done) if done else None


def field_of(name: str, buildings: dict) -> str | None:
    """The field a plantation, winery or farm plants ('vines' for the winery), from the game data:
    a dict with 'field_building' (user: "your winery has not a single vineyard" - the lookup read
    it as a list and never found the field)."""
    f = PLAN_DATA["buildings"].get(name, {}).get("fields")
    field = f.get("field_building") if isinstance(f, dict) else None
    return field if field in buildings else None


EFF_DONE: dict = {}  # field and forest top-ups lately (once per 5 minutes per building)


def chain_shortfalls(island: int) -> list[tuple[str, int, str, int]]:
    """Processors whose raw producers cannot feed them at full speed (user: industries and farms
    must run at 100%, with the supply chain they need). From the game data: a weaving hut eats
    4 t of wool a minute, a sheep farm makes 2, at a real 85% that is 3 farms per weaving hut.
    Returns (raw producer, how many are missing, processor, how many processors)."""
    have: dict[str, int] = {}
    for name, *_ in production(island):
        have[name] = have.get(name, 0) + 1
    data = strategy._DATA["buildings"]
    out = []
    for proc, n in have.items():
        up = strategy.upstream(proc)
        if not up or up not in data:
            continue
        raw = data[proc]["production"].get("raw") or []
        rate_up = data[up]["production"].get("t_per_min_at_full_speed") or 0
        if not raw or not rate_up:
            continue
        need = n * raw[0]["t_per_min_at_full_speed"]
        required = -(-need // (rate_up * 0.85))
        if have.get(up, 0) < required:
            out.append((up, int(required) - have.get(up, 0), proc, n))
    return out


def efficiency_report(island: int) -> list[str]:
    """Industries and farms below 80% and why, for the plan over the map and the model."""
    lines = []
    short = {up: (miss, proc) for up, miss, proc, _ in chain_shortfalls(island)}
    for name, x, y, util in production(island):
        if name in ("warehouse_1", "warehouse_2", "warehouse_3", "warehouse_4", "marketplace") or name in PUBLIC:
            continue
        if util < 80:
            up = strategy.upstream(name)
            why = f", {short[up][0]} {up} missing" if up in short else ""
            lines.append(f"{name} {x},{y} {util}%{why}")
    return lines[:8]


def efficiency_fixes(island: int, buildings: dict) -> list[str]:
    """Fills the catchment of a plantation, winery or farm below 80% with its fields and plants
    forest around a forester below 50% (5 gold a field or tree), each at most every 5 minutes."""
    done = []
    money = read_state(island).get("money", 0)
    for name, x, y, util in production(island):
        key = (island, name, x, y)
        if time.time() - EFF_DONE.get(key, 0) < 300:
            continue
        field = field_of(name, buildings)
        r = int(strategy._DATA["buildings"].get(name, {}).get("radius_tiles", 2) or 2)
        if name == "forester" and util < 50 and money >= 200:
            EFF_DONE[key] = time.time()
            _, out = ctl("build-many", "forest", island, x - 3, y - 3, x + 4, y + 4)
            done.append(f"forester {x},{y} at {util}%: forest planted ({out.strip().splitlines()[-1][:50]})")
        elif field and field != "forest" and util < 80 and money >= 100:
            EFF_DONE[key] = time.time()
            _, out = ctl("build-many", field, island, x - r, y - r, x + 1 + r, y + 1 + r)
            done.append(f"{name} {x},{y} at {util}%: {field} planted ({out.strip().splitlines()[-1][:50]})")
    return done


def chain_options(island: int, buildings: dict, s: dict, grid: dict) -> dict[str, dict]:
    """An option for each missing raw producer, at its best place (meadow for sheep, free land for
    a plantation's fields), so a processor gets what it needs to run at full speed."""
    o = {}
    util: dict[str, list[int]] = {}
    for line in ctl("production")[1].splitlines():
        m = re.match(rf"(\w+) at \d+,\d+ \({island}\): \w+, (\d+)%", line)
        if m:
            util.setdefault(m[1], []).append(int(m[2]))
    for up, missing, proc, n in chain_shortfalls(island):
        if up not in buildings or not affordable(buildings[up], s):
            continue
        # The ones standing starve themselves (user: three half-busy mills on Essix, one would do;
        # more grain fields are needed): no more of them until they run above 70%.
        have = util.get(up, [])
        if have and sum(have) / len(have) < 70:
            continue
        field = field_of(up, buildings)
        if up in ("sheep_farm", "cattle_farm"):
            found = pasture_site(island, grid)
            if not found:
                continue
            (px, py, pr), score = found
            cmd = [["build", up, island, px, py, pr], ["connect-last", up, px, py]]
        elif field:
            found = field_site(island, grid, up)
            if not found:
                continue
            (px, py, pr), score = found
            cmd = [["build", up, island, px, py, pr], ["build-many", field, island, px - 2, py - 2, px + 3, py + 3],
                   ["connect-last", up, px, py]]
        else:
            site = outskirts_site(up, island)
            if not site:
                continue
            px, py, pr = site
            cmd = [["build", up, island, px, py, pr], ["connect-last", up, px, py]]
        o[f"chain_{up}"] = {"desc": f"Build a {up.replace('_', ' ')} at {px},{py}: the {n} {proc.replace('_', ' ')} "
                                    f"need {missing} more to run at full speed",
                            "cmd": cmd}
    return o


SERVICE_RADIUS = {"fire_station": 15, "doctor": 16}


def road_component(grid: dict, starts: list[tuple[int, int]]) -> set[tuple[int, int]]:
    """All road tiles (roads, bridges, squares, piers) connected to the given tiles."""
    seen = {p for p in starts if grid.get(p) in ROAD}
    todo = list(seen)
    while todo:
        x, y = todo.pop()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (x + dx, y + dy)
            if n not in seen and grid.get(n) in ROAD:
                seen.add(n)
                todo.append(n)
    return seen


def beside(x: int, y: int, w: int, h: int) -> list[tuple[int, int]]:
    return [(x + i, y - 1) for i in range(w)] + [(x + i, y + h) for i in range(w)] + \
           [(x - 1, y + j) for j in range(h)] + [(x + w, y + j) for j in range(h)]


def service_gaps(island: int, service: str) -> tuple[list, list] | None:
    """Houses a fire station (or doctor) cannot reach: its people walk on roads only (user: "the
    fire brigade must reach the houses over the road network, else it is useless"; "the same for
    the doctor"). Returns (houses on a road piece not linked to any station, houses on a linked
    piece but beyond every station's radius), or None when there is no such station."""
    grid = island_map(island)
    stations = [(x, y) for n_, x, y, _ in production(island) if n_ == service]
    if not stations:
        return None
    reach = set()
    for sx, sy in stations:
        reach |= road_component(grid, beside(sx, sy, 2, 2))
    r = SERVICE_RADIUS.get(service, 15)
    cut, far = [], []
    for hx, hy in house_origins(grid):
        if not any(t in reach for t in beside(hx, hy, 2, 2)):
            cut.append((hx, hy))
        elif not any(abs(hx - sx) <= r and abs(hy - sy) <= r for sx, sy in stations):
            far.append((hx, hy))
    return cut, far


def fix_service_gaps(island: int, service: str, buildings: dict) -> list[str]:
    """Links road pieces with unreached houses to a station's road piece (road, bridge or pier),
    and builds another station among houses beyond every station's radius when gold allows."""
    gaps = service_gaps(island, service)
    if not gaps:
        return []
    cut, far = gaps
    done = []
    if cut:
        grid = island_map(island)
        stations = [(x, y) for n_, x, y, _ in production(island) if n_ == service]
        reach = set()
        for sx, sy in stations:
            reach |= road_component(grid, beside(sx, sy, 2, 2))
        piece = road_component(grid, [t for t in beside(cut[0][0], cut[0][1], 2, 2)])
        if piece:
            path = (road_path(grid, sorted(piece), reach, hub_goal=False)
                    or road_path(grid, sorted(piece), reach, through_houses=True, hub_goal=False))
            if path:
                done.append(f"{service}: road piece with {len(cut)} unreached houses linked: " + lay_path(island, grid, path))
    if far and len(far) >= 6 and service in buildings and affordable(buildings[service], read_state(island)):
        fx = sum(x for x, _ in far) // len(far)
        fy = sum(y for _, y in far) // len(far)
        _, out = ctl("find-site", service, island, fx, fy, 8)
        site = next((ln.split() for ln in out.splitlines()[1:] if len(ln.split()) >= 4 and ln.split()[3] == "road"), None)
        if site:
            code, o2 = ctl("build", service, island, site[0], site[1], site[2])
            if code == 0:
                done.append(f"{service}: second one at {site[0]},{site[1]} for {len(far)} houses beyond reach")
    return done


def clear_ruins(island: int) -> str | None:
    """Ruins of burnt or abandoned houses ('x') are cleared so houses can stand there again
    (critic: 13 ruined plots stood in town while the driver searched the outskirts)."""
    grid = island_map(island)
    ruins = [p for p, v in grid.items() if v == "x"]
    for (x, y) in ruins:
        ctl("demolish", island, x, y)
    return f"{len(ruins)} ruin tiles cleared" if ruins else None


ROUTE_AT = {"t": 0.0}


def update_route(home: int, colonies: list[int]) -> str | None:
    """The trade route carries what a colony has to spare and home lacks, for every good, not
    only wood (critic: the route loaded wood the colony did not have while 49 t of food, 40 t of
    wool and 19 t of tools lay there, and home ran out of food). Every 3 minutes."""
    if not colonies or time.time() - ROUTE_AT["t"] < 180:
        return None
    ROUTE_AT["t"] = time.time()
    ship = my_ship()
    if ship is None or SHIP_BUSY["on"]:
        return None
    # The colony with the most of what home lacks, food weighing most (review: the route took wood
    # from island 2, the first colony, while home starved at 65% food and Durtmond held 94 t).
    here = read_state(home)["stock"]
    order = ("food", "cloth", "alcohol", "tobacco_goods", "wool", "tools", "wood", "bricks", "tobacco", "sugar")
    weight = {"food": 4, "cloth": 2, "alcohol": 2, "tobacco_goods": 2}
    best = None
    for c in colonies:
        if c in GROW:
            continue  # a second main town keeps what it has (the route emptied Essix towards home)
        there = read_state(c)["stock"]
        # Food only from a colony with plenty (Durtmond lost a quarter of its pioneers when the route
        # took its last food).
        goods = [w for w in order if there.get(w, 0) >= (40 if w == "food" else 15) and here.get(w, 0) < 60]
        score = sum(weight.get(w, 1) * min(there.get(w, 0), 40) for w in goods[:4])
        if goods and (best is None or score > best[0]):
            best = (score, c, goods)
    if best is None:
        return None
    _, col, goods = best
    load, unload = [], []
    for w in goods[:4]:
        load += ["load", w, 40]
        unload += ["unload", w, 40]
        ctl("trade", col, 0, w, "none")  # the colony keeps it for home instead of selling it
    ctl("route", ship["id"], "stop", 0, col, 0, *load)
    ctl("route", ship["id"], "stop", 1, home, 0, *unload)
    ctl("route", ship["id"], "start")
    ROUTE["on"] = True
    return f"trade route island {col} -> {home}: {', '.join(goods[:4])}"


def best_service_center(missing: list[tuple[int, int]], reach: int = 10) -> tuple[int, int] | None:
    """The house that has the most houses lacking the building within `reach` tiles: build there
    (critic: the centre of all such houses lay between two groups, over the bay)."""
    if not missing:
        return None
    return max(missing, key=lambda c: sum(1 for m in missing if abs(m[0] - c[0]) <= reach and abs(m[1] - c[1]) <= reach))


def options(s: dict, buildings: dict, args) -> dict[str, dict]:
    """Legal actions: key -> {desc, cmd}; cmd is one command or a list of them. Every option is
    something the game will accept. Coach's rules (from the strategy skill and the first log):
    - the small model picks "wait" whenever it is offered, so it is offered only when nothing
      else is possible;
    - batches (5 houses) make each decision count;
    - the opening build order is offered until it stands."""
    o: dict[str, dict] = {}
    isl, cx, cy, r = args.island, args.cx, args.cy, args.radius
    st = s["stock"]
    have = counts(isl)
    people = sum(c["people"] for c in s["classes"].values())
    # Expansion from the home island: a new colony on the nearest free island.
    # Only once the home town stands (coach: a colony founded before the first house took the
    # wood the houses needed). One colony per 20 houses at home.
    # And only when every colony stands on its own feet and home has 3000 gold (review: islands 12
    # and 2 founded within minutes, both with no wood, no tools, no market; money 1544 -> 900).
    if isl == LIVE_ISLANDS[0] and s.get("money", 0) >= 3000 and st.get("wood", 0) >= 12 and st.get("tools", 0) >= 8 \
            and sum(s.get("houses", [0])) >= 20 * len(LIVE_ISLANDS) and all(colony_established(c) for c in LIVE_ISLANDS[1:]):
        ship = my_ship()
        target = colony_target(isl) if ship and ship["idle"] and not SHIP_BUSY["on"] else None
        if target:
            o["colony"] = {"desc": f"Found a colony on island {target['island']} ({target['w']}x{target['h']}, "
                                   f"{target['climate']}, crops {target['crops']}; 100 gold, 6 t wood): more land "
                                   f"for settler houses and new crops",
                           "cmd": [["colonize", target["island"]]]}

    def build(key: str, name: str, why: str):
        cost = buildings.get(name)
        if cost is None or not affordable(cost, s):
            return
        # Public buildings among the houses, industry and farms at the town's edge (user: "better put
        # industry and agriculture at the edge of town or on other islands").
        # Producers with their own resource use their own site search and its minimum (critic: a
        # fisher with 6 fish-ground tiles came through this generic path).
        special = {"fishers_hut": water_site, "forester": forest_site, "sheep_farm": pasture_site}
        if name in special:
            found = special[name](isl, island_map(isl))
            site = found[0] if found else None
        else:
            site = best_site(name, isl, cx, cy, r) if name in PUBLIC else outskirts_site(name, isl)
        if site:
            c = f"{cost['gold']} gold" if cost["gold"] else "no gold"
            o[key] = {"desc": f"Build a {name.replace('_', ' ')} ({c}, {cost['wood']:g} t wood): {why}",
                      "cmd": ["build", name, isl, *site]}

    # Houses in batches: cheap (wood only), every inhabitant pays taxes.
    wood = st.get("wood", 0)
    # Keep 6 t of wood for houses rising and chapels (coach: houses ate the last wood).
    keep = 6 + (10 if s.get("houses_without_market", 0) >= 3 else 0)  # wood for the marketplace first
    n_houses = int(min(10, (wood - keep) // 3))  # pioneer houses pay: as many as the wood allows
    # Resource islands: few houses (user: they eat the food there too). Up to 12 (enough to count
    # as established), and only while food is fully supplied.
    if LIVE_ISLANDS and isl != LIVE_ISLANDS[0] and isl not in GROW:
        n_h_here = sum(s.get("houses", [0]))
        # With the treasury full the colonies grow into towns of their own (user: "so much money,
        # yet you expand very slowly" - 28k gold, home full, colonies held at 12 houses).
        cap = COLONY_HOUSES_RICH if s.get("money", 0) >= RICH else 12
        # Production colonies (--produce) stay small: Kap Crus grew to 30 houses on its sugar fields
        # and its own citizens drank the rum it was founded to send home.
        if isl in PRODUCE:
            cap = 12
        n_houses = min(n_houses, cap - n_h_here) if s.get("food_supply", 100) >= 100 else 0
    if n_houses >= 1 and best_site("house", isl, cx, cy, r):
        o["houses"] = {"desc": f"Build {n_houses} houses at the streets (no gold, {3 * n_houses} t wood): "
                               f"more inhabitants pay more taxes",
                       "cmd": [["build-house-batch", n_houses]]}
    elif n_houses >= 2 and s.get("money", 0) > 200:
        # No place at a street, but wood for houses: a new street first (coach: never houses
        # without a road; and no street while there is no wood for the houses along it).
        street = plan_street(isl, island_map(isl))
        if street and street[1] >= 2:
            o["street"] = {"desc": f"Lay a new street from the road network (about 40 gold): room for "
                                   f"{street[1]} houses, all reachable by carts and the fire brigade",
                           "cmd": ["road", isl, *street[0]]}
        # A whole planned quarter (user): streets in a grid, houses between, open street ends.
        q = plan_quarter(isl, island_map(isl))
        if q and len(q["plots"]) >= 8 and s.get("money", 0) >= 150:
            x0, y0, w, h = q["area"]
            o["quarter"] = {"desc": f"Plan a new quarter at {x0},{y0} ({w}x{h} tiles): streets in a grid with room "
                                    f"for {len(q['plots'])} houses, street ends left open to grow",
                            "cmd": [["quarter"]]}
        elif "marketplace" in buildings and affordable(buildings["marketplace"], s) and s.get("money", 0) >= 400:
            # No room left inside the city: a marketplace at its edge claims the free land beyond
            # (user, early on: markets make an island usable).
            g = island_map(isl)
            edge = [(x, y) for (x, y), v in g.items() if v in (":", "T") and
                    sum(g.get((x + dx, y + dy)) in (".", "t") for dx in range(-6, 7) for dy in range(-6, 7)) >= 40]
            if edge:
                ex, ey = max(edge, key=lambda p: sum(g.get((p[0] + dx, p[1] + dy)) in (".", "t")
                                                     for dx in range(-6, 7) for dy in range(-6, 7)))
                o["claim_land"] = {"desc": f"Build a marketplace at the city's edge near {ex},{ey} (200 gold): it "
                                           f"claims the free land beyond for new quarters",
                                   "cmd": [["market-near", ex, ey]]}
    # The opening, until it stands (strategy skill: 2-3 foresters, 1-2 fishers, chapel, cloth).
    # Foresters only where the forest is (coach: six of them between the houses cut nothing).
    # Caps by the size of the town (coach, new game: 3 fishers, 3 hunters and 5 foresters before the
    # first house, all wood gone, no inhabitants to pay their running costs).
    n_h = sum(s.get("houses", [0]))
    cap_forester = 2 + n_h // 6
    cap_food = 1 + n_h // 8
    if have.get("forester", 0) < min(cap_forester, 3 if wood >= MIN_STOCK["wood"] else 6) \
            and affordable(buildings.get("forester", {"gold": 1e9}), s):
        grid = island_map(isl)
        found = forest_site(isl, grid)
        if found:
            (fx, fy, fr), trees = found
            cmds = [["build", "forester", isl, fx, fy, fr], ["connect-last", "forester", fx, fy],
                    ["build-many", "forest", isl, fx - 3, fy - 3, fx + 4, fy + 4]]
            o["forester"] = {"desc": f"Build a forester in the forest ({trees} trees in reach, 50 gold): wood for "
                                     f"houses ({have.get('forester', 0)} foresters, {wood:g} t wood)",
                             "cmd": cmds}
    n_food = have.get("fishers_hut", 0) + have.get("hunters_hut", 0)
    if s.get("gaps") is not None:  # the plan knows the food demand of the stage
        cap_food = max(cap_food, n_food + s["gaps"].get("fishers_hut", 0) + s["gaps"].get("hunters_hut", 0))
    if n_food < cap_food and (n_food < 1 or s.get("food_supply", 100) < 100 or st.get("food", 0) < 15) \
            and affordable(buildings.get("fishers_hut", {"gold": 1e9}), s):
        found = water_site(isl, island_map(isl))
        if found:
            (wx, wy, wr), water = found
            o["food"] = {"desc": f"Build a fishers hut at open sea (score {water}, 100 gold): food for the growing "
                                 f"town ({st.get('food', 0):g} t in stock)",
                         "cmd": [["build", "fishers_hut", isl, wx, wy, wr], ["connect-fisher", wx, wy]]}
        else:
            pass  # no hunters any more (user: a hunting lodge without game ran at 0%); fishers only
    # Bricks: pave the main roads (faster carts), sell what the Kontor cannot hold.
    # Keep 20 t for sugarcane plantation (8 t) and rum distillery (5 t) until both stand: settlers want alcohol.
    reserve = 20 if have.get("rum_distillery", 0) < 1 else 0
    # Paving is no option for the model any more (review: picked again and again over the chapel
    # for 41 houses, refused or of little use); a full brick store paves by itself from 800 gold.
    if False and st.get("bricks", 0) >= 25 + reserve and pave(isl, island_map(isl), dry=True):
        o["pave"] = {"desc": f"Pave the main roads at the markets with stone ({st.get('bricks', 0):g} t bricks; "
                             f"carts run faster than on dirt)",
                     "cmd": [["pave"]]}
    # Public buildings of the class the houses rise to, where houses lack them (coach: 14 of 22
    # houses had no chapel in reach and could never become settlers).
    citizens_next = any(n_ == "settlers" and c["people"] >= 30 for n_, c in s["classes"].items())
    services = [("chapel", "settlers need a chapel in reach to rise")]
    if citizens_next:
        services += [("tavern", "citizens need a tavern in reach"), ("school", "citizens need a school in reach")]
    grid_s = island_map(isl)
    for service, why in services:
        if service not in buildings or not affordable(buildings[service], s):
            continue
        # At most one per 9 houses (coach: six chapels for 46 houses cost more than they brought).
        # Tavern and school reach 12 tiles (chapel 8): one per 20 houses is enough.
        per = 9 if service == "chapel" else 20
        if have.get(service, 0) >= max(1, sum(s.get("houses", [0])) // per):
            continue
        missing = houses_without(isl, grid_s, service) if people >= 8 else []
        if len(missing) >= 3 or (service == "chapel" and have.get("chapel", 0) < 1 and people >= 8):
            centre = best_service_center(missing)  # the biggest group, not the mean of all
            mx, my = centre if centre else (cx, cy)
            site = None
            # Radius 10, and a place a road can still reach (review: in a built-up town no place
            # within 6 tiles lay at a road, and 34 houses waited for a chapel).
            _, out = ctl("find-site", service, isl, mx, my, 10)
            rows_s = [ln.split() for ln in out.splitlines()[1:] if len(ln.split()) >= 4]
            pick_s = next((p for p in rows_s if p[3] == "road"), None) or \
                next((p for p in rows_s if reachable(grid_s, int(p[0]), int(p[1]), 2, 1)), None)
            if pick_s:
                site = (int(pick_s[0]), int(pick_s[1]), int(pick_s[2]))
            if site:
                cost = buildings[service]
                o[service] = {"desc": f"Build a {service} among {len(missing)} houses that lack one "
                                      f"({cost['gold']} gold): {why}",
                              "cmd": ["build", service, isl, *site]}
    if have.get("sheep_farm", 0) < 2 and people >= 15 and affordable(buildings.get("sheep_farm", {"gold": 1e9}), s):
        # Sheep only on open meadow (coach: a farm among trees grazes nothing).
        grid = island_map(isl)
        found = pasture_site(isl, grid)
        if found:
            (px, py, pr), meadow = found
            o["sheep"] = {"desc": f"Build a sheep farm on open meadow (score {meadow}, 200 gold): wool for cloth, "
                                  f"settlers need cloth to rise",
                          "cmd": [["build", "sheep_farm", isl, px, py, pr], ["connect-last", "sheep_farm", px, py]]}
    if have.get("sheep_farm", 0) >= 1 and have.get("weaving_hut", 0) < 1:
        build("weaving", "weaving_hut", "turns wool into cloth for the settlers")
    # Settlers: alcohol (sugar plantation with its fields in radius 2, then a rum distillery),
    # bricks (quarry at a mountain + stonemason), the tavern. Each only once unlocked.
    settlers = sum(c["people"] for n_, c in s["classes"].items() if n_ != "pioneers")
    if settlers >= 1 and have.get("sugarcane_plantation", 0) < 2 and "sugarcane_plantation" in buildings \
            and affordable(buildings["sugarcane_plantation"], s):
        found = field_site(isl, island_map(isl), "sugarcane_plantation")
        if found:
            (px, py, pr), room = found
            o["sugar"] = {"desc": f"Build a sugarcane plantation with {room} fields around it (300 gold): sugar for "
                                  f"rum, settlers need alcohol",
                          "cmd": [["build", "sugarcane_plantation", isl, px, py, pr],
                                  ["build-many", "sugarcane_field", isl, px - 2, py - 2, px + 3, py + 3],
                                  ["connect-last", "sugarcane_plantation", px, py]]}
    if have.get("sugarcane_plantation", 0) >= 1 and have.get("rum_distillery", 0) < 1:
        build("rum", "rum_distillery", "turns sugar into alcohol for the settlers")
    # A quarry without a stonemason (coach: the quarry stood, the stonemason found no place): the
    # stonemason next to it, a bit farther out.
    # Quarries are mines ('E' on the map) and not in the production list (coach: four quarries were
    # built, each 6 t of tools, because the first one was never seen). The one at the network first.
    g_q = island_map(isl)
    net_q = network(g_q)
    quarries = [(x, y) for (x, y), v in g_q.items() if v == "E" and g_q.get((x, y - 1)) != "E"
                and g_q.get((x - 1, y)) != "E"]
    quarries.sort(key=lambda p: not touches(net_q, g_q, p[0], p[1], 2, 2))
    if quarries and have.get("stonemason", 0) < 1 and "stonemason" in buildings \
            and affordable(buildings["stonemason"], s):
        qx, qy = quarries[0]
        # A place whose worker walks to the quarry in a few steps over land (coach: across the river
        # it got no stone; two tiles from the quarry it ran at 76%).
        _, out = ctl("find-site", "stonemason", isl, qx, qy, 6)
        site = next((p for p in (ln.split() for ln in out.splitlines()[1:]) if len(p) >= 4
                     and worker_reaches(g_q, int(p[0]), int(p[1]), 2, 2, "E", 4)
                     and (p[3] == "road" or reachable(g_q, int(p[0]), int(p[1]), 2, 2))), None)
        if site:
            sx, sy, sr = int(site[0]), int(site[1]), int(site[2])
            o["bricks"] = {"desc": f"Build the stonemason at {sx},{sy}, a few steps from the quarry at {qx},{qy} "
                                   f"(100 gold): bricks for the winery, the tavern and the citizens' houses",
                           "cmd": [["build", "stonemason", isl, sx, sy, sr], ["connect-last", "stonemason", sx, sy]]}
    elif settlers >= 15 and have.get("stonemason", 0) < 1 and "quarry" in buildings \
            and affordable(buildings["quarry"], s) and affordable(buildings.get("stonemason", {"gold": 1e9}), s):
        grid = island_map(isl)
        rocks = [k for k, v in grid.items() if v in ("/", "^")]
        if rocks:
            # The slope nearest the town (coach: the mean of two mountains lay on flat land between them).
            rocks.sort(key=lambda p: abs(p[0] - cx) + abs(p[1] - cy))
            q, mx, my = None, cx, cy
            for (rx, ry) in rocks[:40:8]:
                q = any_site("quarry", isl, rx, ry, 4)
                if q:
                    mx, my = rx, ry
                    break
            if q:
                o["bricks"] = {"desc": "Build a quarry at the mountain and a stonemason (250 gold): bricks for "
                                       "bigger houses and plantations",
                               "cmd": [["build", "quarry", isl, *q], ["connect-last", "quarry", q[0], q[1]],
                                       ["build-near", "stonemason", q[0], q[1]]]}
    if settlers >= 50 and have.get("tavern", 0) < 1:
        build("tavern", "tavern", "settlers need a tavern to rise to citizens")
    # Producers for what is short.
    shortest: dict[str, int] = {}
    for cls in s["classes"].values():
        for ware, pct in cls["supply"].items():
            shortest[ware] = min(shortest.get(ware, 100), pct)
    shortest["food"] = s.get("food_supply", 100)
    for ware, pct in shortest.items():
        if pct < 90:
            for name in PRODUCERS.get(ware, []):
                # Only a producer whose raw material comes from somewhere (coach: a rum distillery was
                # offered without any sugar plantation; the plan makes alcohol from wine here).
                raw_from = strategy.upstream(name)
                if raw_from and have.get(raw_from, 0) < 1:
                    continue
                # Not another one while those there idle (a second weaving hut was offered while the
                # first ran at 2% for want of wool): first their supply chain, then more of them.
                if any(n_ == name and u < 70 for n_, _, _, u in production(isl)):
                    continue
                build(f"more_{ware}_{name}", name, f"{ware} is supplied only {pct}%")
    # Tools run out with every building: buy them cheaply while gold is plenty (once: the order stays).
    if st.get("tools", 0) < MIN_STOCK["tools"] and s.get("money", 0) > 500 and "tools" not in s.get("buying", ()):
        o["buy_tools"] = {"desc": f"Buy tools from traders at 75 ({st.get('tools', 0):g} t left; every building "
                                  f"needs tools)",
                          "cmd": [["trade", isl, 0, "food", "none"], ["trade", isl, 0, "tools", "buy", 20, 75]]}
    # Trade: sell surpluses (gold now), buy what is short and cannot be made.
    for ware, t in st.items():
        # Building materials are kept for building (coach: it sold the wood the houses needed).
        limit = 80 if ware in ("wood", "tools", "bricks") else SELL_ABOVE_T
        if t > limit and ware not in ("food",) and ware not in s.get("selling", ()):
            o[f"sell_{ware}"] = {"desc": f"Sell {ware} at the Kontor above {KEEP_T} t ({t:g} t in stock): gold now",
                                 "cmd": ["trade", isl, 0, ware, "sell", KEEP_T]}
    for ware, pct in shortest.items():
        # User: produce it yourself; buy only when there is no other way and it really matters -
        # under 25% supplied, a class needing it clearly unhappy, money to spare, 10 t at a time.
        unhappy = any(c["people"] and c["satisfaction"] < 100 and ware in c.get("supply", {})
                      for c in s["classes"].values())
        if pct < 25 and unhappy and ware != "food" and s.get("money", 0) > 50000 \
                and ware not in s.get("buying", ()):
            o[f"buy_{ware}"] = {"desc": f"Emergency: buy 10 t {ware} from traders ({pct}% supplied, people "
                                        f"unhappy): costs gold, own production is better",
                                "cmd": ["trade", isl, 0, ware, "buy", 10]}
    # Taxes: higher only while people are content; lower when they are not.
    for name, cls in s["classes"].items():
        idx = ["pioneers", "settlers", "citizens", "merchants", "aristocrats"].index(name)
        if cls["people"] == 0:
            continue
        # tune_taxes() in the round loop raises the tax of every fully content class and steps it
        # back at the first dip (a fixed rule, no choice); this option is the model's quick way down.
        if name != "pioneers" and cls["satisfaction"] < 128 and cls["tax"] > 128:
            o[f"tax_down_{name}"] = {"desc": f"Lower the tax of the {name} to 128 (satisfaction {cls['satisfaction']})",
                                     "cmd": ["tax", isl, 0, idx, 128]}
    # Producers far from every market (user: the sheep farms' road to the market was long, the
    # weaving hut starved): a marketplace beside them, where their goods land and workshops fetch.
    far = [(n_, x, y) for n_, x, y, _ in production(isl)
           if n_ not in PUBLIC and n_ not in ("warehouse_1", "warehouse_2", "warehouse_3", "warehouse_4")
           and not near_market(grid_s, x, y)]
    if len(far) >= 1 and "marketplace" in buildings and affordable(buildings["marketplace"], s) \
            and "market_link" not in o:
        # The biggest group of far producers (within 10 tiles of each other), not the mean of all.
        group = max(([f for f in far if abs(f[1] - c[1]) + abs(f[2] - c[2]) <= 10] for c in far), key=len)
        fx = sum(x for _, x, _ in group) // len(group)
        fy = sum(y for _, _, y in group) // len(group)
        names = ", ".join(sorted({n_ for n_, _, _ in group}))
        o["market_near"] = {"desc": f"Build a marketplace at {fx},{fy} beside far producers ({names}): their goods "
                                    f"reach a store quickly and the workshops get them",
                            "cmd": [["market-near", fx, fy]]}
    # Buildings no road can link to a market or the Kontor (Kontor in a pocket of beach and mountain,
    # as on island 3): a marketplace beside them. Market and Kontor share one store, so the
    # market need not reach the Kontor; its carts collect from the buildings around it.
    cut_off = [b for b in isolated(isl, grid_s, buildings) if b[0] != "house"
               and connect_check(grid_s, *b[1:])]
    if cut_off and "marketplace" in buildings and affordable(buildings["marketplace"], s):
        mx = sum(b[1] for b in cut_off) // len(cut_off)
        my = sum(b[2] for b in cut_off) // len(cut_off)
        o["market_link"] = {"desc": f"Build a marketplace at {mx},{my}: {len(cut_off)} buildings there have no road "
                                    f"to any market (their goods never arrive)",
                            "cmd": [["market-near", mx, my]]}
    # Houses without a marketplace in reach get no goods and pay little (coach, new game: 9 houses
    # at the Kontor alone). A marketplace in the middle of them, at a road.
    if s.get("houses_without_market", 0) >= 3 and "marketplace" in buildings \
            and affordable(buildings["marketplace"], s):
        hs = house_origins(grid_s)
        if hs:
            mx = sum(x for x, _ in hs) // len(hs)
            my = sum(y for _, y in hs) // len(hs)
            o["market"] = {"desc": f"Build a marketplace at {mx},{my}: {s['houses_without_market']} houses have no "
                                   f"market in reach and get no goods",
                           "cmd": [["market-near", mx, my]]}
    # Long-term plan (strategy.py, the planner's Gozintograph): buildings the stage still misses and
    # no rule above offers (winery, tobacco, school, church ...), and nothing the plan already has.
    gaps = s.get("gaps")
    if gaps is not None:
        offered = {b for k in o for b in OPT_OF.get(k, [])}
        for b, n in gaps.items():
            # Buildings with their own site search (water, forest, meadow, mountain) only via their rule.
            if b in ("houses", "warehouse_1", "fishers_hut", "hunters_hut", "forester", "sheep_farm", "quarry",
                     "marketplace") or b in offered or b not in buildings or not affordable(buildings[b], s):
                continue
            # Along the chain from the raw end (coach: the tobacco factory came before any plantation).
            raw_from = strategy.upstream(b)
            if raw_from and have.get(raw_from, 0) < 1:
                continue
            field = field_of(b, buildings)
            if field:
                found = field_site(isl, grid_s, b)
                if not found:
                    continue
                (px, py, pr), room = found
                cmd = [["build", b, isl, px, py, pr], ["build-many", field, isl, px - 2, py - 2, px + 3, py + 3],
                       ["connect-last", b, px, py]]
                where = f"with {room} {field} around it"
            else:
                if b in PUBLIC:
                    cmd = [["build-near", b, cx, cy, 12], ["connect-last", b, cx, cy]]  # among the houses
                    where = "at a road in town"
                else:
                    site_o = outskirts_site(b, isl)
                    if not site_o:
                        continue
                    cmd = [["build", b, isl, *site_o], ["connect-last", b, site_o[0], site_o[1]]]
                    where = f"at the edge of town ({site_o[0]},{site_o[1]})"
            o[f"plan_{b}"] = {"desc": f"Build a {b.replace('_', ' ')} {where} ({buildings[b]['gold']} gold): the plan "
                                      f"still needs {n} for {s.get('stage', 'this stage')}",
                              "cmd": cmd}
        # Drop what the plan already has enough of. Forester and brickworks stay: houses eat wood beyond
        # the plan, and tavern, winery and plantations need bricks a stage before the plan's stonemason.
        for key, blds in OPT_OF.items():
            # Public buildings follow the houses they must reach, not the plan's count (review: the
            # plan said 2 chapels, 4 stood, so 55 houses never got one).
            if key in o and key not in ("forester", "bricks", "chapel", "tavern", "school", "church") \
                    and not any(gaps.get(b, 0) > 0 for b in blds):
                del o[key]
        if "houses" in o and gaps.get("houses", 0) <= 0 and len(o) > 1:
            pass  # houses always pay: more than the stage needs is fine
    # Materials first (the Gozintograph's second half): while the brickworks is missing and bricks
    # are short, the scarce tools are kept for it; nothing else that eats tools is offered.
    rows = s.get("material_rows") or []
    bricks_row = next((r for r in rows if r["material"] == "bricks"), None)
    if bricks_row and bricks_row["short"] > 0 and have.get("stonemason", 0) < 1:
        reserve = sum(buildings.get(b, {}).get("tools", 0) for b in ("quarry", "stonemason")
                      if have.get(b, 0) < 1)
        spare = st.get("tools", 0) - reserve
        for key in list(o):
            if key == "bricks":
                continue
            blds = OPT_OF.get(key) or ([key[5:]] if key.startswith("plan_") else [])
            tools = max((buildings.get(b, {}).get("tools", 0) for b in blds), default=0)
            if tools > 0 and tools > spare:
                del o[key]
    # Supply before expansion, and no running costs the taxes cannot carry (coach, game 3: rum
    # distillery, school, tavern and winery cost 95 a minute before anything was supplied; cloth and
    # alcohol fell to 0-4%, the settlers moved out and the money went below zero).
    unmet = {w for cls in s["classes"].values() if cls["people"] for w, pct in cls["supply"].items() if pct < 90}
    if s.get("food_supply", 100) < 100:
        unmet.add("food")
    supplies = {b for w in unmet for _, chain in strategy.planner.CHAINS.get(w, []) for b in chain}
    PUBLIC_NEXT = ("tavern", "school", "church", "bathhouse", "theatre", "college")
    supply_offered = any(set(OPT_OF.get(k) or ([k[5:]] if k.startswith("plan_") else [])) & supplies for k in o)
    for key in list(o):
        blds = OPT_OF.get(key) or ([key[5:]] if key.startswith("plan_") else [])
        if not blds:
            continue
        running = max(buildings.get(b, {}).get("running", 0) for b in blds)
        feeds_need = bool(set(blds) & supplies)
        if supply_offered and any(b in PUBLIC_NEXT for b in blds):
            del o[key]  # the next class's public buildings wait until the present needs are met
        # With a full treasury the guard rests, and a chapel (5 a minute) never waits for it (review:
        # 20 houses on Essix could not rise for want of a chapel while 19.7k gold lay idle).
        elif running and s.get("balance", 0) - running < 0 and not feeds_need \
                and s.get("money", 0) < RICH and key != "chapel":
            del o[key]  # its running costs would push the balance below zero
    # Colonies grow what their soil grows best and send it home (review: alcohol at 25% for 372
    # settlers while island 2 has full wine and island 12 full sugar, neither with a winery or rum).
    if LIVE_ISLANDS and isl != LIVE_ISLANDS[0]:
        _, isl_txt = ctl("islands")
        m_c = re.search(rf"island {isl}:.*crops: ([^;]*?);", isl_txt)
        full_crops = [c for c in (m_c[1].split() if m_c else []) if "(" not in c]
        g_c = island_map(isl)
        if "wine" in full_crops and have.get("winery", 0) < 2 and "winery" in buildings \
                and affordable(buildings["winery"], s):
            # 14 vines on a colony are enough while alcohol is that scarce (review: home 17%, Essix 0%,
            # no winery anywhere on wine soil because no place had 20 free tiles).
            best_w = ranked_sites("winery", isl, g_c, gap=5)
            found = best_w[0] if best_w and best_w[0][1] >= 14 else None
            if found:
                (px, py, pr), room = found
                o["chain_colony_winery"] = {"desc": f"Build a winery with {room} vines at {px},{py} on this colony "
                                                    f"(full wine soil): alcohol for home by ship",
                                            "cmd": [["build", "winery", isl, px, py, pr],
                                                    ["build-many", "vines", isl, px - 2, py - 2, px + 3, py + 3],
                                                    ["connect-last", "winery", px, py]]}
        if "sugar" in full_crops and have.get("sugarcane_plantation", 0) < 2 \
                and "sugarcane_plantation" in buildings and affordable(buildings["sugarcane_plantation"], s):
            found = field_site(isl, g_c, "sugarcane_plantation")
            if found:
                (px, py, pr), room = found
                o["chain_colony_sugar"] = {"desc": f"Build a sugarcane plantation with {room} fields at {px},{py} "
                                                   f"(full sugar soil): sugar for rum",
                                           "cmd": [["build", "sugarcane_plantation", isl, px, py, pr],
                                                   ["build-many", "sugarcane_field", isl, px - 2, py - 2, px + 3, py + 3],
                                                   ["connect-last", "sugarcane_plantation", px, py]]}
        # Cocoa for the merchants (Essix: full cocoa soil; home had 343 citizens waiting for it).
        if "cocoa" in full_crops and have.get("cocoa_plantation", 0) < 2 and "cocoa_plantation" in buildings \
                and affordable(buildings["cocoa_plantation"], s):
            best_c = ranked_sites("cocoa_plantation", isl, g_c, gap=5)
            field_c = field_of("cocoa_plantation", buildings)
            if best_c and best_c[0][1] >= 12 and field_c:
                (px, py, pr), room = best_c[0]
                o["chain_colony_cocoa"] = {"desc": f"Build a cocoa plantation with {room} fields at {px},{py} "
                                                   f"(full cocoa soil): cocoa for the merchants",
                                           "cmd": [["build", "cocoa_plantation", isl, px, py, pr],
                                                   ["build-many", field_c, isl, px - 2, py - 2, px + 3, py + 3],
                                                   ["connect-last", "cocoa_plantation", px, py]]}
        # Tobacco goods from tobacco (Kap Crus, island 4: full tobacco soil; the citizens at home sit
        # at 3% tobacco goods and cannot rise to merchants).
        if "tobacco" in full_crops and have.get("tobacco_plantation", 0) < 2 and "tobacco_plantation" in buildings \
                and affordable(buildings["tobacco_plantation"], s):
            best_t = ranked_sites("tobacco_plantation", isl, g_c, gap=5)
            field_t = field_of("tobacco_plantation", buildings)
            if best_t and best_t[0][1] >= 12 and field_t:
                (px, py, pr), room = best_t[0]
                o["chain_colony_tobacco"] = {"desc": f"Build a tobacco plantation with {room} fields at {px},{py} "
                                                     f"(full tobacco soil): tobacco goods for the citizens at home",
                                             "cmd": [["build", "tobacco_plantation", isl, px, py, pr],
                                                     ["build-many", field_t, isl, px - 2, py - 2, px + 3, py + 3],
                                                     ["connect-last", "tobacco_plantation", px, py]]}
        if have.get("tobacco_plantation", 0) >= 1 and have.get("tobacco_products", 0) < 1 \
                and "tobacco_products" in buildings and affordable(buildings["tobacco_products"], s):
            site = outskirts_site("tobacco_products", isl) or best_site("tobacco_products", isl, cx, cy, r)
            if site:
                o["chain_colony_tobacco_goods"] = {"desc": f"Build a tobacco goods workshop at {site[0]},{site[1]}: "
                                                           f"the colony's tobacco becomes tobacco goods",
                                                   "cmd": [["build", "tobacco_products", isl, *site],
                                                           ["connect-last", "tobacco_products", site[0], site[1]]]}
        # Cloth from cotton (Essix: full cotton soil; its pioneers cannot rise to settlers without
        # cloth and alcohol in store - the engine wants the next class fully satisfied).
        if "cotton" in full_crops and have.get("cotton_plantation", 0) < 2 and "cotton_plantation" in buildings \
                and affordable(buildings["cotton_plantation"], s):
            found = field_site(isl, g_c, "cotton_plantation")
            field = field_of("cotton_plantation", buildings)
            if found and field:
                (px, py, pr), room = found
                o["chain_colony_cotton"] = {"desc": f"Build a cotton plantation with {room} fields at {px},{py} "
                                                    f"(full cotton soil): cloth for the settlers",
                                            "cmd": [["build", "cotton_plantation", isl, px, py, pr],
                                                    ["build-many", field, isl, px - 2, py - 2, px + 3, py + 3],
                                                    ["connect-last", "cotton_plantation", px, py]]}
        if have.get("cotton_plantation", 0) >= 1 and have.get("weaving_mill", 0) < 1 \
                and "weaving_mill" in buildings and affordable(buildings["weaving_mill"], s):
            site = outskirts_site("weaving_mill", isl) or best_site("weaving_mill", isl, cx, cy, r)
            if site:
                o["chain_colony_weaving"] = {"desc": f"Build a weaving mill at {site[0]},{site[1]}: the colony's "
                                                     f"cotton becomes cloth",
                                             "cmd": [["build", "weaving_mill", isl, *site],
                                                     ["connect-last", "weaving_mill", site[0], site[1]]]}
        if have.get("sugarcane_plantation", 0) >= 1 and have.get("rum_distillery", 0) < 1 \
                and "rum_distillery" in buildings and affordable(buildings["rum_distillery"], s):
            site = outskirts_site("rum_distillery", isl) or best_site("rum_distillery", isl, cx, cy, r)
            if site:
                o["chain_colony_rum"] = {"desc": f"Build a rum distillery at {site[0]},{site[1]}: the colony's sugar "
                                                 f"becomes alcohol for home",
                                         "cmd": [["build", "rum_distillery", isl, *site],
                                                 ["connect-last", "rum_distillery", site[0], site[1]]]}
        # Colonies get chapels only, no tavern, school or church (review: two schools and a tavern on
        # colonies of a few pioneers cost 75 a minute for nothing) - unless the colony has become a
        # town (40+ settlers) and the treasury is full: then its settlers may rise and pay more.
        grown = s.get("classes", {}).get("settlers", {}).get("people", 0) >= 40 and s.get("money", 0) >= RICH
        for k in [k for k in o if k in ("tavern", "school", "church", "plan_tavern", "plan_school", "plan_church")]:
            if not (grown and k in ("tavern", "school")) and isl not in GROW:
                del o[k]
        # Colonies buy nothing from traders: home supplies them by ship (colonies bought alcohol and
        # tools at 60-75 for a handful of pioneers). A second main town (GROW) trades like home.
        # Exception: a colony grown to 80+ settlers buys cloth and alcohol while the treasury is full
        # (review: Ackstedt 150 -> 100 and Prahag 234 -> 195 settlers at cloth ~50%, alcohol 0-10%).
        settlers_here = s.get("classes", {}).get("settlers", {}).get("people", 0)
        keep = ()  # user: produce, do not buy (was cloth + alcohol for big colonies)
        if isl not in GROW:
            for w in s.get("buying", ()):
                if w not in keep:
                    ctl("trade", isl, 0, w, "none")
            for w, price in (("cloth", 40), ("alcohol", 60)):
                if w in keep and w not in s.get("buying", ()):
                    ctl("trade", isl, 0, w, "buy", 15, price)
            for k in [k for k in o if k.startswith("buy_")]:
                del o[k]
    # A second main town (user: "Essix would suit better as the new main island" - same size as
    # home, free land, cocoa soil): its food from grain (user: "grain, mill and bakery for more food
    # for such big new towns"), along the chain from the raw end: farms, then a mill, then a bakery;
    # one chain per 25 houses.
    # Also any grown colony that runs short of food (Prahag: 40 houses, no fisher place left, 78%).
    hungry = LIVE_ISLANDS and isl != LIVE_ISLANDS[0] and sum(s.get("houses", [0])) >= 20         and s.get("food_supply", 100) < 100 and s.get("money", 0) >= RICH
    if isl in GROW or hungry:
        n_here = sum(s.get("houses", [0]))
        chains = 1 + n_here // 25
        g_g = island_map(isl)
        if n_here >= 6 and have.get("grain_farm", 0) < 2 * chains and "grain_farm" in buildings \
                and affordable(buildings["grain_farm"], s):
            found = field_site(isl, g_g, "grain_farm")
            field = field_of("grain_farm", buildings)
            if found and field:
                (px, py, pr), room = found
                o["food_grain_farm"] = {"desc": f"Build a grain farm with {room} fields at {px},{py}: grain for "
                                                f"flour and bread, food for a big town",
                                        "cmd": [["build", "grain_farm", isl, px, py, pr],
                                                ["build-many", field, isl, px - 1, py - 1, px + 2, py + 2],
                                                ["connect-last", "grain_farm", px, py]]}
        for b, before in (("grain_mill", "grain_farm"), ("bakery", "grain_mill")):
            # One mill and one bakery per chain (review: mills grew with the farms, 4 mills and 4
            # bakeries on Essix stood full and idle, their carts could not keep up).
            want = chains
            if have.get(before, 0) >= 1 and have.get(b, 0) < want and b in buildings and affordable(buildings[b], s):
                site = outskirts_site(b, isl) or best_site(b, isl, cx, cy, r)
                if site:
                    o[f"food_{b}"] = {"desc": f"Build a {b.replace('_', ' ')} at {site[0]},{site[1]}: the next step "
                                              f"of the bread chain",
                                      "cmd": [["build", b, isl, *site], ["connect-last", b, site[0], site[1]]]}
    # Supply chains at full speed (user: industries and farms must run at 100%): the raw producers a
    # workshop lacks, at a good place in a market's reach. Not subject to the cost guard above.
    # Home only: on Essix it stacked farms on mills on bakeries (6 farms, 5 mills at 12-55%) while
    # the bread rule above already sizes that chain.
    if LIVE_ISLANDS and isl == LIVE_ISLANDS[0]:
        o.update(chain_options(isl, buildings, s, grid_s))
    # Safety before the cost guard: a fire station once the town has 20 houses (radius 15, in the
    # middle of the houses). It is offered even when its running costs pinch.
    if sum(s.get("houses", [0])) >= 20 and have.get("fire_station", 0) < 1 and "fire_station" in buildings \
            and affordable(buildings["fire_station"], s):
        hs = house_origins(grid_s)
        if hs:
            hx = sum(x for x, _ in hs) // len(hs)
            hy = sum(y for _, y in hs) // len(hs)
            o["fire_station"] = {"desc": f"Build a fire station among the {len(hs)} houses (150 gold): without it a "
                                         f"fire spreads from house to house",
                                 "cmd": [["build-near", "fire_station", hx, hy, 10],
                                         ["connect-last", "fire_station", hx, hy]]}
    # A full town and a full treasury: houses make way for the public buildings the next class
    # needs (user: "so much money, yet you expand very slowly" - church, bathhouse, school and
    # tavern found no place on the built-up home island while 28k gold lay idle).
    # Also on a second main town, by the houses that lack the building (Essix: 540 settlers, no school
    # or tavern place, no citizen).
    # Home only again: on Essix it put 9 schools/taverns into the middle (the houses lacking them lie
    # at both edges, their centroid is the middle too) and pulled 12 houses down for nothing.
    if LIVE_ISLANDS and isl == LIVE_ISLANDS[0] and s.get("money", 0) >= RICH:
        g_r = island_map(isl)
        for b in ("church", "bathhouse", "school", "tavern"):
            wanted = s.get("gaps", {}).get(b, 0) > 0 if isl == LIVE_ISLANDS[0] else \
                (b in ("school", "tavern") and len(houses_without(isl, g_r, b)) >= 8)
            # At most one of each kind per island in 10 minutes: its reach must show first.
            if time.time() - ROOM_AT.get((isl, b), 0) < 600:
                continue
            if wanted and b in buildings and affordable(buildings[b], s) \
                    and not best_site(b, isl, cx, cy, r):
                o[f"room_{b}"] = {"desc": f"Pull down the houses on one spot in town and build the {b} there "
                                          f"({buildings[b]['gold']} gold): the plan needs it and no free place is left",
                                  "cmd": [["make-room", b]]}
                break  # one at a time
    # Money brake (coach: the colony's foresters took the gold down to 177): below 500 gold no
    # building at all, only trade, taxes and waiting until the city has earned again.
    # With a strong balance a small cushion is enough (review: money swung between 0 and 370 at
    # +136 a minute and never reached 500, so the winery and the chapels were never built).
    brake = 150 if s.get("balance", 0) >= 100 else 500
    if s.get("money", 0) < brake:
        # A chapel stays: 100 gold, 5 a minute, and houses without one can never become settlers
        # (review: 24 of 43 houses lacked a chapel while the brake held everything back).
        keep_chapel = "chapel" in o and s.get("money", 0) >= buildings.get("chapel", {}).get("gold", 100) + 100
        # Houses (wood only, no gold) and the streets for them (5 gold a tile) bring the money back:
        # they stay too (user: "why not many more pioneer houses?" - the brake had blocked them).
        o = {k: v for k, v in o.items() if k.startswith(("sell_", "tax_")) or (k == "chapel" and keep_chapel)
             or k == "houses" or (k == "street" and s.get("money", 0) >= 100) or k == "quarter"
             or (k.startswith(("chain_", "market_near")) and s.get("money", 0) >= 300)}
    # Options that just failed for want of a place rest for 10 minutes (review: market_near and
    # plan_tavern were picked again and again with 'no place').
    for key in [k for k in o if time.time() - FAILED_AT.get(k, 0) < 600]:
        del o[key]
    # Raw production belongs on the supply islands (user): the main towns keep their land for
    # houses - no new farms, plantations, wineries, pastures, foresters or stonemasons there.
    # Only once a supply island exists: a new game's lone home town would never get wood at all
    # (two-agent test game: Jev waited 150 rounds with 6 t wood and no forester allowed).
    if isl in MAIN_TOWNS and len(LIVE_ISLANDS) > 1:
        for key in [k for k in o if any(b in k for b in RAW_ON_COLONIES + ("grain_mill", "bakery"))]:
            del o[key]
    # Supply islands only fetch raw materials (user): no houses and no public buildings there, the
    # goods go to the main towns, which are to hold as many aristocrats as possible.
    if isl not in MAIN_TOWNS:
        for key in [k for k in o if any(b in k for b in HOUSING_KEYS)]:
            del o[key]
    # A forester among fields without a tree (user screenshot, Kap Crus 9,19 at 0%): none while the
    # island holds 40 t of wood.
    if st.get("wood", 0) >= 40:
        for key in [k for k in o if "forester" in k]:
            del o[key]
    # ... and none where no forest stands (user: the forester went right into the vineyards on
    # Ackstedt twice): only where the game's forester site finds enough trees.
    # The game's forester site counts vines and other crops as trees (Ackstedt: 45 "trees" = vines),
    # so the plantation islands get no forester at all.
    if any("forester" in k for k in o) and (isl in NO_FORESTER or forest_site(isl, island_map(isl)) is None):
        for key in [k for k in o if "forester" in k]:
            del o[key]
    # Stonemasons kept coming back at 0% (no stone in reach) while bricks lay everywhere.
    if st.get("bricks", 0) >= 30:
        for key in [k for k in o if "stonemason" in k or "quarry" in k or k == "bricks"]:
            del o[key]
    if not o:
        o["wait"] = {"desc": "Nothing can be built or traded now: wait and let the city earn", "cmd": None}
    return o


MAIN_TOWNS: set[int] = set()  # filled in main(): the home island and the GROW islands
NO_FORESTER = {2, 4}  # Ackstedt (wine), Kap Crus (tobacco, sugar): crops only, the site count mistakes them for trees
HOUSING_KEYS = ("house", "quarter", "street", "chapel", "tavern", "school", "church", "bathhouse", "doctor", "fire_station",
                "theatre", "college", "upgrade")
RAW_ON_COLONIES = ("sheep_farm", "cattle_farm", "cotton_plantation", "tobacco_plantation", "sugarcane_plantation",
                   "grain_farm", "spice_plantation", "cocoa_plantation", "winery", "forester", "stonemason",
                   "quarry", "hunters_hut")


def connect_check(grid: dict, x: int, y: int, w: int, h: int) -> bool:
    """True when no road can be laid from the building to a market road (it is cut off)."""
    sides = [(x + i, y - 1) for i in range(w)] + [(x + i, y + h) for i in range(w)] + \
            [(x - 1, y + j) for j in range(h)] + [(x + w, y + j) for j in range(h)]
    return road_path(grid, sides, network(grid)) is None


LAST_BUILT: dict[str, tuple[int, int]] = {}
PRODUCE: set = set()            # production colonies (--produce): few houses, crops first
COLONY_TURN = [0]               # round robin over the colonies that are not GROW
GROW: set = set()            # second main towns (--grow): home-town rules on a colony
RICH = 10000                 # gold from which the driver spends on growth instead of saving
COLONY_HOUSES_RICH = 40      # houses a colony may grow to while the treasury is that full


ROOM_AT: dict = {}  # (island, building) -> when make_room last put one up


def make_room(island: int, name: str, buildings: dict, max_dist: int = 8, allow_upper: bool = False) -> str:
    """Pulls down the houses on the spot nearest the middle of town where the building fits on
    houses alone with a road at one side, then builds it there."""
    # Materials first (review: bathhouse and church refused for want of tools after 3 houses fell).
    if name not in buildings or not affordable(buildings[name], read_state(island)):
        return f"{name}: not affordable now - nothing pulled down"
    grid = island_map(island)
    w, h = buildings.get(name, {}).get("size", (2, 2))
    hs = house_origins(grid)
    if not hs:
        return "no houses"
    # Near the houses that lack it, not the middle of town (review: 8 schools on Essix, 5 of them in
    # the middle, while the houses without a school stood at the edge and the count never fell).
    lacking = houses_without(island, grid, name) if name in ("school", "tavern", "chapel", "church", "bathhouse",
                                                             "college", "theatre", "doctor") else []
    # The biggest group of houses lacking it, not their mean (Essix: lacking houses at both edges
    # put the mean in the middle where every house already had one).
    # College and theatre are the aristocrats' (merchant houses rise only with both): aim at the
    # merchant houses lacking it, not at settlers who will not need it for long (user: pull houses
    # down and rebuild to serve the aristocrats' wishes as efficiently as possible).
    if name in ("college", "theatre") and lacking:
        _, hout0 = ctl("houses", island)
        merch = {(int(m[1]), int(m[2])) for m in re.finditer(r"^\s+(\d+) (\d+) merchants ", hout0, re.M)}
        lacking = [h for h in lacking if h in merch] or lacking
    centre = best_service_center(lacking, 10) if lacking else None
    if centre:
        cx, cy = centre
    else:
        cx = sum(x for x, _ in hs) / len(hs)
        cy = sum(y for _, y in hs) / len(hs)
    # Only pioneer and settler houses may make way (review: field clearing in the capital took
    # merchant houses and the merchants fell from 96 to 48).
    _, hout = ctl("houses", island)
    upper = {(int(m[1]), int(m[2])) for m in re.finditer(r"^\s+(\d+) (\d+) (merchants|aristocrats) ", hout, re.M)}
    best = None
    for (x, y), v in grid.items():
        for rot, (fw, fh) in ((0, (w, h)), (1, (h, w))):
            tiles = [(x + i, y + j) for i in range(fw) for j in range(fh)]
            if not all(grid.get(t) in ("H", ":", "T", ".") for t in tiles) or not any(grid.get(t) == "H" for t in tiles):
                continue
            sides = [(x + i, y - 1) for i in range(fw)] + [(x + i, y + fh) for i in range(fw)] + \
                    [(x - 1, y + j) for j in range(fh)] + [(x + fw, y + j) for j in range(fh)]
            if not any(grid.get(t) == "=" for t in sides):
                continue
            # Fewest houses lost first, then nearest the middle of town.
            lost = [(hx, hy) for hx, hy in hs if any(hx <= tx <= hx + 1 and hy <= ty <= hy + 1 for tx, ty in tiles)]
            if not allow_upper and any(h in upper for h in lost):
                continue
            # Close to the group it is for (the theatre for the western merchants landed 12 tiles
            # off because it cost one house less there): a spot beyond 8 tiles does not count.
            dist = abs(x + fw / 2 - cx) + abs(y + fh / 2 - cy)
            if centre and dist > max_dist:
                continue
            score = (len(lost), dist)
            if best is None or score < best[0]:
                best = (score, x, y, rot, lost)
    if best is None:
        return f"no spot of houses fits a {name}"
    _, x, y, rot, lost = best
    for hx, hy in lost:
        ctl("demolish", island, hx, hy)
    code, out = ctl("build", name, island, x, y, rot)
    last = out.strip().splitlines()[-1] if out.strip() else f"exit {code}"
    ctl("fix-roads", island)
    ctl("say", f"Platz gemacht: {len(lost)} Häuser für {name} bei {x},{y}")
    return f"{len(lost)} houses pulled down at {x},{y} for the {name}: {last}"


CHAT = {"on": True, "said": 0.0}  # off after the game says chat is for multiplayer games only
CHAT_EVERY = 60.0  # real seconds between Jev's own lines, so the chat box stays readable
TRADE_WORDS = ("handel", "trade", "vertrag", "treaty", "kauf", "verkauf", "buy", "sell")


def chat_say(text: str, force: bool = False) -> None:
    """One line into the multiplayer chat: the other agent and the people watching read it."""
    if not CHAT["on"] or (not force and time.time() - CHAT["said"] < CHAT_EVERY):
        return
    code, out = ctl("chat", text)
    if code != 0 and "multiplayer" in out:
        CHAT["on"] = False  # a game alone
        return
    CHAT["said"] = time.time()


def other_humans() -> list[int]:
    """The other people's (agents') player numbers, from o1602-ctl diplomacy."""
    _, out = ctl("diplomacy")
    # A tournament's referee hosts as a person too, but plays nothing: no treaties with it.
    return [int(m[1]) for m in re.finditer(r"^\s*(\d+): ([^,]*), human,", out, re.M) if m[2] != "Referee"]


def chat_round(st_line: str) -> None:
    """Reads what the other players wrote (the game's state says when there is something). A line
    about trade: Jev accepts a trade treaty they offered, or offers one, and says so; the rest of the
    trade is the Kontors' buy and sell offers (o1602-ctl trade), which the other's ships use."""
    if not CHAT["on"] or "new lines from the other players" not in st_line:
        return
    code, out = ctl("chat")
    if code != 0:
        return
    for line in out.splitlines():
        if not line.strip() or line.startswith("no new chat"):
            continue
        print(f"{CYAN}  chat: {line}{RESET}", flush=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "chat": line}) + "\n")
        if any(w in line.lower() for w in TRADE_WORDS):
            _, rel = ctl("diplomacy")
            for seat in other_humans():
                if re.search(rf"^\s*{seat}: [^,]*, human, [^,]*, trade signed", rel, re.M):
                    continue  # the treaty stands: the Kontor's offers answer the rest
                _, o = ctl("diplomacy", seat, "trade", "accept")  # "done; ... trade signed" when they offered
                if "trade signed" not in o:
                    _, o = ctl("diplomacy", seat, "trade", "offer")
                print(f"  diplomacy {seat}: {o.strip()[:100]}", flush=True)
                chat_say(f"Handel ja - {o.strip()[:80]}. Mein Kontor zeigt, was ich kaufe und verkaufe.",
                         force=True)


def run(cmd, args) -> str:
    """Carries out an option: one o1602-ctl command, a list of them, or a batch of houses."""
    if cmd is None:
        return "waited"
    cmds = cmd if isinstance(cmd[0], list) else [cmd]
    results = []
    for c in cmds:
        if c[0] == "build-house-batch":
            built = 0
            for _ in range(int(c[1])):
                site = best_site("house", args.island, args.cx, args.cy, args.radius)
                if not site:
                    break
                code, _ = ctl("build", "house", args.island, *site)
                built += code == 0
            ctl("fix-roads", args.island)  # every house at a road (doctor, fire brigade)
            results.append(f"built {built} houses")
            continue
        if c[0] == "road-long":
            results.append(road_long(*map(int, c[1:])))
            continue
        if c[0] == "pave":
            results.append(pave(args.island, island_map(args.island)))
            continue
        if c[0] == "connect-fisher":
            g = island_map(args.island)
            if not touches(network(g), g, int(c[1]), int(c[2]), 1, 1):
                results.append(connect(args.island, g, "fishers_hut", int(c[1]), int(c[2]), 1, 1))
            continue
        if c[0] == "colonize":
            results.append(colonize(int(c[1]), LIVE_ISLANDS[0]))
            continue
        if c[0] == "build-near":
            radius = int(c[4]) if len(c) > 4 else 6
            _, out = ctl("find-site", c[1], args.island, int(c[2]), int(c[3]), radius)
            done = f"no place for {c[1]}"
            sites = [ln.split() for ln in out.splitlines()[1:] if len(ln.split()) >= 4]
            # A place at a road first; else one a road can still reach (connect-last lays it).
            g = island_map(args.island)
            pick = next((p for p in sites if p[3] == "road"), None) or \
                next((p for p in sites if reachable(g, int(p[0]), int(p[1]), 2, 2)), None)
            if pick:
                code, o2 = ctl("build", c[1], args.island, pick[0], pick[1], pick[2])
                done = o2.strip().splitlines()[-1] if o2.strip() else f"exit {code}"
                if code == 0:
                    LAST_BUILT[c[1]] = (int(pick[0]), int(pick[1]))
            results.append(done)
            continue
        if c[0] == "make-room":
            ROOM_AT[(args.island, c[1])] = time.time()
            results.append(make_room(args.island, c[1], read_buildings()))
            continue
        if c[0] == "quarter":
            g = island_map(args.island)
            q = plan_quarter(args.island, g)
            st = read_state(args.island)["stock"]
            results.append(build_quarter(args.island, q, st.get("wood", 0)) if q else "no quarter fits any more")
            continue
        if c[0] == "market-near":
            # A marketplace as close as possible to the cut-off buildings, road or not, then roads
            # from each of them to it.
            _, out = ctl("find-site", "marketplace", args.island, int(c[1]), int(c[2]), 8)
            done = "no place for a marketplace"
            for line in out.splitlines()[1:]:
                p = line.split()
                if len(p) >= 3 and p[0].isdigit():
                    code, o2 = ctl("build", "marketplace", args.island, p[0], p[1], p[2])
                    done = o2.strip().splitlines()[-1] if o2.strip() else f"exit {code}"
                    if code == 0:
                        g = island_map(args.island)
                        for b in isolated(args.island, g, read_buildings())[:6]:
                            done += "; " + connect(args.island, g, *b)
                            g = island_map(args.island)
                    break
            results.append(done)
            continue
        if c[0] == "connect-last":
            g = island_map(args.island)
            bx, by = LAST_BUILT.pop(c[1], (int(c[2]), int(c[3])))  # where build-near really put it
            if not touches(network(g), g, bx, by, 2, 2):
                results.append(connect(args.island, g, c[1], bx, by, 2, 2))
            continue
        code, out = ctl(*c)
        results.append(out.strip().splitlines()[-1] if out.strip() else f"exit {code}")
    return "; ".join(results)


def road_long(island: int, sx: int, sy: int, rx: int, ry: int) -> str:
    """A road longer than the game's drag search reaches: pieces of up to 6 tiles, first along y,
    then along x, each ending on a tile a road may take."""
    grid = island_map(island)
    ok = (":", "T", "t", ".", "=", "#", "+", "w")
    x, y, laid = sx, sy, 0
    for _ in range(12):
        if (x, y) == (rx, ry):
            break
        nx, ny = x, y
        if y != ry:
            ny = y + max(-6, min(6, ry - y))
        else:
            nx = x + max(-6, min(6, rx - x))
        # Back off to a tile a road may take.
        while (nx, ny) != (x, y) and grid.get((nx, ny)) not in ok:
            nx += (x > nx) - (x < nx)
            ny += (y > ny) - (y < ny)
        if (nx, ny) == (x, y):
            return f"road stopped at {x},{y} after {laid} pieces"
        code, _ = ctl("road", island, x, y, nx, ny)
        if code != 0:
            return f"road piece {x},{y}->{nx},{ny} refused after {laid} pieces"
        laid += 1
        x, y = nx, ny
    return f"road of {laid} pieces to {x},{y}"


# ---------------------------------------------------------------------------------------------
# Asking the model


def jev_headers(url: str) -> dict:
    """The hosted Jev (api.typesafe.ai) wants the key as a Bearer token; it comes from the
    environment variable TYPESAFE_API_KEY, never from code or the log."""
    h = {"Content-Type": "application/json"}
    key = os.environ.get("TYPESAFE_API_KEY", "")
    if not key and sys.platform == "win32":  # set for the user after this shell started
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                key = winreg.QueryValueEx(k, "TYPESAFE_API_KEY")[0]
        except OSError:
            key = ""
    if key and "127.0.0.1" not in url and "localhost" not in url:
        h["Authorization"] = f"Bearer {key}"
    return h


HISTORY: list[dict] = []          # the last decisions and what came of them (for the hosted model)
HOSTED_CALLS: list[float] = []    # times of hosted calls in the last minute (cost cap)
HOSTED_TOTAL = [0]                # hosted calls since the start (shown over the map)
LOCAL_URL = "http://127.0.0.1:11434/v1/systemone"
LOCAL_MODEL = "tev1:0.8b"
GOAL = ("Earn as much gold per minute as possible and keep the inhabitants supplied; follow the long-term "
        "plan (stage, missing buildings, building materials); never let money fall below -1000 (bankruptcy).")


def option_facts(key: str, opt: dict, buildings: dict, s: dict) -> dict:
    """What an option costs and how it relates to the plan: the facts the hosted model weighs."""
    blds = OPT_OF.get(key) or ([key[5:]] if key.startswith("plan_") else [])
    cost = {"gold": 0, "tools": 0.0, "wood": 0.0, "bricks": 0.0, "running": 0}
    for b in blds[:1]:
        c = buildings.get(b, {})
        cost = {k: c.get(k, 0) for k in ("gold", "tools", "wood", "bricks", "running")}
    gaps = s.get("gaps") or {}
    return {"what": opt["desc"], "builds": blds, "cost": cost,
            "plan_still_needs": sum(gaps.get(b, 0) for b in blds)}


def decide(s: dict, opts: dict, args, buildings: dict | None = None) -> dict:
    """Asks Jev which option to take. Hosted (api.typesafe.ai, --hosted): the whole picture as state
    (city, plan, materials, warnings, recent decisions, the facts of every option) and an extra
    yes/no question on the money risk; the docs advise one judgement per question, combined here.
    Local (Ollama): the compact city state as before. Over the cost cap or on an error: local."""
    hosted = args.hosted and "127.0.0.1" not in args.url
    now = time.time()
    HOSTED_CALLS[:] = [t for t in HOSTED_CALLS if now - t < 60]
    if hosted and len(HOSTED_CALLS) >= args.max_calls_per_min:
        hosted = False  # cost cap: this decision goes to the local model
    compact = {k: v for k, v in s.items() if k not in ("island", "material_rows")}
    if hosted:
        state = {
            "goal": GOAL,
            "city": compact,
            "plan": {"stage": s.get("plan", ""), "materials": s.get("materials", []),
                     "goods_chains": s.get("gozinto", [])},
            "warnings": s.get("alerts", []),
            "recent_decisions": HISTORY[-8:],
            "options": {k: option_facts(k, v, buildings or {}, s) for k, v in opts.items()},
        }
        questions = {
            "action": {"type": "choice",
                       "instructions": "Which single action helps this city most right now, given the plan, the "
                                       "building materials, the money and what the recent decisions achieved?",
                       "criteria": {k: v["desc"] for k, v in opts.items()}},
            "money_risk": {"type": "noul",
                           "instructions": "Will the city run out of money (below 0 gold) within the next ten "
                                           "minutes if it goes on like this?"},
        }
        body = {"model": args.model, "state": state, "questions": questions}
        url = args.url
    else:
        body = {"model": LOCAL_MODEL if args.hosted else args.model,
                "state": {"city": json.dumps(compact, separators=(",", ":")), "goal": GOAL},
                "questions": {"action": {"type": "choice",
                                         "instructions": "Which single action helps this city most right now?",
                                         "criteria": {k: v["desc"] for k, v in opts.items()}}}}
        url = LOCAL_URL if args.hosted else args.url
    t0 = time.time()
    try:
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers=jev_headers(url))
        with urllib.request.urlopen(req, timeout=60) as r:
            reply = json.loads(r.read())
        if hosted:
            HOSTED_CALLS.append(time.time())
            HOSTED_TOTAL[0] += 1
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        if not hosted:
            raise
        print(f"{YELLOW}  JEV  hosted call failed ({e}); asking the local model{RESET}", flush=True)
        args_local = argparse.Namespace(**{**vars(args), "hosted": False, "url": LOCAL_URL, "model": LOCAL_MODEL})
        return decide(s, opts, args_local, buildings)
    ans = reply["answers"]["action"]
    ans["backend"] = f"{'hosted ' + reply.get('model', args.model) if hosted else 'local'}"
    if "money_risk" in reply.get("answers", {}):
        ans["money_risk"] = reply["answers"]["money_risk"].get("noul", 0.0)
    ans["tokens"] = reply.get("usage", {}).get("input_tokens", 0)
    if VERBOSE:
        size = len(json.dumps(body["state"]))
        print(f"{CYAN}  JEV  {ans['backend']} at {url} ({size} chars of state, {ans['tokens']} input tokens){RESET}")
        if hosted:
            print(f"{CYAN}       state:{RESET} goal, city, plan ({len(state['plan']['materials'])} material lines), "
                  f"{len(state['warnings'])} warnings, {len(state['recent_decisions'])} recent decisions, "
                  f"facts of {len(state['options'])} options")
        else:
            print(f"{CYAN}       city:{RESET} {body['state']['city'][:300]}...")
        print(f"{CYAN}       question:{RESET} {body['questions']['action']['instructions']}")
        for k, v in opts.items():
            p = ans.get("probabilities", {}).get(k, 0.0)
            bar = "#" * int(p * 30)
            mark = f"{GREEN}<- choice{RESET}" if k == ans["choice"] else ""
            print(f"{YELLOW}       {p:5.0%} {bar:30s}{RESET} {k}: {v['desc'][:80]} {mark}")
        if "money_risk" in ans:
            print(f"{CYAN}       money_risk (yes/no):{RESET} {ans['money_risk']:.0%}")
        print(f"{CYAN}       answer in {time.time() - t0:.2f}s, confidence {ans.get('confidence', 0):.2f}{RESET}",
              flush=True)
    return ans


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="tev1:0.8b")
    # 127.0.0.1, not localhost: Windows tries IPv6 ::1 first, Ollama listens on IPv4 only, and each
    # request waited 2 s for the fallback (Jev itself answers in 0.01-0.03 s on the GPU).
    ap.add_argument("--url", default="http://127.0.0.1:11434/v1/systemone")
    ap.add_argument("--island", default="10",
                    help="the home island, or 'auto': a new game's first Kontor where the start ship lies")
    ap.add_argument("--cx", type=int, default=27, help="town centre x for site searches")
    ap.add_argument("--cy", type=int, default=26)
    ap.add_argument("--radius", type=int, default=12)
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--speed", type=int, default=8, help="game speed to keep (the game drops to x1 on events)")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dry", action="store_true", help="decide but do not act")
    ap.add_argument("--verbose", action="store_true", help="show every game query and every Jev request")
    ap.add_argument("--hosted", action="store_true",
                    help="ask TypeSafe's hosted Jev (api.typesafe.ai, key in TYPESAFE_API_KEY) with the full picture; "
                         "the local model stays the fallback")
    ap.add_argument("--max-calls-per-min", type=int, default=10, help="cost cap for hosted calls")
    ap.add_argument("--min-confidence", type=float, default=0.0)
    ap.add_argument("--grow", default="", help="islands to grow into second main towns, e.g. 18")
    ap.add_argument("--produce", default="", help="production colonies kept at 12 houses, e.g. 4,11")
    ap.add_argument("--port", type=int, default=0,
                    help="the game's control port (default: O1602_CONTROL_PORT, else 7602); two games on "
                         "one computer, e.g. a multiplayer game of two agents, listen on different ports")
    ap.add_argument("--restart-on-change", action="store_true",
                    help="end (code 3) when jev_driver.py or strategy.py changes, for a runner that starts it again")
    ap.add_argument("--state-dir", default="",
                    help="where the log, castle.json, key_buildings.json, reviews.md and reflection.txt "
                         "live (default: tools/agent); another game, such as a test, keeps its own")
    args = ap.parse_args()
    if args.port:
        os.environ["O1602_CONTROL_PORT"] = str(args.port)  # o1602-ctl reads it (every ctl() call)
    global VERBOSE, LOG, REVIEWS, REFLECTION, KEY_FILE, CASTLE_FILE
    if args.state_dir:
        d = Path(args.state_dir)
        d.mkdir(parents=True, exist_ok=True)
        LOG, REVIEWS, REFLECTION = d / "jev_log.jsonl", d / "reviews.md", d / "reflection.txt"
        KEY_FILE, CASTLE_FILE = d / "key_buildings.json", d / "castle.json"
        KNOWN_KEY.clear()  # those of tools/agent were read at the start: another game's
        try:
            KNOWN_KEY.update({int(i): {tuple(e) for e in v}
                              for i, v in json.loads(KEY_FILE.read_text(encoding="utf-8")).items()})
        except (OSError, ValueError):
            pass
        NO_FORESTER.clear()  # island numbers of the weekend game: another world's are others
    if str(args.island) == "auto":
        home = opening()
        while home is None:
            print("  opening: no city yet and none founded; again in 15 s", flush=True)
            time.sleep(15)
            home = opening()
        args.island, args.cx, args.cy = home
        print(f"  opening: home island {args.island}, Kontor at {args.cx},{args.cy}", flush=True)
    else:
        args.island = int(args.island)
    VERBOSE = args.verbose
    if VERBOSE:
        os.system("")  # turns on ANSI colours in the Windows console
    if args.hosted and "127.0.0.1" in args.url:
        args.url = "https://api.typesafe.ai/v1/systemone"
        args.model = "jev-latest" if args.model == LOCAL_MODEL else args.model
    ctl("say", "clear")  # old lines from an earlier run (e.g. "Jev lokal") off the screen
    ctl("say", f"Agent startet: {'Jev hosted (TypeSafe ' + args.model + ')' if args.hosted else 'Jev lokal'}")

    buildings = read_buildings()
    LIVE_ISLANDS[:] = [args.island]
    GROW.update(int(g) for g in args.grow.split(",") if g.strip())
    MAIN_TOWNS.update(GROW | {args.island})
    PRODUCE.update(int(g) for g in args.produce.split(",") if g.strip())
    _, isl_out = ctl("islands")
    n_islands = int(m[1]) if (m := re.search(r"(\d+) islands", isl_out)) else 64
    for isl in range(n_islands):  # colonies founded before this run (an own Kontor there)
        if isl != args.island and kontor_pos(isl) and isl not in LIVE_ISLANDS:
            LIVE_ISLANDS.append(isl)
    print("islands:", LIVE_ISLANDS, flush=True)
    # The long-term plan for the home island's crops (full fertility first, half as fallback).
    m = re.search(rf"island {args.island}:.*crops: ([^;]*?);", isl_out)
    crops = [c.strip() for c in m[1].split()] if m else ["grain"]
    full = [c for c in crops if "(" not in c]
    half = [c.split("(")[0] for c in crops if "(half)" in c]
    strategy.setup(full, half, food="fish")
    print(f"plan for crops {full} (half {half}): {len(strategy._PLANS)} stages", flush=True)
    # A standing trade route brings a colony's wood home (user: "why no trade route for the surplus
    # wood of the upper island?"). The ship runs it between supply runs.
    # Its cargo follows what the colony has to spare and home lacks (critic), see update_route().
    routed = update_route(args.island, LIVE_ISLANDS[1:])
    if routed:
        print(f"trade route: {routed}", flush=True)
    else:
        # A restart in the middle of a supply run leaves the route stopped (review: ship 1 stood still
        # and home ran out of food): start whatever route the ship has.
        ship0 = my_ship()
        if ship0 is not None:
            ctl("route", ship0["id"], "start")
    shown_plan = ""
    last_tools_buy = -1
    n = 0
    own_code = {p: p.stat().st_mtime for p in (Path(__file__), Path(strategy.__file__)) if p.exists()}
    while True:
        # A coach changed this driver or its plan (tournament: the runner starts it again at once).
        if args.restart_on_change and any(p.stat().st_mtime != t for p, t in own_code.items() if p.exists()):
            print(f"{YELLOW}  the driver's code changed: ending, the runner starts the new one{RESET}", flush=True)
            return 3
        n += 1
        t0 = time.time()
        CACHE.clear()  # every round reads the game afresh (the game went on meanwhile)
        tick_game_clock()
        # Round robin over the own islands: the home island every other turn, colonies in between.
        a = argparse.Namespace(**vars(args))
        if len(LIVE_ISLANDS) > 1 and n % 2 == 0:
            # A second main town gets every other colony turn (user: Essix as the new main island);
            # the other colonies take turns on a counter of their own (review: with the old formula
            # the Essix turns fell exactly on the turns of islands 4 and 11, which never came up).
            grow = [g for g in GROW if g in LIVE_ISLANDS]
            others = [c for c in LIVE_ISLANDS[1:] if c not in GROW]
            if grow and (n % 4 == 2 or not others):
                a.island = grow[(n // 4) % len(grow)]
            else:
                COLONY_TURN[0] += 1
                a.island = others[COLONY_TURN[0] % len(others)]
            a.cx, a.cy = kontor_pos(a.island) or (args.cx, args.cy)
            a.radius = 14 if a.island in GROW else 10
        if VERBOSE:
            print(f"\n{GREEN}=== Decision #{n}, island {a.island} " + "=" * 60 + RESET, flush=True)
        update_pier_bricks(a.island)
        # Burnt key buildings first, every round (a market's area is lost soon after it burns).
        for fix in rebuild_burnt(a.island):
            print(f"{YELLOW}  rebuild: {fix}{RESET}", flush=True)
            ctl("say", f"Brand: {fix[:70]}")
        # The game's warnings first (question marks, missing roads, full storage): fixed before the
        # model chooses, the rest goes to the model as part of the state.
        if n % 2 == 1 or a.island != args.island:
            for fix in handle_alerts(a.island, buildings):
                print("  alert:", fix, flush=True)
                ctl("say", f"Warnung behoben: {fix[:70]}")
        # A colony that waits for goods from home (bricks for piers, wood, tools): the ship brings
        # them, in the background. Not a choice for the model: without it nothing there moves.
        if a.island != args.island and not SHIP_BUSY["on"]:
            loads = colony_needs(a.island, args.island, buildings)
            if loads:
                msg = supply_run(args.island, a.island, loads)
                print(f"  supply: {msg}", flush=True)
            elif a.island not in GROW:  # a second main town keeps its materials (Essix sent 120 t wood home)
                # The other way: what lies idle in a full colony store goes home where it is short
                # (review: 30 t of wood filled the colony while home had 17 t and built nothing).
                there, here = read_state(a.island)["stock"], s_home_stock(args.island)
                # The colony keeps 25 t for its own farms (Kap Crus sat at 0 t wood with 30 t tools
                # and could build no plantation).
                back = [(w, int(there.get(w, 0)) - 25) for w in ("wood", "bricks")
                        if there.get(w, 0) >= 45 and here.get(w, 0) < 30]
                if back:
                    msg = supply_run(a.island, args.island, back)
                    print(f"  supply home: {msg}", flush=True)
        if n % 2 == 0:
            for a_msg in arm_ships():
                print(f"  arm: {a_msg}", flush=True)
        if n % 3 == 0 and not SHIP_BUSY["on"]:
            msg = distribute_weapons()
            if msg:
                print(f"  weapons: {msg}", flush=True)
        if n % 5 == 0:
            for fix in repair(a.island):
                print("  repair:", fix, flush=True)
                ctl("say", f"Reparatur: {fix[:70]}")
            # Treaties the computer players offer are accepted (user: trade treaties with them, then
            # supply them to earn money; all three offered one and waited).
            if a.island == args.island:
                _, dip = ctl("diplomacy")
                for m_d in re.finditer(r"^\s+(\d+): [^,]+, computer, peace ([^,]+), trade ([^,]+),", dip, re.M):
                    for kind, state in (("peace", m_d[2]), ("trade", m_d[3])):
                        if state.startswith("they offer"):
                            ctl("diplomacy", m_d[1], kind, "accept")
                            ctl("say", f"{kind} treaty with player {m_d[1]} accepted")
            if a.island == args.island:
                for d in defend(args.island, s.get("money", 0)):
                    print("  defence:", d, flush=True)
                    ctl("say", f"Verteidigung: {d[:70]}")
                shipped = order_ships(args.island, s.get("money", 0))
                if shipped:
                    print("  ships:", shipped, flush=True)
                    ctl("say", shipped[:90])
            upgraded = upgrade_kontor(a.island, buildings)
            if upgraded:
                print("  kontor:", upgraded, flush=True)
                ctl("say", upgraded)
            for fix in relieve_full_stores(a.island):
                print("  store:", fix, flush=True)
            for fix in free_enclosed_hubs(a.island):
                print("  market:", fix, flush=True)
                ctl("say", f"Markt freigelegt: {fix[:70]}")
            ruins = clear_ruins(a.island)
            if ruins:
                print("  ruins:", ruins, flush=True)
            if a.island == args.island:
                routed = update_route(args.island, LIVE_ISLANDS[1:])
                if routed:
                    print("  route:", routed, flush=True)
                    ctl("say", f"Handelsroute: {routed[:70]}")
            # Fire brigade and doctor walk roads: link road pieces with unreached houses, a second
            # station for houses beyond the radius (user: else the fire station is useless).
            if a.island == args.island:
                for service in ("fire_station", "doctor"):
                    for fix in fix_service_gaps(a.island, service, buildings):
                        print("  service:", fix, flush=True)
                        ctl("say", f"Feuerwehr/Arzt: {fix[:70]}")
            # Fields and forest for producers below full speed (user: 100% efficiency).
            for fix in efficiency_fixes(a.island, buildings):
                print("  efficiency:", fix, flush=True)
                ctl("say", f"Effizienz: {fix[:70]}")
        if n % 3 == 1:
            grid = island_map(a.island)
            for b in isolated(a.island, grid, buildings)[:4]:
                fix = connect(a.island, grid, *b)
                print("  network:", fix, flush=True)
                ctl("say", f"Netz: {fix[:70]}")
                grid = island_map(a.island)
        s = read_state(a.island)
        # The game drops to x1 on fires, plague and attacks; back to full speed once no fire burns.
        st_line = ctl("state")[1]
        chat_round(st_line)  # a multiplayer game: what the other agent wrote, and treaties asked for
        # The stream must never stand still (user): a paused game goes on at once (review: found it
        # paused at 13:40 with nobody waiting on it).
        if re.search(r"^time \S+\s+paused", st_line, re.M):
            ctl("resume")
            ctl("speed", args.speed)
            print(f"{YELLOW}  the game was paused: resumed{RESET}", flush=True)
        # War first, every round and before the model (user: Jev must decide fast when it comes):
        # fixed answers to soldiers on our islands and armed ships near them; the game slows to x2
        # while it lasts so the answers keep up.
        for w_msg in war_response():
            print(f"{YELLOW}  war: {w_msg}{RESET}", flush=True)
            ctl("say", f"Krieg: {w_msg[:80]}")
        speed_m = re.search(r"speed x(\d+)", st_line)
        if speed_m and int(speed_m[1]) < args.speed and not WAR["on"] \
                and not any(t == "FIRE" for t, _ in alerts(a.island)):
            ctl("speed", args.speed)
        s["alerts"] = [f"[{t}] {x}" for t, x in alerts(a.island)][:15]
        runout = runout_warnings(a.island, s)
        if runout:
            s["alerts"] = runout + s["alerts"]  # first in what the model reads
            for w in runout:
                print(f"{YELLOW}  {w}{RESET}", flush=True)
            ctl("say", runout[0][:90])
        taxed = tune_taxes(a.island, s)
        # High priority (user): both main towns at the tax edge every round, not only on their turn.
        for isl_m in MAIN_TOWNS - {a.island}:
            more = tune_taxes(isl_m, read_state(isl_m))
            if more:
                taxed = f"{taxed}; {more}" if taxed else more
        if taxed:
            print(f"  tax: {taxed}", flush=True)
            ctl("say", f"Steuer: {taxed}")
        if a.island == args.island:  # the plan is for the home town; colonies follow the rules
            pop = {c: v["people"] for c, v in s["classes"].items()}
            stage, gaps = strategy.current(pop, counts(a.island), sum(s.get("houses", [0])))
            s["gaps"], s["stage"] = gaps, stage.stage.name
            s["plan"] = strategy.summary(stage, gaps)
            who_line = (f"Entscheider: Jev hosted (TypeSafe {args.model}), {HOSTED_TOTAL[0]} Aufrufe"
                        if args.hosted else f"Entscheider: Jev lokal ({args.model})")
            refl = reflection_line()
            steps = ([refl] if refl else []) + [rate_line(), who_line, f"Stufe {stage.stage.name}: {stage.stage.goal}",
                     "fehlt: " + (", ".join(f"{v} {k}" for k, v in sorted(gaps.items())) or "nichts")]
            steps += strategy.gozinto(stage)
            s["gozinto"] = strategy.gozinto(stage)
            # Building materials: need (this stage + half the next), stock, own output, what to do.
            need = strategy.material_need(stage, gaps, pop)
            # No target above what the Kontor holds (critic: 130 t of bricks wanted, 80 t of room,
            # "more stonemasons" while the store stood full).
            _, ctext0 = ctl("cities", a.island, 0)
            room0 = int(mm[1]) if (mm := re.search(r"room (\d+) t", ctext0)) else 60
            for mat in strategy.MATERIALS:
                need[mat] = min(need[mat], room0)
            rows = strategy.material_plan(need, s["stock"], counts(a.island), set())
            s["material_rows"] = rows
            s["materials"] = strategy.material_lines(rows)
            steps += ["Material: " + line for line in s["materials"]]
            s["efficiency"] = efficiency_report(a.island)  # below 80% and why, for viewers and the model
            steps += ["Effizienz: " + line for line in s["efficiency"][:5]]
            steps = [w for w in s["alerts"] if w.startswith("[RUNOUT]")] + steps  # on top, for viewers
            # Tools come from traders until the toolmaker chain stands: the Kontor buys what is
            # missing, as far as its storage goes (one obvious answer, not a choice for the model).
            tools_row = next(r for r in rows if r["material"] == "tools")
            _, ctext = ctl("cities", a.island, 0)
            room = int(m[1]) if (m := re.search(r"room (\d+) t", ctext)) else 30
            # Tools at 75 a ton: keep a working stock of 25 t, not the plan's whole need (review: the
            # Kontor bought up to 54 t while 34 t lay there, and the balance went negative).
            want_tools = 25 if tools_row["short"] > 0 and s.get("money", 0) > 1500 else 0
            if s["stock"].get("tools", 0) < 10 and s.get("money", 0) > 300:
                want_tools = max(want_tools, 15)  # without tools nothing can be built, not even a fire station
            # Below 1500 gold the Kontor buys nothing else either (alcohol at 60 a ton drained it).
            if s.get("money", 0) < 1500 and "alcohol" in s.get("buying", ()):
                ctl("trade", a.island, 0, "alcohol", "none")
            if want_tools != last_tools_buy:
                ctl("trade", a.island, 0, "tools", "buy" if want_tools else "none", *([want_tools, 75] if want_tools else []))
                last_tools_buy = want_tools
            text = " | ".join(steps)
            if text != shown_plan:  # over the map for the viewers, only when it changes
                ctl("plan", text)
                shown_plan = text
            if VERBOSE:
                print(f"{YELLOW}  PLAN {s['plan']}{RESET}")
                for line in strategy.gozinto(stage):
                    print(f"{YELLOW}       {line}{RESET}")
                for line in s["materials"]:
                    print(f"{YELLOW}       material: {line}{RESET}")
        opts = options(s, buildings, a)
        # Only one legal action: nothing to decide, no need to ask the model.
        ans = decide(s, opts, a, buildings) if len(opts) > 1 else \
            {"choice": next(iter(opts)), "confidence": 1.0, "probabilities": {next(iter(opts)): 1.0},
             "backend": "rule"}
        stat(ans.get("backend", "local").split()[0])  # rule, local or hosted
        # The hosted model's money judgement: a high risk stops all buying at the Kontor.
        if ans.get("money_risk", 0.0) > 0.7:
            for w in s.get("buying", ()):
                ctl("trade", a.island, 0, w, "none")
            last_tools_buy = 0
            print(f"{YELLOW}  money_risk {ans['money_risk']:.0%}: the Kontor stops buying{RESET}", flush=True)
        pick = ans["choice"]
        conf = ans.get("confidence", 0.0)
        result = "dry run" if args.dry else "low confidence: skipped"
        if not args.dry and conf >= args.min_confidence:
            result = run(opts[pick]["cmd"], a)
            # Any failed option rests 10 minutes (review: "pave" was picked four times in a row and
            # refused each time while 51 houses waited for the chapel that was also offered).
            if "no place" in result or "no quarter fits" in result or result.startswith("error") \
                    or ("built 0 of" in result and "built 1" not in result and "built 2" not in result):
                FAILED_AT[pick] = time.time()
        prob = ans.get("probabilities", {}).get(pick, 0.0)
        who = {"rule": "Regel", "local": "Jev lokal"}.get(ans.get("backend", "local"), "Jev (TypeSafe)")
        # Waiting is no action to show (user): the one line at the top goes away instead.
        if pick == "wait" or opts.get(pick, {}).get("cmd") is None:
            ctl("say", "idle")
        else:
            ctl("say", f"{who}: {pick} ({prob:.0%}) - {result[:60]}")
            chat_say(f"{pick} - {result.splitlines()[0][:80] if result else ''}")
        HISTORY.append({"island": a.island, "action": pick, "result": result[:120], "money": s.get("money"),
                        "balance": s.get("balance")})
        del HISTORY[:-12]
        line = (f"#{n} money {s.get('money')} bal {s.get('balance')} | {len(opts)} options -> {pick} "
                f"p={prob:.2f} conf={conf:.2f} | {result} | {time.time() - t0:.1f}s")
        print(line, flush=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "state": s, "options": {k: v["desc"] for k, v in opts.items()},
                                "answer": ans, "result": result}) + "\n")
        if args.once:
            return 0
        if n % 20 == 0:
            buildings = read_buildings()  # unlocks change
        time.sleep(max(0.0, args.interval - (time.time() - t0)))


if __name__ == "__main__":
    sys.exit(main())
