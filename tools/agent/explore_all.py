"""Sends one ship round the given islands and explores each (crops, ore and gold deposits), then
prints the deposits the 'islands' listing knows. Usage: python explore_all.py SHIP ISL ISL ..."""
import re
import sys
import time

sys.path.insert(0, ".")
import jev_driver as j  # noqa: E402


def island_centre(island: int) -> tuple[int, int]:
    _, out = j.ctl("islands")
    m = re.search(rf"island {island}: world (\d+),(\d+) size (\d+)x(\d+)", out)
    k = j.world_kontor(island)
    if k:
        return k
    return int(m[1]) + int(m[3]) // 2, int(m[2]) + int(m[4]) // 2


def main() -> None:
    ship = int(sys.argv[1])
    j.ctl("route", ship, "stop")
    for isl in (int(a) for a in sys.argv[2:]):
        wx, wy = island_centre(isl)
        print(isl, "sail", j.sail_to(ship, wx, wy, timeout=400), flush=True)
        _, out = j.ctl("explore", ship)
        print(isl, out.strip(), flush=True)
        if out.startswith("exploring"):
            time.sleep(40)  # the steps take about a minute of game time at x8
    _, out = j.ctl("islands")
    for line in out.splitlines():
        if "deposits" in line:
            print(line.strip(), flush=True)


if __name__ == "__main__":
    main()
