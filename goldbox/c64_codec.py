"""The C64 codec: a 580-byte C64 record to and from a neutral character.

Both halves of the pair `goldbox/neutral.py` describes.  :func:`write` turns a
neutral character into the 580 bytes; :func:`read` turns the 580 bytes into a
neutral character.  The module knows the C64 record and nothing else: which
neutral field goes to which entry of `goldbox/layout.py`, what the C64 stores
that no source supplies, and what the C64 has no room for.  Where a value
came from is a source reader's business and reaches :func:`write` only as
the phrase :class:`goldbox.neutral.Value` carries.

Every byte of the output is justified -- it came from a neutral value, or it
was computed from one by a named rule, or it is a documented constant --
which is what :attr:`Report.unaccounted` asserts.

Evidence for the fields themselves is in `goldbox/layout.py`; for the conversion,
`docs/117-save-conversion.md`.
"""

from __future__ import annotations

import dataclasses

from . import neutral, spells
from .encoding import COMBAT_BIAS
from .layout import RECORD_SIZE, Confidence, Field
from .neutral import NeutralCharacter, Provenance
from .record import CharacterRecord

__all__ = [
    "Report",
    "INFRAVISION",
    "LEVEL_FIELDS",
    "strength_index",
    "write",
    "read",
    "READ_TARGETS",
    "record_shape",
    "span_of",
    "memorised_span",
    "get_memorised",
    "set_memorised",
    "field_disposition",
    "DIRECT",
    "TRANSFORMED",
    "DROPPED",
    "STATUS_BITS",
    "STATUS_BY_BITS",
    "OUT_OF_PLAY",
    "NO_C64_STATUS",
]


@dataclasses.dataclass
class Report(neutral.Report):
    """A C64 conversion's provenance: **every** byte has to be explained.

    Not merely the non-zero ones.  A zero the C64 record wants is as much a
    decision as a value copied into it, and `docs/117-save-conversion.md`
    makes accounting for all 580 the test that replaces a round trip.
    """

    total: int = RECORD_SIZE

    #: True when this character's own sheet portrait crossed -- both
    #: `portrait_head` and `portrait_body` written from a source, not left at
    #: whatever `CharacterRecord.blank()` starts with.  Kept separate from
    #: reading the record's own bytes back: `HEAD00` is a real portrait, so a
    #: written zero and an unwritten zero are the same byte and only the
    #: report can tell them apart (#57).
    has_portrait: bool = False

    @property
    def unaccounted(self) -> list[int]:
        """C64 offsets this conversion cannot explain. Should be empty."""
        return [i for i in range(self.total) if i not in self.sources]

    def summary_notes(self) -> list[str]:
        if self.unaccounted:
            return [f"  UNACCOUNTED: {len(self.unaccounted)} bytes"]
        return []


#: Neutral field -> the C64 field it becomes, where the value crosses
#: unchanged.  The names differ in only two places, and both times because
#: the C64 name is a storage detail: `thac0` and `roster_movement` are what
#: the roster block calls the current THAC0 and the current movement rate.
DIRECT: tuple[tuple[str, str], ...] = (
    ("strength", "strength"),
    ("intelligence", "intelligence"),
    ("wisdom", "wisdom"),
    ("dexterity", "dexterity"),
    ("constitution", "constitution"),
    ("charisma", "charisma"),
    ("exceptional_strength", "exceptional_strength"),
    ("thac0_base", "thac0_base"),
    ("race", "race"),
    ("char_class", "char_class"),
    ("age", "age"),
    ("hp_max", "hp_max"),
    ("attack_level", "attack_level"),
    ("save_paralysis", "save_paralysis"),
    ("save_petrification", "save_petrification"),
    ("save_wands", "save_wands"),
    ("save_breath", "save_breath"),
    ("save_spell", "save_spell"),
    ("movement", "movement"),
    ("level", "level"),
    ("levels_drained", "levels_drained"),
    ("hp_lost_to_drain", "hp_lost_to_drain"),
    ("thief_pick_pockets", "thief_pick_pockets"),
    ("thief_open_locks", "thief_open_locks"),
    ("thief_find_traps", "thief_find_traps"),
    ("thief_move_silently", "thief_move_silently"),
    ("thief_hide_in_shadows", "thief_hide_in_shadows"),
    ("thief_hear_noise", "thief_hear_noise"),
    ("thief_climb_walls", "thief_climb_walls"),
    ("thief_read_languages", "thief_read_languages"),
    ("copper", "copper"),
    ("silver", "silver"),
    ("electrum", "electrum"),
    ("gold", "gold"),
    ("platinum", "platinum"),
    ("gems", "gems"),
    ("jewelry", "jewelry"),
    ("sex", "sex"),
    ("alignment", "alignment"),
    ("armour_class_base", "armour_class_base"),
    ("experience", "experience"),
    ("class_bits", "class_bits"),
    ("hp_rolled", "hp_rolled"),
    ("party_order", "party_order"),
    ("hp_current", "hp_current"),
    ("thac0_current", "thac0"),
    ("armour_class", "armour_class"),
    ("movement_current", "roster_movement"),
)

@dataclasses.dataclass(frozen=True)
class RecordShape:
    """The parts of the 580-byte record the titles do not agree about.

    `goldbox/layout.py` is Pool of Radiance's table and every offset in it is
    the same in the later titles -- what differs is how far three regions run
    and whether two fields are used at all.  Each row below was read out of
    the title's own overlays, and a title with no row is written as Pool of
    Radiance, which is what a caller with no title in hand means.
    """

    key: str
    #: The declared fields the memorised-spell list spans, in offset order.
    #: Both ends move between titles: what shortens it is spending twelve of
    #: those bytes on a second copy of the abilities at `0x065`, and Silver
    #: Blades starts it five bytes earlier because it mirrors only seven of
    #: them.  :func:`memorised_span` turns this into an offset and a width,
    #: and every reader and the writer ask it rather than the layout (#268).
    memorised: tuple[str, ...]
    #: Does this title keep a second copy of the seven ability scores at
    #: `0x065`, which `0x014` is then a copy of?
    second_abilities: bool = False
    #: Does the record store the free-spell-slot array at `0x0EE`?
    spell_slots: bool = True
    #: Does the record store the dual-class pair at `0x0B9`/`0x0BA`?
    dual_class: bool = False
    #: Does this title's GEN draw the identity pair at `0x0E6`-`0x0E7`? Pool
    #: of Radiance's alone -- Curse of the Azure Bonds and Secret of the
    #: Silver Blades never write it and hold `00 00` in every shipped party
    #: (#258, The C64 side of 0x0AB is unnamed, so the conversion drops it
    #: with no issue behind it).
    identity_pair: bool = False


#: Pool of Radiance: **81 memorised slots, `0x020`-`0x070`**, and no second
#: ability array, no dual-class pair.
#:
#: The 81 is read out of its own `CAMP`, which counts down from `#$50` at
#: every site that seeds an index -- `LDX #$50 / LDA $6B20,X` at `+$0C52`,
#: `+$10A5` and `+$21E5`, `LDY #$50 / LDA $6B20,Y` at `+$11F2` and `+$176E`,
#: with `AND #$7F / STA $6B20,Y` at `+$16CA` clearing the cast bit the same
#: way Curse's does.  Those six were read by hand and are offsets into the
#: file; `tools/memorisedwidth.py` walks the whole overlay, finds sixteen
#: sites and one immediate across all of them, and prints run-time addresses
#: -- the same six are `$1450`, `$18A3`, `$29E3`, `$19F0`, `$1F6C` and
#: `$1EC8`, the overlay running at `$0800`.  `0x020 + 80 = 0x070`, and
#: `0x071` is `thac0_base`, so the region ends exactly where the next field
#: begins.  CONFIRMED, and it corrected two documents that disagreed with
#: each other: `goldbox/layout.py` declared sixteen until #268 and
#: `docs/117-save-conversion.md` said twenty-one.  Nothing crosses to DOS
#: past sixteen either way -- DOS Pool of Radiance allots sixteen slots, so a
#: converted character never arrives with more (#192).
POOL_OF_RADIANCE_RECORD = RecordShape(
    key="pool-of-radiance",
    memorised=("spells_memorised", "abilities_second", "gap_06c"),
    identity_pair=True)

