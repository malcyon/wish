#!/usr/bin/env python3
"""Watch `$49E7`-`$49E9` pin two wall pieces, and watch the next area draw them.

`#179 (Warping out of Valhingen Graveyard or Valjevo Castle leaves two wall
pieces unrelocated)` was filed off the bytecode and fixed off the bytecode.
This is the run that watches it happen.

`ECL0A` entry 4 -- "after loading" -- opens with `SAVE 1, [$49E7]` and
`SAVE 1, [$49E8]`, unconditionally, so **every** load of the graveyard's
script sets the pins, a fast travel included.  `DUNGEON $14CB` then reads
`$49E7,X` before unpacking wall piece `X`, so the next area keeps the
graveyard's screen codes for pieces 0 and 1.

The comparison is made at an ordinary indoor area rather than at the travel
grid, and that is the correction this run makes to the issue's own Testing
section: `ECL1A` entry 4 issues no `LOADPIECES` at all, so arriving on the
travel grid touches `$ED50` by neither route and `cmp -l` there is empty.  The
damage only shows one hop later, where something does unpack wall pieces.

    tools/wallpins.py --slot 2 --out work/issue179

Three arrivals at Podol Plaza's own arrival square, so the pictures compare:

  * `01-podol-control`  -- warped in from the Slums, pins clear
  * `03-podol-broken`   -- warped in from the graveyard with the pins left set,
    which is the fault: the write list is `newecl_writes` minus its `$49E7`
    entry, built here rather than by reverting the fix
  * `05-podol-fixed`    -- warped in from the graveyard with the whole of
    `newecl_writes`, which is what wish ships

Nothing is written to the player's disks: `stage_disks` copies the sides into
the slot and `Session.attach` refuses a path outside it.  The pool owns the
emulator -- claim, launch, tear down.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import struct
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap import actions as A  # noqa: E402
from automap.paths import find_disks  # noqa: E402
from tools import session as S  # noqa: E402

DISKS = pathlib.Path(os.environ.get("POR_DISKS") or find_disks() or "")

GRAVEYARD, PODOL, SLUMS, GRID = 10, 18, 20, 26

#: label -> (start, length, ram-under-the-kernal?).  `$ED50`-`$FF97` is where
#: `$1485` unpacks the three wall pieces, and it is under the KERNAL, so it
#: needs the monitor's `ram` bank rather than the CPU's view.
REGIONS = {
    "walls":  (0xED50, 0x1248, True),
    "pieces": (0x6500, 0x600, False),
    "cache":  (0x6E13, 0x19, False),
    "geo":    (0x0400, 0x400, False),
    "party":  (0x49C0, 0x60, False),
}

CMD_BANKS = 0x82


def bank_ids(mon) -> dict:
    resp = mon.command(CMD_BANKS, b"")
    count = struct.unpack("<H", resp[:2])[0]
    off, out = 2, {}
    for _ in range(count):
        size = resp[off]
        bid = struct.unpack("<H", resp[off + 1:off + 3])[0]
        n = resp[off + 3]
        out[resp[off + 4:off + 4 + n].decode("latin1")] = bid
        off += size + 1
    return out


class SessTarget:
    """`automap.actions`' Target contract over a driven session's monitor."""

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
            return m.registers().get(A.pc_register(m))

    def set_pc(self, address: int) -> None:
        with self.sess.mon(5) as m:
            m.set_registers({A.pc_register(m): address})


def pins(sess) -> list[int]:
    with sess.mon(5) as m:
        return list(m.read(A.WALL_SLOT_PINNED, A.WALL_SLOT_PINNED_LEN))


def wait_idle(sess, timeout: float = 300.0, need: int = 6) -> bool:
    """Wait until `DUNGEON` is back in its key-wait loop and stays there.

    A fixed settle measures this machine's floppy rather than the game: a
    capture taken while the arriving area's pieces are still coming off the
    disk reads them half loaded.
    """
    deadline = time.time() + timeout
    inloop = 0
    while time.time() < deadline:
        sess.settle(2)
        try:
            with sess.mon(5) as m:
                pc = m.registers().get(A.pc_register(m))
        except Exception:                       # noqa: BLE001
            pc = None
        idle = pc is not None and any(lo <= pc < hi
                                      for lo, hi in (A.KEY_WAIT, A.KEY_FETCH))
        inloop = inloop + 1 if idle else 0
        if inloop >= need:
            return True
    print("  NEVER went idle", flush=True)
    return False


def capture(sess, out: pathlib.Path, label: str, note: str = "") -> dict:
    meta = {"label": label, "note": note}
    with sess.mon(8) as m:
        banks = bank_ids(m)
        for name, (start, length, under) in REGIONS.items():
            bid = banks.get("ram", 0) if under else 0
            (out / f"{label}.{name}.bin").write_bytes(
                m.read(start, length, bank=bid))
        meta["6E11"] = m.read(0x6E11, 1)[0]
        meta["6E12"] = m.read(0x6E12, 1)[0]
        meta["C04B"] = list(m.read(0xC04B, 3))
    party = (out / f"{label}.party.bin").read_bytes()
    meta["pins"] = list(party[0x27:0x2A])       # $49E7-$49E9
    meta["49E6"] = party[0x26]
    meta["49F2"] = party[0x32]
    meta["cache"] = (out / f"{label}.cache.bin").read_bytes().hex(" ")
    s = sess.screen()
    if s is not None:
        meta["text"] = s.text()
    sess.kbd.screenshot(str(out / f"{label}.png"))
    print(f"[{label}] $49E7-$49E9={meta['pins']} $49F2={meta['49F2']} "
          f"$49E6={meta['49E6']} C04B={meta['C04B']}", flush=True)
    (out / f"{label}.json").write_text(json.dumps(meta, indent=1))
    return meta


def warp(sess, target, ft, area_id: int, repair: bool):
    """A fast travel, with or without the `$49E7`-`$49E9` repair.

    `repair=False` is the game as it was before `#179` was fixed, reproduced by
    building the write list here and dropping the one entry -- **not** by
    editing, reverting or checking out `automap/actions.py`, which several
    agents share.
    """
    row = A.area_by_id(area_id)
    arrival = ft.arrival_of(row)
    verdict = ft.legality(target, row)
    print(f"warp -> {row.name} arrival={arrival} repair={repair} "
          f"legal={verdict.ok} {'' if verdict.ok else verdict.reason}",
          flush=True)
    if not verdict.ok:
        raise RuntimeError(f"refused: {verdict.reason}")
    here = ft.current_area(target)
    writes = A.newecl_writes(here or 0, area_id, getattr(row, "disk", None),
                             arrival)
    if not repair:
        writes = tuple(w for w in writes if w[0] != A.WALL_SLOT_PINNED)
    print("  writes: " + ", ".join(f"${a:04X}={d.hex()}" for a, d in writes),
          flush=True)
    A._write_all(target, writes)
    if not A.jump(target, A.NEWECL_TAIL):
        raise RuntimeError("the program counter could not be set")
    wait_idle(sess)
    sess.settle(4)


def step_west(sess, target, ft, tries: int = 4) -> bool:
    """One step west off the graveyard's own west edge, on to the travel grid.

    The party arrives at `(0, 4)` facing west, and `ECL0A` entry 0 answers a
    step off that edge with `SAVE 0, [$49E7]` / `SAVE 0, [$49E8]` and
    `NEWECL 26`.  So the walked exit is one key, and it is the only walk this
    experiment needs.  Whether it happened is read off `$6E1B` rather than off
    the status line, which outdoors says `OUTDOORS` where the facing goes.
    """
    for attempt in range(tries):
        sess.leave_move(8)
        for _ in range(4):
            if sess.position()[2] == 3:
                break
            sess.walk_one("K")
            sess.settle(1)
        print(f"  attempt {attempt}: at {sess.position()} pins={pins(sess)}",
              flush=True)
        if not sess.select_bar("MOVE", timeout=10):
            continue
        time.sleep(0.6)
        sess.kbd.key("i", 0.15, 0.30)
        wait_idle(sess)
        sess.settle(4)
        if ft.current_area(target) == GRID:
            print(f"  walked out; pins={pins(sess)}", flush=True)
            return True
    return False


#: The travel grid's own square for the graveyard's entrance, read out of
#: `ECL1A`'s dispatch tables: `$B04A` the rows, `$B061` how many squares each
#: has, `$B053` the columns and `$B06A` the handler.  Rows 26 columns 12 and 13
#: both answer handler 2, whose menu's second option is `NEWECL 10`.
START, GATES = (11, 26), {(12, 26), (13, 26)}


def overland_key(sess, key: str, timeout: float = 20.0) -> bool:
    """Press one compass digit on the travel grid, whichever bar is showing.

    A walked exit lands with the movement prompt (`1-8, RETURN OR BUTTON`)
    already up, so `select_bar("MOVE")` finds no MOVE and gives up -- which is
    how the first run of this failed.  A warped arrival lands on the command
    bar and does need MOVE selecting first.  So look at row 24 and answer what
    is actually there.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        screen = sess.screen()
        row = screen.row(24) if screen is not None else ""
        if "1-8" in row:
            sess.kbd.key(key, 0.15, 0.30)
            return True
        if "MOVE" in row:
            if sess.select_bar("MOVE", timeout=10):
                time.sleep(0.6)
                sess.kbd.key(key, 0.15, 0.30)
                return True
        time.sleep(0.5)
    print(f"  neither a 1-8 prompt nor MOVE on row 24 within {timeout:.0f}s",
          flush=True)
    return False


