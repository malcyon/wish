"""A paladin's cure-disease and lay-on-hands uses, shared by every writer.

Moved out of `tools/c64/curedisease.py` (#626) because `goldbox/c64_codec.py`
needs `c64_cure_write` and neither `goldbox/` nor `dos_codec.py` may import
from `tools/`. `tools/c64/curedisease.py` imports these names back, so its own
callers and `tests/records/test_curedisease.py` keep working unchanged.
"""

from __future__ import annotations

import dataclasses


def full_count(level: int, thresholds: tuple[int, int] = (6, 11)) -> int:
    """What `GEN` seeds and the camp's reset restores for a paladin level."""
    if level <= 0:
        return 0
    return 1 + (level >= thresholds[0]) + (level >= thresholds[1])


def dos_full_count(level: int) -> int:
    """What the DOS refresh writes: `(level - 1) / 5 + 1`."""
    return (level - 1) // 5 + 1 if level > 0 else 0


#: The cure timer's id and the magnitude the cure writes, per C64 title.
CURE_TIMER = {"curse-of-the-azure-bonds": (141, 0xC7),
              "secret-of-the-silver-blades": (110, 0xC7)}

#: The lay-on-hands timer's id and the magnitude a spent use writes, per C64
#: title -- the pair `tools/c64/curedisease.py`'s own `_timer` reads off
#: `ECL65` as `lay_timer` (`(140, 0xC1)` Curse, `(109, 0xC1)` Silver Blades).
LAY_ON_HANDS_C64 = {"curse-of-the-azure-bonds": (140, 0xC1),
                    "secret-of-the-silver-blades": (109, 0xC1)}


class Unrepresentable(ValueError):
    """No C64 state gives this DOS paladin the same uses and recovery."""


@dataclasses.dataclass(frozen=True)
class CureWrite:
    """What a C64 writer puts in the save for one paladin's cures.

    `cures` is record `0x012`; each row is `(id, duration byte, magnitude)`
    in the save's effect arrays, owned by the paladin's own save slot.
    """

    cures: int
    rows: tuple[tuple[int, int, int], ...] = ()


def c64_cure_write(title: str, level: int, cures: int,
                   node_minutes: int | None, clock_minutes: int) -> CureWrite:
    """The C64 state that plays a DOS paladin's cures back the way DOS would.

    `title` is the C64 key, `level` the paladin level, `cures` the DOS uses
    byte, `node_minutes` the minutes left on his DOS cure node (id 141 in
    Curse, 110 in Silver Blades) or None, and `clock_minutes` the C64 save's
    time of day.

    Both DOS engines decrement the uses (never below 0), add a 10080-minute
    node only when he has none, and on the node's removal write
    `(level - 1) / 5 + 1`.  The C64 engines write the same count at a cure
    row's camp expiry and hide CURE at 0.  Where they differ is when a cure
    starts a timer: Silver Blades when he has no row, as DOS does; Curse
    only when `0x012` equals the full count (`ECL65 $86F4`-`$86FA`).  So:

    * the uses byte is always the DOS uses -- never a refill;
    * a DOS node becomes one row, its duration the byte whose camp-clock
      time left is nearest the node's minutes (`goldbox.effects.
      closest_duration`), magnitude `$C7` as the cure writes it;
    * no node, no row -- except a **Curse** paladin with 0 < uses < full,
      whom no C64 Curse state reproduces exactly.  Donald's decision
      (#600): write an adjustment row anyway, `(141, $C7, $C7)`, the same
      byte the cure itself writes -- his recovery starts fresh, seven days
      from the moment of conversion, rather than reproducing whenever DOS
      would actually have brought it back.  This is an adjustment, not DOS
      parity: with no row his first cure would start no timer and CURE
      would never return, so this trades an exact recovery time for one
      that at least exists.

    Level 16 and up, where DOS counts 4 and the C64 stops at 3, raises too.
    """
    from goldbox import effects

    full = full_count(level)
    if level <= 0:
        return CureWrite(0)
    if dos_full_count(level) != full:
        raise Unrepresentable(f"paladin level {level}: DOS refreshes to "
                              f"{dos_full_count(level)}, the C64 to {full}")
    if not 0 <= cures <= full:
        raise Unrepresentable(f"{cures} uses is more than the {full} a "
                              f"paladin {level} is ever given")
    eid, magnitude = CURE_TIMER[title]
    if node_minutes is not None:
        byte = effects.closest_duration(node_minutes, clock_minutes)
        return CureWrite(cures, ((eid, byte, magnitude),))
    if title == "curse-of-the-azure-bonds" and 0 < cures < full:
        return CureWrite(cures, ((eid, magnitude, magnitude),))
    return CureWrite(cures)
