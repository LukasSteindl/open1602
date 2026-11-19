"""Brings ships to a Kontor with cannons, loads as many as they can mount and mounts them.
Usage: python arm_fleet.py ISLAND SHIP [SHIP ...]"""
import sys
import threading

sys.path.insert(0, ".")
import jev_driver as j  # noqa: E402


def arm(island: int, ship: int) -> None:
    j.ctl("route", ship, "stop")
    k = j.world_kontor(island)
    print(ship, "sail", j.sail_to(ship, *k, timeout=500), flush=True)
    for _ in range(4):  # a hold takes up to 50 t; mount what fits, load again
        print(ship, j.ctl("load", ship, "cannons", 10)[1].strip(), flush=True)
        print(ship, j.ctl("arm", ship)[1].strip(), flush=True)


def main() -> None:
    island = int(sys.argv[1])
    ts = [threading.Thread(target=arm, args=(island, int(s))) for s in sys.argv[2:]]
    for t in ts:
        t.start()
    for t in ts:
        t.join()


if __name__ == "__main__":
    main()