def walk_into_graveyard(sess, target, ft, out) -> bool:
    """Step on to the graveyard's own overland square and take its menu.

    The party is put one square west of the entrance by writing `$49C3`/
    `$49C4` -- which is not the fault under test and not a value the game
    would object to: `#178 (Fast Travel to the wilderness leaves the party on
    whatever overland square it last stood on)` is the standing fact that a
    warp leaves that square arbitrary anyway.  **The step itself is walked**,
    so `ECL1A` entry 1 dispatches, the menu is the game's own, and `NEWECL 10`
    runs with its whole prologue.

    Which digit is east is not written down anywhere -- `#189 (The emulator
    driver cannot move a party on the travel grid, and reads its facing out of
    the word OUTDOORS)` is open, and `tools/outdoorwalk.py` records only that
    `8` and `4` each moved the party a square.  So the eight are tried in
    turn, the square put back to the start before each, and the one that lands
    on a gate square is the answer.
    """
    (sx, sy) = START
    for key in "63219874":
        with sess.mon(5) as m:
            m.write(0x49C3, bytes([sx, sy]))
        sess.settle(2)
        if sess.in_combat():
            print("  a random encounter started; stopping the walk", flush=True)
            return False
        if not overland_key(sess, key):
            return False
        here = (sx, sy)
        deadline = time.time() + 25
        while time.time() < deadline:
            with sess.mon(5) as m:
                here = tuple(m.read(0x49C3, 2))
            if here != (sx, sy):
                break
            time.sleep(0.5)
        print(f"  {key}: {sx},{sy} -> {here[0]},{here[1]}", flush=True)
        if here in GATES:
            break
    else:
        print("  no digit reached a gate square", flush=True)
        return False
    sess.settle(4)
    sess.kbd.screenshot(str(out / "08-graveyard-gate-menu.png"))
    screen = sess.screen()
    if screen is None:
        print("  no text screen at the gate", flush=True)
        return False
    words = screen.row(24).split()
    print(f"  the gate menu has {len(words)} option(s)", flush=True)
    if len(words) < 2:
        return False
    if not sess.select_bar(words[1], timeout=20):
        print("  the second option could not be selected", flush=True)
        return False
    wait_idle(sess)
    sess.settle(4)
    where = ft.current_area(target)
    print(f"  the menu led to area {where}", flush=True)
    return where == GRAVEYARD


