"""Waits until the given ships lie at the Kontor of ISLAND, then boards the given units onto them,
one ship after the other, until all are aboard or the time is up.
Usage: python board_when_docked.py ISLAND SHIPS(comma) UNITS(comma) [MINUTES]"""
import re
import sys
import time

sys.path.insert(0, ".")
import jev_driver as j  # noqa: E402


def main() -> None:
    isl = int(sys.argv[1])
    ships = [int(s) for s in sys.argv[2].split(",")]
    units = [int(u) for u in sys.argv[3].split(",")]
    minutes = float(sys.argv[4]) if len(sys.argv) > 4 else 10
    t0 = time.time()
    while time.time() - t0 < minutes * 60:
        _, u_out = j.ctl("units")
        left = [u for u in units if re.search(rf"unit {u} figure", u_out)]
        if not left:
            break
        _, s_out = j.ctl("ships")
        for s in ships:
            block = s_out.split(f"ship {s} ")[1].split("\nship ")[0] if f"ship {s} " in s_out else ""
            free = block.count("(") and int(re.search(r"\((\d+) holds\)", block)[1]) - len(re.findall(r" \d+\.\d t;", block))
            if f"Kontor of island {isl}" in block and free and free > 0:
                print(s, left[:free], j.ctl("board", s, *left[:free])[1].strip(), flush=True)
                break
        time.sleep(10)
    _, s_out = j.ctl("ships")
    for s in ships:
        i = s_out.find(f"ship {s} ")
        print(s_out[i:i + 260], flush=True)


if __name__ == "__main__":
    main()
