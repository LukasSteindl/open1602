"""Pulls down chapels whose houses a church reaches already (houses.cpp: settlers and citizens
need a chapel OR a church). One at a time: after each, every house must still have a chapel or a
church in reach, else the chapel is built again at once. Usage: python prune_chapels.py ISLAND"""
import sys

sys.path.insert(0, ".")
import jev_driver as j  # noqa: E402

REACH = 9  # a chapel reaches 8 tiles; one more to stay on the safe side


def houses(island: int) -> list[tuple[int, int, set]]:
    _, out = j.ctl("houses", island)
    rows = []
    for line in out.splitlines()[2:]:
        p = line.split()
        if len(p) >= 7 and p[0].isdigit():
            have = p[6].split(":", 1)[1] if p[6].startswith("have:") else ""
            rows.append((int(p[0]), int(p[1]), set(have.split(","))))
    return rows


def uncovered(island: int) -> list[tuple[int, int]]:
    return [(x, y) for x, y, h in houses(island) if "chapel" not in h and "church" not in h]


def chapels(island: int) -> list[tuple[int, int]]:
    _, out = j.ctl("production")
    res = []
    for line in out.splitlines():
        p = line.split()
        if len(p) >= 4 and p[0] == "chapel" and p[3] == f"({island}):":
            x, y = p[2].split(",")
            res.append((int(x), int(y)))
    return res


def main() -> None:
    isl = int(sys.argv[1])
    before = len(uncovered(isl))
    gone = []
    for cx, cy in chapels(isl):
        near = [h for x, y, h in houses(isl) if max(abs(x - cx), abs(y - cy)) <= REACH]
        if not all("church" in h for h in near):
            continue
        out = j.ctl("demolish", isl, cx, cy)[1].strip()
        if len(uncovered(isl)) > before:
            back = j.ctl("build", "chapel", isl, cx, cy)[1].strip()
            print(f"chapel {cx},{cy}: needed after all, built again ({back[:50]})", flush=True)
        else:
            gone.append((cx, cy))
            print(f"chapel {cx},{cy}: {len(near)} houses near, all reached by a church - {out}", flush=True)
    print(f"island {isl}: {len(gone)} chapels pulled down: {gone}", flush=True)


if __name__ == "__main__":
    main()
