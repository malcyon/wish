"""SAVEDGAME0 / SAVEDGAME1 structure for Pool of Radiance (C64).

`SAVEDGAME0` is a **raw memory image** of $4900-$64FF with no header, no packing
and (so far) no observed checksum. Character records sit in a slot area that
follows a $400-byte header region:

    $4900 .. $4CFF   header / party globals   ($400 bytes)
    $4D00 .. $64FF   character slot area      ($1800 bytes)

**8 slots of $100 (256 bytes)** at $4D00-$54FF:

    $4D00 $4E00 $4F00 $5000 $5100 $5200 $5300 $5400

A slot holds only the **first 256 bytes** of the 580-byte character record --
verified byte-identical against every character's own exported .chr file for a
full six-character party. The rest of the record lives elsewhere: the combat
icon in the shared table at $4BE0 (8 entries of 36 bytes, ending exactly at
$4D00), and items in the region from $5500 which is all zero until something is
bought.

Everything a character sheet needs -- name, abilities, race, class, age, hit
points, saving throws, movement, money -- falls inside those first 256 bytes.

**Earlier this was recorded as 6 slots of $400, which was wrong.** That reading
came from a save holding only two characters, where the bytes between them were
zero and so agreed with a mostly-zero exported record. A full party disproves
it outright. Occupancy is still *detected* per slot, since a slot can hold
leftover bytes from a previous save without holding a live character.

Nothing in this module does disk I/O; it takes and returns bytes.
"""

from __future__ import annotations

from dataclasses import dataclass

# split/attach_load_address are the *generic* PRG helpers; record.py's variants
# are record-specific and validate a 582-byte length.
from .d64 import attach_load_address, split_load_address
from .record import CharacterRecord, RECORD_SIZE

SAVE0_LOAD_ADDRESS = 0x4900
SAVE0_SIZE = 0x1C00

SAVE1_LOAD_ADDRESS = 0x8300
SAVE1_SIZE = 0x0800

# The first page of SAVEDGAME1 is a per-character roster: 8 blocks of $20,
# filling $8300-$83FF exactly. $8400 begins a jump table (4C xx 84), which is
# what bounds the area -- there is no ninth block.
ROSTER_STRIDE = 0x20
ROSTER_COUNT = 8
ROSTER_AREA_END = SAVE1_LOAD_ADDRESS + ROSTER_COUNT * ROSTER_STRIDE   # $8400

# Offsets within one roster block.
ROSTER_SPELLS = 0x03          # three bytes: spells memorised at levels 1, 2, 3
ROSTER_SPELL_LEVELS = 3
ROSTER_SLOT_INDEX = 0x0D
ROSTER_THAC0 = 0x0E
ROSTER_ARMOUR_CLASS = 0x0F
ROSTER_ARMOUR_BONUS = 0x10
ROSTER_ENCUMBERED = 0x11      # 1 when armour has cut the movement rate
ROSTER_EQUIPMENT = 0x15       # rises with what is readied; see docs
ROSTER_DAMAGE_BONUS = 0x17
ROSTER_HP_CURRENT = 0x19
ROSTER_MOVEMENT = 0x1B

# THAC0 and armour class are both stored as (60 - value): lower armour class is
# better, and the game keeps the byte rising as the character improves.
COMBAT_BIAS = 60
ARMOUR_BIAS = 48              # armour bonus is stored as 48 + bonus

HEADER_SIZE = 0x400
SLOT_AREA_BASE = SAVE0_LOAD_ADDRESS + HEADER_SIZE   # $4D00
SLOT_STRIDE = 0x100
SLOT_COUNT = 8
SLOT_AREA_END = SLOT_AREA_BASE + SLOT_COUNT * SLOT_STRIDE   # $5500

# Where the party is standing. All in the SAVEDGAME0 header, established by
# walking a known number of steps in known directions and diffing:
# three steps north moved PARTY_Y by exactly 3 and left PARTY_X alone, three
# steps west did the reverse, and turning on the spot moved only PARTY_FACING.
PARTY_X = 0x49C0
PARTY_Y = 0x49C1
PARTY_FACING = 0x49C2
PARTY_PREV_X = 0x49F0          # the square occupied before the last move
PARTY_PREV_Y = 0x49F1
PARTY_CLOCK = 0x49C7           # three decimal digits, least significant first

