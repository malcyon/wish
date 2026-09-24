"""The active-effect arrays at `SAVEDGAME0` `$4900`, and the spell table that
gives a new one its duration.

Ported out of `automap/live.py` on `#13 (Edit traits and active effects, in
two separate panels)`, because the panels that read and write this belong to
`editor/`, and `editor/` may not import `automap` -- `tests/wish/test_wish.py::
test_editor_imports_nothing_live` is what enforces it. `automap/live.py`
imports these same names back, so `automap/combat.py`, `tools/gui/combatshot.py`,
`tools/gui/livestrip.py` and `tests/c64/test_coldread.py` still resolve them as
`live.EFFECT_ID_OFFSET` and so on.

No Qt and no emulator here, the same rule the rest of `goldbox/` follows --
`load_effect_table` is the one function that touches a disk, and it is bytes
in, bytes out, exactly like `goldbox/items.py`'s `load_item_names`.

**These are not the ten trait slots at record `0x0AD`.** The two meet only at
`LIBRARY $4028` and the `$9AD5` dispatch and share one code namespace
(`goldbox/traits.py`); the active effects here are 64 slots for the *whole
save*, own a character, a monster or the party, and expire. A trait never
does. `docs/133-active-effects.md` is the plan for the two panels this module
feeds.
"""

from __future__ import annotations

from dataclasses import dataclass

from .d64 import D64, load_payload

# The four parallel 64-slot effect arrays. Four arrays and not one table of
# records, so a slot is read across all four at the same index.
#
# **Payload offsets, not addresses**, which is the form that transfers: in Pool
# of Radiance they are $4900, $4940, $4980 and $4B80, and in Curse the same
# four offsets off $4B00. The arrays have only ever been *read* on Pool of
# Radiance (`docs/139` A16) -- what is fixed here is that they follow the save
# image wherever it loads, not that their contents mean the same thing.
EFFECT_ID_OFFSET = 0x000
EFFECT_OWNER_OFFSET = 0x040
EFFECT_DURATION_OFFSET = 0x080
EFFECT_MAGNITUDE_OFFSET = 0x280
EFFECT_SLOTS = 0x40

# Owner encoding: a party member by slot, a monster, or everybody.
#
# **The engine uses both shapes for a spell on the party, and neither can be
# dropped.** Measured in the running game on `#142 (The party effects line is
# computed every poll and shown nowhere)`, two casts on one party:
#
# * **Bless** writes **six rows, one per character**, each owner byte holding
#   that character's own slot. No `0xFF` row at all.
# * **Prayer** writes **one row with owner `0xFF`**, id 35, and nothing per
#   character.
#
# So `0xFF` is CONFIRMED rather than assumed.
FIRST_MONSTER = 8
PARTY_WIDE = 0xFF

# The duration byte: bits 0-5 a count, bits 6-7 the unit the count is in --
# one minute, ten minutes, one hour, one day (`docs/133-active-effects.md`,
# "The duration byte"). A count loses one every time the clock byte one place
# coarser than its own unit ticks: unit 00 with each minute, 01 when the
# minute digit `$49C7` wraps, 10 when the tens-of-minutes digit `$49C8` wraps,
# 11 when the hour `$49C9` wraps.
#
# CONFIRMED for all four units in the running game, each falling by exactly
# the boundaries crossed and by nothing else: a 30-minute rest from 21:16 took
# 30 off unit 00 and 3 off unit 01 (the wraps at :20, :30 and :40) and left
# units 10 and 11 alone; an eight-hour rest from 21:17 across midnight took 8
# off unit 10 and 1 off unit 11 and expired the other two.
#
# **Two bits hold four units and a day is the coarsest**, so nothing is ever
# aged by the clock's month byte `$49CB` and no duration can be expressed in
# months.
#
# A whole byte of zero is skipped by all three ageing routines, so it never
# counts down and never expires -- one such slot kept its id and its zero
# through those same eight hours.
DURATION_COUNT = 0x3F
DURATION_UNIT = 6
DURATION_UNIT_NAMES = ("minute", "ten minutes", "hour", "day")
DURATION_UNIT_MINUTES = (1, 10, 60, 1440)

# Bit 7 of the magnitude says there is something to put back when the effect
# expires; the restore reads the value out of the effect record, never from the
# character's base value.
MAGNITUDE_RESTORE_FLAG = 0x80

# Which ids read the magnitude on expiry, from the `ECL65 $9AD5` list (the
# other nineteen ids in that 24-entry list discard it, and an id outside the
# list reaches no handler). Out of combat: 12 and 38 rebuild STR and STR %, 14
# rebuilds CHA; 131 and 132 read only bit 7, as a branch.
MAGNITUDE_VALUE_IDS = frozenset({12, 14, 38})
MAGNITUDE_BRANCH_IDS = frozenset({131, 132})
MAGNITUDE_READ_IDS = MAGNITUDE_VALUE_IDS | MAGNITUDE_BRANCH_IDS

# In combat the expiry indexes a 139-entry table (`SQRPACI01 $0791`, handlers
# in `SPELLE01`) and only four entries have been read: 12 and 38 at `$A81D`
# (STR, STR %), 13 and 14 at `$A83F` (CHA). The other 135 are UNKNOWN, so this
# is a lower bound: an id missing from it may still restore a statistic in a
# fight. It is not folded into `MAGNITUDE_VALUE_IDS`, which is the out-of-combat
# list and is exact.
COMBAT_MAGNITUDE_VALUE_IDS = frozenset({12, 13, 14, 38})


@dataclass(frozen=True)
class Duration:
    """A decoded duration byte."""

    count: int
    unit: str
    minutes_per_unit: int
    never_expires: bool

    @property
    def minutes(self) -> int:
        """The most game-clock minutes the count can last; 0 for a byte that never expires.

        An upper bound, not an exact time: a count in unit 01-11 loses one when
        its clock digit wraps, so the effect lapses between (count - 1) units
        plus the time to the next boundary and count units from now. Measured:
        a unit-01 count staged at 21:16 lost its first ten-minute unit four
        minutes later, at 21:20.
        """
        return 0 if self.never_expires else self.count * self.minutes_per_unit


def duration_unit(byte: int) -> Duration:
    """Split a duration byte into its count and unit.

    A byte of exactly zero is skipped by the ageing routines, so
    `never_expires` is set and the count is not a time. A non-zero byte whose
    count bits are zero does not expire either: it drops a whole unit at its
    next boundary, `$40` becoming `$3F`, which `remaining_minutes` counts.
    """
    _check_byte("duration", byte)
    unit = byte >> DURATION_UNIT
    return Duration(
        count=byte & DURATION_COUNT,
        unit=DURATION_UNIT_NAMES[unit],
        minutes_per_unit=DURATION_UNIT_MINUTES[unit],
        never_expires=byte == 0,
    )


