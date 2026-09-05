#!/usr/bin/env python3
"""Watch the Kobold Caves' exit take an NPC out of the party, and watch a fast
travel not take her.

`#180 (What the Kobold Caves exit does to an NPC in the party is not
understood, and Fast Travel skips it)` is the ticket.  `ECL0D` dispatches
square-attribute id 28 -- `GEO0D` (6,15) and (10,15) -- to `$99C1`, which asks
whether to leave, walks the eight party slots looking for one character by
name, and on finding her zeroes `$6B00` (the name) and `$6C00` (the roster
status) and writes the emptied record back with `LOADCHAR slot | 128`.  A fast
travel enters `NEWECL` at its tail, `$2034`, past all of it.

    tools/koboldnpc.py --plan walk --out work/issue180/walk
    tools/koboldnpc.py --plan warp --out work/issue180/warp

Both plans boot the **same** save disk and end in area 27, so exactly one
thing differs between the two captures: how the party left area 13.  The save
has to be a party standing inside the Kobold Caves with an NPC in it;
`npc_party.d64` is one -- `$4BC2` = `$0D`, `$49E6` = 1 -- and is the default.

The party is put on (6,14) facing south by writing `$C04B`-`$C04D` before the
walk, which is the same teleport a fast travel makes and is not the thing
under test: driving a maze from wherever the save happens to sit would take
the run's whole budget and change nothing about which statements run.  **The
step itself is walked**, so the game's own dispatch reaches `$99C1`.

Nothing is written to the player's disks: `stage_disks` copies the sides into
the slot and `Session.attach` refuses a path outside it.  The pool owns the
emulator -- claim, launch, tear down.  Captures go to `work/`, which is
gitignored; the tool does not.
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

from automap import actions as A  # noqa: E402
from automap.paths import find_disks  # noqa: E402
from tools import session as S  # noqa: E402

DISKS = pathlib.Path(os.environ.get("POR_DISKS") or find_disks() or "")

#: The Kobold Caves, and the wilderness east window its exit leads to.
CAVES, EAST = 13, 27

#: `GEO0D` square-attribute id 28 sits on (6,15) and (10,15); the party is
#: placed one square north of the first and stepped on to it.
BEFORE = (6, 14, 2)

#: `$4D00 + slot * $100` is the master character record and `$8300 +
#: slot * $20` the master roster block -- `LIBRARY $312B` and `$3140` compute
#: exactly those two pointers, and `LOADCHAR` copies to and from them.
SLOT_RECORD, SLOT_ROSTER, SLOTS = 0x4D00, 0x8300, 8


def wait_idle(sess, timeout: float = 300.0, need: int = 6) -> bool:
    """Wait until `DUNGEON` is back in its key-wait loop and stays there.

    A fixed settle measures this machine's floppy rather than the game.  Taken
    from `tools/wallpins.py`, which needed it for the same reason.
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


def _name(raw: bytes) -> str:
    """A record's name field as text, stopping at the first zero.

    A zero first byte is how the engine marks a slot empty -- that is the
    whole measurement, so it is reported as `<empty>` rather than dropped.
    """
    if not raw or raw[0] == 0:
        return "<empty>"
    out = raw.split(b"\x00")[0]
    return "".join(chr(c) if 32 <= c < 127 else "." for c in out)


def party(sess) -> list[dict]:
    """The eight master slots: name, the NPC flag, the roster status byte."""
    rows = []
    with sess.mon(8) as m:
        for i in range(SLOTS):
            rec = m.read(SLOT_RECORD + i * 0x100, 0x100)
            ros = m.read(SLOT_ROSTER + i * 0x20, 0x20)
            rows.append({"slot": i, "name": _name(rec[:16]),
                         "name0": rec[0], "flags_0b8": rec[0xB8],
                         "status": ros[0]})
    return rows


def capture(sess, out: pathlib.Path, label: str, note: str = "") -> dict:
    meta = {"label": label, "note": note}
    with sess.mon(8) as m:
        meta["6E11"] = m.read(0x6E11, 1)[0]
        meta["6E12"] = m.read(0x6E12, 1)[0]
        meta["6E1B"] = m.read(0x6E1B, 1)[0]
        meta["49E6"] = m.read(0x49E6, 1)[0]
        meta["C04B"] = list(m.read(0xC04B, 3))
        meta["49C0"] = list(m.read(0x49C0, 3))
        meta["49C3"] = list(m.read(0x49C3, 2))
        resident = m.read(0x6B00, 0x100)
        meta["6B00"] = _name(resident[:16])
        meta["6B00.0"] = resident[0]
        meta["6C00"] = list(m.read(0x6C00, 0x20))
    meta["party"] = party(sess)
    screen = sess.screen()
    if screen is not None:
        meta["text"] = screen.text()
        meta["row24"] = screen.row(24)
    sess.kbd.screenshot(str(out / f"{label}.png"))
    (out / f"{label}.json").write_text(json.dumps(meta, indent=1))
    live = ", ".join(f"{r['slot']}:{r['name']}"
                     f"{'*' if r['flags_0b8'] & 0x80 else ''}"
                     for r in meta["party"])
    print(f"[{label}] area={meta['6E1B'] & 0x7F} $49E6={meta['49E6']} "
          f"square={meta['C04B']} overland={meta['49C3']}\n"
          f"          party: {live}", flush=True)
    return meta


