#!/usr/bin/env python3
"""Dual-class a C64 *Curse* paladin or ranger and watch the old class come back.

`#409 (A regained dual-classed paladin or ranger has a class mask Curse's own
table cannot name, so Wish shows him a class he is not)`.  `GEN $1951` has no
code for seven of the pairs a dual-classed character can make, and every one of
the seven has a paladin or a ranger in it.  Six are reachable through the
party menu's own `HUMAN CHANGE CLASSES`; this drives one of them end to end and
keeps the record the engine writes, because a routine read right is not the
same as a byte on a disk.

The route, and why each step is where it is:

* **`GEN $23F3` decides what a character is offered**, indexed by `alignment`
  at record `0x0D8` -- `$CB` for lawful good, which is magic-user, cleric,
  fighter, paladin and ranger, `$8F` for the other two good alignments, `$0F`
  for everybody else.  A paladin is lawful good, so he is offered FIGHTER and
  CLERIC and never THIEF.
* **`GEN $2442` then wants 17 in the *new* class's prime requisites**, which
  the tables at `$242A`/`$2432`/`$243A` give as strength alone for a fighter
  and wisdom alone for a cleric.  MATHEW on `WISH-SPEC-curse-trained-party` is
  a human paladin 6 with strength 18, so `--change MATHEW:FIGHTER` needs no
  staged ability at all; a change to CLERIC needs wisdom staged to 17.
* **`GEN $20A3` is the regain**, and its test is `dual_class_level < level`.
  Rather than train the new class from 1 up to the old level -- six presses,
  each needing the experience poked back because `GEN $2086` clamps it -- this
  stages the new class's level array entry *to* `dual_class_level` and trains
  once.  The staged number is an input; `class_bits`, the restored level slot
  and `char_class` are all written by the engine on that press.

    tools/cursepaladin.py stage --base <in.d64> --out <out.d64> --repair \\
        --give MARK:wis=18

    tools/cursepaladin.py run --pool N --disks <PIS> --save <out.d64> \\
        --change MATHEW:FIGHTER --regain MATHEW --out work/issue409/run1

`stage` writes **inputs only** and says which; `run` prints the class fields
before the change, after the change and after the training, photographs every
screen it presses a key on, and writes one JSON line per event as it goes so a
run that falls over says where it was.  Nothing writes to the player's disks:
`tools/curserun.py` copies the six sides into the pooled slot read only.
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

from goldbox.d64 import D64  # noqa: E402
from tools.cursetrain import (  # noqa: E402
    FIELDS,
    MONEY,
    PLATINUM,
    RECORD,
    SLOT0,
    SLOT_SIZE,
    XP,
    payload_of,
    read_u,
    slot_names,
    write_u,
)

#: The roster copies in the running machine: `SAVEAZURE` loads at `$4B00` and
#: its eight slots start `$400` in, so slot *n* is `$4F00 + n * $100`.  The
#: engine copies one into the working record at `RECORD` when a menu picks a
#: character and writes it back on success only, which is why a poke goes here.
ROSTER = 0x4F00

#: `GEN $12CA` gates TRAIN CHARACTER on this byte; the area scripts write 127
#: when the party is in a hall (`tools/cursetrain.py`).
HALL = 0x7EA8
HALL_OPEN = 0x7F

#: The class fields this run is about, all inside the 256 bytes a roster slot
#: keeps.  `class_bits` is the one the ticket turns on.
CLASS_FIELDS = [
    (0x065, 1, "str"), (0x066, 1, "int"), (0x067, 1, "wis"),
    (0x068, 1, "dex"), (0x069, 1, "con"), (0x06A, 1, "cha"),
    (0x072, 1, "race"), (0x073, 1, "char_class"), (0x0A0, 1, "level"),
    (0x0B9, 1, "dual_class_slot"), (0x0BA, 1, "dual_class_level"),
    (0x0C9, 1, "level_magic_user"), (0x0CA, 1, "level_cleric"),
    (0x0CB, 1, "level_thief"), (0x0CC, 1, "level_fighter"),
    (0x0CF, 1, "level_paladin"), (0x0D0, 1, "level_ranger"),
    (0x0D8, 1, "alignment"), (0x0E8, 3, "experience"),
    (0x0EB, 1, "class_bits"), (0x0ED, 1, "hp_rolled"),
    (0x071, 1, "thac0_base"), (0x076, 2, "hp_max"),
    (0x0C3, 2, "platinum"),
]

#: Class name -> its slot in the level array at `0x0C9`, which is the bit
#: order `GEN $0B82` (`01 02 04 08 10 20 40 80`) indexes with the same number.
CLASS_SLOT = {
    "magic-user": 0, "cleric": 1, "thief": 2, "fighter": 3,
    "paladin": 6, "ranger": 7,
}

#: Abilities `stage --give` may write, in the record's own order.  Each is
#: written **twice**: the change routine reads `$7C65` (`0x065`) and `GEN
#: $1E9C` copies that block down to `0x014`, so leaving the two disagreeing
#: stages a character no roll could make (`#367`).
ABILITIES = {"str": 0, "int": 1, "wis": 2, "dex": 3, "con": 4, "cha": 5}
ABILITY_NOW = 0x065
ABILITY_COPY = 0x014


def describe(record: bytes) -> dict:
    """The class fields of one 256-byte roster slot."""
    return {name: read_u(record, off, width)
            for off, width, name in CLASS_FIELDS}


def stage(args) -> int:
    """Copy a save disk, writing ability and level inputs into named slots."""
    image = pathlib.Path(args.base).read_bytes()
    load, payload = payload_of(image)
    names = slot_names(payload)
    upper = [n.upper() for n in names]
    body = bytearray(payload)
    for spec in args.give:
        who, _, fields = spec.partition(":")
        if who.upper() not in upper:
            raise SystemExit(f"no slot is called {who!r}; the disk has {names}")
        n = upper.index(who.upper())
        base = SLOT0 + n * SLOT_SIZE
        wrote = []
        for pair in fields.split(","):
            key, _, val = pair.partition("=")
            value = int(val)
            if key in ABILITIES:
                i = ABILITIES[key]
                write_u(body, base + ABILITY_NOW + i, 1, value)
                write_u(body, base + ABILITY_COPY + i, 1, value)
            elif key == "plat":
                for coin in range(4):
                    write_u(body, base + MONEY + 2 * coin, 2, 0)
                write_u(body, base + PLATINUM, 2, value)
            elif key in FIELDS:
                off, width = FIELDS[key]
                write_u(body, base + off, width, value)
            else:
                raise SystemExit(
                    f"unknown field {key!r}; use plat=, one of "
                    f"{', '.join(sorted(ABILITIES))} or one of "
                    f"{', '.join(sorted(FIELDS))}")
            wrote.append(f"{key}={value}")
        print(f"{names[n]:10s} slot {n}: staged {', '.join(wrote)}")
    disk = D64(image)
    disk.write_file_inplace(b"SAVEAZURE",
                            load.to_bytes(2, "little") + bytes(body))
    pathlib.Path(args.out).write_bytes(disk.to_bytes())
    if args.repair:
        from tools.curseload import close_splat  # noqa: PLC0415

        for entry in close_splat(args.out):
            name = entry["name"]
            name = name.decode("latin1") if isinstance(name, bytes) else name
            print(f"closed {name}: type {entry['type_was']} -> "
                  f"{entry['type_now']}, {entry['blocks_now']} blocks")
    print(f"wrote {args.out}")
    return 0


def show(args) -> int:
    """Print the class fields of every slot of a save disk, with no emulator."""
    load, payload = payload_of(pathlib.Path(args.disk).read_bytes())
    for n, name in enumerate(slot_names(payload)):
        if not name:
            continue
        base = SLOT0 + n * SLOT_SIZE
        fields = describe(payload[base:base + SLOT_SIZE])
        print(f"{n} {name:10s} " + " ".join(
            f"{k}={v}" for k, v in fields.items() if v))
    return 0


class Run:
    """One driven session, logging every event where it is taken."""

    def __init__(self, out: pathlib.Path):
        self.out = out
        out.mkdir(parents=True, exist_ok=True)
        self.log = (out / "run.jsonl").open("a")
        self.sess = None
        self.shots = 0

    def note(self, **kw) -> None:
        kw["t"] = round(time.time(), 2)
        self.log.write(json.dumps(kw) + "\n")
        self.log.flush()
        print(json.dumps(kw), flush=True)

    def shot(self, tag: str) -> None:
        self.shots += 1
        name = f"{self.shots:02d}-{tag}.png"
        ok = self.sess.kbd.screenshot(str(self.out / name))
        s = self.sess.screen()
        text = s.text() if s is not None else None
        if text is not None:
            (self.out / f"{self.shots:02d}-{tag}.txt").write_text(text)
        self.note(event="shot", tag=tag, file=name, ok=bool(ok),
                  bitmap=text is None)

    # -- the record, in the running machine --------------------------------

    def roster(self, slot: int) -> bytes:
        with self.sess.mon(8) as m:
            return m.read(ROSTER + slot * SLOT_SIZE, SLOT_SIZE)

    def working(self) -> bytes:
        with self.sess.mon(8) as m:
            return m.read(RECORD, SLOT_SIZE)

    def poke(self, addr: int, data: bytes) -> None:
        with self.sess.mon(8) as m:
            was = m.read(addr, len(data))
            m.write(addr, data)
        self.note(event="poke", addr=f"${addr:04X}",
                  was=was.hex(" "), now=data.hex(" "))

    def record(self, tag: str, slot: int, name: str) -> dict:
        fields = describe(self.roster(slot))
        self.note(event="record", tag=tag, who=name, slot=slot, fields=fields)
        return fields


def find_slot(save: str, who: str) -> int:
    _, payload = payload_of(pathlib.Path(save).read_bytes())
    names = [n.upper() for n in slot_names(payload)]
    if who.upper() not in names:
        raise SystemExit(f"no slot is called {who!r}; the disk has {names}")
    return names.index(who.upper())


def live_class(fields: dict) -> str | None:
    """The one class whose level array entry is non-zero, or None."""
    live = [name for name, slot in CLASS_SLOT.items()
            if fields.get(f"level_{name.replace('-', '_')}")]
    return live[0] if len(live) == 1 else None


def sheet(run: "Run", who: str) -> bool:
    """Photograph one character's `VIEW` sheet, which is what a player reads.

    `VIEW CHARACTER` does not put a sheet up: it puts up `VIEW WHICH
    CHARACTER?`, a list of the party under a `NAME  AC HP` heading, and the
    sheet is one row further in.  A run that photographed the first screen
    photographed the list and called it the sheet.
    """
    sess = run.sess
    if not sess.select_row("VIEW CHARACTER"):
        run.note(event="no-view-item", who=who)
        return False
    if not sess.select_row(who):
        run.note(event="not-in-view-picker", who=who)
        sess.select_row("EXIT")
        return False
    sess.settle(3)
    run.shot(f"{who}-sheet")
    sess.leave_sheet()
    sess.select_row("EXIT")
    return True


def save_current_game(run: "Run") -> bool:
    """`SAVE CURRENT GAME`, which is the **party menu's** save.

    `CurseSession.save_game` is `ENCAMP > SAVE` and wants the party in the
    world; nothing here ever presses `BEGIN ADVENTURING`, so that one reports
    that it never reached the world bar and saves nothing.  This is the item
    that wrote `WISH-SPEC-curse-trained-party` and `WISH-SPEC-curse-dual-
    classed` (`docs/172-curse-trainer.md`), and a save made here stands in
    area 0, before the party has begun adventuring.
    """
    from tools.curseload import answer_yes  # noqa: PLC0415

    sess = run.sess
    if not sess.select_row("SAVE CURRENT GAME"):
        run.note(event="no-save-item")
        run.shot("no-save-item")
        return False
    # **`SAVE GAME ? YES NO` is a bar, and it reads the KERNAL buffer
    # only** -- the same one `LOAD SAVED GAME ? YES NO` puts up, so an XTEST
    # Return leaves the question on the screen and the run copies out the
    # disk it arrived with.  `answer_yes` walks with XTEST and answers with
    # one `press_kernal`.
    if not answer_yes(sess, "YES"):
        run.note(event="no-save-question")
        run.shot("no-save-question")
        return False
    run.shot("save-answered")
    sess.settle(12)
    run.shot("saved")
    return True


def drive(args) -> int:
    """Boot Curse, change class, stage the regain, train, and read it back."""
    from tools import curseload, curserun  # noqa: PLC0415
    from tools import session as por  # noqa: PLC0415

    run = Run(pathlib.Path(args.out))
    slot = None
    try:
        slot = por.claim_slot(args.pool, note=os.environ.get(
            "POR_AGENT", "i409"))
        run.note(event="slot", n=slot.n, monitor=slot.port,
                 cmd=slot.cmd_port, display=slot.display, dir=str(slot.dir))
        disk = curserun.stage(slot, args.disks, args.save)
        sess = run.sess = curserun.CurseSession(disk, slot=slot)
        sess.save_disk = str(pathlib.Path(slot.dir) / "SIDE0.D64")
        run.note(event="booting")
        if not sess.boot():
            run.note(event="boot-failed")
            return 1
        run.note(event="booted")
        run.shot("party-menu")
        how = curseload.load_saved_game(sess, note=run.note)
        if how != "loaded":
            run.note(event="load-failed", how=how)
            run.shot("load-failed")
            return 1
        run.shot("loaded")
        sess.patch_disk_prompt()

        want = {}
        for spec in args.change:
            who, _, cls = spec.partition(":")
            want[who.upper()] = cls.upper()
        for who, cls in want.items():
            n = find_slot(args.save, who)
            run.record("before-change", n, who)
            if not sess.select_row("CHANGE CLASS"):
                run.note(event="no-change-class-item")
                run.shot("no-change-class")
                return 1
            run.shot(f"{who}-picker")
            if not sess.select_row(who):
                run.note(event="not-in-picker", who=who)
                return 1
            run.shot(f"{who}-class-list")
            if not sess.select_row(cls):
                run.note(event="class-not-offered", who=who, cls=cls)
                return 1
            sess.settle(4)
            run.shot(f"{who}-changed")
            run.record("after-change", n, who)

        for who in [w.upper() for w in args.regain]:
            n = find_slot(args.save, who)
            fields = run.record("before-regain-stage", n, who)
            cls = live_class(fields)
            dcl = fields["dual_class_level"]
            if cls is None or not dcl:
                run.note(event="not-dual-classed", who=who, live=cls, dcl=dcl)
                return 1
            base = ROSTER + n * SLOT_SIZE
            # Inputs, and they are the only thing this writes: put the new
            # class one level below the level he left the old one at, so a
            # single press crosses `GEN $20A3`'s `dual_class_level < level`.
            run.poke(base + 0x0C9 + CLASS_SLOT[cls], bytes([dcl]))
            run.poke(base + 0x0A0, bytes([dcl]))
            run.poke(base + XP, int(args.experience).to_bytes(3, "little"))
            run.poke(base + PLATINUM, int(args.platinum).to_bytes(2, "little"))
            run.poke(HALL, bytes([HALL_OPEN]))
            run.record("staged", n, who)
            # Any trip through the menu rebuilds it, which is what makes
            # TRAIN CHARACTER appear now the hall byte is set.
            sess.select_row("VIEW CHARACTER")
            run.shot(f"{who}-view-before")
            sess.select_row("EXIT")
            if not sess.select_row("TRAIN CHARACTER"):
                run.note(event="no-train-item")
                run.shot("no-train")
                return 1
            run.shot(f"{who}-train-picker")
            # `row <NAME>` is the whole press; a Return after it starts a
            # second training (`docs/172-curse-trainer.md`).
            if not sess.select_row(who):
                run.note(event="not-in-train-picker", who=who)
                return 1
            sess.settle(6)
            run.shot(f"{who}-trained")
            run.record("after-train", n, who)
            with sess.mon(8) as m:
                work = m.read(RECORD, SLOT_SIZE)
            run.note(event="working-record", who=who, fields=describe(work))
            sess.kbd.key("Return")
            sess.settle(3)
            run.shot(f"{who}-after-message")
            run.record("after-message", n, who)
            # **The `TRAIN WHO` list is still up.**  A training does not put
            # the party menu back, so anything looking for a menu item next
            # spends its whole timeout in front of a list that has none.
            sess.select_row("EXIT")

        for who in [w.upper() for w in args.sheet]:
            sheet(run, who)

        for n, name in enumerate(slot_names(payload_of(
                pathlib.Path(args.save).read_bytes())[1])):
            if name:
                run.record("final", n, name)

        if args.save_out:
            if save_current_game(run):
                dest = pathlib.Path(args.save_out)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(pathlib.Path(slot.dir) / "SIDE0.D64", dest)
                run.note(event="saved", to=str(dest))
            else:
                run.note(event="save-failed")
        return 0
    finally:
        if run.sess is not None:
            run.sess.terminate()
        if slot is not None:
            slot.release()
        run.note(event="done")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    st = sub.add_parser("stage", help="write ability and level inputs")
    st.add_argument("--base", required=True)
    st.add_argument("--out", required=True)
    st.add_argument("--give", action="append", default=[],
                    metavar="NAME:wis=18,lvl_paladin=2")
    st.add_argument("--repair", action="store_true",
                    help="close a SAVEAZURE the drive never finished (#298)")
    st.set_defaults(func=stage)

    sh = sub.add_parser("show", help="print the class fields of a save disk")
    sh.add_argument("disk")
    sh.set_defaults(func=show)

    rn = sub.add_parser("run", help="drive the change, the regain and a read")
    rn.add_argument("--pool", type=int, default=None)
    rn.add_argument("--disks", default=os.environ.get("COAB_DISKS", ""))
    rn.add_argument("--save", required=True)
    rn.add_argument("--change", action="append", default=[],
                    metavar="NAME:CLASS")
    rn.add_argument("--regain", action="append", default=[], metavar="NAME")
    rn.add_argument("--sheet", action="append", default=[], metavar="NAME",
                    help="photograph this character's VIEW sheet at the end")
    rn.add_argument("--experience", type=int, default=900000)
    rn.add_argument("--platinum", type=int, default=2000)
    rn.add_argument("--save-out", default="")
    rn.add_argument("--out", default="work/issue409/run")
    rn.set_defaults(func=drive)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