def plan_walkin(sess, target, ft, out) -> int:
    """The player's own route: walk in through the entrance, then warp out.

    Split from the main plan because it needs the party on the travel grid
    first, and the only way to get there is to walk out of the graveyard --
    a warp from outdoors to an indoor area is refused, and rightly
    (`FastTravel.OUTDOORS_TRAP`).
    """
    warp(sess, target, ft, GRAVEYARD, True)
    capture(sess, out, "06-graveyard-for-the-walk", "about to walk out")
    if not step_west(sess, target, ft):
        raise RuntimeError("the walked exit west never left area 10")
    capture(sess, out, "07-grid-walked",
            "walked west out of the graveyard on to the travel grid")
    if not walk_into_graveyard(sess, target, ft, out):
        raise RuntimeError("the walk in through the real entrance failed")
    capture(sess, out, "09-graveyard-walked-in",
            "walked in from the travel grid through the real entrance")
    warp(sess, target, ft, PODOL, False)
    capture(sess, out, "10-podol-after-walkin",
            "warped out of a walked-into graveyard, no repair")
    return 0


def run(args) -> int:
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    slot = S.claim_slot(args.slot, "issue179 wall pins")
    print(f"Slot {slot.n} display {slot.display}", flush=True)
    sess = None
    try:
        boot = S.stage_disks(slot, DISKS)
        shutil.copy(pathlib.Path(args.disks) / args.save,
                    pathlib.Path(slot.dir) / "SIDE0.D64")
        for p in pathlib.Path(slot.dir).glob("*.D64"):
            os.chmod(p, 0o644)
        sess = S.Session(boot, slot=slot)
        if not sess.boot():
            raise RuntimeError("Boot failed")
        if not sess.load_save():
            raise RuntimeError("The game did not accept the disk")
        if not sess.select_row("BEGIN ADVENTURING"):
            raise RuntimeError("BEGIN ADVENTURING could not be selected")
        if sess.wait_text("MOVE", timeout=args.arrive)[0] is None:
            raise RuntimeError("No command bar after BEGIN ADVENTURING")
        sess.settle(4)
        target, ft = SessTarget(sess), A.FastTravel()
        capture(sess, out, "00-start", f"{args.save} just loaded")

        if args.plan == "walkin":
            return plan_walkin(sess, target, ft, out)

        warp(sess, target, ft, PODOL, True)
        capture(sess, out, "01-podol-control",
                "warped in from the loaded save, pins clear")

        warp(sess, target, ft, GRAVEYARD, True)
        capture(sess, out, "02-graveyard",
                "warped into Valhingen Graveyard; ECL0A entry 4 runs")

        warp(sess, target, ft, PODOL, False)
        capture(sess, out, "03-podol-broken",
                "warped out of the graveyard with the pins left set")

        warp(sess, target, ft, GRAVEYARD, True)
        capture(sess, out, "04-graveyard-again", "back in the graveyard")

        warp(sess, target, ft, PODOL, True)
        capture(sess, out, "05-podol-fixed",
                "warped out of the graveyard with $49E7-$49E9 zeroed")

        # The game's own clearing, watched: one step west off the graveyard's
        # edge runs `ECL0A $9932`/`$9938` and lands on the travel grid.
        warp(sess, target, ft, GRAVEYARD, True)
        capture(sess, out, "06-graveyard-for-the-walk", "about to walk out")
        if not step_west(sess, target, ft):
            raise RuntimeError('the walked exit west never left area 10')
        capture(sess, out, "07-grid-walked",
                "walked west out of the graveyard on to the travel grid")
        # A warp from the travel grid to an indoor area is refused --
        # `FastTravel.OUTDOORS_TRAP`, and rightly: it hangs the loader.  So
        # the party walks back in through the graveyard's real entrance
        # instead, which is also the only way to watch `ECL0A` entry 4 set the
        # pins on a journey the player could have made.
        if walk_into_graveyard(sess, target, ft, out):
            capture(sess, out, "09-graveyard-walked-in",
                    "walked in from the travel grid through the real entrance")
            warp(sess, target, ft, PODOL, False)
            capture(sess, out, "10-podol-after-walkin",
                    "warped out of a walked-into graveyard, no repair")
        else:
            print("  the walk in through the real entrance did not happen",
                  flush=True)
    finally:
        for what, fn in (("session", sess.terminate if sess else None),
                         ("slot teardown", slot.teardown),
                         ("slot release", slot.release)):
            if fn is None:
                continue
            try:
                fn()
            except Exception as e:              # noqa: BLE001
                print(f"  {what} failed: {e}", flush=True)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--disks", default=str(DISKS),
                   help="where the player's game disks are; read, never written")
    p.add_argument("--save", default="PORSAVE13.D64",
                   help="the save disk to copy in as SIDE0")
    p.add_argument("--slot", type=int, default=None, help="the pool slot")
    p.add_argument("--out", default=str(ROOT / "work" / "issue179"))
    p.add_argument("--plan", choices=("full", "walkin"),
                   default="full",
                   help="the whole comparison, or only the walk in")
    p.add_argument("--arrive", type=float, default=240.0)
    return run(p.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
