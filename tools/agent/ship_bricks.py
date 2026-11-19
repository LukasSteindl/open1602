"""Brings building material from the home Kontor to a colony Kontor with the own ship.
Usage: python ship_bricks.py HOME COLONY [WARE TONS ...]   e.g. 9 3 bricks 12"""
import sys

sys.path.insert(0, ".")
import jev_driver as j  # noqa: E402


def world_kontor(island: int) -> tuple[int, int]:
    _, out = j.ctl("islands")
    for line in out.splitlines():
        if line.startswith(f"island {island}:"):
            ox, oy = map(int, line.split("world ")[1].split()[0].split(","))
            kx, ky = j.kontor_pos(island)
            return ox + kx, oy + ky
    raise SystemExit(f"island {island} not found")


def main() -> None:
    home, colony = int(sys.argv[1]), int(sys.argv[2])
    loads = list(zip(sys.argv[3::2], map(int, sys.argv[4::2]))) or [("bricks", 12)]
    ship = j.my_ship()
    if ship is None:
        raise SystemExit("no ship")
    j.ctl("say", f"Schiff holt {', '.join(f'{t:g} t {w}' for w, t in loads)} fuer Insel {colony}")
    j.ctl("route", ship["id"], "stop")
    print("to home:", j.sail_to(ship["id"], *world_kontor(home)))
    for w, t in loads:
        print(j.ctl("load", ship["id"], w, t)[1].strip())
    print("to colony:", j.sail_to(ship["id"], *world_kontor(colony)))
    for w, t in loads:
        print(j.ctl("unload", ship["id"], w, t)[1].strip())
    j.ctl("say", f"Material auf Insel {colony} abgeladen: Piers koennen gebaut werden")


if __name__ == "__main__":
    main()
