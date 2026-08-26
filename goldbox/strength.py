"""Party strength: the number random encounters are sized from.

`PARTYSTRENGTH` is ECL opcode `$1D`, implemented at `DUNGEON $1BE8`. Twelve of
the thirty area scripts call it, and in every one of those the value becomes --
after a divide, and sometimes a random reduction -- the count operand of
`LOADMON`: literally how many monsters are placed in the fight. The slums use
`(strength / 3) * 2`.

Nothing stores it. The routine walks the eight roster slots on every call and
writes only to the ECL variable its operand names, which is why this module
recomputes rather than reads a byte. See `docs/114-party-strength.md`.

**The biased fields are used as stored, not as decoded.** The THAC0 and armour
class fields hold `60 - value`, and the routine subtracts its own constant from
the byte: 39 from THAC0, 60 from armour class. `RosterBlock.thac0` would hand
back the number on the character sheet, which is the wrong end of the encoding
for arithmetic the game does in the stored space.

No Qt and no transport: `from_bytes` takes the two blocks a save file or a live
read both produce, and `read_live` takes anything with a `read(address, length)`.
"""

from __future__ import annotations

from dataclasses import dataclass

from .layout import NAME_SIZE
from .petscii import decode_record_name
from .savegame import (
    HEADER_SIZE,
    ROSTER_ARMOUR_CLASS,
    ROSTER_COUNT,
    ROSTER_STRIDE,
    ROSTER_THAC0,
    SAVE0_LOAD_ADDRESS,
    SAVE0_SIZE,
    SAVE1_LOAD_ADDRESS,
    SLOT_STRIDE,
    SaveGame0,
    SaveGame1,
)

#: Roster `+0x00`, the byte the routine tests before it does anything else:
#: zero for an empty slot, bit 7 for a dead one (`$01` -> `$84` was seen going
#: in on death). `$1BF6 BEQ / BMI` -- **a dead character stops counting**, so a
#: party that loses somebody meets smaller encounters until it raises them.
ROSTER_STATUS = 0x00
STATUS_DEAD = 0x80

#: Record offsets. Hit points **maximum**, not current: wounds do not shrink a
#: Pool of Radiance encounter, though Curse of the Azure Bonds' version of the
#: same routine reads current and they do there.
RECORD_HP_MAX = 0x076
RECORD_LEVEL = 0x0A0
RECORD_CLASS_BITS = 0x0EB

CLASS_MAGIC_USER = 0x01
CLASS_CLERIC = 0x02

#: What the routine subtracts from each biased field. THAC0's subtraction at
#: `$1C01` has **no underflow guard**; armour class's at `$1C16` has one
#: (`BCC`), which is why only the second has a floor here.
THAC0_OFFSET = 39
ARMOUR_FLOOR = 60

THAC0_WEIGHT = 5
ARMOUR_WEIGHT = 5
CLERIC_WEIGHT = 4
MAGIC_USER_WEIGHT = 8

#: `$1C51`: the 16-bit sum, divided once at the end. CoAB divides per character
#: instead, so with six characters this is systematically the larger by up to 5.
DIVISOR = 10

ROSTER_PAGE = ROSTER_COUNT * ROSTER_STRIDE


@dataclass(frozen=True)
class Contribution:
    """One roster slot's share of the sum, term by term.

    The breakdown is the useful part: a total of 130 says nothing about what to
    change, and "MALCYON 27" beside "BRUTUS 26" says the wizard is pulling as
    hard as the fighter.
    """

    slot: int
    name: str
    thac0_term: int
    hp_term: int
    armour_term: int
    cleric_term: int
    magic_user_term: int
    #: The fields as stored, for anyone checking the arithmetic against memory.
    thac0_field: int = 0
    armour_field: int = 0
    level: int = 0
    #: The THAC0 subtraction wrapped: a current THAC0 worse than 21, which the
    #: routine turns into a number near 255 and then multiplies by five.
    wrapped: bool = False

    @property
    def total(self) -> int:
        return (self.thac0_term + self.hp_term + self.armour_term
                + self.cleric_term + self.magic_user_term)

    @property
    def thac0(self) -> int:
        """The number on the character sheet, for display only."""
        return 60 - self.thac0_field

    @property
    def armour_class(self) -> int:
        return 60 - self.armour_field

    @property
    def terms(self) -> tuple[tuple[str, int], ...]:
        """The named terms that are not zero, in the routine's own order."""
        named = (("THAC0", self.thac0_term), ("hp max", self.hp_term),
                 ("AC", self.armour_term), ("cleric", self.cleric_term),
                 ("magic-user", self.magic_user_term))
        return tuple((label, value) for label, value in named if value)

    @property
    def line(self) -> str:
        sums = " + ".join(f"{value} {label}" for label, value in self.terms)
        text = f"{self.name} {self.total}" + (f" = {sums}" if sums else "")
        return text + ("   (THAC0 field wrapped)" if self.wrapped else "")


