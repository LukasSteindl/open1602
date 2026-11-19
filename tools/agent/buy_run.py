"""Buys goods at a foreign Kontor (trade treaty needed) and brings them home, then restarts the
trade route. Usage: python buy_run.py FOREIGN_ISLAND HOME_ISLAND "cloth 40,spices 20" """
import re
import sys

sys.path.insert(0, ".")
import jev_driver as j  # noqa: E402


def foreign_kontor_world(island: int) -> tuple[int, int]:
    _, out = j.ctl("islands")
    m = re.search(rf"island {island}: world (\d+),(\d+)", out)
    _, c = j.ctl("cities", island, 0)
    k = re.search(r"Kontor at (\d+),(\d+)", c)
    return int(m[1]) + int(k[1]), int(m[2]) + int(k[2])


def main() -> None:
    far, home = int(sys.argv[1]), int(sys.argv[2])
    goods = [(p.split()[0], int(p.split()[1])) for p in sys.argv[3].split(",")]
    ship = j.my_ship()
    j.ctl("route", ship["id"], "stop")
    j.ctl("say", f"Einkaufsfahrt nach Insel {far}: {sys.argv[3]}")
    print("to", far, j.sail_to(ship["id"], *foreign_kontor_world(far), timeout=300))
    for w, t in goods:
        print(j.ctl("load", ship["id"], w, t)[1].strip())
    print("home", j.sail_to(ship["id"], *j.world_kontor(home), timeout=300))
    for w, t in goods:
        print(j.ctl("unload", ship["id"], w, t)[1].strip())
    print(j.ctl("route", ship["id"], "start")[1].strip())


if __name__ == "__main__":
    main()
