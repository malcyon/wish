"""The active-effect arrays at `SAVEDGAME0` `$4900`, and the spell table that
gives a new one its duration.

Ported out of `automap/live.py` on `#13 (Edit traits and active effects, in
two separate panels)`, because the panels that read and write this belong to
`editor/`, and `editor/` may not import `automap` -- `tests/test_wish.py::
test_editor_imports_nothing_live` is what enforces it. `automap/live.py`
imports these same names back, so `automap/combat.py`, `tools/combatshot.py`,
`tools/livestrip.py` and `tests/test_coldread.py` still resolve them as
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

# Bits 6-7 of the duration byte select the time unit. Which unit each value
# means is NOT decoded, so the count is shown and the unit is not invented.
DURATION_COUNT = 0x3F
DURATION_UNIT = 6


@dataclass(frozen=True)
class Effect:
    """One slot of the effect table.

    **Expiry clears only the id**, so a slot with id 0 is free whatever the
    other three arrays still hold. `active_effects` filters on exactly that,
    and anything that skips it shows effects that ended hours ago.
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
        """How much time is left, in whatever unit the top two bits select."""
        return self.duration & DURATION_COUNT

    @property
    def unit(self) -> int:
        return self.duration >> DURATION_UNIT

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
        return (f"id {self.id} on {who}; duration byte ${self.duration:02X} "
                f"= {self.remaining} in unit {self.unit} (the unit's meaning "
                f"is not decoded); magnitude {self.magnitude}")


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
    """Zero one slot across all four arrays.

    Tidier than the game's own clear: `CAMP $131F` expires an effect by
    clearing `$4900,X` alone and leaving owner, duration and magnitude as
    residue (`docs/125-bug-notes.md` N7 -- `PORSAVE13` carries six slots with
    a leftover magnitude of 1 from effects that had already lapsed). A slot
    this function clears is fully free, not merely free by the one field
    `active_effects` happens to filter on.
    """
    _check_slot(slot)
    payload[EFFECT_ID_OFFSET + slot] = 0
    payload[EFFECT_OWNER_OFFSET + slot] = 0
    payload[EFFECT_DURATION_OFFSET + slot] = 0
    payload[EFFECT_MAGNITUDE_OFFSET + slot] = 0


def write_effect(payload: bytearray, slot: int, id: int, owner: int,
                 duration: int, magnitude: int) -> None:
    """Write one slot across all four arrays.

    Each of the five arguments is a raw byte; nothing here validates that the
    combination means anything the game would recognise -- `owner` is not
    checked against `PARTY_WIDE`/`FIRST_MONSTER` and `magnitude` is not
    checked against whichever ids in `docs/50-experiments.md` turn out to
    carry restore data -- M2 of `#13 (Edit traits and active effects, in two
    separate panels)`. Callers behind a write path decide what is safe to
    offer; this only puts the bytes where the four arrays expect them.
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

    `duration` is bits 0-5 a count and bits 6-7 a time unit not decoded, the
    same shape `Effect.duration` carries -- **and it is frequently 0**: a
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
