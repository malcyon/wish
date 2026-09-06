#!/usr/bin/env python3
"""Drive a *Secret of the Silver Blades* training and read what it wrote.

`#344 (A converted Silver Blades dwarf, gnome or halfling keeps DOS's saving
throws, because that title's racial bonus has never been watched in the
game)`.  `goldbox/levels.py` reads `GEN $11D8` as *the constitution bonus
goes to race 3 -- the dwarf -- alone, on columns 0, 2 and 4*, which is not
what Pool of Radiance or Curse does, and until 2026-09-06 no Silver Blades
trainer had been watched writing the five bytes.  This is
`tools/cursetrain.py` for the third title, and the lever is the same one:
Silver Blades' party-menu builder is Curse's `$12AF` moved to `GEN $0991`,

    $0991  LDA #$7F / LDX #$07        the in-game menu, all but LOAD
    $0995  LDY $7F3E / BNE $09A3      a game in progress?
    $099A  LDA #$A1 / LDX #$00        the boot menu: CREATE, ADD, LOAD
    $099E  LDY #$02 / STY $4CF4
    $09A3  STX $493B                  the mask's high byte
    $09A6  LDY $7EA8 / BNE $09AE
    $09AB  AND #$F7                   ... and with no hall, no TRAIN CHARACTER

so `$7EA8` gates `TRAIN CHARACTER` here too, and poking it to `$7F` from the
monitor opens the hall wherever the party stands.

Three subcommands:

    tools/ssbtrain.py stage --base <in.d64> --out <out.d64> \\
        --give MALACHITE:xp=124000,plat=3000

        Copy a Silver Blades save disk and write named fields into named
        slots of `SAVEDBASH`.  **Those are inputs we write and they prove
        nothing**; what the trainer does with them is the measurement
        (`.claude/rules/testing.md`).  A slot is found by **the name inside
        the record**, not by the name table at `+$C00`: in this title that
        table runs in marching order while the slots do not
        (`goldbox/c64_save.py`), and on `work/193/SSBD.D64` entry 2 says
        EPONA over a slot whose record says MALACHITE.  The fields are
        `xp`, `plat`, `con`, `race`, `bits`, `dcs`, `dcl`, `hpr` and
        `lvl_<class>`; `plat` zeroes the four lesser coins.  `--repair`
        closes a `SAVEDBASH` the drive never finished (`#298`).

    tools/ssbtrain.py run --pool N --save <out.d64> --out work/issue344/run1

        `tools/ssbrun.py`: claim a pooled slot, stage the six sides and the
        save disk, boot through the cracker intro, load the party and serve
        the command port at the party menu.  It presses nothing further.

    tools/ssbtrain.py diff --before <stem> --after <stem> --class thief

        Read a pair of `$7C00`/`$7D00` hex dumps taken with `tools/porcmd
        peek`, print the field-by-field delta, and check the five stored
        saving throws against `goldbox.levels.saving_throws` for the record
        the engine wrote -- the question `#344` asks.  `--class` is then
        handed to `goldbox.levelup.plan` as well, reaching past
        `levels.TRAINER_MEASURED` in this process only, and a `plan` that
        cannot yet answer for this title is reported rather than fatal.

### The recipe, once the session is up

    savedisk <slot dir>/SIDE0.D64      # `run` has already loaded the party
    poke 7EA8 7F                       # the hall, wherever the party stands
    row VIEW CHARACTER / row EXIT      # any trip through the menu rebuilds it
    row TRAIN CHARACTER
    row <NAME>                         # this presses; do **not** add a Return

**The party's records are in memory at `$4F00 + slot * $100`**, the same
place as Curse's: `SAVEDBASH` loads at `$4B00` and its eight character slots
start `$400` in.  So a race byte poked at `$4F72 + slot * $100` and an
experience byte at `$4FE8 + slot * $100` between presses train the same
character again under a different race without a reboot; the engine copies
the roster slot to `$7C00` when the character is picked and writes it back
on success.

Nothing here writes to the player's own disks: the six sides are copied into
the slot by `tools/ssbwarp.stage`, which opens them read only.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TOOLS))

from goldbox.d64 import D64  # noqa: E402
from goldbox.record import CharacterRecord  # noqa: E402

#: Where the working character record sits while `GEN` runs.  `$11D8` reads
#: the race at `$7C72` and the constitution at `$7C18` and writes `$7C9A,X`,
#: which are record `0x072`, `0x018` and `0x09A`-`0x09E`.
RECORD = 0x7C00
RECORD_LEN = 0x200

#: The party menu's TRAIN CHARACTER gate, `GEN $09A6`; 127 is what Curse's
#: area scripts write and what opened its hall (`docs/172-curse-trainer.md`).
HALL = 0x7EA8
HALL_OPEN = 0x7F

#: `SAVEDBASH`'s geometry, from `goldbox/c64_save.py`: Curse's container
#: byte for byte under another name.
SAVE_FILE = b"SAVEDBASH"
SLOT0 = 0x400
SLOT_SIZE = 0x100
SLOTS = 8

XP = 0x0E8
MONEY = 0x0BB
PLATINUM = 0x0C3

#: What `--give` may write, as `(offset, width)`.  Every one is an **input**.
FIELDS = {
    "xp": (XP, 3),
    "con": (0x018, 1),
    "race": (0x072, 1),
    "dcs": (0x0B9, 1),
    "dcl": (0x0BA, 1),
    "hpr": (0x0ED, 1),
    "bits": (0x0EB, 1),
    "lvl_magic-user": (0x0C9, 1), "lvl_cleric": (0x0CA, 1),
    "lvl_thief": (0x0CB, 1), "lvl_fighter": (0x0CC, 1),
    "lvl_paladin": (0x0CF, 1), "lvl_ranger": (0x0D0, 1),
}

SAVES = ("save_paralysis", "save_petrification", "save_wands",
         "save_breath", "save_spell")

WATCH = [
    (0x018, 1, "constitution"),
    (0x071, 1, "thac0_base"),
    (0x072, 1, "race"),
    (0x076, 2, "hp_max"),
    (0x098, 1, "attack_level"),
    (0x09A, 1, "save_paralysis"),
    (0x09B, 1, "save_petrification"),
    (0x09C, 1, "save_wands"),
    (0x09D, 1, "save_breath"),
    (0x09E, 1, "save_spell"),
    (0x0A0, 1, "level"),
    (0x0A4, 1, "turn_power"),
    (0x0A5, 1, "thief_pick_pockets"),
    (0x0A6, 1, "thief_open_locks"),
    (0x0A7, 1, "thief_find_traps"),
    (0x0A8, 1, "thief_move_silently"),
    (0x0A9, 1, "thief_hide_in_shadows"),
    (0x0AA, 1, "thief_hear_noise"),
    (0x0AB, 1, "thief_climb_walls"),
    (0x0AC, 1, "thief_read_languages"),
    (0x0BB, 2, "copper"),
    (0x0BD, 2, "silver"),
    (0x0BF, 2, "electrum"),
    (0x0C1, 2, "gold"),
    (0x0C3, 2, "platinum"),
    (0x0C9, 1, "level_magic_user"),
    (0x0CA, 1, "level_cleric"),
    (0x0CB, 1, "level_thief"),
    (0x0CC, 1, "level_fighter"),
    (0x0CF, 1, "level_paladin"),
    (0x0D0, 1, "level_ranger"),
    (0x0D9, 1, "attack_forms"),
    (0x0E8, 3, "experience"),
    (0x0ED, 1, "hp_rolled"),
]


def payload_of(image: bytes) -> tuple[int, bytes]:
    raw = D64(image).read_file(SAVE_FILE)
    return raw[0] | raw[1] << 8, raw[2:]


def slot_names(payload: bytes) -> list[str]:
    """Each slot's name **as its own record spells it**, empty when unused."""
    out = []
    for n in range(SLOTS):
        rec = payload[SLOT0 + n * SLOT_SIZE:SLOT0 + (n + 1) * SLOT_SIZE]
        out.append(CharacterRecord.from_bytes(rec.ljust(580, b"\0")).name)
    return out