#: Curse of the Azure Bonds: **69 memorised slots, `0x020`-`0x064`**, a second
#: ability array at `0x065`, the dual-class pair, and **no spell-slot array at
#: all**.
#:
#: The 69 is Curse's own `CAMP` counting from `#$44` at every site that seeds
#: an index; five of those `LDX`/`LDY` were read by hand at `$2037`, `$1A1F`,
#: `$1A5A`, `$1AE6` and `$20BB`, and `tools/memorisedwidth.py` finds twelve
#: accesses in all with `#$44` behind every one.  The twelve bytes it
#: stops short of are the ability block: `GEN $1E9C` is `LDX #$0B / LDA
#: $7C65,X / STA $7C14,X`, so `0x065`-`0x070` is the array the engine works
#: in and clamps against the racial minimum and maximum, and `0x014`-`0x01F`
#: is a copy of it.  All six records of the engine-written Curse save in
#: `work/issue32/specimens/` hold the two blocks byte for byte identical.
#:
#: **The spell-slot array is the drop.** `0x0EE`-`0x0F3` has 32 code
#: references in Pool of Radiance and **none** in Curse across 411 files, and
#: all six of those engine-written records read zero there -- including a
#: level-5 cleric who has memorised nothing and would have every slot free.
#: So the C64 has no such field in this title and `CAMP` works the ceiling
#: out for itself (#192 step 0d).
CURSE_RECORD = RecordShape(
    key="curse-of-the-azure-bonds",
    memorised=("spells_memorised",),
    second_abilities=True, spell_slots=False, dual_class=True)

#: Secret of the Silver Blades: **74 memorised slots, `0x01B`-`0x064`** -- the
#: only title measured whose list does not start at `0x020`.
#:
#: Its `CAMP` walks the list at twelve sites that line up one for one with
#: Curse's twelve -- the same addressing modes in the same order, and eleven
#: of the twelve the same instruction, the odd one being a `CMP` where Curse
#: has an `LDA` -- counting from `#$49` at every site that seeds an index:
#: `LDX #$49 / CMP $7C1B,X` at `$1412`, `LDA $7C1B,X` at `$1824`, `$18EE` and
#: `$28BC`, `LDY #$49 / LDA $7C1B,Y` at `$18FF` and `$1EB7`, with
#: `AND #$7F / STA $7C1B,Y` at `$1E13` clearing the cast bit -- the same
#: instruction sequence as Curse's at `$2016`.  `0x01B + 73 = 0x064`, so the
#: list ends where Curse's ends, immediately before `abilities_second`.
#:
#: **Why it starts five bytes earlier**, from a second overlay and so an
#: independent reading: Curse's `GEN $1E9C` is `LDX #$0B / LDA $7C65,X /
#: STA $7C14,X`, copying twelve bytes, so `0x01B`-`0x01F` is the tail of
#: Curse's ability block.  Silver Blades' `GEN $1F0A` is the same three
#: instructions with `LDX #$06` -- seven bytes, `0x065`-`0x06B` into
#: `0x014`-`0x01A` -- so those five bytes are free and the spell list has
#: them.  CONFIRMED; `tools/memorisedwidth.py` reads it again off the disks.
#:
#: **All three flags are this title's own, by a reference census of its 347
#: files** -- the same question `#192` asked of Curse's 411, counting the
#: little-endian address of each byte of the region wherever it appears.
#:
#: * `second_abilities`: `GEN $1F0A` reads `$7C65`, so the array is there.
#:   CONFIRMED, from the copy loop above.
#: * `dual_class`: `$7CB9`/`$7CBA` appear **32 times, all in code** -- `GEN`
#:   14, `ECL65` 6, `SPELLE65` 6, `POST.COM` 4, `LIBRARY` 1 -- which is the
#:   same set of files as Curse's 45 and unlike Pool of Radiance's **zero**.
#:   CONFIRMED, and it corroborates `#224`'s reading that the pair is Curse's,
#:   Silver Blades' and Gateway's.
#: * `spell_slots`: `$7CEE`-`$7CF3` appear 20 times and **not once in a code
#:   file** -- every hit is a `PIC`, `COMPIC`, `SPRITE` or `WALLSET`, one or
#:   two per file, which is what a 16-bit value looks like in bitmap data.
#:   Pool of Radiance has 24 in `GEN` and `POOLRB` alone.  PROBABLE rather
#:   than CONFIRMED: Curse's answer had a second leg this one has not, six
#:   engine-written records reading zero at `0x0EE`, and no Silver Blades save
#:   on this machine has been written by the engine.  One that reads zero
#:   there for a caster who has memorised nothing settles it.
SILVER_BLADES_RECORD = RecordShape(
    key="secret-of-the-silver-blades",
    memorised=("gap_01b", "spells_memorised"),
    second_abilities=True, spell_slots=False, dual_class=True)

RECORD_SHAPES: dict[str, RecordShape] = {
    s.key: s for s in (POOL_OF_RADIANCE_RECORD, CURSE_RECORD,
                       SILVER_BLADES_RECORD)}


def record_shape(game=None) -> RecordShape:
    """The record shape for a title, Pool of Radiance's by default.

    Duck-typed on `.key` the way `goldbox.spells.for_game` is, so a
    `goldbox.games.Game`, a key or None all work and this module still does
    not import `goldbox/games.py`.
    """
    if isinstance(game, RecordShape):
        return game
    return RECORD_SHAPES.get(getattr(game, "key", game),
                             POOL_OF_RADIANCE_RECORD)


def span_of(names: "tuple[str, ...]") -> tuple[int, int]:
    """`(offset, size)` of a run of declared fields, refusing a gap in it."""
    fields = [_field(n) for n in names]
    at = fields[0].offset
    size = 0
    for f in fields:
        if f.offset != at + size:
            raise ValueError(
                f"{names} do not run end to end: {f.name} is at "
                f"{f.offset:#05x} and the run had reached {at + size:#05x}")
        size += f.size
    return at, size


def _set_span(rec: CharacterRecord, names: "tuple[str, ...]",
              data: bytes) -> None:
    """Write a run of bytes that crosses more than one declared field.

    `CharacterRecord.set_raw` is width-exact per field, which is what stops a
    writer running off the end of one; a region the *game* treats as one
    field and `goldbox/layout.py` declares as several needs this instead.
    """
    at, size = span_of(names)
    if len(data) != size:
        raise ValueError(f"{names} is {size} bytes; got {len(data)}")
    cursor = 0
    for name in names:
        f = _field(name)
        rec.set_raw(name, data[cursor:cursor + f.size])
        cursor += f.size


def _get_span(rec: CharacterRecord, names: "tuple[str, ...]") -> bytes:
    """Read back what :func:`_set_span` writes, in one piece."""
    span_of(names)                      # refuses a run with a hole in it
    return b"".join(rec.get_raw(n) for n in names)


def memorised_span(game=None) -> tuple[int, int]:
    """`(offset, size)` of this title's memorised-spell list.

    **Every reader of the list goes through here, and so does the writer.**
    `goldbox/layout.py` declares `spells_memorised` as the 69 bytes at
    `0x020` that all three measured titles agree about, which is not any one
    title's list: Pool of Radiance runs 81 bytes to `0x070`, Curse of the
    Azure Bonds stops at 69 because `0x065` is its second ability array, and
    Secret of the Silver Blades starts five bytes *earlier* at `0x01B` and
    runs 74.  Asking the record for the declared field instead is what lost a
    Pool of Radiance character everything past their sixteenth memorised
    spell (#268).
    """
    return span_of(record_shape(game).memorised)


