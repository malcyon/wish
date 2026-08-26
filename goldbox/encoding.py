"""The biased encodings the format uses, in one place.

Three fields are stored as an offset rather than as themselves, because the
value they hold gets *better* as it gets smaller and the game wanted a byte that
rises:

| stored as | fields |
|---|---|
| `60 - value` | THAC0, armour class -- record `0x071`, `0x10E`, `0x10F`, roster `+0x0E`, `+0x0F` |
| `48 + value` | the armour bonus at roster `+0x10` |
| `60 - value` | an item's protection byte in the `ITEMS` type table, bit 7 masked off |

`RosterBlock` applies the first two for you. **The record does not**: `get` hands
back the byte as stored, so `record.get("thac0_base")` is `39` for a THAC0 of
21. Every caller that forgets is off by a lot and in the wrong direction, which
is why these are functions rather than a constant to subtract by hand.
"""

from __future__ import annotations

COMBAT_BIAS = 60
ARMOUR_BONUS_BIAS = 48
#: `ITEMS` type byte +6, bit 7: the item affects armour class at all.
ITEM_PROTECTION_GRANTS = 0x80


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


def item_protection_ac(protection: int) -> int:
    """An `ITEMS` protection byte as the armour class it grants.

    This was long read as `12 - (byte & 0x0F)` under a `$B0` mask, which is the
    same arithmetic in disguise -- `60 - (0x30 + n)` is `12 - n` -- and agrees
    with the general rule on every armour the disks carry. **They diverge at
    armour class 13**: `$AF` is 13 here and -3 under the nibble rule, and the
    general form is the one the rest of the format uses. `goldbox/items.py` reads
    the byte with the same rule and decides bonus-versus-class by magnitude.
    """
    return COMBAT_BIAS - (protection & 0x7F)
