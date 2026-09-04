#!/usr/bin/env python3
"""Make an engine-written DOS overland saved game, without playing there.

`#50 (Lift the wilderness refusal from the DOS save converter)` and
`#59 (Map the DOS saved game, not just the character record)` both needed a
DOS saved game made on the travel grid, and the three that were made for them
in 2026-08 lived in `work/p59-outdoor/` and are gone -- along with the run
script that produced them.  Donald's own three DOS saves are all indoors, so
there is no overland specimen on this machine and every session that wants one
has to make it again.  This is the thing that makes it, kept in `tools/` so
nobody writes it a third time.

**The party is not walked out there.**  Reaching the travel grid by playing
means crossing New Phlan to the harbour master and taking a boat, which is a
navigation nobody has automated.  What this does instead is seed and resave:

1. `goldbox.dos_savegame.retarget` moves a *copy* of an indoor save onto a
   travel window -- `ECL7.DAX` block 26 for the middle window -- and the four
   fields measured to differ outdoors are set on top of it: `$49C5` = 0 (the
   overland names no `GEO`), `$49E6` = 0 (travel mode), the travel square at
   `$49C3`/`$49C4`, and `put_tail_state(indoors=False)`.
2. DOSBox loads that seed and the party stands on the grid.
3. The game's own `ENCAMP > SAVE` writes a new slot.

**Every byte of the specimen is then the engine's**, which is the whole point:
a seed is a thing we assembled and is not evidence, and the file the engine
writes over it is.  The two are kept side by side in the output directory so a
reader can see which is which, and `--steps` walks the party first so the
saved square is one the engine itself moved the party to rather than the one
the seed asked for.

Nothing here touches the player's own game tree: `tools.dosbox.Session.stage`
copies it into `work/dosbox/inst/<n>/` and the seed is written into the copy.

Run it with `--check` first; it needs `dosbox`, `Xvfb`, `xdotool` and
ImageMagick's `import`, and says which are absent rather than half-running.
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
from tools import dosbox  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent

def ecl_block(game: pathlib.Path, dax: int, area: int) -> bytes:
    """The area's script, out of the player's own `ECL<n>.DAX`."""
    data = (game / f"ECL{dax}.DAX").read_bytes()
    return sg.dax_block(data, area, name=f"ECL{dax}.DAX")


def seed(save: bytes, *, area: int, x: int, y: int, script: bytes) -> bytes:
    """An indoor saved game moved onto a travel window, ready to be loaded.

    `retarget` writes the seven things a move needs; the four below are what
    `#59 (Map the DOS saved game, not just the character record)` measured to
    separate an outdoor save from an indoor one, three specimens each way.

    The square at 12801/12802 is left where it was on purpose.  Outdoors the
    engine freezes it at the last indoor square and keeps the facing byte
    live, so overwriting it would be inventing a value the engine does not
    maintain out there.
    """
    where = areas.area(area)
    if where is None or not where.outdoors:
        raise ValueError(f"area {area} is not one of the travel windows")
    out = bytearray(save)
    # The triple and the `$49C5` = 0 are both `goldbox`'s to state, not this
    # tool's: `dos_savegame.OUTDOOR_WALLSET` carries the six specimens behind
    # it and `outdoors=True` writes the area word (#59, #190).  This file had
    # its own copy of the constant and wrote `$49C5` by hand, which is two
    # places to update the day a measurement moves and one of them forgotten.
    sg.retarget(out, area=area, dax=where.disk, outdoors=True,
                wallset=sg.OUTDOOR_WALLSET, script=script)
    sg.put_word(out, sg.INDOORS, 0)     # $49E6 = 0 is what boots travel mode
    sg.put_travel_square(out, x, y)
    sg.put_tail_state(out, indoors=False)
    return bytes(out)


def describe(save: bytes) -> dict:
    """What a reader needs to see to believe a save stands outdoors."""
    return {
        "outdoors": sg.outdoors(save),
        "area": sg.current_area(save),
        "travel_square": list(sg.travel_square(save)),
        "stale_square": list(sg.position(save)),
        "dax_byte": save[0],
        "disk_word": sg.word(save, sg.DISK),
    }


def make(*, source: str = "A", target: str = "C", area: int = 26,
         x: int = 7, y: int = 29, steps: int = 1,
         out: pathlib.Path | None = None) -> dict:
    """Seed, load, walk, save.  Returns what the engine wrote, described."""
    out = pathlib.Path(out or REPO / "work" / "p50-outdoor")
    out.mkdir(parents=True, exist_ok=True)
    game = dosbox.find_game()
    report: dict = {"area": area, "asked_for": [x, y], "steps": steps}

    with dosbox.claim("dosoutdoor") as slot:
        # Not `with Session(...)`: its `__enter__` boots, and the seed has to
        # be in the staged tree before DOSBox reads the save directory.
        s = dosbox.Session(slot, game)
        try:
            s.stage(fresh=True)
            staged = s.save_file(source)
            planted = seed(staged.read_bytes(), area=area, x=x, y=y,
                           script=ecl_block(s.game_dir, areas.area(area).disk,
                                            area))
            staged.write_bytes(planted)
            (out / f"SEED-SAVGAM{source.upper()}.DAT").write_bytes(planted)
            report["seed"] = describe(planted)

            s.boot(fresh=False)
            por = dosbox.PoolOfRadiance(s)
            por.to_main_menu()
            por.load_game(source)
            shutil.copy(s.shot("outdoor-loaded"), out / "loaded.png")

            # `step` answers False when the world bar does not come back --
            # an unhandled prompt, or a blocked heading. Letting that through
            # would save a specimen and call it walked on no evidence, which
            # is the whole claim this argument makes.
            walked = 0
            for i in range(steps):
                if not por.step():
                    raise SystemExit(
                        f"step {i + 1} of {steps} did not complete, so the "
                        f"square this would save is the one the seed asked "
                        f"for rather than one the engine moved the party to")
                walked += 1
            report["walked"] = walked
            if steps:
                shutil.copy(s.shot("outdoor-walked"), out / "walked.png")

            written = por.save_game(target)
            report["written"] = describe(written)
            # Named, not globbed: `*C*` matches `CHRDATA1.SAV` and every
            # `.CHA` in the directory, so the specimen arrived surrounded by
            # two other slots' parties the first time this ran.
            wanted = [s.save_file(target)]
            for n in range(1, 7):
                wanted += sorted(
                    s.save_dir.glob(f"CHRDAT{target.upper()}{n}.*"))
            for p in wanted:
                shutil.copy(p, out / p.name)
        finally:
            s.close()

    report["out"] = str(out)
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="Report whether the emulator tooling is installed")
    ap.add_argument("--from", dest="source", default="A",
                    help="The indoor slot to seed from")
    ap.add_argument("--slot", dest="target", default="C",
                    help="The slot the game saves the specimen to")
    ap.add_argument("--area", type=int, default=26,
                    help="Travel window: 25, 26 or 27")
    ap.add_argument("--x", type=int, default=7, help="Window-local x")
    ap.add_argument("--y", type=int, default=29, help="Window-local y")
    ap.add_argument("--steps", type=int, default=1,
                    help="Steps to walk before saving")
    ap.add_argument("--out", default=None, help="Where the specimen goes")
    args = ap.parse_args(argv)

    if args.check:
        absent = dosbox.missing_tools()
        print("Tools missing:", ", ".join(absent) if absent else "none")
        return 1 if absent else 0

    report = make(source=args.source, target=args.target, area=args.area,
                  x=args.x, y=args.y, steps=args.steps, out=args.out)
    print(json.dumps(report, indent=2))
    return 0 if report["written"]["outdoors"] else 1


if __name__ == "__main__":
    sys.exit(main())
