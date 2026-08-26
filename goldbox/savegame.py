"""The save container: Pool of Radiance's two files, and the family's one.

Which title a save belongs to is a `goldbox.games.Game`, passed to every class here
and defaulting to Pool of Radiance so that callers written before there was a
second game keep working. The constants below are Pool of Radiance's and stay
for those callers; anything that must work on Curse reads the `Game`.


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
$4D00), and items in the area from $5900, one $100 block per slot (see
goldbox/items.py).

**There are twelve record slots, not eight.** `LIBRARY $312B` computes both
`$4D00 + n*$100` and `$5900 + n*$100`, and the arithmetic only closes at twelve:
records run $4D00-$58FF and items $5900-$64FF, which is exactly where SAVEDGAME0
ends. So $5500 is **slot 8** -- long described here as a "staging page" because
it held the last record the game loaded, which was the encountered monster after
a fight. It was a combatant occupying a real slot. $5600-$58FF are slots 9, 10
and 11, and read zero only because our saves have never used them.

`SLOT_COUNT` stays 8 deliberately: that is the *party*, which the game enforces
at six player characters and eight total. Slots 8-11 are combat scratch and must
never appear in a party list.

Everything a character sheet needs -- name, abilities, race, class, age, hit
points, saving throws, movement, money -- falls inside those first 256 bytes.

**Earlier this was recorded as 6 slots of $400, which was wrong.** That reading
came from a save holding only two characters, where the bytes between them were
zero and so agreed with a mostly-zero exported record. A full party disproves
it outright. Occupancy is still *detected* per slot, since a slot can hold
leftover bytes from a previous save without holding a live character.

`load_save` and `store_save` are the only things here that touch a D64;
everything else takes and returns bytes.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import encoding as _enc
from . import games as _games

# split/attach_load_address are the *generic* PRG helpers; record.py's variants
# are record-specific and validate a 582-byte length.
from .d64 import attach_load_address, split_load_address
from .games import Game
from .record import RECORD_SIZE, CharacterRecord

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
# Three bytes whose meaning is NOT established. They were read as the number of
# spells memorised at levels 1, 2 and 3 -- which matches npc_party.d64 level by
# level, and PORSAVE11 too, and is contradicted by PORSAVE4, where they read
# 0/0/0 for a party with five spells memorised. That contradicting page is stale
# (PORSAVE2-PORSAVE9 share one byte-identical roster), which weakens the
# retraction without settling it. See docs/30-savegame-layout.md; the bytes are
# carried through a round trip rather than interpreted.
ROSTER_UNKNOWN_03 = 0x03
ROSTER_UNKNOWN_03_LEN = 3
ROSTER_SLOT_INDEX = 0x0D
ROSTER_THAC0 = 0x0E
ROSTER_ARMOUR_CLASS = 0x0F
ROSTER_ARMOUR_BONUS = 0x10

# +0x11 to +0x18 are the **current attack form**: the running copy of the
# record's attack_forms block at 0x0D9, in the engine's own order -- two attack
# counts, two dice counts, two die sizes, two damage bonuses, primary first in
# each pair. The DOS record spells the same eight bytes out at 0x113-0x11A as
# ATK_1/2_Count/Rolls/Dice/Modifier_Current, and a DOS Pool of Radiance party
# on this machine reads `00 00 01 00 02 00 03 00` for an unarmed character,
# which is the same shape a C64 roster block holds.
#
# The die size at +0x15 was called EQUIPMENT here, because it "rises with what
# is readied". It does, and this is why: across thirteen of Donald's save disks
# it reads 3 for MALCYON's dart, 6 for LADY KATHERINE's short sword, 6 for
# ROLAND's mace, 8 for three long swords and 2 for everyone with nothing
# readied -- 1d3, 1d6, 1d6+1, 1d8 and the unarmed 1d2, each matching the ITEMS
# entry for the item that character had equipped.
ROSTER_ATTACKS = 0x11         # primary; +0x12 is the secondary form
ROSTER_DAMAGE_DICE = 0x13     # how many dice
ROSTER_DAMAGE_DIE = 0x15      # how many sides -- was ROSTER_EQUIPMENT
ROSTER_DAMAGE_BONUS = 0x17
ROSTER_ATTACK_FORMS = 2       # the pairs are primary, secondary
ROSTER_HP_CURRENT = 0x19
ROSTER_MOVEMENT = 0x1B

# THAC0 and armour class are both stored as (60 - value): lower armour class is
# better, and the game keeps the byte rising as the character improves.
# Re-exported from goldbox/encoding.py, which is now the one place these live.
COMBAT_BIAS = _enc.COMBAT_BIAS
ARMOUR_BIAS = _enc.ARMOUR_BONUS_BIAS

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
PARTY_CLOCK = 0x49C7           # game time in minutes, 3 digits

NORTH, EAST, SOUTH, WEST = 0, 1, 2, 3
FACINGS = {NORTH: "north", EAST: "east", SOUTH: "south", WEST: "west"}
# y decreases going north, x increases going east.
FACING_STEP = {NORTH: (0, -1), EAST: (1, 0), SOUTH: (0, 1), WEST: (-1, 0)}

# The loader's "what is currently loaded" cache, 25 entries, saved verbatim.
# LIBRARY $4225 is the universal "ensure file number A of type X is loaded" and
# keeps this at $6E13,X in a running game; CAMP $0D00 copies all 25 into the
# header when saving, and GEN $25DE copies them back on load with bit 7 set to
# force a reload. **Bit 7 is that dirty marker, not data** -- mask it off.
LOADED_FILES = 0x4BC0
LOADED_FILE_COUNT = 25
LOADED_DIRTY = 0x80

# Which of the 29 GEO maps the party is standing on. This is the answer to the
# question that stood open longest: a scan once reported no such field, but every
# save then held was in New Phlan, so it had no negative example to find one
# against. All ten read 0 -- GEO00, New Phlan, agreeing with the independent
# wall-match -- and the one foreign save reads 13, a fully roofed dungeon.
AREA = 0x4BC2

ICON_TABLE_BASE = 0x4BE0        # 8 combat icons of 36 bytes, ending at $4D00
ICON_SIZE = 0x24

# The party is 8 slots; the slot *array* is 12. Combat fills 8-11, which is why
# a monster's record turns up at $5500 after a fight.
RECORD_SLOT_COUNT = 12
COMBAT_SLOT_BASE = 0x5500          # slot 8; was called STAGING_PAGE_BASE
STAGING_PAGE_BASE = COMBAT_SLOT_BASE   # old name, kept so callers do not break

# Items live at $5900, immediately after the twelfth slot -- see goldbox/items.py.
ITEM_AREA_BASE = 0x5900


class SaveGameError(ValueError):
    """Raised when save data is not the size or shape we expect."""


@dataclass(frozen=True)
class Slot:
    """One character slot window within the slot area."""

    index: int
    address: int
    window: bytes          # the $100 the slot stores
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
        return CharacterRecord(
            self.window + bytes(RECORD_SIZE - len(self.window)),
            stored_size=len(self.window))

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

    def __init__(self, data: bytearray, game: Game = _games.DEFAULT):
        self._data = data
        self._game = game

    # The constants above are Pool of Radiance's *addresses*; subtracting its
    # load address turns each into the payload offset, which is the same number
    # in every title of the family. Only the base moves.
    def _get(self, addr: int) -> int:
        return self._data[addr - SAVE0_LOAD_ADDRESS]

    def _set(self, addr: int, value: int) -> None:
        if not 0 <= value <= 0xFF:
            live = self._game.save_load_address + addr - SAVE0_LOAD_ADDRESS
            raise SaveGameError(f"${live:04X}: {value} does not fit in a byte")
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
    def clock(self) -> tuple[int, int]:
        """The time of day as `(hour, minute)`.

        Three bytes: units of a minute, tens of a minute, then the **hour**.
        `DUNGEON $09F7` prints `$49C9`, a colon, `$49C8`, `$49C7`, so the
        display is HH:MM and the top byte was never a hundreds digit.

        This was read as "minutes, three decimal digits" for a while and the
        arithmetic looked sound, because 637 through 649 across PORSAVE4 to
        PORSAVE9 is a believable count either way. PORSAVE11 gave it away: 1647
        "minutes" is 27:27, an impossible time, where the real reading is a
        plain 16:47. PORSAVE12 and 13 are 16:58 and 16:59 -- one minute apart
        across one step, which is exactly right.
        """
        return (self._get(PARTY_CLOCK + 2),
                self._get(PARTY_CLOCK + 1) * 10 + self._get(PARTY_CLOCK))

    @property
    def clock_text(self) -> str:
        hour, minute = self.clock
        return f"{hour}:{minute:02d}"

    def __repr__(self) -> str:
        return (f"<PartyPosition ({self.x},{self.y}) facing {self.facing_name}"
                f" clock {self.clock_text}>")


class SaveGame0:
    """The party save: header region plus the character slot area.

    In Pool of Radiance this is the whole of `SAVEDGAME0`. In every later title
    it is the whole of the single save file, roster page included -- the roster
    is reached through `SaveGame1`, not through here.
    """

    def __init__(self, payload: bytes, game: Game = _games.DEFAULT):
        if len(payload) != game.save_size:
            raise SaveGameError(
                f"{game.save_file.decode()} payload must be {game.save_size} "
                f"bytes, got {len(payload)}"
            )
        self._data = bytearray(payload)
        self.game = game

    @property
    def area(self) -> int:
        """The GEO map number the party is on, with the dirty bit masked off."""
        return self._data[AREA - SAVE0_LOAD_ADDRESS] & ~LOADED_DIRTY & 0xFF

    @property
    def area_file(self) -> str:
        """That number as the GEO filename, e.g. `GEO14` for the slums."""
        return f"GEO{self.area:02X}"

    @property
    def loaded_files(self) -> bytes:
        """All 25 cache entries, dirty bits masked off."""
        base = LOADED_FILES - SAVE0_LOAD_ADDRESS
        return bytes(b & ~LOADED_DIRTY & 0xFF
                     for b in self._data[base:base + LOADED_FILE_COUNT])

    @property
    def party(self) -> PartyPosition:
        """Where the party is standing."""
        return PartyPosition(self._data, self.game)

    # -- construction -----------------------------------------------------
    @classmethod
    def from_bytes(cls, payload: bytes,
                   game: Game = _games.DEFAULT) -> "SaveGame0":
        return cls(payload, game)

    @classmethod
    def from_prg(cls, data: bytes, game: Game = _games.DEFAULT) -> "SaveGame0":
        load, payload = split_load_address(data)
        if load != game.save_load_address:
            raise SaveGameError(
                f"expected load address ${game.save_load_address:04X}, "
                f"got ${load:04X}"
            )
        return cls(payload, game)

    # -- serialisation ----------------------------------------------------
    def to_bytes(self) -> bytes:
        return bytes(self._data)

    def to_prg(self) -> bytes:
        return attach_load_address(self.game.save_load_address, bytes(self._data))

    def __bytes__(self) -> bytes:
        return self.to_bytes()

    # -- regions ----------------------------------------------------------
    @property
    def header(self) -> bytes:
        """$4900-$4CFF. Contents not yet understood; preserved verbatim."""
        return bytes(self._data[:HEADER_SIZE])

    def _window_offset(self, index: int) -> int:
        count = self.game.slot_count
        if not 0 <= index < count:
            raise IndexError(f"slot index {index} out of range 0..{count - 1}")
        return HEADER_SIZE + index * SLOT_STRIDE

    def slot(self, index: int) -> Slot:
        off = self._window_offset(index)
        window = bytes(self._data[off:off + SLOT_STRIDE])
        return Slot(
            index=index,
            address=self.game.slot_area_base + index * SLOT_STRIDE,
            window=window,
            occupied=looks_occupied(window),
        )

    @property
    def slots(self) -> list[Slot]:
        return [self.slot(i) for i in range(self.game.slot_count)]

    # -- the roster, for titles that keep it in this payload ---------------
    def roster_page(self) -> bytes:
        """The roster bytes, when this title keeps them here. Else `b""`."""
        if not self.game.roster_in_payload:
            return b""
        at = self.game.roster_offset
        return bytes(self._data[at:at + self.game.roster_size])

    def set_roster_page(self, payload: bytes) -> None:
        if not self.game.roster_in_payload:
            raise SaveGameError(
                f"{self.game.title} keeps its roster in "
                f"{self.game.roster_file.decode()}, not in the save payload")
        if len(payload) != self.game.roster_size:
            raise SaveGameError(
                f"roster page must be {self.game.roster_size} bytes, "
                f"got {len(payload)}")
        at = self.game.roster_offset
        self._data[at:at + self.game.roster_size] = payload

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
        g = self.game
        base, size = g.save_load_address, g.save_size
        lines = [
            f"{g.save_file.decode()}  ${base:04X}-"
            f"${base + size - 1:04X}  ({size} bytes)",
            f"  header  ${base:04X}-${g.slot_area_base - 1:04X}"
            f"  ({sum(1 for b in self.header if b)} non-zero of {HEADER_SIZE})",
            f"  slots   {g.slot_count} x ${SLOT_STRIDE:04X} from "
            f"${g.slot_area_base:04X}  (record head only)",
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
    does not understand -- fourteen of the thirty-two -- are never disturbed.

    This is where the game caches what it *derives*. Armour class and THAC0 are
    recomputed when equipment changes and never when an ability score changes,
    which is why editing dexterity alone leaves a character's combat numbers
    stale. See docs/30-savegame-layout.md.
    """

    def __init__(self, data: bytearray, index: int,
                 game: Game = _games.DEFAULT, offset: int = 0):
        self._data = data
        self._index = index
        self._game = game
        self._offset = offset
        self._base = offset + index * ROSTER_STRIDE

    # -- identity ---------------------------------------------------------
    @property
    def index(self) -> int:
        return self._index

    @property
    def address(self) -> int:
        return self._game.roster_base + self._index * ROSTER_STRIDE

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
        """Which save slot this block describes. Always equals `index`
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
        return _enc.combat_value(self._get(ROSTER_THAC0))

    @thac0.setter
    def thac0(self, value: int) -> None:
        self._set(ROSTER_THAC0, self._biased(value, COMBAT_BIAS, "THAC0"))

    @property
    def armour_class(self) -> int:
        return _enc.combat_value(self._get(ROSTER_ARMOUR_CLASS))

    @armour_class.setter
    def armour_class(self, value: int) -> None:
        self._set(ROSTER_ARMOUR_CLASS,
                  self._biased(value, COMBAT_BIAS, "armour class"))

    @property
    def armour_bonus(self) -> int:
        """Armour's own contribution, shield excluded. Read only -- the game
        derives it from equipment and nothing is known about writing it.

        The DOS record spends the byte at this offset on armour class from
        behind, and the alignment between the two ports is otherwise exact, so
        the temptation to rename this is real. Resist it: 48/50/54 for
        nothing/leather/banded mail are the AD&D armour bonuses 0/2/6 exactly,
        they were measured by putting the armour on, and a shield does not move
        them. Read the same bytes as 60 - AC and they give 12, 10 and 6, two
        worse than each armour's real class and meaning nothing. An alignment
        is a hypothesis; a measurement is evidence.
        """
        return _enc.armour_bonus_value(self._get(ROSTER_ARMOUR_BONUS))

    @property
    def damage_bonus(self) -> int:
        """The primary attack form's damage bonus: strength plus the weapon's.

        Matches the AD&D 1st edition table on all twelve characters of the
        unarmoured/armoured pair -- including ROLAND, whose single change from
        0 to 1 is explained entirely by readying a mace, which does 1d6+1.
        """
        return self._get(ROSTER_DAMAGE_BONUS)

    @damage_bonus.setter
    def damage_bonus(self, value: int) -> None:
        self._set(ROSTER_DAMAGE_BONUS, value)

    @property
    def damage_dice(self) -> int:
        """How many dice the primary attack rolls. 1 for every weapon here."""
        return self._get(ROSTER_DAMAGE_DICE)

    @property
    def damage_die(self) -> int:
        """How many sides the primary attack's damage die has.

        3 for a dart, 6 for a short sword or a mace, 8 for a long sword, 2 for
        an empty hand -- the readied weapon's ITEMS entry, on thirteen save
        disks. This is the byte that used to be called EQUIPMENT.
        """
        return self._get(ROSTER_DAMAGE_DIE)

    @property
    def damage(self) -> str:
        """The primary attack's damage, as `1d8+5`."""
        bonus = self.damage_bonus
        return (f"{self.damage_dice}d{self.damage_die}"
                + (f"+{bonus}" if bonus else ""))

    @property
    def attacks(self) -> int:
        """+0x11, the primary form's attack count. PROBABLE.

        DOS calls it `ATK_1_Count_Current`. MALCYON reads 3 with a dart
        readied, whose ITEMS rate of fire is 6 in halves -- three throws a
        round -- and every character with a melee weapon reads 1. But the same
        characters read 0 in the earlier saves and every DOS record on this
        machine reads 0 for a character holding a two-handed weapon, so
        whether the byte is the rate or what is left of it this round is not
        settled.

        It was read once as "armour has cut the movement rate", because it was
        1 on the six banded-mail wearers and 0 on the leather. It is not that:
        LADY KATHERINE reads 1 in PORSAVE11 in the same leather she read 0 in.
        """
        return self._get(ROSTER_ATTACKS)

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
    def unknown_03_05(self) -> tuple[int, ...]:
        """The three bytes at +0x03-+0x05, whose meaning is not established.

        Exposed so they can be round-tripped and edited, not because we know
        what they do. See `ROSTER_UNKNOWN_03`.
        """
        b = self._base + ROSTER_UNKNOWN_03
        return tuple(self._data[b:b + ROSTER_UNKNOWN_03_LEN])

    @unknown_03_05.setter
    def unknown_03_05(self, values) -> None:
        values = list(values)
        if len(values) != ROSTER_UNKNOWN_03_LEN:
            raise SaveGameError(
                f"unknown_03_05 needs {ROSTER_UNKNOWN_03_LEN} bytes, "
                f"got {len(values)}")
        for offset, n in enumerate(values):
            if not 0 <= int(n) <= 0xFF:
                raise SaveGameError(
                    f"roster byte +0x{ROSTER_UNKNOWN_03 + offset:02X} out of "
                    f"range: {n}")
        b = self._base + ROSTER_UNKNOWN_03
        self._data[b:b + ROSTER_UNKNOWN_03_LEN] = bytes(int(n) for n in values)

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
    hit points, movement and the damage bonus. Everything from $8400 on is
    still opaque, and is carried through a load/save cycle untouched.
    """

    def __init__(self, payload: bytes, game: Game = _games.DEFAULT):
        if len(payload) != game.roster_size:
            raise SaveGameError(
                f"roster payload must be {game.roster_size} bytes, "
                f"got {len(payload)}"
            )
        self._data = bytearray(payload)
        self.game = game

    # -- the roster -------------------------------------------------------
    def roster(self, index: int) -> RosterBlock:
        if not 0 <= index < ROSTER_COUNT:
            raise IndexError(f"roster index {index} out of range 0..{ROSTER_COUNT - 1}")
        # `_data` is the roster payload itself in both shapes -- Pool of
        # Radiance's whole SAVEDGAME1, or the single page lifted out of a
        # later title's save -- so blocks always start at 0 within it.
        return RosterBlock(self._data, index, self.game)

    @property
    def roster_blocks(self) -> list[RosterBlock]:
        return [self.roster(i) for i in range(ROSTER_COUNT)]

    @classmethod
    def from_prg(cls, data: bytes, game: Game = _games.DEFAULT) -> "SaveGame1":
        if game.roster_in_payload:
            raise SaveGameError(
                f"{game.title} has no separate roster file; its roster is the "
                f"last page of {game.save_file.decode()}")
        load, payload = split_load_address(data)
        if load != game.roster_load_address:
            raise SaveGameError(
                f"expected load address ${game.roster_load_address:04X}, "
                f"got ${load:04X}"
            )
        return cls(payload, game)

    def to_bytes(self) -> bytes:
        return bytes(self._data)

    def to_prg(self) -> bytes:
        if self.game.roster_in_payload:
            raise SaveGameError(
                f"{self.game.title} has no separate roster file")
        return attach_load_address(self.game.roster_load_address,
                                   bytes(self._data))

    def __bytes__(self) -> bytes:
        return self.to_bytes()


# -- the disk, for the callers that would otherwise name files by hand ------

def load_save(disk, game: Game | None = None):
    """Read a save off a D64 image as `(game, SaveGame0, SaveGame1 | None)`.

    With no `game` the title is identified from the disk's own directory, which
    is what makes opening a Curse save need no argument. The size check is the
    corroborator: Curse's side B carries a 2032-byte `SAVEAZURE` that is a
    truncated demo party, and this refuses it by name rather than decoding
    nonsense.

    `SaveGame1` is None only for Pool of Radiance, and only when the disk
    carries `SAVEDGAME0` alone -- which its own game disks do. Every later
    title keeps the roster inside the save payload, so it is always there.
    """
    if game is None:
        game = _games.detect(disk)
        if game is None:
            known = ", ".join(g.save_file.decode() for g in _games.GAMES)
            raise SaveGameError(
                f"no save file on this disk: looked for {known}")
    prg = disk.read_file(game.save_file)
    if len(prg) != game.save_prg_size:
        raise SaveGameError(
            f"{game.save_file.decode()} here is {len(prg)} bytes, not the "
            f"{game.save_prg_size} a {game.title} save measures")
    sg0 = SaveGame0.from_prg(prg, game)
    if game.roster_in_payload:
        return game, sg0, SaveGame1(sg0.roster_page(), game)
    try:
        sg1 = SaveGame1.from_prg(disk.read_file(game.roster_file), game)
    except Exception:
        sg1 = None
    return game, sg0, sg1


def store_save(disk, sg0: SaveGame0, sg1: "SaveGame1 | None" = None,
               game: Game | None = None) -> None:
    """Write a save back into a D64 image, in place.

    The mirror of `load_save`, and the only place that knows a later title's
    roster has to be folded back into the save payload before it is written.
    """
    game = game or sg0.game
    if game.roster_in_payload:
        if sg1 is not None:
            sg0.set_roster_page(sg1.to_bytes())
        disk.write_file_inplace(game.save_file, sg0.to_prg())
        return
    disk.write_file_inplace(game.save_file, sg0.to_prg())
    if sg1 is not None:
        disk.write_file_inplace(game.roster_file, sg1.to_prg())