def get_memorised(rec: CharacterRecord, game=None) -> bytes:
    """The whole memorised-spell list, as wide as this title reads it."""
    return _get_span(rec, record_shape(game).memorised)


def set_memorised(rec: CharacterRecord, data: bytes, game=None) -> None:
    """Write the whole list back.  `data` must be the title's own width."""
    _set_span(rec, record_shape(game).memorised, bytes(data))


#: Class name -> the C64 field holding that class's level.  The C64 indexes
#: its eight slots by the class *bit*; a class with no bit has no slot, and a
#: level for one is reported rather than written somewhere plausible.
LEVEL_FIELDS: dict[str, str] = {
    "magic-user": "level_magic_user", "cleric": "level_cleric",
    "thief": "level_thief", "fighter": "level_fighter",
    "knight": "level_knight", "paladin": "level_paladin",
    "ranger": "level_ranger",
}

#: The order the level slots are reported in: the C64's own, bit by bit.
_LEVEL_ORDER = ("level_magic_user", "level_cleric", "level_thief",
                "level_fighter", "level_knight", "level_paladin",
                "level_ranger")

#: Race code -> infravision range in feet.  The C64 stores this at `0x0D5`
#: and it is a property of the race, not of any save: DOS does not store it,
#: the Amiga derives what it needs, so the C64 writer computes it.  6 for
#: every dwarf, elf and half-elf and 0 for every human across the twelve C64
#: specimens that carry it; gnome, halfling and half-orc are PROBABLE, on
#: AD&D 1st edition giving all three the same 60 feet.
INFRAVISION = {0: 0, 1: 6, 2: 6, 3: 6, 4: 6, 5: 6, 6: 6, 7: 0}

#: How many item slots the C64 record has.
ITEM_SLOTS = 16
ITEM_SIZE = 16

#: What a player reads when a title's C64 record has no home for something
#: the source held.  **PROPOSED, not yet approved**:
#: `.claude/rules/gui-text.md` makes every word a player reads Donald's, and
#: these five are written so they can be seen running rather than only
#: described.  None names an offset, a field or a ticket.
NO_SPELL_SLOTS = (
    "How many spells each character can still cast today: this game works "
    "that out from their class and level when you make camp, so it keeps no "
    "list of it")
NO_SLOT_ARRAY_FOR = (
    "Spell slots for a {what}: the C64 game has nowhere to keep them")
SPELL_LEVELS_ABOVE_THREE = (
    "Free spell slots above third level: the C64 game keeps three levels")
NO_DUAL_CLASS = (
    "The class this character trained out of: this game does not let a "
    "character change class, so its saved games have nowhere to put it")
NO_DUAL_CLASS_SLOT = (
    "The character used to be a {what}, and the C64 game has no place in the "
    "saved game for that class")
TWO_FORMER_CLASSES = (
    "The character used to be both a {what}, and the saved game has room for "
    "only one class trained out of")

#: Neutral status name -> the low three bits of C64 record `0x100`.  The
#: C64's own enumeration, read off the routine that draws the STATUS line:
#: `LIBRARY $38BE` is `LDA $6C00 / AND #$07 / CLC / ADC #$29 / TAX`, and the
#: string table at `LIBRARY $3439`/`$347B` holds ids `$29`-`$30` as
#: HITPOINTS, OK, GONE, DEAD, DYING, UNCONSIOUS -- the game's own spelling --
#: RUNNING, STONED.  Index 0 is unreachable: zero at `0x100` means the slot
#: is **empty**, which is what DROP CHARACTER writes (`CAMP $0C0B`), so the
#: word the table holds there is never drawn.
#:
#: CONFIRMED three ways (#235): the display arithmetic above; a character an
#: orc took to 0 hit points in a driven fight, whose byte went `$01` -> `$84`
#: and then `$84` -> `$85` as the fight ended, which is what the engine
#: saved; and each of `$82`-`$87` staged into a copy of that save and read
#: back off the sheet as GONE, DEAD, UNCONSIOUS, RUNNING and STONED.
#:
#: **Two neutral names are missing from it and that is the finding, not an
#: omission**: `animated` and `temporarily gone` are DOS states with no C64
#: value.  `SPELLE04 $AA11` writes `$03` beside creature type 4, undead, for
#: Animate Dead -- but `$03` is DEAD with bit 7 clear, written on a thing the
#: same routine marks as not a player character, so it is the nearest thing
#: rather than the same thing.
STATUS_BITS: dict[str, int] = {
    "okay": 1, "gone": 2, "dead": 3, "dying": 4, "unconscious": 5,
    "running": 6, "stoned": 7,
}

#: The same table read the other way, for :func:`read`.
STATUS_BY_BITS: dict[int, str] = {v: k for k, v in STATUS_BITS.items()}

#: Bit 7 of record `0x100`, and it is a flag in its own right rather than
#: part of the status: `LIBRARY $38BE` masks it off with `AND #$07` before
#: drawing the word, `$1BF6` skips a slot carrying it when it sums the
#: party's strength, and `$3E4A` picks the greyed colour for the party panel
#: with `CMP #$80` -- and the colour it picks is **2, red**, not grey.  Set
#: means the character is out of play, which is the same thing DOS says at
#: `0x10D` with the opposite polarity, and DOS draws its own name red too.
#:
#: **CONFIRMED, and independent of the low three bits** (#235): one boot with
#: `$81` -- OK with the flag set -- beside `$05` -- unconscious with it clear
#: -- and three controls at `$01` drew OK in red for the first and UNCONSIOUS
#: in the panel's ordinary colour for the second.  Two of two red against
#: three of three not, partitioning on bit 7 and on nothing else.
OUT_OF_PLAY = 0x80

#: What a player is told when the source's status has no C64 value.
#:
#: **PROPOSED, not yet approved.** `.claude/rules/gui-text.md` makes every
#: word a player reads Donald's; this is the working proposal, written so it
#: can be seen running rather than only described.  No file offset and no
#: issue number, which `tests/test_dosconvert.py`'s two guard tests enforce
#: for the DOS table and this one follows.
NO_C64_STATUS: dict[str, str] = {
    "animated": "Animated by a spell: the character arrives "
                "as they were before it -- the C64 game has no such state, "
                "and the nearest thing it has is a dead creature the game "
                "runs as a monster rather than a member of the party",
    "temporarily gone": "Temporarily gone from the party: "
                        "the character arrives with it -- the C64 game has "
                        "no such state",
}


def strength_index(strength: int, percentile: int) -> int:
    """The C64's `strength_index`: STR below 18, else 18 plus the band.

    Equals strength below 18; 18/01-18/50 give 19 and 20, 18/80 and 18/81 give
    21, 18/98 gives 22 -- the AD&D exceptional-strength bands collapsed to one
    number.  PROBABLE, and it is computed rather than copied because no source
    port has been found to store it.
    """
    if strength != 18 or not percentile:
        return strength
    for bound, value in ((50, 19), (75, 20), (90, 21), (99, 22)):
        if percentile <= bound:
            return value
    return 23


def _clamp_nibble(n: int) -> int:
    return min(int(n), 0x0F)


def _field(name: str) -> Field:
    from . import layout as _l
    return _l.FIELDS_BY_NAME[name]


def _layout():
    from . import layout as _l
    return _l.LAYOUT


