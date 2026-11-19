"""Plants every free tile around the farms of the given islands with their crop (user: plant
everything to fit): fields cost 5 gold and no tools; 'does not grow here' tiles are refused by the
game and cost nothing. Usage: python plant_all.py ISLAND [ISLAND ...]"""
import sys

sys.path.insert(0, ".")
import jev_driver as j  # noqa: E402

FIELD = {"winery": ("vines", 2), "tobacco_plantation": ("tobacco_field", 2),
         "sugarcane_plantation": ("sugarcane_field", 2), "cotton_plantation": ("cotton_field", 2),
         "cocoa_plantation": ("cocoa_field", 2), "spice_plantation": ("spice_field", 2),
         "grain_farm": ("grain_field", 1)}


def main() -> None:
    _, prod = j.ctl("production")
    for isl in (int(a) for a in sys.argv[1:]):
        total = 0
        for line in prod.splitlines():
            p = line.split()
            if len(p) < 4 or p[3] != f"({isl}):" or p[0] not in FIELD:
                continue
            field, r = FIELD[p[0]]
            x, y = (int(v) for v in p[2].split(","))
            _, out = j.ctl("build-many", field, isl, x - r, y - r, x + 1 + r, y + 1 + r)
            n = int(out.split("built ")[1].split(" ")[0]) if "built " in out else 0
            total += n
            print(f"  {isl} {p[0]} {x},{y}: +{n} {field}", flush=True)
        print(f"island {isl}: {total} fields planted", flush=True)


if __name__ == "__main__":
    main()
