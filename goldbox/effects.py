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
    in the minute a ten-minute boundary is crossed.

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