def remaining_minutes(byte: int, clock_minutes: int) -> int:
    """The camp-clock minutes a duration byte has left at a time of day.

    `clock_minutes` is the game clock as minutes since midnight, the reading
    `$49C7`-`$49C9` holds. The count of a byte in unit `u` runs out on the
    `count`-th wrap of the digit one place coarser, and the radix tables make
    that wrap land on every multiple of `u` minutes, so the time left is
    `count * u - (clock % u)` -- never a whole `count * u`, which is why
    `Duration.minutes` is only an upper bound.

    CONFIRMED from the camp ageing routine of all three C64 titles, which is
    the same code at three addresses: Pool of Radiance `CAMP $1283` with its
    per-slot rule at `$12BE`, Curse of the Azure Bonds `CAMP $1432` and
    `$146D`, Secret of the Silver Blades `CAMP $126B` and `$12A6`, each at
    load base `$0800`. It holds while no single camp call passes two boundaries
    of one digit, which is what the wrapped-digit **mask** the sweep reads can
    record; rest passes five minutes a call (`CAMP $1D7A`). Both driven rests
    in `docs/133-active-effects.md` agree with it on all four units.

    **Two other routes age a slot differently** and this function does not
    describe them: a combat round decrements unit `00` and nothing else
    (`COMBAT $221E`, `COMBAT2 $FA72`, `COMBAT2 $F747`), and walking ages one
    unit a minute in Pool of Radiance and Curse, so a minute-count is skipped
    in the minute a ten-minute boundary is crossed. Silver Blades' walking
    rule differs from both Pool's and Curse's (`DUNGEON $0D95`).

    A whole zero byte never expires and returns 0. A non-zero byte with a zero
    count does expire: `$12D6`'s `DEX` on a zero count gives `$FF` rather than
    zero, so `$12D9` takes one off the whole byte and `$40` becomes `$3F`.
    """
    _check_byte("duration", byte)
    if byte == 0:
        return 0
    unit = DURATION_UNIT_MINUTES[byte >> DURATION_UNIT]
    count = byte & DURATION_COUNT
    phase = clock_minutes % unit
    if count:
        return count * unit - phase
    wait = unit - phase
    return wait + remaining_minutes(byte - 1, clock_minutes + wait)


def exact_durations(minutes: int, clock_minutes: int) -> tuple[int, ...]:
    """Every duration byte that runs out after exactly `minutes`, in byte order.

    Counts of 1 to 63 only, which is what a cast writes. Empty for most
    values: at a given time of day the four units reach 213 to 216 of the
    65,535 an engine-written DOS duration word can hold.
    """
    return tuple(byte for byte in range(1, 0x100)
                 if byte & DURATION_COUNT
                 and remaining_minutes(byte, clock_minutes) == minutes)


def longest_duration_within(minutes: int, clock_minutes: int) -> int | None:
    """The duration byte with the most time left that does not outlast `minutes`.

    A measurement of what the destination can hold, not a conversion policy:
    which byte a converted running effect should get is a decision nobody has
    taken. Ties go to the smaller unit, which is the byte the engine's own
    walking and combat routines age most finely.

    `None` for a source with less than a minute left, which no engine-written
    DOS record holds -- its ageing removes a node rather than storing zero.
    """
    best, best_left = None, 0
    for byte in range(1, 0x100):
        if not byte & DURATION_COUNT:
            continue
        left = remaining_minutes(byte, clock_minutes)
        if best_left < left <= minutes:
            best, best_left = byte, left
    return best


def clock_minutes(digits: "tuple[int, ...]") -> int:
    """Minutes since midnight from the clock digits `WorldState.clock` holds.

    `digits` is `(sub-minute, minute units, minute tens, hour, day, month)`,
    the order `goldbox.dos_codec.apply_clock` writes and `goldbox.world_state.
    from_c64`/`from_dos` read.  Same arithmetic as `tools/c64/curedrive.py`'s
    own `clock_minutes`, which reads the three bytes straight out of a
    payload rather than through `WorldState`.
    """
    _, units, tens, hour = digits[0], digits[1], digits[2], digits[3]
    return hour * 60 + tens * 10 + units


def closest_duration(minutes: int, clock_minutes: int) -> int | None:
    """The duration byte whose time left is nearest `minutes`, in either direction.

    The converted effect may outlast its source slightly. Ties go to the
    shorter time left and then to the smaller unit, which is the byte the
    engine's own walking and combat routines age most finely. Counts of 1 to
    63 only, which is what a cast writes.

    `None` for a source with less than a minute left, which no engine-written
    DOS record holds -- its ageing removes a node rather than storing zero.
    """
    if minutes < 1:
        return None
    best, best_key = None, None
    for byte in range(1, 0x100):
        if not byte & DURATION_COUNT:
            continue
        left = remaining_minutes(byte, clock_minutes)
        key = (abs(left - minutes), left, byte >> DURATION_UNIT)
        if best_key is None or key < best_key:
            best, best_key = byte, key
    return best


# --- the neutral running effect ----------------------------------------------
#
# `goldbox/neutral.py`'s `running_effects` holds one whole DOS `.SPC` record per
# spell still counting down. **The DOS encoding is the neutral encoding**: DOS
# and Amiga hold it literally, and a C64 slot's magnitude is a per-title,
# per-id function of it rather than a copy. The owner is implicit -- the
# record's own character. An id in `PARTY_ROW_IDS` converts a party-wide
# row to a node on one member, or to a node on every member for an id in
# `PARTY_ROW_ON_EVERY_MEMBER`; no other party-wide row converts yet.
RUNNING_EFFECT_SIZE = 9
_RUNNING_EFFECT_NEXT = bytes(4)


