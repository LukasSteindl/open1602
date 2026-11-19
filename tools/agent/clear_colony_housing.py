"""Supply islands keep no houses (user: they only fetch raw materials): pulls down every house and
the public buildings that served them (chapel, tavern, school, church, bathhouse, doctor, fire
station). Kontor, markets, warehouses and production stay. Usage: python clear_colony_housing.py ISL..."""
import sys

sys.path.insert(0, ".")
import jev_driver as j  # noqa: E402

PUBLIC = ("chapel", "tavern", "school", "church", "bathhouse", "doctor", "fire_station", "theatre", "college")


def main() -> None:
    for isl in (int(a) for a in sys.argv[1:]):
        _, out = j.ctl("houses", isl)
        houses = [(int(p[0]), int(p[1])) for p in (ln.split() for ln in out.splitlines()[2:])
                  if len(p) >= 2 and p[0].isdigit() and p[1].isdigit()]
        for x, y in houses:
            j.ctl("demolish", isl, x, y)
        _, prod = j.ctl("production")
        pub = []
        for line in prod.splitlines():
            p = line.split()
            if len(p) >= 4 and p[0] in PUBLIC and p[3] == f"({isl}):":
                x, y = p[2].split(",")
                j.ctl("demolish", isl, x, y)
                pub.append(p[0])
        print(f"island {isl}: {len(houses)} houses and {len(pub)} public buildings pulled down ({', '.join(pub)})",
              flush=True)


if __name__ == "__main__":
    main()
