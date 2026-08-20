"""The ten trait slots at `0x0AD`, and what the codes mean. No Qt, no I/O.

This is where racial abilities and monster specials live. `GEN $0BF3` seeds the
list per race from `[1, 0, 107, 0, 124, 0, 0, 0]`, so an elf is born carrying
107 and a half-elf 124 -- partial resistance to sleep and charm.

**The codes are named where we know them and shown raw where we do not.** About
forty were enumerated from 61 `MON*` records; some land on exactly the creatures
the Monster Manual says they should (83 on the two petrifiers, 119 on the five
monsters needing a magic weapon), and some are simply a number a mummy carries.
A code with no name here shows as its number and says so, which is the
difference between "we have not decoded this" and "there is nothing there".

Not to be confused with item byte `+14`, which shares these slots and not their
meaning: 85 is POTION OF HEALING as an item and "drains one level" here.

Lives in `por/` rather than in the editor because the combat view names the same
codes on a monster's tooltip, and one table cannot be allowed to become two.
"""

from __future__ import annotations

from dataclasses import dataclass

SLOTS = 10                     # 0x0AD-0x0B6; three overlays loop LDX #$09
FIRST = 0x0AD

# code -> (what it does, how sure we are). Read off the census in
# work/reports/analysis-batch.md and docs/50-experiments.md. A monster carrying
# a code is the evidence for it, so several are named by the one creature that
# has them and are marked accordingly.
NAMES: dict[int, tuple[str, str]] = {
    1: ("seeded for dwarves by GEN", "GUESS"),
    24: ("resist fire (spell 24)", "PROBABLE"),
    64: ("poison", "CONFIRMED"),
    65: ("poison, weaker grade", "PROBABLE"),
    66: ("poison, weaker grade", "PROBABLE"),
    67: ("poison, weaker grade", "PROBABLE"),
    68: ("paralysing touch", "PROBABLE"),
    69: ("poison bite", "GUESS"),
    73: ("rear-claw rake", "GUESS"),
    76: ("blood drain", "PROBABLE"),
    80: ("acid squirt", "PROBABLE"),
    83: ("petrifying gaze", "CONFIRMED"),
    85: ("drain one level", "CONFIRMED"),
    86: ("drain two levels", "CONFIRMED"),
    89: ("displacement", "PROBABLE"),
    99: ("fights on below 0 hp", "PROBABLE"),
    100: ("regeneration", "PROBABLE"),
    101: ("regeneration, or gets back up", "GUESS"),
    107: ("partial resistance to sleep and charm (elf)", "PROBABLE"),
    108: ("immunity to sleep and charm", "PROBABLE"),
    109: ("hit only by silver or magic", "PROBABLE"),
    110: ("immunity to cold", "PROBABLE"),
    112: ("immunity to fire", "PROBABLE"),
    113: ("efreeti fire resistance", "PROBABLE"),
    115: ("half damage from edged weapons", "PROBABLE"),
    117: ("undead, and so turnable", "PROBABLE"),
    119: ("hit only by magic weapons", "PROBABLE"),
    120: ("hurls boulders", "PROBABLE"),
    121: ("burrowing", "GUESS"),
    124: ("partial resistance to sleep and charm (half-elf)", "PROBABLE"),
    125: ("immunity to sleep, charm, paralysis and poison", "PROBABLE"),
    127: ("immunity to its own gaze", "GUESS"),
    139: ("phasing", "PROBABLE"),
    # 255 is the byte after the last used slot in a MON* record, not a code.
    255: ("fill, not a code", "PROBABLE"),
}

# The byte after the last used slot in a MON* record. Not a trait, and a live
# ORC carries it, so the combat tooltip drops it rather than printing "fill".
FILL = 255

UNNAMED = "not named yet"
EMPTY = "—"


def describe(code: int) -> str:
    """What a slot says. An unnamed code is visibly unnamed, never blank."""
    if not code:
        return EMPTY
    named = NAMES.get(code)
    return named[0] if named else UNNAMED


def confidence(code: int) -> str:
    """How sure the name is. `UNNAMED` codes have no confidence to report."""
    named = NAMES.get(code)
    return named[1] if named else ""


@dataclass(frozen=True)
class Trait:
    """One occupied slot, named if we can and numbered either way."""

    slot: int
    code: int

    @property
    def named(self) -> bool:
        return self.code in NAMES

    @property
    def is_fill(self) -> bool:
        return self.code == FILL

    @property
    def label(self) -> str:
        """`petrifying gaze` for a code we know, `trait 91` for one we do not.

        The number is what makes a new code visible rather than silently
        dropped, which is how the census grew in the first place.
        """
        return describe(self.code) if self.named else f"trait {self.code}"

    @property
    def detail(self) -> str:
        where = f"0x{FIRST + self.slot:03X}"
        if not self.named:
            return f"{where} holds {self.code}, which the census does not name"
        return f"{where}: {describe(self.code)} ({confidence(self.code)})"


def traits(raw: bytes) -> tuple[Trait, ...]:
    """The occupied slots of one ten-byte trait block."""
    return tuple(Trait(i, code) for i, code in enumerate(raw[:SLOTS]) if code)
