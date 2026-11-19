"""Walls an island in (user: wall the islands in, with castle walls and defence towers): a wall on
every beach tile beside own land, except beside the Kontor, piers and the shipyard (the harbour
stays open); a watchtower every 10 walls while cannons and bricks last. Stops at 10 t of bricks.
Usage: python wall_island.py ISLAND [ISLAND ...]"""
import sys

sys.path.insert(0, ".")
import jev_driver as j  # noqa: E402

OWN = set(":=+#") | set("HMKBCESLFW") | set("T")
HARBOUR = set("KpS")
N8 = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0)]


def stock(island: int) -> dict:
    return j.read_state(island)["stock"]


def wall(island: int) -> str:
    g = j.island_map(island)
    beach = [(x, y) for (x, y), v in g.items() if v == "b"
             and any(g.get((x + dx, y + dy)) in OWN for dx, dy in N8)
             and not any(g.get((x + dx, y + dy)) in HARBOUR for dx in range(-2, 3) for dy in range(-2, 3))
             and any(g.get((x + dx, y + dy)) == "~" for dx, dy in N8)]
    walls = towers = 0
    for n, (x, y) in enumerate(sorted(beach)):
        st = stock(island) if n % 10 == 0 else st
        if st.get("bricks", 0) < 10:
            break
        if n % 10 == 5 and st.get("cannons", 0) >= 2 and st.get("bricks", 0) >= 16:
            code, out = j.ctl("build", "watchtower", island, x, y)
            if "built 1" in out:
                towers += 1
                continue
        code, out = j.ctl("build", "wall", island, x, y)
        if "built 1" in out:
            walls += 1
    return f"island {island}: {walls} walls, {towers} towers on {len(beach)} beach tiles"


def main() -> None:
    for isl in (int(a) for a in sys.argv[1:]):
        print(wall(isl), flush=True)


if __name__ == "__main__":
    main()
