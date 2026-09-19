#!/usr/bin/env python3
"""Boot the generated test party in VICE and read all six sheets off the screen.

`docs/119-test-party.md` §6's third gate, and the only one that is evidence
about the game: `tools/testparty.py` builds a party out of our own tables, and
a test that reads those bytes back through the same tables passes whether or
not the game agrees.  This asks the C64 instead.  The name, class, level, hit
points, armour class and THAC0 come back through the game's own character-sheet
routine and its own charset, which shares nothing with `goldbox/layout.py`.

    tools/testpartyrun.py --disk path/to/TESTPARTY.D64

**Nothing is written to the player's disks.**  `--disk` is a copy
`tools/testparty.py` already made; `tools/session.stage_disks` copies the eight
sides and that save into the pool slot's own directory, and `Session.attach`
refuses any path outside it.  `POR_HEADLESS` is the slot's default, so no
window lands on the desktop.

Every event goes to `run.jsonl` as it happens rather than into a summary a
killed run never reaches, and each sheet is photographed while it is up --
which is the only moment it can be, since `Session.character_sheet` leaves the
sheet before it returns.

**Interrupt this with SIGINT and not SIGTERM**, so the `finally` gets to free
the slot.

`--full` adds the four remaining `#10 (Finish the high-level test party)`
questions the 2026-09-09T03:00:20Z comment named as sharing one boot:

    tools/testpartyrun.py --disk path/to/TESTPARTY-ARMED.D64 --full \\
        --out DIR

1. the six sheets (as above), now armed;
2. `REMOVE CHARACTER FROM PARTY` on BULWARK, from the party menu, before
   `BEGIN ADVENTURING` -- the file the game writes is the `0x119` evidence,
   and he is re-added with `ADD CHARACTER TO PARTY` so the world portion still
   has all six (`docs/121-silver-blades.md` names the same two commands on
   the sibling engine; the party menu cannot be reached again once
   adventuring has begun, so this has to happen first);
3. un-ready then re-ready PILFER's `LEATHER ARMOR +4`, and ready then
   un-ready BULWARK's `TWO-HANDED SWORD +1 +3 VS UNDEAD`, each read at
   `$8300 + slot * 0x20` for 32 bytes before and after
   (`goldbox.savegame.RosterBlock`, `tools/traitask.py`'s own item-list
   driving);
4. walk until something ambushes the party and screenshot the fight, which is
   the only way to see the icons `tools/testparty.py --disk` (no
   `--keep-icons`) cleared actually drawn.
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

from automap.paths import find_disks  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from goldbox.savegame import SLOT_AREA_BASE, SLOT_STRIDE  # noqa: E402
from tools import scratch  # noqa: E402
from tools import session as S  # noqa: E402
from tools.c64addprobe import answer as answer_yn  # noqa: E402
from tools.c64nametable import character_files  # noqa: E402
from tools.traitask import (  # noqa: E402
    ROSTER_STRIDE,
    SAVE1_LOAD,
    leave_items,
    open_items,
    toggle_item,
)

DISKS = pathlib.Path(os.environ.get("POR_DISKS") or find_disks() or "")

#: Pool of Radiance's own prefix byte for a parked character's filename
#: (`tools/c64nametable.py`'s `PREFIX`).
POR_PREFIX = 0x01


class Log:
    """One JSON line per event, written as it happens."""

    def __init__(self, out: pathlib.Path, quiet: bool = False) -> None:
        out.mkdir(parents=True, exist_ok=True)
        self.dir = out
        self.file = open(out / "run.jsonl", "w")
        self.quiet = quiet

    def emit(self, kind: str, **what) -> None:
        self.file.write(json.dumps({"t": round(time.time(), 3),
                                    "event": kind, **what}) + "\n")
        self.file.flush()

    def say(self, line: str) -> None:
        if not self.quiet:
            print(line, flush=True)

    def close(self) -> None:
        self.file.close()


# -- the four extra questions -------------------------------------------------

def dump(sess, out: pathlib.Path, log: Log, tag: str) -> None:
    """A screenshot and the screen text, named for the step that made it."""
    s = sess.screen()
    rows = [] if s is None else [r.rstrip() for r in s.rows()]
    log.emit("screen", tag=tag, rows=rows)
    sess.kbd.screenshot(str(out / f"{tag}.png"))


def remove_and_readd(sess, log: Log, out: pathlib.Path, name: str) -> bytes | None:
    """`REMOVE CHARACTER FROM PARTY` on `name`, keep the file the game wrote,
    then `ADD CHARACTER TO PARTY` to put him straight back.

    **This has to happen before `BEGIN ADVENTURING`.**  The party menu that
    offers both commands is the one `LOAD SAVED GAME` returns to; once the
    party has set out there is no route back to it short of a fresh load, so
    this is the one of the four questions that cannot share the *world*
    portion of the boot, only the disk and the party.

    Returns the exported `.CHR` bytes (the file `\\x01BULWARK` on the C64,
    `tools/c64nametable.py`'s `PREFIX` for Pool of Radiance), or None if the
    remove never produced one.
    """
    dump(sess, out, log, "party-menu")
    if not sess.select_row("REMOVE CHARACTER FROM PARTY", timeout=25.0):
        log.say("  REMOVE CHARACTER FROM PARTY not found on the party menu")
        return None
    sess.settle(3)
    dump(sess, out, log, "remove-list")
    if not sess.select_row(name, timeout=25.0):
        log.say(f"  {name} not found on the remove list")
        return None
    sess.settle(3)
    dump(sess, out, log, f"asked-{name}")
    # NO keeps the disk that is already in the drive; YES would format a
    # fresh one, which is not the disk this run staged.
    answer_yn(sess, "NO")
    sess.settle(4)
    dump(sess, out, log, f"removed-{name}")

    disk = D64.open(sess.save_disk)
    files = character_files(disk, POR_PREFIX)
    raw = None
    if name in files:
        for entry in disk.iter_directory():
            if entry.name.decode("latin1").rstrip("\xa0 ")[1:] == name:
                raw = disk.read_file(entry)
                break
    log.emit("removed", name=name, parked_files=files, exported=raw is not None)
    log.say(f"  parked files after remove: {files}; exported {name}: "
            f"{raw is not None}")

    if not sess.select_row("EXIT", timeout=15.0):
        log.say("  EXIT off the remove list did not take")
    sess.settle(3)
    dump(sess, out, log, "after-remove-exit")

    if not sess.select_row("ADD CHARACTER TO PARTY", timeout=25.0):
        log.say("  ADD CHARACTER TO PARTY not found on the party menu")
        return raw
    sess.settle(4)
    dump(sess, out, log, "add-bar")
    # The bar offers a source game each add list is read from -- Pool of
    # Radiance keeps no such choice; if one is on row 24 it is answered by
    # whatever word is not EXIT.
    s = sess.screen()
    bar = "" if s is None else s.row(24).strip()
    if bar and "EXIT" in bar and bar != "EXIT":
        word = next((w for w in bar.split() if w != "EXIT"), None)
        if word:
            sess.select_bar(word, timeout=15.0)
            sess.settle(3)
    dump(sess, out, log, "add-list")
    if not sess.select_row(name, timeout=25.0):
        log.say(f"  {name} not offered on the add list")
        return raw
    sess.settle(3)
    dump(sess, out, log, f"asked-add-{name}")
    answer_yn(sess, "NO")
    sess.settle(4)
    dump(sess, out, log, f"added-{name}")
    if not sess.select_row("EXIT", timeout=15.0):
        log.say("  EXIT off the party menu did not take")
    log.say(f"  re-added {name}")
    return raw


def roster_bytes(sess, slot_index: int) -> bytes:
    """The 32-byte roster block at `$8300 + slot_index * 0x20`."""
    with sess.mon(8) as m:
        raw = m.read(SAVE1_LOAD + slot_index * ROSTER_STRIDE, ROSTER_STRIDE)
        m.resume()
    return raw


def slot_index_for(sess, name: str) -> int | None:
    """Which save slot (0-7) holds `name`, read live off `SAVEDGAME0`.

    Independent of the party panel's marching order, and independent of
    whatever `REMOVE`/`ADD CHARACTER` did to the slot layout -- this reads the
    name each slot's own record stores.
    """
    with sess.mon(8) as m:
        raw = m.read(SLOT_AREA_BASE, SLOT_STRIDE * 8)
        m.resume()
    for i in range(8):
        chunk = raw[i * SLOT_STRIDE:i * SLOT_STRIDE + 16]
        stored = chunk.split(b"\0", 1)[0].decode("ascii", "replace").strip()
        if stored == name:
            return i
    return None


def item_toggle_pair(sess, log: Log, out: pathlib.Path, name: str,
                     label: str, tag: str,
                     sequence: "list[str] | None" = None) -> list[dict]:
    """Toggle READY for `name`, reading the roster block at
    `$8300 + slot * 0x20` before and after each press.

    `sequence` names one label per press, in order; the default is `label`
    twice, which leaves that item's readied state as it started -- an
    un-ready/re-ready pair for something already readied, a ready/un-ready
    pair for something that was not.  A longer sequence is for a character
    whose target item cannot be readied on its own, such as a two-handed
    weapon while a shield is already worn: un-ready the shield, ready the
    weapon, then reverse both, and every step is still a before/after roster
    read rather than an assumption about why the direct toggle refused.
    """
    diffs: list[dict] = []
    steps = sequence or [label, label]
    slot = slot_index_for(sess, name)
    if slot is None:
        log.say(f"  {name} not found in the live roster; cannot toggle {label}")
        return diffs
    # A screenshot of whatever the game is showing right before this tries
    # to put the party-panel highlight on `name` -- diagnostic only, no keys
    # sent, so a failure below can be read back rather than guessed at.
    dump(sess, out, log, f"{tag}-precheck")
    # `leave_items`'s last `EXIT` targets camp's own bar to leave camp
    # entirely, and after one character's item list that bar reads
    # `ENCAMP:SAVE VIEW MAGIC REST ALTER EXIT` -- **camp's own command bar**,
    # a compound word exactly like the sheet's own `VIEW:ITEMS`, not the
    # plain world bar `MOVE VIEW CAST AREA ENCAMP SEARCH LOOK`.  Pool of
    # Radiance was measured on 2026-09-16 to leave the game sitting there
    # rather than back on the world, so the next `open_items` call reads
    # `ENCAMP` in that compound word, presses it, and opens the wrong menu.
    # Leaving by name rather than assuming the last call already did.
    s = sess.screen()
    if s is not None and s.row(24).strip().startswith("ENCAMP:"):
        log.say("  still on camp's own bar; leaving by EXIT before "
                f"opening {name}'s items")
        sess.select_bar("EXIT", timeout=10)
        sess.settle(2)
        dump(sess, out, log, f"{tag}-left-camp")
    opened = open_items(sess, log, name, steps[0], tag)
    if not opened:
        # One retry, after a longer settle: `panel_index` reads a live
        # screenshot, and the world panel has come back not-yet-redrawn
        # often enough in this run that a second try costs little against
        # losing the whole measurement to one slow frame.
        dump(sess, out, log, f"{tag}-open-failed-1")
        sess.settle(4)
        opened = open_items(sess, log, name, steps[0], tag)
    if not opened:
        dump(sess, out, log, f"{tag}-open-failed-2")
        log.say(f"  could not open the item list for {name}")
        return diffs
    for n, step_label in enumerate(steps):
        before = roster_bytes(sess, slot)
        ok = toggle_item(sess, log, step_label, f"{tag}{n}")
        sess.settle(1)
        after = roster_bytes(sess, slot)
        diff = [{"offset": f"0x{i:02X}", "was": b, "now": a}
                for i, (b, a) in enumerate(zip(before, after)) if b != a]
        rec = {"name": name, "label": step_label, "n": n, "pressed": ok,
              "slot": slot, "before": before.hex(), "after": after.hex(),
              "diff": diff}
        diffs.append(rec)
        log.emit("toggle", **rec)
        log.say(f"  {name} {step_label} toggle {n}: pressed={ok} diff={diff}")
    leave_items(sess)
    sess.settle(1)
    return diffs


def pick_a_fight(sess, log: Log, out: pathlib.Path, steps: int = 150) -> dict:
    """Walk until the party is ambushed, and photograph the fight.

    Wall-following rather than a fixed pattern: go forward while it works,
    turn (alternating left and right so a dead end does not send this back
    the way it came) the moment a step is refused.  A first attempt with a
    fixed `IIIIJIIII` cycle spent 80 moves getting from (9, 13) to (8, 13) --
    one tile -- because most of the forward presses were walls and the turns
    never pointed it anywhere new twice in a row (a scratch run directory,
    2026-09-16, deleted).  A wall refusing a step is not an error here, just the
    signal to turn.
    """
    taken = 0
    turn = "J"
    while taken < steps and not sess.in_combat():
        moved = sess.walk_one("I")
        sess.handle_prompt()
        taken += 1
        if not moved and taken < steps and not sess.in_combat():
            sess.walk_one(turn)
            sess.handle_prompt()
            taken += 1
            turn = "K" if turn == "J" else "J"
    fighting = sess.in_combat()
    log.emit("walked", steps=taken, in_combat=bool(fighting),
             position=list(sess.position()))
    log.say(f"  walked {taken} steps; in combat: {bool(fighting)}")
    if fighting:
        sess.settle(2)
        dump(sess, out, log, "combat-icon")
    return {"steps": taken, "in_combat": bool(fighting)}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--disk", required=True, type=pathlib.Path,
                   help="the generated save disk, already a copy")
    p.add_argument("--disks", default=str(DISKS),
                   help="where the player's game sides are; read, never "
                        "written")
    p.add_argument("--slot", type=int, default=None,
                   help="demand this pool slot rather than the first free one")
    p.add_argument("--party", type=int, default=6,
                   help="how many sheets to read")
    p.add_argument("--out", default=None, help="run directory")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--full", action="store_true",
                   help="also do the four #10 questions the last comment "
                        "asked for in one boot: remove/re-add BULWARK, "
                        "toggle READY on PILFER and BULWARK, and pick a fight")
    p.add_argument("--fight-only", action="store_true",
                   help="skip the remove/re-add and the item toggles -- just "
                        "boot, load, begin adventuring and pick a fight, for "
                        "re-running the slow part of --full on its own")
    args = p.parse_args(argv)

    out = pathlib.Path(args.out) if args.out else scratch.scratch_dir("testpartyrun", "run")
    log = Log(out, args.quiet)
    log.emit("start", disk=str(args.disk), sides=args.disks)

    # The staging directory holds the generated save beside symlinks to the
    # player's own sides, so `stage_disks` copies all nine into the slot and
    # the originals are only ever read -- the way `tools/turndrive.py` does it.
    staging = out / "disks"
    staging.mkdir(parents=True, exist_ok=True)
    S.stage_writable(args.disk, staging / "STAGED.D64")
    for i in range(1, 9):
        src = pathlib.Path(args.disks) / f"POOL{i}.D64"
        link = staging / f"POOL{i}.D64"
        if src.exists() and not link.exists():
            link.symlink_to(src.resolve())

    slot = S.claim_slot(args.slot, f"testpartyrun/{args.disk.name}")
    log.say(f"slot {slot.n} display {slot.display}  out {out}")
    sess, rc = None, 0
    findings: dict = {}
    try:
        sess = S.Session(S.stage_disks(slot, staging, "STAGED.D64"), slot=slot)
        for step in ("boot", "load_save"):
            log.say(f"{step} ...")
            if not getattr(sess, step)():
                log.emit("failed", step=step)
                raise RuntimeError(f"{step} failed")
            log.emit("done", step=step)

        if args.full:
            log.say("remove/re-add BULWARK, from the party menu ...")
            raw = remove_and_readd(sess, log, out, "BULWARK")
            findings["bulwark_export"] = raw is not None
            if raw is not None:
                (out / "BULWARK-exported.CHR").write_bytes(raw)
                log.say(f"  wrote {len(raw)} bytes to BULWARK-exported.CHR")

        if args.fight_only:
            args.party = 0

        log.say("begin_adventuring ...")
        if not sess.begin_adventuring():
            log.emit("failed", step="begin_adventuring")
            raise RuntimeError("begin_adventuring failed")
        log.emit("done", step="begin_adventuring")
        sess.settle(3)
        log.emit("world", position=list(sess.position()))
        log.say(f"in the world at {sess.position()}")

        for index in range(args.party):
            shot = str(out / f"sheet{index}.png")
            lines = sess.character_sheet(index, shot=shot)
            log.emit("sheet", index=index, lines=lines, shot=shot)
            if lines is None:
                log.say(f"  slot {index}: no sheet")
                rc = 1
                continue
            (out / f"sheet{index}.txt").write_text("\n".join(lines) + "\n")
            log.say(f"  slot {index}: {lines[0][:60] if lines else ''}")
            for line in lines[:6]:
                log.say(f"      {line}")

        if args.full:
            sess.settle(3)
            log.say("toggling PILFER's LEATHER ARMOR +4 ...")
            findings["pilfer_armour"] = item_toggle_pair(
                sess, log, out, "PILFER", "LEATHER ARMOR", "pilfer-armour")
            sess.settle(3)
            log.say("toggling BULWARK's TWO-HANDED SWORD (shield and long "
                    "sword off first -- both already readied, and readying "
                    "the two-handed sword with the shield alone off still "
                    "read NO on 2026-09-16) ...")
            findings["bulwark_sword"] = item_toggle_pair(
                sess, log, out, "BULWARK", "TWO-HANDED SWORD", "bulwark-sword",
                sequence=["SHIELD", "LONG SWORD", "TWO-HANDED SWORD",
                         "TWO-HANDED SWORD", "LONG SWORD", "SHIELD"])
        if args.full or args.fight_only:
            log.say("picking a fight ...")
            findings["fight"] = pick_a_fight(sess, log, out)
            (out / "findings.json").write_text(json.dumps(findings, indent=1))
    except Exception as exc:                       # noqa: BLE001
        log.emit("error", why=repr(exc))
        log.say(f"ERROR {exc!r}")
        rc = 2
    finally:
        if sess is not None:
            sess.terminate()
        else:
            slot.teardown()
        log.emit("end", rc=rc)
        log.close()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
