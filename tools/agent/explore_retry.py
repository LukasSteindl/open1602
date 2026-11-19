"""Explores islands the first round refused: the ship must stand still INSIDE the island's
rectangle (Fleet::island_at_ship), so it tries the four rectangle corners (usually sea) until
'explore' is accepted. Usage: python explore_retry.py SHIP ISL ISL ..."""
import re
import sys
import time

sys.path.insert(0, ".")
import jev_driver as j  # noqa: E402


def rect(island: int) -> tuple[int, int, int, int]:
    _, out = j.ctl("islands")
    m = re.search(rf"island {island}: world (\d+),(\d+) size (\d+)x(\d+)", out)
    return int(m[1]), int(m[2]), int(m[3]), int(m[4])


def main() -> None:
    ship = int(sys.argv[1])
    j.ctl("route", ship, "stop")
    for isl in (int(a) for a in sys.argv[2:]):
        x, y, w, h = rect(isl)
        done = False
        for cx, cy in ((x + 1, y + 1), (x + w - 2, y + 1), (x + 1, y + h - 2), (x + w - 2, y + h - 2)):
            j.sail_to(ship, cx, cy, timeout=400)
            time.sleep(3)  # stand still
            _, out = j.ctl("explore", ship)
            print(isl, (cx, cy), out.strip(), flush=True)
            if out.startswith("exploring"):
                time.sleep(45)
                done = True
                break
        if not done:
            print(isl, "no corner accepted (explored already or no sea inside)", flush=True)
    _, out = j.ctl("islands")
    for line in out.splitlines():
        if "deposits" in line:
            print(line.strip(), flush=True)


if __name__ == "__main__":
    main()
