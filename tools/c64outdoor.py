#!/usr/bin/env python3
"""Make an engine-written C64 saved game on the travel grid, and keep it.

The C64 twin of `tools/dosoutdoor.py`, and the thing
`#190 (A C64 party standing on the travel grid cannot be written into a DOS
save)` was blocked on: **no C64 save on this machine stands outdoors.**  All
twenty of the player's own `PORSAVE*.D64` and `NEWSAVE*.D64` are indoors --
`$49E6` = 1 in every one -- so a converter that accepts an outdoor C64 party
had nothing to be driven against.

**The party is not walked out there.**  Reaching the travel grid by playing
means crossing New Phlan to the harbour master and buying passage, which is a
navigation nobody has automated.  What this does instead is the same seed and
resave `tools/dosoutdoor.py` does on the DOS side:

1. one of the player's own indoor save disks is read (never written), its
   `SAVEDGAME0` is pointed at a travel window by `goldbox.dos.apply_file_cache`
   and `goldbox.dos.apply_position` -- the outdoor recipe
   `#47 (Decode the travel grid's cache entries, so the wilderness can be
   retargeted too)` proved live twice -- and the pair is written to a fresh
   `.D64` in the slot's own directory;
2. VICE loads that seed and the party stands on the grid;
3. the party **walks**, so the square it is saved on is one the engine moved
   it to rather than the one the seed asked for;
4. the game's own `ENCAMP > SAVE` writes the disk back, and that disk is the
   specimen: every byte of it is the C64 engine's.

`--saves` takes more than one, walking between them, because one specimen
cannot show which fields move with the party.

It also reads five things out of memory at every step, which is the other
half of what this tool is for:

* `$49C3`/`$49C4`, the live travel square;
* `$49C0`-`$49C2`, the dungeon square, which is frozen out here;
* `$033D`, where `docs/137-wilderness-automap.md` puts the eight-way travel
  heading -- **outside the `$4900`-`$64FF` a save is an image of**, so a
  saved C64 game cannot carry the party's outdoor facing at all;
* `$49E6`, which world the engine thinks it is in;
* the loaded-files cache at `$4BC0`.

Nothing here touches the player's disks: `tools/session.py`'s `stage_disks`
copies the eight sides into the slot and `Session.attach` refuses a path
outside it.  The pool owns the emulator -- claim, launch, tear down.

    tools/c64outdoor.py --seed-from PORSAVE13.D64 --walk 13 --saves 2
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap.paths import find_disks  # noqa: E402
from goldbox import areas, dos  # noqa: E402
from goldbox import dos_savegame as sg  # noqa: E402
from goldbox.d64 import load_payload  # noqa: E402
from goldbox.games import POOL_OF_RADIANCE  # noqa: E402
from tools import session as S  # noqa: E402

#: Where the player keeps the C64 disks.  Read only, and found the way every
#: other tool here finds them.
DISKS = pathlib.Path(os.environ.get("POR_DISKS") or find_disks() or "")

#: The eight-way travel heading, per `docs/137-wilderness-automap.md`.  Page
#: 3, so no saved game holds it: `SAVEDGAME0` is an image of `$4900`-`$64FF`.
TRAVEL_HEADING = 0x033D


def outdoor_request(area: int, x: int, y: int) -> bytes:
    """A DOS saved game saying only "outdoors, in `area`, at (x,y)".

    Not a specimen and not evidence.  The two functions that know how to
    point a C64 save at an area -- `dos.apply_file_cache` and
    `dos.apply_position` -- read *where to go* out of a DOS save, and between
    them they read three words of it.  This is the shortest way to ask them
    for the travel grid without a DOS save to hand, which matters because the
    only outdoor DOS saves on this machine live under `work/` and have been
    lost once already.
    """
    req = bytearray(sg.SAVGAM_SIZE)
    sg.put_word(req, sg.SCRIPT, area)
    sg.put_word(req, sg.INDOORS, 0)
    sg.put_travel_square(req, x, y)
    return bytes(req)


def seed_disk(source: pathlib.Path, out: pathlib.Path, *, area: int,
              x: int, y: int) -> dict:
    """Write `out`: `source`'s party, standing on the travel grid.

    `source` is one of the player's own save disks and is read only.
    """
    save0 = bytearray(load_payload(str(source), POOL_OF_RADIANCE.save_file))
    save1 = load_payload(str(source), POOL_OF_RADIANCE.roster_file)
    where = areas.area(area)
    if where is None or not where.outdoors:
        raise SystemExit(f"area {area} is not one of the travel windows")
    request = outdoor_request(area, x, y)
    line = dos.apply_file_cache(save0, request)
    dos.apply_position(save0, request)
    out.write_bytes(dos.save_disk(bytes(save0), bytes(save1)).data)
    return {"from": str(source), "cache": line,
            "area": area, "square": [x, y]}


def look(sess) -> dict:
    """The five readings, in one monitor block so they are one snapshot."""
    with sess.mon(5) as m:
        dungeon = m.read(0x49C0, 3)
        travel = m.read(0x49C3, 2)
        indoors = m.read(0x49E6, 1)[0]
        heading = m.read(TRAVEL_HEADING, 1)[0]
        cache = m.read(0x4BC0, 0x19)
    return {
        "travel": list(travel),
        "dungeon": list(dungeon),
        "indoors": indoors,
        "heading": heading,
        "cache": cache.hex(),
    }


def run(args) -> int:
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    source = pathlib.Path(args.seed_from)
    if not source.is_absolute():
        source = DISKS / source
    report: dict = {"seed_from": str(source), "out": str(out), "steps": []}
    slot = S.claim_slot(args.slot, "c64outdoor")
    print(f"slot {slot.n} display {slot.display}", flush=True)
    sess = None
    rc = 0
    try:
        boot = S.stage_disks(slot, DISKS)
        here = pathlib.Path(slot.dir)
        report["seed"] = seed_disk(source, here / "SIDE0.D64",
                                   area=args.area, x=args.x, y=args.y)
        shutil.copy(here / "SIDE0.D64", out / "SEED.D64")

        sess = S.Session(boot, slot=slot)
        if not sess.boot():
            raise RuntimeError("boot failed")
        if not sess.load_save():
            raise RuntimeError("the game did not offer the save")
        if not sess.select_row("BEGIN ADVENTURING"):
            raise RuntimeError("BEGIN ADVENTURING could not be selected")
        if not sess.wait_for_world(args.arrive):
            sess.kbd.screenshot(str(out / "stuck.png"))
            raise RuntimeError(f"no world bar {args.arrive:.0f}s after "
                               f"BEGIN ADVENTURING")
        sess.settle(3)
        report["arrived"] = look(sess)
        at = sess.status()
        report["status"] = None if at is None else at.where()
        print(f"arrived: {report['arrived']} status={report['status']}",
              flush=True)
        sess.kbd.screenshot(str(out / "arrived.png"))

        # One walk, then one save, per specimen.  The saved square has to be
        # one the engine moved the party to: a save taken on the square the
        # seed asked for proves nothing about what the engine does with it.
        for n in range(args.saves):
            for move in args.walk:
                before = look(sess)
                moved = sess.walk_outdoors(move)
                after = look(sess)
                step = {"save": n + 1, "move": move, "moved": moved,
                        "before": before, "after": after}
                report["steps"].append(step)
                print(f"  {move}: moved={moved} "
                      f"{before['travel']}->{after['travel']} "
                      f"heading {before['heading']}->{after['heading']} "
                      f"dungeon {before['dungeon']}->{after['dungeon']}",
                      flush=True)
                if not moved:
                    sess.kbd.screenshot(str(out / f"blocked-{n + 1}{move}.png"))
                sess.handle_prompt()
            name = f"{args.name}{n + 1}.D64"
            if not sess.save_game():
                raise RuntimeError(f"ENCAMP > SAVE did not complete for {name}")
            sess.settle(3)
            shutil.copy(sess.save_disk, out / name)
            saved = load_payload(str(out / name), POOL_OF_RADIANCE.save_file)
            g = lambda a: saved[a - 0x4900]      # noqa: E731
            report.setdefault("saves", []).append({
                "file": str(out / name),
                "travel": [g(0x49C3), g(0x49C4)],
                "dungeon": [g(0x49C0), g(0x49C1), g(0x49C2)],
                "indoors": g(0x49E6), "script": g(0x49F2), "geo": g(0x49C5),
                "clock": [g(0x49C6 + i) for i in range(6)],
                "cache": saved[0x4BC0 - 0x4900:0x4BD9 - 0x4900].hex(),
            })
            print(f"  wrote {name}: {report['saves'][-1]}", flush=True)
            sess.kbd.screenshot(str(out / f"{args.name}{n + 1}.png"))
    except Exception as exc:
        import traceback
        traceback.print_exc()
        report["failed"] = repr(exc)
        try:
            if sess is not None:
                sess.kbd.screenshot(str(out / "failure.png"))
                s = sess.screen()
                report["failure_screen"] = [] if s is None else [
                    line.rstrip() for line in s.rows() if line.strip()]
        except Exception:
            pass
        rc = 1
    finally:
        for what, step in (("session close", lambda: sess and sess.close()),
                           ("slot teardown", slot.teardown),
                           ("slot release", slot.release)):
            try:
                step()
            except Exception as exc:
                print(f"Cleanup failed at {what}: {exc!r}", flush=True)
                rc = rc or 1
    (out / f"{args.name}.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return rc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seed-from", default="PORSAVE13.D64",
                   help="the indoor save disk the party comes off")
    p.add_argument("--area", type=int, default=26,
                   help="travel window: 25, 26 or 27")
    p.add_argument("--x", type=int, default=7, help="window-local x")
    p.add_argument("--y", type=int, default=28, help="window-local y")
    p.add_argument("--walk", default="13",
                   help="compass digits to walk before each save "
                        "(1 north, 3 east, 5 south, 7 west)")
    p.add_argument("--saves", type=int, default=2,
                   help="how many engine-written specimens to take")
    p.add_argument("--name", default="C64OUT",
                   help="stem for the specimen disks")
    p.add_argument("--slot", type=int, default=None, help="the pool slot")
    p.add_argument("--arrive", type=float, default=240.0,
                   help="seconds to wait for the world bar")
    p.add_argument("--out", default=str(ROOT / "work" / "p190"),
                   help="where the specimens and the log go")
    args = p.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
