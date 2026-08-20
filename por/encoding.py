"""The biased encodings the format uses, in one place.

Three fields are stored as an offset rather than as themselves, because the
value they hold gets *better* as it gets smaller and the game wanted a byte that
rises:

| stored as | fields |
|---|---|
| `60 - value` | THAC0, armour class -- record `0x071`, `0x10E`, `0x10F`, roster `+0x0E`, `+0x0F` |
| `48 + value` | the armour bonus at roster `+0x10` |
| `12 - AC` | an item's protection nibble in the `ITEMS` type table |

`RosterBlock` applies the first two for you. **The record does not**: `get` hands
back the byte as stored, so `record.get("thac0_base")` is `39` for a THAC0 of
21. Every caller that forgets is off by a lot and in the wrong direction, which
is why these are functions rather than a constant to subtract by hand.
"""

from __future__ import annotations

COMBAT_BIAS = 60
ARMOUR_BONUS_BIAS = 48
ITEM_PROTECTION_BIAS = 12


def combat_value(stored: int) -> int:
    """A stored THAC0 or armour-class byte, as the number on the sheet."""
    return COMBAT_BIAS - stored


def combat_byte(value: int) -> int:
    """The reverse. Raises rather than wrapping, because a silent wrap here
    produces a plausible number: 60 - (-5) is 65, a perfectly ordinary byte."""
    stored = COMBAT_BIAS - int(value)
    if not 0 <= stored <= 0xFF:
        raise ValueError(
            f"{value} does not fit the 60-x encoding (would store {stored})")
    return stored


def armour_bonus_value(stored: int) -> int:
    return stored - ARMOUR_BONUS_BIAS


def armour_bonus_byte(value: int) -> int:
    stored = ARMOUR_BONUS_BIAS + int(value)
    if not 0 <= stored <= 0xFF:
        raise ValueError(
            f"{value} does not fit the 48+x encoding (would store {stored})")
    return stored


def item_protection_ac(low_nibble: int) -> int:
    """An `ITEMS` protection nibble as the armour class it grants."""
    return ITEM_PROTECTION_BIAS - (low_nibble & 0x0F)
