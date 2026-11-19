"""Pulls down public buildings of one kind that no house needs: one at a time, and if afterwards a
house lacks the service it had, it is built again at once (user: far too many doctors).
Usage: python prune_service.py SERVICE ISLAND [ISLAND ...]   (e.g. doctor 17 18)"""
import sys

sys.path.insert(0, ".")
import jev_driver as j  # noqa: E402


def lacking(island: int, service: str) -> int:
    _, out = j.ctl("houses", island)
    n = 0
    for line in out.splitlines()[2:]:
        p = line.split()
        if len(p) >= 7 and p[0].isdigit():
            have = p[6].split(":", 1)[1] if p[6].startswith("have:") else ""
            n += service not in have.split(",")
    return n


def sites(island: int, service: str) -> list[tuple[int, int]]:
    _, out = j.ctl("production")
    res = []
    for line in out.splitlines():
        p = line.split()
        if len(p) >= 4 and p[0] == service and p[3] == f"({island}):":
            x, y = p[2].split(",")
            res.append((int(x), int(y)))
    return res


def main() -> None:
    service = sys.argv[1]
    for isl in (int(a) for a in sys.argv[2:]):
        base = lacking(isl, service)
        gone = []
        for x, y in sites(isl, service):
            j.ctl("demolish", isl, x, y)
            if lacking(isl, service) > base:
                back = j.ctl("build", service, isl, x, y)[1].strip()
                print(f"{service} {isl}:{x},{y} needed - built again ({back[:40]})", flush=True)
            else:
                gone.append((x, y))
                print(f"{service} {isl}:{x},{y} not needed - pulled down", flush=True)
        print(f"island {isl}: {len(gone)} {service} pulled down {gone}", flush=True)


if __name__ == "__main__":
    main()