@dataclass(frozen=True)
class RunningEffect:
    """One neutral running effect: a DOS `.SPC` record with time left.

    `id` is the effect id in `goldbox/traits.py`'s namespace, `minutes` the
    time left as an exact count of game-clock minutes (bytes 1-2 of the record,
    little-endian), `data` the DOS data byte and `flag` the DOS flag byte. Bytes
    5-8 of the record are the next pointer, NULL because the engine rebuilds
    the chain on load.

    `minutes` is never zero: a record at zero never expires and belongs in
    `granted_effects`.
    """

    id: int
    minutes: int
    data: int
    flag: int

    def __post_init__(self) -> None:
        _check_byte("id", self.id)
        _check_byte("data", self.data)
        _check_byte("flag", self.flag)
        if not 1 <= self.minutes <= 0xFFFF:
            raise ValueError(
                f"minutes left must be 1..65535, got {self.minutes}: a "
                "record at zero never expires and is not a running effect")

    @classmethod
    def from_record(cls, record: bytes) -> RunningEffect:
        """Read the nine-byte `.SPC` record; the next pointer is not read."""
        if len(record) != RUNNING_EFFECT_SIZE:
            raise ValueError(
                f"a running effect is {RUNNING_EFFECT_SIZE} bytes, "
                f"got {len(record)}")
        return cls(id=record[0], minutes=record[1] | record[2] << 8,
                   data=record[3], flag=record[4])

    def to_record(self) -> bytes:
        """The nine-byte record, with the next pointer NULL."""
        return (bytes((self.id, self.minutes & 0xFF, self.minutes >> 8,
                       self.data, self.flag)) + _RUNNING_EFFECT_NEXT)


#: The Pool of Radiance effect ids whose ordinary cast stores the caster's level
#: as the DOS data byte and as the C64 magnitude
#: (`docs/226-the-c64-running-effect-crosswalk.md`).
POOL_CASTER_LEVEL_IDS = frozenset(
    {1, 5, 8, 9, 10, 16, 17, 19, 20, 24, 25, 37, 41, 45, 46})

#: The same, for the later titles: the C64 writes the caster's level for each
#: of these ids and the DOS cast stores it, and nothing but Dispel Magic reads
#: it (`docs/226-the-c64-running-effect-crosswalk.md`). Prayer (49), the
#: ability ids and ids with no C64 spell row stay out.
LATER_CASTER_LEVEL_IDS = {
    "curse-of-the-azure-bonds": frozenset(
        {1, 5, 8, 9, 10, 16, 17, 19, 20, 24, 37, 41, 45, 46, 63, 69}),
    "secret-of-the-silver-blades": frozenset(
        {1, 5, 8, 9, 10, 16, 17, 19, 20, 24, 37, 41, 45, 46, 57, 63, 69}),
}

#: The ids whose value the C64 stores in the magnitude and DOS in the data byte
#: by a rule of its own: Enlarge (12), Friends (14), Mirror Image (28) and
#: Strength (38). Each title's rule is in `c64_row` and `dos_record`.
POOL_VALUE_IDS = frozenset({12, 14, 28, 38})
LATER_VALUE_IDS = frozenset({12, 14, 28, 38})

#: The ids that set strength. C64 Pool restores one old score per character,
#: so a second such node on one character has no row to take it.
STRENGTH_IDS = frozenset({12, 38})

#: The flag byte each later title's DOS cast writes into these nodes, from the
#: push order into the generic cast and the apply routine: Curse Enlarge
#: `GAME.OVR:0x2FFBA`, Friends `0x301A5`, Mirror Image `0x3072F`, Strength
#: `0x30C10`; Silver Blades `0x2E8C9` (the apply routine `0x37EB0`), `0x2E9EB`,
#: `0x2EF94`, `0x2F477`. The flag is inert in both titles (their handlers for
#: 12, 14 and 38 are empty, and removal recomputes by id whatever the flag), so
#: it is only written back as the game wrote it.
LATER_CAST_FLAGS: dict[str, dict[int, int]] = {
    "curse-of-the-azure-bonds": {12: 1, 14: 1, 28: 0, 38: 1},
    "secret-of-the-silver-blades": {12: 0, 14: 1, 28: 0, 38: 1},
}


#: The most minutes a DOS or Amiga running-effect node holds (its `u16`).
DOS_MINUTES_MAX = 0xFFFF


#: The ids each title's C64 game asks for with owner `PARTY_WIDE` and its DOS
#: game asks every party member for, so one C64 row and one node on any member
#: say the same thing. Id 5 is Detect Magic. C64 queries: Pool `LIBRARY
#: $4086`, Curse `$4141`, Silver Blades `$3899`, each `LDA #$05 / LDX #$FF`.
#: DOS loops over the party list: Pool `START.EXE` image `0x1039`-`0x1074`,
#: Curse `GAME.OVR:0x37B62`-`0x37B9D`, Silver Blades `0x385DF`-`0x38617`.
#:
#: Id 49 is Prayer, and Pool's 35 is its camp row. C64 camp Prayer: Pool
#: `SPELLE04 $A816` (id 35, owner `$FF`); Curse and Silver Blades `ECL65` row 27
#: through target mode 0 (`$805A`). C64 Pool combat Prayer: `SPELLE00
#: $AC36`-`$AC56`. DOS asks for 49 for every combatant through the check-list
#: routine (Pool `GAME.OVR:0x2B04A`, Curse `0x3529C`, Silver Blades `0x3606F`).
#: DOS Pool names an id-35 node "Prayer" in Magic > Display (`GAME.OVR:0x189E1`)
#: and reads it nowhere else.
PARTY_ROW_IDS: dict[str, frozenset[int]] = {
    "pool-of-radiance": frozenset({5, 35, 49}),
    "curse-of-the-azure-bonds": frozenset({5, 49}),
    "secret-of-the-silver-blades": frozenset({5, 49}),
}

#: The party-row ids that become one DOS node on every party member, not one:
#: DOS's list of spells in effect is per member, and each member finds its own
#: node first (Pool `GAME.OVR:0x2B075`).
PARTY_ROW_ON_EVERY_MEMBER = frozenset({35, 49})

_PRAYER_ID = 49
DETECT_MAGIC_ID = 5


def prayer_dos_data(title_key: str, magnitude: int) -> int:
    """The DOS data byte for a C64 Prayer row's magnitude.

    The side is bit 6 of the C64 magnitude, inverted for Pool: C64 Pool
    (`SPELLE01 $A9C2`-`$A9C7`) gives the bonus when the sides differ, every
    other handler when they are equal. Both ports use side 0 for the party.
    DOS keeps the side in bit 4 above the low nibble.
    """
    side = magnitude >> 6 & 1
    if title_key == "pool-of-radiance":
        side ^= 1
    return side << 4 | magnitude & 0x0F


def prayer_c64_magnitude(title_key: str, data: int) -> int:
    """The C64 magnitude for a DOS Prayer data byte: the inverse of
    `prayer_dos_data` on the bits it keeps."""
    side = data >> 4 & 1
    if title_key == "pool-of-radiance":
        side ^= 1
    return side << 6 | data & 0x0F


