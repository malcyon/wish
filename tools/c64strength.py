#!/usr/bin/env python3
"""Read THACO and DAMAGE off the C64 sheet with record `0x0E3` set and clear.

`#277 (A DOS character converted to the C64 loses the strength bonus to hit
and damage, because 0x0E3 is written zero)`.  `LIBRARY $375C` gates the AD&D
strength adjustment tables at `$3651` (to hit) and `$3670` (damage) on record
byte `0x0E3`:

    $375C  AE E3 6B   LDX $6BE3      ; the flag
    $375F  F0 03      BEQ $3764      ; zero: index 0, no adjustment
    $3761  AE E2 6B   LDX $6BE2      ; else the strength index

and the C64 character sheet draws both numbers -- `THACO 21  DAMAGE 1D2`.  So
one boot can answer whether the flag is what a player sees, by putting the
*same* converted character in five party slots that differ in that byte and in
nothing else that reaches the recompute.

The five variants, all built from one DOS specimen by `goldbox.dos`:

| name | `0x0E3` | roster block |
|---|---|---|
| `ZEROFLAG` | forced 0 | as `to_c64_record` writes it |
| `ONEFLAG` | forced 1 | as `to_c64_record` writes it |
| `SPOILZERO` | forced 0 | THAC0 and the damage bonus overwritten with values no character has |
| `SPOILONE` | forced 1 | the same spoiling |
| `ASWRITTEN` | whatever the writer wrote | the same spoiling |

`ASWRITTEN` is the one that tests the shipped code rather than this tool: its
`0x0E3` is not touched after `goldbox.dos.to_c64_record` returns, so the row it
lands on after the recompute is the conversion's own answer.

The spoiled pair is what separates "the engine recomputed and the flag decided
it" from "the sheet drew the numbers DOS already put in the roster block":
`to_c64_record` copies DOS's own THAC0 and damage bonus into the roster, which
are *right*, so an unspoiled sheet cannot tell a recompute from a copy.  Write
a THAC0 no level-1 fighter has and any sensible number on the sheet is the
engine's own arithmetic.

An execution checkpoint on `$375C` counts the recomputes, so a run that shows
nothing says which of the two reasons it was.

    tools/c64strength.py --cha ~/wish-specimens/por-dos/WISH-SPEC-elf6/party-ELF6.CHA

The player's disks are read and never written: every image the game sees is
the pool slot's own copy, and `POR_HEADLESS` keeps the window off the desktop.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import struct
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from goldbox import dos  # noqa: E402
from goldbox.d64 import D64, attach_load_address, split_load_address  # noqa: E402
from goldbox.games import POOL_OF_RADIANCE as GAME  # noqa: E402
from goldbox.layout import NAME_SIZE  # noqa: E402
from tools import gamedisks  # noqa: E402
from tools import session as S  # noqa: E402

#: `LIBRARY` is resident at `$2C48` and `$375C` is the strength gate.
STRENGTH_GATE = 0x375C

#: Where `SAVEDGAME1` loads: the eight 32-byte roster blocks, in slot order.
ROSTER_LOAD = 0x8300

#: Roster offsets the sheet draws: THAC0 and armour class are stored as
#: `60 - value`, and the damage bonus is added to the dice at `+0x13`/`+0x15`.
ROSTER_THAC0 = 0x0E
ROSTER_AC = 0x0F
ROSTER_DICE = 0x13
ROSTER_DIE = 0x15
ROSTER_DAMAGE_BONUS = 0x17

#: What goes into the spoiled roster blocks.  `0x0A` is THAC0 50 and `0x07` is
#: a damage bonus of seven -- neither is a number a level-1 fighter can hold,
#: so a sheet showing anything else has been recomputed.
SPOIL_THAC0 = 0x0A
SPOIL_DAMAGE = 0x07

#: name, slot, the byte to force into `0x0E3`, whether the roster block is
#: spoiled.  A flag of `None` leaves whatever `goldbox.dos.to_c64_record`
#: wrote, which is how a run proves the shipped writer rather than the tool.
VARIANTS = (("ZEROFLAG", 0, 0, False),
            ("ONEFLAG", 1, 1, False),
            ("SPOILZERO", 2, 0, True),
            ("SPOILONE", 3, 1, True),
            ("ASWRITTEN", 4, None, True))

RE_THACO = re.compile(r"THACO\s+(\d+)")
RE_DAMAGE = re.compile(r"DAMAGE\s+(\S+)")


def build(cha: pathlib.Path, save: pathlib.Path, log) -> list[dict]:
    """Put each variant into its own slot of the staged save copy."""
    char = dos.read_character(cha)
    image = D64.from_bytes(save.read_bytes())
    load0, save0 = split_load_address(image.read_file(GAME.save_file))
    load1, save1 = split_load_address(image.read_file(GAME.roster_file))
    save0, save1 = bytearray(save0), bytearray(save1)

    made = []
    for name, slot, flag, spoil in VARIANTS:
        rec, _ = dos.to_c64_record(char)
        rec.set("party_order", slot)
        raw = bytearray(rec.to_bytes())
        raw[:NAME_SIZE] = name.encode("ascii").ljust(NAME_SIZE, b"\0")
        if flag is not None:
            raw[0x0E3] = flag
        if spoil:
            raw[0x100 + ROSTER_THAC0] = SPOIL_THAC0
            raw[0x100 + ROSTER_DAMAGE_BONUS] = SPOIL_DAMAGE

        at = dos.SLOT_AREA - dos.SAVE0_BASE + slot * dos.SLOT_STRIDE
        save0[at:at + dos.SLOT_STRIDE] = raw[:dos.SLOT_STRIDE]
        at = dos.ITEM_AREA - dos.SAVE0_BASE + slot * dos.SLOT_STRIDE
        save0[at:at + dos.SLOT_STRIDE] = raw[0x120:0x220]
        at = slot * dos.ROSTER_STRIDE
        save1[at:at + dos.ROSTER_STRIDE] = raw[0x100:0x120]

        made.append({"name": name, "slot": slot,
                     "flag_0e3": raw[0x0E3], "forced": flag,
                     "spoiled": spoil,
                     "strength_index_0e2": raw[0x0E2],
                     "thac0_base_071": raw[0x071],
                     "roster_thac0": raw[0x100 + ROSTER_THAC0],
                     "roster_damage_bonus": raw[0x100 + ROSTER_DAMAGE_BONUS]})

    image.write_file_inplace(GAME.save_file,
                             attach_load_address(load0, bytes(save0)))
    image.write_file_inplace(GAME.roster_file,
                             attach_load_address(load1, bytes(save1)))
    save.write_bytes(image.to_bytes())
    log("built", cha=str(cha), variants=made)
    return made


def checkpoint_hits(mon, number: int) -> int:
    """How many times a checkpoint has fired: bytes 13-16 of the response."""
    body = mon.command(0x11, struct.pack("<I", number))
    return struct.unpack("<I", body[13:17])[0]


def sheet_numbers(lines) -> dict:
    """`THACO` and `DAMAGE` off a character sheet, and the name it carries."""
    text = "\n".join(lines)
    thaco = RE_THACO.search(text)
    damage = RE_DAMAGE.search(text)
    return {"thaco": int(thaco.group(1)) if thaco else None,
            "damage": damage.group(1) if damage else None,
            "name": lines[0].strip() if lines else None}


class Run:
    def __init__(self, out: pathlib.Path, quiet: bool):
        out.mkdir(parents=True, exist_ok=True)
        self.out = out
        self.file = open(out / "strength.jsonl", "w")
        self.quiet = quiet
        self.sess: S.Session | None = None
        self.gate = None
        self.shots = 0

    def log(self, kind: str, **kw) -> None:
        kw["kind"] = kind
        kw["t"] = round(time.time(), 3)
        self.file.write(json.dumps(kw, default=str) + "\n")
        self.file.flush()
        if not self.quiet:
            print(kind, {k: v for k, v in kw.items() if k not in ("kind", "t")},
                  flush=True)

    def dump(self, tag: str) -> list[str]:
        s = self.sess.screen()
        rows = ["(bitmap)"] if s is None else [s.row(r) for r in range(25)]
        self.shots += 1
        (self.out / f"{self.shots:02d}-{tag}.txt").write_text(
            "\n".join(rows) + "\n")
        self.sess.kbd.screenshot(str(self.out / f"{self.shots:02d}-{tag}.png"))
        return rows

    def arm(self) -> None:
        with self.sess.mon(8) as m:
            self.gate = m.checkpoint_set(STRENGTH_GATE, STRENGTH_GATE,
                                         exec_=True, stop=False)
            m.resume()
        self.log("armed", gate=self.gate, at=hex(STRENGTH_GATE))

    def gate_count(self, stage: str) -> int:
        with self.sess.mon(8) as m:
            n = checkpoint_hits(m, self.gate)
            m.resume()
        self.log("gate", stage=stage, hits=n)
        return n

    def roster(self, stage: str) -> list[dict]:
        """The eight roster blocks as the machine holds them right now."""
        with self.sess.mon(8) as m:
            data = m.read(ROSTER_LOAD, 8 * 0x20)
            m.resume()
        out = []
        for slot in range(8):
            b = data[slot * 0x20:(slot + 1) * 0x20]
            out.append({"slot": slot,
                        "thac0": 60 - b[ROSTER_THAC0],
                        "ac": 60 - b[ROSTER_AC],
                        "dice": b[ROSTER_DICE], "die": b[ROSTER_DIE],
                        "damage_bonus": b[ROSTER_DAMAGE_BONUS]})
        self.log("roster", stage=stage, blocks=out)
        return out

    def leave_sheet(self) -> None:
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

    def view(self, name: str, where: str = "menu") -> dict:
        """One sheet off the VIEW CHARACTER list, on the menu or in the world."""
        if where == "world":
            return self.view_in_world(name)
        self.sess.select_row("VIEW CHARACTER", timeout=25.0)
        self.sess.settle(4.0)
        self.dump(f"view-list-{name}")
        before = self.gate_count(f"before-{name}")
        picked = self.sess.select_row(name, timeout=25.0)
        self.sess.settle(5.0)
        rows = self.dump(f"sheet-{name}")
        lines = [r.rstrip() for r in rows if r.strip()]
        got = sheet_numbers([ln.strip("$ ") for ln in lines[1:]])
        after = self.gate_count(f"after-{name}")
        self.roster(f"sheet-{name}")
        self.log("sheet", asked_for=name, picked=picked,
                 gate_delta=after - before, **got, rows=lines)
        self.leave_sheet()
        self.sess.settle(2.0)
        s = self.sess.screen()
        if s is not None and s.contains("VIEW WHICH CHARACTER"):
            self.sess.select_row("EXIT", timeout=10.0)
            self.sess.settle(2.0)
        self.sess.wait_text("BEGIN ADVENTURING", 40)
        return got

    def view_in_world(self, name: str) -> dict:
        """The same sheet, off the world screen's party panel."""
        s = self.sess.screen()
        rows = self.sess.party_rows(s)
        index = next((i for i, r in enumerate(rows)
                      if s is not None and name in s.row(r)), None)
        before = self.gate_count(f"world-before-{name}")
        self.shots += 1
        shot = self.out / f"{self.shots:02d}-world-sheet-{name}.png"
        lines = self.sess.character_sheet(index, shot=str(shot)) or []
        (self.out / f"{self.shots:02d}-world-sheet-{name}.txt").write_text(
            "\n".join(lines) + "\n")
        got = sheet_numbers([ln.strip("$ ") for ln in lines[1:]])
        after = self.gate_count(f"world-after-{name}")
        self.roster(f"world-sheet-{name}")
        self.log("sheet", where="world", asked_for=name, panel_index=index,
                 gate_delta=after - before, **got, rows=lines)
        return got


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--cha", required=True,
                   help="the DOS character to convert, once per variant")
    p.add_argument("--save", default="PORSAVE.D64",
                   help="the save disk to copy, inside --disks")
    p.add_argument("--disks", default=None,
                   help="where the player's disks are; read, never written")
    p.add_argument("--slot", type=int, default=None,
                   help="demand this pool slot rather than the first free one")
    p.add_argument("--out", default=None, help="run directory")
    p.add_argument("--walk", default="I",
                   help="the move to repeat looking for a fight; empty to "
                        "stop before the world")
    p.add_argument("--steps", type=int, default=40,
                   help="give up looking for a fight after this many steps")
    p.add_argument("--fight", action="store_true",
                   help="fight the ambush out as well; the roster is already "
                        "rebuilt by the time the first command bar is up, so "
                        "this adds nothing to the measurement")
    p.add_argument("--budget", type=float, default=420.0,
                   help="seconds to give the fight")
    p.add_argument("--world-sheets", action="store_true",
                   help="read the sheets again off the world party panel; "
                        "measured to add nothing, since nothing recomputes "
                        "between the menu and the first fight")
    p.add_argument("--menu-sheets", action="store_true",
                   help="read the four sheets off the main menu first; this "
                        "leaves a game side in the drive and BEGIN "
                        "ADVENTURING then sits on OUTWARD BOUND")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    disks = pathlib.Path(args.disks or gamedisks.find("pool-of-radiance"))
    out = pathlib.Path(args.out) if args.out \
        else ROOT / "work" / "issue277" / "run"
    run = Run(out, args.quiet)

    slot = S.claim_slot(args.slot, "c64strength/277")
    run.log("slot", n=slot.n, display=slot.display, out=str(out))
    rc = 0
    try:
        boot = S.stage_disks(slot, disks, args.save)
        save = pathlib.Path(slot.dir) / "SIDE0.D64"
        run.log("staged", save=str(save))
        build(pathlib.Path(args.cha).expanduser(), save, run.log)

        sess = S.Session(boot, slot=slot)
        run.sess = sess
        if not sess.boot():
            raise RuntimeError("boot failed")
        if sess.wait_text("LOAD SAVED GAME", 240)[0] is None:
            raise RuntimeError("no main menu")
        run.dump("main-menu")
        run.arm()
        run.gate_count("menu")

        if not sess.load_save():
            raise RuntimeError("load_save failed")
        run.dump("loaded")
        run.gate_count("loaded")
        run.roster("loaded")

        if args.menu_sheets:
            for name, _slot, _flag, _spoil in VARIANTS:
                run.view(name)

        if not args.walk:
            return rc
        # The recompute is not on the load path -- the menu's sheets are drawn
        # from the roster block the conversion wrote, spoiled values and all.
        # So walk until something ambushes the party, sampling the gate at
        # every step, and read the sheets again on the other side of it.
        if not sess.begin_adventuring():
            raise RuntimeError("begin_adventuring failed")
        sess.settle(3)
        run.dump("world")
        run.gate_count("world")
        run.roster("world")
        if args.world_sheets:
            for name, _slot, _flag, _spoil in VARIANTS:
                run.view(name, where="world")

        steps, seen = 0, 0
        while not sess.in_combat() and steps < args.steps:
            sess.walk_one(args.walk)
            sess.handle_prompt()
            steps += 1
            now = run.gate_count(f"step-{steps}")
            if now != seen:
                seen = now
                run.roster(f"step-{steps}")
        run.log("walked", steps=steps, in_combat=sess.in_combat())
        run.dump("after-walk")
        run.gate_count("after-walk")
        run.roster("after-walk")
        # Combat's own VIEW puts the acting character's sheet up, which is the
        # same THACO and DAMAGE a player reads, drawn after the recompute
        # rather than before it.
        if sess.in_combat() and sess.combat_bar("VIEW", timeout=20):
            sess.settle(4)
            run.dump("combat-sheet")
            sess.kbd.key("Return")
            sess.settle(2)
        # The roster read above is the whole measurement: combat preparation
        # has already rebuilt all eight blocks by the time the first command
        # bar is up.  Fighting on is optional, and a party of unarmoured
        # level-1 fighters loses the Slums ambush.
        if args.fight and sess.in_combat():
            result = sess.fight(budget=args.budget)
            run.log("fought", evidence=str(result.evidence)[:2000])
            sess.settle(4)
            run.dump("after-fight")
            run.gate_count("after-fight")
            run.roster("after-fight")
            for name, _slot, _flag, _spoil in VARIANTS:
                run.view(name, where="world")
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
