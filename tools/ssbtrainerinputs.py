#!/usr/bin/env python3
"""The three trainer inputs Silver Blades' `goldbox/levels.py` entry still lacks.

`#89 (Silver Blades' trainer grants spells from a table, and goldbox/levelup.py
offers them from a menu)` cannot put Silver Blades into
`goldbox.levels.TRAINER_MEASURED` while `hp_bonus_by_score`, `thief_skills`/
`thief_skill_race` and `wisdom_bonus_level` are empty for that title. This reads
all three off the player's own disks, prints them, and checks each against the
same table in Curse's files and against a character the game itself wrote.

Nothing is transcribed into the repository: every number below comes off the
disk at run time, the way `goldbox.items.load_item_names` does it.

**Where they are.** `GEN` runs at `$0800` and the working record at `$7C00`;
`ECL65` runs at `$8000`, fixed by its own `LDX $89F0,Y` reading the wisdom row
that sits at payload offset `0x9F0`.

    constitution hit points   GEN   $0E6C reads, table at $0E80
    the ranger's extra one    GEN   $0E9A, uncapped
    thief skills              GEN   $1204 reads, level rows $126D,
                                    dexterity rows $131D, racial rows $12F5
    wisdom bonus spells       ECL65 $89E0 reads, table at $89F0

**The thief's racial row is read one row too far, and that is the game's.**
`GEN $124D` is `LDA race / BEQ / CMP #$06 / BCS / ASL / ASL / ASL`, with no
decrement, so the index is `race * 8` into a table whose first row is the elf's
-- while `$17B1` in the same overlay does `LDX race / DEX` for the racial class
limits, and both Pool of Radiance (`$2005 LDY race / DEY`) and Curse
(`$0FE6 LDX race / DEX`) decrement here too. So a Silver Blades elf gets the
half-elf's adjustments, a dwarf the gnome's, and a halfling runs off the end of
the racial table into the first row of the dexterity table. `--rows` prints what
each race code actually gets, which is what `thief_skill_race` has to hold if
Wish is to write the numbers the trainer writes.

    tools/ssbtrainerinputs.py               everything, with the checks
    tools/ssbtrainerinputs.py --rows        the tables alone, paste-ready
    tools/ssbtrainerinputs.py --check       exit non-zero if a check fails
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS.parent))

from goldbox import games, levels  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from goldbox.savegame import load_save  # noqa: E402
from tools import gamedisks  # noqa: E402
from tools.trainerscan import overlay  # noqa: E402

GEN_BASE = 0x0800
#: `ECL65`'s PRG header says `$4000` here and `$3000` in Curse, and neither
#: runs there: `$89F0` in `$89E0`'s own `LDX $89F0,Y` is payload `0x9F0`.
ECL65_BASE = 0x8000

#: Silver Blades' `GEN`, by the address the code uses.
CON_TABLE = 0x0E80          #: indexed by the raw constitution score, signed
CON_CAP = 16                #: `$0E73 CPX #$11 / BCC / LDX #$10`
CON_UNCAPPED_FROM = 3       #: `$0E6F CPY #$03 / BCS` -- the class slot
THIEF_LEVEL_ROWS = 0x126D   #: 17 rows of 8, `$1213 CPX #$11 / LDX #$11`
THIEF_RACE_ROWS = 0x12F5    #: 6 rows of 8, indexed `race * 8` -- see the header
THIEF_DEX_ROWS = 0x131D     #: 17 rows of 8, `$1230 SBC #$09`
THIEF_DEX_FROM = 9
ROLL_TO = 0x0E21            #: the level each class slot stops rolling dice at

#: Curse's own copies, for the sameness checks.
CURSE_CON_TABLE = 0x11D7
CURSE_THIEF_LEVEL_ROWS = 0x1004
CURSE_THIEF_RACE_ROWS = 0x1064
CURSE_THIEF_DEX_ROWS = 0x10A4
#: Pool of Radiance's, whose record is at `$6B00` and whose rows are nine.
POOL_THIEF_LEVEL_ROWS = 0x102E

#: `ECL65`, as payload offsets, the way `goldbox/levels.py` cites Curse's.
SSB_WISDOM_BONUS = 0x9F0
CURSE_WISDOM_BONUS = 0x906
WISDOM_BONUS_FROM = 13
WISDOM_BONUS_TO = 19        #: `LDX $89F0,Y` past 19 reads the next table

#: The opcodes each address above has to carry, so a different rip fails loudly
#: instead of printing another file's bytes under these names.
GEN_SIGNATURES = {
    #: LDX constitution / CPY #$03 / BCS / CPX #$11 / BCC / LDX #$10
    0x0E6C: bytes.fromhex("AE187CC003B006E0119002A210"),
    #: LDA dual_class_level / BEQ / LDX dual_class_slot / CPX #$07 / BEQ /
    #: LDA level_ranger / BEQ
    0x0E9A: bytes.fromhex("ADBA7CF007AEB97CE007F005ADD07CF00D"),
    #: LDX level_thief / BEQ / CPX #$11 / BCC / LDX #$11
    0x120E: bytes.fromhex("AECB7CF059E0119002A211"),
    #: LDA dexterity / SEC / SBC #$09 / BCS / LDA #$00 / ASL / ASL / ASL / TAX
    0x122D: bytes.fromhex("AD177C38E909B002A9000A0A0AAA"),
    #: LDA race / BEQ / CMP #$06 / BCS / ASL / ASL / ASL / TAX -- no decrement
    0x124D: bytes.fromhex("AD727CF01AC906B0160A0A0AAA"),
}
ECL65_SIGNATURE = (0x9E0, bytes.fromhex("ADCA7CF017AC167CC00D9010BEF089"))

SKILLS = ("pick pockets", "open locks", "find traps", "move silently",
          "hide in shadows", "hear noise", "climb walls", "read languages")


def _rows(data: bytes, base: int, address: int, count: int, *, signed=False):
    """`count` rows of eight, from an address in an overlay that runs at `base`."""
    at = address - base
    out = []
    for n in range(count):
        row = data[at + n * 8:at + n * 8 + 8]
        out.append(tuple(b - 256 if signed and b > 127 else b for b in row))
    return tuple(out)


def _at(data: bytes, base: int, address: int, n: int) -> bytes:
    return data[address - base:address - base + n]


def constitution(gen: bytes, curse_gen: bytes) -> dict:
    """`GEN $0E80`, indexed by the raw score and signed. 26 entries."""
    raw = _at(gen, GEN_BASE, CON_TABLE, 26)
    return {
        "table": tuple(b - 256 if b > 127 else b for b in raw),
        "raw": raw,
        "curse_raw": _at(curse_gen, GEN_BASE, CURSE_CON_TABLE, 26),
        "cap": CON_CAP,
        "uncapped_from": CON_UNCAPPED_FROM,
        "roll_to": tuple(_at(gen, GEN_BASE, ROLL_TO, 8)),
    }


def thief(gen: bytes, curse_gen: bytes, pool_gen: bytes) -> dict:
    """The three rows `$1204` adds together, and what each race code gets."""
    table = _rows(gen, GEN_BASE, THIEF_RACE_ROWS, 6, signed=True)
    # `$1256 ASL / ASL / ASL` with no decrement: race N reads row N.
    effective = {race: table[race] for race in range(1, 6)}
    return {
        "levels": _rows(gen, GEN_BASE, THIEF_LEVEL_ROWS, 17),
        "dexterity": _rows(gen, GEN_BASE, THIEF_DEX_ROWS, 17, signed=True),
        "race_table": table,
        "effective": effective,
        "curse_levels": _at(curse_gen, GEN_BASE, CURSE_THIEF_LEVEL_ROWS, 72),
        "curse_dexterity": _at(curse_gen, GEN_BASE, CURSE_THIEF_DEX_ROWS, 136),
        "curse_race": _rows(curse_gen, GEN_BASE, CURSE_THIEF_RACE_ROWS, 8,
                            signed=True),
        "pool_levels": _at(pool_gen, GEN_BASE, POOL_THIEF_LEVEL_ROWS, 72),
    }


def skill_row(tables: dict, level: int, race: int, dexterity: int):
    """What the game stores at `0x0A5`, by `$1204`'s own three additions."""
    level = max(1, min(level, len(tables["levels"])))
    row = list(tables["levels"][level - 1])
    at = max(0, min(dexterity - THIEF_DEX_FROM, len(tables["dexterity"]) - 1))
    for i, add in enumerate(tables["dexterity"][at]):
        row[i] += add
    if race in tables["effective"]:
        for i, add in enumerate(tables["effective"][race]):
            row[i] += add
    return tuple(v & 0xFF for v in row)


