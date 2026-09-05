"""The former class of a dual-classed character, named and read (#256, #234).

`goldbox/dos_layout.py`'s three later shapes have always had the level array
`former_class_levels`, and the byte right after `level` that repeats the same
number -- both write once, by the same routine, in Curse of the Azure Bonds,
Secret of the Silver Blades and Pools of Darkness.  Until now the second byte
was an anonymous gap and the DOS and Amiga readers set every slot of the array,
including the zeros `goldbox/neutral.py`'s `former_levels` convention says to
leave out.  This file is the regression test for naming the byte
`former_level` and fixing both readers.

Synthetic records come from `goldbox/dos_layout.py`'s own table, exactly as
`tests/test_curseconvert.py`'s `curse_record` does, so they run everywhere with
no game data in them.  Two pairs are specimen-backed: `WISH-SPEC-curse-234-*`
and `WISH-SPEC-ssb-234-*`, DEMELTINA and PAINE one action apart from their own
training halls, rescued into `$WISH_SPECIMENS` from `work/curse/234-*` for
`#234 (A dual-classed Curse or Silver Blades character converted to DOS loses
the class he trained out of)`.  Those tests skip without the specimen tree.
"""

from __future__ import annotations

import gamedata
import pytest

from goldbox import amiga, dos, dos_layout, neutral

CURSE = dos_layout.CURSE_OF_THE_AZURE_BONDS
SILVER_BLADES = dos_layout.SECRET_OF_THE_SILVER_BLADES
POOLS_OF_DARKNESS = dos_layout.POOLS_OF_DARKNESS
POOL_OF_RADIANCE = dos_layout.POOL_OF_RADIANCE


# --- helpers ------------------------------------------------------------
def dos_record(shape: dos_layout.DosShape, **values) -> bytes:
    """A record of the given shape with the named fields set, built from
    `goldbox/dos_layout.py`'s own table -- no game data, runs anywhere."""
    rec = bytearray(shape.record_size)
    table = dos_layout.FIELDS_BY_NAME_FOR[shape.key]
    for name, value in values.items():
        f = table[name]
        raw = bytes([value] * f.size) if isinstance(value, int) else value
        assert len(raw) == f.size, name
        rec[f.span] = raw
    return bytes(rec)


def neutral_of(shape: dos_layout.DosShape, **values):
    return dos.to_neutral(dos.DosCharacter(dos_record(shape, **values),
                                           shape=shape))


def _former_class_levels(shape: dos_layout.DosShape, **slots: int) -> bytes:
    """The former-class array for one shape, by class name."""
    size = dos_layout.FIELDS_BY_NAME_FOR[shape.key]["former_class_levels"].size
    arr = bytearray(size)
    for name, level in slots.items():
        arr[dos._DOS_CLASS_SLOT[name]] = level
    return bytes(arr)


# --- the field itself -----------------------------------------------------
def test_former_level_is_named_at_the_measured_offset_in_the_three_shapes():
    """`0x0E6`, `0x0EF`, `0x139` -- the byte right after `level` in Curse,
    Silver Blades and Pools of Darkness, and absent from Pool of Radiance,
    which has no such array either."""
    assert dos_layout.FIELDS_BY_NAME_FOR[CURSE.key]["former_level"].offset \
        == 0x0E6
    assert dos_layout.FIELDS_BY_NAME_FOR[SILVER_BLADES.key][
        "former_level"].offset == 0x0EF
    assert dos_layout.FIELDS_BY_NAME_FOR[POOLS_OF_DARKNESS.key][
        "former_level"].offset == 0x139
    assert "former_level" not in dos_layout.FIELDS_BY_NAME_FOR[
        POOL_OF_RADIANCE.key]
    assert "former_level" not in dos_layout.FIELDS_BY_NAME


def test_former_level_is_confirmed_not_a_gap():
    """It used to be `gap_0e6`/`gap_0ef`/`gap_139`, UNKNOWN. Naming it moves
    it to CONFIRMED, on the two watched training-hall transitions below."""
    for shape in (CURSE, SILVER_BLADES, POOLS_OF_DARKNESS):
        f = dos_layout.FIELDS_BY_NAME_FOR[shape.key]["former_level"]
        assert f.confidence == dos_layout.Confidence.CONFIRMED


# --- the reader: the non-zero convention -----------------------------------
def test_an_all_zero_array_reads_an_empty_dict():
    """Nobody dual-classed: every slot of the array and the byte after
    `level` are zero, and `former_levels` is `{}`, not eight zero entries."""
    n = neutral_of(CURSE, class_levels=bytes((1, 0, 0, 0, 0, 0, 0, 0)))
    assert n.get("former_levels") == {}


def test_one_former_class_agreeing_with_the_byte_reads_with_no_warning():
    """Array slot 3 (paladin) = 5, byte after `level` = 5: they agree, and
    the read is silent about it."""
    n = neutral_of(CURSE,
                   former_class_levels=_former_class_levels(CURSE, paladin=5),
                   former_level=5)
    assert n.get("former_levels") == {"paladin": 5}
    assert n.warnings == []


