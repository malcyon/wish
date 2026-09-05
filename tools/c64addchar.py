#!/usr/bin/env python3
"""Drive the C64's ADD CHARACTER TO PARTY and count what reads record 0x0E6-0x0E7.

`#258 (The C64 side of 0x0AB is unnamed, so the conversion drops it with no
issue behind it)`.  DOS keeps a random identity byte at `0x0AB` and reads it in
one place: ADD CHARACTER TO PARTY, as the tiebreak between two characters of
the same name.  The C64 writes two random bytes at `0x0E6`-`0x0E7` when GEN
creates a character (`GEN $0C01`-`$0C0A`, two calls to the generator at
`LIBRARY $2D88`) and, by a census of every file on the eight sides, never
reads them.  This is the running-game half of that reading.

Two things are measured on one boot, off a **copy** of a save disk staged into
a pool slot:

* **Whether anything reads the pair.**  Three load watchpoints, none of which
  stop the machine: `$6BE4`-`$6BE5` (two bytes nothing references), `$6BE6`-
  `$6BE7` (the pair in question) and `$6BE8`-`$6BE9` (experience, which the
  sheet and the trainer read).  A block copy of the working record reads all
  three windows alike, so the first two counts agree while every read is a
  copy, and the third runs ahead of them whenever a field is read on its own.
  A count on the middle window that exceeds the first is a field read of the
  pair, which the census says does not exist.

* **What the add screen tests.**  The staged disk carries two edited exports
  beside the game's own: `\\x01MALCYON` rewritten to hold BRUTUS's record under
  MALCYON's name -- same name as a party member, a different character, a
  different pair -- and `\\x01TWIN`, MALCYON's own record under a new name, so
  the pair matches a party member's exactly.  If the screen tests the name
  alone, the first is starred and refused and the second is let in.

The player's disks are read and never written; every image the game sees is
the slot's own copy.  `POR_HEADLESS` is the slot's default, so nothing lands
on the desktop.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import struct
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from goldbox.d64 import D64  # noqa: E402
from goldbox.layout import NAME_SIZE  # noqa: E402
from tools import gamedisks  # noqa: E402
from tools import session as S  # noqa: E402

#: The three watched windows of the working record at `$6B00`.
WINDOWS = {"e4_e5": (0x6BE4, 0x6BE5),
           "e6_e7": (0x6BE6, 0x6BE7),
           "e8_e9": (0x6BE8, 0x6BE9)}

#: `SAVEDGAME0` loads at `$4900`; the twelve character slots are `$100` apart
#: from `$4D00`, each the first 256 bytes of a record, and the party is slots
#: 0-7 listed highest first (docs/30-savegame-layout.md).
SAVE0_LOAD = 0x4900
SLOT_BASE = 0x4D00
SLOT_STRIDE = 0x100


def checkpoint_hits(mon, number: int) -> int:
    """How many times a checkpoint has fired; VICE's response puts the hit
    count at bytes 13-16 (`tools/traitdrive.py` unpacks the same field)."""
    body = mon.command(0x11, struct.pack("<I", number))
    return struct.unpack("<I", body[13:17])[0]


def export(disk: D64, name: bytes) -> bytes:
    """A `\\x01NAME` character export off a disk: 582 bytes, load address on."""
    data = disk.read_file(b"\x01" + name)
    if len(data) != 582:
        raise SystemExit(f"{name!r} is {len(data)} bytes, not an export")
    return data


def renamed(file: bytes, name: bytes) -> bytes:
    """The same export with the record's name field replaced."""
    body = bytearray(file)
    body[2:2 + NAME_SIZE] = name.ljust(NAME_SIZE, b"\0")
    return bytes(body)


def pair(file: bytes) -> str:
    return " ".join(f"{b:02X}" for b in file[2 + 0xE6:2 + 0xE8])


def stage(save: pathlib.Path, log) -> dict:
    """Edit the staged copy: MALCYON's export becomes BRUTUS under MALCYON's
    name, and TWIN is MALCYON's record under a new name."""
    disk = D64.open(str(save))
    malcyon = export(disk, b"MALCYON")
    brutus = export(disk, b"BRUTUS")
    same_name = renamed(brutus, b"MALCYON")
    twin = renamed(malcyon, b"TWIN")
    disk.write_file_inplace(b"\x01MALCYON", same_name)
    disk.write_file(b"\x01TWIN", twin)
    disk.save(str(save))
    facts = {"party MALCYON pair": pair(malcyon),
             "export MALCYON now": f"BRUTUS's record, pair {pair(same_name)}",
             "export TWIN": f"MALCYON's record, pair {pair(twin)}"}
    log("staged", **facts)
    return facts


