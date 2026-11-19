"""Gathers the land units of an island onto a ship lying at its Kontor: idle units walk to the
harbour, then board; repeats until all are aboard or the time is up.
Usage: python embark.py ISLAND SHIP HX HY [MINUTES]   (HX HY: a land tile by the harbour)"""
import re
import sys
import time

sys.path.insert(0, ".")
import jev_driver as j  # noqa: E402


def units_on(island: int) -> list[tuple[int, int, int, bool]]:
    _, out = j.ctl("units")
    return [(int(m[1]), int(m[3]), int(m[4]), bool(m[5]))
            for m in re.finditer(rf"unit (\d+) figure \d+ island ({island}) at (\d+),(\d+) health \d+( \(on the move\))?", out)]


def main() -> None:
    isl, ship, hx, hy = (int(a) for a in sys.argv[1:5])
    minutes = float(sys.argv[5]) if len(sys.argv) > 5 else 6
    t0 = time.time()
    while time.time() - t0 < minutes * 60:
        us = units_on(isl)
        if not us:
            break
        near = [u for u, x, y, moving in us if abs(x - hx) <= 4 and abs(y - hy) <= 4]
        far_idle = [u for u, x, y, moving in us if not moving and u not in near]
        if near:
            print("board", near, j.ctl("board", ship, *near)[1].strip(), flush=True)
        if far_idle:
            print("go", far_idle, j.ctl("units-go", isl, hx, hy, *far_idle)[1].strip(), flush=True)
        time.sleep(10)
    _, o = j.ctl("ships")
    i = o.find(f"ship {ship} ")
    print(o[i:i + 300], flush=True)
    print("left on land:", units_on(isl), flush=True)


if __name__ == "__main__":
    main()
