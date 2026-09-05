#!/usr/bin/env python3
"""Drive a *Curse of the Azure Bonds* training and read what the trainer wrote.

`#18 (Measure Curse's trainer so Level Up works there)` step 3.  Everything
else on that ticket was read off `GEN` or reproduced against a character SSI
shipped; this is the part that has to be watched happening, because two of
Curse's own rules cannot be settled any other way -- `GEN $11AB` divides a
multi-class hit-die roll and constitution total by the class count and rounds
up **at random**, and no record on any disk has ever been seen with the
sturdy-race saving-throw bonus of `GEN $0F19` applied to it.

The lever is `GEN $12AF`, which builds the party menu's item mask:

    $12AF  LDA $4CFD / BEQ ...        a quest flag; non-zero cuts the menu down
    $12BA  LDA #$A1 / LDX #$00        the boot menu: CREATE, ADD, LOAD
    $12BE  LDY $7F3E / BEQ ...        a game in progress?
    $12C3  LDA #$7F / LDX #$07        the in-game menu, all but LOAD
    $12C7  STX $4AFA                  the mask's high byte
    $12CA  LDY $7EA8 / BNE $12D1
    $12CF  AND #$F7                   ... and with no hall, no TRAIN CHARACTER

So `$7EA8` is Curse's gate, the C64 counterpart of the DOS word at
`SAVGAM<slot>.DAT+0xD51` that `#234 (A dual-classed Curse or Silver Blades
character converted to DOS loses the class he trained out of)` found.  The
area scripts write it -- `ECL01`, `ECL03`, `ECL50` and `ECL51` each issue
`SAVE 127, =[$7EA8]` -- and `GEN $2029` puts it back to 0 on the way out.
Writing 127 from the monitor opens the hall wherever the party is standing,
which is `docs/70-driving-the-game.md`'s "open the gate rather than walk to
it" and saves a session of map-reading.

Two subcommands:

    tools/cursetrain.py stage --base <in.d64> --out <out.d64> --repair \\
        --give SHARA:xp=30000,plat=2000 ...

        Copy a Curse save disk and write named fields into named slots of
        `SAVEAZURE`.  **Those are inputs we write and they prove nothing**;
        what the trainer does with them is the measurement
        (`.claude/rules/testing.md`).  `--repair` closes a `SAVEAZURE` the
        drive never finished writing, which is what every image copied out of
        a pool slot after a `SAVE CURRENT GAME` looks like -- `$02` in the
        directory type byte and a block count of zero, and the game refuses to
        load one (`#298`).  The fields are `xp`, `plat`, `con`, `bits`,
        `dcs`, `dcl`, `hpr` and `lvl_<class>`; `plat` zeroes the four lesser
        coins so the total is exactly what it says.

    tools/cursetrain.py run --pool N --disks <PIS> --save <out.d64> \\
        --out work/issue18/run1

        Claim a pooled VICE slot, stage the six sides and the save disk,
        boot, and serve the command port.  **It stops there and does not
        press TRAIN itself**, because four things in this front end have to
        be watched rather than scripted: `YES` on the load bar answers only
        the KERNAL buffer, the save-disk prompt has to be answered by
        attaching `SIDE0.D64` by hand, `$453B`'s side prompt needs
        `curserun`'s two `NOP`s, and the key that dismisses
        `YOU ARE NOW A LEVEL n` is read twice often enough to start a second
        training nobody asked for.  The recipe is in `docs/172-curse-trainer.md`.

    tools/cursetrain.py diff --before <stem> --after <stem> --class cleric

        Read a pair of `$7C00`/`$7D00` hex dumps taken with
        `tools/porcmd peek`, print the field-by-field delta, and replay it
        through `goldbox.levelup.plan` -- which is the check that matters:
        every derived field the engine wrote has to come back out of our own
        module.  `--class` may be given more than once, in the order the
        engine raised them, because Curse's trainer raises **every**
        qualifying class in one visit and `plan` raises one.

### The recipe, once the session is up

`run` boots and serves; these are the `tools/porcmd` lines that drove eight
trainings on 2026-09-05, and they are here because working them out is what
cost the time.

    savedisk <slot dir>/SIDE0.D64      # `drive` does not set it
    row LOAD SAVED GAME
    kernal 0D                          # YES is already white, and the bar
                                       # reads the KERNAL buffer only
    settle 12
    poke 7EA8 7F                       # the hall, wherever the party stands
    row VIEW CHARACTER / row EXIT      # any trip through the menu rebuilds it
    row TRAIN CHARACTER
    row <NAME>                         # this presses; do **not** add a Return

**`row <NAME>` is the whole press.** Adding a Return after it starts a second
training, which is what put a third thousand gold on LEDERA in the first
session; the second call then says `UNABLE TO ADVANCE` and looks like a
refusal of the first.

**The party's records are in memory at `$4F00 + slot * $100`.** `SAVEAZURE`
loads at `$4B00` and its eight character slots start `$400` in, so an
experience byte poked at `$4FE8` is slot 0's -- which is how a character is
trained again and again without a reboot, since `GEN $2086` clamps the number
after every press.  The engine copies the roster slot into the working record
at `$7C00` when the character is picked and writes it back on success only.

**A magic-user's training stops at `INSERT SIDE # 1`**, because its spell menu
loads from side 1.  `curserun.CurseSession.patch_disk_prompt` is the way past
it and `run` does not apply it; from the command port it is
`poke 459A eaea` and `poke 459F eaea`, after checking they read `d0 a9` and
`d0 a4`.

Nothing here writes to the player's own disks: the six sides are copied into
the slot by `tools/curserun.py`, which opens them read only.
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
sys.path.insert(0, str(TOOLS))

from goldbox.d64 import D64  # noqa: E402

#: Where the working character record sits while `GEN` runs.  `#18`'s own
#: census fixed it: `GEN $151D CMP $7CC9,X` is the per-class level array at
#: record `0x0C9`, and `$2041 LDA $7D00` is `roster_in_use` at `0x100`.
RECORD = 0x7C00
#: How much of it to read.  The 580-byte export runs past `$7E44`, which
#: `LIBRARY` uses as a variable, so only the first 512 bytes are the record
#: for certain -- and every field a training writes is inside them.
RECORD_LEN = 0x200

#: The party menu's TRAIN CHARACTER gate, `GEN $12CA`.  127 is what the area
#: scripts themselves write (`ECL01+$1008 SAVE 127, =[$7EA8]`).
HALL = 0x7EA8
HALL_OPEN = 0x7F

#: The `SAVEAZURE` payload's own geometry, from `goldbox/c64_save.py`.
SLOT0 = 0x400
SLOT_SIZE = 0x100
NAMES = 0xC00
NAME_SIZE = 16
SLOTS = 8

#: Record offsets this tool reads and writes.  Names are
#: `goldbox/layout.py`'s.
XP = 0x0E8
MONEY = 0x0BB          # five u16 coin counts: copper, silver, electrum,
PLATINUM = 0x0C3       # gold, platinum -- weights 1, 10, 100, 200, 1000
                       # copper, out of `GEN $2160`

#: What `--give` may write, as `(offset, width)`.  Everything here is an
#: **input**: the measurement is what the trainer does with it, never the value
#: read back.  `lvl_*` indexes the per-class level array at `0x0C9` in
#: `LevelTables.class_order` order, which is the order `GEN $1515` walks.
FIELDS = {
    "xp": (XP, 3),
    "con": (0x018, 1),
    "dcs": (0x0B9, 1),
    "dcl": (0x0BA, 1),
    "hpr": (0x0ED, 1),
    "bits": (0x0EB, 1),
    "lvl_magic-user": (0x0C9, 1), "lvl_cleric": (0x0CA, 1),
    "lvl_thief": (0x0CB, 1), "lvl_fighter": (0x0CC, 1),
    "lvl_paladin": (0x0CF, 1), "lvl_ranger": (0x0D0, 1),
}

#: What to print a diff of, so a reader sees the training and not the
#: bookkeeping.  Every one is inside the 256 bytes a save slot keeps.
WATCH = [
    (0x071, 1, "thac0_base"),
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
    """The `SAVEAZURE` load address and payload out of a `.d64`."""
    raw = D64(image).read_file(b"SAVEAZURE")
    return raw[0] | raw[1] << 8, raw[2:]


def slot_names(payload: bytes) -> list[str]:
    out = []
    for n in range(SLOTS):
        blob = payload[NAMES + n * NAME_SIZE:NAMES + (n + 1) * NAME_SIZE]
        out.append(blob.split(b"\x00")[0].decode("latin1"))
    return out


def read_u(blob: bytes, off: int, width: int) -> int:
    return int.from_bytes(blob[off:off + width], "little")


def write_u(blob: bytearray, off: int, width: int, value: int) -> None:
    blob[off:off + width] = int(value).to_bytes(width, "little")


def describe(record: bytes) -> dict:
    return {name: read_u(record, off, width) for off, width, name in WATCH}


def stage(args) -> int:
    """Copy a save disk, writing experience and platinum into named slots."""
    image = pathlib.Path(args.base).read_bytes()
    load, payload = payload_of(image)
    names = slot_names(payload)
    body = bytearray(payload)
    for spec in args.give:
        who, _, fields = spec.partition(":")
        if who.upper() not in [n.upper() for n in names]:
            raise SystemExit(f"no slot is called {who!r}; the disk has {names}")
        n = [x.upper() for x in names].index(who.upper())
        base = SLOT0 + n * SLOT_SIZE
        for pair in fields.split(","):
            key, _, val = pair.partition("=")
            value = int(val)
            if key == "plat":
                for coin in range(4):          # zero the four lesser coins,
                    write_u(body, base + MONEY + 2 * coin, 2, 0)
                write_u(body, base + PLATINUM, 2, value)
            elif key in FIELDS:
                off, width = FIELDS[key]
                write_u(body, base + off, width, value)
            else:
                raise SystemExit(f"unknown field {key!r}; use plat= or one of "
                                 f"{', '.join(sorted(FIELDS))}")
        print(f"{names[n]:10s} slot {n}: xp {read_u(body, base + XP, 3):8d}"
              f"  platinum {read_u(body, base + PLATINUM, 2):5d}")
    disk = D64(image)
    disk.write_file_inplace(b"SAVEAZURE",
                            load.to_bytes(2, "little") + bytes(body))
    pathlib.Path(args.out).write_bytes(disk.to_bytes())
    if args.repair:
        # An image copied out of a pool slot before the drive finished closing
        # `SAVEAZURE` is `*PRG` with no block count, and the game answers
        # `UNABLE TO LOAD SAVED GAME.` -- `#298`.  The payload is already
        # there, so setting the bit and the count is the whole repair, and it
        # is done to our copy and never to what it was copied from.
        from tools.curseload import close_splat  # noqa: PLC0415

        for entry in close_splat(args.out):
            name = entry["name"]
            name = name.decode("latin1") if isinstance(name, bytes) else name
            print(f"closed {name}: type {entry['type_was']} -> "
                  f"{entry['type_now']}, {entry['blocks_now']} blocks")
    print(f"wrote {args.out}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    st = sub.add_parser("stage", help="write experience and money into a save")
    st.add_argument("--base", required=True, help="the .d64 to copy")
    st.add_argument("--out", required=True, help="the .d64 to write")
    st.add_argument("--give", action="append", default=[],
                    metavar="NAME:xp=N,plat=N",
                    help="what to write into that character's slot")
    st.add_argument("--repair", action="store_true",
                    help="close a SAVEAZURE the drive never finished (#298)")
    st.set_defaults(func=stage)

    rn = sub.add_parser("run", help="boot a Curse session on a pooled slot")
    rn.add_argument("--pool", type=int, default=None)
    rn.add_argument("--disks", default=os.environ.get("COAB_DISKS", ""))
    rn.add_argument("--save", required=True)
    rn.add_argument("--out", default="work/issue18/run")
    rn.set_defaults(func=drive)

    df = sub.add_parser("diff", help="diff a before/after record pair")
    df.add_argument("--before", required=True,
                    help="stem of the <stem>-a.hex/<stem>-b.hex pair")
    df.add_argument("--after", required=True)
    df.add_argument("--class", dest="classes", action="append", default=[],
                    help="the class raised; repeat in the engine's own order")
    df.add_argument("--learn", type=int, default=None,
                    help="the spell id a magic-user picked")
    df.set_defaults(func=compare)

    args = ap.parse_args(argv)
    return args.func(args)


def _record(stem: str):
    """The 580-byte record out of a `$7C00`/`$7D00` `porcmd peek` pair."""
    from goldbox.record import CharacterRecord  # noqa: PLC0415

    a = bytes.fromhex(pathlib.Path(f"{stem}-a.hex").read_text().strip())
    b = bytes.fromhex(pathlib.Path(f"{stem}-b.hex").read_text().strip())
    return CharacterRecord.from_bytes((a + b).ljust(580, b"\0"))


def compare(args) -> int:
    """Print the delta, then replay it through `goldbox.levelup.plan`.

    The replay reaches past `levels.TRAINER_MEASURED` **in this process
    only**, the way `tools/cursedisk.py` reaches past `dos.CONVERTS`: the
    whole point is to find out whether the module reproduces the trainer
    before the key that trusts it is added.
    """
    from goldbox import games, levels, levelup  # noqa: PLC0415

    curse = games.CURSE_OF_THE_AZURE_BONDS
    before, after = _record(args.before), _record(args.after)
    print(f"{before.name} -> {after.name}")
    for off, width, name in WATCH:
        was, now = read_u(bytes(before), off, width), read_u(bytes(after),
                                                            off, width)
        if was != now:
            print(f"  {off:#05x} {name:22s} {was:8d} -> {now:8d}")
    if not args.classes:
        return 0
    levels.TRAINER_MEASURED = frozenset(
        set(levels.TRAINER_MEASURED) | {curse.key})
    rolled = (after.get("hp_rolled") or 0) - (before.get("hp_rolled") or 0)
    record, names, ok, total = before, set(), 0, 0
    for i, cls in enumerate(args.classes):
        kw = {"game": curse, "rolled": rolled if i == 0 else 0}
        if args.learn is not None:
            kw["learn"] = args.learn
        p = levelup.plan(record, cls, **kw)
        names |= set(p.fields)
        record = levelup.apply_to(record, p)
    for name in sorted(names):
        got, want = after.get(name), record.get(name)
        total += 1
        ok += got == want
        print(f"  {'ok ' if got == want else 'NO '} {name:22s} "
              f"plan {want!r:>12}  engine {got!r:>12}")
    print(f"{ok} of {total} derived fields reproduce, roll total {rolled}")
    return 0 if ok == total else 1


def drive(args) -> int:
    """Stage a slot, boot Curse and serve the command port."""
    from tools import curserun  # noqa: PLC0415
    from tools import session as por

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    log = (out / "run.jsonl").open("a")

    def note(**kw):
        kw["t"] = round(time.time(), 2)
        log.write(json.dumps(kw) + "\n")
        log.flush()
        print(json.dumps(kw), flush=True)

    slot = por.claim_slot(args.pool, note=os.environ.get("POR_AGENT", "i18"))
    note(event="slot", n=slot.n, monitor=slot.port, cmd=slot.cmd_port,
         display=slot.display, dir=str(slot.dir))
    disk = curserun.stage(slot, args.disks, args.save)
    sess = curserun.CurseSession(disk, slot=slot)
    note(event="booting")
    if not sess.boot():
        note(event="boot-failed")
        return 1
    note(event="booted")
    por.serve(sess)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