NORTH, EAST, SOUTH, WEST = 0, 1, 2, 3
FACINGS = {NORTH: "north", EAST: "east", SOUTH: "south", WEST: "west"}
# y decreases going north, x increases going east.
FACING_STEP = {NORTH: (0, -1), EAST: (1, 0), SOUTH: (0, 1), WEST: (-1, 0)}

ICON_TABLE_BASE = 0x4BE0        # 8 combat icons of 36 bytes, ending at $4D00
ICON_SIZE = 0x24

# Items live at $5900, not immediately after the slots -- see por/items.py.
# $5500-$58FF stays zero even with a fully equipped party; purpose unknown.
ITEM_AREA_BASE = 0x5900


class SaveGameError(ValueError):
    """Raised when save data is not the size or shape we expect."""


@dataclass(frozen=True)
class Slot:
    """One character slot window within the slot area."""

    index: int
    address: int
    window: bytes          # the full $400 window
    occupied: bool

    @property
    def record_bytes(self) -> bytes:
        """The 256 bytes this slot stores -- the head of the 580-byte record."""
        return self.window

    @property
    def record(self) -> CharacterRecord | None:
        """Decode the slot, zero-padded out to a full record.

        Only the first 256 bytes are real; anything the layout places beyond
        that (items, the combat icon) is not stored per-slot and reads as zero.
        Write-back only ever touches the stored 256, so the padding is inert.
        """
        if not self.occupied:
            return None
        return CharacterRecord.from_bytes(
            self.window + bytes(RECORD_SIZE - len(self.window)))

    def __repr__(self) -> str:
        if not self.occupied:
            return f"<Slot {self.index} ${self.address:04X} empty>"
        return f"<Slot {self.index} ${self.address:04X} {self.record.name!r}>"


def looks_occupied(window: bytes) -> bool:
    """Heuristic: does this window hold a character record?

    Deliberately conservative -- a name whose first byte is a printable ASCII
    letter, plus six ability scores in the AD&D 1st edition range (3..25, which
    allows for magically raised scores). Kept in one place so the discovery
    scripts and the editor agree on what "occupied" means.
    """
    if len(window) < SLOT_STRIDE:
        return False
    first = window[0]
    if not (0x41 <= first <= 0x5A):        # 'A'-'Z'
        return False
    return all(3 <= b <= 25 for b in window[0x14:0x1A])


class PartyPosition:
    """Where the party is standing, as a live view on a SaveGame0.

    Writes go straight through, so nothing else in the header is disturbed.
    Reading is confirmed; **writing has never been loaded in the game**, and a
    position the game did not put there may well be somewhere it cannot cope
    with -- inside a wall, or off the edge of a map whose dimensions we do not
    know.
    """

    def __init__(self, data: bytearray):
        self._data = data

    def _get(self, addr: int) -> int:
        return self._data[addr - SAVE0_LOAD_ADDRESS]

    def _set(self, addr: int, value: int) -> None:
        if not 0 <= value <= 0xFF:
            raise SaveGameError(f"${addr:04X}: {value} does not fit in a byte")
        self._data[addr - SAVE0_LOAD_ADDRESS] = value

    @property
    def x(self) -> int:
        return self._get(PARTY_X)

    @x.setter
    def x(self, value: int) -> None:
        self._set(PARTY_X, value)

    @property
    def y(self) -> int:
        return self._get(PARTY_Y)

    @y.setter
    def y(self, value: int) -> None:
        self._set(PARTY_Y, value)

    @property
    def facing(self) -> int:
        return self._get(PARTY_FACING)

    @facing.setter
    def facing(self, value) -> None:
        if isinstance(value, str):
            lookup = {name: code for code, name in FACINGS.items()}
            if value.lower() not in lookup:
                raise SaveGameError(
                    f"facing must be one of {sorted(lookup)}, got {value!r}")
            value = lookup[value.lower()]
        if value not in FACINGS:
            raise SaveGameError(f"facing must be 0-3, got {value}")
        self._set(PARTY_FACING, value)

    @property
    def facing_name(self) -> str:
        return FACINGS.get(self.facing, str(self.facing))

    @property
    def previous(self) -> tuple[int, int]:
        """The square the party occupied before its last move."""
        return self._get(PARTY_PREV_X), self._get(PARTY_PREV_Y)

    @property
    def clock(self) -> int:
        """A counter that rises with everything the party does, stored as three
        decimal digits least significant first. Units unknown."""
        return (self._get(PARTY_CLOCK)
                + self._get(PARTY_CLOCK + 1) * 10
                + self._get(PARTY_CLOCK + 2) * 100)

    def __repr__(self) -> str:
        return (f"<PartyPosition ({self.x},{self.y}) facing {self.facing_name}"
                f" clock {self.clock}>")