def wisdom(ecl65: bytes, curse_ecl65: bytes) -> dict:
    """`ECL65 $89F0`, indexed by the raw wisdom score: which spell level each
    point from 13 up buys a cleric."""
    span = slice(SSB_WISDOM_BONUS + WISDOM_BONUS_FROM,
                 SSB_WISDOM_BONUS + WISDOM_BONUS_TO + 1)
    curse = slice(CURSE_WISDOM_BONUS + WISDOM_BONUS_FROM,
                  CURSE_WISDOM_BONUS + WISDOM_BONUS_TO + 1)
    return {"table": tuple(ecl65[span]), "curse": tuple(curse_ecl65[curse])}


def bonus_spells(table: tuple[int, ...], score: int) -> tuple[int, ...]:
    """`$89E0`'s loop counted out: one spell a point from 13 up."""
    out = [0] * (max(table) + 1)
    for point in range(WISDOM_BONUS_FROM, min(score, WISDOM_BONUS_TO) + 1):
        out[table[point - WISDOM_BONUS_FROM]] += 1
    return tuple(out)


def hp_bonus(con: dict, class_slot: int, score: int) -> int:
    """`$0E6C`: capped below slot 3, then the signed row."""
    if class_slot < con["uncapped_from"] and score > con["cap"]:
        score = con["cap"]
    return con["table"][max(0, min(score, len(con["table"]) - 1))]


