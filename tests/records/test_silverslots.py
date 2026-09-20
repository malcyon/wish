from __future__ import annotations

"""Secret of the Silver Blades' spell-slot rows in `goldbox.spells._SLOTS`.

A C64 Silver Blades caster reaches the DOS and Amiga writers holding all-zero
slot arrays, because the C64 engine never stores them, so the writer recomputes
them from `goldbox.spells.capacity_by_class` -- and before this title had rows
there, that was an empty table and zeros went out with no warning.

The rows are read back off the player's own `ECL65` at run time and skip
without the disks.  No game bytes are committed.
"""

import pytest

from goldbox import amiga_later, dos_codec, neutral, spells
from tools.dos import dosbox, dosspellslots
from tools.records import laterlegality

SSB = "secret-of-the-silver-blades"


def _c64_caster(levels: dict, wisdom: int) -> neutral.NeutralCharacter:
    """What `goldbox.c64_codec`'s reader hands back for a Silver Blades
    caster: the levels, and three all-zero tuples for the slot arrays the C64
    never writes."""
    char = neutral.NeutralCharacter("C64", game=SSB)
    char.set("levels", levels, "test fixture")
    char.set("wisdom", wisdom, "test fixture")
    char.set("spells_castable",
             {"cleric": (0, 0, 0), "magic-user": (0, 0, 0)},
             "test fixture: all zeros, this title's C64 never stores them")
    return char


def _dos(char) -> dos_codec.DosCharacter:
    rec, _, _, _ = dos_codec.write(char)
    return dos_codec.DosCharacter(rec, deltas=SSB)


def test_silver_blades_has_a_slot_table_per_class():
    table = spells._SLOTS[SSB]
    assert set(table) == {"magic-user", "cleric", "paladin", "ranger"}
    assert spells.capacity_by_class({"magic-user": 15}, 10, SSB) != {}


def test_the_ceiling_rows_are_the_published_ad_and_d_numbers():
    """Magic-user 15 and cleric 15, before any wisdom bonus."""
    assert spells.capacity_by_class({"magic-user": 15}, 10, SSB) == {
        "magic-user": (5, 5, 5, 5, 5, 2, 1)}
    assert spells.capacity_by_class({"cleric": 15}, 10, SSB) == {
        "cleric": (7, 7, 7, 5, 4, 2, 0)}


def test_a_paladin_adds_to_the_cleric_array_without_a_wisdom_bonus():
    got = spells.capacity_by_class({"paladin": 15}, 18, SSB)
    assert got == {"cleric": (3, 2, 1, 1, 0, 0, 0)}
    assert spells.capacity_by_class({"paladin": 8}, 18, SSB) == {
        "cleric": (0,) * 7}


def test_a_ranger_fills_the_druid_and_magic_user_arrays_from_8_and_9():
    assert spells.capacity_by_class({"ranger": 8}, 18, SSB) == {
        "druid": (1, 0, 0, 0, 0, 0, 0), "magic-user": (0,) * 7}
    assert spells.capacity_by_class({"ranger": 15}, 18, SSB) == {
        "druid": (2, 2, 0, 0, 0, 0, 0), "magic-user": (2, 2, 0, 0, 0, 0, 0)}


def test_a_converted_c64_cleric_15_keeps_its_slots_on_dos():
    dos = _dos(_c64_caster({"cleric": 15}, 18))
    assert any(dos.raw("spells_castable_cleric"))
    assert tuple(dos.raw("spells_castable_cleric")) == (
        spells.capacity_by_class({"cleric": 15}, 18, SSB, port="C64")[
            "cleric"])
    assert not any(dos.raw("spells_castable_magic_user"))


def test_a_converted_c64_magic_user_15_keeps_its_slots_on_dos():
    dos = _dos(_c64_caster({"magic-user": 15}, 10))
    assert tuple(dos.raw("spells_castable_magic_user")) == (
        5, 5, 5, 5, 5, 2, 1)


def test_a_converted_c64_caster_keeps_its_slots_on_the_amiga():
    """The Amiga engine never rebuilds the block, so zeros written here stay
    zero for the life of the save."""
    amiga, _ = amiga_later.write_later(_c64_caster({"magic-user": 15}, 10),
                                       SSB)
    assert amiga.spell_slots["magic-user"] == (5, 5, 5, 5, 5, 2, 1)
    assert not any(amiga.spell_slots["cleric"])


def test_the_rows_are_the_games_own():
    """Every row, every level, against the player's `ECL65`."""
    try:
        read = laterlegality.silver_slot_rows()
    except SystemExit as exc:
        pytest.skip(f"needs the Silver Blades C64 disks: {exc}")
    table = spells._SLOTS[SSB]

    def padded(run):
        return tuple(run) + (0,) * (7 - len(run))

    for level in range(1, 16):
        assert table["magic-user"][level - 1] == padded(
            read[("magic-user", 0)][level]), ("magic-user", level)
        assert table["cleric"][level - 1] == padded(
            read[("cleric", 7)][level]), ("cleric", level)
        held_paladin = read[("paladin", 7)].get(level, ())
        assert table["paladin"][level - 1] == padded(held_paladin), (
            "paladin", level)
        druid, magic_user = table["ranger"][level - 1]
        assert druid == padded(read[("ranger", 14)].get(level, ())), (
            "ranger druid", level)
        assert magic_user == padded(read[("ranger", 0)].get(level, ())), (
            "ranger magic-user", level)


def test_the_dos_builder_has_the_same_rows_as_the_c64_builder():
    """All 52 progression rows, from the player's own `GAME.OVR` and `ECL65`."""
    try:
        game = dosbox.find_game("SECRET")
    except FileNotFoundError as exc:
        pytest.skip(f"needs the Silver Blades DOS disks: {exc}")
    try:
        c64 = laterlegality.silver_slot_rows()
    except SystemExit as exc:
        pytest.skip(f"needs the Silver Blades C64 disks: {exc}")

    ovr = (game / "GAME.OVR").read_bytes()
    image = dosspellslots.image_of(game, None)
    block, width = dosspellslots.block_of(439)
    arrays = dosspellslots.slot_arrays(439)
    assert (block, width, arrays) == (
        0x132, 7, ("cleric", "druid", "unattributed", "magic-user"))
    site = dosspellslots.builder_site(ovr, block)
    classes = dosspellslots.builder_classes(ovr, site)
    assert {(cls.number, cls.from_level) for cls in classes} == {
        (0, 2), (3, 9), (4, 8), (5, 2)}
    dos = dosspellslots.slot_tables(
        ovr, image, block, width, {0: 15, 3: 15, 4: 15, 5: 15}, arrays)

    passes = (
        (5, "magic-user", ("magic-user", 0)),
        (0, "cleric", ("cleric", 7)),
        (3, "cleric", ("paladin", 7)),
        (4, "magic-user", ("ranger", 0)),
        (4, "druid", ("ranger", 14)),
    )
    compared = 0
    for number, array, c64_key in passes:
        for level, row in c64[c64_key].items():
            expected = tuple(row) + (0,) * (width - len(row))
            assert dos[number][array][level - 1] == expected, (
                c64_key, level)
            compared += 1
    assert compared == 52