class SaveGame0:
    """The party save: header region plus the character slot area."""

    def __init__(self, payload: bytes):
        if len(payload) != SAVE0_SIZE:
            raise SaveGameError(
                f"SAVEDGAME0 payload must be {SAVE0_SIZE} bytes, got {len(payload)}"
            )
        self._data = bytearray(payload)

    @property
    def party(self) -> PartyPosition:
        """Where the party is standing."""
        return PartyPosition(self._data)

    # -- construction -----------------------------------------------------
    @classmethod
    def from_bytes(cls, payload: bytes) -> "SaveGame0":
        return cls(payload)

    @classmethod
    def from_prg(cls, data: bytes) -> "SaveGame0":
        load, payload = split_load_address(data)
        if load != SAVE0_LOAD_ADDRESS:
            raise SaveGameError(
                f"expected load address ${SAVE0_LOAD_ADDRESS:04X}, got ${load:04X}"
            )
        return cls(payload)

    # -- serialisation ----------------------------------------------------
    def to_bytes(self) -> bytes:
        return bytes(self._data)

    def to_prg(self) -> bytes:
        return attach_load_address(SAVE0_LOAD_ADDRESS, bytes(self._data))

    def __bytes__(self) -> bytes:
        return self.to_bytes()

    # -- regions ----------------------------------------------------------
    @property
    def header(self) -> bytes:
        """$4900-$4CFF. Contents not yet understood; preserved verbatim."""
        return bytes(self._data[:HEADER_SIZE])

    def _window_offset(self, index: int) -> int:
        if not 0 <= index < SLOT_COUNT:
            raise IndexError(f"slot index {index} out of range 0..{SLOT_COUNT - 1}")
        return HEADER_SIZE + index * SLOT_STRIDE

    def slot(self, index: int) -> Slot:
        off = self._window_offset(index)
        window = bytes(self._data[off:off + SLOT_STRIDE])
        return Slot(
            index=index,
            address=SLOT_AREA_BASE + index * SLOT_STRIDE,
            window=window,
            occupied=looks_occupied(window),
        )

    @property
    def slots(self) -> list[Slot]:
        return [self.slot(i) for i in range(SLOT_COUNT)]

    @property
    def characters(self) -> list[Slot]:
        return [s for s in self.slots if s.occupied]

    # -- mutation ---------------------------------------------------------
    def write_record(self, index: int, record: CharacterRecord | bytes) -> None:
        """Write a record into a slot -- only the 256 bytes the slot stores.

        Accepts a full 580-byte record and keeps its head; bytes past 256 are
        not stored per-slot and are silently dropped rather than corrupting the
        next slot. Everything else -- the header, the icon table, other slots --
        is left untouched.
        """
        raw = record.to_bytes() if isinstance(record, CharacterRecord) else bytes(record)
        if len(raw) not in (SLOT_STRIDE, RECORD_SIZE):
            raise SaveGameError(
                f"expected {SLOT_STRIDE} or {RECORD_SIZE} bytes, got {len(raw)}")
        off = self._window_offset(index)
        self._data[off:off + SLOT_STRIDE] = raw[:SLOT_STRIDE]

    # -- reporting --------------------------------------------------------
    def summary(self) -> str:
        lines = [
            f"SAVEDGAME0  ${SAVE0_LOAD_ADDRESS:04X}-"
            f"${SAVE0_LOAD_ADDRESS + SAVE0_SIZE - 1:04X}  ({SAVE0_SIZE} bytes)",
            f"  header  ${SAVE0_LOAD_ADDRESS:04X}-${SLOT_AREA_BASE - 1:04X}"
            f"  ({sum(1 for b in self.header if b)} non-zero of {HEADER_SIZE})",
            f"  slots   {SLOT_COUNT} x ${SLOT_STRIDE:04X} from ${SLOT_AREA_BASE:04X}"
            f"  (record head only)",
        ]
        for s in self.slots:
            if s.occupied:
                r = s.record
                lines.append(
                    f"    {s.index}  ${s.address:04X}  {r.name:<16s}"
                    f"  STR {r.strength}/{r.exceptional_strength:02d}"
                    f"  INT {r.intelligence} WIS {r.wisdom} DEX {r.dexterity}"
                    f"  CON {r.constitution} CHA {r.charisma}"
                )
            else:
                nz = sum(1 for b in s.window if b)
                lines.append(
                    f"    {s.index}  ${s.address:04X}  -empty-"
                    + (f"  ({nz} non-zero bytes!)" if nz else "")
                )
        return "\n".join(lines)


