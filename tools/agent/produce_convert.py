"""Turns part of a built-up colony into farmland: picks the spot where a 2x2 producer with its
6x6 field window fits on houses, own land and forest (most field room, next to a market's reach),
pulls the houses and trees there down, builds the producer, plants its fields and links it by road.
Usage: python produce_convert.py ISLAND BUILDING FIELD COUNT  (e.g. 2 winery vines 2)"""
import sys

sys.path.insert(0, ".")
import jev_driver as j  # noqa: E402

FREE = (":", "T", "H", ".")


def best_spot(island: int):
    g = j.island_map(island)
    best = None
    for (x, y) in list(g):
        foot = [(x + a, y + b) for a in (0, 1) for b in (0, 1)]
        if not all(g.get(t) in FREE for t in foot) or not j.near_market(g, x, y):
            continue
        win = [(x + a, y + b) for a in range(-2, 4) for b in range(-2, 4) if not (0 <= a <= 1 and 0 <= b <= 1)]
        room = sum(1 for t in win if g.get(t) in FREE)
        houses = sum(1 for t in win + foot if g.get(t) == "H")
        side = [(x - 1, y), (x - 1, y + 1), (x + 2, y), (x + 2, y + 1), (x, y - 1), (x + 1, y - 1), (x, y + 2), (x + 1, y + 2)]
        road = any(g.get(t) in j.ROAD for t in side)
        score = (room, road, -houses)
        if room >= 16 and (best is None or score > best[0]):
            best = (score, x, y, win, foot)
    return best


CROP = {"tobacco_plantation": "tobacco", "winery": "wine", "sugarcane_plantation": "sugar",
        "cotton_plantation": "cotton", "cocoa_plantation": "cocoa", "spice_plantation": "spices",
        "grain_farm": "grain"}


def crop_full(island: int, building: str) -> bool:
    """The crop grows on the whole island, not only on some tiles (Alsdorf, tobacco 'half': 8
    houses came down for two plantations that got one field each)."""
    crop = CROP.get(building)
    if crop is None:
        return True
    _, out = j.ctl("islands")
    line = next((ln for ln in out.splitlines() if ln.strip().startswith(f"island {island}:")), "")
    return f" {crop} " in line.replace(";", " ").replace(",", " ") + " " and f"{crop}(half)" not in line


def convert(island: int, building: str, field: str) -> str:
    if not crop_full(island, building):
        return f"{building}: its crop grows only on some tiles of island {island} - nothing pulled down"
    spot = best_spot(island)
    if spot is None:
        return "no spot with 16 field tiles"
    (room, road, nh), x, y, win, foot = spot
    # Materials first: on Kap Crus four houses came down and then the plantation was refused for
    # want of bricks.
    bl = j.read_buildings()
    if building not in bl or not j.affordable(bl[building], j.read_state(island)):
        return f"{building}: not affordable on island {island} now (gold/tools/wood/bricks) - nothing pulled down"
    g = j.island_map(island)
    hs = j.house_origins(g)
    area = set(win) | set(foot)
    gone = {(hx, hy) for hx, hy in hs if any((hx + a, hy + b) in area for a in (0, 1) for b in (0, 1))}
    for hx, hy in gone:
        j.ctl("demolish", island, hx, hy)
    for t in area:
        if g.get(t) == "T":
            j.ctl("demolish", island, *t)
    code, out = j.ctl("build", building, island, x, y, 0)
    res = out.strip().splitlines()[-1] if out.strip() else str(code)
    if code != 0:
        return f"{building} at {x},{y} refused: {res}"
    _, fo = j.ctl("build-many", field, island, x - 2, y - 2, x + 3, y + 3)
    link = j.connect(island, j.island_map(island), building, x, y, 2, 2)
    if "no way" in link:
        # Cut off (Durtmond: a winery on the separate islet, twice): no cart would ever come.
        j.ctl("demolish", island, x, y)
        return f"{building} at {x},{y}: no road to a market possible - pulled down again"
    j.ctl("fix-roads", island)
    j.ctl("say", f"Produktionsinsel {island}: {building} bei {x},{y}, {len(gone)} Haeuser weichen Feldern")
    return f"{building} at {x},{y}: {len(gone)} houses down, {fo.strip()[:60]}; {link}"


if __name__ == "__main__":
    isl, b, f, n = int(sys.argv[1]), sys.argv[2], sys.argv[3], int(sys.argv[4])
    j.update_pier_bricks(isl)
    for _ in range(n):
        print(convert(isl, b, f))
