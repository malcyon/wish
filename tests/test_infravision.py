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
import stat
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import c64_codec, dos, dos_layout, games, savegame  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
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

    `#392 (A converted halfling gets sixty feet of infravision, where the
    C64's own generator gives him thirty)` found the halfling wrong -- the
    writer's table said 6 where two titles' generators write 3 -- and this
    asserted that disagreement while it stood.  Fixed, every race the two
    tables share now agrees, and this fails the moment any row moves again.
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
    assert wrong == {}, (
        "the writer's table disagrees with the generator's: " + repr(wrong))


def test_a_converted_halfling_gets_the_generators_thirty_feet():
    """`#392`: a halfling's stored `0x0D5` after conversion has to be the
    game's own 3 (30 feet), not the AD&D-inferred 6 (60 feet) the table used
    to carry."""
    assert c64_codec.INFRAVISION["halfling"] == 3


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

def test_the_writers_accounting_calls_infravision_derived_not_dropped():
    """`write_field_disposition` still names the field -- it is not a loss
    that dropped off the books, it is one the destination derives -- and
    since #483 (The Convert flag could come off while two fields are still
    lost, because a silencing list keeps them out of the count that decides
    it) it says so honestly: `derived:` rather than a `dropped:` line a
    now-deleted silencing list kept out of the report."""
    said = dos.write_field_disposition()
    assert said["infravision"].startswith("derived:")


def test_a_c64_party_converted_to_dos_is_not_told_about_infravision():
    """The C64's own byte is a pure function of race (this module's own
    measurement), so a real conversion never puts a line about it in front of
    anybody -- achieved since #483 by `write` consuming the field with `use`
    rather than by a separate list built to keep it off the count."""
    from test_neutral import _filled

    char = _filled()
    char.set("infravision", 6, "made up: a C64 source's own byte")
    _, _, _, rep = dos.write(char)
    assert not [d for d in rep.dropped if "infravision" in d]


# -- stage: the copy must stay writable, whatever --source arrived as (#495) -

def _synthetic_save_disk(path: pathlib.Path) -> pathlib.Path:
    """A `D64` carrying an empty Pool of Radiance save -- no game bytes, just
    the format `goldbox.savegame` and `goldbox.games` already describe."""
    game = games.POOL_OF_RADIANCE
    disk = D64.blank()
    sg0 = savegame.SaveGame0.from_bytes(bytes(game.save_size), game)
    sg1 = savegame.SaveGame1(bytes(game.roster_size), game)
    disk.write_file(game.save_file, sg0.to_prg())
    disk.write_file(game.roster_file, sg1.to_prg())
    disk.save(str(path))
    return path


def test_stage_gives_the_copy_the_write_bit_back(tmp_path):
    """`--source` is often a read-only specimen; `shutil.copy` would carry
    that mode onto `--out`, and this must not (#495).

    Skips with no message read from a disk if Pool of Radiance's own disks
    are not on this machine -- `stage` reads the generator's race table off
    them, the same way `test_the_c64_generator_writes_infravision_from_a_race_
    table` above does, and CI carries none (`AGENTS.md` forbids the game's
    data entering this repository, so no fixture can stand in)."""
    source = _synthetic_save_disk(tmp_path / "base.d64")
    source.chmod(0o444)
    out = tmp_path / "staged.d64"

    try:
        infravision.stage(source, out)
    except SystemExit as e:
        pytest.skip(str(e))

    assert out.stat().st_mode & stat.S_IWUSR


def test_staging_over_a_read_only_leftover_does_not_raise(tmp_path):
    """The loud half of the bug, and it is narrower than "run it twice":
    `D64.save` replaces `--out` with `os.replace`, which needs no write
    permission on the file it is replacing, so a run that completes leaves
    `--out` writable regardless of how it got there.  What still carries a
    read-only leftover forward is `shutil.copy` finding one already sitting
    at `--out` -- a specimen copied there by hand, or an earlier run that
    died between its own copy and its own `image.save` -- and dying opening
    it for writing.

    Skips with no Pool of Radiance disks on this machine, for the same reason
    `test_stage_gives_the_copy_the_write_bit_back` above does."""
    import shutil

    source = _synthetic_save_disk(tmp_path / "base.d64")
    source.chmod(0o444)
    out = tmp_path / "staged.d64"
    shutil.copy(source, out)  # a read-only leftover, however it got there

    try:
        infravision.stage(source, out)  # must not raise
    except SystemExit as e:
        pytest.skip(str(e))