def predicted_hp_max(con: dict, record) -> int | None:
    """`$0DBA`'s loop, so `hp_max` can vote on the constitution table.

    `Σ min(level, roll_to) * bonus(slot)` over the eight class slots, one more
    bonus for a ranger (`$0E9A`), divided by how many classes the character
    holds (`$0D96`), plus the rolled hit points. The divide has no floor and
    rounds up at random, so this returns the rounded-down answer and the caller
    allows one more.
    """
    slots = list(record.slice(0x0C9, 8))
    if record.get("dual_class_level"):
        return None                       # `$0E29`'s deduction, not modelled
    total = sum(min(level, con["roll_to"][slot]) * hp_bonus(con, slot,
                                                            record.get("constitution"))
                for slot, level in enumerate(slots) if level)
    if slots[7]:
        total += hp_bonus(con, 7, record.get("constitution"))
    classes = sum(1 for level in slots if level)
    return record.get("hp_rolled") + total // max(1, classes)


def _party(path: pathlib.Path):
    game, sg0, _ = load_save(D64.open(str(path)))
    if game is not games.SECRET_OF_THE_SILVER_BLADES:
        raise SystemExit(f"ssbtrainerinputs.py: {path} is not a Silver Blades save")
    return [slot.record for slot in sg0.characters]


def shipped_party():
    """The party SSI ships, off whichever side carries a whole `SAVEDBASH`."""
    ssb = games.SECRET_OF_THE_SILVER_BLADES
    where = gamedisks.find(ssb.key)
    if where is None:
        return []
    for path in sorted(pathlib.Path(where).glob(ssb.disk_glob)):
        try:
            disk = D64.open(str(path))
            if ssb.matches_payload(disk.read_file(ssb.save_file)):
                return _party(path)
        except Exception:
            continue
    return []


def specimen_party(name="ssb-malachite-trained"):
    """An engine-written Silver Blades save from `$WISH_SPECIMENS`, if it is here."""
    root = pathlib.Path(os.environ.get(
        "WISH_SPECIMENS", pathlib.Path.home() / "wish-specimens"))
    for path in root.rglob(f"WISH-SPEC-{name}.[dD]64"):
        return _party(path)
    return []


def signatures(gen: bytes, ecl65: bytes) -> list[str]:
    """Anything whose opcodes are not what this file says they are."""
    bad = []
    for address, want in GEN_SIGNATURES.items():
        if _at(gen, GEN_BASE, address, len(want)) != want:
            bad.append(f"GEN ${address:04X} is not the routine this tool reads")
    offset, want = ECL65_SIGNATURE
    if ecl65[offset:offset + len(want)] != want:
        bad.append("ECL65 $89E0 is not the routine this tool reads")
    return bad


