"""The fourth `field_83_87` byte carries a C64 source's former class (#614).

Silver Blades' own importer reads this byte as the class a dual-classed
human left, in the shared DOS numbering (`docs/229-the-npc-window-bytes.md`).
A DOS or Amiga source already carries the whole window byte for byte
(`goldbox.dos_codec.window_source`); a C64 source has no window at all, and
until this fix nothing put the C64's own `dual_class_slot`/`dual_class_level`
pair -- surfaced as neutral `former_levels` by `goldbox.c64_codec.read` -- into
that byte, so a converted ex-paladin or ex-ranger reached Silver Blades'
import as though he had never changed class (Donald, #614: "converted
characters keep what they earned").

`support.amigarecords.sample` builds a `NeutralCharacter("C64")` with no
`field_83_87` window of its own, which is exactly what a real C64 source
looks like to every writer here -- no disk needed.
"""
from __future__ import annotations

from support.amigarecords import sample

from goldbox import amiga_later, amiga_port, dos_codec

CURSE = dos_codec.CURSE_OF_THE_AZURE_BONDS
SILVER_BLADES = dos_codec.SECRET_OF_THE_SILVER_BLADES


def _fighter_who_was_a_paladin():
    """A human fighter 8 who trained out of paladin 5 and passed his old
    level, so `former_levels` names the one class he left."""
    return sample(
        levels={"fighter": 8, "thief": 0, "cleric": 0, "magic-user": 0,
               "knight": 0, "paladin": 0, "ranger": 0},
        class_bits=4, char_class=2,
        former_levels={"paladin": 5})


def test_a_regained_paladins_former_class_reaches_dos_curse():
    rec, _itm, _spc, rep = dos_codec.write(
        _fighter_who_was_a_paladin(), deltas=CURSE)
    assert rec[0x0F9] == 3
    assert any("paladin was left at" in line for line in rep.sources.values())


def test_a_regained_paladins_former_class_reaches_dos_silver_blades():
    rec, _itm, _spc, _rep = dos_codec.write(
        _fighter_who_was_a_paladin(), deltas=SILVER_BLADES)
    assert rec[0x101] == 3


def test_a_regained_paladins_former_class_reaches_amiga_silver_blades():
    written, _rep = amiga_later.write_later(
        _fighter_who_was_a_paladin(), deltas=amiga_port.SILVER_BLADES_DELTAS)
    assert written.raw[0x9C] == 3


def test_a_character_who_never_dual_classed_gets_zero_in_curse():
    rec, _itm, _spc, rep = dos_codec.write(sample(), deltas=CURSE)
    assert rec[0x0F9] == 0
    assert not any("paladin was left at" in line
                   for line in rep.sources.values())


def test_a_character_who_never_dual_classed_gets_zero_in_silver_blades():
    rec, _itm, _spc, _rep = dos_codec.write(sample(), deltas=SILVER_BLADES)
    assert rec[0x101] == 0


def test_a_source_with_its_own_window_keeps_its_own_fourth_byte():
    """A source with a window of its own is untouched by this fix: the byte
    already there travels through `window_source`, and `former_levels`'s
    class name is never consulted while a window is present."""
    char = _fighter_who_was_a_paladin()
    dos_codec.set_window_source(char, b"\x00\x00\x00\x04\x00")
    rec, _itm, _spc, _rep = dos_codec.write(char, deltas=CURSE)
    assert rec[0x0F9] == 4