def party_row_ids(title_key: str) -> frozenset[int]:
    """The ids a title converts as one party-wide C64 row."""
    return PARTY_ROW_IDS.get(title_key, frozenset())


def _caster_level_ids(title_key: str) -> frozenset[int]:
    """The ids a title converts, the same set in both directions."""
    if title_key == "pool-of-radiance":
        return POOL_CASTER_LEVEL_IDS
    return LATER_CASTER_LEVEL_IDS.get(title_key, frozenset())


@dataclass(frozen=True)
class Unconverted:
    """A running effect `c64_row` or `dos_record` has no rule for, and the
    reason in a clause."""

    reason: str


def _value_row(title_key: str, node: RunningEffect,
               strength_nodes: int) -> tuple[int, int] | Unconverted:
    """`c64_row` for Enlarge, Friends, Mirror Image and Strength."""
    data, flag = node.data, node.flag
    if title_key == "pool-of-radiance" and node.id in POOL_VALUE_IDS:
        if node.id in STRENGTH_IDS:
            if data == 0 or data & 0x80:
                return Unconverted("a data byte no DOS engine writes for a "
                                   "strength or Enlarge node")
            if strength_nodes > 1:
                return Unconverted("more than one strength node on one "
                                   "character, and C64 Pool restores one "
                                   "old score")
            value = data - 1 if data <= 101 else data
        elif node.id == 14:
            if data > 0x7F:
                return Unconverted("a data byte no DOS engine writes for "
                                   "Friends")
            value = data
        else:
            if flag != 0 or data > 0x7F:
                return Unconverted("a Mirror Image node no DOS engine writes")
            return node.id, data
        return node.id, value | MAGNITUDE_RESTORE_FLAG if flag else value
    if title_key in LATER_CAST_FLAGS and node.id in LATER_VALUE_IDS:
        if node.id == 38:
            if data == 101:
                return Unconverted("a Strength data byte of 101, which DOS "
                                   "may read as 18/100 and not one step")
            if not 102 <= data <= 108:
                return Unconverted("a data byte no DOS engine writes for "
                                   "Strength")
            return node.id, later_ability_magnitude(data - 100, data & 0x0F)
        if node.id == 14:
            if not 1 <= data <= 8:
                return Unconverted("a data byte no DOS engine writes for "
                                   "Friends")
            return node.id, later_ability_magnitude(data, data & 0x0F)
        if node.id == 12:
            level = enlarge_level(*later_node_score(data))
            if level is not None:
                return node.id, MAGNITUDE_RESTORE_FLAG | level
            if data == 0x7B:
                return Unconverted("Enlarge at caster level 12 or more sets "
                                   "strength 23, above the C64's 22")
            return Unconverted("an Enlarge score no DOS engine writes")
        if flag != 0:
            return Unconverted("a Mirror Image node no DOS engine writes")
        return node.id, mirror_image_count(data, later=True)
    return Unconverted("no rule yet for this id in this title")


def c64_row(title_key: str, node: RunningEffect, *,
            strength_nodes: int = 1) -> tuple[int, int] | Unconverted:
    """The C64 id and magnitude for a DOS running effect, or why there is none.

    A title's caster-level ids (`POOL_CASTER_LEVEL_IDS`,
    `LATER_CASTER_LEVEL_IDS`) convert with flag 0 and a caster level as the
    data byte. Enlarge, Friends, Mirror Image and Strength (12, 14, 28, 38)
    take their title's rule from `docs/226`; `strength_nodes` counts the
    nodes on this character that set strength. A state refused as one "no DOS
    engine writes" is unreachable in play.
    """
    if node.id not in _caster_level_ids(title_key):
        return _value_row(title_key, node, strength_nodes)
    if node.flag != 0:
        return Unconverted("a flag byte other than 0 on a caster-level effect")
    if not 1 <= node.data <= 0x7F:
        return Unconverted("a data byte that is not a caster level")
    return node.id, node.data


def _value_node(title_key: str, effect_id: int,
                m: int) -> tuple[int, int] | Unconverted:
    """`dos_record`'s `(data, flag)` for Enlarge, Friends, Mirror Image and
    Strength, the inverse of `_value_row`."""
    if title_key == "pool-of-radiance" and effect_id in POOL_VALUE_IDS:
        if effect_id in STRENGTH_IDS:
            value = m & 0x7F
            # DOS's own encoder writes 101 for a strength of 1 and for 18/100.
            return (value + 1 if value <= 100 else value), m >> 7
        if effect_id == 14:
            return m & 0x7F, m >> 7
        if m & 0x80:
            return Unconverted("a Mirror Image magnitude with bit 7 set, "
                               "which waits on the C64 combat-writer read")
        return m, 0
    if title_key in LATER_CAST_FLAGS and effect_id in LATER_VALUE_IDS:
        if effect_id == 28:
            if m > 4:
                return Unconverted("a Mirror Image count above 4, which "
                                   "waits on the C64 combat-writer read")
            return m << 4 | m, 0
        if not m & MAGNITUDE_RESTORE_FLAG:
            return Unconverted("a magnitude without bit 7, which waits on "
                               "the C64 combat-writer read")
        if effect_id == 12:
            if m & 0x0F == 0:
                return Unconverted("an Enlarge magnitude with no level")
            return (later_node_data(*ENLARGE_STRENGTHS[min(m & 0x0F, 10) - 1]),
                    LATER_CAST_FLAGS[title_key][12])
        bonus = later_ability_bonus(m)
        if effect_id == 38:
            if bonus == 1:
                return Unconverted("a Strength bonus of 1, which waits on "
                                   "the run that reads DOS data 101")
            return 100 + bonus, 1
        return bonus, 1
    return Unconverted("no rule yet for this id in this title")


def dos_record(title_key: str, row: "Effect",
               clock_minutes: int) -> RunningEffect | Unconverted:
    """The DOS running-effect node for a C64 row, or why there is none.

    The inverse of `c64_row`. A minutes count DOS cannot hold is clamped to
    the nearest value it can. A duration byte of zero never expires and has
    no node, so the caller must route it elsewhere.
    """
    if row.duration == 0:
        raise ValueError("a never-expiring row has no running-effect node")
    minutes = min(remaining_minutes(row.duration, clock_minutes),
                  DOS_MINUTES_MAX)
    if row.id not in _caster_level_ids(title_key):
        made = _value_node(title_key, row.id, row.magnitude)
        if isinstance(made, Unconverted):
            return made
        return RunningEffect(row.id, minutes, *made)
    if not 1 <= row.magnitude <= 0x7F:
        return Unconverted("a magnitude that is not a caster level")
    return RunningEffect(row.id, minutes, row.magnitude, 0)


