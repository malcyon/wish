#!/usr/bin/env python3
"""Warp to a wilderness window and try to walk off the square wish ships.

`#178 (Fast Travel to the wilderness leaves the party on whatever overland
square it last stood on)` was fixed by giving areas 25, 26 and 27 an
`overland` square in `goldbox/areas.py`, which `newecl_writes` now writes to
`$49C3`/`$49C4`.  Two of the three squares are named by a script.  **Window
25's is not**: (14, 29) is the column every westward seam crossing writes and
the row the other two windows arrive on, and nobody had ever stood on it.

Passability cannot be read off the disk: the impassable-terrain table's
address was in `work/reports/world-map.md`, which is lost (#136), so the
running game is the only authority left.  That is what this drives:

    tools/windowsquare.py --slot 0 --out work/issue178

For each window, in order: write `$49C3`/`$49C4` to a known wrong value so the
arrival cannot be the stale square, fast travel there through
`FastTravel.apply` (the shipped path, not a hand-built write list), read the
square back, photograph the screen, and then press each of the eight compass
digits in turn -- putting the party back on the arrival square before each --
recording which ones move it.

**The compass is clockwise from north**: 1 N, 2 NE, 3 E, 4 SE, 5 S, 6 SW,
7 W, 8 NW.  A square that can be left in at least one direction is not a trap.

Captures go to `work/`, which is gitignored; the tool does not.  Nothing is
written to the player's disks: `stage_disks` copies the sides into the slot
and `Session.attach` refuses a path outside it.  The pool owns the emulator --
claim, launch, tear down.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap import actions as A  # noqa: E402
from automap.paths import find_disks  # noqa: E402
from tools import session as S  # noqa: E402

DISKS = pathlib.Path(os.environ.get("POR_DISKS") or find_disks() or "")

WINDOWS = (25, 26, 27)

#: Clockwise from north, which is what the travel grid's own bar
#: (`1-8, RETURN OR BUTTON`) asks for.
COMPASS = {"1": "N", "2": "NE", "3": "E", "4": "SE",
           "5": "S", "6": "SW", "7": "W", "8": "NW"}

#: Written to `$49C3`/`$49C4` before every warp.  (0, 0) is outside the
#: walkable band and is the value `docs/140-loaded-files-cache.md` watched a
#: fast travel carry through unchanged, so a party that comes up on it is the
#: unfixed behaviour and a party on the table's square is the fix.
WRONG_SQUARE = (0, 0)


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


def wait_idle(sess, timeout: float = 300.0, need: int = 6) -> bool:
    """Wait until `DUNGEON` is back in its key-wait loop and stays there.

    A fixed settle measures this machine's floppy rather than the game.
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


def put(sess, square) -> None:
    """Stand the party on `square` by writing `$49C3`/`$49C4`."""
    with sess.mon(5) as m:
        m.write(A.FASTTRAVEL_TRAVEL_X, bytes(square))


def read_square(sess):
    with sess.mon(5) as m:
        return tuple(m.read(A.FASTTRAVEL_TRAVEL_X, 2))


def capture(sess, out: pathlib.Path, label: str, note: str = "") -> dict:
    meta = {"label": label, "note": note}
    with sess.mon(8) as m:
        meta["49C3"] = list(m.read(A.FASTTRAVEL_TRAVEL_X, 2))
        meta["49E6"] = m.read(A.FASTTRAVEL_INDOORS, 1)[0]
        meta["6E1B"] = m.read(A.FASTTRAVEL_SLOT, 1)[0]
        meta["6E12"] = m.read(A.FASTTRAVEL_DISK, 1)[0]
        meta["C04B"] = list(m.read(A.FASTTRAVEL_X, 3))
    s = sess.screen()
    if s is not None:
        meta["row24"] = s.row(24)
        meta["status"] = s.row(23)
        meta["text"] = s.text()
    sess.kbd.screenshot(str(out / f"{label}.png"))
    print(f"[{label}] $49C3={meta['49C3']} $49E6={meta['49E6']} "
          f"area={meta['6E1B'] & 0x7F} row24={meta.get('row24', '')!r}",
          flush=True)
    (out / f"{label}.json").write_text(json.dumps(meta, indent=1))
    return meta


def clear_menu(sess, out: pathlib.Path, label: str,
               wait: float = 12.0) -> str | None:
    """Answer an event menu if the square fired one, and say what it was.

    `docs/50-experiments.md` records that on DOS the WEST boat landing is the
    overland's own "boat back to Phlan" event, whose TAKE BOAT / STAY menu
    came up on arrival.  The same happens here, and it happens **again every
    time the party is put back on that square and a direction is pressed** --
    which is what made the first run of this read seven of window 26's eight
    directions as blocked when what was blocking them was an unanswered
    menu.  So this is called before the sweep and after every press that did
    not move the party.
    """
    deadline = time.time() + wait
    while time.time() < deadline:
        s = sess.screen()
        row = "" if s is None else s.row(24)
        if S.OUTDOOR_PROMPT in row or S.word_column(row, "MOVE") >= 0:
            return None
        if S.word_column(row, "STAY") >= 0:
            print(f"  an event menu is up: {row.strip()!r}; answering STAY",
                  flush=True)
            if label:
                sess.kbd.screenshot(str(out / f"{label}.menu.png"))
            sess.select_bar("STAY", timeout=20)
            wait_idle(sess, timeout=90)
            sess.settle(3)
            return row.strip()
        sess.handle_prompt(s)
        time.sleep(0.6)
    s = sess.screen()
    return None if s is None else s.row(24).strip()