def read_u(blob: bytes, off: int, width: int) -> int:
    return int.from_bytes(blob[off:off + width], "little")


def write_u(blob: bytearray, off: int, width: int, value: int) -> None:
    blob[off:off + width] = int(value).to_bytes(width, "little")


def stage(args) -> int:
    image = pathlib.Path(args.base).read_bytes()
    load, payload = payload_of(image)
    names = [n.upper() for n in slot_names(payload)]
    body = bytearray(payload)
    for spec in args.give:
        who, _, fields = spec.partition(":")
        if who.upper() not in names:
            raise SystemExit(f"no slot is called {who!r}; the disk has "
                             f"{[n for n in names if n]}")
        n = names.index(who.upper())
        base = SLOT0 + n * SLOT_SIZE
        for pair in fields.split(","):
            key, _, val = pair.partition("=")
            value = int(val)
            if key == "plat":
                for coin in range(4):
                    write_u(body, base + MONEY + 2 * coin, 2, 0)
                write_u(body, base + PLATINUM, 2, value)
            elif key in FIELDS:
                off, width = FIELDS[key]
                write_u(body, base + off, width, value)
            else:
                raise SystemExit(f"unknown field {key!r}; use plat= or one "
                                 f"of {', '.join(sorted(FIELDS))}")
        print(f"{names[n]:14s} slot {n}: race {body[base + 0x72]}  con "
              f"{body[base + 0x18]:2d}  xp {read_u(body, base + XP, 3):7d}"
              f"  platinum {read_u(body, base + PLATINUM, 2):5d}")
    disk = D64(image)
    disk.write_file_inplace(SAVE_FILE,
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


def _record(stem: str) -> CharacterRecord:
    a = bytes.fromhex(pathlib.Path(f"{stem}-a.hex").read_text().strip())
    b = bytes.fromhex(pathlib.Path(f"{stem}-b.hex").read_text().strip())
    return CharacterRecord.from_bytes((a + b).ljust(580, b"\0"))


def class_levels(record: CharacterRecord, tables) -> dict[str, int]:
    out = {}
    for name in tables.class_order:
        if name is None:
            continue
        level = record.get("level_" + name.replace("-", "_")) or 0
        if level:
            out[name] = level
    return out


def check_saves(after: CharacterRecord) -> tuple[int, int]:
    """The five stored saves against `levels.saving_throws`; `(ok, total)`."""
    from goldbox import levels  # noqa: PLC0415

    ssb = levels.SECRET_OF_THE_SILVER_BLADES
    held = class_levels(after, ssb)
    race, con = after.get("race") or 0, after.get("constitution") or 0
    want = levels.saving_throws(held, race, con, ssb)
    got = tuple(after.get(f) or 0 for f in SAVES)
    print(f"  {after.name}: race {race}, constitution {con}, {held}")
    print(f"  stored by the engine {got}")
    print(f"  levels.saving_throws {want}"
          f"{'' if want == got else '   <-- DIFFERS'}")
    if want is None:
        return 0, 5
    return sum(a == b for a, b in zip(got, want)), 5


def compare(args) -> int:
    from goldbox import games, levels, levelup  # noqa: PLC0415

    ssb = games.SECRET_OF_THE_SILVER_BLADES
    before, after = _record(args.before), _record(args.after)
    print(f"{before.name} -> {after.name}")
    for off, width, name in WATCH:
        was = read_u(bytes(before), off, width)
        now = read_u(bytes(after), off, width)
        if was != now:
            print(f"  {off:#05x} {name:22s} {was:8d} -> {now:8d}")
    ok, total = check_saves(after)
    print(f"{ok} of {total} saving-throw columns reproduce")
    if not args.classes:
        return 0 if ok == total else 1
    levels.TRAINER_MEASURED = frozenset(
        set(levels.TRAINER_MEASURED) | {ssb.key})
    rolled = (after.get("hp_rolled") or 0) - (before.get("hp_rolled") or 0)
    record, names = before, set()
    try:
        for i, cls in enumerate(args.classes):
            p = levelup.plan(record, cls, game=ssb,
                             rolled=rolled if i == 0 else 0)
            names |= set(p.fields)
            record = levelup.apply_to(record, p)
    except Exception as e:  # noqa: BLE001 -- reported, not fatal
        print(f"levelup.plan cannot replay this title yet: {e!r}")
        return 0 if ok == total else 1
    pok = 0
    for name in sorted(names):
        got, want = after.get(name), record.get(name)
        pok += got == want
        print(f"  {'ok ' if got == want else 'NO '} {name:22s} "
              f"plan {want!r:>12}  engine {got!r:>12}")
    print(f"{pok} of {len(names)} derived fields reproduce through plan, "
          f"roll total {rolled}")
    return 0 if ok == total else 1


def drive(args) -> int:
    from tools import ssbrun  # noqa: PLC0415

    argv = ["--save", args.save, "--out", args.out]
    if args.pool is not None:
        argv += ["--pool", str(args.pool)]
    if args.disks:
        argv += ["--disks", args.disks]
    ssbrun.run(argv)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    st = sub.add_parser("stage", help="write input fields into a save")
    st.add_argument("--base", required=True)
    st.add_argument("--out", required=True)
    st.add_argument("--give", action="append", default=[],
                    metavar="NAME:xp=N,plat=N")
    st.add_argument("--repair", action="store_true",
                    help="close a SAVEDBASH the drive never finished (#298)")
    st.set_defaults(func=stage)

    rn = sub.add_parser("run", help="boot a Silver Blades session on a slot")
    rn.add_argument("--pool", type=int, default=None)
    rn.add_argument("--disks", default=os.environ.get("SSB_DISKS", ""))
    rn.add_argument("--save", required=True)
    rn.add_argument("--out", default="work/issue344/run")
    rn.set_defaults(func=drive)

    df = sub.add_parser("diff", help="diff a before/after record pair")
    df.add_argument("--before", required=True)
    df.add_argument("--after", required=True)
    df.add_argument("--class", dest="classes", action="append", default=[])
    df.set_defaults(func=compare)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
