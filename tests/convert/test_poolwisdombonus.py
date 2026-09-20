"""#559 (A converted DOS Pool of Radiance cleric with wisdom 12 or 13 arrives
on the C64 one first-level spell short).

Pool of Radiance's own cleric wisdom bonus starts one point lower on the C64
than on DOS -- `GEN $10AD` grants a first-level bonus spell at wisdom 12, DOS's
own table (`START.EXE 0x00F6B0`, `#557`) at 13. `goldbox.c64_codec.write`
copied the source's `spells_castable` array unchanged, so a DOS cleric of
wisdom 12 or 13 converted to the C64 arrived one first-level spell short of
what the C64 trainer itself would give the same wisdom. Fixed by recomputing
the cleric column through the C64's own table
(`goldbox.spells.capacity_by_class`, no `port`) for a source port measured to
differ -- `goldbox.c64_codec._SPELL_SLOT_RECOMPUTE_FROM_PORTS`, the mirror of
`goldbox.dos_codec`'s three `_..._RECOMPUTE_FROM_PORTS` tuples for the other
direction.

The two engine-written specimens are #84's own DOS creation-screen rolls,
reached through the specimen tree; everything else here is a synthetic
`NeutralCharacter`, which is how `tests/curse_of_the_azure_bonds/test_cursespellslots.py` tests the
mirror-image gate on `goldbox.dos_codec.write`.
"""

from __future__ import annotations

import pytest
from gamedata import specimen

from goldbox import c64_codec, dos_codec, neutral

POOL = "pool-of-radiance"


def _packed_cleric_nibble(rec) -> int:
    return rec.get_raw("spells_castable")[0] >> 4


def _c64_written(port: str, wisdom: int, cleric_level: int = 1,
                 castable_cleric=(1, 0, 0)):
    char = neutral.NeutralCharacter(port, game=POOL)
    char.set("name", "TEST", "test fixture")
    char.set("levels", {"cleric": cleric_level}, "test fixture")
    char.set("wisdom", wisdom, "test fixture")
    char.set("spells_castable",
             {"cleric": castable_cleric, "magic-user": (0, 0, 0)},
             "test fixture: the source's own array")
    rec, _rep = c64_codec.write(char)
    return rec


def test_a_dos_cleric_of_wisdom_12_converted_to_c64_gets_the_c64s_own_bonus():
    """DOS's own wisdom-12 write is `1 0 0` (#557); the C64 trainer at the
    same wisdom gives `2 0 0` and the converted record must match it."""
    rec = _c64_written("DOS", wisdom=12, castable_cleric=(1, 0, 0))
    assert _packed_cleric_nibble(rec) == 2


def test_a_dos_cleric_of_wisdom_13_converted_to_c64_gets_the_c64s_own_bonus():
    """DOS's own wisdom-13 write is `2 0 0`; the C64 trainer gives `3 0 0`."""
    rec = _c64_written("DOS", wisdom=13, castable_cleric=(2, 0, 0))
    assert _packed_cleric_nibble(rec) == 3


def test_a_c64_source_array_is_copied_unchanged():
    """The gate must not rewrite a record that was already right: a C64
    source at wisdom 12 already carries the C64's own `1 0 0`
    (`GEN $10AD`'s one-point-low table), and it is copied, not
    "corrected" a second time."""
    rec = _c64_written("C64", wisdom=12, castable_cleric=(1, 0, 0))
    assert _packed_cleric_nibble(rec) == 1


def test_an_amiga_source_keeps_its_own_array():
    """`_SPELL_SLOT_RECOMPUTE_FROM_PORTS` names DOS alone -- nobody has read
    Amiga Pool of Radiance's own wisdom table, so an Amiga source's array is
    copied rather than "corrected" by a table never checked against it. This
    is what goes wrong if the gate is ever widened to include it."""
    rec = _c64_written("Amiga", wisdom=12, castable_cleric=(1, 0, 0))
    assert _packed_cleric_nibble(rec) == 1


@pytest.mark.parametrize("name,wisdom,c64_nibble", [
    ("human7", 12, 2), ("halfe8", 13, 3)])
def test_dos_specimens_converted_to_c64_get_the_c64s_own_bonus(
        name, wisdom, c64_nibble):
    """The issue's own test: `WISH-SPEC-human7` (wisdom 12) and
    `WISH-SPEC-halfe8` (wisdom 13), read `goldbox.dos_codec.read_character`
    -> `to_neutral` -> `goldbox.c64_codec.write`. Fails today at 1 and 2."""
    where = specimen(name, "dos")
    cha = sorted(where.glob("*.CHA"))
    assert cha, f"WISH-SPEC-{name} has no .CHA"
    dos = dos_codec.read_character(cha[0])
    char = dos_codec.to_neutral(dos)
    assert char.get("wisdom") == wisdom
    rec, _rep = c64_codec.write(char)
    assert _packed_cleric_nibble(rec) == c64_nibble