def party_names(save: pathlib.Path) -> list[dict]:
    """Names and pairs of the occupied party slots in `SAVEDGAME0`."""
    disk = D64.open(str(save))
    data = disk.read_file(b"SAVEDGAME0")[2:]
    out = []
    for slot in reversed(range(8)):
        at = SLOT_BASE - SAVE0_LOAD + slot * SLOT_STRIDE
        rec = data[at:at + 0x100]
        name = rec[:NAME_SIZE].split(b"\0")[0].decode("latin-1")
        if name:
            out.append({"slot": slot, "name": name,
                        "pair": " ".join(f"{b:02X}" for b in rec[0xE6:0xE8])})
    return out


class Run:
    def __init__(self, out: pathlib.Path, quiet: bool):
        out.mkdir(parents=True, exist_ok=True)
        self.out = out
        self.file = open(out / "addchar.jsonl", "w")
        self.quiet = quiet
        self.sess: S.Session | None = None
        self.cp: dict[str, int] = {}
        self.shots = 0

    def log(self, kind: str, **kw) -> None:
        kw["kind"] = kind
        kw["t"] = round(time.time(), 3)
        self.file.write(json.dumps(kw, default=str) + "\n")
        self.file.flush()
        if not self.quiet:
            print(kind, {k: v for k, v in kw.items() if k not in ("kind", "t")},
                  flush=True)

    def dump(self, tag: str) -> str:
        """The screen as text, kept beside the run."""
        s = self.sess.screen()
        text = "(bitmap)" if s is None else "\n".join(s.row(r) for r in range(25))
        self.shots += 1
        (self.out / f"{self.shots:02d}-{tag}.txt").write_text(text + "\n")
        self.sess.kbd.screenshot(str(self.out / f"{self.shots:02d}-{tag}.png"))
        return text

    def arm(self) -> None:
        with self.sess.mon(8) as m:
            for key, (lo, hi) in WINDOWS.items():
                self.cp[key] = m.checkpoint_set(lo, hi, load=True, stop=False)
            m.resume()
        self.log("armed", checkpoints=self.cp)

    def counts(self, stage: str) -> dict[str, int]:
        with self.sess.mon(8) as m:
            got = {k: checkpoint_hits(m, v) for k, v in self.cp.items()}
            m.resume()
        self.log("counts", stage=stage, **got)
        return got

    def pick(self, label: str, tag: str, settle: float = 4.0,
             still: bool = False) -> str:
        ok = self.sess.select_row(label, timeout=20.0)
        if still:
            self.wait_still(settle)
        else:
            self.sess.settle(settle)
        text = self.dump(tag)
        self.log("picked", label=label, selected=ok,
                 on_screen=[ln for ln in text.splitlines() if ln.strip()][:25])
        return text

    def wait_still(self, budget: float, quiet: int = 3) -> None:
        """Ride out a screen that is still being built -- the add list stars
        its entries one directory entry at a time -- until three polls a
        second apart agree, or the budget is spent."""
        last, same, end = None, 0, time.time() + max(budget, 6.0)
        while time.time() < end and same < quiet:
            self.sess.handle_prompt()
            s = self.sess.screen()
            text = None if s is None else "\n".join(s.row(r) for r in range(25))
            same = same + 1 if text == last else 0
            last = text
            time.sleep(1.0)

    def answer_yes(self, tag: str) -> None:
        """A `YES NO` question, wherever the game draws it, then the disk
        prompt that follows a write."""
        s = self.sess.screen()
        if s is not None and s.contains("YES"):
            if not self.sess.select_row("YES", timeout=6.0):
                self.sess.select_bar("YES", timeout=6.0)
        self.sess.settle(6.0)
        self.dump(tag)

    def remove(self, names: list[str]) -> None:
        """REMOVE CHARACTER FROM PARTY keeps its list up after each removal
        (`REMOVE CHARACTER ?` stays on row 24), so one visit takes them all,
        and EXIT is what brings the main menu back."""
        self.pick("REMOVE CHARACTER FROM PARTY", "remove-list", settle=3.0)
        for name in names:
            self.pick(name, f"removed-{name.split()[0]}", settle=12.0, still=True)
        self.pick("EXIT", "after-removes", settle=3.0)
        self.sess.wait_text("BEGIN ADVENTURING", 60)

    def leave_sheet(self, tag: str) -> None:
        """Off a party-menu character sheet, by whichever of its exits the
        screen offers: the `OK` row, a bar `EXIT`, and last a bare key."""
        for attempt in ("OK", "EXIT", "space"):
            s = self.sess.screen()
            if s is None or s.contains("VIEW WHICH CHARACTER") \
                    or s.contains("BEGIN ADVENTURING"):
                break
            if attempt == "OK":
                self.sess.select_row("OK", timeout=6.0)
            elif attempt == "EXIT":
                self.sess.select_bar("EXIT", timeout=6.0)
            else:
                self.sess.kbd.key("space")
            self.sess.settle(2.0)
        self.dump(tag)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--save", default="PORSAVE.D64",
                   help="the save disk to copy, inside --disks")
    p.add_argument("--disks", default=None,
                   help="where the player's disks are; read, never written")
    p.add_argument("--slot", type=int, default=None,
                   help="demand this pool slot rather than the first free one")
    p.add_argument("--no-stage", action="store_true",
                   help="leave the save copy as the game wrote it")
    p.add_argument("--out", default=None, help="run directory")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    disks = pathlib.Path(args.disks or gamedisks.find("pool-of-radiance"))
    out = pathlib.Path(args.out) if args.out else ROOT / "work" / "issue258" / "run"
    run = Run(out, args.quiet)

    slot = S.claim_slot(args.slot, "c64addchar/258")
    run.log("slot", n=slot.n, display=slot.display, out=str(out))
    rc = 0
    try:
        boot = S.stage_disks(slot, disks, args.save)
        save = pathlib.Path(slot.dir) / "SIDE0.D64"
        run.log("party_before", slots=party_names(save))
        if not args.no_stage:
            stage(save, run.log)
        sess = S.Session(boot, slot=slot)
        run.sess = sess
        if not sess.boot():
            raise RuntimeError("boot failed")
        if sess.wait_text("LOAD SAVED GAME", 240)[0] is None:
            raise RuntimeError("no main menu")
        run.dump("main-menu")
        run.arm()
        run.counts("menu")

        if not sess.load_save():
            raise RuntimeError("load_save failed")
        run.dump("loaded")
        run.counts("loaded")

        # Make room: the party is six strong and the add refuses a seventh
        # player character before it looks at anything else.
        run.remove(["LADY KATHERINE", "SILAS"])
        run.counts("removed")

        run.pick("ADD CHARACTER TO PARTY", "add-list", settle=40.0, still=True)
        run.counts("list")
        run.pick("MALCYON", "after-malcyon", settle=6.0, still=True)
        run.counts("pick-malcyon")
        run.pick("TWIN", "after-twin", settle=8.0, still=True)
        run.counts("add-twin")
        run.pick("LADY KATHERINE", "after-katherine", settle=8.0, still=True)
        run.counts("add-katherine")
        run.pick("EXIT", "after-exit")
        sess.wait_text("BEGIN ADVENTURING", 60)
        run.counts("left-list")

        run.pick("VIEW CHARACTER", "view-list", settle=5.0)
        run.pick("TWIN", "sheet-twin")
        run.counts("view")
        run.leave_sheet("after-sheet")
        s = sess.screen()
        if s is not None and s.contains("VIEW WHICH CHARACTER"):
            run.pick("EXIT", "back-to-menu")
        sess.wait_text("BEGIN ADVENTURING", 30)

        run.pick("SAVE CURRENT GAME", "save", settle=3.0)
        run.answer_yes("after-save")
        sess.wait_text("BEGIN ADVENTURING", 60)
        run.counts("saved")
        run.log("party_after", slots=party_names(save))

        if sess.begin_adventuring():
            sess.settle(3)
            sess.walk("III")
            sess.settle(2)
            run.dump("world")
            run.counts("world")
        else:
            run.log("no_world")
    except Exception as exc:  # noqa: BLE001 -- the run's own failure line
        run.log("failed", error=repr(exc))
        try:
            run.dump("failed")
        except Exception:  # noqa: BLE001
            pass
        rc = 1
    finally:
        if run.sess is not None:
            run.sess.terminate()
        else:
            slot.teardown()
        run.file.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