def party_row_record(title_key: str, row: "Effect",
                     clock_minutes: int) -> RunningEffect | Unconverted:
    """The DOS node for a party-wide C64 row, or why there is none.

    The owner is not looked at. The magnitude is copied to the data byte
    unchanged, except for Prayer's side bit (`prayer_dos_data`): only Dispel
    Magic reads it, the same way on both ports.
    """
    if row.id not in party_row_ids(title_key):
        return Unconverted("no rule yet for a party-wide row of this id")
    if row.duration == 0 and row.id == DETECT_MAGIC_ID:
        raise ValueError("a never-expiring Detect Magic row has no "
                         "running-effect node; see `party_row_granted`")
    data = row.magnitude
    if row.id == _PRAYER_ID:
        data = prayer_dos_data(title_key, row.magnitude)
    if row.duration == 0:
        # Only Detect Magic's never-expiring form is settled (a duration-0
        # record, `party_row_granted`); the other ids keep the longest node
        # a running record can hold until theirs is read.
        return RunningEffect(row.id, DOS_MINUTES_MAX, data, 0)
    minutes = min(remaining_minutes(row.duration, clock_minutes),
                  DOS_MINUTES_MAX)
    return RunningEffect(row.id, minutes, data, 0)


def party_row_granted(title_key: str, row: "Effect") -> bytes | None:
    """The DOS granted record for a never-expiring party-wide row, or `None`.

    Detect Magic only: DOS keeps duration 0 for good and its one id-5 query
    matches by id, so the record `05 00 00 mm 00` (mm the row's magnitude)
    on one member is the exact form. It is `granted_effects`, not a running
    effect, because a running effect cannot have zero minutes.
    """
    if (row.id != DETECT_MAGIC_ID or row.duration != 0
            or row.id not in party_row_ids(title_key)):
        return None
    return bytes((row.id, 0, 0, row.magnitude, 0)) + _RUNNING_EFFECT_NEXT


def is_party_granted_record(title_key: str, node: bytes) -> bool:
    """Whether a DOS granted record is `party_row_granted`'s `05 00 00 mm 00`.

    Flag 1 is an item's grant (removed when the item comes off) and data
    `0xFF` is a racial or trait-slot seed; neither is a party-wide row, and
    both stay in a C64 trait slot. Pool's own item grant of id 5 is
    `05 00 00 0C 00`, which no byte separates from a magnitude-12 row; it
    becomes a party row, because no Pool item grants id 5 and so no save a
    game wrote holds it, and keeping both forms (one `05 00 00 0C 00` per
    readied item with `0x3D` = 5, to a trait slot) is not built.
    """
    return (node[0] == DETECT_MAGIC_ID
            and node[0] in party_row_ids(title_key)
            and node[1] == 0 and node[2] == 0
            and node[3] != 0xFF and node[4] == 0)


def c64_party_row(title_key: str,
                  node: RunningEffect) -> tuple[int, int] | Unconverted:
    """The C64 id and magnitude for a DOS node that becomes a party-wide row.

    Detect Magic's flag byte is not read: no DOS engine reads it for id 5.
    """
    if node.id not in party_row_ids(title_key):
        return Unconverted("no rule yet for this id in this title")
    if node.flag != 0 and node.id != DETECT_MAGIC_ID:
        return Unconverted("a flag byte other than 0 on a party-wide effect")
    if node.id == _PRAYER_ID:
        return node.id, prayer_c64_magnitude(title_key, node.data)
    return node.id, node.data


@dataclass(frozen=True)
class Effect:
    """One slot of the effect table.

    **Expiry clears only the id**, so a slot with id 0 is free whatever the
    other three arrays still hold. `active_effects` filters on exactly that,
    and anything that skips it shows effects that ended hours ago.

    The two slots an eight-hour rest ran out read id 0 with a duration byte of
    0 as well, so an expired slot and a never-expiring one are told apart by
    the id and never by the duration. Which routine wrote that zero -- the
    sweep storing the run-out, or the expiry -- is not established.
    """

    slot: int
    id: int
    owner: int
    duration: int
    magnitude: int

    @property
    def party_wide(self) -> bool:
        return self.owner == PARTY_WIDE

    @property
    def monster(self) -> bool:
        return FIRST_MONSTER <= self.owner < PARTY_WIDE

    @property
    def remaining(self) -> int:
        """The count, in the unit `duration_unit` names for the top two bits."""
        return self.duration & DURATION_COUNT

    @property
    def unit(self) -> int:
        return self.duration >> DURATION_UNIT

    @property
    def restores_a_statistic(self) -> bool:
        """Whether the game's expiry would put a statistic back from this slot
        out of combat.

        Bit 7 of the magnitude is the flag, and ids 12 and 38 (STR, STR %) and
        14 (CHA) are the ones that read the value out of combat. **Id 13 also
        restores a statistic in combat** (`COMBAT_MAGNITUDE_VALUE_IDS`), which
        this answer does not include; `restores_a_statistic_in` asks the
        combat question. Clearing such a slot with `clear_effect` skips that
        restore.
        """
        return self.restores_a_statistic_in()

    def restores_a_statistic_in(self, *, in_combat: bool = False) -> bool:
        """Whether expiry would put a statistic back, out of combat or in it.

        In combat the answer is true for `COMBAT_MAGNITUDE_VALUE_IDS`, which is
        a lower bound: an id outside it may still restore a statistic in a
        fight.
        """
        ids = COMBAT_MAGNITUDE_VALUE_IDS if in_combat else MAGNITUDE_VALUE_IDS
        return bool(self.magnitude & MAGNITUDE_RESTORE_FLAG
                    and self.id in ids)

    @property
    def label(self) -> str:
        """`effect 12` -- always the number, never a looked-up name.

        `goldbox/traits.py` does hold an id-to-name table (`traits.describe`),
        so the old claim that no such table existed anywhere in the project
        was wrong. `label` still prints the bare number, deliberately: it is
        what a debug log shows for an effect no condition badge covers, and
        the point there is to say an id is *unbadged*, not to name it. A
        caller that wants the name calls `traits.describe(effect.id, game)`
        itself.
        """
        return f"effect {self.id}"

    @property
    def detail(self) -> str:
        who = ("the party" if self.party_wide else
               f"monster {self.owner}" if self.monster else
               f"party slot {self.owner}")
        d = duration_unit(self.duration)
        when = ("never expires" if d.never_expires
                else f"{d.count} x {d.unit}")
        return (f"id {self.id} on {who}; duration byte ${self.duration:02X} "
                f"= {when}; magnitude {self.magnitude}")


