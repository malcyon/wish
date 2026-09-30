"""The C64 strength index a converted character arrives with, per title.

The C64 fight code finds a character's strength bonus to hit and damage by
the index at record `0x0E2`.  All three titles compute it with the same
routine (Pool of Radiance `LIBRARY $3ED2`, Curse `$3FB6`, Silver Blades
`$3804`): strength below 18 is its own index, 18 counts up one per
percentile band from 18, and 19 or more is strength + 5, capped at 30.  So
a strength-21 character is index 26, the row giving +4 to hit and +9
damage.

The synthetic tests need no game files.  The last one reads each title's
own routine off the player's disks and runs its arithmetic, and skips
without them.
"""

from __future__ import annotations

import pytest

from goldbox import c64_codec, c64_port
from goldbox.neutral import NeutralCharacter

POOL = "pool-of-radiance"
CURSE = "curse-of-the-azure-bonds"
SSB = "secret-of-the-silver-blades"

#: (strength, percentile, the index the C64 routine stores).  18/00 is
#: percentile 100.
CASES = [
    (17, 0, 17),
    (18, 50, 19),
    (18, 100, 23),
    (19, 0, 24),
    (21, 0, 26),
    (25, 0, 30),
]


def _char(game: str, strength: int, percentile: int) -> NeutralCharacter:
    char = NeutralCharacter("test", source="made up", game=game)
    char.set("levels", {"fighter": 1}, "made up")
    char.set("strength", strength, "made up")
    char.set("exceptional_strength", percentile, "made up")
    return char


@pytest.mark.parametrize("game", [POOL, CURSE, SSB])
@pytest.mark.parametrize("strength, percentile, index", CASES)
def test_a_converted_character_gets_the_index_the_c64_computes(
        game, strength, percentile, index):
    rec, _ = c64_codec.write(_char(game, strength, percentile))
    assert rec.get("strength_index") == index


@pytest.mark.parametrize("strength, percentile, index", CASES)
def test_strength_index(strength, percentile, index):
    assert c64_codec.strength_index(strength, percentile) == index


def test_the_index_never_passes_the_last_table_row():
    """The routine caps at 30, the last row of its 31-row tables."""
    assert c64_codec.strength_index(26, 0) == 30
    assert c64_codec.strength_index(30, 0) == 30


#: The routine, from `CMP #$12` to the cap: `CMP #18; BCC store; BEQ
#: percentile; CLC; ADC #5; CMP #31; BCC store; LDA #30`.
_ROUTINE = bytes.fromhex("C912900BF00D186905C91F9002A91E")
#: Each title's `LIBRARY` base.
_LIBRARY_BASE = {POOL: 0x2C48, CURSE: 0x2DC8, SSB: 0x2DC8}


def _game_index(library: bytes, base: int, strength: int, percentile: int) -> int:
    """The routine's own arithmetic, with its constants and its percentile
    table read out of `library` rather than written here."""
    at = library.find(_ROUTINE)
    assert at >= 0 and library.find(_ROUTINE, at + 1) < 0
    top, add = library[at + 1], library[at + 8]
    below, cap = library[at + 10], library[at + 14]
    # `STA idx; RTS; STA idx; LDA pct; BEQ; LDX #4; SEC; SBC table,X`.
    sbc = at + len(_ROUTINE) + 3 + 1 + 3 + 3 + 2 + 2 + 1
    assert library[sbc] == 0xFD
    table_at = library[sbc + 1] | library[sbc + 2] << 8
    count = library[sbc - 2] + 1                          # `LDX #4`
    table = library[table_at - base:table_at - base + count]
    if strength < top:
        return strength
    if strength > top:
        return strength + add if strength + add < below else cap
    index = top
    if percentile:
        rest = percentile
        for x in range(count - 1, -1, -1):
            rest -= table[x]
            if rest < 0:
                break
            index += 1
    return index


@pytest.mark.parametrize("game", [POOL, CURSE, SSB])
def test_every_strength_matches_the_titles_own_routine(game):
    from support.coldread import _root

    from tools.c64 import coldread
    title = c64_port.by_key(game)
    library = coldread.overlay(title, b"LIBRARY", _root(title))
    base = _LIBRARY_BASE[game]
    for strength in range(3, 26):
        for percentile in (range(101) if strength == 18 else (0,)):
            assert (c64_codec.strength_index(strength, percentile)
                    == _game_index(library, base, strength, percentile)), \
                (game, strength, percentile)
