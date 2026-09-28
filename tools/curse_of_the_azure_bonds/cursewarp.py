#!/usr/bin/env python3
"""Fast-travel a *Curse of the Azure Bonds* party, to find out whether the
mechanism works there at all.

`#19 (Can Curse be fast-travelled at all, or is the mechanism Pool of
Radiance's alone?)` is the ticket, and it is the gate on the whole Fast Travel
branch.  `tools/areas/newecl.py` answers the static half -- every address the recipe
needs exists in Curse's own overlays and `NEWECL` is the same routine.  This
answers the half that a listing cannot: whether the writes made from outside,
with the PC dropped into the handler's tail, actually land a party in another
area of a running Curse.

    tools/curse_of_the_azure_bonds/cursewarp.py --pool 3 --to 0x03 --disk 2 --out DIR
    tools/curse_of_the_azure_bonds/cursewarp.py --pool 3 --probe --out DIR
    tools/curse_of_the_azure_bonds/cursewarp.py --pool 5 --to 0x10 --disk 3 --via-actions --out DIR

`--probe` boots, loads the party, and reports what the machine holds without
warping -- which is what to run first, because the current area and the
indoors flag both decide whether a warp is legal.

**`--via-actions` makes the trip with `automap.actions.FastTravel` instead of
with this file's own writes**, which is the measurement
`#15 (Fast Travel for more than one Gold Box title)` needed: `#19` proved the
mechanism by writing the bytes from here, and what a player clicking Fast
Travel runs is the action, with its own address table, its own legality chain
and its own jump. A tool that reproduces a result its own way says nothing
about the code that ships.

**Every address here is Curse's, read out of Curse's overlays**, and none of
them is Pool of Radiance's with an offset applied by hand: `tools/areas/newecl.py`
prints the derivation.  They are re-derived at run time rather than written
down, so a differently-cracked release answers with its own or refuses.

**The party must be indoors.**  Warping out of an overland area with the
indoors flag clear wedges Pool of Radiance's loader in an unrecoverable
`INSERT SIDE #` loop (`docs/118-debug-mode.md` §3), and nothing suggests Curse
is kinder; `--force` is there to test that claim deliberately and is refused
otherwise.

Nothing is written to the player's disks.  `curserun.stage` copies the six
sides into the pool slot and makes the save disk there, and every byte this
writes goes to RAM.  Captures go to the `cursewarp` scratch directory by default.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap.actions import pc_register  # noqa: E402
from goldbox import c64_port  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from tools.c64 import session as por  # noqa: E402
from tools.curse_of_the_azure_bonds import curserun  # noqa: E402
from tools.curse_of_the_azure_bonds.curseload import (  # noqa: E402,F401
    Addresses,
    clear_messages,
    enter_world,
)
from tools.registry import scratch  # noqa: E402

#: Where Curse's live party square is.  **Not relocated**: `DUNGEON`'s own
#: position flush reads `$C04B,X` in Curse exactly as it does in Pool of
#: Radiance, which is what says the triple did not move with the save image.
LIVE_X, LIVE_Y, LIVE_FACING = 0xC04B, 0xC04C, 0xC04D

#: How long to give an arrival that comes off a floppy before believing the
#: capture.  `docs/50-experiments.md`: a fixed settle is a measurement of the
#: harness, so this is a ceiling on a poll of the program counter, not a wait.
ARRIVAL_TIMEOUT = 180.0


def geo_square(disks: str, geo_name: str):
    """A square in the largest open part of a named map, or None.

    The same rule `FastTravel` uses for a Pool of Radiance area with no
    arrival square of its own -- `goldbox.areas.landing_square`, which stays
    off the outer ring so the party is not one keypress from leaving the area
    it has just been put in.
    """
    from goldbox.areas import landing_square
    from goldbox.geo import load_geo_files
    for path in sorted(pathlib.Path(disks).glob("*.[dD]64")):
        try:
            maps = load_geo_files(D64.open(str(path)))
        except Exception:
            continue
        if geo_name in maps:
            return landing_square(maps[geo_name])
    return None


def load_curse_save(sess, timeout: float = 240.0) -> bool:
    """Curse's own load flow, which is not Pool of Radiance's.

    Two differences, both measured at the machine rather than guessed:

    * `Session.load_save` waits for `LOAD SAVED GAME: YES`, and Curse's
      confirmation reads **`LOAD SAVED GAME ? YES NO`** -- a question mark and
      a space where Pool of Radiance has a colon -- so the shared method sits
      out its whole budget in front of a game waiting on the driver.
    * The `YES` on that bar **does not answer to an XTEST Return**.
      `select_bar` walks the highlight on to it and presses, the bar does not
      move, and the run ends there. It answers to the KERNAL buffer, which is
      the same thing `tools/curse_of_the_azure_bonds/curserun.py` found for the release's start-up
      check.

    Written here rather than in `tools/c64/session.py`, which is Pool of
    Radiance's and is another ticket's file.
    """
    if sess.wait_text("LOAD SAVED GAME", timeout)[0] is None:
        return False
    # **Put the save disk in the drive first.**  Curse reads `SAVEAZURE` off
    # whatever is in unit 8 and answers `UNABLE TO LOAD SAVED GAME.` when that
    # is a game side -- it does not prompt for the save disk here, so nothing
    # in `handle_prompt` ever fires and the run loops on the refusal.  Six
    # rounds of that is what the first probe recorded.
    sess.attach(sess.save_disk)
    if not sess.select_row("LOAD SAVED GAME"):
        return False
    deadline = time.time() + timeout
    seen = ""
    while time.time() < deadline:
        s = sess.screen()
        if s is None:
            time.sleep(0.5)
            continue
        text = s.text()
        if "BEGIN ADVENTURING" in text:
            return True
        if sess.handle_prompt(s):
            time.sleep(1.0)
            continue
        bar = s.row(24).strip()
        if bar != seen:
            sess.log(f"  load: {bar!r}")
            seen = bar
        if "YES" in s.row(24):
            sess.select_bar("YES")
            sess.press_kernal(0x0D)
        time.sleep(1.0)
    return False


def walk_proof(sess, addr: Addresses, keys: str = "JIKIKIJI") -> dict:
    """Can the party that arrived actually move?

    The end of the question `#19 (Can Curse be fast-travelled at all, or is
    the mechanism Pool of Radiance's alone?)` asks: a warp that draws the
    right map and cannot then take a step has moved a picture, not a party.

    **Measured in memory, one key at a time.**  Curse does not print the
    square in every area -- area `$01` draws `N 3:41 4,4` and area `$03`
    draws `E 3:44` with no coordinates at all -- so a status-line reader
    answers None there and proves nothing.  `$C04B`-`$C04D` is the live
    triple, and `DUNGEON`'s own flush is what copies it into the save, so it
    is what a step has to change.

    **One key, one reading, and no re-sending.**  `Session.walk_one` re-sends
    a move until the status line changes, which is right for mapping and
    wrong here: a table of key against triple is the evidence, and a key sent
    an unknown number of times cannot be read off one.  `I` forward, `J`
    left, `K` right, `M` about; a wall in front is a map fact, not a failure,
    so the sequence turns as well as steps.
    """
    out = {"bar": clear_messages(sess)}

    def triple():
        with sess.mon(8) as m:
            return list(m.read(LIVE_X, 3))

    out["triple_before"] = triple()
    if "ENCAMP" in out["bar"]:
        out["entered_move"] = sess.select_bar("MOVE", timeout=15)
        time.sleep(1.0)
    else:
        out["entered_move"] = "I,J,K,M" in out["bar"]
    # **Re-enter MOVE before every key.**  The first sequence sent eight keys
    # into a session that had left MOVE mode after the first of them, so seven
    # readings were the same triple and looked like a party that could not
    # move.  `Session.walk_one` learned the same thing from the other end --
    # a stale row 24 -- and the fix here is to read the bar each time rather
    # than to re-send the key.
    steps = []
    for key in keys:
        s = sess.screen()
        bar = s.row(24).strip() if s is not None else ""
        if "I,J,K,M" not in bar:
            sess.select_bar("MOVE", timeout=10)
            time.sleep(0.8)
            s = sess.screen()
            bar = s.row(24).strip() if s is not None else ""
        sess.kbd.key(key.lower(), 0.15, 0.30)
        time.sleep(1.4)
        steps.append({"key": key, "bar": bar, "triple": triple()})
    out["steps"] = steps
    out["triple_after"] = steps[-1]["triple"] if steps else out["triple_before"]
    seen = {tuple(s["triple"]) for s in steps} | {tuple(out["triple_before"])}
    out["distinct_triples"] = len(seen)
    out["moved"] = out["triple_after"][:2] != out["triple_before"][:2]
    out["turned"] = any(s["triple"][2] != out["triple_before"][2]
                        for s in steps)
    sess.leave_move()
    return out


def screen_text(sess, path: pathlib.Path | None = None) -> str:
    """What the screen says now, saved beside the capture if asked.

    A driver that stops without saying what it was looking at costs the next
    run: five of the six failures in this tool's first session were a menu
    whose wording nobody had written down.
    """
    s = sess.screen()
    text = s.text() if s is not None else "(bitmap or unreadable)"
    if path is not None:
        path.write_text(text)
    return text


def snapshot(sess, addr: Addresses, mon=None) -> dict:
    """What the machine holds, in one monitor round trip."""
    close = mon is None
    m = mon or sess.mon(8).__enter__()
    try:
        out = {
            "mode": m.peek(addr.mode),
            "disk": m.peek(addr.disk),
            "slot": m.peek(addr.slot),
            "area": m.peek(addr.slot) & 0x7F,
            "came_from": m.peek(addr.came_from),
            "indoors": m.peek(addr.indoors),
            "square": list(m.read(LIVE_X, 3)),
            "pc": m.registers().get(pc_register(m)),
        }
    finally:
        if close:
            m.__exit__(None, None, None)
    return out


def curse_maps(disks: str) -> dict:
    """Every `GEO` on every side, by name.  Read once and reused."""
    from goldbox.geo import load_geo_files
    out: dict = {}
    for path in sorted(pathlib.Path(disks).glob("*.[dD]64")):
        try:
            out.update(load_geo_files(D64.open(str(path))))
        except Exception:
            continue
    return out


def resident_geo(sess, maps: dict) -> dict:
    """Which of this title's maps is the one drawn at `$0400`, if any.

    `automap/area.py`'s verdict, the same measured test `#21` uses to notice a
    wrong game disk: an exact match against the disk copies first, then
    reciprocity, shared walled edges and agreement about which wall it is.  A
    warp that lands has to change this, and a warp that only *looks* like it
    landed will not.
    """
    from automap.area import ResidentGeo

    class _Block:
        def __init__(self, data):
            self.data = data

        def read(self, addr, length):
            return self.data[addr - 0x0400:addr - 0x0400 + length]

    try:
        with sess.mon(8) as m:
            block = m.read(0x0400, 1024)
        seen = ResidentGeo(_Block(block))
        verdict, name = seen.verdict(maps)
        return {"verdict": verdict, "name": name}
    except Exception as exc:                                  # pragma: no cover
        return {"verdict": "unreadable", "name": None, "error": str(exc)}


def wait_idle(sess, addr: Addresses, timeout: float = ARRIVAL_TIMEOUT
              ) -> tuple[bool, int | None]:
    """Poll until the PC is back in the key-wait loop or its fetcher.

    A capture taken mid-load is a measurement of the harness rather than of
    the game (`docs/50-experiments.md`), and an arrival off a floppy takes as
    long as it takes.  Disk prompts are answered while waiting, because Curse
    asks for a side the moment a warp names one that is not in the drive.
    """
    windows = (addr.key_wait, addr.key_fetch)
    deadline = time.time() + timeout
    pc = None
    while time.time() < deadline:
        try:
            with sess.mon(6) as m:
                pc = m.registers().get(pc_register(m))
        except Exception:
            pc = None
        if pc is not None and any(lo <= pc < hi for lo, hi in windows):
            return True, pc
        sess.handle_prompt()
        time.sleep(0.5)
    return False, pc


def warp(sess, addr: Addresses, target: int, disk: int,
         square: tuple[int, int, int] | None) -> dict:
    """`NEWECL`'s own writes, made from outside, then its tail.

    The order is the handler's, with the operand fetch left out because there
    is no script stream to fetch from -- `docs/118-debug-mode.md` §3 for Pool
    of Radiance, and `tools/areas/newecl.py` for why the same order is Curse's.
    """
    made = {}
    with sess.mon(10) as m:
        m.write(addr.disk, bytes([disk]))
        made["disk"] = disk
        if square is not None:
            m.write(LIVE_X, bytes(square))
            made["square"] = list(square)
        here = m.peek(addr.slot) & 0x7F
        m.write(addr.came_from, bytes([here]))
        made["came_from"] = here
        m.write(addr.slot, bytes([target | 0x80]))
        made["slot"] = target | 0x80
        m.write(addr.scratch, bytes(32))
        made["scratch_zeroed"] = 32
        rid = pc_register(m)
        m.set_registers({rid: addr.tail})
        made["pc"] = addr.tail
        m.resume()
    return made


class SessTarget:
    """`automap.actions`' Target contract over this session's monitor.

    The same four methods `tools/areas/windowsquare.py` wraps a Pool of Radiance
    session in. It exists so that `--via-actions` exercises the code the
    window ships rather than this file's own `warp`: the two write the same
    bytes, and only one of them is what a player clicking Fast Travel runs.
    """

    def __init__(self, sess):
        self.sess = sess

    def read(self, addr: int, length: int) -> bytes:
        with self.sess.mon(5) as m:
            return m.read(addr, length)

    def write(self, addr: int, data) -> None:
        with self.sess.mon(5) as m:
            m.write(addr, bytes(data))

    def pc(self):
        with self.sess.mon(5) as m:
            return m.registers().get(pc_register(m))

    def set_pc(self, address: int) -> None:
        with self.sess.mon(5) as m:
            m.set_registers({pc_register(m): address})


class Row:
    """One area, in the shape `FastTravel` reads a table row in.

    Curse has no area table -- `goldbox/areas.py` has Pool of Radiance's and
    Silver Blades' -- so a driven trip has to supply the three fields itself:
    the id, the side that carries the area's `ECL`, and where to put the
    party. `FastTravel` reads them off any object, which is what lets this run
    without waiting on a table nobody has built.
    """

    def __init__(self, id: int, disk: int, arrival=None):
        self.id, self.disk, self.arrival = id, disk, arrival
        self.name = f"area ${id:02X}"
        self.outdoors = False
        self.fasttravelable = True


def warp_via_actions(sess, target, to: int, disk: int, square) -> dict:
    """The same trip, made by `automap.actions.FastTravel` itself.

    **This is the measurement `#15 (Fast Travel for more than one Gold Box
    title)` needs and `#19` did not make.** `#19` proved the mechanism by
    writing the bytes from this file; what a player runs is
    `FastTravel.apply`, with its own legality chain, its own address table and
    its own jump. A tool that reproduces a result its own way says nothing
    about the code that ships.
    """
    from automap import actions

    ft = actions.FastTravel(c64_port.CURSE_OF_THE_AZURE_BONDS)
    row = Row(to, disk, arrival=tuple(square) if square else None)
    verdict = ft.legality(target, row)
    out = {"legal": bool(verdict), "reason": verdict.reason,
           "addresses": ft.addresses.title if ft.addresses else None}
    if not verdict:
        return out
    outcome = ft.apply(target, area=row)
    out["ok"] = outcome.ok
    out["message"] = outcome.message
    out["writes"] = [[at, list(data)] for at, data in outcome.writes]
    out["notes"] = list(outcome.notes)
    return out


def run(args) -> int:
    game = c64_port.CURSE_OF_THE_AZURE_BONDS
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    addr = Addresses(game, args.disks)
    print("addresses:", addr.describe(), flush=True)
    (out / "addresses.json").write_text(json.dumps(addr.as_dict(), indent=1))

    maps = curse_maps(args.disks)
    print(f"{len(maps)} maps read off the sides", flush=True)

    slot = por.claim_slot(args.pool, note=os.environ.get("POR_AGENT", "warp19"))
    print(f"slot {slot.n}: monitor {slot.port} display {slot.display} "
          f"dir {slot.dir}", flush=True)
    sess = None
    try:
        save = args.save
        if save:
            # A slot is reused, so a bare `shutil.copy` here would carry a
            # read-only specimen's mode onto `SAVE_IN.D64` and then raise on
            # the next run's attempt to stage over it (#472) -- the same
            # fault `curserun.stage` below has for `SIDE0.D64`.
            staged = pathlib.Path(slot.dir) / "SAVE_IN.D64"
            por.stage_writable(save, staged)
            save = str(staged)
        # **`tools/c64/session.py` is Pool of Radiance's, and one of its module
        # constants is an address.**  `Session.indoors` reads `$49E6`, which in
        # a running Curse is `LIBRARY` code rather than the indoors flag, and
        # `walk_one` routes to the travel grid's compass keys on the strength
        # of it.  Point it at Curse's own `$4BE6` for this process only; the
        # file is another ticket's and is not edited.
        por.INDOORS_AT = addr.indoors
        first = curserun.stage(slot, args.disks, save)
        sess = curserun.CurseSession(first, slot=slot)
        if not sess.boot():
            print("boot incomplete", flush=True)
            return 3
        sess.patch_disk_prompt()
        if not load_curse_save(sess):
            print("could not load the saved party; the screen says:",
                  flush=True)
            print(screen_text(sess, out / "stuck-load.txt"), flush=True)
            sess.kbd.screenshot(str(out / "stuck-load.png"))
            return 3
        if not enter_world(sess, addr):
            print("never reached the world; the screen says:", flush=True)
            print(screen_text(sess, out / "stuck-world.txt"), flush=True)
            sess.kbd.screenshot(str(out / "stuck-world.png"))
            return 3
        sess.settle(4)
        ok, pc = wait_idle(sess, addr, 90)
        before = snapshot(sess, addr)
        before["resident"] = resident_geo(sess, maps)
        before["idle"] = ok
        s = sess.screen()
        before["screen"] = s.text() if s is not None else None
        print("before:", json.dumps({k: v for k, v in before.items()
                                     if k != "screen"}), flush=True)
        (out / "before.json").write_text(json.dumps(before, indent=1))
        sess.kbd.screenshot(str(out / "before.png"))

        if args.probe:
            return 0
        if not before["idle"]:
            print(f"the PC is ${pc:04X} and not in a key window; refusing",
                  flush=True)
            return 4
        if before["mode"] != 1:
            print(f"${addr.mode:04X} is {before['mode']}, not 1: DUNGEON is "
                  f"not resident and the tail is somebody else's code",
                  flush=True)
            return 4
        if not before["indoors"] and not args.force:
            print(f"${addr.indoors:04X} is 0, so the party is on the travel "
                  f"grid. Pool of Radiance wedges its loader warping out of "
                  f"one; pass --force to test that here deliberately.",
                  flush=True)
            return 4
        if before["area"] == args.to:
            print(f"the party is already in area ${args.to:02X}; NEWECL "
                  f"skips a same-area transition", flush=True)
            return 4

        square = None
        if args.geo:
            square = geo_square(args.disks, args.geo)
            if square is not None:
                square = (square[0], square[1], square[2])
            print(f"arrival square from {args.geo}: {square}", flush=True)
        if args.via_actions:
            made = warp_via_actions(sess, SessTarget(sess), args.to,
                                    args.disk, square)
            print("FastTravel.apply:", json.dumps(made), flush=True)
            (out / "writes.json").write_text(json.dumps(made, indent=1))
            if not made.get("ok"):
                print("the action refused; nothing was written", flush=True)
                return 4
        else:
            made = warp(sess, addr, args.to, args.disk, square)
            print("wrote:", json.dumps(made), flush=True)
            (out / "writes.json").write_text(json.dumps(made, indent=1))

        landed, pc = wait_idle(sess, addr)
        sess.settle(3)
        after = snapshot(sess, addr)
        after["resident"] = resident_geo(sess, maps)
        after["idle"] = landed
        if landed:
            after["walk"] = walk_proof(sess, addr)
            after["resident_after_walk"] = resident_geo(sess, maps)
        s = sess.screen()
        after["screen"] = s.text() if s is not None else None
        print("after:", json.dumps({k: v for k, v in after.items()
                                    if k != "screen"}), flush=True)
        (out / "after.json").write_text(json.dumps(after, indent=1))
        sess.kbd.screenshot(str(out / "after.png"))
        if after["screen"]:
            (out / "after-screen.txt").write_text(after["screen"])
        if before["screen"]:
            (out / "before-screen.txt").write_text(before["screen"])
        return 0 if landed else 5
    finally:
        if sess is not None:
            sess.terminate()
        else:
            slot.teardown()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pool", type=int, default=None,
                    help="which pool slot to claim (default: any free one)")
    ap.add_argument("--disks", default=os.environ.get("POR_DISKS"),
                    help="where the six Curse sides are")
    ap.add_argument("--save", default="",
                    help="a save disk to stage as SIDE0 (default: a blank one)")
    ap.add_argument("--to", type=lambda v: int(v, 0), default=0x03,
                    help="the target area id, the ECL number (default: 0x03)")
    ap.add_argument("--disk", type=int, default=2,
                    help="which side carries that ECL, 1-6 (default: 2)")
    ap.add_argument("--geo", default="",
                    help="pick the arrival square off this map, e.g. GEO03; "
                         "omitted, the arriving script places the party")
    ap.add_argument("--probe", action="store_true",
                    help="boot and report, warp nothing")
    ap.add_argument("--via-actions", action="store_true",
                    help="make the trip with automap.actions.FastTravel "
                         "rather than with this file's own writes, which is "
                         "what a player clicking the button runs")
    ap.add_argument("--force", action="store_true",
                    help="warp even from the travel grid, which is expected "
                         "to wedge the loader")
    ap.add_argument("--out", default=str(scratch.scratch_dir("cursewarp")),
                    help="where captures go (default: %(default)s)")
    args = ap.parse_args(argv[1:])
    if not args.disks or not os.path.isdir(args.disks):
        print("No Curse disks. Set $POR_DISKS or pass --disks.",
              file=sys.stderr)
        return 2
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