class RosterBlock:
    """One 32-byte party-roster entry, seen as a live view on its save.

    Writes go straight through to the parent `SaveGame1`, so bytes this class
    does not understand -- nineteen of the thirty-two -- are never disturbed.

    This is where the game caches what it *derives*. Armour class and THAC0 are
    recomputed when equipment changes and never when an ability score changes,
    which is why editing dexterity alone leaves a character's combat numbers
    stale. See docs/30-savegame-layout.md.
    """

    def __init__(self, data: bytearray, index: int):
        self._data = data
        self._index = index
        self._base = index * ROSTER_STRIDE

    # -- identity ---------------------------------------------------------
    @property
    def index(self) -> int:
        return self._index

    @property
    def address(self) -> int:
        return SAVE1_LOAD_ADDRESS + self._base

    @property
    def raw(self) -> bytes:
        return bytes(self._data[self._base:self._base + ROSTER_STRIDE])

    @property
    def occupied(self) -> bool:
        """An unused block is all zero. No live character has a zero block:
        movement alone is never 0."""
        return any(self.raw)

    @property
    def slot_index(self) -> int:
        """Which SAVEDGAME0 slot this block describes. Always equals `index`
        in every save seen, but the game stores it, so we read it."""
        return self._data[self._base + ROSTER_SLOT_INDEX]

    # -- byte access ------------------------------------------------------
    def _get(self, offset: int) -> int:
        return self._data[self._base + offset]

    def _set(self, offset: int, value: int) -> None:
        if not 0 <= value <= 0xFF:
            raise SaveGameError(f"roster byte +0x{offset:02X} out of range: {value}")
        self._data[self._base + offset] = value

    @staticmethod
    def _biased(value: int, bias: int, what: str) -> int:
        stored = bias - value
        if not 0 <= stored <= 0xFF:
            raise SaveGameError(
                f"{what} {value} does not fit: stored as {bias} - {value}, "
                f"which must be 0..255")
        return stored

    # -- the fields -------------------------------------------------------
    @property
    def thac0(self) -> int:
        return COMBAT_BIAS - self._get(ROSTER_THAC0)

    @thac0.setter
    def thac0(self, value: int) -> None:
        self._set(ROSTER_THAC0, self._biased(value, COMBAT_BIAS, "THAC0"))

    @property
    def armour_class(self) -> int:
        return COMBAT_BIAS - self._get(ROSTER_ARMOUR_CLASS)

    @armour_class.setter
    def armour_class(self, value: int) -> None:
        self._set(ROSTER_ARMOUR_CLASS,
                  self._biased(value, COMBAT_BIAS, "armour class"))

    @property
    def armour_bonus(self) -> int:
        """Armour's own contribution, shield excluded. Read only -- the game
        derives it from equipment and nothing is known about writing it."""
        return self._get(ROSTER_ARMOUR_BONUS) - ARMOUR_BIAS

    @property
    def damage_bonus(self) -> int:
        """Strength damage bonus plus the readied weapon's own bonus.

        Matches the AD&D 1st edition table on all twelve characters of the
        unarmoured/armoured pair -- including ROLAND, whose single change from
        0 to 1 is explained entirely by readying a mace, which does 1d6+1.
        """
        return self._get(ROSTER_DAMAGE_BONUS)

    @damage_bonus.setter
    def damage_bonus(self, value: int) -> None:
        self._set(ROSTER_DAMAGE_BONUS, value)

    @property
    def encumbered(self) -> bool:
        """True when armour has reduced the movement rate."""
        return bool(self._get(ROSTER_ENCUMBERED))

    @property
    def hit_points(self) -> int:
        return self._get(ROSTER_HP_CURRENT)

    @hit_points.setter
    def hit_points(self, value: int) -> None:
        self._set(ROSTER_HP_CURRENT, value)

    @property
    def movement(self) -> int:
        return self._get(ROSTER_MOVEMENT)

    @movement.setter
    def movement(self, value: int) -> None:
        self._set(ROSTER_MOVEMENT, value)

    @property
    def spells_memorised(self) -> tuple[int, ...]:
        """How many spells are memorised at levels 1, 2 and 3. Pool of Radiance
        casts no higher; the bytes above are zero in every specimen."""
        b = self._base + ROSTER_SPELLS
        return tuple(self._data[b:b + ROSTER_SPELL_LEVELS])

    @spells_memorised.setter
    def spells_memorised(self, counts) -> None:
        counts = list(counts)
        if len(counts) != ROSTER_SPELL_LEVELS:
            raise SaveGameError(
                f"spells_memorised needs {ROSTER_SPELL_LEVELS} counts, "
                f"got {len(counts)}")
        for level, n in enumerate(counts, start=1):
            if not 0 <= int(n) <= 0xFF:
                raise SaveGameError(
                    f"level {level} spell count out of range: {n}")
        b = self._base + ROSTER_SPELLS
        self._data[b:b + ROSTER_SPELL_LEVELS] = bytes(int(n) for n in counts)

    def __repr__(self) -> str:
        if not self.occupied:
            return f"<RosterBlock {self.index} ${self.address:04X} empty>"
        return (f"<RosterBlock {self.index} ${self.address:04X} "
                f"AC {self.armour_class} THAC0 {self.thac0} "
                f"HP {self.hit_points}>")