def write(char: NeutralCharacter, icon: bytes | None = None,
          ) -> tuple[CharacterRecord, Report]:
    """Build a 580-byte C64 character record from a neutral one.

    `icon` is the 36-byte combat icon.  No port outside the C64 has one -- it
    is a C64 character set -- so with none given the field is left zero and
    reported.
    """
    rec = CharacterRecord.blank()
    rep = Report()
    port = char.port
    shape = record_shape(char.game)
    w = neutral.Writer(char, rep, into="C64", dropped=DROPPED)
    use, emit = w.use, w.emit

    # -- the name: 20 NUL-padded bytes ---------------------------------------
    name = use("name")
    if name is not None:
        rec.set("name", name.value)
        emit(name, "name", 0x000, 20,
             ", re-padded to the C64's 20 NUL-padded bytes")

    for field, c64_name in DIRECT:
        v = use(field)
        if v is None:
            continue
        dst = _field(c64_name)
        rec.set(c64_name, v.value)
        emit(v, c64_name, dst.offset, dst.size)

    # -- memorised spells, into as many slots as this title has --------------
    # Written before the second ability array because in Pool of Radiance the
    # list runs *through* `0x065` and in Curse it stops just short of it.
    memorised = use("spells_memorised")
    mem_at, mem_size = span_of(shape.memorised)
    if memorised is not None:
        ids = list(memorised.value)[:mem_size]
        _set_span(rec, shape.memorised, bytes(ids) + bytes(mem_size - len(ids)))
        emit(memorised, "spells_memorised", mem_at, mem_size,
             f" (the C64 fills this title's {mem_size} slots from the start, "
             f"which is the neutral order)")
        if len(memorised.value) > mem_size:
            rep.warnings.append(
                f"{len(memorised.value)} memorised spells and this title's "
                f"C64 record has {mem_size} slots; "
                f"{len(memorised.value) - mem_size} dropped from the end")

    # -- the second ability array -------------------------------------------
    # Curse of the Azure Bonds keeps every ability twice and works in this
    # copy -- `GEN $1E9C` copies these twelve bytes forward to `0x014`, and
    # creation and the racial clamp both write here.  Pool of Radiance has no
    # such field: these seven bytes are part of its memorised list, written
    # above.
    second = use("abilities_second")
    if shape.second_abilities:
        if second is not None:
            rec.set_raw("abilities_second",
                        bytes(second.value.get(n, 0) & 0xFF
                              for n in neutral.ABILITIES))
            emit(second, "abilities_second", 0x065, 7,
                 ", the copy this title's engine works in; 0x014 is the copy "
                 "it makes of this one")
        else:
            rec.set_raw("abilities_second",
                        bytes(w.get(n, 0) & 0xFF for n in neutral.ABILITIES))
            rep.note(0x065, 7,
                     f"abilities_second: the same seven scores again, because "
                     f"{port} gave only one copy and this title's engine "
                     f"works in this one")

    # -- the spellbook: as many bits as the title's mask has ------------------
    # Seven bytes on Pool of Radiance, thirteen on Curse, sixteen on Silver
    # Blades. The title is the neutral record's own, so a Silver Blades
    # character written back keeps the spells the reader found -- the read half
    # widened in #85 and this is the other end of it.
    #
    # UNAPPROVED WORDING: the warning below is reworded, because "the C64's
    # seven-byte mask" is not true of every title. Donald has not seen it.
    known = use("spells_known")
    if known is not None:
        table = spells.for_game(char.game)
        ceiling = table.last_spellbook_spell
        converted = [i for i in known.value if i <= ceiling]
        spells.write_spellbook(rec, converted, char.game)
        emit(known, "spells_known", 0x078, table.spellbook_size,
             " packed to one bit; ids are identical")
        for i in known.value:
            if i > ceiling:
                rep.warnings.append(
                    f"Spell id {i} is set in the {port} spellbook and "
                    f"{table.title}'s {table.spellbook_size}-byte mask has no "
                    f"bit for it (ids 1-{ceiling})"
                    + ("; id 56 is RESTORATION"
                       if table is spells.POOL_OF_RADIANCE else ""))

    # -- the per-class level array: indexed by the class bit -----------------
    levels = use("levels")
    if levels is not None:
        for name_, level in levels.value.items():
            field = LEVEL_FIELDS.get(name_)
            if field is None:
                if level:
                    rep.warnings.append(
                        f"{port} carries {name_} level {level}, and the C64's "
                        f"eight-slot array has no {name_} slot")
                continue
            rec.set(field, level)
        for f in _LEVEL_ORDER:
            dst = _field(f)
            emit(levels, f, dst.offset, dst.size)
    rep.note(0x0CE, 1, "the C64's unused sixth level slot: zero")

    # -- spell slots: three packed nibbles, cleric high, magic-user low ------
    castable = use("spells_castable")
    if castable is not None and shape.spell_slots:
        cleric = castable.value.get("cleric", (0, 0, 0))
        mage = castable.value.get("magic-user", (0, 0, 0))
        packed = bytes((_clamp_nibble(cleric[i]) << 4) | _clamp_nibble(mage[i])
                       for i in range(3)) + bytes(3)
        rec.set_raw("spells_castable", packed)
        emit(castable, "spells_castable", 0x0EE, 6,
             ", repacked cleric-high/magic-user-low")
        for name_ in castable.value:
            if name_ not in ("cleric", "magic-user"):
                rep.dropped.append(NO_SLOT_ARRAY_FOR.format(what=name_))
        if any(len(v) > 3 for v in castable.value.values()):
            rep.dropped.append(SPELL_LEVELS_ABOVE_THREE)
    elif castable is not None:
        rep.dropped.append(NO_SPELL_SLOTS)

    # -- the class a dual-classed human left --------------------------------
    # One class and one level, where the source keeps a whole second level
    # array: `dual_class_level` is the pair's sentinel, so zero there means
    # "not dual-classed" whatever `dual_class_slot` holds, and a character
    # who left two classes cannot be spelled at all.
    former = use("former_levels")
    if former is not None:
        held = {n: lv for n, lv in former.value.items() if lv}
        if not held:
            pass                                  # not dual-classed: zero
        elif not shape.dual_class:
            rep.dropped.append(NO_DUAL_CLASS)
        elif len(held) > 1:
            rep.dropped.append(TWO_FORMER_CLASSES.format(
                what=", ".join(sorted(held))))
        else:
            name_, level = next(iter(held.items()))
            field = LEVEL_FIELDS.get(name_)
            if field is None:
                rep.dropped.append(NO_DUAL_CLASS_SLOT.format(what=name_))
            else:
                slot = _field(field).offset - _field("level_magic_user").offset
                rec.set("dual_class_slot", slot)
                rec.set("dual_class_level", level)
                emit(former, "dual_class_slot", 0x0B9, 2,
                     f", as slot {slot} ({name_}) of the C64's level array "
                     f"and the level {level} it was left at")

    # -- size ----------------------------------------------------------------
    size = use("size_small")
    if size is not None:
        rec.set("size_small", size.value)
        emit(size, "size_small", 0x099, 1)

    # -- turning: the C64 has two bytes --------------------------------------
    rep.note(0x0A3, 1, "turn_class: zero -- no player character is undead")
    turning = use("turn_power")
    if turning is not None:
        rec.set("turn_power", turning.value)
        emit(turning, "turn_power", 0x0A4, 1,
             " (PROBABLE: which of the C64's two turning bytes this is cannot "
             "be told from a party with no turning cleric above level 3)")

    # -- attack forms: eight bytes -------------------------------------------
    forms = use("attack_forms")
    if forms is not None:
        rec.set_raw("attack_forms", bytes(forms.value))
        emit(forms, "attack_forms", 0x0D9, 8)

    # -- computed, not copied ------------------------------------------------
    # `w.get`, not `char.get`: the floor applies to a derivation as much as
    # to a copy, so a refused race yields infravision 0 and not a value
    # computed from a grade this conversion would not write.
    rec.set("infravision", INFRAVISION.get(w.get("race", 0), 0))
    rep.note(0x0D5, 1,
             f"infravision: computed from race; {port} does not store it")
    rec.set("strength_index", strength_index(w.get("strength", 0),
                                             w.get("exceptional_strength",
                                                   0)))
    rep.note(0x0E2, 1, f"strength_index: computed from strength and the "
                       f"percentile; the {port} byte at the aligned offset is "
                       f"a different field")
    # The index above is inert without this: `LIBRARY $375C` reads 0x0E3 and
    # indexes the AD&D strength tables at $3651/$3670 with 0 unless it is
    # non-zero, so a converted fighter with 18/75 swung at no bonus to hit and
    # did no bonus damage the moment the engine next rebuilt his roster block
    # (#277).  One is what `GEN $0B79` writes for every character it creates,
    # and it is what every engine-made player character on the C64 disks of
    # all three titles holds; the monsters that share the record layout are
    # the only things that read zero, and this writer never builds one.
    rec.set("strength_bonus_flag", 1)
    rep.note(0x0E3, 1, "strength_bonus_flag: 1, the value the C64's own "
                       "character creation writes -- without it the engine "
                       "gives no strength bonus to hit or to damage")

    # -- innate effects and item grants: ten shared trait slots --------------
    # `docs/171-c64-trait-slots.md` (#252): a trait slot is one byte meaning
    # "this character has effect N", with no owner and no record of who wrote
    # it -- the engine applies an id written here exactly where it would
    # apply one its own READY wrote (watched: 98 regenerated a wounded
    # character three a round, and a fire spell hit a 61-carrier for less
    # damage, both with the id staged by this project rather than granted by
    # the game).  Racial ids fill from slot 0, the way `GEN` seeds them at
    # creation; item-granted ids fill from slot 9 down, the way
    # `SPELLE04 $ADD4` itself scans for a free slot when an item is readied.
    #
    # The value an effect is worth and the flag DOS reads on removal have no
    # C64 counterpart to write, and need none: the C64's own un-ready
    # (`SPELLE04 $AE13`) finds the id in the ten slots and clears it, nothing
    # else, and for every item power that uses a trait slot the id is the
    # whole effect -- the handler holds the magnitude, not the record.
    innate = use("innate_effects")
    granted = use("granted_effects")
    if innate is not None or granted is not None:
        slots = [0] * 10
        innate_ids = list(innate.value) if innate is not None else []
        for i, e in enumerate(innate_ids[:10]):
            slots[i] = e
        granted_ids = ([int(node[0]) for node in granted.value]
                       if granted is not None else [])
        free = [i for i in range(9, -1, -1) if slots[i] == 0]
        for i, e in zip(free, granted_ids):
            slots[i] = e
        rec.set_raw("item_effects", bytes(slots))
        # Each field claims only the bytes it actually placed. Both used to
        # claim the whole ten, and `Report.note` assigns per offset, so the
        # second call erased the first: an elf wearing a ring came out with
        # the two bytes holding his *racial* ids attributed to the ring.
        # `docs/117-save-conversion.md` calls `Report.sources` "the test that
        # replaces a round trip: for any offset in the output, say where that
        # byte came from", so a wrong answer there is a wrong answer to the
        # question the writer exists to answer, even though no byte of the
        # save moves.
        taken = [i for i, _ in zip(free, granted_ids)]
        if innate is not None:
            emit(innate, "item_effects", 0x0AD, len(innate_ids[:10]))
        if granted is not None:
            emit(granted, "item_effects",
                 0x0AD + (min(taken) if taken else 0), len(taken),
                 "; the id is the whole of what the item's own READY would "
                 "write (#252, docs/171-c64-trait-slots.md) -- the value and "
                 "the removal flag the other ports keep beside it have no "
                 "C64 counterpart, because the C64 removes by id alone and "
                 "its handler holds the magnitude")
        if len(innate_ids) > 10:
            rep.warnings.append(
                f"{len(innate_ids)} innate effects and the C64 has ten "
                f"slots; {len(innate_ids) - 10} dropped from the end")
        if len(granted_ids) > len(free):
            rep.warnings.append(
                f"{len(granted_ids)} item-granted effects and only "
                f"{len(free)} free trait slots after the innate ones; "
                f"{len(granted_ids) - len(free)} dropped from the end")

    # -- the inventory: sixteen fixed slots ----------------------------------
    inventory = use("inventory")
    if inventory is not None:
        converted = list(inventory.value)
        inv = bytearray(ITEM_SLOTS * ITEM_SIZE)
        for n, item in enumerate(converted[:ITEM_SLOTS]):
            inv[n * ITEM_SIZE:(n + 1) * ITEM_SIZE] = item
        rec.set_raw("inventory", bytes(inv))
        emit(inventory, "inventory", 0x120, 256)
        if len(converted) > ITEM_SLOTS:
            rep.warnings.append(
                f"{len(converted)} items and the C64 has sixteen slots; "
                f"{len(converted) - ITEM_SLOTS} dropped from the end")

    # -- the combat icon: only the C64 has one -------------------------------
    if icon is not None:
        rec.set_raw("region_220", bytes(icon))
        rep.note(0x220, 36, "combat icon: supplied")
    else:
        rep.note(0x220, 36, f"combat icon: zero. {port} has no C64 charset "
                            f"icon; goldbox/iconparts.py can compose a legal one")
        rep.dropped.append("the combat icon: C64 icons are 18 CHARPIC00 "
                           "screen codes plus 18 colours and "
                           f"{port} has no equivalent")

    # -- fields with no source, written as documented constants --------------
    rep.note(0x0B8, 1, "flags_0b8: zero -- a player character, bit 7 clear")

    # -- the sheet portrait: the art's own id, both ports' one menu ----------
    # The C64 fetches `HEAD<xx>` and `BODY<xx>` by these two bytes, measured
    # in the running game: six of six converted characters fetched their own
    # art (#57).  A source that gave no id leaves the byte zero, and zero is
    # a real portrait -- `HEAD00` is the first entry of the menu -- so a
    # character with no id is reported rather than quietly given that face.
    both = True
    for name, offset, stem in (("portrait_head", 0x0FE, "HEAD"),
                               ("portrait_body", 0x0FF, "BODY")):
        v = use(name)
        if v is None:
            both = False
            rep.dropped.append(
                f"the character sheet's portrait {stem[:4].lower()}: "
                f"{port} gave none, so the sheet draws no face")
        else:
            rec.set(name, v.value)
            emit(v, name, offset, 1, f"{stem}{v.value:02X}")
    rep.has_portrait = both

    # -- the status, and the out-of-play flag packed above it -----------------
    # One byte holding two things: the low three bits are the state the sheet
    # puts into words (:data:`STATUS_BITS`) and bit 7 is whether the game is
    # still playing the character (:data:`OUT_OF_PLAY`).  Writing a hard 1
    # here is what brought a dead DOS character across alive (#235).
    #
    # The two neutral fields are taken separately because the sources hold
    # them separately -- DOS at 0x10C and 0x10D -- and a source that supplies
    # a status and no `active` gets bit 7 from the status instead: every
    # value the six C64 overlays are seen to write for a party member carries
    # it for every state but OK, and a DOS record the engine wrote pairs the
    # two the same way.  `$03`, DEAD with bit 7 clear, is written only by
    # Animate Dead on a thing the same routine marks as not a player
    # character.
    status, active = use("status"), use("active")
    bits = STATUS_BITS["okay"]
    where = ["1 (OK), the state a character with no source for one is in"]
    if status is not None:
        found = STATUS_BITS.get(status.value)
        if found is None:
            rep.dropped.append(
                NO_C64_STATUS.get(
                    status.value,
                    f"{status.value.capitalize()}: the "
                    f"character arrives well -- the C64 game has no such "
                    f"state"))
            where = [f"1 (OK): {status.value} has no C64 value"]
        else:
            bits = found
            where = [f"{found} ({status.value}) <- {status.origin}"]
        rep.dropped.extend(status.dropped)
    in_play = active.value if active is not None else bits == STATUS_BITS["okay"]
    if active is not None:
        where.append(f"bit 7 {'clear' if in_play else 'set'} <- {active.origin}")
        rep.dropped.extend(active.dropped)
    else:
        where.append(f"bit 7 {'clear' if in_play else 'set'}: computed from "
                     f"the status, which is how every value the C64 engine "
                     f"writes for a party member pairs the two")
    byte = bits | (0 if in_play else OUT_OF_PLAY)
    rec.set("roster_in_use", byte)
    rep.note(0x100, 1, f"roster status ${byte:02X}: " + ", ".join(where))

    # -- the combat side and quickfight flag, packed into one byte -----------
    # Bit 0 is the side the character fights on (0 the party's, 1 the
    # enemy's) and bit 7 is quickfight, set by QUICK and never cleared
    # (goldbox-bugs.md bug 3).  DOS keeps the same two flags separately at
    # 0x10E and 0x10F -- the DOS engine's own script-field accessor converts
    # between the two shapes, which is what fixes this byte's meaning
    # (docs/169-dos-combat-side.md, #235).  A source supplying neither writes
    # 0x00, which is what every fresh C64 character holds.
    hostile, quickfight = use("hostile"), use("quickfight")
    side_bits = 0
    side_where: list[str] = []
    for value, bit, label in ((hostile, 0x01, "bit 0"),
                              (quickfight, 0x80, "bit 7")):
        if value is not None:
            if value.value:
                side_bits |= bit
            side_where.append(
                f"{label} {'set' if value.value else 'clear'} <- "
                f"{value.origin}")
            rep.dropped.extend(value.dropped)
    rec.set("combat_side", side_bits)
    rep.note(0x10C, 1, f"combat side ${side_bits:02X}: " +
             (", ".join(side_where) if side_where else
              "no source for the combat side or quickfight, written 0"))
    tail = use("roster_tail")
    if tail is not None:
        rec.set_raw("roster_tail", bytes(tail.value))
        emit(tail, "roster_tail", 0x110, 9)

    # -- the identity draw: a home instead of a drop --------------------------
    # GEN draws two bytes at 0x0E6-0x0E7 at creation and nothing on the C64
    # reads them back; DOS's own 0x0AB is the same field on one byte (#258,
    # docs/170-c64-identity-pair.md).  Only Pool of Radiance's GEN draws the
    # pair -- Curse of the Azure Bonds and Secret of the Silver Blades never
    # write it -- so a source with a value and a title with nowhere to put it
    # is reported rather than written.
    identity = use("unnamed_0ab")
    if identity is not None and shape.identity_pair:
        rec.set_raw("identity_pair", bytes([int(identity.value) & 0xFF, 0]))
        emit(identity, "identity_pair", 0x0E6, 2,
             "; 0x0E7 is the pair's second byte, which nothing on the C64 "
             "reads back")
    elif identity is not None:
        rep.dropped.append(
            "the identity byte: this title's GEN never draws the identity "
            "pair, so there is nowhere on the C64 to put it")

    # -- the closing sweep: unwritten fields, then the reader's own drops ----
    w.finish()

    # Everything still unnamed is a byte the C64 record does not use: the
    # unknown gaps of goldbox/layout.py, which are zero in every specimen we hold.
    for f in _layout():
        for i in range(f.offset, f.end):
            rep.sources.setdefault(
                i, f"{f.name}: zero (UNKNOWN on the C64 side and zero in "
                   f"every specimen)" if not f.is_known
                   else f"{f.name}: zero (no {port} source)")
    return rec, rep



