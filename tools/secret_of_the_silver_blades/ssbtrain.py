#!/usr/bin/env python3
"""Drive a *Secret of the Silver Blades* training and read what it wrote.

`#344 (A converted Silver Blades dwarf, gnome or halfling keeps DOS's saving
throws, because that title's racial bonus has never been watched in the
game)`.  `goldbox/levels.py` reads `GEN $11D8` as *the constitution bonus
goes to race 3 -- the dwarf -- alone, on columns 0, 2 and 4*, which is not
what Pool of Radiance or Curse does, and until 2026-09-06 no Silver Blades
trainer had been watched writing the five bytes.  This is
`tools/curse_of_the_azure_bonds/cursetrain.py` for the third title, and the lever is the same one:
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

    tools/secret_of_the_silver_blades/ssbtrain.py stage --base <in.d64> --out <out.d64> \\
        --give MALACHITE:xp=124000,plat=3000

        Copy a Silver Blades save disk and write named fields into named
        slots of `SAVEDBASH`.  **Those are inputs we write and they prove
        nothing**; what the trainer does with them is the measurement
        (`.claude/rules/testing.md`).  A slot is found by **the name inside
        the record**, not by the name table at `+$C00`: in this title that
        table runs in marching order while the slots do not
        (`goldbox/c64_save.py`), and on `cited/193/SSBD.D64` entry 2 says
        EPONA over a slot whose record says MALACHITE.  The fields are
        `xp`, `plat`, `con`, `race`, `bits`, `dcs`, `dcl`, `hpr`, `int`,
        `wis` and `lvl_<class>`; `plat` zeroes the four lesser coins, and
        `int` and `wis` each write **two** bytes -- the permanent score at
        `0x066`/`0x067`, which is what this title's trainer reads
        (`$18AA LDA $7C66`, `$0F35 LDA $7C67`), and the score in force at
        `0x015`/`0x016`, so the sheet agrees with it.  `--repair` closes a
        `SAVEDBASH` the drive never finished (`#298`).

    tools/secret_of_the_silver_blades/ssbtrain.py run --pool N --save <out.d64> --out DIR

        `tools/secret_of_the_silver_blades/ssbrun.py`: claim a pooled slot, stage the six sides and the
        save disk, boot through the cracker intro, load the party and serve
        the command port at the party menu.  It presses nothing further.

    tools/secret_of_the_silver_blades/ssbtrain.py diff --before <stem> --after <stem> --class thief

        Read a pair of `$7C00`/`$7D00` hex dumps taken with `tools/c64/porcmd
        peek`, print the field-by-field delta, and check the five stored
        saving throws against `goldbox.levels.saving_throws` for the record
        the engine wrote -- the question `#344` asks.  `--class` is then
        handed to `goldbox.levelup.plan` as well, reaching past
        `levels.TRAINER_MEASURED` in this process only, and a `plan` that
        cannot yet answer for this title is reported rather than fatal.
        With **no** `--class` the replay goes through `plan_all`, which is
        what `automap.actions.LevelUp.run` calls and what this title's
        `trains_all_ready_classes` needs.  `--learn <id>` is the spell a
        magic-user picked off the menu at `$1896`, and the sixteen-byte
        spellbook at `0x078` is diffed id by id whether or not one was
        picked -- `Plan.spellbook` is a separate attribute from
        `Plan.fields` and nothing compared it before `#89`.

        **The trainer's inputs come off `--after`.**  A run that pokes the
        roster between presses changes bytes the trainer *reads* -- race,
        the six abilities in force, the six permanent ones -- between the
        two dumps, and replaying from the stale `--before` then derives the
        wrong row and reports every field that depends on it as a mismatch.
        Three of `#344`'s six pairs read as 9-10 failures for exactly that
        reason and all three are clean once the inputs are taken from the
        record the engine actually trained.  Each one taken this way is
        printed, so a substitution is never silent.

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
the slot by `tools/secret_of_the_silver_blades/ssbwarp.stage`, which opens them read only.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import socket
import sys
import time

TOOLS = pathlib.Path(__file__).resolve().parent.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from goldbox.d64 import D64  # noqa: E402
from goldbox.record import CharacterRecord  # noqa: E402
from tools.registry import scratch  # noqa: E402

#: Where the working character record sits while `GEN` runs.  `$11D8` reads
#: the race at `$7C72` and the constitution at `$7C18` and writes `$7C9A,X`,
#: which are record `0x072`, `0x018` and `0x09A`-`0x09E`.
RECORD = 0x7C00
RECORD_LEN = 0x200

#: The party menu's TRAIN CHARACTER gate, `GEN $09A6`; 127 is what Curse's
#: area scripts write and what opened its hall (`docs/172-curse-trainer.md`).
HALL = 0x7EA8
HALL_OPEN = 0x7F

#: **The roster, as the running game holds it.** `SAVEDBASH` loads at `$4B00`
#: and its eight slots start `$400` in, so slot *n* is here -- the record the
#: trainer copies to `$7C00` when a name is picked and writes back on
#: success.  Measured 2026-09-16: with the shipped party on `SILVER-6.D64`
#: loaded, all four slots read back **byte for byte identical** to the same
#: slots of `SAVEDBASH` on the disk.
ROSTER = 0x4F00

#: **The party list's own current hit points, which the record page has not
#: got.**  A record stores `hp_max` at `0x076` and no current total; the number
#: the party list prints, and the number `SAVE CURRENT GAME` writes into the
#: save's roster block at payload `+$1C00`, lives here at
#: `roster_base + slot * $20 + $19` -- `$4B00 + $1C00` for this title,
#: `goldbox/c64_save.py`.  A training press raises both together, so poking a
#: pre-press record page back over a character the engine has already trained
#: leaves a save whose current hit points exceed its own maximum, which is what
#: `WISH-SPEC-ssb-89-train-input` holds (`#605`).  Measured live 2026-09-20:
#: MORGAINE's byte read 35 before the press and 40 after, beside `hp_max`
#: 35 -> 40 in the record.
PARTY_CACHE = 0x6700
PARTY_CACHE_STRIDE = 0x20
PARTY_CACHE_HP = 0x19
HP_MAX = 0x076

#: What the magic-user menu at `GEN $1896` leaves behind, and the whole
#: reason a menu can be measured without reading the screen.
#: `$18DA STY $1C10` is how many ids it offered, `$18EB STA $7A00,X` is the
#: ids themselves in the order the menu lists them, and `$1902 STA $2ACE` is
#: the one the player picked.  Every reference to `$1C10` in `GEN` is inside
#: `$18D8`-`$1B21` and `$2A2D`, all of it this menu, so zeroing it before a
#: press makes a non-zero reading afterwards this press's and no other's.
MENU_COUNT = 0x1C10
MENU_IDS = 0x7A00
MENU_PICKED = 0x2ACE

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
    "level": (0x0A0, 1),
    "lvl_magic-user": (0x0C9, 1), "lvl_cleric": (0x0CA, 1),
    "lvl_thief": (0x0CB, 1), "lvl_fighter": (0x0CC, 1),
    "lvl_paladin": (0x0CF, 1), "lvl_ranger": (0x0D0, 1),
}

#: `--give int=` and `--give wis=` each write two bytes: the permanent score
#: the trainer reads and the score in force the sheet draws.
PAIRED = {"int": (0x015, 0x066), "wis": (0x016, 0x067)}

#: What the trainer **reads and never writes**, as `(offset, width, what)`.
#: A poke between two dumps moves these, and a replay from the stale
#: `--before` then derives the wrong row -- see `compare`.
INPUTS = ((0x014, 6, "abilities in force"),
          (0x065, 6, "permanent abilities"),
          (0x072, 1, "race"))

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
            elif key in PAIRED:
                for off in PAIRED[key]:
                    write_u(body, base + off, 1, value)
            elif key in FIELDS:
                off, width = FIELDS[key]
                write_u(body, base + off, width, value)
            else:
                raise SystemExit(
                    f"unknown field {key!r}; use plat= or one of "
                    f"{', '.join(sorted(set(FIELDS) | set(PAIRED)))}")
        print(f"{names[n]:14s} slot {n}: race {body[base + 0x72]}  con "
              f"{body[base + 0x18]:2d}  int {body[base + 0x66]:2d}  wis "
              f"{body[base + 0x67]:2d}  xp {read_u(body, base + XP, 3):7d}"
              f"  platinum {read_u(body, base + PLATINUM, 2):5d}")
    disk = D64(image)
    disk.write_file_inplace(SAVE_FILE,
                            load.to_bytes(2, "little") + bytes(body))
    pathlib.Path(args.out).write_bytes(disk.to_bytes())
    if args.repair:
        from tools.curse_of_the_azure_bonds.curseload import (
            close_splat,  # noqa: PLC0415
        )

        for entry in close_splat(args.out):
            name = entry["name"]
            name = name.decode("latin1") if isinstance(name, bytes) else name
            print(f"closed {name}: type {entry['type_was']} -> "
                  f"{entry['type_now']}, {entry['blocks_now']} blocks")
    print(f"wrote {args.out}")
    return 0


def _record(stem: str) -> CharacterRecord:
    """The record out of a `tools/c64/porcmd peek` dump.

    `<stem>-a.hex` and `<stem>-b.hex` are `$7C00` and `$7D00`.  A dump of a
    **roster slot** -- `$4F00 + slot * $100`, where the trainer reads the
    record from and writes it back to -- is 256 bytes and has no second
    half, so a missing `-b.hex` is zero-filled rather than an error: every
    field this tool compares lives below `0x100`.
    """
    a = bytes.fromhex(pathlib.Path(f"{stem}-a.hex").read_text().strip())
    second = pathlib.Path(f"{stem}-b.hex")
    b = bytes.fromhex(second.read_text().strip()) if second.exists() else b""
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


def inputs_from_after(before: CharacterRecord, after: CharacterRecord,
                      overrides: dict[str, int]) -> CharacterRecord:
    """`before` carrying the trainer's **inputs** as the engine saw them.

    Race, the six abilities in force and the six permanent ones are read by
    the trainer and never written by it, so where the two dumps disagree the
    difference is a poke between the presses and `--after` is the record the
    engine actually trained.  Taking them off `--before` is what made three
    of `#344`'s six pairs report 9-10 mismatches that were the tool's and not
    the model's.  Each substitution prints.
    """
    body = bytearray(bytes(before))
    late = bytes(after)
    for off, width, what in INPUTS:
        was, now = body[off:off + width], late[off:off + width]
        if was != now:
            print(f"  input {what:20s} {was.hex(' ')} -> {now.hex(' ')}"
                  f"  (taken from --after)")
            body[off:off + width] = now
    for key, value in overrides.items():
        for off in PAIRED[key]:
            body[off] = value
        print(f"  input {key:20s} forced to {value} at "
              f"{', '.join(f'{o:#05x}' for o in PAIRED[key])}")
    return CharacterRecord.from_bytes(bytes(body))


def compare_spellbook(replayed: CharacterRecord, after: CharacterRecord,
                      game) -> tuple[int, int]:
    """The sixteen-byte mask at `0x078`, id by id; `(ok, total)`.

    `Plan.spellbook` is a separate attribute from `Plan.fields`, so the loop
    over `set(p.fields)` never reaches it and no test in this repository
    compared a trained spellbook before `#89`.
    """
    from goldbox import spells  # noqa: PLC0415

    want = spells.spellbook_raw(replayed)[:16]
    got = spells.spellbook_raw(after)[:16]
    wanted = set(spells.spells_known(bytes(replayed), game))
    engine = set(spells.spells_known(bytes(after), game))
    print(f"  spellbook plan   {want.hex(' ')}")
    print(f"  spellbook engine {got.hex(' ')}"
          f"{'' if want == got else '   <-- DIFFERS'}")
    if wanted != engine:
        print(f"  plan grants and the engine did not: "
              f"{sorted(wanted - engine)}")
        print(f"  the engine granted and plan did not: "
              f"{sorted(engine - wanted)}")
    return (16 if want == got else sum(a == b for a, b in zip(want, got))), 16


def compare(args) -> int:
    from goldbox import c64_port, levels, levelup  # noqa: PLC0415

    ssb = c64_port.SECRET_OF_THE_SILVER_BLADES
    before, after = _record(args.before), _record(args.after)
    print(f"{before.name} -> {after.name}")
    for off, width, name in WATCH:
        was = read_u(bytes(before), off, width)
        now = read_u(bytes(after), off, width)
        if was != now:
            print(f"  {off:#05x} {name:22s} {was:8d} -> {now:8d}")
    ok, total = check_saves(after)
    print(f"{ok} of {total} saving-throw columns reproduce")
    overrides = {k: getattr(args, k) for k in PAIRED
                 if getattr(args, k) is not None}
    before = inputs_from_after(before, after, overrides)
    levels.TRAINER_MEASURED = frozenset(
        set(levels.TRAINER_MEASURED) | {ssb.key})
    rolled = (after.get("hp_rolled") or 0) - (before.get("hp_rolled") or 0)
    record, names = before, set()
    try:
        if args.classes:
            for i, cls in enumerate(args.classes):
                p = levelup.plan(record, cls, game=ssb, learn=args.learn,
                                 rolled=rolled if i == 0 else 0)
                names |= set(p.fields)
                record = levelup.apply_to(record, p)
        else:
            # `trains_all_ready_classes` is set for this title, so one press
            # raises every ready class and `plan_all` is the walk
            # `automap.actions.LevelUp.run` itself makes.  It takes no
            # `rolled`, so the die is compared rather than handed in.
            for p in levelup.plan_all(record, game=ssb, learn=args.learn):
                names |= set(p.fields)
                record = levelup.apply_to(record, p)
    except Exception as e:  # noqa: BLE001 -- reported, not fatal
        print(f"levelup.plan cannot replay this title yet: {e!r}")
        return 1
    pok = 0
    for name in sorted(names):
        got, want = after.get(name), record.get(name)
        pok += got == want
        print(f"  {'ok ' if got == want else 'NO '} {name:22s} "
              f"plan {want!r:>12}  engine {got!r:>12}")
    print(f"{pok} of {len(names)} derived fields reproduce through plan, "
          f"roll total {rolled}")
    sok, stotal = compare_spellbook(record, after, ssb)
    print(f"{sok} of {stotal} spellbook bytes reproduce")
    return 0 if (ok == total and pok == len(names) and sok == stotal) else 1


def cmd(port: int, *words) -> str:
    """One line to a `tools/c64/session.py` command server; its whole reply."""
    sock = socket.create_connection(("127.0.0.1", port), timeout=600)
    sock.sendall((" ".join(str(w) for w in words) + "\n").encode())
    out = b""
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            break
        out += chunk
    sock.close()
    return out.decode("latin1")


def _peek(port: int, addr: int, length: int) -> bytes:
    # `session.handle`'s `peek` takes the address in hex and the **length in
    # decimal**, and prints hex.  A `peek 5100 100` that looks like 256 bytes
    # is 100 of them, which is how this tool first read a record with no
    # class levels in it at all.
    return bytes.fromhex(cmd(port, "peek", f"{addr:X}", length).strip())


def press(args) -> int:
    """One `TRAIN CHARACTER` press, staged, pressed and dumped.

    The whole 256-byte roster slot is written before the press rather than
    the handful of bytes that change, so `--before` is a record this tool
    composed and the engine then trained -- there is nothing left over from
    the press before it to go stale.  `--set` takes the same field names
    `stage --give` does.

    **The party list's current hit points are written too**, at
    `PARTY_CACHE`, because they are not in the record page: without them a
    save taken between two presses of the same character holds the earlier
    press's total beside the composed record's lower maximum (`#605`).

    The spell menu is driven only when one was built: `$1C10` is zeroed and
    `$7A00` filled with `$FF` first, so a count that comes back non-zero is
    this press's menu and the ids beside it are its own.
    """
    port = args.port
    base = bytearray(bytes.fromhex(
        pathlib.Path(args.record).read_text().strip()))
    if len(base) != SLOT_SIZE:
        raise SystemExit(f"{args.record} holds {len(base)} bytes, not "
                         f"{SLOT_SIZE}")
    for spec in args.set:
        for pair in spec.split(","):
            key, _, val = pair.partition("=")
            value = int(val)
            if key in PAIRED:
                for off in PAIRED[key]:
                    base[off] = value
            elif key in FIELDS:
                off, width = FIELDS[key]
                write_u(base, off, width, value)
            else:
                raise SystemExit(f"unknown field {key!r}")
    at = ROSTER + args.slot * SLOT_SIZE
    out = pathlib.Path(args.out)
    scratch.ensure(out.parent)

    cmd(port, "poke", f"{at:X}", base.hex())
    # The record page carries no current hit points, so the party list's copy
    # keeps whatever the last press left it at and a save taken here holds a
    # character with more hit points than their own maximum (`#605`).  Written
    # to the poked record's own `hp_max`, which is what a press sets it to.
    hp = min(read_u(base, HP_MAX, 2), 0xFF)
    cmd(port, "poke",
        f"{PARTY_CACHE + args.slot * PARTY_CACHE_STRIDE + PARTY_CACHE_HP:X}",
        f"{hp:02x}")
    cmd(port, "poke", f"{MENU_COUNT:X}", "00")
    cmd(port, "poke", f"{MENU_IDS:X}", "ff" * 64)
    before = _peek(port, at, SLOT_SIZE)
    if before != bytes(base):
        raise SystemExit("the roster slot did not take the poke")
    pathlib.Path(f"{args.out}-before-a.hex").write_text(before.hex())

    if args.enter:
        cmd(port, "row", "TRAIN CHARACTER")
    cmd(port, "row", args.name)
    # **`row` returns when the key is sent, not when the trainer has run.**
    # `$18DA` writes the count part-way through the raise, and a press read
    # the moment the highlight was picked came back zero with the menu on
    # screen a second later -- so this settles first, and it also answers the
    # `INSERT SIDE A` the menu needs before it can print a spell's name.
    cmd(port, "settle", 12)
    count = _peek(port, MENU_COUNT, 1)[0]
    offered = list(_peek(port, MENU_IDS, max(count, 1))[:count])
    print(f"menu offered {count} ids: {offered}")
    picked = None
    if count:
        cmd(port, "bar", "LEARN SPELL")
        for _ in range(args.pick):
            cmd(port, "key", "Down")
        cmd(port, "key", "Return")
        picked = _peek(port, MENU_PICKED, 1)[0]
        print(f"the engine took id {picked}")
    cmd(port, "settle", 6)
    time.sleep(1.0)
    after = _peek(port, at, SLOT_SIZE)
    pathlib.Path(f"{args.out}-after-a.hex").write_text(after.hex())
    pathlib.Path(f"{args.out}-menu.txt").write_text(
        f"count {count}\nids {offered}\npicked {picked}\n")
    changed = [i for i in range(SLOT_SIZE) if before[i] != after[i]]
    print(f"{len(changed)} bytes moved: "
          + ", ".join(f"{i:#05x} {before[i]:02x}->{after[i]:02x}"
                      for i in changed))
    return 0


def drive(args) -> int:
    from tools.secret_of_the_silver_blades import ssbrun  # noqa: PLC0415

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
    rn.add_argument("--out", default=str(scratch.scratch_dir("ssbtrain", "run")))
    rn.set_defaults(func=drive)

    pr = sub.add_parser("press", help="drive one training press and dump it")
    pr.add_argument("--port", type=int,
                    default=int(os.environ.get("POR_CMD_PORT") or 6600),
                    help="the session's command port")
    pr.add_argument("--slot", type=int, required=True,
                    help="which roster slot, 0-7")
    pr.add_argument("--name", required=True, help="the row to press")
    pr.add_argument("--record", required=True,
                    help="a 256-byte slot, as hex, to write before pressing")
    pr.add_argument("--set", action="append", default=[],
                    metavar="lvl_cleric=10,xp=675001")
    pr.add_argument("--out", required=True, help="stem for the dumps")
    pr.add_argument("--enter", action="store_true",
                    help="press TRAIN CHARACTER first; without it the "
                         "session is already at TRAIN WHO")
    pr.add_argument("--pick", type=int, default=0,
                    help="how far down the spell menu to walk before Return")
    pr.set_defaults(func=press)

    df = sub.add_parser("diff", help="diff a before/after record pair")
    df.add_argument("--before", required=True)
    df.add_argument("--after", required=True)
    df.add_argument("--class", dest="classes", action="append", default=[],
                    help="the class raised; repeat in the engine's own "
                         "order. With none, the replay goes through plan_all")
    df.add_argument("--learn", type=int, default=None,
                    help="the spell id a magic-user picked at `$1896`")
    df.add_argument("--int", dest="int", type=int, default=None,
                    help="force the intelligence the trainer read, both "
                         "copies, when neither dump holds what was poked")
    df.add_argument("--wis", dest="wis", type=int, default=None,
                    help="force the wisdom the trainer read, both copies")
    df.set_defaults(func=compare)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
