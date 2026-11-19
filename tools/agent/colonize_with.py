"""Founds a colony with a given ship (not the driver's ship 1, which runs the trade route).
Usage: python colonize_with.py SHIP TARGET_ISLAND HOME_ISLAND"""
import re
import sys

sys.path.insert(0, ".")
import jev_driver as j  # noqa: E402


def main() -> None:
    ship_id, target, home = (int(a) for a in sys.argv[1:4])

    def ship() -> dict | None:
        _, out = j.ctl("ships")
        m = re.search(rf"ship {ship_id} \"[^\"]*\" figure \d+ at world (\d+),(\d+) (\w+)", out)
        return {"id": ship_id, "x": int(m[1]), "y": int(m[2]), "idle": m[3] == "idle"} if m else None

    j.my_ship = ship
    # The ship first goes home to load (it may lie elsewhere).
    print("home", j.sail_to(ship_id, *j.world_kontor(home), timeout=300))
    print(j.colonize(target, home))


if __name__ == "__main__":
    main()
