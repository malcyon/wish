"""Where infravision comes from on each port, and what a conversion does with it.

`#52 (File ▸ Import and File ▸ Export for every direction the library
supports)` reported `infravision` as dropped on all three C64 → DOS rows, on
the argument that the destination recomputes it.  These are the assertions
behind the measurement that settled it:

* the **C64 writes it once, from race**, out of a table in the game's own
  character generator -- so the byte carries nothing the `race` byte does not;
* the **DOS record has no such byte**, across eight characters of six races
  rolled in the DOS game's own creation screens;
* and the **DOS engine puts nothing race-shaped back** when it loads a
  converted party, measured on its own resave of one.

Everything here reads the player's own disks or the specimen tree and skips
when neither is on the machine.  `tools/infravision.py` is the tool.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import c64_codec, dos, dos_layout  # noqa: E402
from tests import gamedata  # noqa: E402
from tools import infravision  # noqa: E402

#: The eight characters `#84 (Roll a gnome in DOS and read the two innate
#: effect ids nobody has seen)` rolled in DOS Pool of Radiance's own creation
#: screens: one dwarf, one elf, three gnomes, one half-elf, one halfling and
#: one human.
ROLLED = ("dwarfc4", "elf6", "gnomf1", "gnomft3", "gnomt2", "halfe8",
          "halfl5", "human7")

#: What the C64 generator's table holds for races 1 to 7 -- dwarf, elf, gnome,
#: half-elf, halfling, half-orc, human -- in tens of feet.  The halfling's 3
#: is the one that is not 6.
GENERATOR_TABLE = (6, 6, 6, 6, 3, 6, 0)


def _rolled_records():
    out = {}
    for name in ROLLED:
        where = gamedata.specimen(name, "dos")
        cha = sorted(where.glob("*.CHA"))
        assert cha, f"WISH-SPEC-{name} has no .CHA"
        out[name] = dos.read_character(cha[0])
    return out


def _race_split(records):
    """Offsets where every human agrees, every demi-human agrees, and the two
    groups differ.  An infravision byte would be exactly one of these."""
    humans = [r.to_bytes() for r in records
              if dos_layout.RACE_NUMBERS[r.get("race")] == "human"]
    demis = [r.to_bytes() for r in records
             if dos_layout.RACE_NUMBERS[r.get("race")] != "human"]
    assert humans and demis
    out = []
    for offset in range(len(humans[0])):
        h = {b[offset] for b in humans}
        d = {b[offset] for b in demis}
        if len(h) == 1 and len(d) == 1 and h != d:
            out.append(offset)
    return out


def _field_at(offset: int) -> str:
    for f in dos_layout.LAYOUT:
        if f.offset <= offset < f.offset + f.size:
            return f.name
    return "?"


# --- the C64: a table in the game's own character generator -----------------

@pytest.mark.parametrize("title", sorted(infravision.GENERATORS))
def test_the_c64_generator_writes_infravision_from_a_race_table(title):
    """Pool of Radiance and Curse of the Azure Bonds ship the same seven
    numbers, and the halfling's is 3 rather than 6."""
    try:
        table = infravision.race_table(title)
    except SystemExit as e:
        pytest.skip(str(e))
    assert tuple(table) == GENERATOR_TABLE


def test_the_generator_reads_that_table_with_the_race_byte_as_its_index():
    """The four instructions that make it a derivation rather than a
    coincidence: `LDY #$D5` picks the record offset, the race code goes into
    X, the table is indexed by it, and the result is stored into the record.
    Read off `POOL3.D64:GEN`, disassembled at the `$0800` every overlay runs
    at."""
    try:
        table = infravision.race_table("pool-of-radiance")
    except SystemExit as e:
        pytest.skip(str(e))
    assert tuple(table) == GENERATOR_TABLE
    from goldbox.d64 import D64, split_load_address
    from tools import d6502, gamedisks
    disks = gamedisks.find("pool-of-radiance")
    if disks is None:
        pytest.skip("no Pool of Radiance disks")
    _, gen = split_load_address(
        D64.open(pathlib.Path(disks) / "POOL3.D64").read_file("GEN"))
    printed = [line.split("  ", 2)[-1].strip()
               for line in d6502.lines(gen, 0x0800, 0x094F, 4)]
    assert printed == ["LDY #$D5", "TAX", "LDA $0E5C,X", "STA $6B00,Y"]


