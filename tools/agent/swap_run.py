"""One ship round trip between two own Kontors: load at A, unload at B, load at B, unload at A.
Usage: python swap_run.py A B "wood 25,tools 3" "bricks 8"   (goods A->B, then goods B->A)"""
import sys

sys.path.insert(0, ".")
import jev_driver as j  # noqa: E402


def goods(text: str) -> list[tuple[str, int]]:
    return [(p.split()[0], int(p.split()[1])) for p in text.split(",") if p.strip()]


def main() -> None:
    a, b = int(sys.argv[1]), int(sys.argv[2])
    a_to_b, b_to_a = goods(sys.argv[3]), goods(sys.argv[4]) if len(sys.argv) > 4 else []
    ship = j.my_ship()
    wa, wb = j.world_kontor(a), j.world_kontor(b)
    j.ctl("route", ship["id"], "stop")
    j.ctl("say", f"Schiff: Tausch zwischen Insel {a} und {b}")
    print("to", a, j.sail_to(ship["id"], *wa))
    for w, t in a_to_b:
        print(j.ctl("load", ship["id"], w, t)[1].strip())
    print("to", b, j.sail_to(ship["id"], *wb))
    for w, t in a_to_b:
        print(j.ctl("unload", ship["id"], w, t)[1].strip())
    for w, t in b_to_a:
        print(j.ctl("load", ship["id"], w, t)[1].strip())
    if b_to_a:
        print("to", a, j.sail_to(ship["id"], *wa))
        for w, t in b_to_a:
            print(j.ctl("unload", ship["id"], w, t)[1].strip())


if __name__ == "__main__":
    main()