# ---------------------------------------------------------------------------
# What the C64 writer does with every neutral field
# ---------------------------------------------------------------------------
#: Neutral fields the writer takes by a rule rather than by a copy.
TRANSFORMED: tuple[tuple[str, str], ...] = (
    ("name", "re-padded into the C64's 20 NUL-padded bytes at 0x000"),
    ("levels", "permuted onto the C64's eight slots, which are indexed by the "
               "class bit; a class with no bit is reported"),
    ("spells_known", "packed into the C64 mask at 0x078, as many bytes of it "
                     "as the title uses; an id past the last the mask has a "
                     "bit for is warned about"),
    ("spells_memorised", "into the slots the title's own C64 record has, "
                         "filled from the start: 81 in Pool of Radiance and "
                         "69 in Curse of the Azure Bonds"),
    ("spells_castable", "repacked cleric-high/magic-user-low into three "
                        "bytes, in the titles whose C64 record has the "
                        "array; reported in the ones that do not"),
    ("abilities_second", "written to the second ability array in the titles "
                         "that keep one, and part of the memorised list in "
                         "Pool of Radiance, which does not"),
    ("former_levels", "the one class with a level becomes the C64's "
                      "dual_class_slot and dual_class_level; two would be "
                      "reported"),
    ("size_small", "copied to the C64's size byte"),
    ("turn_power", "copied to the C64's caster turning byte at 0x0A4"),
    ("attack_forms", "copied as a block to 0x0D9"),
    ("innate_effects", "the first ten ids, into the C64's trait slots; the "
                       "rest are warned about"),
    ("granted_effects", "each id, into a free trait slot after the innate "
                        "ones, filled from slot 9 down the way the item's "
                        "own READY would fill it (#252); the rest are warned "
                        "about. The record's duration, value and removal "
                        "flag have no C64 counterpart and need none -- see "
                        "the write itself. Not something the C64 reader can "
                        "give back as this name, because a trait slot the "
                        "converter filled and one READY filled are the same "
                        "byte to the engine's own compare"),
    ("inventory", "the first sixteen items, into the C64's fixed slots; the "
                  "rest are warned about"),
    ("roster_tail", "copied as a block into the C64's roster tail"),
    ("status", "the name indexed into the C64's own seven-value table, into "
               "the low three bits of record 0x100; a state the C64 does not "
               "have is reported and the character arrives OK"),
    ("active", "bit 7 of that same byte, set when the character is out of "
               "play -- the opposite polarity to DOS's own flag"),
    ("hostile", "bit 0 of record 0x10C -- 0 the party's side, 1 the enemy's"),
    ("quickfight", "bit 7 of the same byte, set by QUICK and never cleared"),
    # #57: the two ports share one 14-head, 12-body menu, byte for byte, in
    # both binaries -- so the neutral value is already the C64's own art id
    # and this is a copy, not a table lookup.  Kept out of `DIRECT` because a
    # source that gives no id is reported with its own sentence rather than
    # left to `DIRECT`'s silent `continue`; see the write itself.
    ("portrait_head", "the art's own id, copied to 0x0FE; a character with no "
                      "id gets none written and the sheet draws no face"),
    ("portrait_body", "the art's own id, copied to 0x0FF -- see "
                      "portrait_head"),
    ("unnamed_0ab", "the first byte into the C64's identity_pair at 0x0E6, "
                    "second byte zero; reported instead in Curse of the "
                    "Azure Bonds or Secret of the Silver Blades, whose GEN "
                    "never draws the pair (#258, The C64 side of 0x0AB is "
                    "unnamed, so the conversion drops it with no issue "
                    "behind it)"),
)