def active_effects(save0_bytes: bytes) -> tuple[Effect, ...]:
    """Every effect slot whose id is non-zero, read across all four arrays.

    Takes the payload, so it is already title-independent: the offsets are
    inside the save image and follow it wherever the title loads it.
    """
    out = []
    for i in range(EFFECT_SLOTS):
        eid = save0_bytes[EFFECT_ID_OFFSET + i]
        if not eid:
            continue                       # expiry clears only the id
        out.append(Effect(
            slot=i,
            id=eid,
            owner=save0_bytes[EFFECT_OWNER_OFFSET + i],
            duration=save0_bytes[EFFECT_DURATION_OFFSET + i],
            magnitude=save0_bytes[EFFECT_MAGNITUDE_OFFSET + i],
        ))
    return tuple(out)


def _check_slot(slot: int) -> None:
    if not 0 <= slot < EFFECT_SLOTS:
        raise ValueError(f"slot out of range 0..{EFFECT_SLOTS - 1}: {slot}")


def _check_byte(name: str, value: int) -> None:
    if not 0 <= value <= 0xFF:
        raise ValueError(f"{name} must be a byte, 0..255, got {value}")


def clear_effect(payload: bytearray, slot: int) -> None:
    """Zero one slot across all four arrays, and restore nothing.

    **This is not the game's own clear.** `CAMP $131F` clears `$4900,X` alone,
    leaving owner, duration and magnitude as residue (`docs/125-bug-notes.md`
    N7), and then, when bit 7 of the magnitude is set, calls a handler that
    puts a statistic back. This function skips the handler, so clearing a slot
    whose id is 12, 14 or 38 with that bit set (`Effect.restores_a_statistic`),
    or 13 in combat (`COMBAT_MAGNITUDE_VALUE_IDS`), leaves the character's
    strength or charisma altered for good. A caller
    offering to remove an effect must apply the restore or refuse those slots
    (`docs/133-active-effects.md`, "What this means for a write path").
    """
    _check_slot(slot)
    payload[EFFECT_ID_OFFSET + slot] = 0
    payload[EFFECT_OWNER_OFFSET + slot] = 0
    payload[EFFECT_DURATION_OFFSET + slot] = 0
    payload[EFFECT_MAGNITUDE_OFFSET + slot] = 0


def write_effect(payload: bytearray, slot: int, id: int, owner: int,
                 duration: int, magnitude: int) -> None:
    """Write one slot across all four arrays.

    Each of the four value arguments is a raw byte; nothing here validates
    that the combination means anything the game would recognise -- `owner` is
    not checked against `PARTY_WIDE`/`FIRST_MONSTER`. **A magnitude with bit 7
    set on an id in `MAGNITUDE_VALUE_IDS` is a write to the character record,
    deferred:** on expiry the game rebuilds STR or CHA from that byte. Callers
    behind a write path decide what is safe to offer; this only puts the bytes
    where the four arrays expect them.
    """
    _check_slot(slot)
    for name, value in (("id", id), ("owner", owner),
                        ("duration", duration), ("magnitude", magnitude)):
        _check_byte(name, value)
    payload[EFFECT_ID_OFFSET + slot] = id
    payload[EFFECT_OWNER_OFFSET + slot] = owner
    payload[EFFECT_DURATION_OFFSET + slot] = duration
    payload[EFFECT_MAGNITUDE_OFFSET + slot] = magnitude


# --- which slot a new effect takes, and who owns it --------------------------
#
# All three engines allocate through one routine, the same code at three
# addresses: Pool of Radiance `LIBRARY $3FE4`, Curse of the Azure Bonds
# `LIBRARY $409F` and Secret of the Silver Blades `LIBRARY $3854`. It takes an
# id in A and an owner in X and walks the slots **from 63 down to 0**, matching
# the first slot whose id is the one asked for and whose owner is either the
# one asked for or negative. `$4005`/`$40C0`/`$3875` return carry clear for no
# match.
#
# The cast calls it twice (`SPELLE04 $A7F1` and `$A80E`, `ECL65 $8138` and
# `$815A`): once for the id and owner it is about to write, and then with id 0
# and owner `$FF` for a free slot. So:
#
# * a new effect lands in the **highest-numbered slot whose id is zero**;
# * a cast writes at most **one slot per (id, owner) pair** -- a second cast of
#   the same spell on the same character replaces the first rather than adding
#   a row (Pool expires the old slot through `CAMP $131F` first, Curse and
#   Silver Blades overwrite it in place). That is what the *cast* does; the
#   arrays themselves hold as many rows of one id as a writer puts in them, and
#   every sweep in the engine is per slot;
# * which of the two survives is `replaces_slot` below;
# * with no free slot the cast silently does nothing (`$A811`, `$815D`).
#
# The owner is the party slot for a per-character effect and `PARTY_WIDE` for
# one the whole party carries, and a negative owner matches every query.


def slot_for(payload: bytes, id: int, owner: int) -> int | None:
    """The slot the engine's own search returns for this id and owner.

    `None` when it would return carry clear. An id of 0 asks for a free slot,
    which is what the cast does with `PARTY_WIDE` as the owner.
    """
    _check_byte("id", id)
    _check_byte("owner", owner)
    for slot in range(EFFECT_SLOTS - 1, -1, -1):
        if payload[EFFECT_ID_OFFSET + slot] != id:
            continue
        if id == 0:
            return slot
        held = payload[EFFECT_OWNER_OFFSET + slot]
        if held >= 0x80 or held == owner:
            return slot
    return None


def free_slot(payload: bytes) -> int | None:
    """The slot a cast would put a new effect in, or `None` when all 64 are taken."""
    return slot_for(payload, 0, PARTY_WIDE)


def write_party_row(payload: bytearray, id: int, duration: int,
                    magnitude: int, clock_minutes: int) -> bool:
    """Write one party-wide row, keeping the longest-lasting one per id.

    An existing party row is overwritten only when the new one lasts longer,
    or is a duration byte of 0, which never expires (`replaces_slot`'s rule);
    an existing duration byte of 0 is left alone. Returns
    `False` when there is no row and no free slot.
    """
    held = slot_for(payload, id, PARTY_WIDE)
    if held is not None:
        old = payload[EFFECT_DURATION_OFFSET + held]
        if old != 0 and (duration == 0
                         or remaining_minutes(duration, clock_minutes)
                         > remaining_minutes(old, clock_minutes)):
            write_effect(payload, held, id, PARTY_WIDE, duration, magnitude)
        return True
    free = free_slot(payload)
    if free is None:
        return False
    write_effect(payload, free, id, PARTY_WIDE, duration, magnitude)
    return True


