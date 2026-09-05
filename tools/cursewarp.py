#!/usr/bin/env python3
"""Fast-travel a *Curse of the Azure Bonds* party, to find out whether the
mechanism works there at all.

`#19 (Can Curse be fast-travelled at all, or is the mechanism Pool of
Radiance's alone?)` is the ticket, and it is the gate on the whole Fast Travel
branch.  `tools/newecl.py` answers the static half -- every address the recipe
needs exists in Curse's own overlays and `NEWECL` is the same routine.  This
answers the half that a listing cannot: whether the writes made from outside,
with the PC dropped into the handler's tail, actually land a party in another
area of a running Curse.

    tools/cursewarp.py --pool 3 --to 0x03 --disk 2 --out work/issue19/run1
    tools/cursewarp.py --pool 3 --probe --out work/issue19/probe

`--probe` boots, loads the party, and reports what the machine holds without
warping -- which is what to run first, because the current area and the
indoors flag both decide whether a warp is legal.

**Every address here is Curse's, read out of Curse's overlays**, and none of
them is Pool of Radiance's with an offset applied by hand: `tools/newecl.py`
prints the derivation.  They are re-derived at run time rather than written
down, so a differently-cracked release answers with its own or refuses.

**The party must be indoors.**  Warping out of an overland area with the
indoors flag clear wedges Pool of Radiance's loader in an unrecoverable
`INSERT SIDE #` loop (`docs/118-debug-mode.md` §3), and nothing suggests Curse
is kinder; `--force` is there to test that claim deliberately and is refused
otherwise.

Nothing is written to the player's disks.  `curserun.stage` copies the six
sides into the pool slot and makes the save disk there, and every byte this
writes goes to RAM.  Captures go to `work/`, which is gitignored.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TOOLS))

import curserun  # noqa: E402
import newecl  # noqa: E402
import session as por  # noqa: E402

from automap.actions import pc_register  # noqa: E402
from goldbox import games  # noqa: E402
from goldbox.d64 import D64  # noqa: E402

#: Where Curse's live party square is.  **Not relocated**: `DUNGEON`'s own
#: position flush reads `$C04B,X` in Curse exactly as it does in Pool of
#: Radiance, which is what says the triple did not move with the save image.
LIVE_X, LIVE_Y, LIVE_FACING = 0xC04B, 0xC04C, 0xC04D

#: How long to give an arrival that comes off a floppy before believing the
#: capture.  `docs/50-experiments.md`: a fixed settle is a measurement of the
#: harness, so this is a ceiling on a poll of the program counter, not a wait.
ARRIVAL_TIMEOUT = 180.0


class Addresses:
    """Every address the warp needs, read out of this title's own overlays.

    Built by `tools/newecl.py`'s finders rather than written down, so the one
    trap `#17` names -- an address taken from a PRG header, `$800` out -- has
    no way in.  The `save` base is `Game.save_load_address`, which is the only
    number here that comes from a table, and the two fields derived from it
    are checked against the operands `NEWECL` itself uses.
    """

    def __init__(self, game: games.Game, disks: str, base: int = 0x0800):
        _, body = newecl.load("DUNGEON", disks, game)
        self.base, self.body = base, body
        call, lo_t, hi_t, opcode_at = newecl.dispatch_tables(body, base)
        self.opcode_byte = opcode_at
        self.handler = newecl.handler(body, base, lo_t, hi_t,
                                      newecl.NEWECL_OPCODE)
        lines = newecl.instructions(body, base, self.handler, 0x40)
        self.tail = newecl.newecl_tail(lines)
        # The handler's own operands are the writes, so take them from there.
        # `LDA $xxxx / AND #$7F / STA $yyyy` opens it: the first is the cache
        # slot, the second where the departing id is left.
        self.slot = int(lines[0][2][5:], 16)
        self.came_from = int(lines[2][2][5:], 16)
        self.scratch = next(int(t[5:9], 16) for _, _, t in lines
                            if t.startswith("STA $") and t.endswith(",X"))
        test = newecl.find_window(body, base, newecl.KEY_WAIT_SIG, "key-wait")
        if not test:
            raise SystemExit("DUNGEON's key-wait loop is not where its page-3 "
                             "signature says; nothing below can be trusted.")
        self.key_wait = newecl.loop_start(body, base, test)
        # The indoors flag is what the position flush tests before copying
        # `$C04B` into the save, and the flush is the handler's own tail call.
        flush = int(lines[[i for i, ln in enumerate(lines)
                           if ln[0] == self.tail][0]][2][5:], 16)
        self.indoors = int(newecl.instructions(body, base, flush, 4)[0][2][5:],
                           16)
        # `LINKER`'s first two absolute operands are the mode flag and the
        # disk byte; they are base-independent, so `LINKER`'s own load address
        # never has to be known.
        _, lk = newecl.load("LINKER", disks, game)
        loads = [t for _, _, t in newecl.instructions(lk, 0, 0, 0x20)
                 if t.startswith(("LDA $", "STA $")) and "," not in t]
        self.mode = int(loads[0][5:], 16)
        # The disk byte is the flag's neighbour -- `$6E11`/`$6E12` in Pool of
        # Radiance, `$7F11`/`$7F12` here -- and Curse's `LINKER` names it in
        # its own prologue, which Pool of Radiance's does not have. Prefer
        # what the file says and fall back to the neighbour, recording which.
        self.disk = next((int(t[5:], 16) for t in loads[1:]
                          if int(t[5:], 16) == self.mode + 1), self.mode + 1)
        self.disk_named = any(t.endswith(f"${self.disk:04X}") for t in loads[1:])
        _, lib = newecl.load("LIBRARY", disks, game)
        called = next(int(t[5:], 16) for _, _, t
                      in newecl.instructions(body, base, self.key_wait[0], 0x10)
                      if t.startswith("JSR $"))
        off = lib.find(newecl.KEY_FETCH_SIG)
        self.key_fetch = (called, newecl.reachable_end(lib, called - off,
                                                       called))

    def as_dict(self) -> dict:
        return {
            "handler": self.handler, "tail": self.tail, "slot": self.slot,
            "came_from": self.came_from, "scratch": self.scratch,
            "indoors": self.indoors, "mode": self.mode, "disk": self.disk,
            "key_wait": list(self.key_wait), "key_fetch": list(self.key_fetch),
            "opcode_byte": self.opcode_byte,
        }

    def describe(self) -> str:
        return (f"mode ${self.mode:04X}  disk ${self.disk:04X}  "
                f"slot ${self.slot:04X}  came-from ${self.came_from:04X}  "
                f"scratch ${self.scratch:04X}  indoors ${self.indoors:04X}  "
                f"NEWECL ${self.handler:04X} tail ${self.tail:04X}  "
                f"key-wait ${self.key_wait[0]:04X}-${self.key_wait[1]:04X}  "
                f"fetch ${self.key_fetch[0]:04X}-${self.key_fetch[1]:04X}")


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
      the same thing `tools/curserun.py` found for the release's start-up
      check.

    Written here rather than in `tools/session.py`, which is Pool of
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


def enter_world(sess, timeout: float = 300.0) -> bool:
    """Take a loaded party from the formation menu into the world.

    `Session.begin_adventuring` picks the row once and then waits, and two
    things get in the way of that here, both recorded rather than guessed:

    * **A disk prompt can be up when the row is picked.**  Loading the party
      pulls in side 2, so `INSERT SIDE # 2, AND PRESS ANY KEY.` sits over the
      menu; a pick made then opened a submenu and lost `BEGIN ADVENTURING`
      off the screen entirely (`work/issue19/warp1`).
    * **The screen goes blank while the area draws.**  1024 zeroes is not a
      menu that needs a keypress, and pressing one into it is how a run ends
      up somewhere nobody can name.

    So: act only on what is on screen, press nothing at a blank screen, and
    back out with Escape only when some *other* menu has been sitting there
    unchanged for `STUCK` seconds.
    """
    STUCK = 15.0
    deadline = time.time() + timeout
    seen, since = "", time.time()
    while time.time() < deadline:
        s = sess.screen()
        if s is None:
            time.sleep(0.5)
            continue
        text = s.text()
        if "ENCAMP" in text:
            return True
        if sess.handle_prompt(s):
            time.sleep(1.5)
            continue
        state = ("BEGIN" if "BEGIN ADVENTURING" in text
                 else "(blank)" if not text.strip("@ \n") else s.row(24).strip())
        if state != seen:
            sess.log(f"  world: {state!r}")
            seen, since = state, time.time()
        if state == "BEGIN":
            sess.select_row("BEGIN ADVENTURING")
            sess.press_kernal(0x0D)
        elif state != "(blank)" and time.time() - since > STUCK:
            sess.log("  world: backing out with Escape")
            sess.kbd.key("Escape")
            since = time.time()
        time.sleep(1.5)
    return False


def clear_messages(sess, timeout: float = 120.0) -> str:
    """Answer the arriving script's messages until the command bar is back.

    An arrival has a scene in front of it -- warping into area `$03` printed
    four lines about the Tilverton sewers and then
    `PRESS BUTTON OR RETURN TO CONTINUE.` -- and a party behind a message is
    not yet a party that can be shown to walk.  Returns whatever row 24 says
    when it stops.
    """
    deadline = time.time() + timeout
    seen = ""
    while time.time() < deadline:
        s = sess.screen()
        if s is None:
            time.sleep(0.5)
            continue
        bar = s.row(24).strip()
        if bar != seen:
            sess.log(f"  bar: {bar!r}")
            seen = bar
        if "ENCAMP" in bar:
            return bar
        if sess.handle_prompt(s):
            time.sleep(1.0)
            continue
        if "CONTINUE" in bar or "MORE" in bar or "PRESS" in bar:
            sess.press_kernal(0x0D)
        time.sleep(1.0)
    return f"(never got the command bar back; last {seen!r})"


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
    of Radiance, and `tools/newecl.py` for why the same order is Curse's.
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


def run(args) -> int:
    game = games.CURSE_OF_THE_AZURE_BONDS
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
            staged = pathlib.Path(slot.dir) / "SAVE_IN.D64"
            shutil.copy(save, staged)
            save = str(staged)
        # **`tools/session.py` is Pool of Radiance's, and one of its module
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
        if not enter_world(sess):
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
    ap.add_argument("--force", action="store_true",
                    help="warp even from the travel grid, which is expected "
                         "to wedge the loader")
    ap.add_argument("--out", default="work/issue19/run",
                    help="where captures go (default: %(default)s)")
    args = ap.parse_args(argv[1:])
    if not args.disks or not os.path.isdir(args.disks):
        print("No Curse disks. Set $POR_DISKS or pass --disks.",
              file=sys.stderr)
        return 2
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
