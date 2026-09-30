"""The strength to-hit and damage steps the C64 writer applies, per title.

The C64 rebuild reads its to-hit table by the strength index, and that table
has rows for strength 3 to 7 and 19 to 25 as well as 8 to 18.  The disk-backed
test reads Curse's and Pool of Radiance's own table; Silver Blades' table
address is unread, so it is covered by the synthetic test only.  The damage
table follows the to-hit table in every title's `LIBRARY`, 31 bytes on.
"""

from __future__ import annotations

import pytest

from goldbox import c64_codec, c64_port
from goldbox.encoding import COMBAT_BIAS, combat_value
from goldbox.neutral import NeutralCharacter

POOL = "pool-of-radiance"
CURSE = "curse-of-the-azure-bonds"

#: (title, `LIBRARY` base, to-hit table address).
TABLES = {POOL: (0x2C48, 0x3651), CURSE: (0x2DC8, 0x3840)}


def _char(game: str, strength: int, percentile: int = 0) -> NeutralCharacter:
    char = NeutralCharacter("test", source="made up", game=game)
    char.set("levels", {"fighter": 1}, "made up")
    char.set("strength", strength, "made up")
    char.set("exceptional_strength", percentile, "made up")
    char.set("thac0_base", COMBAT_BIAS - 20, "made up")
    char.set("thac0_current", COMBAT_BIAS - 99, "made up: the write recomputes it")
    return char


@pytest.mark.parametrize("game", [POOL, CURSE])
@pytest.mark.parametrize("strength, step", [(21, 4), (25, 7), (26, 7), (5, -2)])
def test_a_strength_outside_8_to_18_gets_the_c64_tables_step(game, strength, step):
    # An empty type table selects Pool's own block; Curse ignores it.
    rec, _ = c64_codec.write(_char(game, strength), item_types={})
    base = combat_value(rec.get("thac0_base"))
    assert combat_value(rec.get("thac0")) == base - step
    assert rec.get("thac0") == (rec.get("thac0_base") + step) & 0xFF


@pytest.mark.parametrize("game", [POOL, CURSE])
def test_every_strength_step_matches_the_titles_own_table(game):
    """Runs the writer, and compares what it added with the game's table row
    at the index the writer stored, so a wrong step shows as a wrong byte."""
    from support.coldread import _root

    from tools.c64 import coldread
    title = c64_port.by_key(game)
    library = coldread.overlay(title, b"LIBRARY", _root(title))
    base, table = TABLES[game]
    for strength in range(3, 26):
        for percentile in (range(101) if strength == 18 else (0,)):
            rec, _ = c64_codec.write(_char(game, strength, percentile),
                                     item_types={})
            row = library[table - base + rec.get("strength_index")]
            row -= 256 if row > 127 else 0
            added = (rec.get("thac0") - rec.get("thac0_base") + 128) % 256 - 128
            assert added == row, (game, strength, percentile)


SILVER = "secret-of-the-silver-blades"

#: (title, `LIBRARY` base, damage table address); Silver Blades' `LIBRARY`
#: holds the to-hit table at payload offset 0x5D4, so `$339C` with the `$2DC8`
#: base, and the damage table at `$33BB`.
DAMAGE_TABLES = {POOL: (0x2C48, 0x3670), CURSE: (0x2DC8, 0x385F),
                 SILVER: (0x2DC8, 0x33BB)}


@pytest.mark.parametrize("game", [POOL, CURSE, SILVER])
def test_every_damage_step_matches_the_titles_own_table(game):
    from support.coldread import _root

    from tools.c64 import coldread
    title = c64_port.by_key(game)
    library = coldread.overlay(title, b"LIBRARY", _root(title))
    base, table = DAMAGE_TABLES[game]
    for strength in range(3, 26):
        for percentile in (range(101) if strength == 18 else (0,)):
            rec, _ = c64_codec.write(_char(game, strength, percentile),
                                     item_types={})
            row = library[table - base + rec.get("strength_index")]
            row -= 256 if row > 127 else 0
            assert c64_codec.c64_strength_damage_step(
                strength, percentile) == row, (game, strength, percentile)