def replaces_slot(old_duration: int, new_duration: int) -> bool:
    """Whether a fresh cast takes over the slot it found for its id and owner.

    The engines compare the two **duration bytes** rather than the time left,
    so `$41` beats `$3F` and lasts a tenth as long, and the two zero cases go
    opposite ways: a new duration of zero always takes the slot, an old one of
    zero always keeps it. Otherwise the cast writes on a tie or a larger byte
    and abandons its spell on a smaller one.

    Pool of Radiance `SPELLE04 $A7F6`-`$A805` and the later titles' `ECL65
    $8143`-`$8154` are the same four tests; Pool expires the old slot through
    `CAMP $131F` and allocates a fresh one where the later titles overwrite in
    place, which changes which slot ends up holding the effect and not which
    cast wins.
    """
    for name, value in (("old duration", old_duration),
                        ("new duration", new_duration)):
        _check_byte(name, value)
    if new_duration == 0:
        return True
    if old_duration == 0:
        return False
    return new_duration >= old_duration


# --- the later titles' ability effects, which are modifiers and not old values
#
# Curse of the Azure Bonds and Secret of the Silver Blades keep the permanent
# score at record `0x065` and the score in force at `0x014`, and rebuild the
# second from the first plus the running effects
# (`docs/201-the-two-ability-arrays.md`, the recompute at Curse `ECL65 $9160`
# and Silver Blades `$9637`). So a slot's magnitude holds **how much the
# effect adds**, never the score it replaced, and the two DOS-side encodings
# differ per id. Every constant below is read out of the engines in
# `tools/c64/effectcrosswalk.py`.

#: The later titles cast an ability spell with the bonus in the magnitude's
#: **upper nibble, one less than the bonus**, the caster's level in the low
#: nibble and bit 7 set (Curse `ECL65 $8241`, Silver Blades `$828A`). The
#: recompute reads `(magnitude & 0x7F) >> 4` (Curse `$9797`, Silver Blades
#: `$99EA`) and applies one more step than that.
LATER_ABILITY_BONUS_SHIFT = 4

#: What Enlarge sets strength to, by caster level, capped at level 10. The C64
#: table is Curse `ECL65 $9223`/`$922F` and Silver Blades `$96E9`/`$96F5`; DOS
#: writes the same ten values from its own ladder of `cmp al, <level>` tests at
#: Curse `GAME.OVR:0x2FFCD`-`0x3004B`. Both ports hold two more entries, 23 and
#: 24. DOS Silver Blades reaches 23 at caster level 12 or more, through the
#: default arm at `0x2E892` (`mov byte ptr [0x64d8], 0x17`); the C64 caps the
#: level at 10 in both titles, so its most is 22. DOS Curse keeps 18/00 there.
ENLARGE_STRENGTHS: tuple[tuple[int, int], ...] = (
    (18, 0), (18, 1), (18, 51), (18, 76), (18, 91), (18, 100),
    (19, 0), (20, 0), (21, 0), (22, 0),
)

#: The strength ladder one step of a later title's Strength effect climbs:
#: below 18 the score itself, at 18 the percentile in tens, stopping at 18/100.
#: Curse `ECL65 $9191`-`$91B0`, Silver Blades `$9663`-`$9682`, under a loop
#: whose count is the magnitude's nibble in the operand of `LDA #` at Curse
#: `$91B6` (Silver Blades `$9688`), decremented at `$91B3`/`$9685` and run
#: while it stays positive -- so the ladder climbs one more step than the
#: nibble holds. The DOS cast computes the same arrival in closed form,
#: `(new - 18) * 10 + old percentile` clamped to 100 (Curse
#: `GAME.OVR:0x30D3A`-`0x30D5D`).
STRENGTH_CAP = (18, 100)


def raise_strength(strength: int, percentile: int, steps: int) -> tuple[int, int]:
    """Climb the later titles' strength ladder, the way the recompute does.

    There is no inverse, and none is needed: both ports keep the permanent
    score beside the one in force, and every engine derives the second from the
    first (`docs/204-the-dos-ability-pair.md`,
    `docs/226-the-c64-running-effect-crosswalk.md`).
    """
    if steps < 0:
        raise ValueError(f"steps must not be negative: {steps}")
    for _ in range(steps):
        if (strength, percentile) == STRENGTH_CAP or strength > 18:
            break
        if strength != 18:
            strength, percentile = strength + 1, 0
        elif percentile >= 90:
            percentile = 100
        else:
            percentile += 10
    return strength, percentile


def mirror_image_count(dos_data: int, *, later: bool) -> int:
    """The images a DOS Mirror Image node has left.

    Pool of Radiance keeps the count in the whole byte; Curse and Silver Blades
    keep it in the **upper nibble** and the caster's level in the low one, which
    is what both engines' casts write (Curse `GAME.OVR:0x30700`, Silver Blades
    `0x2EF6E`) and what both selection rolls read back.

    **A spent count of zero converts to C64 magnitude 0.** DOS Curse decrements
    the whole byte, so a node can reach an upper nibble of zero with its low
    nibble still holding the caster's level -- `0x0F` is a fifteenth-level
    caster's spent Mirror Image. Neither port's handler absorbs a hit with a
    count of zero: DOS Curse rolls `dice(1, count + 1)` and absorbs only above
    1, and the C64's roll is `random(0..count)` with only a nonzero roll
    decrementing (`COMBAT $20DF`-`$20F7` with `LIBRARY $2F46`). The C64's sweeps
    age a row by its id and duration alone, so the zero row still expires on its
    time, as the DOS node does. Pool and Silver Blades remove the node at zero,
    so only a Curse player reaches the state.
    """
    _check_byte("data", dos_data)
    return dos_data >> 4 if later else dos_data


def later_ability_magnitude(bonus: int, caster_level: int) -> int:
    """The C64 magnitude for a later title's Strength or Friends slot.

    `bonus` is the number of steps the effect adds -- a DOS Strength node's
    `data - 100` or a DOS Friends node's `data`. The low nibble is read only
    for Enlarge, so a source with no level to give can pass 0.
    """
    if not 1 <= bonus <= 8:
        raise ValueError(f"a later ability bonus is 1 to 8, got {bonus}")
    if not 0 <= caster_level <= 0x0F:
        raise ValueError(f"caster level must fit the low nibble: {caster_level}")
    return MAGNITUDE_RESTORE_FLAG | (bonus - 1) << LATER_ABILITY_BONUS_SHIFT \
        | caster_level


