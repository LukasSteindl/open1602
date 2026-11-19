"""The attack on Keln (island 5, player 3 White) for its gold at 5,5. NOT started automatically:
the first shot means war. A computer city is gone when its Kontor, market, towers and houses are
(computer_city_gone): ships shell the coastal Kontor, the troops land by the pier and take the
tower, the market and what is left; then a Kontor of ours, the gold mine and a goldsmith.
Usage: python attack_keln.py TROOPSHIP WARSHIP [WARSHIP ...]"""
import re
import sys
import time

sys.path.insert(0, ".")
import jev_driver as j  # noqa: E402

ISLAND = 5
KONTOR = (27, 15)      # coastal, pier at 29,15..17
TOWER = (17, 17)       # beside the market (screenshot: tower east of the market)
MARKET = (13, 17)
OFF_PIER = (233, 306)  # sea east of the Kontor (island world 200,290)
# The gap in Keln's walls (user screenshot): beach 29..32,20..22 open to the sea, south of the pier;
# a second, smaller one at 32,29. The troops land here, not at the walled pier.
LANDING = (234, 311)


def say(text: str) -> None:
    print(text, flush=True)
    j.ctl("say", text)


def foreign(ch: str) -> int:
    _, m = j.ctl("map", ISLAND)
    return sum(line[5:].count(ch) for line in m.splitlines()[3:])


def ship_move(ship: int, wx: int, wy: int) -> None:
    for r in range(0, 6):
        for dx, dy in ((-r, 0), (r, 0), (0, -r), (0, r)):
            if j.ctl("ship-move", ship, wx + dx, wy + dy)[0] == 0:
                return


def units_on(island: int) -> list[int]:
    _, out = j.ctl("units")
    return [int(m[1]) for m in re.finditer(rf"unit (\d+) figure \d+ island {island} ", out)]


def main() -> None:
    troop, warships = int(sys.argv[1]), [int(a) for a in sys.argv[2:]]
    say("Angriff auf Keln: die Flotte segelt los")
    for s in [troop] + warships:
        j.ctl("route", s, "stop")
        ship_move(s, *OFF_PIER)
    time.sleep(60)
    for s in warships + [troop]:
        print(s, j.ctl("attack", s, ISLAND, *KONTOR)[1].strip(), flush=True)
    t0 = time.time()
    while foreign("k") and time.time() - t0 < 900:
        time.sleep(15)
    say(f"Kontor von Keln: {'zerstoert' if not foreign('k') else 'steht noch'}")
    ship_move(troop, *LANDING)
    time.sleep(20)
    print("land", j.ctl("units-land", troop)[1].strip(), flush=True)
    time.sleep(15)
    ids = units_on(ISLAND)
    say(f"{len(ids)} Einheiten an Land: Turm, dann Markt")
    for target in (TOWER, MARKET):
        print(target, j.ctl("units-attack", ISLAND, *target, *ids)[1].strip(), flush=True)
        t1 = time.time()
        while time.time() - t1 < 600:
            time.sleep(15)
            ids = units_on(ISLAND)
            _, b = j.ctl("map", ISLAND, target[0], target[1], 1, 1)
            if not ids or b.splitlines()[-1][5:6] not in "bmkh":
                break
    say(f"Keln: {len(units_on(ISLAND))} Einheiten stehen noch; Markt {'weg' if not foreign('m') else 'steht'}")


if __name__ == "__main__":
    main()