class SaveGame1:
    """$8300-$8AFF.

    The first page is the party roster -- eight 32-byte blocks holding the
    combat numbers the character record does not: armour class, THAC0, current
    hit points, movement and the memorised spell counts. Everything from $8400
    on is still opaque, and is carried through a load/save cycle untouched.
    """

    def __init__(self, payload: bytes):
        if len(payload) != SAVE1_SIZE:
            raise SaveGameError(
                f"SAVEDGAME1 payload must be {SAVE1_SIZE} bytes, got {len(payload)}"
            )
        self._data = bytearray(payload)

    # -- the roster -------------------------------------------------------
    def roster(self, index: int) -> RosterBlock:
        if not 0 <= index < ROSTER_COUNT:
            raise IndexError(f"roster index {index} out of range 0..{ROSTER_COUNT - 1}")
        return RosterBlock(self._data, index)

    @property
    def roster_blocks(self) -> list[RosterBlock]:
        return [self.roster(i) for i in range(ROSTER_COUNT)]

    @classmethod
    def from_prg(cls, data: bytes) -> "SaveGame1":
        load, payload = split_load_address(data)
        if load != SAVE1_LOAD_ADDRESS:
            raise SaveGameError(
                f"expected load address ${SAVE1_LOAD_ADDRESS:04X}, got ${load:04X}"
            )
        return cls(payload)

    def to_bytes(self) -> bytes:
        return bytes(self._data)

    def to_prg(self) -> bytes:
        return attach_load_address(SAVE1_LOAD_ADDRESS, bytes(self._data))

    def __bytes__(self) -> bytes:
        return self.to_bytes()
