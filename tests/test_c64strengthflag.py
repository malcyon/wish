"""The strength gate a converted character needs to keep its bonus.

#277 (A DOS character converted to the C64 loses the strength bonus to hit
and damage, because 0x0E3 is written zero).  The C64 record keeps the AD&D
strength adjustment in two bytes, not one: `strength_index` at 0x0E2 says
*which row* of the tables at `LIBRARY $3651`/`$3670` applies, and
`strength_bonus_flag` at 0x0E3 says whether any row applies at all --

    $375C  LDX $6BE3      ; the flag
    $375F  BEQ $3764      ; zero: row 0, no adjustment either way
    $3761  LDX $6BE2      ; else the index

so a record with the right index and a zero flag is a character with no
strength bonus.  Measured in the running game on 2026-09-05: two converted
records identical but for that byte, both 18/75 fighters, came out of the
first ambush's roster recompute at THAC0 20 with no damage bonus and THAC0
18 with +3.

Most of these build a record from zeroes and need no game files.  The one
that reads a real 18/75 fighter uses the specimen this project rolled in the
game's own creation screens, and skips where there is none.
"""

from __future__ import annotations

import pytest

from goldbox import c64_codec, dos, dos_layout
from tests import gamedata

STR_BONUS = dos_layout.FIELDS_BY_NAME["strength_bonus"]
STRENGTH = dos_layout.FIELDS_BY_NAME["strength"]
EXCEPTIONAL = dos_layout.FIELDS_BY_NAME["exceptional_strength"]


def _dos_record(strength: int = 18, percentile: int = 75,
                flag: int = 1) -> dos.DosCharacter:
    """A Pool of Radiance DOS record that is zero but for its strength."""
    raw = bytearray(dos_layout.RECORD_SIZE)
    raw[STRENGTH.offset] = strength
    raw[EXCEPTIONAL.offset] = percentile
    raw[STR_BONUS.offset] = flag
    return dos.DosCharacter(bytes(raw))


def _converted(**kw):
    return c64_codec.write(dos.to_neutral(_dos_record(**kw)))


def test_a_converted_character_has_the_strength_gate_open():
    """The byte the engine tests before it looks at the index at all.

    Without this the conversion writes a correct `strength_index` that
    `LIBRARY $375C` never reaches, and the character swings at no bonus.
    """
    rec, _ = _converted()
    assert rec.get("strength_bonus_flag") == 1


def test_the_gate_is_open_for_every_strength_not_only_an_exceptional_one():
    """`GEN $0B79` writes 1 for every character it creates, whatever the
    score: rows 8 to 15 of the tables are zero anyway, so the flag is about
    being a character rather than about being strong."""
    for strength, percentile in ((3, 0), (9, 0), (16, 0), (18, 0), (18, 100)):
        rec, _ = _converted(strength=strength, percentile=percentile)
        assert rec.get("strength_bonus_flag") == 1, (strength, percentile)


def test_the_index_and_the_gate_agree_on_an_exceptional_fighter():
    """18/75 is row 20 of the C64's tables, which is +2 to hit and +3 damage.
    Both bytes have to be right for the engine to reach that row."""
    rec, _ = _converted(strength=18, percentile=75)
    assert rec.get("strength_index") == 20
    assert rec.get("strength_bonus_flag") == 1


def test_the_converted_fighter_reaches_plus_two_and_plus_three_in_the_games_own_tables():
    """What the player is owed, read out of the machine rather than asserted.

    `LIBRARY` is resident at $2C48 and holds the two adjustment tables the
    gate indexes.  This does the arithmetic the engine does at `$375C` --
    row 0 when the flag is clear, `strength_index` when it is set -- and an
    18/75 fighter has to come out at +2 to hit and +3 damage, which is the
    Players Handbook row for that score.  The tables stay on the player's
    own disk; only the two numbers come back here.
    """
    # `load_payload` has already taken the PRG load address off, and the
    # address in the header is a lie in any case: every overlay claims $1000
    # and `LIBRARY` is resident at $2C48 (docs/41-memory-regions.md).
    library = gamedata.game_file("LIBRARY")
    base = 0x2C48

    def signed(table: int, row: int) -> int:
        byte = library[table - base + row]
        return byte - 256 if byte > 127 else byte

    rec, _ = _converted(strength=18, percentile=75)
    row = rec.get("strength_index") if rec.get("strength_bonus_flag") else 0
    assert (signed(0x3651, row), signed(0x3670, row)) == (2, 3)


def test_a_c64_record_read_and_written_back_keeps_the_gate():
    """The reader has no neutral field for the flag, so the round trip rests
    on the writer's own rule -- and has to survive it."""
    rec, _ = _converted()
    again, _ = c64_codec.write(c64_codec.read(rec))
    assert again.get("strength_bonus_flag") == 1


@pytest.mark.skipif(not gamedata.have_specimen("elf6"),
                    reason="needs the rolled 18/75 fighter specimen")
def test_the_rolled_eighteen_seventyfive_fighter_converts_with_the_gate_open():
    """The record the running-game run used: WISH-SPEC-elf6, an elf fighter
    with 18/75 rolled in DOS Pool of Radiance's own creation screens.

    Its DOS `strength_bonus` is 1, and the C64 record it converts to has to
    say the same thing in its own byte.
    """
    where = gamedata.specimen("elf6")
    char = dos.read_character(where / "party-ELF6.CHA")
    assert char.get("strength") == 18
    assert char.get("exceptional_strength") == 75
    assert char.get("strength_bonus") == 1
    rec, _ = c64_codec.write(dos.to_neutral(char))
    assert rec.get("strength_index") == 20
    assert rec.get("strength_bonus_flag") == 1