def test_the_c64_writer_gives_every_race_the_number_the_generator_writes():
    """`goldbox.c64_codec` computes the byte for a converted character, and
    the numbers it computes have to be the game's own.

    The halfling is the one disagreement: the writer's table says 6 where
    two titles' generators write 3, which is `#392 (A converted halfling gets
    sixty feet of infravision, where the C64's own generator gives him
    thirty)`.  This asserts that it is the *only* one, so the row moving
    fails here rather than in a conversion.
    """
    try:
        table = infravision.race_table("pool-of-radiance")
    except SystemExit as e:
        pytest.skip(str(e))
    from goldbox import games
    names = games.race_table(games.POOL_OF_RADIANCE)
    wrong = {names[code]: (c64_codec.INFRAVISION[names[code]], table[code - 1])
             for code in range(1, 8)
             if code in names
             and c64_codec.INFRAVISION.get(names[code]) != table[code - 1]}
    assert wrong == {"halfling": (6, 3)}, (
        "the writer's table has moved away from the generator's in a way "
        "#392 does not describe: " + repr(wrong))


# --- DOS: no such byte ------------------------------------------------------

def test_no_dos_record_byte_separates_a_human_from_the_demi_humans():
    """Eight characters of six races, every one rolled in the DOS game's own
    creation screens.  A stored infravision byte would read 0 for the human
    and 6 (or 3) for all seven others; no offset in the 285 does."""
    records = list(_rolled_records().values())
    assert len(records) == 8
    split = _race_split(records)
    assert split == [], [f"0x{o:03X} {_field_at(o)}" for o in split]


def test_every_unattributed_dos_byte_is_zero_in_all_eight():
    """The other half of the same claim: the byte cannot be hiding in a gap,
    because no gap holds anything at all."""
    records = _rolled_records()
    unattributed = [f for f in dos_layout.LAYOUT
                    if f.name.startswith("gap_") or f.name == "field_83_87"]
    assert unattributed, "the DOS layout has no gaps left to check"
    for name, record in records.items():
        raw = record.to_bytes()
        for f in unattributed:
            assert set(raw[f.offset:f.offset + f.size]) == {0}, (
                f"{name}: {f.name} at 0x{f.offset:03X} is not zero")


def test_the_dos_engines_own_resave_puts_back_nothing_race_shaped():
    """A converted party -- two humans, an elf, a half-elf, a halfling and a
    dwarf -- loaded in DOS Pool of Radiance, walked, and written back by the
    game's own ENCAMP ▸ SAVE.  One offset splits the humans from the
    demi-humans in what the engine wrote, and it is the pointer to the
    effect list, which is where DOS keeps a race's innate abilities."""
    where = gamedata.specimen("por-52-dialog-converted-resave", "dos")
    party = dos.read_party(where, "D")
    assert len(party) == 6
    split = _race_split(party)
    assert [_field_at(o) for o in split] == ["effect_chain"], (
        [f"0x{o:03X} {_field_at(o)}" for o in split])


def test_no_dos_effect_id_a_race_is_born_with_means_infravision():
    """The other place a racial ability can live on DOS is an innate effect
    record, and the ids the engine writes for a race are named."""
    from goldbox import traits
    born_with = set()
    for ids in dos.RACE_COMBAT_EFFECTS.values():
        born_with |= set(ids)
    for ids in dos.RACE_COMBAT_EFFECTS_SILVER_BLADES.values():
        born_with |= set(ids)
    assert born_with, "no racial effect ids are declared"
    for code in sorted(born_with):
        name = traits.NAMES[code][0]
        assert "infra" not in name.lower(), f"{code} is {name}"


# --- the accounting ---------------------------------------------------------

def test_the_writers_accounting_still_calls_infravision_a_drop():
    """Silence is a line in front of a person, not a change to the books:
    `write_field_disposition` still says `dropped` for it."""
    said = dos.write_field_disposition()
    assert said["infravision"].startswith("dropped:")


def test_a_c64_party_converted_to_dos_is_not_told_about_infravision():
    assert "infravision" in dos.WRITE_UNREPORTED_DROPS