#: Neutral fields the C64 writer takes nothing from, and why.  Reported by
#: `Writer.finish` for any character that carries one, never silent.
DROPPED: tuple[tuple[str, str], ...] = (
    ("infravision", "the C64 computes its own from race, so a source's value "
                    "is recomputed rather than copied"),
    ("npc", "0x0B8 is written as a player character with bit 7 clear; which "
            "roster slot a character lands in is the destination save's "
            "business"),
    ("encumbrance", "derived -- the C64 has no such field and recomputes what "
                    "it needs"),
)


def field_disposition() -> dict[str, str]:
    """Every neutral field and what :func:`write` does with it.

    The neutral-vocabulary twin of `goldbox.dos.field_disposition`, which asks the
    same question of the DOS layout.  `Writer.finish` catches a value no
    writer took one character at a time; this catches a *name* the writer has
    never been taught, which is the failure that rots silently -- a field
    added to `goldbox/neutral.py`'s `FIELDS` and never wired up here.
    """
    return neutral.disposition(DIRECT, TRANSFORMED, DROPPED,
                               "the C64 record's")


# ---------------------------------------------------------------------------
# The reading half: a C64 record becomes a neutral character
# ---------------------------------------------------------------------------
#: A save slot holds 256 of the record's 580 bytes; the roster block and the
#: item page hold the rest.  So the reader takes them as separate arguments,
#: the way :func:`write` takes the combat icon -- a C64 "character" is spread
#: across three places and only a `.chr` file has it in one.
#:
#: C64 fields this reader deliberately leaves behind, and why.
READ_DROPPED: tuple[tuple[str, str], ...] = (
    ("strength_bonus_flag", "the strength-adjustment gate LIBRARY's roster "
                            "recompute reads at 0x0E3. Every character any "
                            "port creates holds 1 there -- GEN writes it at "
                            "creation and only the monsters that share the "
                            "record layout read 0 -- so `write` sets it from "
                            "the same rule rather than from a source value, "
                            "and a C64 record read here and written back "
                            "keeps it (#277, A DOS character converted to the "
                            "C64 loses the strength bonus to hit and damage, "
                            "because 0x0E3 is written zero)"),
    ("abilities_second", "not a field of its own in Pool of Radiance -- these "
                         "seven bytes are part of that title's memorised list "
                         "and are read with it (#268), and they are zero in "
                         "every Pool of Radiance specimen. In Curse of the "
                         "Azure Bonds and Silver Blades it is the second "
                         "ability array and the reader takes it whole"),
    ("turn_class", "zero for every player character -- the undead's row, not "
                   "the caster's"),
    ("strength_index", "derived from strength and the percentile; a writer "
                       "that wants it recomputes it"),
    ("dual_class_slot", "the class a dual-classed human left, and "
                        "dual_class_level the level it was left at. Zero in "
                        "every Pool of Radiance specimen because that title's "
                        "code never references either byte -- the pair is "
                        "Curse, Silver Blades and Gateway's (#224). **This is "
                        "a defect, not an exemption**: no DOS field has been "
                        "attributed to it, so a dual-classed Curse character "
                        "converted to DOS would lose its old class. What "
                        "settles it is one DOS Curse save of a dual-classed "
                        "human, diffed against the same character before the "
                        "change, which names the DOS byte"),
    ("dual_class_level", "see dual_class_slot: the two are one field with a "
                         "sentinel, and neither has a DOS home yet"),
    ("region_220", "the combat icon: 18 CHARPIC00 screen codes and 18 "
                   "colours, a C64 character set no other port can draw"),
    ("missile_attack_adjustment",
     "a cache of what dexterity is worth to hit at range. COM.PREP $1633 "
     "rebuilds it from the record's own dexterity, which is carried, at the "
     "start of every fight and before anything reads it (#202)"),
)

