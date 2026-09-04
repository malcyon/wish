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
    "field_disposition",
    "DIRECT",
    "TRANSFORMED",
    "DROPPED",
]


@dataclasses.dataclass
class Report(neutral.Report):
    """A C64 conversion's provenance: **every** byte has to be explained.

    Not merely the non-zero ones.  A zero the C64 record wants is as much a
    decision as a value copied into it, and `docs/117-save-conversion.md`
    makes accounting for all 580 the test that replaces a round trip.
    """

    total: int = RECORD_SIZE

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

    # -- the second ability array -------------------------------------------
    # Seven zeroes in every Pool of Radiance specimen, and Curse's importer
    # writes both halves of every (base, current) pair. Zero is what a Pool of
    # Radiance C64 record holds, so zero is what we write.
    rep.note(0x065, 7, "abilities_second: zero, as in every C64 Pool of "
                       "Radiance specimen")

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
        carried = [i for i in known.value if i <= ceiling]
        spells.write_spellbook(rec, carried, char.game)
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

    # -- memorised spells: sixteen slots, filled from the start --------------
    memorised = use("spells_memorised")
    if memorised is not None:
        mem = list(memorised.value)[:16]
        rec.set_raw("spells_memorised", bytes(mem) + bytes(16 - len(mem)))
        emit(memorised, "spells_memorised", 0x020, 16,
             " (the C64 fills its sixteen slots from the start, which is the "
             "neutral order)")

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
    if castable is not None:
        cleric = castable.value.get("cleric", (0, 0, 0))
        mage = castable.value.get("magic-user", (0, 0, 0))
        packed = bytes((_clamp_nibble(cleric[i]) << 4) | _clamp_nibble(mage[i])
                       for i in range(3)) + bytes(3)
        rec.set_raw("spells_castable", packed)
        emit(castable, "spells_castable", 0x0EE, 6,
             ", repacked cleric-high/magic-user-low")

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

    # -- innate effects: ten slots -------------------------------------------
    innate = use("innate_effects")
    if innate is not None:
        ids = list(innate.value)[:10]
        rec.set_raw("item_effects", bytes(ids) + bytes(10 - len(ids)))
        emit(innate, "item_effects", 0x0AD, 10)

    # -- the inventory: sixteen fixed slots ----------------------------------
    inventory = use("inventory")
    if inventory is not None:
        carried = list(inventory.value)
        inv = bytearray(ITEM_SLOTS * ITEM_SIZE)
        for n, item in enumerate(carried[:ITEM_SLOTS]):
            inv[n * ITEM_SIZE:(n + 1) * ITEM_SIZE] = item
        rec.set_raw("inventory", bytes(inv))
        emit(inventory, "inventory", 0x120, 256)
        if len(carried) > ITEM_SLOTS:
            rep.warnings.append(
                f"{len(carried)} items and the C64 has sixteen slots; "
                f"{len(carried) - ITEM_SLOTS} dropped from the end")

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
    rep.note(0x0FE, 2, f"portrait_head/body: zero. HEADnn/BODYnn name C64 "
                       f"disk files; the {port} art is a different set")
    rep.dropped.append(f"portrait ids: the {port} art has different numbering")
    rep.note(0x100, 1, "roster status: 1 (OK)")
    rec.set("roster_in_use", 1)
    tail = use("roster_tail")
    if tail is not None:
        rec.set_raw("roster_tail", bytes(tail.value))
        emit(tail, "roster_tail", 0x110, 9)

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
    ("spells_memorised", "the first sixteen ids, into slots the C64 fills "
                         "from the start"),
    ("spells_castable", "repacked cleric-high/magic-user-low into three "
                        "bytes"),
    ("size_small", "copied to the C64's size byte"),
    ("turn_power", "copied to the C64's caster turning byte at 0x0A4"),
    ("attack_forms", "copied as a block to 0x0D9"),
    ("innate_effects", "the first ten ids, into the C64's trait slots"),
    ("inventory", "the first sixteen items, into the C64's fixed slots; the "
                  "rest are warned about"),
    ("roster_tail", "copied as a block into the C64's roster tail"),
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
    ("portrait_head", "HEADnn names a C64 disk file; another port's art is a "
                      "different set with different numbering"),
    ("portrait_body", "BODYnn -- see portrait_head"),
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
    ("abilities_second", "zero in every Pool of Radiance specimen; Curse's "
                         "(base, current) pairs, unused here"),
    ("turn_class", "zero for every player character -- the undead's row, not "
                   "the caster's"),
    ("strength_index", "derived from strength and the percentile; a writer "
                       "that wants it recomputes it"),
    ("roster_in_use", "roster bookkeeping, not character state"),
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
       "spells_memorised": "zeroes stripped into neutral spells_memorised",
       "spells_castable": "nibbles unpacked into neutral spells_castable",
       "item_effects": "zeroes stripped into neutral innate_effects",
       "flags_0b8": "bit 7 read as neutral npc",
       "attack_forms": "read as neutral attack_forms",
       "infravision": "read as neutral infravision",
       "turn_power": "read as neutral turn_power",
       "size_small": "read as neutral size_small",
       "portrait_head": "read as neutral portrait_head",
       "portrait_body": "read as neutral portrait_body",
       "roster_tail": "read as neutral roster_tail, from the roster block's "
                      "+0x10-+0x18 or the record",
       "inventory": "read as neutral inventory, from the save's item page "
                    "or the record's sixteen slots"}
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

    # As wide as the *title's* mask, not as wide as Pool of Radiance's. Seven
    # bytes stop at id 55, which cost MORGAINE five of her twenty-nine spells
    # and PAINE all four of his -- issue #85.
    out.set("spells_known", spells.spells_known(rec.to_bytes(), game),
            f"the C64's spellbook mask @0x078, "
            f"{spells.for_game(game).spellbook_size} bytes on this title, "
            f"unpacked to ids", grade("spells_known"))
    out.set("spells_memorised",
            [b for b in rec.get_raw("spells_memorised") if b],
            "the C64's sixteen slots @0x020, zeroes stripped",
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

    for name, why in READ_DROPPED:
        out.drop(f"C64 {name}: {why}")
    return out
