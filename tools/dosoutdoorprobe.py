#!/usr/bin/env python3
"""Drive DOS Pool of Radiance on the travel grid and read what it writes.

`tools/dosoutdoor.py` makes **one** overland specimen with the fields
`#59 (Map the DOS saved game, not just the character record)` had already
measured.  Two questions it cannot answer are the ones left open on that issue
and on `#190 (A C64 party standing on the travel grid cannot be written into a
DOS save)`, and both need a *differential* rather than a specimen:

**Is the wallset triple at `$4AFA`-`$4AFC` live or stale outdoors?**  All of
2026-08's overland saves read `(0, $FFFF, $FFFF)` -- and so did the New Phlan
save each was seeded from, so live-versus-stale was never separated.  The
separation is to seed from a slot whose triple is *different* (Donald's slot B
stands in Sokol Keep with `(1, 5, 9)`), leave that triple in place, and see
both whether the game loads and what its own `ENCAMP > SAVE` writes back.
`--wallset keep` does that; `--wallset outdoor` is the control that writes
`(0, $FFFF, $FFFF)` from the same seed.

**What are `$507A`-`$507C`?**  They are the only words in the whole variable
array that are nonzero in an engine-written overland save and zero in all
eleven engine-written indoor ones (`tools/dossavcensus.py`), so they are
overland state -- but one specimen cannot say which of them tracks the square.
`--route` walks a scripted path and saves at every waypoint, so a run produces
three or four squares' worth of the same words.

The route is arrow keys: `U` north, `D` south, `L` west, `R` east -- outdoors
the arrows move the party directly instead of turning it -- and a `S<letter>`
step saves to that slot.  `--route "U,SC,R,SD"` steps north, saves as C, steps
east, saves as D.

**A seed is not evidence and the file the engine writes over it is**, so both
are kept side by side in the output directory and the report says which is
which.  Nothing here writes to the player's own game tree: `tools.dosbox`
stages a copy under `work/dosbox/inst/<n>/`.

Run `--check` first; it names the tools it needs rather than half-running.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import areas  # noqa: E402
from goldbox import dos_savegame as sg  # noqa: E402
from tools import (
    dosbox,  # noqa: E402
    dosoutdoor,  # noqa: E402
)

REPO = pathlib.Path(__file__).resolve().parent.parent

#: What each route letter presses.  Outdoors the arrows move the party a
#: square rather than turning it -- measured in #59's play-out run, and the
#: reason a route needs no turn-then-step pair.
MOVES = {"U": "Up", "D": "Down", "L": "Left", "R": "Right"}


def seed(save: bytes, *, area: int, x: int, y: int, script: bytes,
         wallset: tuple[int, int, int] | None) -> bytes:
    """`dosoutdoor.seed`, with the wallset triple left to the caller.

    `wallset=None` keeps whatever the source save carries, which is the whole
    point of the probe: a seed that overwrites the triple can never say
    whether the triple mattered.
    """
    where = areas.area(area)
    if where is None or not where.outdoors:
        raise ValueError(f"area {area} is not one of the travel windows")
    keep = sg.wall_triple(save)
    out = bytearray(save)
    sg.retarget(out, area=area, dax=where.disk,
                wallset=(keep if wallset is None else wallset), script=script)
    sg.put_word(out, sg.AREA, 0)        # $49C5: the overland names no GEO
    sg.put_word(out, sg.INDOORS, 0)     # $49E6 = 0 boots travel mode
    sg.put_travel_square(out, x, y)
    sg.put_tail_state(out, indoors=False)
    return bytes(out)


def fields(save: bytes) -> dict:
    """The fields this probe exists to compare, and nothing else."""
    return {
        "outdoors": sg.outdoors(save),
        "area": sg.current_area(save),
        "travel": list(sg.travel_square(save)),
        "stale_square": list(sg.position(save)),
        "wallset": list(sg.wall_triple(save)),
        "wallmap": [sg.word(save, sg.WALLMAP + i) for i in range(3)],
        "tail": list(save[12801:12809]),
        "clock": list(sg.clock(save)),
        "words": {f"${a:04X}": sg.word(save, a)
                  for a in (0x49C3, 0x49C4, 0x49C5, 0x49E6, 0x49F0, 0x49F1,
                            0x49F2, 0x5012, 0x5079, 0x507A, 0x507B, 0x507C,
                            0x507D, 0x5200)},
    }


def parse_route(text: str) -> list[str]:
    steps = [s.strip().upper() for s in text.split(",") if s.strip()]
    for s in steps:
        if s in MOVES:
            continue
        if len(s) == 2 and s[0] == "S" and s[1].isalpha():
            continue
        raise ValueError(f"route step {s!r} is neither a move nor S<slot>")
    return steps


def run(*, source: str, area: int, x: int, y: int, route: list[str],
        wallset: tuple[int, int, int] | None,
        out: pathlib.Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    game = dosbox.find_game()
    report: dict = {"source": source, "area": area, "seeded_at": [x, y],
                    "route": route, "saves": {}}

    with dosbox.claim("dosoutdoorprobe") as slot:
        # Not `with Session(...)`: its `__enter__` boots, and the seed has to
        # be staged before DOSBox opens the save directory.
        s = dosbox.Session(slot, game)
        try:
            s.stage(fresh=True)
            staged = s.save_file(source)
            planted = seed(
                staged.read_bytes(), area=area, x=x, y=y,
                script=dosoutdoor.ecl_block(s.game_dir,
                                            areas.area(area).disk, area),
                wallset=wallset)
            staged.write_bytes(planted)
            (out / f"SEED-SAVGAM{source.upper()}.DAT").write_bytes(planted)
            report["seed"] = fields(planted)

            s.boot(fresh=False)
            por = dosbox.PoolOfRadiance(s)
            por.to_main_menu()
            por.load_game(source)
            shutil.copy(s.shot("probe-loaded"), out / "loaded.png")
            report["loaded"] = True

            moved = 0
            for i, step in enumerate(route):
                if step in MOVES:
                    if not por._move(MOVES[step]):
                        raise SystemExit(
                            f"route step {i + 1} ({step}) did not complete -- "
                            f"the command bar never came back, so the party "
                            f"is not where the route says and no save taken "
                            f"after this would mean anything")
                    moved += 1
                    continue
                letter = step[1]
                written = por.save_game(letter)
                report["saves"][letter] = fields(written)
                report["saves"][letter]["after_moves"] = moved
                shutil.copy(s.shot(f"probe-{letter}"), out / f"{letter}.png")
                for p in ([s.save_file(letter)] +
                          [q for n in range(1, 7)
                           for q in sorted(
                               s.save_dir.glob(f"CHRDAT{letter.upper()}{n}.*"))
                           ]):
                    shutil.copy(p, out / p.name)
        finally:
            s.close()
    report["out"] = str(out)
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="Report whether the emulator tooling is installed")
    ap.add_argument("--from", dest="source", default="B",
                    help="The indoor slot to seed from (B is Sokol Keep)")
    ap.add_argument("--area", type=int, default=26, help="Travel window")
    ap.add_argument("--x", type=int, default=7, help="Window-local x")
    ap.add_argument("--y", type=int, default=29, help="Window-local y")
    ap.add_argument("--route", default="U,SC",
                    help="Comma-separated U/D/L/R moves and S<slot> saves")
    ap.add_argument("--wallset", default="keep",
                    help="'keep' the source's triple, 'outdoor' for "
                         "(0,$FFFF,$FFFF), or three comma-free ints a:b:c")
    ap.add_argument("--out", default=None, help="Where the specimens go")
    args = ap.parse_args(argv)

    if args.check:
        absent = dosbox.missing_tools()
        print("Tools missing:", ", ".join(absent) if absent else "none")
        return 1 if absent else 0

    if args.wallset == "keep":
        wallset = None
    elif args.wallset == "outdoor":
        wallset = dosoutdoor.OUTDOOR_WALLSET
    else:
        wallset = tuple(int(v) for v in args.wallset.split(":"))
        if len(wallset) != 3:
            ap.error("--wallset wants three values, a:b:c")

    out = pathlib.Path(args.out or REPO / "work" / "p59-wallset")
    report = run(source=args.source, area=args.area, x=args.x, y=args.y,
                 route=parse_route(args.route), wallset=wallset, out=out)
    print(json.dumps(report, indent=2))
    return 0 if all(v["outdoors"] for v in report["saves"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
