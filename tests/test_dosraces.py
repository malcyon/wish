"""The DOS race tables: read out of the games, checked against AD&D (#237).

`goldbox/dos_layout.py` carried one race table for all four DOS titles until
#237.  It was right for Pool of Radiance and Curse and wrong for the two later
games, which reorder the table and drop the half-orc, and the way that showed
was a party of half-orc paladins.

Two kinds of test here, and they are deliberately different in kind.

* **The legality test** asserts a rule of AD&D rather than a table: every
  shipped record decodes to a race its class is allowed to be.  It knows
  nothing about where the numbering came from, so it cannot be made to agree
  with the code by construction, and
  `test_the_single_table_is_what_the_legality_test_catches` shows it failing
  against the pre-#237 numbering on the same records.
* **The reader tests** check that `tools/dosraces.py` finds each title's own
  race-name table in the executable the game runs, and that what it reads is
  what `DosShape.race_numbers` says.  Run against Pool of Radiance and Curse
  the reader reproduces `RACE_NUMBERS`, a table established here independently
  from 24 specimens and from the C64 -- which is what makes the same reading
  of the other two a measurement rather than a guess.

**The archives are the player's**, so everything that reads one skips without
them.  The synthetic tests of the reader itself run everywhere, which is what
CI covers.
"""
from __future__ import annotations

import functools
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from goldbox import dos_layout  # noqa: E402
from tools import dosraces  # noqa: E402

#: What AD&D lets each race be, as the Gold Box character creation screen
#: enforces it.  This is the *rules*, not a restatement of anything in
#: `goldbox/`: a paladin is human, a dwarf never casts a magic-user spell, and
#: only an elf or a half-elf takes all three of fighter, magic-user and thief.
#: Humans are the only race with no multi-class, which is why their set is the
#: eight single classes and nothing else.
ALLOWED: dict[str, frozenset[str]] = {
    "dwarf": frozenset({
        "cleric", "fighter", "thief",
        "cleric/fighter", "cleric/thief", "fighter/thief"}),
    "elf": frozenset({
        "cleric", "fighter", "mage", "thief",
        "cleric/fighter", "cleric/mage", "cleric/thief",
        "cleric/fighter/mage", "fighter/mage", "fighter/thief",
        "mage/thief", "fighter/mage/thief"}),
    "gnome": frozenset({
        "cleric", "fighter", "thief",
        "cleric/fighter", "cleric/thief", "fighter/thief"}),
    "half-elf": frozenset({
        "cleric", "druid", "fighter", "mage", "ranger", "thief",
        "cleric/fighter", "cleric/mage", "cleric/ranger", "cleric/thief",
        "cleric/fighter/mage", "fighter/mage", "fighter/thief",
        "mage/thief", "fighter/mage/thief"}),
    "halfling": frozenset({
        "cleric", "fighter", "thief",
        "cleric/fighter", "cleric/thief", "fighter/thief"}),
    "half-orc": frozenset({
        "cleric", "fighter", "thief",
        "cleric/fighter", "cleric/thief", "fighter/thief"}),
    "human": frozenset({
        "cleric", "druid", "fighter", "paladin", "ranger", "mage", "thief",
        "monk"}),
}

#: Not player races: the record can hold them and no rule constrains them.
#: `tribble` is Silver Blades' entry 0, and it is what the executable says.
NOT_A_PLAYER_RACE = frozenset({"monster", "tribble"})


# --------------------------------------------------------------------------
# Finding the player's files
# --------------------------------------------------------------------------


def _candidates():
    """`gamedisks.toml`'s own search list for the DOS archives (#212)."""
    from tools import gamedisks
    return gamedisks.candidates("dos-archives")


@functools.lru_cache(maxsize=1)
def _records() -> tuple[tuple[str, str, str, int, int], ...]:
    """Every shipped character record in the archives.

    `(path, shape key, name, race byte, class byte)` per file.  The record
    size names the shape, which is `shape_for`'s own claim; a file of any
    other length is not a record and is skipped.
    """
    out: dict[str, tuple[str, str, str, int, int]] = {}
    for root in _candidates():
        if not root.is_dir():
            continue
        try:
            paths = sorted(root.rglob("*"))
        except OSError:
            continue
        for path in paths:
            if not path.is_file() or path.suffix.upper() not in (
                    ".SAV", ".CHA", ".GUY"):
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size not in dos_layout.SHAPES_BY_SIZE:
                continue
            shape = dos_layout.SHAPES_BY_SIZE[size]
            fields = {f.name: f for f in dos_layout.LAYOUTS[shape.key]}
            blob = path.read_bytes()
            name = blob[1:1 + blob[0]].decode("latin-1").strip()
            out[str(path)] = (str(path), shape.key, name,
                              blob[fields["race"].offset],
                              blob[fields["char_class"].offset])
    return tuple(out.values())