def warp(sess, target, ft, out: pathlib.Path, area_id: int) -> dict:
    """One fast travel, through the shipped `FastTravel.apply`."""
    row = A.area_by_id(area_id)
    # A menu left on screen keeps the PC out of the key-wait loop, and
    # `FastTravel.legality` rightly refuses that -- which is how the first run
    # of this never reached window 27 at all.
    clear_menu(sess, out, "")
    sess.leave_outdoor_move(2)
    put(sess, WRONG_SQUARE)
    sess.settle(1)
    print(f"warp -> {row.name} overland={row.overland} "
          f"(from ${A.FASTTRAVEL_TRAVEL_X:04X}={WRONG_SQUARE})", flush=True)
    outcome = ft.apply(target, area=row)
    print(f"  {outcome.ok}: {outcome.message}", flush=True)
    for note in outcome.notes:
        print(f"  note: {note}", flush=True)
    if not outcome.ok:
        raise RuntimeError(f"refused: {outcome.message}")
    wait_idle(sess)
    sess.settle(4)
    return {"notes": list(outcome.notes),
            "writes": [[a, d.hex()] for a, d in outcome.writes]}


def press(sess, out: pathlib.Path, key: str, square,
          patience: float, tries: int = 3) -> tuple[bool, list[str]]:
    """One compass digit from `square`, answering the square's own event.

    On a landing square the first press re-opens the boat menu instead of
    moving, so a menu is answered and the digit pressed again.  A direction is
    only called blocked once a press that met no menu failed to move the
    party -- otherwise the driver would be reporting its own unanswered
    dialogue as impassable terrain, which is exactly what the first run did.
    """
    menus: list[str] = []
    for _ in range(tries):
        if sess.walk_outdoors(key, patience=patience):
            return True, menus
        menu = clear_menu(sess, out, "")
        if menu is None or S.word_column(menu, "STAY") < 0:
            return False, menus
        menus.append(menu)
        put(sess, square)
        sess.settle(2)
    return False, menus


def sweep(sess, out: pathlib.Path, tag: str, square, patience: float) -> dict:
    """Try all eight compass digits from `square`, resetting before each."""
    results = {}
    for key, name in COMPASS.items():
        if sess.in_combat():
            print("  a random encounter is on screen; stopping this sweep",
                  flush=True)
            results[key] = {"direction": name, "moved": None,
                            "note": "a random encounter interrupted the sweep"}
            break
        clear_menu(sess, out, "")
        put(sess, square)
        sess.settle(2)
        moved, menus = press(sess, out, key, square, patience)
        now = read_square(sess)
        combat = sess.in_combat()
        print(f"  {key} ({name}): {tuple(square)} -> {now}"
              f"{'  [menu answered]' if menus else ''}"
              f"{'  [combat]' if combat else ''}", flush=True)
        results[key] = {"direction": name, "from": list(square),
                        "to": list(now), "moved": bool(moved),
                        "menus": menus, "combat": bool(combat)}
        sess.kbd.screenshot(str(out / f"{tag}.step{key}.png"))
        if combat:
            results[key]["note"] = ("a random encounter started on this step; "
                                    "the square still moved")
            break
    clear_menu(sess, out, "")
    put(sess, square)
    sess.settle(2)
    return results


def visit(sess, target, ft, out: pathlib.Path, area_id: int,
          patience: float) -> dict:
    row = A.area_by_id(area_id)
    tag = f"{area_id}-{(row.name or '').split(', ')[-1].lower().replace(' ', '')}"
    record: dict = {"area": area_id, "name": row.name,
                    "shipped": list(row.overland)}
    record["warp"] = warp(sess, target, ft, out, area_id)
    record["menu"] = clear_menu(sess, out, f"{tag}-arrival")
    arrived = capture(sess, out, f"{tag}-arrival",
                      f"fast travel to {row.name}, $49C3 seeded {WRONG_SQUARE}")
    record["arrived"] = arrived["49C3"]
    record["indoors"] = arrived["49E6"]
    record["status_line"] = arrived.get("status", "").strip()
    record["on_the_shipped_square"] = arrived["49C3"] == list(row.overland)
    if not record["on_the_shipped_square"]:
        print(f"  ARRIVED ON {arrived['49C3']}, NOT {list(row.overland)}",
              flush=True)
    record["steps"] = sweep(sess, out, tag, tuple(row.overland), patience)
    record["moved"] = sorted(k for k, v in record["steps"].items()
                             if v.get("moved"))
    print(f"  {row.name}: {len(record['moved'])} of 8 directions moved the "
          f"party", flush=True)
    return record


def run(args) -> int:
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    areas = [int(a) for a in args.areas.split(",")]
    slot = S.claim_slot(args.slot, "issue178 window arrival squares")
    print(f"Slot {slot.n} display {slot.display}", flush=True)
    sess, report = None, {"save": args.save, "areas": []}
    try:
        boot = S.stage_disks(slot, pathlib.Path(args.disks), save=args.save)
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
        for area_id in areas:
            try:
                report["areas"].append(
                    visit(sess, target, ft, out, area_id, args.patience))
            except Exception as e:              # noqa: BLE001
                print(f"  {area_id} failed: {e}", flush=True)
                report["areas"].append({"area": area_id, "failed": str(e)})
    finally:
        (out / "report.json").write_text(json.dumps(report, indent=1))
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
    p.add_argument("--out", default=str(ROOT / "work" / "issue178"))
    p.add_argument("--areas", default=",".join(str(a) for a in WINDOWS),
                   help="which wilderness windows to visit, in order")
    p.add_argument("--patience", type=float, default=25.0,
                   help="seconds to wait for one overland step to land")
    p.add_argument("--arrive", type=float, default=240.0)
    return run(p.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