@dataclass(frozen=True)
class PartyStrength:
    """What `PARTYSTRENGTH` would return right now, and where it came from."""

    parts: tuple[Contribution, ...]

    @property
    def total(self) -> int:
        """The 16-bit sum, before the divide."""
        return sum(p.total for p in self.parts) & 0xFFFF

    @property
    def value(self) -> int:
        return self.total // DIVISOR

    def __int__(self) -> int:
        return self.value

    @property
    def slums_count(self) -> int:
        """Monsters in a slums random encounter: `ECL14`'s `(s / 3) * 2`.

        The one scaled count that has been watched end to end, and the reason
        the number is worth showing at all.
        """
        return (self.value // 3) * 2

    @property
    def detail(self) -> str:
        """The per-character breakdown, one line each, for a tooltip."""
        head = (f"party strength {self.value}   "
                f"= {self.total} / {DIVISOR}, summed over "
                f"{len(self.parts)} living character"
                f"{'s' if len(self.parts) != 1 else ''}")
        return "\n".join([head] + [f"  {p.line}" for p in self.parts])


def _contribution(slot: int, window: bytes, block: bytes) -> Contribution:
    thac0_field = block[ROSTER_THAC0]
    # 8-bit SBC, unguarded. A cursed weapon is the plausible route to a THAC0
    # worse than 21, and the wrap adds well over a thousand to the sum.
    stepped = (thac0_field - THAC0_OFFSET) & 0xFF
    armour_field = block[ROSTER_ARMOUR_CLASS]
    level = window[RECORD_LEVEL]
    bits = window[RECORD_CLASS_BITS]
    return Contribution(
        slot=slot,
        name=decode_record_name(window[:NAME_SIZE]),
        thac0_term=THAC0_WEIGHT * stepped,
        hp_term=window[RECORD_HP_MAX] | (window[RECORD_HP_MAX + 1] << 8),
        armour_term=(ARMOUR_WEIGHT * (armour_field - ARMOUR_FLOOR)
                     if armour_field >= ARMOUR_FLOOR else 0),
        cleric_term=CLERIC_WEIGHT * level if bits & CLASS_CLERIC else 0,
        magic_user_term=(MAGIC_USER_WEIGHT * level
                         if bits & CLASS_MAGIC_USER else 0),
        thac0_field=thac0_field,
        armour_field=armour_field,
        level=level,
        wrapped=thac0_field < THAC0_OFFSET,
    )


def from_bytes(save0_bytes: bytes, roster_bytes: bytes) -> PartyStrength:
    """From the two blocks the game keeps the party in.

    `save0_bytes` is `$4900`-`$64FF` -- a `SAVEDGAME0` payload, or the live read
    of the same range -- and `roster_bytes` the roster page at `$8300`. Both are
    what `automap/live.py` already reads on every poll.
    """
    if len(save0_bytes) < HEADER_SIZE + ROSTER_COUNT * SLOT_STRIDE:
        raise ValueError(f"save0 block is {len(save0_bytes)} bytes, need "
                         f"{HEADER_SIZE + ROSTER_COUNT * SLOT_STRIDE}")
    if len(roster_bytes) < ROSTER_PAGE:
        raise ValueError(f"roster block is {len(roster_bytes)} bytes, need "
                         f"{ROSTER_PAGE}")
    parts = []
    for slot in range(ROSTER_COUNT):
        block = roster_bytes[slot * ROSTER_STRIDE:(slot + 1) * ROSTER_STRIDE]
        status = block[ROSTER_STATUS]
        if status == 0 or status & STATUS_DEAD:
            continue
        off = HEADER_SIZE + slot * SLOT_STRIDE
        parts.append(_contribution(slot, save0_bytes[off:off + SLOT_STRIDE],
                                   block))
    return PartyStrength(tuple(parts))


def from_saves(save0: SaveGame0, save1) -> PartyStrength:
    """From decoded saves. `save1` may be a `SaveGame1` or the roster bytes."""
    roster = save1.to_bytes() if isinstance(save1, SaveGame1) else bytes(save1)
    return from_bytes(save0.to_bytes(), roster)


def read_live(target) -> PartyStrength:
    """From a running game, through anything with `read(address, length)`.

    `MemoryTarget` in the tests and `ViceTarget` in the window both qualify, and
    neither this module nor `goldbox/` in general knows which it has.
    """
    read_blocks = getattr(target, "read_blocks", None)
    blocks = ((SAVE0_LOAD_ADDRESS, SAVE0_SIZE), (SAVE1_LOAD_ADDRESS, ROSTER_PAGE))
    if read_blocks is not None:
        save0_bytes, roster_bytes = read_blocks(blocks)
    else:
        save0_bytes, roster_bytes = (target.read(addr, size)
                                     for addr, size in blocks)
    return from_bytes(bytes(save0_bytes), bytes(roster_bytes))