def _need_records():
    records = _records()
    if not records:
        pytest.skip("needs the DOS archives; set FR_ARCHIVES")
    return records


@functools.lru_cache(maxsize=1)
def _tables():
    return dosraces.tables()


def _need_tables():
    found = _tables()
    if not found:
        pytest.skip("needs the DOS game files; set FR_ARCHIVES")
    return found


def _violations(records, table_for) -> list[str]:
    """Every record whose class its race may not take, as readable lines."""
    bad = []
    for path, key, name, race, char_class in records:
        races = table_for(key)
        if race >= len(races) or char_class >= len(dos_layout.CLASS_NUMBERS):
            bad.append(f"{key} {name}: race {race} class {char_class} "
                       f"out of range")
            continue
        race_name = races[race]
        class_name = dos_layout.CLASS_NUMBERS[char_class]
        if race_name in NOT_A_PLAYER_RACE or class_name == "monster":
            continue
        if class_name not in ALLOWED[race_name]:
            bad.append(f"{key} {name}: a {race_name} {class_name} "
                       f"(race {race}, class {char_class})")
    return bad


# --------------------------------------------------------------------------
# The rule, asserted against the records
# --------------------------------------------------------------------------


def test_every_shipped_record_is_a_race_its_class_may_be():
    """The assertion #237 asked for, and it is about AD&D rather than about
    the table it checks.

    A half-orc paladin and a halfling magic-user are what the single table
    produced; neither can be created in any of these games.
    """
    records = _need_records()
    bad = _violations(records, lambda key: dos_layout.shape_for(key).race_numbers)
    assert not bad, f"{len(bad)} of {len(records)} records:\n" + "\n".join(bad)
    assert len(records) >= 100, f"only {len(records)} records found"


def test_the_single_table_is_what_the_legality_test_catches():
    """The test above failing without the fix, kept as a test.

    Reading every record through the pre-#237 numbering -- one table for all
    four titles -- puts halfling paladins and dwarf magic-users in the later
    two games.  Without this, a legality test that passed would not tell you
    whether it was capable of failing.
    """
    records = _need_records()
    bad = _violations(records, lambda key: dos_layout.RACE_NUMBERS)
    assert len(bad) >= 20, f"expected the old table to be caught, got {bad}"
    assert all("pool-of-radiance" not in line
               and "curse-of-the-azure-bonds" not in line for line in bad), (
        "the old table is still right for the first two titles:\n"
        + "\n".join(bad))


def test_the_two_later_titles_are_the_only_ones_that_moved():
    """Pool of Radiance and Curse keep today's tuple, which is the part of
    #237 that had to not change meaning."""
    assert dos_layout.POOL_OF_RADIANCE.race_numbers is dos_layout.RACE_NUMBERS
    assert (dos_layout.CURSE_OF_THE_AZURE_BONDS.race_numbers
            is dos_layout.RACE_NUMBERS)
    assert (dos_layout.SECRET_OF_THE_SILVER_BLADES.race_numbers
            != dos_layout.RACE_NUMBERS)
    assert dos_layout.POOLS_OF_DARKNESS.race_numbers != dos_layout.RACE_NUMBERS


def test_the_race_byte_never_runs_off_the_end_of_its_title_table():
    """Silver Blades has eight races and Pools of Darkness seven, so a
    too-short table would raise on a real record rather than mis-name one."""
    for path, key, name, race, _ in _need_records():
        races = dos_layout.shape_for(key).race_numbers
        assert race < len(races), f"{name} in {path}: race {race}"


# --------------------------------------------------------------------------
# The reader, against the games
# --------------------------------------------------------------------------