#: What :func:`read` does with every named field of the C64 layout -- the
#: layout-wide account the DOS writer of #26 called for, so a C64 field
#: nothing reads cannot be dropped in silence.  `tests/test_doswriter.py`
#: checks it against `goldbox/layout.py`'s named fields.
READ_TARGETS: dict[str, str] = (
    {c64_name: f"read as neutral {n}" for n, c64_name in DIRECT}
    | {"name": "read as neutral name",
       "spells_known": "the spellbook mask's low seven bytes, unpacked into "
                       "neutral spells_known",
       "spells_known_high": "the same mask's high nine bytes, 0x07F-0x087, "
                            "unpacked into the same neutral spells_known. How "
                            "far into them the reader goes is the title's "
                            "goldbox.spells.SpellTable.spellbook_size -- 7, 13 or "
                            "16 -- so Pool of Radiance reads none of them and "
                            "Curse stops at 0x084",
       "spells_memorised": "zeroes stripped into neutral spells_memorised, "
                           "over the span goldbox.c64_codec.memorised_span "
                           "gives for the title -- 81 bytes from 0x020 in "
                           "Pool of Radiance, 69 in Curse of the Azure Bonds, "
                           "74 from 0x01B in Secret of the Silver Blades -- "
                           "and not the declared field's 69 (#268)",
       "spells_castable": "nibbles unpacked into neutral spells_castable",
       "item_effects": "zeroes stripped into neutral innate_effects",
       "flags_0b8": "bit 7 read as neutral npc",
       "attack_forms": "read as neutral attack_forms",
       "infravision": "read as neutral infravision",
       "turn_power": "read as neutral turn_power",
       "size_small": "read as neutral size_small",
       "portrait_head": "read as neutral portrait_head",
       "portrait_body": "read as neutral portrait_body",
       "roster_in_use": "the low three bits read as neutral status and bit 7 "
                        "as neutral active; zero is an empty roster slot and "
                        "is neither",
       "combat_side": "bit 0 read as neutral hostile and bit 7 as neutral "
                      "quickfight",
       "roster_tail": "read as neutral roster_tail, from the roster block's "
                      "+0x10-+0x18 or the record",
       "inventory": "read as neutral inventory, from the save's item page "
                    "or the record's sixteen slots",
       "identity_pair": "the first byte read as neutral unnamed_0ab, in "
                        "Pool of Radiance only; Curse of the Azure Bonds "
                        "and Secret of the Silver Blades never draw it "
                        "(#258)"}
    | {f: "read into neutral levels, named by the class bit"
       for f in _LEVEL_ORDER}
    | {name: f"dropped: {why}" for name, why in READ_DROPPED}
)


