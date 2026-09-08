"""A converted character's THAC0 on the C64 sheet, computed rather than copied.

`#405 (A converted character's THAC0 on the C64 sheet is the source save's
stored byte, and the engine only corrects it at his first fight)`. The C64
sheet draws `thac0_current` straight (`LIBRARY $3758`) and nothing recomputes
it before the party's first fight, so a copied byte can carry a number the
C64's own tables would never produce -- a low-level magic-user or thief is
THAC0 20 on DOS and 21 on the C64 (`#318`). Donald's ruling on the issue:
compute it on the way out, the way `LIBRARY $3918` (`$3729` in Pool of
Radiance) rebuilds it at the party's first fight -- `thac0_base` plus the
AD&D strength to-hit bonus, gated on `strength_bonus_flag` -- so our number
and the engine's own first recompute agree from the moment the character
arrives. `docs/205-the-c64-thac0-rebuild.md` is the evidence, from `#368`.

Synthetic characters throughout except the last test, which reads the real
to-hit table off the player's own `LIBRARY` the way
`tests/test_c64strengthflag.py` does, so the claim that our number is the
engine's own is checked rather than assumed.
"""

from __future__ import annotations

from goldbox import c64_codec
from goldbox import levels as level_tables
from goldbox.encoding import COMBAT_BIAS, combat_value
from goldbox.neutral import NeutralCharacter
from tests import gamedata


def _char(levels: dict[str, int], strength: int = 10, percentile: int = 0,
          source_thac0_current: int | None = None) -> NeutralCharacter:
    """A neutral character with just enough to reach `c64_codec.write`'s
    THAC0 arithmetic: class levels, a strength score, and a source-stored
    `thac0_current` -- the byte a real save carries that this fix stops
    trusting."""
    char = NeutralCharacter("test", source="a made-up character")
    char.set("levels", levels, "made up")
    char.set("strength", strength, "made up")
    char.set("exceptional_strength", percentile, "made up")
    char.set("thac0_base", 8, "made up: overwritten by the class levels "
                              "regardless (#366)")
    if source_thac0_current is not None:
        char.set("thac0_current", source_thac0_current,
                 "made up: the source save's own stored byte")
    return char


def test_thac0_current_byte_adds_the_bonus_only_when_the_gate_is_open():
    """The pure arithmetic `LIBRARY $3918` does: `thac0_base` plus the
    strength to-hit bonus, and nothing added when `strength_bonus_flag` is
    clear (#277) -- the case `write` itself can never produce, since it
    always sets the flag to 1, so the gate is exercised directly here."""
    assert c64_codec.thac0_current_byte(44, 2, True) == 46
    assert c64_codec.thac0_current_byte(44, 2, False) == 44
    assert c64_codec.thac0_current_byte(44, 0, True) == 44


def test_thac0_current_byte_wraps_like_the_c64s_own_byte_arithmetic():
    """The stored byte is `60 - THAC0`; a strong bonus can carry it past 255
    the way an 8-bit `ADC` would, and the engine's own byte does the same."""
    assert c64_codec.thac0_current_byte(254, 3, True) == 1


def test_a_low_level_magic_user_arrives_with_the_c64s_own_thac0():
    """`#318 (DOS gives a low-level magic-user or thief THAC0 20 where the
    C64 gives 21, and our table holds only the C64's own)`: a magic-user 3's
    DOS save stores THAC0 20 -- byte 40 -- and the C64's own table gives 21.
    Before this fix the converted sheet showed 20, the DOS number, until the
    party's first fight; now it shows 21 from the moment the character
    arrives."""
    char = _char({"magic-user": 3}, source_thac0_current=COMBAT_BIAS - 20)
    rec, _ = c64_codec.write(char)
    expected = level_tables.base_thac0({"magic-user": 3}, char.game)
    assert expected == 21          # the C64's own table, not DOS's 20 (#366)
    assert rec.thac0_base_value == expected
    assert combat_value(rec.get("thac0")) == expected
    assert combat_value(rec.get("thac0")) != 20


def test_a_character_whose_source_thac0_already_agreed_converts_unchanged():
    """The control: a fighter 1's THAC0 is 20 in both ports (#318's own
    table), and strength 10 gives no bonus, so the recomputed byte matches
    the number the source already held."""
    expected = level_tables.base_thac0({"fighter": 1}, None)
    assert expected == 20
    char = _char({"fighter": 1}, strength=10,
                 source_thac0_current=COMBAT_BIAS - 20)
    rec, _ = c64_codec.write(char)
    assert combat_value(rec.get("thac0")) == 20


def test_a_strong_character_gets_his_bonus_through_the_full_conversion():
    """`#277`'s worked example, end to end through `write`: an 18/75 fighter
    1. `write` always opens the strength gate (#277), so his converted sheet
    carries the +2 to-hit bonus the C64's own table gives that score, two
    points better than his bare `thac0_base`."""
    char = _char({"fighter": 1}, strength=18, percentile=75,
                 source_thac0_current=COMBAT_BIAS - 99)   # a stale sentinel
    rec, _ = c64_codec.write(char)
    assert rec.get("strength_bonus_flag") == 1
    assert rec.get("strength_index") == 20
    base = combat_value(rec.get("thac0_base"))
    assert base == 20                          # fighter 1, C64's own table
    assert combat_value(rec.get("thac0")) == base - 2
    assert combat_value(rec.get("thac0")) != base


def test_our_number_is_what_the_engines_own_first_fight_would_write():
    """The real check: read `LIBRARY`'s own to-hit table for an 18/75
    fighter's row and confirm our recomputed byte is exactly what
    `LIBRARY $3918`'s `ADC` would leave in the roster the moment the party's
    first fight starts -- so the sheet never has to correct itself again.

    Same technique as
    `tests/test_c64strengthflag.py::test_the_converted_fighter_reaches_plus_two_and_plus_three_in_the_games_own_tables`:
    the table stays on the player's own disk, and only the one number it
    gives comes back here.
    """
    library = gamedata.game_file("LIBRARY")
    base = 0x2C48

    def signed(table: int, row: int) -> int:
        byte = library[table - base + row]
        return byte - 256 if byte > 127 else byte

    char = _char({"fighter": 1}, strength=18, percentile=75,
                 source_thac0_current=COMBAT_BIAS - 1)
    rec, _ = c64_codec.write(char)
    row = rec.get("strength_index") if rec.get("strength_bonus_flag") else 0
    hit_from_the_game = signed(0x3651, row)
    engine_thac0 = combat_value(rec.get("thac0_base")) - hit_from_the_game
    assert combat_value(rec.get("thac0")) == engine_thac0