def test_the_array_and_the_byte_disagreeing_is_a_warning_naming_both():
    """Same array, byte after `level` = 3 instead of 5: `former_levels` still
    comes from the array -- the two watched specimens below confirm the array
    is the one written first -- but the disagreement is not silent."""
    n = neutral_of(CURSE,
                   former_class_levels=_former_class_levels(CURSE, paladin=5),
                   former_level=3)
    assert n.get("former_levels") == {"paladin": 5}
    assert len(n.warnings) == 1
    assert "5" in n.warnings[0] and "3" in n.warnings[0]


def test_pool_of_radiance_has_no_former_levels_field_at_all():
    """Pool of Radiance declares neither array nor byte, so the neutral
    record carries no `former_levels` entry -- absent, not empty."""
    n = neutral_of(POOL_OF_RADIANCE)
    assert "former_levels" not in n


# --- the disposition tables: the mandatory row ------------------------------
@pytest.mark.parametrize("shape", (CURSE, SILVER_BLADES, POOLS_OF_DARKNESS),
                         ids=lambda s: s.key)
def test_former_level_has_a_disposition_in_every_later_shape(shape):
    """A field the table declares and `field_disposition` names nowhere is a
    field dropped in silence -- the mechanism that makes the row mandatory."""
    table = dos.field_disposition(shape)
    assert "former_level" in table
    assert "former_class_levels" in table


def test_former_level_has_a_disposition_in_the_amiga_reader():
    for shape in (amiga.CURSE_SHAPE, amiga.SILVER_BLADES_SHAPE):
        declared = [f.name for f in dos_layout.layout_for(shape.dos)]
        unaccounted, unknown = neutral.undeclared(
            declared, amiga.later_field_disposition(shape))
        assert not unaccounted, (shape.key, sorted(unaccounted))
        assert not unknown, (shape.key, sorted(unknown))
        assert "former_level" in amiga.later_field_disposition(shape)
        assert "former_class_levels" in amiga.later_field_disposition(shape)


# --- the Amiga reader: carried, not dropped ---------------------------------
def test_amiga_reads_former_levels_with_no_drop_line():
    """`to_neutral_later` used to drop `former_class_levels` outright, saying
    there was nowhere to put it -- stale since `former_levels` landed. A fake
    record with the array set now reaches the neutral record and the report
    says nothing about a drop."""
    shape = amiga.CURSE_SHAPE
    f = shape.dos_field("former_class_levels")
    raw = bytearray(shape.record_size)
    for i in range(6):
        raw[0x10 + 2 * i] = raw[0x11 + 2 * i] = 12   # a legal ability pair
    arr = bytearray(f.size)
    arr[dos._DOS_CLASS_SLOT["paladin"]] = 5
    at = shape.offset(f.offset)
    raw[at:at + f.size] = arr
    char = amiga.AmigaCharacter.from_bytes(bytes(raw), shape)
    n = amiga.to_neutral_later(char)
    assert n.get("former_levels") == {"paladin": 5}
    assert not any("former" in d.lower() for d in n.dropped)


# --- specimens: the two watched training-hall transitions -------------------
def _read(name: str, filename: str) -> dos.DosCharacter:
    where = gamedata.specimen(name)
    return dos.read_character(where / filename)


@pytest.mark.skipif(not gamedata.have_specimen("curse-234-before"),
                    reason="needs the Curse dual-class specimens")
def test_curse_specimen_before_and_after_the_training_hall():
    """DEMELTINA, human paladin 5, one action through Curse's HUMAN CHANGE
    CLASSES: paladin 5 -> cleric 1. `#234`'s own worked example."""
    before = dos.to_neutral(_read("curse-234-before", "CHRDATC1.SAV"))
    after = dos.to_neutral(_read("curse-234-dualclassed", "CHRDATD1.SAV"))

    assert before.get("former_levels") == {}
    assert before.warnings == []

    assert after.get("former_levels") == {"paladin": 5}
    assert after.get("levels")["paladin"] == 0
    assert after.get("levels")["cleric"] == 1
    assert after.get("class_bits") == 0x02   # the new class only, not yet
                                              # regained (docs/117, `#234`)
    assert after.warnings == []


@pytest.mark.skipif(not gamedata.have_specimen("ssb-234-before"),
                    reason="needs the Silver Blades dual-class specimens")
def test_silver_blades_specimen_before_and_after_the_training_hall(monkeypatch):
    """PAINE, human ranger 8, one action through Silver Blades' HUMAN CHANGE
    CLASSES: ranger 8 -> magic-user 1.

    Silver Blades is not on `dos.CONVERTS` -- nobody has loaded a converted
    Silver Blades save in the running game the way `#192` did for Curse, and
    this test does not claim to settle that. It only exercises the
    former-class reader this file is about, so `CONVERTS` is widened for the
    one call rather than for the module.
    """
    monkeypatch.setattr(dos, "CONVERTS", dos.CONVERTS + (SILVER_BLADES,))
    before = dos.to_neutral(_read("ssb-234-before", "CHRDATC2.SAV"))
    after = dos.to_neutral(_read("ssb-234-dualclassed", "CHRDATD2.SAV"))

    assert before.get("former_levels") == {}
    assert before.warnings == []

    assert after.get("former_levels") == {"ranger": 8}
    assert after.get("levels")["ranger"] == 0
    assert after.get("levels")["magic-user"] == 1
    assert after.get("class_bits") == 0x01   # the new class only
    assert after.warnings == []