def later_ability_bonus(magnitude: int) -> int:
    """How many steps a later title's magnitude adds, the recompute's own read."""
    _check_byte("magnitude", magnitude)
    return ((magnitude & 0x7F) >> LATER_ABILITY_BONUS_SHIFT) + 1


def enlarge_level(strength: int, percentile: int) -> int | None:
    """The caster level whose Enlarge produces this strength, or `None`.

    A DOS Enlarge node exists only where the spell actually raised the score
    (`GAME.OVR:0x30068` skips `add_affect` when it did not), so the record's
    own strength is the table entry and the level reads straight back off it.
    """
    for index, entry in enumerate(ENLARGE_STRENGTHS):
        if entry == (strength, percentile):
            return index + 1
    return None


def later_node_score(data: int) -> tuple[int, int]:
    """The score a later title's DOS engine reads out of an ability node.

    One byte carries a whole `(strength, percentile)`: the engine's own decoder
    reads `data & 0x7F` of 101 or less as `18/(data - 1)` and anything larger
    as an ordinary score of `data - 100`. Curse `GAME.OVR:0x366FB`, Silver
    Blades `0x372AB`.
    """
    if not 0 <= data <= 0xFF:
        raise ValueError("DOS data must be a byte")
    value = data & 0x7F
    return (18, value - 1) if value <= 101 else (value - 100, 0)


def later_node_data(strength: int, percentile: int) -> int:
    """What the engine's encoder writes for one score, the inverse above.

    Curse `GAME.OVR:0x366D2`, Silver Blades `0x37282`: `strength + 100`, or the
    percentile plus one at strength 18. Both engines' ability setters call it
    with the score the spell is about to produce, so an Enlarge node holds the
    enlarged score itself. A strength of 1 encodes to the same 101 as 18/100
    and the decoder answers 18/100, which is the one collision in the byte.
    """
    if not 1 <= strength <= 155 or not 0 <= percentile <= 100:
        raise ValueError("A later-title score is 1 to 155 with a percentile")
    return percentile + 1 if strength == 18 else strength + 100


# --- the spell-effect table, ECL65 relocated to $9900 -----------------------
#
# `docs/50-experiments.md`, "The effect and status system at $4900":
#
#     ECL65 loads at $9900, and its first 469 bytes are 67 records of 7.
#     One per spell id 1-56, then eleven item-only effects 57-67 (item byte
#     +14 = 80-90). CAMP $1429 computes $9900 + (id - 1) * 7 and copies the
#     record to $28C7.
#
# so the table's own **position** is the id CAMP indexes it by -- record 1 is
# whatever is at spell id 1, byte for byte, whatever byte +3 of that record
# happens to hold. That matters here because +3 is a *different* number,
# confirmed against `POOL1.D64`'s own copy: record 1 (BLESS) does carry +3 =
# 1, but record 9, 15 and twenty-one others carry +3 = 0 (a spell with no
# ongoing status to add to $4900 -- CURE LIGHT WOUNDS is one, `docs/50` says
# so directly), and several values repeat across records (id 5, 8, 9, 25, 38,
# 39 and 52 each label two different spells). A dict keyed on `+3 & 0x7F`
# collapses most of the table into its id-0 entry and silently drops one
# record of every colliding pair -- so this reads by **position**, matching
# CAMP's own arithmetic, and leaves +3 alone.
ECL65_FILE = b"ECL65"
EFFECT_TABLE_RECORD_SIZE = 7
EFFECT_TABLE_RECORD_COUNT = 67
EFFECT_TABLE_SIZE = EFFECT_TABLE_RECORD_SIZE * EFFECT_TABLE_RECORD_COUNT  # 469

_REC_DURATION = 0
_REC_PER_LEVEL = 1
_REC_CASTABLE_OUTSIDE = 2
_REC_EFFECT_ID = 3          # not read here -- see the note above
_REC_MESSAGE = 4


@dataclass(frozen=True)
class EffectTableEntry:
    """One record of ECL65's spell-effect table.

    `duration` is in the same count-and-unit form as `Effect.duration` --
    **and it is frequently 0, which here means "scales with level" rather
    than the never-expires of a slot's zero**: a
    spell whose whole duration scales with the caster sets only `per_level`.
    ENLARGE is exactly this: `duration` 0, `per_level` `$0A`, and a level-1
    cast measured live wrote effect duration `$0A` -- one level's worth,
    `docs/50-experiments.md` confirms the live write and this table gives the
    per-level rate it came from.
    """

    duration: int
    per_level: int
    castable_outside_combat: bool
    message_index: int


def load_effect_table(disk: D64 | str) -> dict[int, EffectTableEntry]:
    """Read ECL65's spell-effect table off a game disk, keyed by the record's
    own position -- spell id 1-56, then item-only effect argument 57-67.

    Pattern: `goldbox/items.py::load_item_names`. `ECL65`'s own PRG header
    claims load address `$1000`, not `$9900` -- like every other game overlay
    (`docs/50-experiments.md`, "every game overlay loads at $0800, not the
    $1000 its header claims"), the header is not where the loader actually
    puts it, and `load_payload` never reads the header for anything but its
    length. Record 1's duration byte reading `$06` -- CONFIRMED live as
    BLESS's -- is what says these are the right 469 bytes.
    """
    payload = load_payload(disk, ECL65_FILE)
    if len(payload) < EFFECT_TABLE_SIZE:
        raise ValueError(
            f"ECL65 is {len(payload)} bytes after its load address; "
            f"the spell-effect table needs at least {EFFECT_TABLE_SIZE}")
    table = payload[:EFFECT_TABLE_SIZE]
    out: dict[int, EffectTableEntry] = {}
    for i in range(EFFECT_TABLE_RECORD_COUNT):
        rec = table[i * EFFECT_TABLE_RECORD_SIZE:
                    (i + 1) * EFFECT_TABLE_RECORD_SIZE]
        out[i + 1] = EffectTableEntry(
            duration=rec[_REC_DURATION],
            per_level=rec[_REC_PER_LEVEL],
            castable_outside_combat=bool(rec[_REC_CASTABLE_OUTSIDE]),
            message_index=rec[_REC_MESSAGE],
        )
    return out
