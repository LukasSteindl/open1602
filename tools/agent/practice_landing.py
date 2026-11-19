"""Landing drill on an own island: the ship sails to a sea tile, lands its soldiers, waits, takes
them aboard again. Usage: python practice_landing.py SHIP ISLAND WX WY"""
import re
import sys
import time

sys.path.insert(0, ".")
import jev_driver as j  # noqa: E402


def ship_state(ship: int) -> tuple[bool, str]:
    _, o = j.ctl("ships")
    m = re.search(rf"^ship {ship} \"[^\"]*\" figure \d+ at world (\d+),(\d+) (\w+)[^\n]*\n((?:  [^\n]*\n)*)", o, re.M)
    return (m[3] == "idle", m[0]) if m else (False, "")


def sail(ship: int, wx: int, wy: int) -> bool:
    for r in range(0, 6):
        for dx, dy in ((-r, 0), (r, 0), (0, -r), (0, r)):
            if j.ctl("ship-move", ship, wx + dx, wy + dy)[0] == 0:
                time.sleep(4)
                for _ in range(120):
                    idle, _ = ship_state(ship)
                    if idle:
                        return True
                    time.sleep(3)
                return False
    return False


def on_island(isl: int) -> list[int]:
    _, out = j.ctl("units")
    return [int(m[1]) for m in re.finditer(rf"unit (\d+) figure \d+ island {isl} ", out)]


def main() -> None:
    ship, isl, wx, wy = (int(a) for a in sys.argv[1:5])
    j.ctl("say", f"Uebung: Landung auf Insel {isl}")
    print("sail", sail(ship, wx, wy), flush=True)
    print(ship_state(ship)[1], flush=True)
    before = set(on_island(isl))
    print("land", j.ctl("units-land", ship)[1].strip(), flush=True)
    time.sleep(8)
    landed = [u for u in on_island(isl) if u not in before]
    print("landed", landed, flush=True)
    j.ctl("say", f"Uebung: {len(landed)} Einheiten an Land auf Insel {isl}")
    time.sleep(20)
    if landed:
        for _ in range(12):
            print("board", j.ctl("board", ship, *landed)[1].strip(), flush=True)
            time.sleep(8)
            if not [u for u in on_island(isl) if u in landed]:
                break
    print(ship_state(ship)[1], flush=True)
    j.ctl("say", "Uebung beendet: Truppen wieder an Bord" if not [u for u in on_island(isl) if u in landed]
          else "Uebung: nicht alle wieder an Bord")


if __name__ == "__main__":
    main()