def answer_the_exit(sess, target, out: pathlib.Path,
                    budget: float = 180.0) -> bool:
    """Drive whatever the exit puts on row 24 until the area has changed.

    The exit prints a question, offers two words, then prints seventy-two more
    bytes, and each of those may want a keypress.  Rather than guessing the
    sequence, read row 24 and answer what is there -- the same shape as
    `tools/wallpins.py`'s `overland_key`.
    """
    deadline, shots, seen = time.time() + budget, 0, []
    while time.time() < deadline:
        if A.FastTravel.current_area(target) == EAST:
            return True
        screen = sess.screen()
        row = screen.row(24).strip() if screen is not None else ""
        if row and (not seen or seen[-1] != row):
            seen.append(row)
            shots += 1
            sess.kbd.screenshot(str(out / f"walk-bar-{shots:02d}.png"))
            print(f"  row 24: {row!r}", flush=True)
        words = row.split()
        if "YES" in words and "NO" in words:
            if not sess.select_bar("YES", timeout=20):
                print("  YES could not be selected", flush=True)
                return False
            time.sleep(1.0)
            continue
        if "PRESS" in row or "RETURN" in row or "BUTTON" in row:
            sess.press_kernal(0x0D)
            time.sleep(1.0)
            continue
        time.sleep(0.8)
    print(f"  the area never became {EAST}", flush=True)
    return False


def plan_walk(sess, target, out) -> int:
    """Step on to the exit square and take the game's own way out."""
    with sess.mon(5) as m:
        m.write(0xC04B, bytes(BEFORE))
    sess.settle(2)
    print(f"  placed at {BEFORE} (x, y, facing)", flush=True)
    capture(sess, out, "01-on-the-exit-approach",
            "one square north of GEO0D (6,15), facing south")
    if not sess.select_bar("MOVE", timeout=20):
        raise RuntimeError("MOVE could not be selected")
    time.sleep(0.6)
    sess.kbd.key("i", 0.15, 0.30)
    if not answer_the_exit(sess, target, out):
        raise RuntimeError("the walked exit never reached area 27")
    wait_idle(sess)
    sess.settle(4)
    capture(sess, out, "02-walked-out",
            "walked south out of the Kobold Caves through ECL0D $99C1")
    return 0


def plan_warp(sess, target, out) -> int:
    """The same journey as a fast travel, which enters `NEWECL` at `$2034`."""
    area = A.area_by_id(EAST)
    ft = A.FastTravel()
    verdict = ft.legality(target, area)
    print(f"  legality: {verdict.ok} {'' if verdict.ok else verdict.reason}",
          flush=True)
    if not verdict.ok:
        raise RuntimeError(f"refused: {verdict.reason}")
    outcome = ft.apply(target, area=area)
    print("  " + outcome.message, flush=True)
    if not outcome.ok:
        raise RuntimeError(outcome.message)
    wait_idle(sess)
    sess.settle(4)
    capture(sess, out, "02-warped-out",
            "fast travelled out of the Kobold Caves to the same area 27")
    return 0


def run(args) -> int:
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    slot = S.claim_slot(args.slot, "issue180 kobold caves NPC")
    print(f"Slot {slot.n} display {slot.display}", flush=True)
    sess = None
    try:
        boot = S.stage_disks(slot, DISKS)
        shutil.copy(pathlib.Path(args.save).expanduser(),
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
        target = SessTarget(sess)
        meta = capture(sess, out, "00-start",
                       f"{pathlib.Path(args.save).name} just loaded")
        here = meta["6E1B"] & 0x7F
        if here != CAVES:
            raise RuntimeError(f"the save is in area {here}, not the Kobold "
                               f"Caves ({CAVES})")
        return plan_walk(sess, target, out) if args.plan == "walk" \
            else plan_warp(sess, target, out)
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


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--plan", choices=("walk", "warp"), default="walk")
    p.add_argument("--save", default="~/Downloads/npc_party.d64",
                   help="a save disk whose party is inside the Kobold Caves "
                        "with an NPC in it; copied in as SIDE0")
    p.add_argument("--slot", type=int, default=None, help="the pool slot")
    p.add_argument("--out", default=str(ROOT / "work" / "issue180"))
    p.add_argument("--arrive", type=float, default=240.0)
    return run(p.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