def report(check: bool = False, rows_only: bool = False) -> int:
    gen, curse_gen, pool_gen = (overlay("ssb", "GEN"), overlay("curse", "GEN"),
                                overlay("pool", "GEN"))
    ecl65, curse_ecl65 = overlay("ssb", "ECL65"), overlay("curse", "ECL65")
    failures = signatures(gen, ecl65)

    con = constitution(gen, curse_gen)
    th = thief(gen, curse_gen, pool_gen)
    wis = wisdom(ecl65, curse_ecl65)

    print("hp_bonus_by_score -- GEN $0E80, indexed by the raw constitution")
    print("   ", con["table"])
    print(f"    cap {con['cap']} below class slot {con['uncapped_from']} "
          f"($0E6F/$0E73); the ranger takes one more at $0E9A")
    same = con["raw"] == con["curse_raw"]
    print(f"    Curse's $11D7: {'byte for byte the same 26 bytes' if same else 'DIFFERENT'}")
    if not same:
        failures.append("the constitution row is not Curse's")
    if con["table"] != levels.CURSE_OF_THE_AZURE_BONDS.hp_bonus_by_score:
        failures.append("the constitution row is not goldbox/levels.py's Curse row")
    print(f"    roll_to by class slot, $0E21: {con['roll_to']}")

    print("\nwisdom_bonus_level -- ECL65 $89F0, wisdom 13 to 19")
    print("   ", wis["table"], f"from {WISDOM_BONUS_FROM}")
    same = wis["table"] == wis["curse"]
    print(f"    Curse's $8906: {'the same seven bytes' if same else 'DIFFERENT'}")
    if not same:
        failures.append("the wisdom row is not Curse's")
    if wis["table"] != levels.CURSE_OF_THE_AZURE_BONDS.wisdom_bonus_level:
        failures.append("the wisdom row is not goldbox/levels.py's Curse row")
    for score in (13, 16, 18):
        print(f"    wisdom {score}: {bonus_spells(wis['table'], score)}")

    print("\nthief_skills -- GEN $126D, 17 rows of eight, clamped at 17 ($1213)")
    for level, row in enumerate(th["levels"], start=1):
        print(f"    {level:2d}  " + " ".join(f"{v:3d}" for v in row))
    print(f"    rows 1-9 are Curse's $1004 and Pool of Radiance's $102E: "
          f"{th['levels'][:9] == _rows(th['curse_levels'], 0, 0, 9)}")
    print("\n  dexterity rows -- GEN $131D, from a dexterity of 9")
    for n, row in enumerate(th["dexterity"]):
        print(f"    {n + THIEF_DEX_FROM:2d}  " + " ".join(f"{v:4d}" for v in row))
    print(f"    Curse's $10A4: {'the same 136 bytes' if th['dexterity'] == _rows(th['curse_dexterity'], 0, 0, 17, signed=True) else 'DIFFERENT'}")

    print("\n  racial rows -- GEN $12F5, read at race * 8 with no decrement")
    order = dict(games.RACES_SILVER_BLADES)
    for n, row in enumerate(th["race_table"]):
        label = ("the dexterity table's first row" if n == 5
                 else f"laid out for {order.get(n + 1, '?')}")
        print(f"    row {n}  " + " ".join(f"{v:4d}" for v in row) + f"   {label}")
    print("  what each race code actually gets, which is the effective table:")
    for race, name in games.RACES_SILVER_BLADES:
        row = th["effective"].get(race)
        print(f"    {race} {name:10s} " +
              (" ".join(f"{v:4d}" for v in row) if row else "no adjustment"))

    if rows_only:
        return 0

    print("\ncorroboration")
    for label, party in (("shipped", shipped_party()),
                         ("engine-written after five trainings",
                          specimen_party())):
        if not party:
            print(f"  {label}: no party here")
            continue
        for rec in party:
            want = predicted_hp_max(con, rec)
            got = rec.get("hp_max")
            if want is not None:
                ok = got in (want, want + 1)
                print(f"  {label} {rec.name:14s} hp_max {got:3d} "
                      f"predicted {want:3d}{'' if ok else '   MISMATCH'}")
                if not ok:
                    failures.append(f"{rec.name}'s hp_max is not the "
                                    f"constitution table's answer")
            if not rec.slice(0x0CB, 1)[0]:
                continue
            stored = tuple(rec.get(f"thief_{n.replace(' ', '_')}") for n in SKILLS)
            want = skill_row(th, rec.slice(0x0CB, 1)[0], rec.get("race"),
                             rec.get("dexterity"))
            ok = stored == want
            print(f"  {label} {rec.name:14s} thief skills {stored}")
            print(f"  {' ' * len(label)} {' ' * 14} predicted    {want}"
                  f"{'' if ok else '   MISMATCH'}")
            if not ok:
                failures.append(f"{rec.name}'s thief skills are not the "
                                f"three rows added")

    if failures:
        print("\nFAILED:")
        for line in failures:
            print(f"  {line}")
    return 1 if (failures and check) else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if a reading or a check fails")
    ap.add_argument("--rows", action="store_true",
                    help="the tables alone, without the corroboration")
    args = ap.parse_args(argv)
    return report(check=args.check, rows_only=args.rows)


if __name__ == "__main__":
    raise SystemExit(main())