def test_the_reader_finds_the_table_pool_of_radiance_already_knew():
    """The validation that makes the other two readings a measurement.

    `RACE_NUMBERS` was established from 24 specimens and from the C64, before
    anybody looked in the executable.  The reader reproducing it entry for
    entry in both of the titles that use it is what says the construct is an
    index-ordered enumeration.
    """
    found = _need_tables()
    for key in ("pool-of-radiance", "curse-of-the-azure-bonds"):
        if key not in found:
            continue
        _, _, _, names = found[key]
        assert tuple(n.lower() for n in names) == dos_layout.RACE_NUMBERS, key


def test_each_titles_table_is_what_dos_layout_says_it_is():
    """`tools/dosraces.py --check`, as an assertion."""
    found = _need_tables()
    assert len(found) >= 2, f"only {sorted(found)} found"
    for key, (path, offset, stride, names) in found.items():
        shape = dos_layout.shape_for(key)
        assert tuple(n.lower() for n in names) == tuple(shape.race_numbers), (
            f"{shape.title}: {path} at 0x{offset:06x} stride {stride} reads "
            f"{names}")


def test_silver_blades_is_eight_entries_and_pools_of_darkness_seven():
    """The entry counts are the finding, not a detail: the table shortening
    is what shifts every race below it."""
    found = _need_tables()
    for key, count in (("secret-of-the-silver-blades", 8),
                       ("pools-of-darkness", 7)):
        if key not in found:
            continue
        assert len(found[key][3]) == count, found[key][3]


def test_no_later_title_still_has_a_half_orc():
    """AD&D 2nd Edition dropped the half-orc as a player race, and so did
    these two games -- which is why the numbering below it moves."""
    found = _need_tables()
    for key in ("secret-of-the-silver-blades", "pools-of-darkness"):
        if key not in found:
            continue
        assert "half-orc" not in tuple(n.lower() for n in found[key][3])


# --------------------------------------------------------------------------
# The reader itself, on tables built here
# --------------------------------------------------------------------------


def _synthetic(names, stride, before=b"", pad_after=0) -> bytes:
    """A race table in the games' own shape, for testing the reader alone."""
    out = bytearray(before)
    for name in names:
        slot = bytes([len(name)]) + name.encode("ascii")
        out += slot.ljust(stride, b"\0")
    out += b"\0" * pad_after
    out += dosraces.ANCHOR + b"\0" * 4
    return bytes(out)


def test_a_table_at_stride_nine_is_read_back():
    names = ("Tribble", "Elf", "Half-Elf", "Dwarf", "Gnome")
    blob = _synthetic(names, 9, before=b"\x0cIllegal type\x0d\x00")
    offset, stride, read = dosraces.read_table(blob)
    assert (stride, read) == (9, names)
    assert blob[offset] == len("Tribble")


def test_a_table_padded_before_the_alignment_table_is_still_read():
    """Treasures of the Savage Frontier puts an extra byte between the two
    tables, and anchoring hard on the alignment table read nothing there."""
    names = ("Elf", "Half-Elf", "Dwarf", "Gnome", "Halfling")
    blob = _synthetic(names, 9, before=b"\x0cIllegal type\x0d\x00", pad_after=1)
    _, stride, read = dosraces.read_table(blob)
    assert (stride, read) == (9, names)


def test_the_walk_stops_at_the_class_table_rather_than_eating_it():
    """The class names are longer than a race slot and padded differently, so
    the run has to end there -- otherwise entry 0 is a class name and every
    index is wrong."""
    names = ("Elf", "Half-Elf", "Dwarf", "Gnome", "Halfling")
    before = b"\x19Cleric/Fighter/Magic-User\x00\x10Magic-User/Thief\x2c\x00"
    _, _, read = dosraces.read_table(_synthetic(names, 9, before=before))
    assert read == names


def test_a_file_with_no_alignment_table_is_refused():
    with pytest.raises(LookupError):
        dosraces.read_table(b"\x03Elf\0\0\0\0\0\0" * 8)


def test_a_run_too_short_to_be_a_race_table_is_refused():
    """Handing back three entries would read as a title with three races,
    and every record in it would decode to something."""
    with pytest.raises(LookupError):
        dosraces.read_table(_synthetic(("Elf", "Dwarf", "Gnome"), 9))


def test_two_alignment_tables_are_refused_rather_than_guessed_between():
    blob = _synthetic(("Elf", "Half-Elf", "Dwarf", "Gnome", "Halfling"), 9)
    with pytest.raises(LookupError):
        dosraces.read_table(blob + blob)