def read(rec: CharacterRecord, roster=None, inventory=None,
         game=None, source: str | None = None) -> NeutralCharacter:
    """Read one C64 record into the neutral record.

    `roster` is the character's roster block, which is where a *save slot*
    keeps the four current combat numbers -- a slot record stores only 256 of
    the 580 bytes and stops short of them.  `inventory` is the sixteen-byte
    item records off the save's item page, for the same reason.  Either may be
    None, and then the value is read from `rec` when it holds it and left
    unset when it does not: a field nobody supplied is absent rather than
    zero, so a writer reports it instead of writing a plausible nothing.

    `game` is the title whose race and class tables the record's indices are
    in; it travels on the neutral record so a writer can name them.
    """
    out = NeutralCharacter("C64", source=source, game=game)
    shape = record_shape(game)

    def grade(name: str) -> Confidence:
        return _field(name).confidence

    def origin(name: str) -> str:
        f = _field(name)
        return f"C64 {name} @{f.offset:#05x} ({f.confidence})"

    def copy(neutral_name: str, c64_name: str) -> None:
        if rec.is_stored(c64_name):
            out.set(neutral_name, rec.get(c64_name), origin(c64_name),
                    grade(c64_name))

    out.set("name", rec.get("name"),
            "the C64's 20 NUL-padded bytes at 0x000", grade("name"),
            Provenance.RESHAPED)

    for neutral_name, c64_name in DIRECT:
        copy(neutral_name, c64_name)

    # -- what a save slot stops short of, from the roster block --------------
    # The block's own accessors decode the family's 60 - value bias into the
    # number on the sheet; the neutral convention is the *stored* byte, the
    # one every record path carries.  Handing the decoded value through here
    # is what made a converted DOS character display AC 51 for AC 9 -- the
    # first live C64-to-DOS run caught it.
    if roster is not None:
        for neutral_name, c64_name, value in (
                ("hp_current", "hp_current", roster.hit_points),
                ("thac0_current", "thac0", COMBAT_BIAS - roster.thac0),
                ("armour_class", "armour_class",
                 COMBAT_BIAS - roster.armour_class),
                ("movement_current", "roster_movement", roster.movement)):
            out.set(neutral_name, value,
                    f"the C64 roster block's {c64_name}", grade(c64_name))
        # The block also holds the nine-byte combat tail -- the armour bonus
        # and the eight running attack-form bytes -- which a slot record
        # stops short of.  Leaving it behind wrote zeros into the DOS combat
        # tail on the first C64-to-DOS conversion.
        out.set("roster_tail", roster.raw[0x10:0x19],
                "the C64 roster block's +0x10-+0x18: the armour bonus and "
                "the eight running attack-form bytes",
                grade("roster_tail"))
        out.drop("C64 roster +0x03-0x05: the roster's own derived bytes, "
                 "with no neutral field to hold them")

    copy("infravision", "infravision")
    copy("turn_power", "turn_power")
    copy("size_small", "size_small")
    copy("portrait_head", "portrait_head")
    copy("portrait_body", "portrait_body")

    out.set("npc", rec.is_npc, "bit 7 of the C64's 0x0B8, the byte the game "
            "itself counts player characters with", grade("flags_0b8"))

    # -- the status byte, unpacked into the two things it holds --------------
    # Zero is not a state: it is an **empty roster slot**, which is what DROP
    # CHARACTER writes, so a record holding it says nothing about a character
    # and neither field is set.  A low three bits of 0 with bit 7 set is the
    # same nothing wearing the flag, and has never been seen.
    #
    # A save *slot* stores only the record's first 256 bytes and this byte is
    # at 0x100, one past that -- so `rec.is_stored` is False for every real
    # save and this never fired at all until the roster block's own copy of
    # the same byte was read instead (#281, A dead character on a C64 save
    # converts to DOS alive, because the reader never reads the four bytes
    # past 0x100).
    if roster is not None:
        raw, roster_in_use_origin = (roster.roster_in_use,
                                      "the C64 roster block's roster_in_use")
    elif rec.is_stored("roster_in_use"):
        raw, roster_in_use_origin = (rec.get("roster_in_use"),
                                      "C64 record 0x100")
    else:
        raw = None
    if raw is not None:
        name = STATUS_BY_BITS.get(raw & 0x07)
        if name is not None:
            out.set("status", name,
                    f"the low three bits of {roster_in_use_origin}, "
                    f"${raw:02X}, indexed into the game's own seven status "
                    f"words",
                    grade("roster_in_use"), Provenance.RESHAPED)
            out.set("active", not raw & OUT_OF_PLAY,
                    f"bit 7 of {roster_in_use_origin}, ${raw:02X} -- set "
                    f"means the party panel greys the name and the party's "
                    f"strength leaves the character out",
                    grade("roster_in_use"), Provenance.RESHAPED)
        elif raw:
            out.drop("The character's state: this save holds a value the "
                     "game reads as an empty roster slot, which is not one "
                     "of the states it can put into words")

    # -- the combat side and quickfight flag, unpacked from one byte ---------
    # Same reason: 0x10C is past the 256 a slot stores, so this is the C64
    # roster block's own copy when there is one (#281).
    if roster is not None:
        raw, combat_side_origin = (roster.combat_side,
                                    "the C64 roster block's combat_side")
    elif rec.is_stored("combat_side"):
        raw, combat_side_origin = rec.get("combat_side"), "C64 record 0x10C"
    else:
        raw = None
    if raw is not None:
        out.set("hostile", bool(raw & 0x01),
                f"bit 0 of {combat_side_origin}, ${raw:02X}",
                grade("combat_side"), Provenance.RESHAPED)
        out.set("quickfight", bool(raw & 0x80),
                f"bit 7 of {combat_side_origin}, ${raw:02X}",
                grade("combat_side"), Provenance.RESHAPED)

    # As wide as the *title's* mask, not as wide as Pool of Radiance's. Seven
    # bytes stop at id 55, which cost MORGAINE five of her twenty-nine spells
    # and PAINE all four of his -- issue #85.
    out.set("spells_known", spells.spells_known(rec.to_bytes(), game),
            f"the C64's spellbook mask @0x078, "
            f"{spells.for_game(game).spellbook_size} bytes on this title, "
            f"unpacked to ids", grade("spells_known"))
    # As wide as this title's own list, which is not the declared field: Pool
    # of Radiance reads 81 bytes from 0x020 and Silver Blades 74 from 0x01B.
    # Asking the record for `spells_memorised` cost a Pool of Radiance cleric
    # 6 / magic-user 6 everything past their sixteenth spell (#268).
    mem_at, mem_size = memorised_span(game)
    out.set("spells_memorised",
            [b for b in get_memorised(rec, game) if b],
            f"the C64's {mem_size} slots @{mem_at:#05x}, zeroes stripped",
            grade("spells_memorised"))

    out.set("levels",
            {name: rec.get(field) for name, field in LEVEL_FIELDS.items()},
            "the C64's level slots @0x0C9, named by the class bit that "
            "indexes them", grade("level_magic_user"))

    packed = rec.get_raw("spells_castable")
    out.set("spells_castable",
            {"cleric": tuple(b >> 4 for b in packed[:3]),
             "magic-user": tuple(b & 0x0F for b in packed[:3])},
            "the C64's three packed bytes @0x0EE, cleric high nibble and "
            "magic-user low", grade("spells_castable"))

    # Both fields arrived with #192 (Convert a Curse of the Azure Bonds DOS
    # save into a C64 one, which the importer refuses today)'s container work
    # and `write()` takes both, so the reader has to supply them or a record
    # cannot survive its own round trip.  Neither is stored in every title:
    # `abilities_second` is Curse's and Silver Blades' second array, and
    # `former_levels` is the pair a dual-classed character carries.
    # Only in a title that has one. In Pool of Radiance these seven bytes are
    # part of the memorised list read above, and reading them here as well
    # would put seven spell ids into the neutral record's ability array.
    if shape.second_abilities and rec.is_stored("abilities_second"):
        out.set("abilities_second",
                dict(zip(neutral.ABILITIES, rec.get_raw("abilities_second"))),
                "the second ability array @0x065", grade("abilities_second"))
    if rec.is_stored("dual_class_slot") and rec.get("dual_class_slot") != 0xFF:
        out.set("former_levels", {rec.get("dual_class_slot"):
                                  rec.get("dual_class_level")},
                "the class the character trained out of, from the C64's "
                "dual-class pair", grade("dual_class_slot"))

    out.set("attack_forms", rec.get_raw("attack_forms"),
            origin("attack_forms"), grade("attack_forms"))
    out.set("innate_effects",
            [b for b in rec.get_raw("item_effects") if b],
            "the C64's ten trait slots @0x0AD, zeroes stripped; racial "
            "abilities and item powers share one id namespace and the slots "
            "do not say which is which", grade("item_effects"))

    if inventory is not None:
        out.set("inventory", [bytes(i) for i in inventory],
                "the save's item page, one sixteen-byte record each",
                grade("inventory"))
    elif rec.is_stored("inventory"):
        raw = rec.get_raw("inventory")
        out.set("inventory",
                [raw[n * ITEM_SIZE:(n + 1) * ITEM_SIZE]
                 for n in range(ITEM_SLOTS)
                 if any(raw[n * ITEM_SIZE:(n + 1) * ITEM_SIZE])],
                "the C64's sixteen fixed slots @0x120, the empty ones "
                "stripped", grade("inventory"))

    if rec.is_stored("roster_tail") and "roster_tail" not in out:
        out.set("roster_tail", rec.get_raw("roster_tail"),
                origin("roster_tail"), grade("roster_tail"))

    # -- the identity pair: Pool of Radiance's alone --------------------------
    # GEN draws two bytes at 0x0E6-0x0E7 at creation and nothing on the C64
    # reads them back (#258, docs/170-c64-identity-pair.md); only the first
    # is DOS's own 0x0AB, and only Pool of Radiance's GEN draws the pair at
    # all -- Curse of the Azure Bonds and Secret of the Silver Blades hold
    # `00 00` in every shipped party because their GEN never writes it.
    if shape.identity_pair and rec.is_stored("identity_pair"):
        out.set("unnamed_0ab", rec.get_raw("identity_pair")[0],
                "the C64's identity pair @0x0E6, the first byte",
                grade("identity_pair"))

    for name, why in READ_DROPPED:
        out.drop(f"C64 {name}: {why}")
    return out
