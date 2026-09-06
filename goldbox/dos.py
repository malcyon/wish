"""The DOS codec: read a DOS Pool of Radiance save, or write one.

Both directions now (#26).  The player's own DOS files are still opened
read-only and never written -- :func:`write` builds *new* bytes, and
:func:`write_dos_save` writes them into a directory the caller names.

    DOS character file  ->  to_neutral  ->  NeutralCharacter
                                          ->  c64_codec.write  ->  C64 record
    C64 save  ->  c64_codec.read  ->  NeutralCharacter
                                    ->  dos.write  ->  DOS record + .ITM

The middle is `goldbox/neutral.py`'s typed record, and this module is the DOS
codec of that pair -- the only module that knows a DOS offset.  The C64 half
is `goldbox/c64_codec.py`'s, and the two never mention each other.
`goldbox/dos_layout.py` is the field table, in the same declarative style as
`goldbox/layout.py` and with a confidence on every entry, which is the grade the
neutral value carries and a writer refuses to write below.

`export_party` renders the result as the editor's own YAML, so a DOS party
and a C64 party come out in one shape; that is a view, not the interchange.

What the conversion promises
----------------------------
* the DOS files are opened read-only and never written;
* **every byte of the C64 record is justified** -- it came from the DOS save,
  or it was computed from it by a named rule, or it is a documented constant.
  `Report.sources` says which, for every offset;
* every DOS field with no C64 home is named in `Report.dropped`;
* the encumbrance identity balances, and `Report` says when it does not.

The three places the formats diverge in kind
--------------------------------------------
* **The spellbook.** DOS spends one byte per spell across `0x033`-`0x06A`;
  the C64 packs 56 bits at `0x078`.  The *ordering* turns out to be identical
  -- DOS byte *n* is spell id *n + 1*, the same id `goldbox/spells.py` uses -- so
  the transpose is a pack and not a permutation.  See `dos_layout.spellbook`.
  Spell 56, `RESTORATION`, is the one id with no C64 bit and is reported.
* **The per-class level array.** Eight wide on both.  DOS indexes by the class
  *number*, the C64 by the class *bit*, and the neutral record names the class
  instead; `CLASS_LEVEL_SLOTS` is this side of it, `c64_codec.LEVEL_FIELDS`
  the other, and druid and monk have no C64 slot at all.
* **The items.** Past its cached display line the 63-byte DOS record *is* the
  C64's sixteen bytes, one field to a byte -- `item_to_c64` is the projection,
  and it reproduces 157 of the 163 distinct C64 item records byte for byte.

The write-ups, `work/reports/dos-saves.md` and `work/reports/dos-items.md`, are
lost. The plan is `docs/117-save-conversion.md` and the assertions are
`tests/test_dosconvert.py`.
"""

from __future__ import annotations

import dataclasses
import hashlib
import pathlib
import shutil
import tempfile
from typing import Any, Iterable, Sequence

from . import areas, c64_codec, c64_save, dos_savegame, games, neutral, traits
from .c64_codec import Report
from .dos_layout import (
    CLASS_NUMBERS,
    CURSE_OF_THE_AZURE_BONDS,
    EFFECT_SIZE,
    FIELDS_BY_NAME,
    FIELDS_BY_NAME_FOR,
    ITEM_FIELDS_BY_NAME,
    ITEM_SIZE,
    LAYOUTS,
    POOL_OF_RADIANCE,
    RECORD_SIZE,
    SECRET_OF_THE_SILVER_BLADES,
    SHAPES,
    DosShape,
    DosShapeError,
    shape_for,
)
from .iconparts import DosIconTables, IconParts, dos_icon_tables, dos_size
from .layout import Confidence, Field, Kind
from .neutral import NeutralCharacter, Provenance
from .portraits import (
    PortraitError,
    PortraitTables,
    draws_sheet_portrait,
    tables_from_dos,
)
from .record import CharacterRecord

__all__ = [
    "DosRecordError",
    "WrongTitleError",
    "CANNOT_CONVERT",
    "CLASS_SLOTS_FOR_CLASS",
    "CLASS_BIT_FOR_SLOT",
    "class_bits_for",
    "neutral_class_bits_from",
    "INFRAVISION",
    "to_neutral",
    "DosCharacter",
    "DosItem",
    "Report",
    "WRITE_DEFAULTS",
    "WRITE_DERIVED",
    "identity_byte",
    "PortraitTables",
    "portrait_tables",
    "C64SaveReport",
    "item_to_c64",
    "item_from_c64",
    "read_character",
    "read_party",
    "slots_available",
    "c64_name",
    "to_c64_record",
    "export_party",
    "quest_flags",
    "SHARED_SCRATCH",
    "apply_position",
    "apply_quest_flags",
    "apply_file_cache",
    "apply_clock",
    "marching_slot",
    "convert_save",
    "new_save",
    "save_disk",
    "WriteReport",
    "write",
    "WRITE_UNREPORTED_DROPS",
    "SilencingWriter",
    "write_field_disposition",
    "write_dos_save",
    "new_dos_save",
]


#: The fallback shown to a player for any refusal that is not a wrong title --
#: bytes with no source, the two outdoor signals disagreeing, an area with no
#: row in `goldbox/areas.py`, and anything else `DosRecordError` is raised
#: for.  Donald's wording, 2026-09-02 (#195), chosen over a longer version
#: adding "not all of it has been decoded yet".  `.claude/rules/gui-text.md`
#: warns this interface kept growing sentences explaining itself and every one
#: was removed on request, so this is the only sentence and it covers every case.
CANNOT_CONVERT = "This save cannot be converted."


class DosRecordError(ValueError):
    """A file that is not a DOS Gold Box character record, or a conversion
    that refuses for any other reason.

    The message carries the developer's reason -- offsets, addresses, source
    file names, issue numbers -- because that is what a traceback and a log
    are for.  `player_message` is the other half: one sentence for somebody
    who is not reading the tracker, which is what a dialog shows.  The
    default is `CANNOT_CONVERT`; a subclass overrides it when it has
    something more specific and still player-safe to say, as `WrongTitleError`
    does below.  Generalised from `WrongTitleError` alone (#176) to cover
    every refusal (#195), after `editor/dosimport.py` was found showing a
    memory address and a source file name for everything else.
    """

    @property
    def player_message(self) -> str:
        """What a player is shown.  Donald's wording, 2026-09-02 (#195)."""
        return CANNOT_CONVERT


class WrongTitleError(DosRecordError):
    """A record from a title this operation does not handle.

    Reading is per title and works for all four; **converting to the C64 is
    only for titles in `CONVERTS`**, each pair whose two ports have been
    measured against each other and proven in the running game -- Pool of
    Radiance, and Curse of the Azure Bonds since `#192 (Convert a Curse of
    the Azure Bonds DOS save into a C64 one, which the importer refuses
    today)`.  Raising here is the difference between "not yet" and a
    conversion that silently reads the wrong bytes.

    The message carries the developer's reason, including the issue number,
    because that is what a traceback and a log are for.  `player_message` is
    the other half: one sentence for somebody who is not reading the tracker,
    which is what a dialog shows.  Donald wrote it (#176) after the exception
    text reached the import pane verbatim and put an issue number in front of
    a player.
    """

    def __init__(self, message: str, title: str) -> None:
        super().__init__(message)
        self.title = title

    @property
    def player_message(self) -> str:
        """What a player is shown.  Donald's wording, 2026-09-02.

        `title` is required rather than defaulted, so a caller that forgets it
        is a `TypeError` at the raise site instead of a dialog reading
        `" imports not yet supported."` -- leading space, lower case, and
        nothing naming the game.  Found in the code review of #176.
        """
        return f"{self.title} imports not yet supported."


#: Race -> infravision range.  The table lives with the C64 writer, which is
#: the only port that stores infravision at all; it is re-exported here
#: because this module is where it was first written down.
INFRAVISION = c64_codec.INFRAVISION


# ---------------------------------------------------------------------------
# Decoding one record
# ---------------------------------------------------------------------------
def _decode(f: Field, raw: bytes) -> Any:
    if f.kind is Kind.U8:
        return raw[0]
    if f.kind is Kind.I8:
        return raw[0] - 256 if raw[0] > 127 else raw[0]
    if f.kind in (Kind.U16LE, Kind.UINT_LE):
        return int.from_bytes(raw, "little")
    return bytes(raw)


class _Fielded:
    """Read-only field access driven by a layout table."""

    _TABLE: dict[str, Field] = {}

    def __init__(self, data: bytes, size: int, what: str,
                 table: dict[str, Field] | None = None) -> None:
        if len(data) != size:
            raise DosRecordError(
                f"a DOS {what} is {size} bytes; got {len(data)}")
        self._data = bytes(data)
        if table is not None:
            # Per instance, because the table is per title and one process
            # reads more than one title.
            self._TABLE = table

    def to_bytes(self) -> bytes:
        """The record exactly as it was read. Nothing here ever rewrites it."""
        return self._data

    def __bytes__(self) -> bytes:
        return self._data

    def __len__(self) -> int:
        return len(self._data)

    @property
    def fields(self) -> dict[str, Field]:
        """This record's own field table -- the title's, not the class's."""
        return self._TABLE

    def get(self, name: str) -> Any:
        f = self._TABLE[name]
        return _decode(f, self._data[f.span])

    def raw(self, name: str) -> bytes:
        return self._data[self._TABLE[name].span]

    def __getattr__(self, name: str) -> Any:
        # `_TABLE` is a class attribute on `DosItem` and an instance one on a
        # `DosCharacter`, because the table is per title; ordinary attribute
        # lookup picks whichever is there.  `__getattr__` runs only for names
        # that are not attributes at all, so this cannot recurse.
        table = self._TABLE
        if name in table:
            return self.get(name)
        raise AttributeError(name)


class DosItem(_Fielded):
    """One item record, 63 bytes in three titles and 67 in Silver Blades.

    The four extra bytes are at the **end** and are zero in every specimen, so
    every field below `0x03E` is at the same offset whichever title wrote it
    (#113).  `size` is the title's, from `DosShape.item_size`.
    """

    _TABLE = ITEM_FIELDS_BY_NAME

    def __init__(self, data: bytes, size: int = ITEM_SIZE) -> None:
        super().__init__(data, size, "item")

    @property
    def display_line(self) -> str:
        """The cached line the game last drew. **Never a source** -- it goes
        stale, and one specimen reads `11 Darts` over a quantity of 8."""
        n = min(self._data[0], ITEM_FIELDS_BY_NAME["text"].size)
        return self._data[1:1 + n].decode("ascii", "replace")

    def to_c64(self) -> bytes:
        """This item as the C64's sixteen bytes."""
        return item_to_c64(self._data)


#: Where Secret of the Silver Blades' item record grows past the 63 bytes the
#: other three titles write, and what has been read there.
#:
#: `#113 (Silver Blades' items are 67 bytes, not 63)` measured the stride in
#: the running game -- the mayor of New Verdigris hands the party twelve magic
#: items and `CHRDATC1.STF` is 804 bytes, which is 12 x 67 and is not
#: divisible by 63 -- and established that every field below `0x03E` is at the
#: same offset as in the other titles, because the weights are the published
#: AD&D figures and a `MAGE SCROLL 3 SPELLS` carries three ids inside this
#: title's own 1..117 spell space.  So the four extra bytes are `0x03F`-`0x042`
#: and nothing has ever been attributed to them.
#:
#: **They read `00 00 00 00` in 48 of 48 item records**, 24 of them distinct,
#: across every `.STF` this project made by driving DOS Silver Blades and
#: excluding the three folders whose records were edited by hand for
#: `#222 (Silver Blades' fourth spell-slot array is zero in every state
#: anybody can create)`.  Including those three the count is 18 files and the
#: answer does not change.  So a conversion writes nothing from them; a
#: **non-zero** one is a byte nobody has decoded and is refused rather than
#: quietly dropped (`.claude/rules/conversions.md`).
ITEM_TAIL = (0x3F, 4)


def item_to_c64(record: bytes) -> bytes:
    """Project one DOS item onto the C64's sixteen bytes.

    63 bytes in three titles and 67 in Secret of the Silver Blades, whose
    four extra bytes are :data:`ITEM_TAIL` and are refused if they hold
    anything -- every field this reads is below `0x03E` and so is at the same
    offset whichever title wrote it (#113).

    Not a guess at a conversion: it *is* the evidence.  Applied to every item
    in the eight `ITEM*.DAX` files it reproduces **157 of the 163 distinct
    item records on the C64 game disks byte for byte**, which is what fixes
    every offset -- including that readied and the hidden-name mask share the
    C64's byte +6 where DOS spends a byte on each, and that cursed is bit 7 of
    +7.  The six that do not match are items the two ports hand out in
    different places, not near misses.  The write-up,
    `work/reports/dos-items.md`, is lost; asserted in `tests/test_dosbox.py`.
    """
    sizes = sorted({s.item_size for s in SHAPES})
    if len(record) not in sizes:
        raise DosRecordError(
            f"a DOS item is {' or '.join(str(n) for n in sizes)} bytes; "
            f"got {len(record)}")
    tail_at, tail_size = ITEM_TAIL
    tail = record[tail_at:tail_at + tail_size]
    if any(tail):
        raise DosRecordError(
            f"this item holds {tail.hex(' ')} at 0x{tail_at:03X}, and those "
            f"four bytes read zero in all 48 Silver Blades item records this "
            f"project has driven the game into writing -- nothing has been "
            f"attributed to them, so there is nowhere to convert them to")
    at = {n: ITEM_FIELDS_BY_NAME[n].offset for n in
          ("type_index", "name1", "name2", "name3", "plus", "plus_save",
           "readied", "hidden", "cursed", "weight", "quantity", "value",
           "charges", "effect", "power")}
    r = record
    return bytes((
        r[at["type_index"]], r[at["name1"]], r[at["name2"]], r[at["name3"]],
        r[at["plus"]], r[at["plus_save"]],
        (0x80 if r[at["readied"]] else 0) | (r[at["hidden"]] & 0x07),
        0x80 if r[at["cursed"]] else 0,
        r[at["weight"]], r[at["weight"] + 1],
        r[at["quantity"]],
        r[at["value"]], r[at["value"] + 1],
        r[at["charges"]], r[at["effect"]], r[at["power"]],
    ))


#: Effect ids that are innate rather than temporary, and so belong in the
#: C64's ten trait slots at `0x0AD` rather than being dropped with the running
#: spells.  Seven of them are **Curse of the Azure Bonds' own filter**: its
#: importer reads a Pool of Radiance `.spc` file and keeps exactly 18, 26, 47,
#: 48, 97, 107 and 124, every one a racial or constitutional bonus.  90 is
#: added here because the DOS party carries it on the dwarf and on the
#: halfling and `goldbox/traits.py` names it the same kind of thing -- a racial
#: constitution bonus to poison and death saves.  PROBABLE.
#:
#: **18 and 48 are the gnome's, and a gnome is where they come from.**  #84
#: rolled three in the game's own creation screens and the engine wrote 97,
#: 18, 47 and 48 for every one -- so both are innate, both are racial, and
#: neither is carried by any other race.  CONFIRMED.
INNATE_EFFECTS = frozenset({18, 26, 47, 48, 90, 97, 107, 124})

#: Bytes 1-4 of a `.SPC` record for an innate effect.  A record is nine bytes:
#: the effect id, these four, and a four-byte far pointer to the next record.
#: Every innate specimen in the archives -- 26, 47, 90, 97, 107 and 124, over
#: three races and 32 files -- reads `00 00 FF 00`.  **18 and 48 do too, and
#: they are no longer an analogy**: #84 rolled three gnomes in DOS Pool of
#: Radiance's own creation screens -- one of each class the game offers a
#: gnome, both sexes, three alignments -- and each got 97, 18, 47 and 48 with
#: these four bytes, twice over, once as `<NAME>.SPC` at creation and again as
#: `CHRDAT<slot><n>.SPC` when the party was saved.  CONFIRMED, six files.
#:
#: **Byte 3's `0xFF` is an innate effect's own payload, not a universal marker
#: for "permanent."**  This note used to read it that way, against `BLESS`'s
#: `02 00 01 00` as the only counterexample -- but #232's own measurement
#: refutes the generalisation: ADDERLY's extra strength, CONJURER's Ring of
#: Fire Resistance and MAGICIAN's displacement are all permanent (duration
#: zero, bytes 1-2) and hold `92`, `12` and `12` at byte 3, not `0xFF`.  What
#: decides permanence is bytes 1-2, the duration, and byte 3 is simply
#: whatever magnitude the effect carries -- `0xFF` because that is what a
#: racial bonus happens to be, and an item-granted effect's own value
#: otherwise.  `docs/117-save-conversion.md` carries the same correction.
INNATE_PAYLOAD = bytes((0x00, 0x00, 0xFF, 0x00))

#: The `.SPC` record's last four bytes are the far pointer to the next record,
#: and **the engine rebuilds them**: nothing on disk survives the load.
#: Measured three ways under DOSBox-X (`docs/117`, "The `.SPC` effects file"):
#: a slot loaded twice puts its nodes at different addresses; removing one
#: character's file moves the *next* character's first node to where the
#: removed one's used to be, which relocation cannot do; and zeroing all four
#: bytes in every record of a five-record file still loads all five, correctly
#: relinked, so the record count comes from the file's length and not from a
#: NULL terminator.  So this is what a converter writes.  CONFIRMED.
EFFECT_NEXT_NULL = bytes(4)

#: Race name -> the innate ids a **C64** record cannot hand over, because the
#: C64 engine either works them out when the blow lands or keeps them inside
#: another field, and stores no trait id for them at all.
#:
#: **Keyed by name, not by the record's race number** (#293, A converted
#: Silver Blades dwarf, elf or gnome gets another race's innate combat
#: effect, because RACE_COMBAT_EFFECTS is keyed by Pool of Radiance's race
#: numbers).  The number is an index into the record's *own title's* race
#: table, and Secret of the Silver Blades renumbers them -- its dwarf is 3,
#: where Pool of Radiance's 3 is the gnome, so a converted Silver Blades
#: dwarf used to be handed the gnome's set.  `_race_combat_effects` looks the
#: number up through `goldbox.games.race_table` for the record's own title
#: before either table below is asked, the way `_infravision` in
#: `goldbox/c64_codec.py` does for #287 (A converted Silver Blades human sees
#: in the dark, because the infravision table is keyed by Pool of Radiance's
#: race numbers).
#:
#: This table is Pool of Radiance's and Curse of the Azure Bonds' -- they
#: share race names for dwarf, gnome and halfling, and both were measured
#: only on Pool of Radiance specimens.  Two races have a DOS specimen, and
#: each is written the whole set the engine's own save holds for it:
#:
#: * **the dwarf (1): 90, 97, 26 and 47** -- THRENDER GRONE's `.SPC`, in both
#:   of the archives' Pool of Radiance save directories;
#: * **the halfling (5): 90 and 97** -- PHINEAS's, in the same two.  He has no
#:   26 or 47; the bonuses against orcs and against giants are the dwarf's.
#:
#: **90 and 97 are the constitution bonus to saving throws, and they have to
#: be written even though the C64 has already spent that bonus inside the five
#: saving-throw bytes.**  This note argued the opposite until #191 (A
#: converted dwarf loses his constitution bonus to saving throws) measured it:
#: the DOS engine recomputes all five saves on load from class, level and the
#: character's `.SPC` records, so the copied numbers are discarded before
#: anybody can read them and the records that would have replaced them were
#: never written.  MAGNUS, a dwarf fighter, was converted with
#: `14 14 13 11 12` and the engine's own resave held `17 17 16 14 15` -- three
#: worse in every column, permanently.  The C64 half of the old note is still
#: true and is still why nothing can be read off the source record: HOGARTH, a
#: dwarf with constitution 17, stores `9 8 10 12 11` where the class row is
#: `13 12 14 16 15` (`goldbox/levels.py`, "the saving-throw rule is the game's
#: own"), and THRENDER GRONE, a DOS fighter 1 with constitution 16, stores the
#: plain row `14 15 16 17 17` and keeps his bonus in these two records.
#:
#: **26 and 47 are situational and no stored number can hold them** -- a THAC0
#: bonus against orcs, half-orcs, goblins and hobgoblins, and an armour-class
#: bonus against ogres, trolls, ogre magi and giants.  The C64 dwarf gets them
#: from his race byte at the moment of the blow; the DOS dwarf gets them from
#: these records or not at all.
#:
#: **The gnome (3) is measured now: 97, 18, 47, 48.**  #84 rolled three
#: gnomes in DOS Pool of Radiance's own creation screens -- one of each class
#: the game offers a gnome (fighter, thief, fighter/thief), both sexes, three
#: alignments -- and the engine wrote the same four records for every one,
#: twice over: once as `<NAME>.SPC` at creation and again as
#: `CHRDAT<slot><n>.SPC` after the party was saved.  No 90, which is what the
#: names alone had predicted: 90 is the dwarf's and the halfling's only, 97 is
#: all three sturdy races'.  Five same-boot controls reproduce the archives'
#: census exactly -- dwarf 90/97/26/47, elf 107, half-elf 124, halfling 90/97,
#: human no `.SPC` file at all -- so this is one measurement and not a new
#: kind of one.  CONFIRMED over three gnomes and six engine-written files.
#:
#: **Writing 97 from this table is PROBABLE, not CONFIRMED, and #247 (Nobody
#: knows whether innate effect 97 is racial or the constitution bonus) is
#: why.**  Every race this corpus has ever seen carry 97 -- dwarf, halfling,
#: now gnome -- also earns a constitution bonus, so nothing here separates
#: "97 is racial" from "97 is the constitution bonus computed some other
#: way."  If it turns out to be the latter, a converted character with a low
#: constitution would be handed a bonus he did not roll.  18, 47 and 48 do
#: not carry this doubt: #84 measured them as this race's own,
#: unconditionally.
RACE_COMBAT_EFFECTS: dict[str, tuple[int, ...]] = {
    "dwarf": (90, 97, 26, 47),
    "gnome": (97, 18, 47, 48),
    "halfling": (90, 97),
}

#: Secret of the Silver Blades' own ids, from the same seed table
#: `goldbox/traits.py`'s `NAMES_SILVER_BLADES` reads: `GEN $0C5B`/`$0C62`
#: seed elf 95, half-elf 18, dwarf 26 and 47, gnome 48 and 7, halfling 92,
#: human nothing.  PROBABLE throughout, the grade `goldbox/traits.py` gives
#: the same nine codes -- no Silver Blades `.SPC` has been watched carrying
#: any of them yet, so this is the seed table's own claim rather than a
#: measurement of a written file the way the two races above are.
RACE_COMBAT_EFFECTS_SILVER_BLADES: dict[str, tuple[int, ...]] = {
    "elf": (95,),
    "half-elf": (18,),
    "dwarf": (26, 47),
    "gnome": (48, 7),
    "halfling": (92,),
}

#: Title key -> its table.  A title not listed gets Pool of Radiance's and
#: Curse of the Azure Bonds', which is what every caller written before this
#: split existed means.
_RACE_COMBAT_EFFECTS_TABLES: dict[str, dict[str, tuple[int, ...]]] = {
    games.SECRET_OF_THE_SILVER_BLADES.key: RACE_COMBAT_EFFECTS_SILVER_BLADES,
}


def _race_combat_effects(game: object, race: int) -> tuple[int, ...]:
    """This title's innate combat ids for a race code, empty for an unnamed one.

    `game` is whatever a caller has in hand for the title -- a
    `goldbox.games.Game`, its `.key`, or None for Pool of Radiance -- the same
    three shapes `c64_codec._infravision` accepts, and for the same reason: a
    conversion carries a bare key rather than the descriptor.
    """
    resolved = (game if hasattr(game, "race_names")
               else games.BY_KEY.get(getattr(game, "key", game)))
    name = games.race_table(resolved).get(race)
    table = _RACE_COMBAT_EFFECTS_TABLES.get(
        getattr(resolved, "key", resolved), RACE_COMBAT_EFFECTS)
    return table.get(name, ())


# `STURDY_RACES = (1, 3, 5)` used to live here, Pool-of-Radiance-numbered like
# `RACE_COMBAT_EFFECTS` above and the same bug's shape -- but a repository-wide
# grep for it, done for #293 (A converted Silver Blades dwarf, elf or gnome
# gets another race's innate combat effect, because RACE_COMBAT_EFFECTS is
# keyed by Pool of Radiance's race numbers), found no reader anywhere: not in
# this file, not in any tool, not in any test.  `goldbox/levels.py`'s
# `Progression.sturdy_races` already carries the same decision correctly, per
# title -- Pool of Radiance `(1, 3, 5)`, Silver Blades `(3,)`, the dwarf alone
# and 3 is the dwarf there -- so this was dead rather than wrong, and is
# removed rather than renumbered.

#: DOS class number -> the C64 record field holding that class's level.  DOS
#: indexes its eight slots by the class *number* and the C64 by the class
#: *bit*, so this is the permutation between them.  Druid and monk have no C64
#: slot: the game names both classes and instantiates neither.
CLASS_LEVEL_SLOTS: tuple[tuple[int, str, str | None], ...] = (
    (0, "cleric", "level_cleric"),
    (1, "druid", None),
    (2, "fighter", "level_fighter"),
    (3, "paladin", "level_paladin"),
    (4, "ranger", "level_ranger"),
    (5, "magic-user", "level_magic_user"),
    (6, "thief", "level_thief"),
    (7, "monk", None),
)

#: Class number -> the level-array slots that class fills, derived from the
#: 18-entry combined-class table by name.  A single-class character fills one
#: slot; `fighter/mage/thief` fills three.  What makes this worth a table is
#: that it is a **check**: a spellbook or a memorised region one byte out
#: moves the array, and then the slots that are set stop matching the class
#: byte -- which is `tests/test_dosconvert.py`'s test of every title's shape.
CLASS_SLOTS_FOR_CLASS: dict[int, tuple[int, ...]] = {
    number: tuple(
        slot for slot, name, _ in CLASS_LEVEL_SLOTS
        if name in {"magic-user" if p == "mage" else p
                    for p in combined.split("/")})
    for number, combined in enumerate(CLASS_NUMBERS)
    if combined != "monster"
}


#: Class number -> the bit that class sets in `class_bits`.  Magic-user,
#: cleric, thief and fighter are the C64's own bit order; **paladin and ranger
#: share bit 6**, where the C64 gives the ranger bit 7 of its own.  Measured on
#: three characters across two titles -- Curse's MATHEW (paladin 5) and ARGORA
#: (ranger 5) both read 0x40, and Pools of Darkness' PAINE, a magic-user 13 who
#: was a ranger 9, reads 0x41.  So the mask does not tell a paladin from a
#: ranger on DOS and the class *number* must be read instead.
CLASS_BIT_FOR_SLOT: dict[int, int] = {0: 0x02, 2: 0x08, 3: 0x40, 4: 0x40,
                                      5: 0x01, 6: 0x04}

#: **The shared bit order gives a ranger bit 7 to itself, and DOS does
#: not.**
#:
#: **A DOS ranger used to convert into a C64 paladin, and this is what stops
#: it.**  `class_bits` was DIRECT -- copied byte for byte -- so PAINE, the
#: shipped Silver Blades ranger 8, arrived on the C64 with `class_bits`
#: `$40` and `level_ranger` 8, which is a paladin holding a ranger's levels
#: and is a combination no C64 save on either title holds.  Found by
#: `tools/ssbtwins.py`, which converts the six DOS characters SSI shipped and
#: diffs each against the C64 record SSI shipped for the same character:
#: PAINE's C64 twin reads `$80`.  Curse of the Azure Bonds has the same
#: defect and it shipped, because the party `#192` proved the conversion on
#: had two paladins and no ranger.
#:
#: `goldbox/amiga.py`'s own `CLASS_BIT` had already recorded the same thing
#: from the other side -- *"64 for both the paladin and the ranger, where the
#: C64 gives them 0x40 and 0x80 separately. So the mask is not the neutral
#: `class_bits` byte and must not be copied across"* -- and the Amiga codec
#: has always computed it from the class names rather than copying it.
#:
#: CONFIRMED on both sides: DOS Curse's MATHEW (paladin 5) and ARGORA
#: (ranger 5) and DOS Silver Blades' GUY DE VALOIS (paladin 8) and PAINE
#: (ranger 8) all read `$40`; the C64 twin of Curse's ranger reads `$80` with
#: `0x0D0` = 5 (`goldbox/layout.py` 0x0D0) and the C64 twin of PAINE reads
#: `$80` with `level_ranger` 8.
#:
#: `RANGER_BIT_NEUTRAL` and `RANGER_BIT_DOS` are the one bit the two orders
#: disagree about; `PALADIN_SLOT` and `RANGER_SLOT` are the level-array slots
#: that say which class a DOS record's bit 6 stands for.
RANGER_BIT_NEUTRAL, RANGER_BIT_DOS = 0x80, 0x40
PALADIN_SLOT, RANGER_SLOT = 3, 4


def neutral_class_bits(char: "DosCharacter") -> int:
    """A DOS record's own class mask, in the shared bit order.

    **The record's own byte, with one bit disambiguated and nothing else
    touched.**  Only bit 6 is ambiguous, so only bit 6 is reread: it becomes
    bit 6 where the level array holds a paladin, bit 7 where it holds a
    ranger, and both where a record somehow holds both.  Every other bit is
    the byte the DOS engine wrote, which is what stops this quietly
    rewriting a record whose stored mask and level array disagree for some
    other reason -- Pool of Radiance's SILAS reads `$08` with fighter *and*
    thief levels, and that disagreement is his record's and not ours to
    settle here.

    A record with bit 6 set and neither slot filled keeps bit 6, since there
    is nothing to read it as.
    """
    former = (char.raw("former_class_levels")
              if "former_class_levels" in char.fields else b"")
    return neutral_class_bits_from(char.get("class_bits"),
                                   char.raw("class_levels"), former)


def neutral_class_bits_from(bits: int, class_levels: Sequence[int],
                            former_class_levels: Sequence[int] = ()) -> int:
    """:func:`neutral_class_bits`, from the three values rather than a record.

    **Here because the Amiga's Curse and Silver Blades records hold this
    field exactly as DOS does, and had lost it.** `goldbox.amiga
    .to_neutral_later` reads those two titles through the DOS field table
    and built its copied-field list by iterating `DIRECT`, so taking
    `class_bits` out of `DIRECT` stopped it setting the field at all and an
    Amiga character converted to the C64 arrived with no class
    (#292). It cannot call :func:`neutral_class_bits`, which wants a
    `DosCharacter`'s `.raw()` and `.fields`.

    The ambiguity is the same one on both ports, measured on the party SSI
    shipped for Silver Blades three times over: Amiga PAINE reads `$40` at
    `0x0CC` with 8 in the ranger's level slot and Amiga GUY DE VALOIS reads
    `$40` with 8 in the paladin's, exactly as their DOS records do, and the
    C64 record SSI shipped for PAINE reads `$80`.
    """
    if not bits & RANGER_BIT_DOS:
        return bits
    slots = {n for n, v in enumerate(class_levels) if v}
    slots |= {n for n, v in enumerate(former_class_levels) if v}
    named = 0
    for slot, bit in ((PALADIN_SLOT, RANGER_BIT_DOS),
                      (RANGER_SLOT, RANGER_BIT_NEUTRAL)):
        if slot in slots:
            named |= bit
    return (bits & ~RANGER_BIT_DOS) | (named or RANGER_BIT_DOS)


def dos_class_bits(neutral_bits: int) -> int:
    """A shared-order class mask as DOS's own byte: the ranger folds onto 6.

    The inverse of :func:`neutral_class_bits` as far as it can be -- DOS
    stores less than the neutral record does here, and the class number and
    the level array are what carry the difference.
    """
    if not neutral_bits & RANGER_BIT_NEUTRAL:
        return neutral_bits
    return (neutral_bits & ~RANGER_BIT_NEUTRAL) | RANGER_BIT_DOS


#: The class code table Curse of the Azure Bonds' C64 `GEN` walks at `$1951`,
#: indexed by the class code and holding the bitmask that code stands for.
#: 0 cleric, 1 druid, 2 fighter, 3 paladin, 4 ranger, 5 magic-user, 6 thief,
#: 7 monk, and 8 upward for the multi-class combinations, which is the order
#: `goldbox/layout.py`'s `char_class` note documents.  The druid's entry and
#: the monk's are 0 because no Gold Box record carries either class.
#:
#: **It is the C64's bit order**, the one the neutral record uses, so a DOS
#: mask goes through :func:`neutral_class_bits` first.  And it is **Curse's**
#: table: index 10 is `0x82`, cleric and ranger, where Pool of Radiance --
#: which has neither a paladin nor a ranger -- carries cleric/magic-user
#: there, the row `goldbox/yaml_io.py`'s `CLASS_CODES` records.  The two agree
#: on every combination either title can actually make.
#: `docs/187-the-class-code-byte.md` has the reading.
CLASS_CODE_TABLE: tuple[int, ...] = (
    0x02, 0x00, 0x08, 0x40, 0x80, 0x01, 0x04, 0x00,
    0x0A, 0x0B, 0x82, 0x03, 0x06, 0x09, 0x0C, 0x0D, 0x05)

#: Bitmask -> class code, from the table above, first occurrence winning so
#: the two zero entries do not claim the empty mask.
CLASS_CODE_FOR_BITS: dict[int, int] = {
    bits: code for code, bits in reversed(list(enumerate(CLASS_CODE_TABLE)))
    if bits}

#: Class name -> its bit in the shared order, from `goldbox/games.py`'s own
#: per-title lists so the two cannot drift apart.  Krynn's is the widest,
#: adding the Knight of Solamnia at `0x10`; every other title's is a subset.
CLASS_BIT_FOR_NAME: dict[str, int] = {
    name: bit for bit, name in games.CLASS_BITS_KRYNN}


def _class_code(levels: "dict[str, int] | None") -> int | None:
    """The class code for the classes a character holds levels in, or None.

    None when there is no level array to read, or when the classes it names
    are a combination the game's own table has no code for -- three exist,
    and `goldbox/yaml_io.py`'s `class_code_for` refuses them for the same
    reason: a code that is not in the table means a different class.

    **This is the dual-class answer, not the general one** (#310). A
    dual-classed character gets the old class's bit back in `class_bits` once
    his new class passes the level he left the old one at, so the mask names
    two classes where the code names the one he *is*; his level array holds
    exactly the class he is now, because the old class's slot is zeroed at
    the change. For everybody else :func:`write` reads the mask instead --
    SILAS, the shipped Pool of Radiance fighter, carries a thief 1 in his
    level array that neither his mask nor his code knows about, and taking
    the levels there would give him a class the game does not.
    """
    if not levels:
        return None
    bits = 0
    for name, level in levels.items():
        if level:
            bits |= CLASS_BIT_FOR_NAME.get(name, 0)
    return CLASS_CODE_FOR_BITS.get(bits)


def class_bits_for(char: "DosCharacter") -> int:
    """The class bitmask a record's level arrays imply.

    The OR of `CLASS_BIT_FOR_SLOT` over every slot set in the current
    per-class level array **and** in the former one, where the title has a
    former one.  Equal to the stored `class_bits` in 54 of 54 shipped records
    across all four titles, which is what makes it a check on the layout: a
    shape one byte out moves one array or the other and the two stop agreeing.

    **Not the state at the moment a character dual-classes.** DEMELTINA and
    PAINE, read one action after Curse's and Silver Blades' own training
    halls dual-classed them, both hold `class_bits` for the *new* class only
    -- the old bit returns once the new class's level passes the byte after
    `level` (`#234`, PROBABLE on `0x3C031`), and this function's OR over both
    arrays is that *regained* state rather than the general one. A record
    read fresh off a dual-class, before that threshold, disagrees with what
    this function returns.
    """
    slots = {n for n, v in enumerate(char.raw("class_levels")) if v}
    if "former_class_levels" in char.fields:
        slots |= {n for n, v in enumerate(char.raw("former_class_levels"))
                  if v}
    bits = 0
    for slot in slots:
        bits |= CLASS_BIT_FOR_SLOT.get(slot, 0)
    return bits


class DosCharacter(_Fielded):
    """One DOS Gold Box character record, saved or exported.

    A save slot and a `.CHA` export are the same record in the same order;
    the only systematic difference is that an export zeroes the item count,
    so one reader serves both.

    **The title comes from the length.** 285, 422, 439 and 510 bytes are Pool
    of Radiance, Curse of the Azure Bonds, Secret of the Silver Blades and
    Pools of Darkness, and no two are the same size, so a record identifies
    its own title with nothing else to go on. Pass `shape` to override that.
    """

    _TABLE = FIELDS_BY_NAME

    def __init__(self, data: bytes, items: Sequence[DosItem] = (),
                 effects: Sequence[bytes] = (), source: str | None = None,
                 shape: "int | str | DosShape | None" = None):
        try:
            self.shape = shape_for(len(data) if shape is None else shape)
        except DosShapeError as e:
            raise DosRecordError(str(e)) from None
        super().__init__(data, self.shape.record_size, "character record",
                         FIELDS_BY_NAME_FOR[self.shape.key])
        self.items = tuple(items)
        self.effects = tuple(effects)
        self.source = source

    @property
    def is_pool_of_radiance(self) -> bool:
        return self.shape is POOL_OF_RADIANCE

    def rebuild(self) -> bytes:
        """Re-encode every field from its decoded value.

        The round trip a read-only decoder can actually make: decode the whole
        table, encode it back, and compare with what was read.  It bites on a
        wrong width and on a wrong kind -- a field declared one byte wide that
        is really two comes back with the second byte zeroed -- which is the
        failure a reader that only hands the bytes back can never see.
        """
        out = bytearray(len(self._data))
        for f in self._TABLE.values():
            _encode(f, out, self.get(f.name))
        return bytes(out)

    @property
    def name(self) -> str:
        width = self._TABLE["name_text"].size
        n = self.get("name_length")
        if not 0 <= n <= width:
            raise DosRecordError(f"name length {n} is not 0-{width}")
        return self.raw("name_text")[:n].decode("ascii", "replace")

    @property
    def spells_known(self) -> list[int]:
        """The spell ids the byte-per-spell book at `0x033` has set.

        DOS byte *n* is spell id *n + 1*, and the ids are the C64's own --
        `goldbox/spells.py`'s group boundaries 1-8, 9-21, 22-28, 29-35, 36-44,
        45-55 are the DOS array's cleric-1 / mage-1 / cleric-2 / mage-2 /
        cleric-3 / mage-3 runs exactly.
        """
        book = self.raw("spellbook")
        return [i + 1 for i, b in enumerate(book) if b]

    @property
    def spells_memorised(self) -> list[int]:
        """Memorised spell ids, highest first -- the C64's own order.

        DOS fills its sixteen slots **backwards from the end**; the C64 fills
        its own forwards in descending id.  Reversing is the whole transpose.
        """
        return [b for b in reversed(self.raw("spells_memorised")) if b]

    @property
    def class_levels(self) -> dict[str, int]:
        """Class name -> level, for the classes that carry one."""
        raw = self.raw("class_levels")
        return {name: raw[n] for n, name, _ in CLASS_LEVEL_SLOTS if raw[n]}

    #: The coin slots, richest last.  Pools of Darkness has only the last
    #: three; every earlier title has all seven.
    COINS = ("copper", "silver", "electrum", "gold", "platinum", "gems",
             "jewelry")

    @property
    def money(self) -> dict[str, int]:
        return {k: self.get(k) for k in self.COINS if k in self._TABLE}

    @property
    def effect_ids(self) -> list[int]:
        """The first byte of each 9-byte `.SPC` record."""
        return [e[0] for e in self.effects]

    def expected_encumbrance(self) -> int:
        """`money + sum(item weight x quantity)`, the identity worth keeping.

        Self-contained arithmetic across three structures -- the money block,
        the item file and one derived field -- so it confirms the money
        offsets, the 63-byte item stride, the weight offset and the byte order
        together.  It balances for 16 of the 18 saved characters and all six
        exports; the two that miss carry a stack of darts whose cached name
        disagrees with the quantity byte.
        """
        total = sum(self.money.values())
        for it in self.items:
            # A quantity of zero means one: the field counts *extra* copies
            # for anything that does not stack, and the identity only balances
            # this way round.
            total += it.get("weight") * (it.get("quantity") or 1)
        return total


# ---------------------------------------------------------------------------
# Reading the files
# ---------------------------------------------------------------------------
def _sibling(path: pathlib.Path, suffix: str) -> bytes:
    other = path.with_suffix(suffix)
    return other.read_bytes() if other.exists() else b""


def read_character(path: str | pathlib.Path) -> DosCharacter:
    """One character from a `CHRDAT<slot><n>.SAV` or a `<NAME>.CHA`.

    Any of the four titles: the record's length names it, and the sibling
    item and effect files are whatever that title calls them -- `.ITM`/`.SPC`
    for Pool of Radiance, **`.SWG`**/`.FX` for Curse, **`.STF`**/`.SFX` for
    Silver Blades, `.THG`/`.EFX` for Pools of Darkness.  An export normally has
    neither.  **The stride is per title too**: 63 everywhere except Silver
    Blades, which is 67, so slice at `shape.item_size`.

    Curse's `.SWG` and Silver Blades' `.STF` are both measured in the running
    game, on characters who went shopping (#113) -- 63 and 67 bytes
    respectively, the second from 804 bytes holding twelve items.  Pools of
    Darkness' `.THG` and its 63 are **not** measured that way: they rest on the
    shipped archives dividing evenly, which is the same check Silver Blades
    would have passed while being wrong.

    No sibling item file at all is quiet -- an export normally has none.  A
    sibling that **is** present and does not reconcile with the record's own
    item count, because it is short of a whole number of items or short of
    the count, raises `DosRecordError` naming the file, the stride and both
    counts (#221) rather than silently handing back fewer items than the
    record says it has.
    """
    path = pathlib.Path(path)
    data = path.read_bytes()
    try:
        shape = shape_for(len(data))
    except DosShapeError as e:
        raise DosRecordError(f"{path.name}: {e}") from None
    item_path = path.with_suffix(shape.item_suffix)
    item_file_present = item_path.exists()
    itm = item_path.read_bytes() if item_file_present else b""
    spc = _sibling(path, shape.effect_suffix)
    # The record's own item count is what says how many of the item file
    # belong to this character. It is zeroed in an export, and an export that
    # sits beside a stale `.ITM` from an earlier save would otherwise be given
    # items it does not carry -- which is exactly what the archives hold.
    count = data[FIELDS_BY_NAME_FOR[shape.key]["item_count"].offset]
    stride = shape.item_size
    # No sibling item file at all is deliberate and documented above -- an
    # export normally has none, and that case stays silent. A file that is
    # *present* and the wrong shape is not: `min()` used to paper over a
    # truncated or short `.ITM`/`.SWG`/`.STF`/`.THG`, which is exactly what a
    # 63-byte `.ITM` did to every Curse and Silver Blades character (#113).
    if item_file_present and (len(itm) % stride != 0
                               or len(itm) // stride < count):
        raise DosRecordError(
            f"{item_path.name}: {len(itm)} bytes at a {stride}-byte stride "
            f"is {len(itm) // stride} items, but {path.name}'s item_count "
            f"says {count}"
        )
    items = [DosItem(itm[i * stride:(i + 1) * stride], stride)
             for i in range(min(count, len(itm) // stride))]
    effects = [spc[i:i + EFFECT_SIZE] for i in range(0, len(spc), EFFECT_SIZE)
               if len(spc[i:i + EFFECT_SIZE]) == EFFECT_SIZE]
    return DosCharacter(data, items, effects, source=str(path), shape=shape)


def slots_available(folder: str | pathlib.Path) -> list[str]:
    """The save slot letters present in a DOS save directory."""
    folder = pathlib.Path(folder)
    return sorted(p.name[6] for p in folder.glob("SAVGAM?.DAT"))


def read_party(folder: str | pathlib.Path, slot: str) -> list[DosCharacter]:
    """The six characters of one save slot, in file order."""
    folder = pathlib.Path(folder)
    out = []
    for n in range(1, 7):
        path = folder / f"CHRDAT{slot}{n}.SAV"
        if path.exists():
            out.append(read_character(path))
    if not out:
        raise DosRecordError(f"no CHRDAT{slot}?.SAV in {folder}")
    return out


# ---------------------------------------------------------------------------
# What the conversion does with every DOS field
# ---------------------------------------------------------------------------
#: DOS field -> C64 field, where the conversion is a straight copy of a value
#: the two ports encode the same way.  Everything not in this table needs work
#: and gets it below.
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
    # The class byte copies because the two ports share one 18-entry table:
    # goldbox/yaml_io.py's CLASS_CODES is Gold Box Companion's list entry for
    # entry, checked against the class bitmask on all 24 specimens.
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
    ("hp_rolled", "hp_rolled"),
    # **Not the marching order** -- the DOS byte at 0x0BF is the character's
    # combat-icon slot, and the loader hands those out in file order, so a
    # party nobody has reordered numbers 0-5 and the neutral marching
    # position is what that number means (#305, `goldbox/dos_layout.py`).
    # The name here is the *neutral* field's and stays until the rename can
    # be made across `goldbox/amiga.py` and `goldbox/c64_codec.py` too.
    ("party_order", "party_order"),
    ("hp_current", "hp_current"),
    ("thac0_current", "thac0"),
    ("armour_class", "armour_class"),
    ("movement_current", "roster_movement"),
)

#: DOS fields deliberately left behind, and why.  Reported, never silent
#: unless :data:`UNREPORTED_DROPS` names them.
DROPPED: tuple[tuple[str, str], ...] = (
    # #57: `to_neutral` carries this across when it is given the game's own
    # creation tables, and only drops it when it is not.
    ("portrait_head", "the sheet portrait's head: a menu position, which "
                      "needs the game's own creation tables to become the "
                      "C64's HEADnn id. Converted across when those tables "
                      "are available, dropped when they are not"),
    ("portrait_body", "see portrait_head; the body half of the same pair"),
    # #130 (A converted DOS party arrives with six identical combat figures,
    # not its own): the C64 has one size byte where DOS has two fields --
    # `size` (see `TRANSFORMED`) and this one, the creature's combat
    # footprint.  It is 1 in every player record any title has ever been
    # read carrying and `GAME.OVR:0x19F98` writes the 1 at creation, so
    # nothing here is a loss a player would notice -- silenced below.
    ("icon_dimension", "the C64 has one size byte where DOS has two fields; "
                       "the C64's carries the other one"),
    # #297: this byte is the **target's** turning row, not the caster's
    # strength, so a player character reads 0 and there is nothing for the
    # C64's own `turn_class` at 0x0A3 to gain from it. The C64 writer sets
    # that byte to zero for the same reason.
    ("turn_class", "the row of the turning matrix an undead creature "
                   "answers to. The DOS engine reads it off the creature "
                   "being turned rather than off the cleric turning it, so "
                   "every player character in either port holds zero and the "
                   "C64 writes zero into its own turning row whatever it is "
                   "given"),
)

#: Drops the **player** is not shown, though the conversion still knows them.
#:
#: Every name here is still in :data:`DROPPED`, so `field_disposition` still
#: accounts for it and `goldbox/dos_layout.py` still carries its field note --
#: what changes is only the list in front of somebody importing a save.
#: `icon_dimension` is 1 in every player record any title has ever been read
#: carrying (#130); `turn_class` is 0 in every player character in either
#: port (#297).
#:
#: Donald, 2026-08-27: *"We do not need to report derived lines as being
#: dropped. The user will not notice the difference."*
UNREPORTED_DROPS = frozenset({"icon_dimension", "turn_class"})

#: What a player reads for each name in :data:`DROPPED` that still reaches
#: `report.dropped` -- a subject a person recognises, standing in for the
#: field's own identifier and the file offset `to_neutral` used to put in
#: front of it (`.claude/rules/gui-text.md`: no memory address or file
#: offset in front of a player).  `DROPPED`'s own `(name, why)` pairs are
#: untouched and still carry the byte-level account for `field_disposition()`
#: and anyone reading the source; this dict is read only when composing what
#: a player sees.  A name silenced by `UNREPORTED_DROPS` needs no entry --
#: nothing is composed for it -- and `portrait_head`/`portrait_body` are
#: named here for the case where no creation tables were available at all;
#: the menu-mismatch case has its own sentence at the call site, since it
#: has to name the position.
#:
#: **PROPOSED, not yet approved.** `.claude/rules/gui-text.md` makes every
#: word here Donald's; this is the working proposal for
#: #244 (Every DROPPED entry's composed line carries a raw hex file offset
#: in front of the player, not only the two #235 fixed), built so it can be
#: seen running rather than only described.
DROPPED_PLAYER_TEXT: dict[str, str] = {
    "portrait_head": "Character portrait (head): needs the game's own "
                     "character-creation art, which this import could not "
                     "read",
    "portrait_body": "Character portrait (body): needs the game's own "
                     "character-creation art, which this import could not "
                     "read",
}


#: DOS fields converted by a rule rather than by a copy.  Named here so the
#: disposition check below can see them; the rules themselves are in
#: `to_c64_record`.
TRANSFORMED: tuple[tuple[str, str], ...] = (
    ("class_bits", "reread from the level array into the shared bit order: "
                   "DOS gives the paladin and the ranger one bit between "
                   "them and the C64 gives the ranger a bit of its own, so "
                   "copying the byte made a converted ranger a paladin"),
    ("name_length", "folded into the C64's 20-byte NUL-padded name"),
    ("name_text", "re-padded into the C64's 20-byte name, and folded to "
                  "capitals with its trailing blanks cut: the C64 draws its "
                  "text in the uppercase/graphics character set, where a "
                  "lower-case letter is a punctuation mark (goldbox.dos."
                  "c64_name)"),
    ("spellbook", "56 bytes packed into 56 bits; the ids are identical"),
    ("spells_memorised", "reversed: DOS fills from the end, the C64 from the "
                         "start. The arrangement is not converted and does not "
                         "need to be -- the C64 engine ignores position "
                         "entirely and repacks the field itself by the first "
                         "camp (#110, goldbox/layout.py 0x020)"),
    ("class_levels", "permuted from class number to class bit"),
    ("spells_castable_cleric", "packed into the C64's high nibbles"),
    ("spells_castable_magic_user", "packed into the C64's low nibbles"),
    ("size", "1/2 on DOS becomes 0/1 on the C64"),
    ("attack_forms", "copied as a block"),
    ("roster_tail", "copied as a block into the C64's roster tail"),
    ("field_10c_10f", "the four bytes read apart: 0x10C indexed into the "
                      "neutral status, 0x10D into active, 0x10E into "
                      "hostile and 0x10F into quickfight (#235, "
                      "docs/169-dos-combat-side.md)"),
    ("unnamed_0ab", "the identity draw the C64's add screen never needs, "
                    "given a home instead of a digest: written into the "
                    "C64's identity_pair at 0x0E6, with 0x0E7 left zero "
                    "(#258, The C64 side of 0x0AB is unnamed, so the "
                    "conversion drops it with no issue behind it)"),
    # #130 (A converted DOS party arrives with six identical combat figures,
    # not its own): the composition and the tables are in
    # `goldbox/iconparts.py`; `IconParts.dos_icon` is what `to_c64_record`
    # calls through `_icon_for`.
    ("icon_head", "DOS art: CHEAD.DAX, the combat icon's head. Converted "
                  "through the head table in tools/iconproposal.yaml into "
                  "one of the C64's own head options"),
    ("icon_body", "DOS art: CBODY.DAX, the combat icon's body. Converted "
                  "through the body table in tools/iconproposal.yaml -- the "
                  "C64 draws a whole pose, arms and any held item included, "
                  "as one WEAPON option -- into one of the C64's own weapon "
                  "options"),
    ("icon_colours", "the DOS combat figure's own colours: six pairs of "
                     "4-bit indices, one pair per part, the low nibble the "
                     "main colour and the high one the highlight. Converted "
                     "through the colour table in tools/iconproposal.yaml -- "
                     "the low nibble of each pair for most parts, the high "
                     "one for the leg and the shield, which it covers more "
                     "of -- into the C64's own eighteen colours over its "
                     "seven named parts"),
)


#: Fields only the titles after Pool of Radiance declare, and what the
#: conversion does with each.  Kept out of :data:`TRANSFORMED` and
#: :data:`DROPPED` because those two are asked of every title and Pool of
#: Radiance declares none of these.
LATER_TITLE_TRANSFORMED: tuple[tuple[str, str], ...] = (
    ("former_class_levels", "the class a dual-classed character left, "
                            "permuted from class number to class name and "
                            "written into the C64's dual_class_slot and "
                            "dual_class_level"),
    ("former_level", "the same level again; checked against the array and "
                     "folded into former_levels"),
    ("spells_castable_druid", "the third slot array, converted into the "
                              "neutral record beside the cleric's and the "
                              "magic-user's"),
)

LATER_TITLE_DROPPED: tuple[tuple[str, str], ...] = (
    ("paladin_cures",
     "the paladin's cure-disease bookkeeping, which the C64 record has "
     "nowhere to keep: no byte of the C64 record is 1 for a paladin and 0 "
     "for everybody else across the 78 C64 records this project holds, 12 "
     "of them paladins, and the only two that separate paladins at all are "
     "the class byte itself and one that tracks level. The DOS writer puts "
     "back the value every engine-written paladin record holds, derived "
     "from the class, so a converted paladin's record is the one the game "
     "would have written. **What a player gains by it is not established**: "
     "staged both ways in the running Silver Blades game the sheet offers "
     "CURE either way, so the byte does not gate the command there"),
    ("highest_class_levels",
     "Pools of Darkness' third level array, the level to restore a drained "
     "character to; there is no C64 Pools of Darkness to convert to"),
)

#: DOS fields the C64 recomputes or never needed in the first place, measured
#: rather than assumed -- `.claude/rules/conversions.md`'s "a field the
#: destination derives on load needs no line, and that derivation has to be
#: demonstrated in the running game first."  Reported by `field_disposition`
#: as `derived:` rather than `dropped:`, and never shown to a player: the
#: the import-side counterpart of the export side's own accounting, over
#: the DOS field vocabulary the way :data:`DROPPED` is.  Four of these
#: fields appear on that side too, in :data:`WRITE_UNSOURCED` rather than
#: in :data:`WRITE_DERIVED`, which holds only `unnamed_0ab`.
#:
#: `(name, why, the run that demonstrated it)` -- a row with nothing in the
#: third field is a row nobody has earned yet.
#:
#: #324 (The import pane tells a player nine fields could not be converted
#: that the C64 recomputes for itself).
DERIVED: tuple[tuple[str, str, str], ...] = (
    ("item_chain", "live heap state: the DOS item list is a chain of far "
                   "pointers, rebuilt by the engine on load; the C64 keeps "
                   "sixteen fixed slots instead and needs none of it",
     "the engine's own far pointer in 30 of 30 engine-written records "
     "with items and without, and rebuilt on load (#61, #62, #69)"),
    ("heap_104", "live heap pointers, rebuilt by the engine on load",
     "the engine's own far pointer in 5 of 6 engine-written records, and "
     "carried through a resave unread (#61, #62, #69)"),
    ("effect_chain", "live pointer to the effect list; the effects "
                     "themselves come from the .SPC file and the engine "
                     "rebuilds the chain on load",
     "rebuilt on load in engine-written records with items and without "
     "(#61, #62, #69)"),
    ("hands_used", "live combat state, set again the next time the "
                   "character fights",
     "measured zero in engine-written records with items and without "
     "(#61, #62, #69)"),
    ("encumbrance", "derived -- money plus item weight; the C64 has no such "
                    "field and recomputes what it needs",
     "27 of 27 converted characters balance exactly against money and item "
     "weight (b8a64ea, test_encumbrance_balances_against_money_and_item_"
     "weights)"),
    ("item_count", "implied by the C64's sixteen fixed slots, which it "
                   "counts for itself on load",
     "27 of 27 converted characters balance exactly (b8a64ea)"),
    ("strength_bonus", "a boolean on DOS; the C64 writer sets its own home "
                       "-- strength_bonus_flag at 0x0E3 -- to the constant 1 "
                       "that GEN's creation writes there, so nothing here is "
                       "a loss.  Not 0x0E2, which is the separate computed "
                       "strength index",
     "#277 (A DOS character converted to the C64 loses the strength bonus "
     "to hit and damage, because 0x0E3 is written zero), closed"),
)

#: DOS fields written to the one value every specimen this project has read
#: holds, so nothing a player did produced a different one -- the import-side
#: counterpart of :data:`WRITE_CONSTANTS`.  Reported by `field_disposition`
#: as `constant:` rather than `dropped:`, and never shown to a player.
#:
#: #324 (The import pane tells a player nine fields could not be converted
#: that the C64 recomputes for itself).
CONSTANTS: tuple[tuple[str, str], ...] = (
    # The byte-level evidence is in `docs/141-dos-savegame.md`, under
    # "0x083-0x087: a constant, and what that rests on": 00 00 01 00 00 in
    # 101 of 101 engine-written Pool of Radiance records -- 20 characters,
    # eight classes, levels 1-4, before a fight and after one, and on a
    # character the engine knocked unconscious -- and the sheet is
    # pixel-identical whatever it holds (#235, #304).
    ("field_83_87", "always the same five bytes, and the character sheet "
                    "looks identical whichever value they hold, so nothing "
                    "here is a loss a player would notice"),
)

#: The same, for a field only a later title declares -- split off the way
#: :data:`LATER_TITLE_DROPPED` is split off :data:`DROPPED`, so that
#: `field_disposition` for Pool of Radiance is built from the tables Pool of
#: Radiance actually has (#324).
LATER_TITLE_CONSTANTS: tuple[tuple[str, str], ...] = (
    ("spells_castable_unattributed",
     "Secret of the Silver Blades' fourth spell-slot array, which no shipped "
     "character sets a byte of and nobody has attributed to a class"),
)

#: How the ability pairs are reported for a title that keeps two copies.
_PAIRED_ABILITY = ("the first of the title's two copies; the second goes to "
                   "the neutral abilities_second, and neither codec claims to "
                   "know which the engine treats as current")


def field_disposition(shape: "int | str | DosShape" = POOL_OF_RADIANCE
                      ) -> dict[str, str]:
    """Every field one title declares and what the conversion does with it.

    The test that keeps this module honest: a field declared in
    `goldbox/dos_layout.py` and named nowhere here would be a field silently
    dropped, which `docs/117-save-conversion.md` forbids.  The shape is
    `goldbox/neutral.py`'s, so every direction reports its drops the same way.

    **Asked per title**, because the four tables are not the same table: Curse
    of the Azure Bonds and Secret of the Silver Blades declare fields Pool of
    Radiance has never heard of, and Pools of Darkness is missing nine of Pool
    of Radiance's.  Answering with Pool of Radiance's disposition for all four
    is what let `former_class_levels` sit unnamed.
    """
    shape = shape_for(shape)
    declared = set(FIELDS_BY_NAME_FOR[shape.key])
    paired = {n for n in ABILITY_ORDER
              if n in declared and FIELDS_BY_NAME_FOR[shape.key][n].size > 1}

    def only(rows):
        return tuple((n, w) for n, w in rows if n in declared and
                     n not in paired)

    # `DERIVED` drops its third field here: the run that demonstrated a row
    # is what keeps the row honest in the source, and is not part of what a
    # report says (#324).
    return neutral.disposition(
        only(DIRECT),
        only(TRANSFORMED + LATER_TITLE_TRANSFORMED)
        + tuple((n, _PAIRED_ABILITY) for n in ABILITY_ORDER if n in paired),
        only(DROPPED + LATER_TITLE_DROPPED),
        "the C64's",
        derived=only(tuple((n, w) for n, w, _run in DERIVED)),
        constants=only(CONSTANTS + LATER_TITLE_CONSTANTS))


def portrait_tables(game: str | pathlib.Path | None
                    ) -> tuple[PortraitTables | None, str]:
    """The creation menu's portrait tables out of a DOS game directory.

    Returns `(tables, why_not)`, never raises: the portrait is one cosmetic
    pair of bytes and a game directory that cannot answer for them is a
    reason to report them, not to refuse a conversion that is right in every
    other field.  `goldbox/portraits.py` has the two tables and what they are.
    """
    if game is None:
        return None, ("no DOS game directory was given, and the menu tables "
                      "that turn a portrait into an art id are in its own "
                      "START.EXE")
    try:
        return tables_from_dos(game), ""
    except PortraitError as e:
        return None, str(e)


#: The DOS shapes :func:`to_neutral` will read into a neutral character, and
#: therefore the titles the import converts.  **Curse of the Azure Bonds
#: joined this list as step 4 of `#192 (Convert a Curse of the Azure Bonds
#: DOS save into a C64 one, which the importer refuses today)`**, after step 3
#: loaded a converted Curse save in the running game and read the sheet: six
#: characters matched their DOS save on race, sex, age, alignment, class, all
#: seven abilities, level, experience, HP, AC, THAC0, movement and money, the
#: spellbook listed all nine ids, the party walked, and `ENCAMP > SAVE` came
#: back differing only in bytes the engine itself rewrote.
#:
#: Secret of the Silver Blades joined on 2026-09-05, on the same standard and
#: the same six checks (#193): the loader took a disk this project built, the
#: panel drew all six characters with the DOS save's own AC and HP, six of six
#: sheets matched, `MEMORIZE` on a magic-user 9 offered her 117-spell book and
#: took four picks out of six presses from a ceiling the engine worked out
#: itself, the party walked, and the engine's own resave differed in 600 bytes
#: of 7424 -- every one of them the engine's, 594 being `ANIMATE00`'s picture
#: buffer, which the engine decodes afresh at every camp (#309,
#: `docs/181-curse-picture-buffer.md`).  Four faults were found and fixed on the way, two of
#: which Curse had shipped with: a lower-case name drawing as punctuation, and
#: a ranger arriving as a paladin.  It waited on #287, where every converted
#: human saw in the dark.
#:
#: Pools of Darkness will never join it -- there is no C64 port to convert to.
CONVERTS: tuple[DosShape, ...] = (POOL_OF_RADIANCE, CURSE_OF_THE_AZURE_BONDS,
                                  SECRET_OF_THE_SILVER_BLADES)

#: The seven abilities in the order both ports store them, which is also the
#: order Curse's pairs run in.  `goldbox/neutral.py`'s, because the C64 codec
#: needs the same order and neither may import the other.
ABILITY_ORDER = neutral.ABILITIES

#: DOS class number -> the class name, for the level arrays.  The first
#: element of :data:`CLASS_LEVEL_SLOTS`' rows, hoisted so a former-class array
#: can be read with the same permutation as the current one.
CLASS_BY_SLOT: dict[int, str] = {n: name for n, name, _ in CLASS_LEVEL_SLOTS}


def _ability_pair(dos: "DosCharacter", name: str) -> tuple[int, int]:
    """One ability as `(first, second)`, whichever shape the title stores.

    Pool of Radiance keeps one byte and every later title keeps two, so the
    single byte answers for both halves rather than the reader having to
    branch: a title with one copy has the same value in both places by
    definition.

    **The two are equal in every record this project can reach** -- 0 of 406
    pairs differ, over 58 distinct Curse records, and the six C64 Curse
    records in `work/issue32/specimens/` hold `0x014`-`0x01F` and
    `0x065`-`0x070` byte for byte identical.  So no specimen says which is
    which, and none is likely to: the settling experiment is to cast
    `Strength` on a fighter in DOS Curse, save, and see which byte of the
    pair moves.
    """
    raw = dos.raw(name)
    return raw[0], raw[-1]


def to_neutral(dos: DosCharacter,
               portraits: PortraitTables | None = None) -> NeutralCharacter:
    """Read one DOS character into the neutral record.

    The DOS half of the pair `goldbox/neutral.py` describes, and the only half
    that knows a DOS offset.  It names where every value came from and what
    the DOS record holds that no neutral field does; what becomes of them
    afterwards is a writer's business.

    `portraits` is the creation menu's two tables, from
    :func:`portrait_tables`.  With them the sheet portrait crosses -- the DOS
    record's menu position becomes the art id the neutral record carries,
    which is what the C64 stores -- and without them it is reported as a
    drop, exactly as it was before #57.
    """
    if dos.shape not in CONVERTS:
        raise WrongTitleError(
            f"{dos.shape.title} records read, but only "
            f"{', '.join(s.title for s in CONVERTS)} converts: no other pair "
            f"of ports has been measured against each other (#53)",
            title=dos.shape.title)
    out = NeutralCharacter("DOS", source=dos.source, game=dos.shape.key)

    # -- the name: a count byte and fifteen characters -----------------------
    out.set("name", dos.name, "the DOS count byte and text at 0x000",
            FIELDS_BY_NAME["name_text"].confidence, Provenance.RESHAPED)

    # -- everything the two ports encode the same way ------------------------
    # `dos.fields`, not the module-level table: the offset quoted in a
    # provenance line is this title's, and only Pool of Radiance's is the
    # module's.
    for dos_name, _ in DIRECT:
        if dos_name in ABILITY_ORDER:
            continue                      # a pair in three of the four titles
        f = dos.fields[dos_name]
        out.set(dos_name, dos.get(dos_name),
                f"DOS {dos_name} @{f.offset:#05x} ({f.confidence})",
                f.confidence)

    # -- the class mask, which is *not* the DOS byte -------------------------
    # DOS gives the paladin and the ranger the same bit 6; the neutral record
    # and the C64 give the ranger bit 7.  See `NEUTRAL_CLASS_BIT_FOR_SLOT`:
    # copying the byte sent a DOS ranger to the C64 as a paladin holding a
    # ranger's levels.
    f = dos.fields["class_bits"]
    out.set("class_bits", neutral_class_bits(dos),
            f"DOS class_bits @{f.offset:#05x} ({f.confidence}), reread from "
            f"the level array because DOS gives the paladin and the ranger "
            f"one bit between them",
            f.confidence, Provenance.RESHAPED)

    # -- the abilities, which are a (first, second) pair after Pool of --------
    # Radiance.  Both halves cross; the first goes to the neutral ability and
    # the second to `abilities_second`, and neither codec claims to know
    # which the engine treats as current -- see `_ability_pair`.
    second: dict[str, int] = {}
    for dos_name in ABILITY_ORDER:
        f = dos.fields[dos_name]
        first, last = _ability_pair(dos, dos_name)
        out.set(dos_name, first,
                f"DOS {dos_name} @{f.offset:#05x} ({f.confidence})"
                + (", the first of its two bytes" if f.size > 1 else ""),
                f.confidence)
        second[dos_name] = last
    if any(dos.fields[n].size > 1 for n in ABILITY_ORDER):
        out.set("abilities_second", second,
                f"DOS {dos.shape.title} keeps every ability twice; these are "
                f"the second byte of each pair",
                Confidence.CONFIRMED, Provenance.RESHAPED)

    # -- the spellbook: one byte per spell ------------------------------------
    book = dos.fields["spellbook"]
    out.set("spells_known", dos.spells_known,
            f"DOS spellbook @{book.offset:#05x}, one byte per spell across "
            f"{book.size} of them", book.confidence)

    # -- memorised spells, put into the neutral order: highest first ---------
    mem = dos.fields["spells_memorised"]
    out.set("spells_memorised", dos.spells_memorised,
            f"DOS {mem.offset:#05x}, {mem.size} slots reversed into the "
            f"neutral highest-first order", mem.confidence)

    # -- the per-class levels, named rather than numbered --------------------
    def _by_class(field: str) -> dict[str, int]:
        raw = dos.raw(field)
        return {name: raw[n] for n, name in CLASS_BY_SLOT.items()
                if n < len(raw)}

    f = dos.fields["class_levels"]
    out.set("levels", _by_class("class_levels"),
            f"DOS class_levels @{f.offset:#05x}, permuted from class number "
            f"to class bit", f.confidence)

    # -- the class a dual-classed human left, where the title has one --------
    # Curse of the Azure Bonds and everything after it keep a second copy of
    # the level array holding what the character *was*, and the same level
    # again in the single byte right after `level` (#234).  Pool of Radiance
    # has neither and sets nothing here.
    if "former_class_levels" in dos.fields:
        f = dos.fields["former_class_levels"]
        former = {name: level for name, level in _by_class(
            "former_class_levels").items() if level}
        lf = dos.fields["former_level"]
        byte_value = dos.raw("former_level")[0]
        if len(former) == 1:
            ((only_name, only_level),) = former.items()
            if byte_value != only_level:
                out.warnings.append(
                    f"DOS former_class_levels @{f.offset:#05x} holds "
                    f"{only_name} {only_level} and the byte after level "
                    f"@{lf.offset:#05x} holds {byte_value}; the two should "
                    f"agree and do not, so former_levels is taken from the "
                    f"array")
        elif not former and byte_value:
            out.warnings.append(
                f"DOS former_class_levels @{f.offset:#05x} is all zero but "
                f"the byte after level @{lf.offset:#05x} holds {byte_value}, "
                f"which should mean a dual-classed character; former_levels "
                f"is left empty")
        out.set("former_levels", former,
                f"DOS former_class_levels @{f.offset:#05x}, permuted the "
                f"same way as the current array, non-zero entries only",
                f.confidence)

    # -- spell slots, by class: two arrays on Pool of Radiance, three after --
    castable = {"cleric": tuple(dos.raw("spells_castable_cleric")),
                "magic-user": tuple(dos.raw("spells_castable_magic_user"))}
    if "spells_castable_druid" in dos.fields:
        castable["druid"] = tuple(dos.raw("spells_castable_druid"))
    where = ", ".join(
        f"{name} @{dos.fields['spells_castable_' + key].offset:#05x}"
        for name, key in (("cleric", "cleric"), ("druid", "druid"),
                          ("magic-user", "magic_user"))
        if "spells_castable_" + key in dos.fields)
    out.set("spells_castable", castable, f"DOS {where}",
            dos.fields["spells_castable_cleric"].confidence)

    # -- size: DOS 1 small / 2 medium, the neutral 0 small / 1 large ---------
    out.set("size_small", max(0, dos.get("size") - 1),
            "DOS size @0x0C0, less one", FIELDS_BY_NAME["size"].confidence)

    # **The turning byte is not read into the neutral record at all** (#297).
    # It is the row of the turning matrix the *target* answers to
    # (`GAME.OVR:0x13A2A`), it is 0 for every player character, and the DOS
    # engine works a caster's own strength out from `class_levels[0]` when
    # the command is pressed. `goldbox.c64_codec.write` computes the C64's
    # `turn_power` from the levels for the same reason (#288), so there is
    # nothing here for either side to take. It is named in `DROPPED`.

    # -- the identity draw: no longer a drop, now that it has a C64 home -----
    # `to_c64_record` writes this into the C64's identity_pair at 0x0E6, with
    # 0x0E7 left zero (#258, docs/170-c64-identity-pair.md).  A pure DOS
    # round trip still ignores it in favour of `identity_byte`'s digest --
    # see `write`'s own comment on the point -- so carrying it here changes
    # nothing about that guarantee and only gives the C64 writer something to
    # take.
    ident = FIELDS_BY_NAME["unnamed_0ab"]
    out.set("unnamed_0ab", dos.get("unnamed_0ab"),
            f"DOS unnamed_0ab @{ident.offset:#05x} ({ident.confidence})",
            ident.confidence)

    # -- the combat tail: how the character is, and which side it fights on --
    # `field_10c_10f` is four bytes and all four are a character's own state
    # rather than fill (#235, docs/169-dos-combat-side.md).  0x10C is the
    # status, 0-based, indexing the nine words `neutral.STATUS_NAMES` carries
    # in the engine's own order -- CONFIRMED against the sheet, which drew
    # STATUS OKAY and STATUS UNCONSCIOUS for one character staged 0 and 4.
    # 0x10D is an active flag, CONFIRMED: 0 draws the name red in the party
    # panel and 1 does not, 3 of 3 against 9 of 9 across two boots of the
    # running game.  0x10E is the combat side, 1 for the enemy's, CONFIRMED
    # from the DOS engine's own combat code and the running game (a party
    # member staged to it attacked his own side and was dropped from the
    # party when the fight ended).  0x10F is the quickfight flag, CONFIRMED
    # by effect: a party staged with it set fought its next battle under
    # computer control with the player never asked for a command.
    #
    # A status value past the end of the table is not a state the engine can
    # draw, so it is reported rather than turned into the nearest name.
    tail = dos.raw("field_10c_10f")
    if tail[0] < len(neutral.STATUS_NAMES):
        out.set("status", neutral.STATUS_NAMES[tail[0]],
                f"DOS status @0x10C = {tail[0]}, the game's own "
                f"{len(neutral.STATUS_NAMES)} status words in order",
                Confidence.CONFIRMED, Provenance.RESHAPED)
    else:
        out.drop(f"The character's status: this save holds {tail[0]} there "
                 f"and the game has only {len(neutral.STATUS_NAMES)} states")
    out.set("active", bool(tail[1]),
            "DOS 0x10D: 0 is the flag that draws the name red in the party "
            "panel", Confidence.CONFIRMED)
    out.set("hostile", bool(tail[2]),
            "DOS 0x10E: the combat side, 1 for the enemy's",
            Confidence.CONFIRMED)
    out.set("quickfight", bool(tail[3]), "DOS 0x10F",
            Confidence.CONFIRMED)
    out.set("attack_forms", dos.raw("attack_forms"), "DOS 0x0A1 (PROBABLE)",
            FIELDS_BY_NAME["attack_forms"].confidence)
    out.set("roster_tail", dos.raw("roster_tail"),
            "DOS 0x112: the armour bonus and the eight running attack-form "
            "bytes, one for one",
            FIELDS_BY_NAME["roster_tail"].confidence)

    # -- the .SPC file splits in two: innate, and running ---------------------
    # Only the innate half crosses, which is what the game's own C64 importer
    # does too, and the running half is **not** put in front of the player.
    # Donald, 2026-08-27: *"For running effects, that would expire after a
    # certain period of time, we do not need to report those. The user will
    # not expect this to carry over, so reporting it is unnecessary."*  A
    # Bless that had four rounds left is not a loss anybody can see.
    #
    # An **innate** effect that cannot be converted is the opposite and is
    # always reported -- a racial bonus a player paid for at character
    # creation and would go looking for.  `INNATE_EFFECTS` is where the line
    # is drawn in the bytes and it is the same line drawn here.
    # `docs/133-active-effects.md` records what a running effect is; the
    # active-effect arrays are zeroed by `EFFECT_ARRAYS` in `convert_save`.
    out.set("innate_effects",
            [e for e in dos.effect_ids if e in INNATE_EFFECTS],
            "the innate ids of the DOS .SPC file; the two ports share one "
            "effect-id namespace (goldbox/traits.py)",
            Confidence.PROBABLE)

    # -- the .SPC records INNATE_EFFECTS turns away, converted whole ----------
    # A ring, a girdle or a cloak grants an effect the same way a race does,
    # and the id alone cannot say what the ring is worth: the record's own
    # value byte and the flag the engine reads when the item comes off are
    # what make the effect what it is, so the whole record crosses rather
    # than a number out of it (#232, An item-granted effect is dropped on the
    # way through the neutral record, with no report).
    #
    # **The engine's own test for "has this run out" is the duration at
    # bytes 1-2, and nothing else.** Its expiry routine compares that word
    # against zero: zero skips the node for ever, and anything else is
    # counted down as the clock advances and the node removed on the step
    # that reaches it -- so a saved record at zero was written that way and
    # never counted down to it. The id is not consulted and the engine holds
    # no table of permanent ids. CONFIRMED from the routine's own
    # instructions and watched running: six two-minute BLESS records gone
    # after four steps, eight zero-duration racial records untouched.
    # `docs/162-spc-permanence.md` has the routine, every one of the 38
    # places that add a record, and the runs.
    #
    # So a **nonzero** duration is a spell counting down, and Donald's
    # 2026-08-27 ruling says it needs no report: it was going to expire
    # anyway and the player will not go looking for it.  It is the one thing
    # here that is neither converted nor reported.
    #
    # The next pointer is dropped rather than converted: it is a live heap
    # address the engine rebuilds on load (`EFFECT_NEXT_NULL`).
    granted = [bytes(e[:5]) + EFFECT_NEXT_NULL for e in dos.effects
               if e[0] not in INNATE_EFFECTS
               and int.from_bytes(e[1:3], "little") == 0]
    if granted:
        out.set("granted_effects", granted,
                "the .SPC records that are not innate and never expire -- an "
                "item's grant, whole, since what it is worth is in the "
                "record rather than in the id",
                Confidence.CONFIRMED)

    # -- the .ITM file, projected -------------------------------------------
    out.set("inventory", [it.to_c64() for it in dos.items],
            "the .ITM file, each 63-byte record projected onto sixteen bytes",
            Confidence.CONFIRMED)

    # -- the sheet portrait: a menu position becomes the art's own id --------
    # The two ports choose from one menu of fourteen heads and twelve bodies,
    # and the table of ids is in both binaries, byte for byte and in the same
    # order (#57).  DOS stores where in the menu; the C64 stores what the
    # menu chose, which is the id of a `HEAD<xx>` file.  Head and body move
    # independently -- CONFIRMED on three sheets of one character in DOSBox
    # -- so a position the menu cannot answer for takes only its own half
    # out.
    #
    # **Only Pool of Radiance's C64 sheet draws a face at all**, so only Pool
    # of Radiance has anything here to lose -- #300 (A Curse or Silver Blades
    # party imported to the C64 arrives with no sheet portrait, because the
    # creation menu is read only off a POOL<n>.D64).  `LIBRARY $48A4` asks
    # the loader for the `HEAD<xx>`/`BODY<xx>` the record names; Pool of
    # Radiance calls it from three places and Curse and Silver Blades from
    # none, over 558 and 571 files, and a real portrait id written into every
    # record in the running game changes neither of their sheets
    # (`docs/188-the-sheet-portrait-per-title.md`).  A converted Curse or
    # Silver Blades character arrives correct with no face, so nothing is
    # said: the conversion is still attempted where the tables allow it,
    # because a byte converted costs nothing, but a title whose engine draws
    # no portrait gets no line whatever happens.
    draws_portrait = draws_sheet_portrait(dos.shape.key)
    converted_portrait: set[str] = set()
    for name, art_of, stem in (("portrait_head", "head_art", "HEAD"),
                               ("portrait_body", "body_art", "BODY")):
        if portraits is None:
            continue
        f = FIELDS_BY_NAME[name]
        position = dos.get(name)
        art = getattr(portraits, art_of)(position)
        if art is None:
            label = "head" if name == "portrait_head" else "body"
            if draws_portrait:
                out.drop(f"Character portrait ({label}): position {position} "
                         f"in this save is not one the character-creation "
                         f"menu offers, so no matching C64 {stem}nn portrait "
                         f"exists")
            continue
        out.set(name, art,
                f"DOS {name} @{f.offset:#05x} = menu position {position}, "
                f"which is {stem}{art:02X} in {portraits.source}",
                f.confidence, Provenance.RESHAPED)
        converted_portrait.add(name)

    # -- what the DOS record holds and no neutral field does ------------------
    # `UNREPORTED_DROPS` is still in `DROPPED`, so `field_disposition` still
    # accounts for every name in it; what it is kept out of is the list a
    # person reads.  `DERIVED` and `CONSTANTS` are not in `DROPPED` at all
    # any more (#324), so the loop below never sees `item_chain`, `heap_104`,
    # `effect_chain`, `hands_used`, `encumbrance`, `item_count`,
    # `strength_bonus`, `field_83_87` or `spells_castable_unattributed`, and
    # `icon_head`/`icon_body`/`icon_colours` are `TRANSFORMED` rather than
    # dropped (#130).
    silent = set(UNREPORTED_DROPS)
    if not draws_portrait:
        # Nothing was lost: this title's sheet draws no face for any
        # character, including one the engine made itself (#300).
        silent |= {"portrait_head", "portrait_body"}
    for name, _why in DROPPED:
        if name in silent:
            continue
        if name in converted_portrait:
            continue
        out.drop(DROPPED_PLAYER_TEXT[name])
    return out


def _icon_for(char: "DosCharacter", icon: "bytes | IconParts | None",
              tables: "DosIconTables | None" = None) -> bytes | None:
    """The 36 bytes this character's own combat figure becomes (#130).

    `icon` is either the composed bytes every character shares -- which is
    what a port with no DOS icon fields supplies -- or the C64's own option
    tables, in which case each character gets the figure his own record
    names.  `IconParts.dos_icon` composes it the way the game's own ICON
    menu composes one, so every icon written here is one the game can make.

    `tables` is this title's own correspondence, read once by the caller --
    `tools/iconproposal.yaml` names a different C64 option for a few DOS
    figures at the small size, and for one of Silver Blades' heads, and
    without it every character would be composed from the base table
    whatever he is being converted into (#335).
    """
    if not isinstance(icon, IconParts):
        return icon
    return icon.dos_icon(char.get("icon_head"), char.get("icon_body"),
                         dos_size(char.get("size")),
                         bytes(char.get("icon_colours")),
                         tables=tables)


def to_c64_record(dos: DosCharacter, icon: bytes | None = None,
                  portraits: PortraitTables | None = None,
                  ) -> tuple[CharacterRecord, Report]:
    """Build a 580-byte C64 character record from a DOS one.

    A DOS read and a C64 write with the neutral record between them, which is
    all this function is now.  `icon` is the 36-byte combat icon; DOS has no
    equivalent -- its art is a different set -- so with none given the field
    is left zero and reported.  `portraits` is the creation menu's two
    tables, from :func:`portrait_tables`; without them the sheet portrait is
    reported as a drop rather than converted (#57).

    The report names no character: it is one character's provenance, and which
    character that is belongs to the caller, which is the only thing that
    knows the slot and the marching position.  `convert_save` prefixes each of
    its own notes that way (#107).

    **The name is folded to capitals on the way across**, which is the one
    thing this function does that is not a straight hand-off; see
    :func:`c64_name`.
    """
    out = to_neutral(dos, portraits=portraits)
    field = out.fields.get("name")
    if field is not None:
        out.set("name", c64_name(str(field.value)),
                field.origin + ", folded to capitals for the C64's own "
                               "character set",
                field.confidence, Provenance.RESHAPED)
    return c64_codec.write(out, icon=icon)


def c64_name(name: str) -> str:
    """A DOS name as the C64 can draw it: capitals, no trailing blanks.

    **A lower-case letter in a name is not a letter on a C64 screen.**  The
    game draws its text in the uppercase/graphics character set, where the
    screen code for a byte in `$61`-`$7A` is that byte less `$40` -- so `u`
    is `5`, `y` is `9`, `d` is `$` and `e` is `%`.  Watched on the running
    machine, `#193` step 3: Secret of the Silver Blades' own DOS pregen is
    named `Guy de Valois ` and, converted byte for byte, his name drew in the
    party panel and at the head of his character sheet as

        G59 $% V!,/)3

    which is exactly `G`, then each lower-case letter mapped by that rule.
    The other five characters of the same party are named in capitals and
    drew correctly, so it is the case and nothing else.

    **SSI did the same thing themselves.**  The C64 `SAVEDBASH` on
    `SILVER-6.D64` holds `GUY DE VALOIS` for the character DOS calls
    `Guy de Valois `, and that name is the only field of the six shipped
    characters where the two ports' records differ for a reason that is not
    a separate roll (`tools/ssbtwins.py`).  So capitals are what the
    destination port's own copy of this party has.

    The trailing blanks go for the same reason: DOS counts a trailing space
    into `name_length` and the C64 field is NUL-padded, so a name ending in
    one draws a stray space in a fixed-width column.

    **This is the DOS-to-C64 path only, and the same fault is reachable from
    any other source a C64 record can be written from** -- `c64_codec.write`
    is where it would be closed for all of them, and that file is another
    ticket's.
    """
    return name.upper().rstrip()


# ---------------------------------------------------------------------------
# The writing half: a neutral character becomes a DOS record (#26)
# ---------------------------------------------------------------------------
@dataclasses.dataclass
class WriteReport(neutral.Report):
    """A DOS write's provenance: **every** byte of both outputs explained.

    Offsets 0 to `RECORD_SIZE - 1` are the 285-byte character record;
    `RECORD_SIZE` and up are the `.ITM` payload that goes beside it, and the
    `.SPC` payload after that.  `total` is set by :func:`write` once the item
    and effect counts are known.
    """

    total: int = RECORD_SIZE

    @property
    def unaccounted(self) -> list[int]:
        """Offsets this conversion cannot explain. Should be empty."""
        return [i for i in range(self.total) if i not in self.sources]

    def summary_notes(self) -> list[str]:
        if self.unaccounted:
            return [f"  UNACCOUNTED: {len(self.unaccounted)} bytes"]
        return []


@dataclasses.dataclass
class SaveReport(neutral.Report):
    """A whole-save conversion's report: what was converted, and what was not.

    `sources` covers all 13137 bytes of `SAVGAM<slot>.DAT` and `converted` is
    the same account written for a person -- one line per field taken from
    the C64 save -- because a reader who wants to know whether the clock came
    across should not have to read 13137 provenance lines to find out.
    `warnings` is still only for what could not be done.
    """

    #: One line per field taken from the C64 save and written into the DOS one.
    converted: list[str] = dataclasses.field(default_factory=list)

    #: Offsets the conversion did not write, and so left to whatever the
    #: template held.  **Empty when there was no template**, and that is what
    #: makes "no template" checkable rather than asserted -- the same test
    #: `C64SaveReport.unwritten` is in the other direction (#118).
    unwritten: list[int] = dataclasses.field(default_factory=list)

    def address(self, offset: int) -> str:
        """`$4A20` for a variable, `byte 12804` for the tail.

        The file is a word array indexed by ECL address and then a run of
        plain bytes, so an offset means two different things depending on
        where it falls, and a report that said `0x1234` for both would be
        unreadable in exactly the region a reader is checking.
        """
        first = dos_savegame.VAR_OFFSET
        last = first + 2 * dos_savegame.VAR_WORDS
        if first <= offset < last:
            return f"${dos_savegame.VAR_BASE + (offset - first) // 2:04X}"
        return f"byte {offset}"

    def summary_notes(self) -> list[str]:
        lines = [f"  converted: {c}" for c in self.converted]
        if self.unwritten:
            lines.append(f"  {len(self.unwritten)} bytes left to the "
                         f"template, from {self.address(self.unwritten[0])}")
        return lines


def item_from_c64(record: bytes, item_size: int = ITEM_SIZE) -> bytes:
    """Project one C64 sixteen-byte item onto the DOS item record.

    The inverse of :func:`item_to_c64` for every field the two ports share:
    the C64's two packed bytes come apart into DOS's readied, hidden and
    cursed bytes, everything else is a straight copy.  The 46 bytes the C64
    has no words for are left empty, and each is a documented empty value
    rather than a guess: the rendered line at `0x001` is a cache the game
    rewrites whenever it draws the list, and NULL at `0x02A` is the chain's
    own last-item marker.

    `item_size` is the title's own stride, `DosShape.item_size` -- 63 in
    three of the four titles and **67 in Secret of the Silver Blades**, whose
    four extra bytes are :data:`ITEM_TAIL` and are zero in 48 of 48 item
    records this project drove the game into writing (#113).  So the longer
    record is the shorter one with four measured zeroes after it, and reading
    the stride from the shape is the whole of what the wider title needs.
    """
    if len(record) != 16:
        raise DosRecordError(f"a C64 item is 16 bytes; got {len(record)}")
    sizes = sorted({s.item_size for s in SHAPES})
    if item_size not in sizes:
        raise DosRecordError(
            f"a DOS item is {' or '.join(str(n) for n in sizes)} bytes; "
            f"got {item_size}")
    at = {n: ITEM_FIELDS_BY_NAME[n].offset for n in
          ("type_index", "name1", "name2", "name3", "plus", "plus_save",
           "readied", "hidden", "cursed", "weight", "quantity", "value",
           "charges", "effect", "power")}
    r = record
    out = bytearray(item_size)
    out[at["type_index"]] = r[0]
    out[at["name1"]], out[at["name2"]], out[at["name3"]] = r[1], r[2], r[3]
    out[at["plus"]], out[at["plus_save"]] = r[4], r[5]
    out[at["readied"]] = 1 if r[6] & 0x80 else 0
    out[at["hidden"]] = r[6] & 0x07
    out[at["cursed"]] = 1 if r[7] & 0x80 else 0
    out[at["weight"]:at["weight"] + 2] = r[8:10]
    out[at["quantity"]] = r[10]
    out[at["value"]:at["value"] + 2] = r[11:13]
    out[at["charges"]], out[at["effect"]], out[at["power"]] = r[13], r[14], r[15]
    return bytes(out)


#: Neutral field -> the DOS field it becomes, where the value crosses
#: unchanged.  The mirror of the reader's `DIRECT` above: the same fields, in
#: the other direction.
WRITE_DIRECT: tuple[tuple[str, str], ...] = (
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
    ("hp_rolled", "hp_rolled"),
    # Written, and then thrown away: the DOS loader allocates a fresh combat
    # icon slot for every character it reads, so this byte never survives a
    # load (#305).  It is written because it costs nothing, because the round
    # trip needs it, and because the number a party in file order gets is the
    # marching position this neutral field holds.
    ("party_order", "party_order"),
    ("hp_current", "hp_current"),
    ("thac0_current", "thac0_current"),
    ("armour_class", "armour_class"),
    ("movement_current", "movement_current"),
)

#: Neutral fields the DOS writer takes by a rule rather than by a copy.
WRITE_TRANSFORMED: tuple[tuple[str, str], ...] = (
    ("class_bits", "folded back into DOS's own order, where the paladin and "
                   "the ranger share bit 6 and the class number and the "
                   "level array are what tell them apart"),
    ("name", "length-prefixed into one count byte and fifteen ASCII"),
    ("portrait_head", "the C64's HEADnn id becomes the DOS record's menu "
                      "position, through the creation tables in the game's "
                      "own START.EXE (#57). Zero, and reported, when those "
                      "tables cannot be read or the id is not one of the "
                      "fourteen the menu offers"),
    ("portrait_body", "see portrait_head; twelve bodies rather than "
                      "fourteen heads"),
    ("levels", "permuted onto the DOS eight slots, which are indexed by the "
               "class number; a class with no number (knight) is reported"),
    ("spells_known", "unpacked to one byte per spell; the ids are identical, "
                     "and DOS even has the byte for id 56 the C64's mask "
                     "lacks"),
    ("spells_memorised", "reversed: DOS fills its sixteen slots from the "
                         "end, the neutral order is highest first"),
    ("spells_castable", "unpacked from the class map to two three-byte "
                        "runs, cleric at 0x0B2 and magic-user at 0x0B5"),
    ("size_small", "plus one -- DOS stores 1 small / 2 medium"),
    ("attack_forms", "copied as a block to 0x0A1"),
    ("roster_tail", "copied as a block to 0x112, the combat tail the C64 "
                    "roster keeps at -2"),
    ("inventory", "each sixteen-byte record unpacked onto a 63-byte .ITM "
                  "record; the count and the encumbrance are computed from "
                  "it, and an empty inventory writes no .ITM file at all "
                  "rather than an empty one -- ITM_OMITTED_WHEN_EMPTY"),
    ("innate_effects", "one nine-byte .SPC record each, id + INNATE_PAYLOAD "
                       "+ a NULL next pointer the engine rebuilds; only the "
                       "INNATE_EFFECTS ids are written, the rest reported, "
                       "and a character with none gets no .SPC file"),
    ("status", "the neutral name indexed back into the engine's own nine "
               "status words at 0x10C, which is the order neutral.STATUS_NAMES "
               "is in, so the index is the DOS number. A name DOS has no word "
               "for is reported"),
    ("active", "written to 0x10D, 1 for a character the party panel draws "
               "normally and 0 for one it draws red -- the opposite polarity "
               "to the C64's own bit, which is set for the same character"),
    ("hostile", "written to 0x10E, 1 for the enemy's side -- the same bit "
               "the C64 keeps at record 0x10C bit 0 (#235, "
               "docs/169-dos-combat-side.md)"),
    ("quickfight", "written to 0x10F -- the same bit the C64 keeps at "
                  "record 0x10C bit 7"),
    ("granted_effects", "written into the same .SPC file after the innate "
                        "records, each one's own five bytes with the next "
                        "pointer NULLed -- the value byte and the removal "
                        "flag are the record's, not INNATE_PAYLOAD's"),
    ("unnamed_0ab", "taken and written to 0x0AB when the source is a C64 "
                    "Pool of Radiance record, whose GEN draws the same "
                    "value at 0x0E6; anything else -- a DOS source, or a "
                    "Curse of the Azure Bonds or Silver Blades one, whose "
                    "GEN never draws it -- gets `identity_byte`'s digest "
                    "instead, exactly as before (#258, WRITE_DERIVED)"),
)

#: Neutral fields the DOS writer takes nothing from, and why.  Reported by
#: `Writer.finish` for any character that carries one, unless
#: :data:`WRITE_UNREPORTED_DROPS` names it.
WRITE_DROPPED: tuple[tuple[str, str], ...] = (
    ("infravision", "DOS does not store it; the DOS engine derives what it "
                    "needs from the race byte"),
    # The defensive half of this used to be in the `why` itself -- "this is
    # not a byte we have failed to find" -- which is a developer arguing with
    # a reviewer rather than an account of the field, and it reached a
    # report.  The argument, kept here where it belongs: the turn-undead
    # routine has been read end to end and the only record byte it takes is
    # the row belonging to the creature being turned, so there is no caster
    # byte to look for (#297, docs/178-turning-undead.md).
    ("turn_power", "the DOS game works a cleric's turning strength out for "
                   "itself, from his own class and level, at the moment the "
                   "player presses the command, so it keeps no byte for it "
                   "and there is nothing to write"),
    ("npc", "no attributed DOS field holds it"),
    ("encumbrance", "recomputed from money and item weight -- the identity "
                    "the DOS engine itself uses -- rather than copied"),
    # The two below are the later titles' fields, and this writer builds a
    # Pool of Radiance record: it declares one copy of each ability and no
    # former-class array, so there is nowhere to put either.  A C64 source
    # supplies neither today in any case -- `goldbox.c64_codec.read` sets
    # neither, which is where the export direction has its own work to do
    # (#234 for the dual class; the ability copy is unread on that side too).
    ("abilities_second", "a DOS Pool of Radiance record keeps one copy of "
                         "each ability score, so a second has nowhere to go"),
    ("former_levels", "a DOS Pool of Radiance record has no former-class "
                      "level array; that title does not let a character "
                      "change class"),
)

#: Writer drops the **player** is not shown, the mirror of the reader's
#: :data:`UNREPORTED_DROPS` on the way out.  The reader has had two lists
#: since 2026-08-27 and the writer had one, so every entry in
#: :data:`WRITE_DROPPED` reached a report -- #307 (The DOS writer's drop list
#: has no way to silence a field the DOS engine puts back on load).
#:
#: **Nothing measured leaves the code.**  A name here is still in
#: :data:`WRITE_DROPPED`, so :func:`write_field_disposition` still calls it a
#: drop and the accounting is unchanged; what goes is the line.
#:
#: **An entry needs a measurement, not an argument.**
#: `.claude/rules/conversions.md` allows silence for a field the destination
#: *derives*, and only when the derivation has been demonstrated in the
#: running game.
#:
#: * `turn_power` -- both engines work a cleric's turning strength out from
#:   his class and level when the player presses the command.  The DOS
#:   turn-undead routine was read end to end for #297 (A cleric converted
#:   from the C64 to DOS is given an undead's turning row, because the DOS
#:   writer puts turn_power in the undead's byte): the only record byte it
#:   reads is the row belonging to the creature being turned, and eleven of
#:   the 103 distinct DOS Pool of Radiance monster records carry a non-zero
#:   one against 0 for every player character in either port
#:   (`docs/178-turning-undead.md`).  The reader already silences its
#:   counterpart, `turn_class`, in :data:`UNREPORTED_DROPS`.
#:
#: **`spells_castable` is not here and that is not an oversight.**  #307 named
#: it as the second entry, and this writer composes no line for it: it is
#: `use`\\ d on every path, so the closing sweep never sees it, and a neutral
#: record with no `spells_castable` at all -- which is what a C64 Curse or
#: Silver Blades source produces, `RecordShape.spell_slots` being `False` for
#: both -- writes zeroes and reports nothing.  Measured over the 24 records
#: on the player's own disks: `turn_power` is the only `WRITE_DROPPED` line
#: any of them reaches.  `goldbox.c64_codec.NO_SPELL_SLOTS`, the
#: `spells_castable` line on the DOS-to-C64 direction, went the same way for
#: the same reason (#324): #192 step 3 and #193 step 3 both watched the
#: memorise screen enforce a ceiling nothing in the converted save wrote, so
#: it is a note over the six bytes it leaves zero rather than a line in
#: `report.dropped`.
WRITE_UNREPORTED_DROPS = frozenset({"turn_power"})


class SilencingWriter(neutral.Writer):
    """A `goldbox.neutral.Writer` with the reader's second list.

    `neutral.Writer.finish` composes a line for every neutral field the
    writer took nothing from.  This adds the other half the DOS *reader* has
    had since 2026-08-27: which of those a player is not told about, because
    the destination puts the field back for itself.

    The names in `silent` are counted as consumed by the sweep and by nothing
    else -- :func:`write_field_disposition` still calls each one a drop -- so
    the accounting is the same and only the list in front of a person is
    shorter.
    """

    def __init__(self, *args: Any, silent: Iterable[str] = (),
                 **kw: Any) -> None:
        super().__init__(*args, **kw)
        self.silent = frozenset(silent)

    def finish(self) -> None:
        self.taken.extend(n for n in self.silent if n not in self.taken)
        super().finish()

#: **A character carrying nothing gets no `.ITM` file at all**, and an empty
#: file is not the same thing as no file.  Measured, #62: the engine's own
#: save of a character whose items were all dropped in play writes no
#: `CHRDAT<slot><n>.ITM`, and handing it a zero-length one instead -- the same
#: 285 record bytes either way -- is what produced `WEAPON 254 PASSS`,
#: `DAMAGE 0D8-128`, `THAC0 148` and a phantom item in the next save.  The
#: only difference between the clean run and the garbage one is this file's
#: existence: `docs/50-experiments.md`, "A converted character who owns
#: nothing (#62)".
ITM_OMITTED_WHEN_EMPTY = True

#: DOS bytes with no source in any neutral field: live heap the engine
#: rebuilds, and the unattributed.  Zeroed and reported -- and **measured
#: survivable**: a slot whose records differ from the game's own only in
#: these regions loads and plays under DOSBox, and the game's own resave
#: keeps most of the zeroes (`docs/117-save-conversion.md`, the reverse
#: direction).  The round-trip test masks exactly this list rather than
#: whatever happened to differ.
#:
#: Each entry says which characters the zero has been measured against.  #62
#: is why that is written down: the whole list was measured on characters
#: *carrying items* and read as proven, and "a character carrying none" was a
#: case nobody had run.  Four entries have now been measured both ways --
#: the engine's own record for a character who dropped everything in play,
#: `work/p62/truth/CHRDATD1.SAV`.
WRITE_UNSOURCED: tuple[tuple[str, str], ...] = (
    ("effect_chain", "live heap pointer, and **NULL is right whatever the "
                     "character carries**: the engine allocates a node per "
                     ".SPC record on load and writes the head pointer "
                     "itself. Measured -- a slot loaded twice puts the same "
                     "party's nodes at different addresses (#61). NULL in "
                     "the engine's own record with items and without"),
    ("portrait_head", "**written whenever the game directory's creation "
                      "tables can be read, and only for Pool of Radiance**: "
                      "the C64's HEADnn id is a position in the same "
                      "fourteen-entry menu DOS indexes (#57). Zero when the "
                      "tables cannot be read or the id is not one the menu "
                      "offers, and reported in those two cases. Zero and "
                      "**not** reported for Curse of the Azure Bonds and "
                      "Secret of the Silver Blades: neither title draws a "
                      "sheet portrait on either port, so a character of one "
                      "of them has no face at either end and nothing was "
                      "lost (#300, docs/188-the-sheet-portrait-per-title.md). "
                      "Cosmetic, and the same with items and without"),
    ("portrait_body", "see portrait_head; the body half of the same pair"),
    ("icon_head", "the **combat** icon's head -- a different art set and a "
                  "different pair from the two above, and a different "
                  "ticket (#130). Zero"),
    ("icon_body", "see icon_head"),
    ("item_chain", "live heap pointer block; the items themselves are in "
                   "the .ITM file. **Zero is what the engine itself writes "
                   "for a character carrying nothing** -- measured, #62 -- "
                   "so the empty case is now right by value, not by luck"),
    ("hands_used", "live combat state with no attributed source. The engine "
                   "writes 2 for a fighter holding a weapon and **0 for the "
                   "same fighter after he drops everything**, so zero is "
                   "correct for exactly the character we could not source, "
                   "and #62's prime suspect is refuted"),
    ("heap_104", "live heap. Carried through a resave unread, with items and "
                 "without"),
)

#: DOS fields written as documented constants: `(name, bytes, why)`.  Each is
#: the one value all 24 specimens hold.
WRITE_CONSTANTS: tuple[tuple[str, bytes, str], ...] = (
    ("icon_dimension", b"\x01", "1 in all 24 DOS specimens"),
    ("turn_class", b"\x00",
     "no player character is undead. The byte is the row of the turning "
     "matrix a creature answers to -- eleven of the 103 distinct DOS Pool of "
     "Radiance monster records carry a non-zero one and every one of them is "
     "undead, at the published AD&D rows -- and every player character in "
     "either port reads 0. `goldbox.c64_codec.write` writes zero into the "
     "C64's own turn_class at 0x0A3 for the same reason (#297, "
     "docs/178-turning-undead.md)"),
    ("field_83_87", b"\x00\x00\x01\x00\x00",
     "a player character who takes one share of treasure. **Not one value "
     "every record holds**: the third byte is 1 in every record of the "
     "archives and 0 in 45 of the 54 Pool of Radiance records this project "
     "rolled itself, and `FIELD_83_87` has the counts and why (#304)"),
    ("strength_bonus", b"\x01", "1 in all 24 DOS specimens"),
)

#: Fields written to a **measured default** rather than converted from the
#: source, because the source holds something that does not correspond.
#: Distinct from :data:`WRITE_CONSTANTS`, whose values are the same in every
#: specimen we hold: a default is what a *newly made* character has, and a
#: played character's own value differs -- so a round trip has to mask these,
#: and `tests/test_doswriter.py` builds its mask from this table beside
#: `WRITE_UNSOURCED`.  Each entry is a reported drop as well as a write: the
#: player's own value is being replaced, and that is said out loud.
WRITE_DEFAULTS: tuple[tuple[str, bytes, str, str], ...] = (
    ("icon_colours", b"\x91\xA2\xB3\xC4\xE6\xF7",
     "the set a freshly made DOS character has -- 42 of the 54 shipped "
     "records across the four DOS titles, and the ones that differ are "
     "precisely the played parties (#57). Six pairs of 4-bit indices, one "
     "per part: body, arm, leg, hair and skin, shield, weapon; the low "
     "nibble is the main colour and the high one the highlight, which is "
     "what the game's own icon editor writes as COLOR-1 and COLOR-2",
     "zero is not neutral here: all six parts become EGA 8, dark grey, "
     "which is the combat floor's own colour, so the character is about 64 "
     "black outline pixels on its own shade and reads as not being there "
     "(#112, three fights). The C64's own icon colours are not converted "
     "across -- it has seven colour parts to DOS's six and one 3-bit "
     "colour per part against DOS's two 4-bit ones, so a correspondence "
     "would be a choice rather than a conversion"),
    ("field_10c_10f", b"\x00\x01\x00\x00",
     "okay, not shown red, not the enemy's side and not quick-fought -- "
     "the state a newly made DOS character is in. 0x10C is the status (0 "
     "Okay .. 8 Gone, the order of the game's own status words), 0x10D "
     "the flag that draws a name red in the party panel when it is 0, "
     "0x10E the combat side (1 the enemy's) and 0x10F the quickfight "
     "flag; all four measured in the running game and converted below "
     "when the source supplies them "
     "(#235, docs/169-dos-combat-side.md)",
     "written only when the source supplies none of status, active, the "
     "combat side or quickfight -- each of the four converts on its own "
     "when the source has it"),
)

#: Fields written from a rule over the **record itself** rather than from a
#: neutral value, a constant or a default.  One so far, and it is here because
#: a zero was measured harmful rather than merely unattributed.
#:
#: `tests/test_doswriter.py` masks these in the round trip beside
#: :data:`WRITE_UNSOURCED` and :data:`WRITE_DEFAULTS`: the value is ours and
#: not the source's, so a written record differing from the original here is
#: expected.
WRITE_DERIVED: tuple[tuple[str, str], ...] = (
    ("unnamed_0ab",
     "the identity byte the engine uses to tell two characters of the same "
     "name apart. Written by character creation as one call to the random "
     "routine and read in exactly one place -- ADD CHARACTER TO PARTY, which "
     "refuses a candidate whose **name and this byte both** match a "
     "character already in the party. Zero in every converted record made "
     "the six of a party indistinguishable there, and #216 measured the "
     "consequence in DOSBox: two different characters both named DUPLICO, "
     "the second one silently refused with this byte 0x00 in both and let "
     "in with 0x42 in the second, the engine's own save writing one "
     "CHRDATC<n>.SAV against two. So it is derived from the rest of the "
     "record instead -- a digest rather than a random draw, because a "
     "converter that writes different bytes on two runs of the same save "
     "cannot be diffed against itself.\n"
     "**One exception**: a C64 Pool of Radiance record keeps this same "
     "draw at 0x0E6-0x0E7 and never rewrites it either (#258, The C64 "
     "side of 0x0AB is unnamed, so the conversion drops it with no issue "
     "behind it), so a source that supplies one -- `write` checks "
     "`char.port == 'C64'` before taking it -- writes that byte back "
     "instead of a digest of a record it never held. A DOS source's own "
     "copy of this field is not eligible: `to_neutral` carries it only so "
     "`goldbox.c64_codec.write` has something to give the C64, and a pure "
     "DOS-to-DOS conversion keeps deriving the digest exactly as before"),
)


def identity_byte(record: bytes | bytearray,
                  shape: "int | str | DosShape | None" = None) -> int:
    """The `unnamed_0ab` byte for a record, derived from the rest of it.

    The engine draws this at random when it creates a character, and uses it
    for one thing: telling two characters of the same name apart when one is
    being added to the party.  What it needs is therefore only that two
    *different* characters rarely agree, which a digest gives -- and unlike a
    random draw a digest gives it without making the same save convert to
    different bytes twice running.

    The byte's own position is excluded, so the answer does not depend on
    what was there before.  Two characters identical in all 284 other bytes
    do collide, and are the same character by every field the game has.

    `shape` names the title; with none it is taken from the record's length,
    which identifies it on its own among the four (`shape_for`).  The field
    is at a different offset in every title, so a Pool of Radiance offset
    used on a Curse record would digest the wrong 421 bytes and blank a byte
    of the money block.
    """
    shape = shape_for(len(record) if shape is None else shape)
    f = FIELDS_BY_NAME_FOR[shape.key]["unnamed_0ab"]
    body = bytearray(record)
    body[f.offset:f.end] = bytes(f.size)
    return hashlib.blake2b(bytes(body), digest_size=1).digest()[0]


#: The DOS shapes :func:`write` will build a record for -- the same three
#: :data:`CONVERTS` reads, because a conversion is between two ports of the
#: same title and both directions have to exist for a title to be offered.
#:
#: **Pools of Darkness is not here and is not an oversight**: there is no C64
#: port to convert from, `#194 (Import and export a Pools of Darkness save
#: between DOS and the Amiga)` owns its Amiga pairing, and nothing has ever
#: written one of its 510-byte records.  Its shape reads.
WRITES: tuple[DosShape, ...] = CONVERTS

#: Neutral fields the writer takes by a rule in the **later titles only**.
#: Pool of Radiance declares neither field, so it drops both and keeps its
#: entries in :data:`WRITE_DROPPED`; `write_field_disposition` swaps them per
#: title, exactly as the reader's `field_disposition` does.
WRITE_TRANSFORMED_LATER: tuple[tuple[str, str], ...] = (
    ("abilities_second", "written into the second byte of the title's own "
                         "(current, base) pair; a source with no second copy "
                         "gets the first written into both, which is what "
                         "every record measured holds -- 0 of 406 DOS pairs "
                         "and 0 of 6 C64 Curse records differ"),
    ("former_levels", "permuted onto the title's former-class level array "
                      "the same way the current levels are, and the level "
                      "itself written again into the single byte after "
                      "`level` that the engine keeps it in (#234)"),
)

#: `field_83_87` is five bytes in Pool of Radiance and Curse of the Azure
#: Bonds and **four** in Secret of the Silver Blades, which is the same run
#: with the first byte gone: 17 of the 20 engine-written Silver Blades
#: records here and 22 of the 24 shipped ones read `00 01 00 00`, which is
#: Pool of Radiance's `00 00 01 00 00` from its second byte on.
#:
#: **What those bytes are, out of the shipped overlays** (#303, #305).  The
#: second byte is the **control byte**, whose bit 7 the engine tests to decide
#: whether it drives the character itself: every title's own `GAME.OVR`
#: compares it against `0x7F` and `0x80` and stores `0x00`, `0xB2` and `0xB3`
#: into it, which is `coab`'s `PC_Base` / `PC_Mask` / `NPC_Base` /
#: `NPC_Berzerk` / `PC_Berzerk` in Pool of Radiance's binary, which nobody
#: decompiled.  The third is the **treasure share**: Pool of Radiance reads it
#: `& 7` at `0x006885`, behind that same control test and a status test, and
#: adds it to the split -- a player character takes one part and is never read
#: here at all.  The first, fourth and fifth bytes have **no site** in any of
#: the four overlays.  Curse's own Pool of Radiance importer copies
#: `0x083`-`0x087` into `0x0F6`-`0x0FA` one for one, so the run aligns.
#:
#: **The third byte is not a constant, and this is the value we choose rather
#: than the value every record holds** (#304).  The only instruction in Pool
#: of Radiance, Curse or Silver Blades that stores an immediate into it stores
#: **1**, and it is the last statement of MODIFY CHARACTER, reached when the
#: player presses `K` for KEEP -- a command the engine refuses on any
#: character whose experience is not 0, 8333, 12500 or 25000, so it is
#: reachable only just after creation.
#:
#: **CONFIRMED in the running game, one action apart, with a control**
#: (`tools/dosmodifyprobe.py`, 2026-09-05).  Two human fighters rolled from
#: CREATE NEW CHARACTER and added to the party both read 0.  MODIFY CHARACTER
#: opened on one and left by EXIT, saved again: both records byte for byte
#: unchanged.  MODIFY CHARACTER opened on the same one and left by KEEP, saved
#: again: **exactly one byte of the 285 moved**, `0x085`, 0 to 1, and the
#: other character's record is identical across all three saves.
#: `WISH-SPEC-por-304-modify-exited` and `WISH-SPEC-por-304-modify-kept` are
#: the pair.
#:
#: So the byte records "somebody kept this character out of the modify
#: screen", and the corpus splits on exactly that:
#:
#:   * 1 in 66 of 66 Pool of Radiance archive records, 44 of 48 Curse ones
#:     (the four are Gateway's ERSWELL and GULAIL, twice each) and 22 of 24
#:     Silver Blades ones;
#:   * **0 in 45 of the 54 Pool of Radiance specimen records**, which are the
#:     parties this project rolled from character creation and never modified;
#:   * 0 in Silver Blades' MALACHITE, in the shipped party and in three saves
#:     this project drove -- which is the five exceptions in 76 that
#:     `docs/180-writing-a-later-dos-record.md` counts, and nothing to do with
#:     his being an NPC: his control byte is 0;
#:   * meaningless in Pools of Darkness, whose overlay has no site for the
#:     byte at all.
#:
#: **1 is kept**, because it is the only value any engine writes as an
#: immediate, because it is what 132 of 138 records the engines have lived
#: with hold, and because a share of 0 is the one value the engine treats
#: specially -- `cmp byte ptr es:[di+85h], 0` at `0x006998` skips a character
#: with no share out of the split entirely, so a converted companion would
#: silently get nothing once `npc` reaches bit 7 of the byte before it (#303).
#: For a player character it is inert either way, so no choice here is
#: something a player can see.
#:
#: **It stays in `WRITE_CONSTANTS` rather than moving to `WRITE_DEFAULTS`,
#: deliberately.**  A default is masked out of the round trip, and masking
#: this one would hide MALACHITE's real difference rather than convert it.
#: The fix that removes the choice is to convert the two meaningful bytes --
#: the control byte into the neutral `npc`, the share into a neutral field
#: that does not exist yet -- which needs `goldbox/neutral.py` and
#: `goldbox/amiga.py`.
FIELD_83_87: dict[int, bytes] = {5: b"\x00\x00\x01\x00\x00",
                                 4: b"\x00\x01\x00\x00"}

#: DOS bytes with no source that only the **later titles** declare.  Zeroed
#: and reported, exactly as :data:`WRITE_UNSOURCED` is, and the round trip
#: masks this list beside that one.
WRITE_UNSOURCED_LATER: tuple[tuple[str, str], ...] = (
    ("spells_castable_unattributed",
     "Secret of the Silver Blades' fourth spell-slot array, 28 bytes where "
     "Curse has 15. **Zero in 44 of 44 Silver Blades records** -- 20 this "
     "project drove the game into writing and 24 shipped -- and nobody has "
     "attributed it to a class: cleric, druid and magic-user account for the "
     "other three arrays and a paladin's spells go in the cleric's "
     "(#222). So zero is the measured value and not a shrug"),
)

#: Fields the later titles derive from the record rather than from a neutral
#: value.  Separate from :data:`WRITE_DERIVED`, which Pool of Radiance shares
#: and which `write` unpacks as a single row.
WRITE_DERIVED_LATER: tuple[tuple[str, str], ...] = (
    ("paladin_cures",
     "1 for a character who is or was a paladin and 0 for everybody else, "
     "which is what every engine-written record holds: 8 paladins across "
     "four record shapes and six titles read 1 and 71 other characters read "
     "0. The C64 has no counterpart to convert from -- no byte of "
     "`goldbox/layout.py` separates a paladin that way in 78 C64 records -- "
     "and 1 is the value the DOS engine's own character creation writes "
     "(`coab`'s `ovr018`). It is written from the *former* class too, "
     "because the engine leaves it at 1 for a paladin who has been through "
     "HUMAN CHANGE CLASSES: DEMELTINA is a cleric 1 with former paladin 5 "
     "and still reads 1.\n"
     "**The rule is 'write what the engine writes', not 'give the paladin "
     "his cure back'** -- staged 0 and staged 2 on a paladin in the running "
     "Silver Blades game, the sheet offers CURE either way and one use ends "
     "the offer, so the byte does not gate the command in that title. It "
     "*is* cure-disease bookkeeping: one use took a staged 2 to 0 in the "
     "engine's own resave (#299)"),
)


#: What :func:`write` does with every field `goldbox/dos_layout.py` declares --
#: the *output-side* account, over DOS field names, where
#: :func:`write_field_disposition` accounts over the neutral vocabulary.
#: `tests/test_doswriter.py` fails if a field is declared in the layout and
#: named nowhere here, so a new field cannot be skipped in silence.
#:
#: **Pool of Radiance's**, which is what it has always been; ask
#: :func:`write_targets` for another title's.
WRITE_TARGETS: dict[str, str] = (
    {dos_name: f"from neutral {n}" for n, dos_name in WRITE_DIRECT}
    | {"name_length": "from neutral name, the count byte",
       "name_text": "from neutral name, fifteen ASCII",
       "class_bits": "from neutral class_bits, with the ranger's bit 7 "
                     "folded onto DOS's bit 6",
       "char_class": "from neutral char_class, recomputed from the class "
                     "mask when the source record contradicts itself (#310)",
       "spells_memorised": "from neutral spells_memorised, reversed",
       "spellbook": "from neutral spells_known, one byte per id",
       "class_levels": "from neutral levels, permuted to class numbers",
       "spells_castable_cleric": "from neutral spells_castable['cleric']",
       "spells_castable_magic_user":
           "from neutral spells_castable['magic-user']",
       "size": "from neutral size_small, plus one",
       "attack_forms": "from neutral attack_forms, as a block",
       "roster_tail": "from neutral roster_tail, as a block",
       "item_count": "computed: the number of .ITM records written",
       "encumbrance": "computed: money plus item weight x quantity"}
    | {name: f"constant: {why}" for name, _, why in WRITE_CONSTANTS}
    | {name: f"default: {why}" for name, _, why, _ in WRITE_DEFAULTS}
    | {name: f"zero: {why}" for name, why in WRITE_UNSOURCED}
    | {name: f"derived: {why}" for name, why in WRITE_DERIVED}
)


def write_constants(shape: "int | str | DosShape" = POOL_OF_RADIANCE
                    ) -> tuple[tuple[str, bytes, str], ...]:
    """:data:`WRITE_CONSTANTS`, cut to the title's own field widths.

    One field changes width between the three titles this writes --
    `field_83_87`, five bytes in Pool of Radiance and Curse and four in
    Silver Blades -- and :data:`FIELD_83_87` has the value for each and what
    the bytes are.  A constant whose length does not match the field it goes
    into is a `DosRecordError` from `_encode` rather than a silent misfit.
    """
    table = FIELDS_BY_NAME_FOR[shape_for(shape).key]
    out = []
    for name, data, why in WRITE_CONSTANTS:
        size = table[name].size
        if size != len(data):
            data = FIELD_83_87[size] if name == "field_83_87" else data
        out.append((name, data, why))
    return tuple(out)


def write_targets(shape: "int | str | DosShape" = POOL_OF_RADIANCE
                  ) -> dict[str, str]:
    """:data:`WRITE_TARGETS` for one title.

    **Asked per title for the same reason the reader's `field_disposition`
    is**: Curse of the Azure Bonds and Secret of the Silver Blades declare
    four fields Pool of Radiance has never heard of, and a Pool of Radiance
    account of a Curse record would leave every one of them unnamed -- which
    is a field written or zeroed in silence, the thing this table exists to
    make impossible.
    """
    shape = shape_for(shape)
    declared = set(FIELDS_BY_NAME_FOR[shape.key])
    out = dict(WRITE_TARGETS)
    out |= {name: f"constant: {why}"
            for name, _, why in write_constants(shape)}
    out |= {
        "former_level": "from neutral former_levels, the one level again in "
                        "the byte the engine keeps it in",
        "former_class_levels": "from neutral former_levels, permuted to "
                               "class numbers",
        "spells_castable_druid": "from neutral spells_castable['druid']",
    }
    out |= {name: f"zero: {why}" for name, why in WRITE_UNSOURCED_LATER}
    out |= {name: f"derived: {why}" for name, why in WRITE_DERIVED_LATER}
    return {n: w for n, w in out.items() if n in declared}


#: Class name -> the DOS level slot with that number.  All eight have one --
#: DOS can hold the druid and monk levels the C64 cannot -- and only the
#: C64-only knight is left with nowhere to go.
_DOS_CLASS_SLOT: dict[str, int] = {name: n for n, name, _ in CLASS_LEVEL_SLOTS}

_COINS = ("copper", "silver", "electrum", "gold", "platinum", "gems",
          "jewelry")


def _encode(f: Field, rec: bytearray, value: Any) -> None:
    """The inverse of `_decode`, onto a mutable record."""
    if f.kind in (Kind.U8, Kind.I8):
        rec[f.offset] = int(value) & 0xFF
    elif f.kind in (Kind.U16LE, Kind.UINT_LE):
        val = int(value)
        limit = (1 << (8 * f.size)) - 1
        if not 0 <= val <= limit:
            raise ValueError(f"{f.name}: {val} does not fit in {f.size} bytes")
        rec[f.offset:f.end] = val.to_bytes(f.size, "little")
    else:
        data = bytes(value)
        if len(data) != f.size:
            raise DosRecordError(
                f"DOS field {f.name!r} is {f.size} bytes; got {len(data)}")
        rec[f.offset:f.end] = data


def write_shape(char: NeutralCharacter,
                shape: "int | str | DosShape | None" = None) -> DosShape:
    """Which DOS record :func:`write` will build for this character.

    **The title is the character's, not the caller's**, because a conversion
    is between two ports of the same title and never between titles
    (`.claude/rules/conversions.md`).  A neutral character carries the title
    its reader read it in -- `NeutralCharacter.game`, which is a
    `goldbox.games.Game`, its key, or `None` for Pool of Radiance -- and that
    is what decides the shape.  `shape` overrides it, for a caller that has
    already resolved the title.

    A title with no DOS record raises `DosShapeError`; a DOS record nobody
    has written raises `WrongTitleError`, which is the same refusal
    :func:`to_neutral` makes in the other direction.
    """
    if shape is None:
        game = char.game
        shape = shape_for(getattr(game, "key", game) or POOL_OF_RADIANCE)
    else:
        shape = shape_for(shape)
    if shape not in WRITES:
        raise WrongTitleError(
            f"{shape.title} records read, but only "
            f"{', '.join(s.title for s in WRITES)} can be written: no other "
            f"pair of ports has been measured against each other (#53)",
            title=shape.title)
    return shape


def write(char: NeutralCharacter,
          portraits: PortraitTables | None = None,
          shape: "int | str | DosShape | None" = None
          ) -> tuple[bytes, bytes, bytes, WriteReport]:
    """Build a DOS record and its item and effect payloads from a neutral
    character.

    The reverse of :func:`to_neutral`, and the writer #26 asked for: with it,
    C64 to DOS is `c64_codec.read` plus this, and nothing else.  Returns
    `(record, itm, spc, report)`.

    **Which record is the character's own title's**, not this function's
    (#299).  Pool of Radiance is 285 bytes with one copy of each ability,
    Curse of the Azure Bonds 422 with a (current, base) pair per ability, a
    100-spell book and a former-class array, and Secret of the Silver Blades
    439 with a 117-spell book, seven spell-slot levels and **67-byte items**.
    Every width comes off `goldbox/dos_layout.py`'s table for the title and
    none of them is a constant here: that is what `#113 (Play DOS Curse far
    enough to save a party with items)` closed and what a second writer would
    have reopened.  :func:`write_shape` says how the title is chosen.

    `portraits` is the creation menu's two tables, from
    :func:`portrait_tables`.  With them the sheet portrait crosses -- the C64
    art id the neutral record carries becomes the menu position DOS stores --
    and without them the pair is left zero and reported, which is what a
    converted party looked like before #57: no face on the sheet.  **Only
    Pool of Radiance draws one**: `portrait_head` and `portrait_body` are 0 in
    all 32 Curse records and all 44 Silver Blades records this project can
    reach, so those two titles report the portrait rather than writing a
    position into a byte their sheet never reads.

    Every byte of both outputs is justified in the report: it came from a
    neutral value, it was computed by a named rule, it is a documented
    constant, or it is a zero the report names as having no source --
    the live heap and the three unattributed runs, which the round-trip test
    masks *by this same list* rather than by whatever happened to differ.
    """
    shape = write_shape(char, shape)
    table = FIELDS_BY_NAME_FOR[shape.key]
    size = shape.record_size
    item_size = shape.item_size
    rec = bytearray(size)
    rep = WriteReport()
    port = char.port
    # The later titles turn two of Pool of Radiance's drops into conversions,
    # so the sweep's reasons are the title's rather than the module's.
    later = {n for n, _ in WRITE_TRANSFORMED_LATER}
    dropped = (WRITE_DROPPED if shape is POOL_OF_RADIANCE else
               tuple((n, w) for n, w in WRITE_DROPPED if n not in later))
    w = SilencingWriter(char, rep, into="DOS", dropped=dropped,
                        silent=WRITE_UNREPORTED_DROPS)
    use, emit = w.use, w.emit

    def put(v: neutral.Value, dos_name: str, extra: str = "",
            value: Any = None) -> None:
        f = table[dos_name]
        val = v.value if value is None else value
        if f.kind is Kind.U8 and not 0 <= int(val) <= 0xFF:
            rep.warnings.append(
                f"{dos_name}: {val} does not fit the DOS one-byte field; "
                f"clamped")
            val = max(0, min(int(val), 0xFF))
        _encode(f, rec, val)
        emit(v, dos_name, f.offset, f.size, extra)

    # -- the name: one count byte, fifteen of ASCII --------------------------
    name = use("name")
    if name is not None:
        width = table["name_text"].size
        text = str(name.value)[:width].encode("ascii", "replace")
        if len(str(name.value)) > width:
            rep.warnings.append(
                f"Name {str(name.value)!r} is longer than the DOS {width} "
                f"characters; truncated")
        at = table["name_length"].offset
        rec[at] = len(text)
        rec[at + 1:at + 1 + len(text)] = text
        emit(name, "name_length/name_text", at, 1 + width,
             ", length-prefixed into one count byte and fifteen ASCII")

    # -- everything the two ports encode the same way ------------------------
    # The abilities are a **(current, base) pair** from Curse of the Azure
    # Bonds on, and one byte in Pool of Radiance, so the width decides the
    # shape of the write rather than the title doing so.  `abilities_second`
    # is the neutral record's second copy; a source that has none writes the
    # one value into both halves, which is what every record measured holds
    # -- 0 of 406 DOS pairs differ, and 0 of the 6 C64 Curse records.
    #
    # **coab, the decompilation of the DOS Curse overlays, says which half is
    # which**: `StatValue.Write` puts `cur` at +0 and `full` at +1, so the
    # first byte is the score as play has left it and the second the score
    # the character rolled.  That is the pairing `_ability_pair` and this
    # both use, and no specimen could have told them apart.
    second = use("abilities_second")
    seconds = dict(second.value) if second is not None else {}
    for neutral_name, dos_name in WRITE_DIRECT:
        # Written below, from the class mask when the source contradicts
        # itself, and copied otherwise (#310).  It stays in `WRITE_DIRECT`
        # because that is what it is in every record whose source kept it up
        # to date, and because the reader's `DIRECT` and this table are
        # mirrors.
        if neutral_name == "char_class":
            continue
        v = use(neutral_name)
        if v is None:
            continue
        f = table[dos_name]
        if dos_name in ABILITY_ORDER and f.size == 2:
            base = int(seconds.get(dos_name, v.value))
            put(v, dos_name,
                f", the first of the title's (current, base) pair; the "
                f"second is {base}",
                value=bytes((int(v.value) & 0xFF, base & 0xFF)))
        else:
            put(v, dos_name)
    if second is not None and not any(table[n].size == 2
                                      for n in ABILITY_ORDER):
        rep.dropped.append(
            f"abilities_second: {shape.title} keeps one copy of each ability "
            f"score, so the source's second copy has nowhere to go")

    # -- the class mask, folded back into DOS's own order --------------------
    bits = use("class_bits")
    if bits is not None:
        put(bits, "class_bits",
            ", with the ranger's bit 7 folded onto DOS's bit 6, which it "
            "shares with the paladin",
            value=dos_class_bits(int(bits.value)))

    # -- the class code, repaired when the source contradicts itself (#310) --
    # The DOS sheet prints the class from `char_class`, and Curse of the Azure
    # Bonds' own C64 engine stops maintaining it: `GEN $1939` computes the
    # code by walking `CLASS_CODE_TABLE`, holds the answer in X and stores A,
    # so every character its trainer touches comes away reading 0 and a
    # dual-classed one reads the level he left his old class at.  Copied
    # straight across, that drew CLERIC on a dwarf thief 6 / fighter 5 in the
    # running game.
    #
    # So the code is checked against the **class mask** and rewritten when the
    # two contradict each other.  The mask is the right source and the level
    # array is not: SILAS, the shipped Pool of Radiance fighter, holds a
    # thief 1 in his level array that neither his mask nor his code knows
    # about, and rewriting his code to fighter/thief would be this conversion
    # inventing a class for him.
    #
    # **A dual-classed character is the one exception, and it takes the level
    # array after all.**  His mask carries the old class's bit back once his
    # new class passes the level he left the old one at, so it names two
    # classes where the code names the one he *is* -- and the engine agrees:
    # `GEN $1939` branches away from the table walk entirely when
    # `dual_class_level` is set.  The current level array holds exactly the
    # class he is now, because the old class's slot is zeroed at the change.
    code = use("char_class")
    if code is not None:
        former = w.get("former_levels") or {}
        source = "levels" if any(former.values()) else "class_bits"
        want = (_class_code(w.get("levels")) if source == "levels"
                else CLASS_CODE_FOR_BITS.get(int(w.get("class_bits") or 0)))
        if want is None or want == int(code.value):
            put(code, "char_class")
        else:
            # **Not a warning**, and deliberately: `editor/exports.py`'s
            # `losses` puts every warning in front of the player under a
            # heading that says the conversion could not do something
            # faithfully, and this is the opposite -- the record contradicted
            # itself and the conversion repaired it.  The provenance line
            # `put` writes is our own accounting, which is where it belongs.
            put(code, "char_class",
                f", recomputed from {source}: the source record says "
                f"{int(code.value)} and its own classes say {want} (#310)",
                value=want)

    # -- the spellbook: one byte per spell, ids 1..n -------------------------
    # 56 ids in Pool of Radiance, 100 in Curse and 117 in Silver Blades,
    # which are `goldbox/spells.py`'s three id spaces exactly.  The width is
    # the title's own `spellbook` field, so an id the destination title has
    # no byte for is reported rather than written past the end.
    known = use("spells_known")
    if known is not None:
        spells_in_book = table["spellbook"].size
        book = bytearray(spells_in_book)
        for sid in known.value:
            if 1 <= int(sid) <= spells_in_book:
                book[int(sid) - 1] = 1
            else:
                rep.warnings.append(
                    f"Spell id {sid} is outside the {shape.title} book's "
                    f"ids 1-{spells_in_book}")
        put(known, "spellbook", ", unpacked to one byte per spell",
            value=bytes(book))

    # -- memorised spells: the title's slots, filled from the end ------------
    memorised = use("spells_memorised")
    if memorised is not None:
        slots = table["spells_memorised"].size
        ids = [int(i) for i in memorised.value][:slots]
        if len(memorised.value) > slots:
            rep.warnings.append(
                f"{len(memorised.value)} spells memorised and "
                f"{shape.title} has {slots} slots; the rest dropped")
        put(memorised, "spells_memorised",
            f" reversed -- DOS fills its {slots} slots from the end",
            value=bytes(slots - len(ids)) + bytes(reversed(ids)))

    # -- the per-class level array: indexed by the class number --------------
    # Eight slots in Pool of Radiance and Curse, **seven** in Silver Blades,
    # which drops the monk's.  A class whose number is past the end of this
    # title's array is reported by name rather than written over the field
    # that follows it.
    def _levels_into(v: neutral.Value, dos_name: str, extra: str) -> None:
        slots = table[dos_name].size
        raw = bytearray(slots)
        for cname, lv in v.value.items():
            n = _DOS_CLASS_SLOT.get(cname)
            if n is None or n >= slots:
                if lv:
                    rep.warnings.append(
                        f"{port} carries {cname} level {lv}, and "
                        f"{shape.title}'s {slots}-slot array has no {cname} "
                        f"slot")
                continue
            raw[n] = min(int(lv), 0xFF)
        put(v, dos_name, extra, value=bytes(raw))

    levels = use("levels")
    if levels is not None:
        _levels_into(levels, "class_levels",
                     ", permuted from class name to class number")

    # -- the class a dual-classed human left ---------------------------------
    # Curse of the Azure Bonds and Secret of the Silver Blades keep it twice:
    # a second copy of the level array holding what the character *was*, and
    # the same level again in the single byte after `level` (#234).  Both are
    # written from the one neutral value, which is what that issue said the
    # writer this project did not have would do.  Pool of Radiance declares
    # neither and reports the loss instead -- it has no way for a character
    # to change class at all.
    former = use("former_levels")
    if former is not None and "former_class_levels" in table:
        _levels_into(former, "former_class_levels",
                     ", permuted from class name to class number")
        held = [lv for lv in former.value.values() if lv]
        if len(held) > 1:
            rep.warnings.append(
                f"{port} carries former levels in {len(held)} classes and "
                f"the DOS byte after level holds one; the highest is written "
                f"there and the array keeps them all")
        put(former, "former_level",
            ", the level again in the byte the engine keeps it in",
            value=max(held) if held else 0)
    elif former is not None and any(former.value.values()):
        rep.dropped.append(
            f"former_levels: a DOS {shape.title} record has no former-class "
            f"level array; that title does not let a character change class")

    # -- spell slots, by class: two arrays on Pool of Radiance, three after --
    # Three levels of slots in Pool of Radiance, five in Curse and seven in
    # Silver Blades, and the druid's array only from Curse on.  A neutral
    # record that carries more levels than the destination keeps says so.
    castable = use("spells_castable")
    if castable is not None:
        for school, dos_name in (("cleric", "spells_castable_cleric"),
                                 ("druid", "spells_castable_druid"),
                                 ("magic-user", "spells_castable_magic_user")):
            if dos_name not in table:
                if any(castable.value.get(school, ())):
                    rep.dropped.append(
                        f"spells_castable[{school!r}]: a DOS {shape.title} "
                        f"record has no {school} spell-slot array")
                continue
            depth = table[dos_name].size
            run = tuple(castable.value.get(school, ()))
            if len(run) > depth and any(run[depth:]):
                rep.warnings.append(
                    f"{port} carries {school} spell slots {len(run)} levels "
                    f"deep and {shape.title} keeps {depth}; the rest dropped")
            run = (run + (0,) * depth)[:depth]
            put(castable, dos_name, f", the {school} run",
                value=bytes(min(int(n), 0xFF) for n in run))

    # -- size: neutral 0 small / 1 large, DOS 1 small / 2 medium -------------
    size_small = use("size_small")
    if size_small is not None:
        put(size_small, "size", " plus one -- DOS stores 1 small / 2 medium",
            value=int(size_small.value) + 1)

    # -- two blocks the ports share byte for byte ----------------------------
    forms = use("attack_forms")
    if forms is not None:
        put(forms, "attack_forms", " copied as a block")
    tail = use("roster_tail")
    if tail is not None:
        put(tail, "roster_tail", " copied as a block")

    # -- the sheet portrait: the art's own id becomes a menu position --------
    # Both ports offer one menu of fourteen heads and twelve bodies and both
    # binaries carry the same table of art ids in the same order (#57), so
    # this is a lookup rather than a judgement.  What the C64 keeps is the id
    # -- `$2D` is the file `HEAD2D` -- and what DOS keeps is where that id
    # sits in the menu, counting from one.
    #
    # Nothing is substituted when the lookup cannot be made.  A portrait the
    # menu does not offer has no DOS position to be written as, so the byte
    # is left zero and the loss is reported: the alternative is a face that
    # belongs to somebody else.
    #
    # **Only Pool of Radiance has a sheet portrait**, on either port.  The
    # DOS pair is zero in all 32 Curse and all 44 Silver Blades records this
    # project holds, so writing a menu position there would put a number
    # where the engine writes none -- and #300 (A Curse or Silver Blades
    # party imported to the C64 arrives with no sheet portrait, because the
    # creation menu is read only off a POOL<n>.D64) established the same
    # thing on the C64 side: `LIBRARY $48A4` draws the face and neither later
    # title's `LIBRARY` calls it, over 558 and 571 files
    # (`docs/188-the-sheet-portrait-per-title.md`).  So a Curse or Silver
    # Blades character has no face at either end and there is no loss to
    # report; the line below is for the two cases that are one, where Pool of
    # Radiance's own sheet draws a portrait the DOS record cannot name.
    draws_portrait = draws_sheet_portrait(shape.key)
    portraits_written: set[str] = set()
    for pname, lookup, stem in (("portrait_head", "head_position", "HEAD"),
                                ("portrait_body", "body_position", "BODY")):
        v = use(pname)
        position = None
        if v is not None and portraits is not None and draws_portrait:
            position = getattr(portraits, lookup)(int(v.value))
        if position is not None:
            put(v, pname,
                f", the position of {stem}{int(v.value):02X} in the creation "
                f"menu ({portraits.source})", value=position)
            portraits_written.add(pname)
        elif v is not None and draws_portrait:
            rep.dropped.append(
                f"{pname}: {port} carries {stem}{int(v.value):02X} and " +
                ("the creation menu does not offer it, so the DOS record "
                 "has no position for it"
                 if portraits is not None else
                 "the creation menu's own tables were not available to turn "
                 "it into the position the DOS record stores"))

    # -- the inventory becomes the item file ---------------------------------
    # `.ITM` in Pool of Radiance, **`.SWG`** in Curse and **`.STF`** in
    # Silver Blades, whose records are 67 bytes rather than 63 (#113).  The
    # stride is the shape's and the caller writes the file under
    # `DosShape.item_suffix`; nothing here assumes either.
    itm = b""
    projected: list[bytes] = []
    inventory = use("inventory")
    if inventory is not None:
        projected = [bytes(i) for i in inventory.value]
        itm = b"".join(item_from_c64(i, item_size) for i in projected)
        if projected:
            emit(inventory, f"the {shape.item_suffix} file", size, len(itm),
                 f", each sixteen-byte record unpacked onto the DOS "
                 f"{item_size}")
            for n in range(len(projected)):
                base = size + n * item_size
                rep.note(base, 0x02A,
                         f"item {n}: the rendered-line cache, left empty -- "
                         f"the game rewrites it whenever it draws the list")
                rep.note(base + 0x02A, 4,
                         f"item {n}: next pointer left NULL -- the loader "
                         f"rebuilds the chain, measured by its own resave")
                if item_size > ITEM_SIZE:
                    rep.note(base + ITEM_TAIL[0], ITEM_TAIL[1],
                             f"item {n}: the four bytes Silver Blades' item "
                             f"record has and the others do not, zero in 48 "
                             f"of 48 records driven out of the game (#113)")

    # -- the innate effects become the effect file ---------------------------
    # Running spells are not written, which is what the game's own C64
    # importer does: it reads a `.spc` and keeps only the racial and
    # constitutional ids.  A character with none gets no file, the state the
    # engine itself writes for a party member with nothing running.
    innate = use("innate_effects")
    converted = [int(e) for e in innate.value] if innate is not None else []
    race = int(w.get("race", 0) or 0)
    derived = [e for e in _race_combat_effects(char.game, race)
               if e not in converted]
    keep = derived + [e for e in converted if e in INNATE_EFFECTS]

    # An item's grant follows the innate records in the same file, each one
    # its own five bytes rather than `INNATE_PAYLOAD`: a girdle's record
    # carries the strength it replaced and a flag the engine reads when the
    # girdle comes off, and writing `INNATE_PAYLOAD` over those would leave
    # the character with the girdle's strength for ever (#232, An
    # item-granted effect is dropped on the way through the neutral record,
    # with no report).  The order is innate then granted; the engine walks
    # the chain looking for an id and rebuilds it from the file's length, so
    # the order in the file is not something it reads meaning from.
    given = use("granted_effects")
    grants = [bytes(g)[:5] + EFFECT_NEXT_NULL
              for g in (given.value if given is not None else ())]

    spc = b"".join([bytes((e,)) + INNATE_PAYLOAD + EFFECT_NEXT_NULL
                    for e in keep] + grants)
    base = size + len(itm)
    for n, e in enumerate(keep):
        at = base + n * EFFECT_SIZE
        whence = (f"derived from race {race} -- the C64 works this one out "
                  f"at combat time and stores it nowhere"
                  if e in derived else f"{port} innate_effects")
        rep.note(at, 1, f"{shape.effect_suffix} record {n}: effect {e} "
                        f"({traits.describe(e)}), {whence}")
        rep.note(at + 1, 4,
                 f"{shape.effect_suffix} record {n}: INNATE_PAYLOAD, the four "
                 f"bytes every innate specimen in the archives holds")
        rep.note(at + 5, 4,
                 f"{shape.effect_suffix} record {n}: next pointer NULL -- the "
                 f"loader allocates a node per record and relinks them, and "
                 f"the count comes from the file's length")
    for i, g in enumerate(grants):
        n = len(keep) + i
        at = base + n * EFFECT_SIZE
        rep.note(at, 1, f"{shape.effect_suffix} record {n}: effect {g[0]} "
                        f"({traits.describe(g[0])}), {port} granted_effects")
        rep.note(at + 1, 2,
                 f"{shape.effect_suffix} record {n}: duration zero -- the "
                 f"engine's expiry pass skips a node at zero and never "
                 f"removes it")
        rep.note(at + 3, 2,
                 f"{shape.effect_suffix} record {n}: the value the effect "
                 f"carries and the flag the engine reads when the item comes "
                 f"off, the source record's own two bytes")
        rep.note(at + 5, 4,
                 f"{shape.effect_suffix} record {n}: next pointer NULL -- the "
                 f"loader allocates a node per record and relinks them, and "
                 f"the count comes from the file's length")
    for e in converted:
        if e not in INNATE_EFFECTS:
            rep.dropped.append(
                f"innate_effects {e} ({traits.describe(e)}): not one of the "
                f"ids the game's own importer keeps, so it is an item power "
                f"or a running effect rather than an innate one and no "
                f"{shape.effect_suffix} record is written for it")

    # -- computed, not copied ------------------------------------------------
    count = min(len(projected), 0xFF)
    rec[table["item_count"].offset] = count
    rep.note(table["item_count"].offset, 1,
             f"item_count: computed -- the {count} records of the "
             f"{shape.item_suffix} file")
    money = sum(int(w.get(k, 0)) for k in _COINS if k in table)
    weight = sum(int.from_bytes(i[8:10], "little") * (i[10] or 1)
                 for i in projected)
    _encode(table["encumbrance"], rec, min(money + weight, 0xFFFF))
    rep.note(table["encumbrance"].offset, 2,
             "encumbrance: computed -- money plus item weight x quantity, "
             "the identity the DOS engine itself uses")

    # -- documented constants ------------------------------------------------
    for cname, data, why in write_constants(shape):
        f = table[cname]
        rec[f.offset:f.end] = data
        rep.note(f.offset, f.size, f"{cname}: {why}")

    # -- measured defaults, where the source holds no matching value --------
    # The provenance note carries both halves: why this value, and what the
    # source held that is not being converted.  It does **not** go in
    # `rep.dropped`, which is read by a person in the conversion pane -- that
    # is a sentence for Donald to approve rather than one to model on the
    # sibling lines already there (`.claude/rules/gui-text.md`).
    for dname, data, why, lost in WRITE_DEFAULTS:
        f = table[dname]
        rec[f.offset:f.end] = data
        rep.note(f.offset, f.size,
                 f"{dname}: {data.hex()} -- {why}. Not converted: {lost}")

    # -- the combat tail, over the default just written -----------------------
    # `field_10c_10f` is four bytes and all four are the character's own
    # state (#235, docs/169-dos-combat-side.md): 0x10C is the status,
    # 0-based over the engine's own nine words -- which is the order
    # `neutral.STATUS_NAMES` is in, so the index *is* the DOS number; 0x10D
    # is the flag that draws a name red in the party panel when it is 0;
    # 0x10E is the combat side, 1 for the enemy's; and 0x10F is the
    # quickfight flag.
    #
    # A source that carries none of the four leaves all four at the
    # default just written, which is the state a freshly made DOS character
    # is in.
    f = table["field_10c_10f"]
    status, active = w.use("status"), w.use("active")
    hostile, quickfight = w.use("hostile"), w.use("quickfight")
    said = []
    if status is not None:
        if status.value in neutral.STATUS_NAMES:
            rec[f.offset] = neutral.STATUS_NAMES.index(status.value)
            said.append(f"the status byte is {rec[f.offset]} "
                        f"({status.value}) <- {status.origin}")
        else:
            rep.dropped.append(
                f"{status.value.capitalize()}: the character "
                f"arrives well -- the DOS game has no such state")
    if active is not None:
        rec[f.offset + 1] = 1 if active.value else 0
        said.append(f"the active flag is {rec[f.offset + 1]} "
                    f"<- {active.origin}")
    if hostile is not None:
        rec[f.offset + 2] = 1 if hostile.value else 0
        said.append(f"the combat side is {rec[f.offset + 2]} "
                    f"<- {hostile.origin}")
    if quickfight is not None:
        rec[f.offset + 3] = 1 if quickfight.value else 0
        said.append(f"quickfight is {rec[f.offset + 3]} "
                    f"<- {quickfight.origin}")
    if said:
        rep.note(f.offset, f.size,
                 f"field_10c_10f @{f.offset:#05x}: "
                 f"{bytes(rec[f.offset:f.end]).hex()} -- " + "; ".join(said))

    # -- bytes with no source: live heap and the unattributed ----------------
    # The portrait pair is in that list because it is what a conversion with
    # no game directory still writes, and a note here would overwrite the
    # provenance of a portrait that *was* converted.
    for uname, why in WRITE_UNSOURCED + WRITE_UNSOURCED_LATER:
        if uname in portraits_written or uname not in table:
            continue
        f = table[uname]
        rep.note(f.offset, f.size, f"{uname}: zero -- {why}")

    # -- derived from the record ---------------------------------------------
    # The paladin's cure-disease allowance, which the C64 has no byte for and
    # the DOS engine's own character creation writes as 1.  Taken from the
    # class the character holds *or* the class a dual-classed one left, the
    # way the engine leaves it set for both.
    if "paladin_cures" in table:
        (_pal_name, _pal_why), = WRITE_DERIVED_LATER
        f = table[_pal_name]
        was = dict(w.get("levels", {}) or {})
        was.update(w.get("former_levels", {}) or {})
        rec[f.offset] = 1 if was.get("paladin") else 0
        rep.note(f.offset, f.size,
                 f"{_pal_name}: {rec[f.offset]} -- {_pal_why}")

    # -- derived from the record, once everything else in it is written ------
    # Last, so the digest covers the finished record: a field written after
    # this would change the character without changing its identity byte.
    # `WRITE_DERIVED` is the declaration the tests read; the rule itself is
    # per field, and there is one -- with the one exception its own note
    # describes: a C64 Pool of Radiance source's own draw, taken instead of
    # a digest of a record it never held (#258).  `w.use`, not `char.get`,
    # so a value graded below the floor is refused and reported rather than
    # taken, and so the field counts as consumed either way.
    (_derived_name, _derived_why), = WRITE_DERIVED
    f = table[_derived_name]
    supplied = w.use(_derived_name)
    if supplied is not None and char.port == "C64":
        rec[f.offset] = int(supplied.value) & 0xFF
        rep.note(f.offset, f.size,
                 f"{_derived_name}: {rec[f.offset]:#04x} <- {supplied.origin}")
    else:
        rec[f.offset] = identity_byte(rec, shape)
        rep.note(f.offset, f.size,
                 f"{_derived_name}: {rec[f.offset]:#04x} -- {_derived_why}")

    # -- the gaps, zero in every specimen held -------------------------------
    for f in LAYOUTS[shape.key]:
        if f.name.startswith("gap_"):
            rep.note(f.offset, f.size, f"{f.name}: zero ({f.note})")

    # -- the closing sweep: unwritten fields, then the reader's own drops ----
    w.finish()
    rep.total = size + len(itm) + len(spc)
    return bytes(rec), itm, spc, rep


def write_field_disposition(shape: "int | str | DosShape" = POOL_OF_RADIANCE
                            ) -> dict[str, str]:
    """Every neutral field and what :func:`write` does with it.

    The DOS writer's twin of `goldbox.c64_codec.field_disposition`, over the
    neutral vocabulary; :func:`write_targets` is the same account over the
    DOS layout's own names, and the tests hold both complete.

    **Asked per title, for the reason the reader's `field_disposition` is.**
    Two fields Pool of Radiance drops are converted by the later titles --
    the second copy of each ability score and the class a dual-classed
    character left -- so a Pool of Radiance answer given for a Curse record
    would call a conversion a loss.
    """
    shape = shape_for(shape)
    if shape is POOL_OF_RADIANCE:
        return neutral.disposition(WRITE_DIRECT, WRITE_TRANSFORMED,
                                   WRITE_DROPPED, "the DOS record's")
    later = {n for n, _ in WRITE_TRANSFORMED_LATER}
    return neutral.disposition(
        WRITE_DIRECT, WRITE_TRANSFORMED + WRITE_TRANSFORMED_LATER,
        tuple((n, w) for n, w in WRITE_DROPPED if n not in later),
        "the DOS record's")


# ---------------------------------------------------------------------------
# The conversion, previewed as the plain data `goldbox/yaml_io.py` writes
# ---------------------------------------------------------------------------
def export_party(folder: str | pathlib.Path, slot: str,
                 game_disk: str | None = None) -> dict[str, Any]:
    """A DOS save slot as the same plain data a C64 export produces.

    A **preview of the conversion**, not a raw view of the DOS files: the
    record is converted to the C64 first and the entry built off that, so what
    the document shows is what would land on the C64 disk, and each entry
    carries the conversion's own `_dropped` beside it.  That is why the extra
    hop through `goldbox/c64_codec.py` is there and is not a detour.

    Everything DOS keeps and the C64 does not is kept as a `_`-prefixed
    annotation: `strip_annotations` drops those on import, so the document
    still describes exactly what a C64 save can hold.
    """
    from .icons import Icon
    from .items import ITEM_SIZE as C64_ITEM_SIZE
    from .items import Item, load_item_names, load_item_types
    from .spells import load_spell_names
    from .yaml_io import entry_for

    names = types = spell_names = None
    if game_disk:
        for loader in (load_item_names, load_item_types, load_spell_names):
            try:
                value = loader(game_disk)
            except Exception:
                value = None
            if loader is load_item_names:
                names = value
            elif loader is load_item_types:
                types = value
            else:
                spell_names = value

    party = []
    for index, char in enumerate(read_party(folder, slot)):
        rec, rep = to_c64_record(char)
        inv = rec.get_raw("inventory")
        items = [Item(inv[n * C64_ITEM_SIZE:(n + 1) * C64_ITEM_SIZE], names)
                 for n in range(len(inv) // C64_ITEM_SIZE)]
        items = [i for i in items if not i.is_empty]
        entry = entry_for(c64_codec.read(rec, source=str(folder)),
                          index, items=items,
                          icon=Icon(rec.get_raw("region_220")),
                          names=names, types=types, spell_names=spell_names)
        # What DOS keeps and the C64 does not. Reported, not dropped.
        entry["_dos_encumbrance"] = char.get("encumbrance")
        entry["_dos_encumbrance_expected"] = char.expected_encumbrance()
        entry["_dos_effects"] = [f"{e}: {traits.describe(e)}"
                                 for e in char.effect_ids]
        entry["_dos_item_weights_lb"] = [it.get("weight") / 10.0
                                         for it in char.items]
        entry["_dropped"] = list(rep.dropped)
        if rep.warnings:
            entry.setdefault("_warnings", []).extend(rep.warnings)
        party.append(entry)

    return {
        "source_path": str(pathlib.Path(folder).resolve()),
        "source_slot": slot,
        "game": "pool-of-radiance",
        "port": "dos",
        "party": party,
    }


# ---------------------------------------------------------------------------
# `SAVGAM<slot>.DAT` -- the saved game
# ---------------------------------------------------------------------------
#: **The byte map is `goldbox/dos_savegame.py`'s and only its** (#64). This module
#: used to restate the base, the stride, the word accessor and the position
#: offsets, and the two copies had already begun to disagree about bounds
#: checking within one commit of the second existing. `dos_savegame` depends on
#: nothing but `struct`, so the edge runs this way and not the other.
#:
#: The persistent quest flags. The write-up that gave all 352 bytes of
#: $4A20-$4B7F a disposition, `work/reports/quest-flags.md`, is lost; $4AF9
#: upwards is provably not flag storage, so only this window transfers.
FLAGS_FIRST = dos_savegame.FLAGS_FIRST
FLAGS_LAST = dos_savegame.FLAGS_LAST

#: ECL-visible state the two ports keep at the same addresses, and therefore
#: convertible the way the quest flags are: read the C64 byte, write the DOS
#: word.  `docs/141-dos-savegame.md` grades both CONFIRMED as the same field
#: on both ports.
#:
#: `$49EB` is a script variable -- 0 in ten C64 New Phlan saves and in the DOS
#: New Phlan ones, 1 in both ports' Slums saves; `ECL00` writes 1 when the
#: party boards a boat.  `$4A00`-`$4A1F` is the per-script scratch, the C64's
#: own `SCRIPT_SCRATCH` at the same addresses, zeroed on every area change.
#:
#: Copying the whole scratch window rather than the six words measured live in
#: it (#59) is the same code with fewer special cases, and the other twenty-six
#: read zero on both ports in every specimen -- so what changes is provenance,
#: not values.  **What each word gates is still UNKNOWN and this does not
#: claim otherwise.**  What it settles is where the bytes come from: the party
#: being converted, at its own address, rather than whichever stranger's save
#: was used as the template.
#:
#: It is right on a retarget too, and that is the case that matters: the C64
#: party's scratch belongs to the area the C64 party is standing in, which is
#: exactly the area the DOS save is being moved to.
SHARED_SCRATCH = (0x49EB,) + tuple(range(0x4A00, 0x4A20))


def quest_flags(save: bytes,
                shape: "dos_savegame.DosSaveShape | None" = None,
                window: "tuple[int, int] | None" = None) -> bytes:
    """The flag page as the C64's bytes: read each word, keep the low byte.

    `window` is `(payload offset, length)` and defaults to Pool of Radiance's
    `$4A20`-`$4AF8`, 217 bytes.  Every nonzero word in that window is 1, 2, 3
    or 255 across three saves of two parties -- the flag alphabet, nothing
    wider -- and the runs the quest-flag report names are set and clear
    together.  A base off by one would straddle them.

    **The window is per title, because where it ends is.**  Pool of Radiance
    stops at `$4AF8` because `$4AFA` and `$4AFD` are its wallset and wallmap
    triples (`goldbox/dos_savegame.py`).  Secret of the Silver Blades keeps
    its wall triples in the twelve unnamed bytes of the square block instead
    (#253), and an address census over all twenty-two of its `ECL` scripts,
    on both ports, finds the scripts reading and writing right up to the end
    of the page: `$4CFD` -- the same word index as Pool of Radiance's
    wallmap -- is named by seventeen of the twenty-two, 33 reads and 63
    writes (`tools/eclcensus.py secret-of-the-silver-blades --range 4CE0
    4CFF`).  So five more bytes of a Silver Blades party's flags live past
    where Pool of Radiance's page ends, and the window that stops at `$4AF8`
    loses them.

    CONFIRMED in the running game: the C64 engine's own `ENCAMP > SAVE` of a
    converted party wrote `$FF` at payload `+$1FD`, where the conversion had
    written zero, and all three driven DOS Silver Blades containers hold 255
    at that word (`#193` step 3).
    """
    first, size = window or (FLAGS_FIRST - SAVE0_BASE,
                             FLAGS_LAST - FLAGS_FIRST + 1)
    out = bytearray()
    for i in range(size):
        out.append(dos_savegame.word(save, SAVE0_BASE + first + i, shape)
                   & 0xFF)
    return bytes(out)


def apply_quest_flags(save0: bytearray, savgam: bytes,
                      shape: "dos_savegame.DosSaveShape | None" = None,
                      window: "tuple[int, int] | None" = None) -> int:
    """Copy the flags into a C64 payload. Returns bytes changed.

    The payload is a verbatim image of the save image, so the C64 offset of
    an address is the address less that title's own base.  `window` is the
    container's `quest_flags`; see :func:`quest_flags` for why it is per
    title.
    """
    first, _size = window or (FLAGS_FIRST - SAVE0_BASE,
                              FLAGS_LAST - FLAGS_FIRST + 1)
    flags = quest_flags(savgam, shape, window)
    changed = sum(1 for i, b in enumerate(flags) if save0[first + i] != b)
    save0[first:first + len(flags)] = flags
    return changed


#: The six clock digits and the largest value each holds -- sub-minute,
#: minute units, minute tens, hour, day, month (#58).  `$49C6` means the same
#: six things on both ports, which is what makes the copy below unconditional.
CLOCK_LIMITS = (10, 10, 6, 24, 30, 12)


def apply_clock(save0: bytearray, savgam: bytes,
                shape: "dos_savegame.DosSaveShape | None" = None
                ) -> tuple[str, list[str]]:
    """Copy the DOS clock into a `SAVEDGAME0` payload, digit for digit.

    The mirror of what `write_dos_save` does the other way (#67), and for the
    same reason: the time of day is a value the party carries, not one the
    engine derives on load, so a conversion that does not write it leaves the
    template's clock in place.  Two DOS saves reading 10:15 and 22:15 both
    arrived at 21:15, which was `PORSAVE13`'s time (#103).

    Returns the report line and any complaints, because a digit above what
    its field holds means the six words are not the clock we think they are.
    """
    digits = [dos_savegame.word(savgam, dos_savegame.CLOCK + i, shape)
              for i in range(dos_savegame.CLOCK_DIGITS)]
    warnings = [
        f"clock digit {i} reads {d}, above the {limit} that digit holds; "
        f"written as {d & 0xFF}"
        for i, (d, limit) in enumerate(zip(digits, CLOCK_LIMITS)) if d > limit]
    at = dos_savegame.CLOCK - SAVE0_BASE
    save0[at:at + dos_savegame.CLOCK_DIGITS] = bytes(d & 0xFF for d in digits)
    hour, minute, day, month = dos_savegame.clock(savgam)
    return (f"the clock: {hour}:{minute:02d}, day {day} month {month} -- the "
            f"DOS save's six digit words, narrowed to the C64's six bytes",
            warnings)


def apply_position(save0: bytearray, savgam: bytes,
                   shape: "dos_savegame.DosSaveShape | None" = None) -> tuple:
    """Write the party's square and facing into `SAVEDGAME0`.

    The area is **not** written here.  `$4BC2` is slot 2 of the loaded-files
    cache, not a field beside it, so it belongs to `apply_file_cache` with the
    other twenty-four slots and the three bytes that make them findable.

    Outdoors the square is the travel pair `$49C3`/`$49C4` -- window-local on
    both ports, measured on DOS in #59 and on the C64 in #47 -- and this
    function writes **nothing** into `$49C0`-`$49C2`: the DOS file's
    12801-12803 x,y are the stale square the party left the grid on, not
    where it stands, and the one proven live shape (#47 test D) wrote the
    travel pair alone.

    What those three bytes hold outdoors is :data:`DUNGEON_SQUARE`'s answer
    and not this function's -- `convert_save` zeroes them before calling
    here, so indoors the three writes below land on top of the zero and
    outdoors the zero is what stands.  Saying "left alone" was true only
    while there was a template underneath to leave them to (#118).

    Returns the `(address, what)` notes for the report, because which pair
    was written is exactly what its reader wants to know.
    """
    if dos_savegame.outdoors(savgam):
        x, y = dos_savegame.travel_square(savgam)
        save0[dos_savegame.TRAVEL_X - SAVE0_BASE] = x
        save0[dos_savegame.TRAVEL_Y - SAVE0_BASE] = y
        return ((dos_savegame.TRAVEL_X, "travel-grid x, from SAVGAM $49C3"),
                (dos_savegame.TRAVEL_Y, "travel-grid y, from SAVGAM $49C4"))
    x, y, facing = dos_savegame.position(savgam, shape)
    save0[PARTY_X - SAVE0_BASE] = x
    save0[PARTY_Y - SAVE0_BASE] = y
    save0[PARTY_FACING - SAVE0_BASE] = facing
    return ((PARTY_X, "party x, from SAVGAM"),
            (PARTY_Y, "party y, from SAVGAM"),
            (PARTY_FACING, "facing, the DOS value halved, from SAVGAM"))


# ---------------------------------------------------------------------------
# The whole save
# ---------------------------------------------------------------------------
#: `SAVEDGAME0` is a verbatim image of `$4900`-`$64FF` and `SAVEDGAME1` of
#: `$8300`-`$8AFF`. Every offset below is an address less `$4900` (or `$8300`).
SAVE0_BASE = 0x4900
SAVE1_BASE = 0x8300
#: Where the C64 keeps the party's square -- `goldbox/savegame.py`'s own names for
#: these, read here as offsets into a raw payload.
PARTY_X, PARTY_Y, PARTY_FACING = 0x49C0, 0x49C1, 0x49C2
SLOT_AREA = 0x4D00
SLOT_STRIDE = 0x100
#: `$4D00`-`$54FF` is eight party slots.  Slots 8-11 from `$5500` are combat
#: scratch and are not the party.
SLOT_COUNT = 8

#: How the engine empties a slot, **measured on its own `DROP CHARACTER`**
#: (#104): one byte in each of two places, and nothing else.
#:
#: Dropping BRUTUS from a six-character party changed seven bytes of
#: `SAVEDGAME0` -- five of them the file cache's dirty bits -- and the only one
#: inside his slot was the first byte of his name, `42` to `00`, leaving
#: `\0RUTUS` and every ability, hit point and item exactly where they were.
#: `SAVEDGAME1` changed one byte, roster +0x00.  **There is no party count to
#: decrement**: no byte of `$4900`-`$4CFF` holds one, in 190 saves.
#:
#: So a conversion empties a slot the same way rather than zeroing it: a state
#: the engine is known to produce is worth more than a tidier one nobody has
#: seen it write.
EMPTY_RECORD_BYTE = 0x000    # the first byte of the name
EMPTY_ROSTER_BYTE = 0x000    # `roster_in_use`, `goldbox/layout.py` 0x100
ITEM_AREA = 0x5900
ICON_TABLE = 0x4BE0
ICON_SIZE = 36
ROSTER_STRIDE = 0x20
#: The four 64-entry active-effect arrays. Zero is "no effects running", which
#: is a legal state, and it is what a converted save should carry: every
#: temporary effect is lost in the trip and dropping them is the honest form
#: of that. `docs/133-active-effects.md`.
EFFECT_ARRAYS = ((0x4900, 0xC0), (0x4B80, 0x40))
#: Per-script scratch. `DUNGEON $202A` zeroes it on every area change anyway.
SCRIPT_SCRATCH = (0x4A00, 0x20)
#: The loaded-files cache: twenty-five slots, one per **file kind**, each
#: holding the two hex digits of the file of that kind the engine believes is
#: resident.  Slot 2 is `GEO`, which is why `$4BC2` is the area, and slot 8 is
#: `ECL`.  `docs/140-loaded-files-cache.md` has the whole table.
#:
#: `$FF` is "empty" and is the only value the load path leaves alone.  Bit 7 is
#: not data: `GEN $25DE` reads `LDA $4BC0,X / ORA #$80 / STA $6E13,X` for all
#: twenty-five, so whatever bit a save carries is discarded and set again.
#:
#: **Three slots are enough, and two are not.**  `$FF` everywhere else, slot
#: 2 = the area's `GEO` number, slot 8 = the area id and slot 11 =
#: `ANIMATE00`, and the arriving script's entry 4 refills the rest --
#: CONFIRMED twice in the running game, once retargeting a New Phlan save into
#: Sokol Keep.  That is what lets a converted save stand somewhere the
#: template never did.  Slot 11 was the one #102 found missing: it is not a
#: lazy slot, because the save is *carrying* the file (`CACHE_ANIMATE`).
FILE_CACHE = (0x4BC0, 0x19)
FILE_CACHE_EMPTY = 0xFF
FILE_CACHE_RELOAD = 0x80
#: Which slot is which kind, for the two a converted save writes.
CACHE_GEO = 2
CACHE_ECL = 8
#: Outdoors, slot 4 (`SQRDATA`) does slot 2's job and slot 2 stays `$FF` --
#: no `GEO` loads on the travel grid at all.  Proven live twice in #47,
#: including an indoor Slums template retargeted onto the grid from a cold
#: boot with exactly slot 4 + slot 8 written.
CACHE_SQRDATA = 4
#: And the three a *DOS* save needs: slots 15-17 are the `WALLSET` pieces, and
#: the same three numbers are the DOS save's wallset triple at `$4AFA` -- the
#: Slums is (2,4,1) on both ports and Sokol Keep (1,5,9).  So the C64 save
#: being converted is the source, and no DOS table is needed.
CACHE_WALLSET = 15
CACHE_WALLSET_PIECES = 3
#: A masked slot reading `$7F` is empty -- `$FF` and `$7F` both mean "nothing
#: loaded" to `LIBRARY $4225`.
CACHE_UNSET = 0x7F
#: Slot 11 is `ANIMATE`, and it is **not** one of the lazy slots a converted
#: save may leave empty (#102).  `SAVEDGAME1` is `$8300`-`$8AFF` and its tail
#: from `$8400` is the resident `ANIMATE00` -- 829 of 852 bytes match the file
#: on the disk in `W1`, `PORSAVE11` and `PORSAVE13` alike -- so a save that
#: leaves the slot `$FF` says nothing is loaded while carrying the file.  With
#: `$FF` there, walking off the travel grid into an area draws the area window
#: and stops in it, in all four directions; with `00` the same save completes
#: the transition.  Measured by bisecting the sixteen cache bytes that differ
#: between a full and a minimal cache: slot 11 alone is sufficient and slot 11
#: removed is sufficient to break it (`work/p102/bisect3.log`, `anim.log`).
#:
#: `00` is not a guess and not a choice: `ANIMATE00` is the only `ANIMATE`
#: file in the game and it is on all eight `POOL` sides, so the disk hint
#: never has to reach it.
CACHE_ANIMATE = 11
ANIMATE_RESIDENT = 0x00

#: The disk hint.  `GEN $08BD` is `LDA $49EA / STA $6E12`, and `$6E12` is the
#: `POOL` side the loader asks for by number.  It is not part of the cache but
#: it is what makes the cache's entries findable: a save naming an area on
#: another disk and carrying the template's hint sits on `INSERT SIDE # N`
#: hunting a file that is not on the side it asked for.
DISK_HINT = 0x49EA
#: The map `LOADFILES` reloads into slot 2 indoors.
CURRENT_GEO = 0x49C5
#: The script id.  `CAMP $0D0B` copies it into cache slot 8 when it saves.
CURRENT_SCRIPT = 0x49F2
#: 1 indoors, 0 on the travel grid: `LOADFILES` picks the file *type* from it.
INDOORS = 0x49E6

#: How big each payload is, so a conversion can build one rather than be
#: handed one.  `goldbox/savegame.py`'s own numbers, repeated here beside
#: `SAVE0_BASE` because this module's offsets are all relative to those.
SAVE0_SIZE = 0x1C00             # $4900-$64FF
SAVE1_SIZE = 0x0800             # $8300-$8AFF

#: Twelve slots, not eight.  `$4D00`-`$54FF` is the eight the party can occupy
#: and `$5500`-`$58FF` four more the engine fills during a fight; the item
#: blocks from `$5900` run the same twelve, ending at `$64FF`.  A conversion
#: writes the party's slots and zeroes all the rest, combat scratch included:
#: `ZSLOT8` was built with slots 6-11 and item blocks 6-11 zeroed outright,
#: and the party in it started a fight, fought it and won it -- so combat
#: fills those four from nothing (#118, `work/p118-step3/runF.log`).
SLOT_TOTAL = 12

# ---------------------------------------------------------------------------
# What a conversion writes as zero, and what measured it
# ---------------------------------------------------------------------------
#: The header bytes no part of the conversion computes, as `(address, size)`.
#:
#: All 192 of them were written as zero in a converted save that was then
#: loaded, walked, taken into a random encounter and taken through an area
#: change in VICE (#118, `work/p118-step3/runC.log` and `runE.log`).  The
#: template was `PORSAVE13`, chosen because it is one of the few saves that
#: carries something here to destroy: `$49EB` = 1, `$49F0`-`$49F1` the
#: previous square, `$49FC` = 2, `$49FD`-`$49FE` the wall colours 8 and 9,
#: `$49FF` = 1.  The result was indistinguishable from the control on every
#: check -- the same six names, the same status line, the same arrival screen
#: but for the blinking command-bar cursor, the same squares walked.
#:
#: Corroborated by a census of **99 distinct C64 save payloads**: 48 of the
#: 56 that were unattributed before that run are zero in all 99, and all 56
#: are zero in every one of Donald's own 13 `PORSAVE` disks.  The 137 in
#: `$49FD`-`$49FE` and `$4AF9`-`$4B7F` were already graded "the engine
#: rebuilds it" from the bytecode; the run is what turned that into a
#: measurement.
#:
#: `$49C3`-`$49C4` is here because it is zero in every indoor save, and
#: `apply_position` overwrites it with the travel square when the DOS party is
#: outdoors -- so the zero is what an indoor conversion leaves and not what an
#: outdoor one writes.
#:
#: **`$49EB` is the one entry with a better answer waiting.**  #59 established
#: that the DOS save holds the same script variable at the same ECL address --
#: `SHARED_SCRATCH` copies it in the other direction -- so a conversion could
#: carry the party's own value instead of zeroing it.  Nobody has measured
#: that in this direction, and zero is measured, so zero is what is written.
HEADER_ZEROED: tuple[tuple[int, int], ...] = (
    (0x49C3, 2), (0x49CC, 26), (0x49E7, 3), (0x49EB, 5), (0x49F0, 2),
    (0x49F3, 9), (0x49FC, 1), (0x49FD, 2),
    (0x4AF9, 135), (0x4BD9, 7),
)

#: The C64 save's own portrait switch, and the one word of `$4900`-`$52FF`
#: this conversion writes to a value **measured in the running game** rather
#: than to a measured zero.
#:
#: `LIBRARY $48A4` is the routine that draws the sheet portrait, and
#: **only Pool of Radiance calls it** -- #300 (A Curse or Silver
#: Blades party imported to the C64 arrives with no sheet portrait,
#: because the creation menu is read only off a POOL<n>.D64),
#: `docs/188-the-sheet-portrait-per-title.md`.  The address was
#: written here as `$2C5C`, which is the file offset before
#: `LIBRARY`'s own `$2C48` base is added; the instructions quoted
#: below were right and only the address was wrong:
#:
#:     LDA $49EB / BNE done      ; the arriving area's script scratch
#:     LDA $49FF / BPL done      ; bit 7 clear: draw nothing
#:     LDX #$0B / JSR $4222      ; loaded-files slot 11: ANIMATE
#:     LDA $6BFE / LDX #$0E ...  ; record 0x0FE into cache slot 14, HEAD<xx>
#:     LDA $6BFF / LDX #$0D ...  ; record 0x0FF into cache slot 13, BODY<xx>
#:
#: Measured, VICE, `tools/c64portraitprobe.py`: PORSAVE12 with `$49FF = $01`
#: fetches no portrait art at all and the sheet is blank; the **same image
#: with this one byte set to `$81`** fetches `$08`/`$07` for BRUTUS and
#: `$09`/`$02` for MALCYON -- each character's own record -- and draws the
#: face. Zero here made every converted party faceless whatever its records
#: said, which is the same defect `SAVGAM_MEASURED` records in the other
#: direction, at the same address.
#:
#: **`$81` because `INIT $1156` is `LDA #$81 / STA $49FF`** -- what the engine
#: itself writes when a new game starts. It is a **player's switch**, not a
#: constant: `CAMP $11C7`-`$11F8` reads bit 7 and bit 0, draws a four-item
#: menu and writes the byte back, and Donald's own save disks hold `$81` on
#: five and `$01` on fourteen. Bit 0 is a second flag, read twice by
#: `DUNGEON $1F3C` and `$1FA6` in the view-drawing path and set in 19 of 19 of
#: his saves; what it does is UNKNOWN and `$81` sets it either way.
#: **Two values, and which one is written depends on the party.** `$81` turns
#: the portrait on and is what `INIT` writes; `$01` is the same byte with bit
#: 7 clear, which is the portrait switched off and is what fourteen of the
#: nineteen engine-written C64 saves on this machine hold. A party whose
#: records carry no portrait id must get `$01`: with `$81` and a zero id the
#: loader goes after `HEAD00` -- a real portrait -- and `BODY00`, which is on
#: none of the eight sides, and the sheet sticks on `INSERT SIDE # 2, AND
#: PRESS ANY KEY.` with no bar and no way out. Measured (#57).
PORTRAIT_ON = 0x81
PORTRAIT_OFF = 0x01
PORTRAIT_SWITCH = 0x49FF
PORTRAIT_SWITCH_WHY = (
    "the sheet portrait is not drawn at all when bit 7 of this byte is clear "
    "(#57), and $81 is what INIT writes on a new game. Bit 0 is a second flag "
    "DUNGEON reads and is set in 19 of 19 of the player's saves")

#: The party's square and facing on the **dungeon** map, `$49C0`-`$49C2`.
#:
#: Kept apart from `HEADER_ZEROED` because the evidence is a different run and
#: only one of the two branches ever leaves the zero standing.  `convert_save`
#: writes it before `apply_position`, which overwrites all three indoors --
#: so this is what an *outdoor* conversion puts there, and nothing else.
#:
#: Outdoors nothing computes them: the party is on the travel grid and its
#: square is `$49C3`/`$49C4`.  While the conversion still had a template to
#: work onto, the answer was to leave them alone; with no template, "alone"
#: means whatever `new_save`'s zeroed buffer held, and an unmeasured zero is
#: a blocker rather than a gap (#118).  Left as it was, `new_save` raised on
#: **every** outdoor DOS save -- three bytes with no source.
#:
#: **The engine itself skips these three outdoors**, which is why they are
#: nobody's.  `DUNGEON $1A3C` is `if $49E6 then copy $C04B..$C04D into
#: $49C0..$49C2` (`docs/118-debug-mode.md`): `$C04B`-`$C04D` inside `GDRIVE00`
#: is the live party square and `$49C0`-`$49C2` is the lagging copy a save
#: carries, and the copy is made only when `$49E6` says indoors.  So an
#: outdoor save keeps whatever those three held when the party last left a
#: dungeon, and never anything newer.
#:
#: **Nothing reads them outdoors, measured in VICE.**  Two non-stopping
#: checkpoints over the three bytes, one on loads and one on stores, on four
#: converted outdoor saves built as two pairs differing in these three bytes
#: and nothing else -- `0,0,0` against `15,1,3`.  The read count stayed at
#: **0** through 4 cold boots, 4 save loads, 4 arrivals on the travel grid, 8
#: travel-grid steps and 4 area changes; the first read comes only after the
#: arrival has already written them.  Every log line matched between the two
#: disks of each pair, and 13 screenshot pairs differ in **0 pixels** of the
#: emulated screen (#118, `work/p118-outdoor/`).
#:
#: That run also corrected what the census below looked like it said: the
#: `15,1,3` is New Phlan's arrival square, written by the boat on all four
#: disks, so it is a stale *indoor* square left behind rather than anything an
#: outdoor save means by it.  Zero and 15,1,3 are the same kind of value --
#: whatever the party last arrived on -- and the game reads neither.
#:
#: Zero is also what an engine-written outdoor save holds.  `work/p3/W4.D64`
#: through `W7.D64` are four travel-grid saves the game itself wrote through
#: its own ENCAMP > SAVE (`work/p3/wsave.py`) and all four read 0,0,0.  Over
#: every C64 save payload on this machine -- 115 distinct, 30 of them
#: outdoors -- 6 of the 30 read 0,0,0 (`work/p118-outdoor/census.py`).
DUNGEON_SQUARE: tuple[int, int] = (0x49C0, 3)

#: `SAVEDGAME1`'s tail past `ANIMATE00`: the bitmap buffer, `$8754`-`$8AFF`.
#: 940 bytes, of which 407 were non-zero on the template it was measured
#: against.  Zeroed, loaded, walked, fought in and taken through an area
#: change with no visible difference from the control (#118).
BITMAP_BUFFER = (0x8754, 0x8AFF - 0x8754 + 1)

#: Where the resident `ANIMATE00` sits in `SAVEDGAME1`, and the file it is.
#:
#: `$8400 + 852 - 1` is `$8753`, which is exactly where `BITMAP_BUFFER`
#: begins, so the split between the two is measured rather than assumed.  The
#: file is 852 payload bytes at load address `$1000` and is **byte-identical
#: on all eight `POOL` sides**, so a reader never has to care which side is in
#: the drive.  829 of the 852 match what an engine-written save carries at
#: `$8400` on all 14 of the player's save disks; the 23 that differ are
#: run-time state, and a save with all 852 written as zero loads, walks and
#: changes area anyway (#118, `runD.log`).  So the file's own bytes are
#: strictly closer to right than either zero or a stranger's save.
#:
#: The bytes are never stored here.  `convert_save` is *handed* the payload by
#: a caller that found the disk -- `goldbox/` takes a game file as a parameter
#: and never goes looking, which is what keeps the search in `automap/paths.py`
#: and the application's preferences.
ANIMATE_FILE = b"ANIMATE00"
ANIMATE_AT = 0x8400
ANIMATE_SIZE = 852


#: The refusals, which reach the player through the import dialog's generic
#: handler. Donald's wording, approved 2026-08-24.  Each fires on where the
#: *DOS* party stood, not on the C64 template -- and none of them fires at all
#: when the template already stands in that same area, because then its own
#: cache is real and is kept.
#:
#: The wilderness refusal came off `apply_file_cache` in #50, once #59's
#: outdoor saves settled where a DOS save keeps the travel square, and came
#: off `retarget_reason` -- the other direction -- in #190, once an outdoor
#: DOS retarget had actually been driven.  `WILDERNESS`, Donald's own wording
#: for it, is gone with the last thing that raised it: neither direction
#: refuses a party on the travel grid now.
#:
#: **`UNSUPPORTED_LOCATION` came off `apply_file_cache` in #257** and is now
#: `retarget_reason`'s alone.  Converting a save, the resident map is a word
#: *in that save* -- `$49C5`, see `_resident_geo` -- so an area that loads no
#: map or picks one at run time needs no row to name one, and the training
#: hall stopped being refused.  Retargeting there is a different question
#: with no save to read: the player names an area the party has never been
#: in, and the table is the only source there is.
NOT_AN_AREA = ("the DOS party is in area {area}, which is not an area of "
               "{title}, so there is no map file and no disk to name")
UNSUPPORTED_LOCATION = "Saves from this location are not supported."


def _sqrdata_number(name: str) -> int:
    """`SQRDATA05` -> 5.  Hex digits, like `geo_number`'s."""
    return int(name[len("SQRDATA"):], 16)


def _resident_geo(savgam: bytes, where: "areas.Area", title: str) -> int:
    """Which `GEO` has to be resident for this save.  **The save's own word.**

    `$49C5`, which `goldbox.dos_savegame.geo_block` reads.  It is written by
    `LOADFILES` and read by the `GEO` loader and by nothing else, on both
    ports, so it *is* the map the party is standing on -- and it is a fact in
    the file rather than an inference from the area table.

    This used to be `areas.geo_number(where.geos[0])`, and that reading has
    three failures the save does not have (#257):

    * **an area whose script loads no map** -- the training hall (11) and
      Phlan City Hall (8) run on whatever `ECL00` left resident, so
      `where.geos` is empty and the conversion refused the save outright with
      `Saves from this location are not supported.`;
    * **an area that picks its map at run time** -- areas 3 and 5, whose
      `geos` entry `goldbox/areas.py` says in as many words is the doc's
      inference from the id and is wrong for both.  Refused as well;
    * **an area that loads two maps**, where `geos[0]` is whichever the
      script loads first and the party may be standing on the other.

    The save answers all three the same way.  CONFIRMED for the one-map case:
    12 of 12 Pool of Radiance saved games on this machine whose area owns a
    map hold `$49C5` = `geo_number(geos[0])` exactly -- areas 0, 20 and 21
    across three collections, including the five this project made itself.
    CONFIRMED for the training hall in the running game, where the two hall
    specimens hold `$49C5` = 0 with `$49F2` = 11 and the C64 draws the school
    on `GEO00`.  The two-map and dynamic cases are PROBABLE: the reasoning is
    the same and no save has been made in one.

    Both refusals are contradictions rather than gaps, and neither has ever
    fired on a real save.
    """
    geo = dos_savegame.geo_block(savgam)
    known = {areas.geo_number(g) for g in areas.geos_in(title)}
    # An empty set is not a contradiction, it is a title whose area table
    # nobody has built yet -- `areas.geos_in` says so itself: "if this ever
    # refuses a save the game itself wrote, the row is what is incomplete."
    # Curse of the Azure Bonds has no rows at all, so refusing on an empty
    # set refused every Curse save there is, which is the opposite of what
    # #257 set out to do: trust the word in the save.
    if known and geo not in known:
        raise DosRecordError(
            f"the save's own $49C5 says GEO{geo:02X} is the resident map, "
            f"and no area of {title} loads that map -- so either the save is "
            f"not one this reader understands or goldbox/areas.py is missing "
            f"a row")
    owned = {areas.geo_number(g) for g in where.geos}
    if owned and not where.dynamic_geo and geo not in owned:
        raise DosRecordError(
            f"the save's own $49C5 says GEO{geo:02X} is the resident map, "
            f"but area {where.id} ({where.name or where.ecl}) loads "
            f"{' and '.join(where.geos)} in goldbox/areas.py -- these two "
            f"disagree and neither is trusted over the other")
    return geo


def apply_file_cache(save0: bytearray, savgam: bytes,
                     container: "c64_save.Container | None" = None) -> str:
    """Point a `SAVEDGAME0` payload at the area the DOS party is standing in.

    The cache is rewritten to `$FF` in all twenty-five slots with slot 2 =
    the resident `GEO` number, slot 8 = the area id and slot 11 = `ANIMATE00`
    -- the file `SAVEDGAME1`'s own tail holds (#102) -- plus the three bytes
    outside the cache that make those findable: the disk hint `$49EA`, the
    map `$49C5` and the script id `$49F2`.  Returns the one line the report
    puts against the cache.

    That is `docs/140-loaded-files-cache.md`'s recipe and is the shape both
    live tests used.  Outdoors the same recipe with slot 4 in slot 2's
    role -- `SQRDATA` where a dungeon has a `GEO` -- which is the outdoor form
    #47 proved live twice, plus `$49E6` = 0, which is on its own what boots
    the engine into travel mode.

    **The area and the map are two different words and are read separately**
    (#257).  Slot 8 and `$49F2` take `current_area`, which is `$49F2` in the
    DOS save; slot 2 and `$49C5` take `_resident_geo`, which is `$49C5`.  The
    two hold the same number wherever an area loads its own map, which is
    most of them, and part company in the training hall -- where a save read
    through `$49C5` alone converted to a party standing in New Phlan.  One
    refusal is left, for an area this project has no row for at all.

    **It applies to a template standing in the area too** (#121).  That case
    used to return early and keep the template's own cache, on the reasoning
    that the game wrote it and it names more files than a converted save
    needs.  It was the only path here that preferred an inherited value to a
    computed one, and it cost 29 bytes of somebody else's save.  One of the
    two live tests of the recipe is itself a same-area case -- PORSAVE13 in
    the Slums -- so the branch that went is the one already proven
    unnecessary.
    """
    container = c64_save.container_for(container)
    at, slots = container.cache
    on = FILE_CACHE_RELOAD if container.cache_bit7 else 0
    there = dos_savegame.current_area(savgam)
    where = areas.area_in(there, container.game.title)
    if where is None:
        raise DosRecordError(NOT_AN_AREA.format(area=there,
                                                title=container.game.title))
    savgam_outdoors = dos_savegame.outdoors(savgam)
    if savgam_outdoors != where.outdoors:
        raise DosRecordError(
            f"the save's own $49E6 says "
            f"{'outdoors' if savgam_outdoors else 'indoors'}, but script id "
            f"{there} ({where.name or where.ecl}) is marked "
            f"{'outdoors' if where.outdoors else 'indoors'} in "
            "goldbox/areas.py -- these two disagree and neither is trusted "
            "over the other")
    save0[at:at + slots] = bytes([FILE_CACHE_EMPTY]) * slots
    save0[at + CACHE_ECL] = there | on
    save0[at + CACHE_ANIMATE] = ANIMATE_RESIDENT | on
    save0[container.disk_hint] = where.disk
    save0[container.current_script] = there
    if where.outdoors:
        sqr = _sqrdata_number(where.sqrdata)
        save0[at + CACHE_SQRDATA] = sqr | on
        save0[container.current_geo] = sqr   # $49C5 holds the SQRDATA
        save0[container.indoors] = 0         # number outdoors (#47)
        return (f"loaded-files cache: $FF in all twenty-five, then slot 4 = "
                f"{where.sqrdata}, slot 8 = {where.ecl} and slot 11 = "
                f"ANIMATE00; outdoors no GEO loads at all, and $49E6 = 0 is "
                f"what boots into travel mode")
    geo = _resident_geo(savgam, where, container.game.title)
    save0[at + CACHE_GEO] = geo | on
    save0[container.current_geo] = geo
    save0[container.indoors] = 1
    return (f"loaded-files cache: $FF in all twenty-five, then slot 2 = "
            f"GEO{geo:02X}, the save's own $49C5, slot 8 = {where.ecl} and "
            f"slot 11 = ANIMATE00"
            + ("," if container.cache_bit7 else ";")
            + (" each with bit 7 set, which this title's loader does not set "
               "for itself; " if container.cache_bit7 else " ")
            + "the arriving script refills the rest")


def marching_slot(index: int, count: int) -> int:
    """Which C64 save slot a party member at DOS marching position `index` goes in.

    **The C64 lists the party from the highest slot down** (#101).  Its own
    `ENCAMP > ALTER > ORDER` screen asks `WHO TAKES POSITION #1?` over a list
    headed by BRUTUS, and BRUTUS is in slot 5 of `work/p3/W1.D64`, an
    engine-written save whose slots 0-5 are MALCYON, LADY KATHERINE, ROLAND,
    SILAS, MAGNUS, BRUTUS.  The main panel lists the same six in the same
    order, and so does `PORSAVE13`.

    DOS is the other way round: the file order is the marching order, and
    `party_order` at `0x0BF` is 0 for the first-listed character because the
    loader allocates combat-icon slots as it reads that list (#305).  So the
    conversion reverses; writing DOS index *i* into slot *i* put the DOS
    party's front-rank fighter at the back of the C64 one.

    The party stays in the low slots, `count - 1` down to 0, which is where
    every engine-written save keeps it.

    **This assumes a packed party** -- `count` members in slots `0..count-1`
    with no gap -- which is what this function's one caller, `convert_save`,
    always builds. It is not the arithmetic for reading a party back off a
    save that may hold a hole: `ALTER > DROP` can leave one, and `count - 1 -
    index` has no way to skip it. `SaveGame0.marching_order` (`#160`) is the
    one that reads a real save's occupied slots and descends over exactly
    those, so it is the home for that case rather than a generalisation of
    this formula.
    """
    return count - 1 - index


@dataclasses.dataclass
class C64SaveReport(Report):
    """A whole-save conversion's provenance, over **both** save files.

    Offsets 0 to `save0_size - 1` are `SAVEDGAME0`, a verbatim image of
    `$4900`-`$64FF`; `save0_size` and up are `SAVEDGAME1`, which is `$8300`
    onwards.  One flat offset map for two files, which is the shape
    :class:`WriteReport` already uses for the record and the `.ITM` payload
    beside it.

    `SAVEDGAME1` was absent from the report entirely until #120: nothing
    called `note` for it, the fill-in sweep ran to `len(save0)`, and `total`
    counted one file -- so the summary said `3833/7168 bytes accounted for`
    about a 9216-byte output whose second file is 90% template bytes.
    """

    #: How many of the offsets belong to `SAVEDGAME0`.  The rest are
    #: `SAVEDGAME1`, and zero of them when the caller passed no `save1`.
    #:
    #: `convert_save` is the only thing that builds one of these and it always
    #: passes `len(save0)`, so this default is never reached.  It is `$6500` -
    #: `$4900` -- the real size -- rather than 0, because a second constructor
    #: that forgot to pass it would otherwise pair it with `Report.total`'s own
    #: default of `RECORD_SIZE` and label every offset `SAVEDGAME1`.  Both
    #: defaults being wrong together is a seam; this half of it is at least the
    #: right number.
    save0_size: int = 0x1C00

    #: Offsets the conversion did not write, and so left to whatever the
    #: payload already held.  Empty when the save was built from nothing:
    #: that is what makes "no template" checkable rather than asserted.
    unwritten: list[int] = dataclasses.field(default_factory=list)

    def summary_notes(self) -> list[str]:
        lines = super().summary_notes()
        if self.total > self.save0_size:
            lines.append(f"  SAVEDGAME0 {self.save0_size} bytes, SAVEDGAME1 "
                         f"{self.total - self.save0_size}")
        if self.unwritten:
            lines.append(f"  {len(self.unwritten)} bytes left to the payload, "
                         f"from {self.address(self.unwritten[0])}")
        return lines

    def address(self, offset: int) -> str:
        """`SAVEDGAME1 $8300`-style, because `0x0100` now means two things."""
        if offset < self.save0_size:
            return f"SAVEDGAME0 ${SAVE0_BASE + offset:04X}"
        return f"SAVEDGAME1 ${SAVE1_BASE + offset - self.save0_size:04X}"


def convert_save(folder: str | pathlib.Path, slot: str,
                 save0: bytearray, save1: bytearray | None = None,
                 icon: "bytes | IconParts | None" = None,
                 animate: bytes | None = None,
                 portraits: PortraitTables | None = None,
                 game=None) -> C64SaveReport:
    """Write a DOS save into C64 `SAVEDGAME0` / `SAVEDGAME1` payloads.

    Both payloads are modified in place, and **the conversion writes every
    byte of both** when it is given an `icon` and an `animate`: hand it two
    zeroed buffers and the result is a whole save owing nothing to anybody
    else's (#118).  :func:`new_save` is that call, and is what the import
    uses.

    `icon` is either the 36-byte combat icon every converted character gets
    when there is no DOS figure to draw from -- composed from the player's
    own game disk, `goldbox.iconparts.IconParts.default_icon` -- or an
    `IconParts` itself, in which case each character's own `icon_head`,
    `icon_body` and `icon_colours` become his own figure instead (#130,
    :func:`_icon_for`).  `animate` is `ANIMATE00`'s 852-byte payload off the
    same disks, which goes at `$8400`.  Leave either out and that region
    keeps whatever the payload already held, which is only ever right when
    the payload came from a real C64 save; `Report.unwritten` is what says
    so afterwards.

    `portraits` is the creation menu's two tables, from
    :func:`portrait_tables`.  With them each character's sheet portrait
    crosses and `PORTRAIT_SWITCH` is turned on; without them, or when a
    character's own position is not one the menu offers, the switch is left
    off rather than turned on over a party some of whom have no art id --
    turning it on over a zero id sends the C64 hunting a `BODY00` that is on
    none of the eight sides, and the sheet sticks with no way off it (#57).

    The report covers both files: an offset below `len(save0)` is a
    `SAVEDGAME0` offset and one at or above it is `SAVEDGAME1`'s (#120).
    `Report.unwritten` is empty when nothing was left to the payload.
    """
    container = c64_save.container_for(game)
    shape = dos_savegame.save_shape_for(container.game.key)
    party = read_party(folder, slot)
    savgam = pathlib.Path(folder).joinpath(
        f"SAVGAM{slot}{shape.suffix}").read_bytes()
    save1_at = len(save0)
    report = C64SaveReport(
        total=len(save0) + (0 if save1 is None else len(save1)),
        save0_size=len(save0))

    # First, because `apply_position` writes the travel square over
    # `$49C3`-`$49C4` when the DOS party is outdoors.
    for at, size, why in container.zeroed:
        save0[at:at + size] = bytes(size)
        report.note(at, size, why)
    # And the header bytes with a source in the DOS save and no attribution:
    # the party's own value at the same distance into the same ECL variable
    # array, rather than a zero nobody has measured for this title.
    for at, size, why in container.copied:
        save0[at:at + size] = bytes(
            dos_savegame.word(savgam, SAVE0_BASE + at + i, shape) & 0xFF
            for i in range(size))
        report.note(at, size, why)
    # And the dungeon square, which `apply_position` overwrites indoors and
    # leaves standing outdoors.  Its own note and its own evidence, so the
    # sentence above keeps saying exactly what its own run covered.
    at = DUNGEON_SQUARE[0] - SAVE0_BASE
    save0[at:at + DUNGEON_SQUARE[1]] = bytes(DUNGEON_SQUARE[1])
    report.note(at, DUNGEON_SQUARE[1],
                "zero: the party is on the travel grid and its square is "
                "$49C3/$49C4, so nothing here computes the dungeon square -- "
                "and nothing in the game reads it there, measured at 0 reads "
                "across a load, eight travel steps and an area change (#118)")

    #: This title's own correspondence, once for each size rather than once
    #: per character: the file is read from disk and six characters would
    #: read it six times.  Both sizes because a party mixes them -- a
    #: halfling and a human in the same six -- and the small list is not the
    #: large one scaled, so a few rows name a different C64 option there
    #: (#335).
    icon_tables = {
        which: dos_icon_tables(title=container.game.key, size=which)
        for which in ("small", "large")
    } if isinstance(icon, IconParts) else {}

    all_faced = True
    for index, char in enumerate(party):
        place = marching_slot(index, len(party))
        rec, one = to_c64_record(
            char,
            icon=_icon_for(char, icon,
                           icon_tables.get(dos_size(char.get("size")))),
            portraits=portraits)
        all_faced = all_faced and one.has_portrait
        # `party_order` in a roster block is the record's slot index, not the
        # marching position -- `goldbox/layout.py` 0x10D, and identity in every
        # engine-written save read.  It follows the slot the record lands in.
        rec.set("party_order", place)
        raw = rec.to_bytes()
        who = f"slot {place}: {char.name}, {index + 1} in the DOS marching order"
        at = container.slot(place)
        save0[at:at + SLOT_STRIDE] = raw[:SLOT_STRIDE]
        report.note(at, SLOT_STRIDE, f"{who} -- the converted record")
        at = container.items(place)
        save0[at:at + SLOT_STRIDE] = raw[0x120:0x220]
        report.note(at, SLOT_STRIDE, f"{who} -- the converted inventory")
        at = container.icon(place)
        save0[at:at + ICON_SIZE] = raw[0x220:0x244]
        report.note(at, ICON_SIZE, f"{who} -- " + (
            "the combat figure this character's own DOS record names: "
            "icon_body and icon_head through the table in "
            "tools/iconproposal.yaml, and the low nibble of most of the six "
            "icon_colours pairs through the same file's colour table -- the "
            "high nibble for the leg and the shield (#130)"
            if isinstance(icon, IconParts) else
            "the combat icon the game's own character creation writes, "
            "composed from the player's own disk"
            if icon is not None else
            "icon from the record, which is zero"))
        if container.name_table is not None:
            entry = container.name_index(place, len(party))
            at = container.name(entry)
            save0[at:at + container.name_stride] = (
                raw[:container.name_stride])
            report.note(at, container.name_stride,
                        f"{who} -- the party's own name table, which this "
                        f"title keeps beside the records and fills in "
                        + ("marching order, so entry 0 is the character at "
                           "the head of the party"
                           if container.names_in_marching_order
                           else "slot order"))
        at, into = ((container.roster_offset + place * ROSTER_STRIDE, save0)
                    if container.roster_in_payload
                    else (place * ROSTER_STRIDE, save1))
        if into is not None:
            into[at:at + ROSTER_STRIDE] = raw[0x100:0x120]
            flat = at if into is save0 else save1_at + at
            report.note(flat, ROSTER_STRIDE,
                        f"{report.address(flat)} -- {who} -- the converted "
                        f"roster block: the derived combat numbers the "
                        f"character record does not hold")
        report.dropped.extend(d for d in one.dropped if d not in report.dropped)
        report.warnings.extend(f"{char.name}: {w}" for w in one.warnings)

    at = container.portrait_switch
    faces = bool(party) and all_faced
    if container.game.key == games.POOL_OF_RADIANCE.key:
        save0[at] = PORTRAIT_ON if faces else PORTRAIT_OFF
        report.note(at, 1, f"${save0[at]:02X}: {PORTRAIT_SWITCH_WHY}"
                    + ("" if faces else ". Written with bit 7 clear "
                       "because a character here has no portrait id, and "
                       "the game hunts for a BODY00 that is on no side"))
    else:
        # `PORTRAIT_OFF` is Pool of Radiance's answer to a party with no
        # portrait ids, and it is Pool of Radiance's because `BODY00` is on
        # none of its eight sides. Curse of the Azure Bonds carries `HEAD00`
        # and `BODY00` on side 2, its own `INIT` writes `LDA #$81 / STA
        # $4BFF`, and both engine-written Curse saves hold `$81` over six
        # characters whose portrait ids are all zero -- so the on value is
        # safe here whether or not the ids crossed.
        save0[at] = PORTRAIT_ON
        report.note(at, 1,
                    f"${PORTRAIT_ON:02X}: what this title's own INIT writes "
                    f"when a new game starts, and what both engine-written "
                    f"saves of it hold")

    # The party fills slots `len(party) - 1` down to 0, so everything above it
    # is somebody else's and would otherwise walk into the converted party
    # (#104).  The whole slot goes, not the `DROP`-style name byte the engine
    # writes: `ZSLOT8` zeroed slots 6-11, item blocks 6-11, icons 6-7 and
    # roster blocks 6-7 on the one template in 99 whose slots 6 and 7 hold a
    # seventh and an eighth character -- 555 non-zero bytes of a stranger's
    # party wiped -- and the party list showed six, the party walked five
    # squares and won a fight (#118, `work/p118-step3/runF.log`).
    for place in range(len(party), container.record_pages):
        for at in (container.slot(place), container.items(place)):
            save0[at:at + SLOT_STRIDE] = bytes(SLOT_STRIDE)
            report.note(at, SLOT_STRIDE,
                        f"slot {place}: zeroed entire -- not this party's, and "
                        f"a party that carried none of these fought and won "
                        f"(#118)")
        if place >= container.party_slots:
            continue
        at = container.icon(place)
        save0[at:at + ICON_SIZE] = bytes(ICON_SIZE)
        report.note(at, ICON_SIZE,
                    f"slot {place}: combat icon zeroed -- nothing draws "
                    f"an icon for a slot with no character in it")
        if container.name_table is not None:
            at = container.name(place)
            save0[at:at + container.name_stride] = bytes(container.name_stride)
            report.note(at, container.name_stride,
                        f"slot {place}: name table entry zeroed, since no "
                        f"character is in that slot")
        at, into = ((container.roster_offset + place * ROSTER_STRIDE, save0)
                    if container.roster_in_payload
                    else (place * ROSTER_STRIDE, save1))
        if into is not None:
            into[at:at + ROSTER_STRIDE] = bytes(ROSTER_STRIDE)
            flat = at if into is save0 else save1_at + at
            report.note(flat, ROSTER_STRIDE,
                        f"{report.address(flat)} -- slot {place}: roster "
                        f"block zeroed, `roster_in_use` with it")
    if len(party) < container.party_slots:
        report.warnings.append(
            f"Slots {len(party)}-{container.party_slots - 1} emptied: a DOS "
            f"save holds six characters and a C64 save "
            f"{container.party_slots}")

    for base, size in EFFECT_ARRAYS:
        at = base - SAVE0_BASE
        save0[at:at + size] = bytes(size)
        report.note(at, size, "active effects: zeroed, which is 'none running'")
    if not any(at == SCRIPT_SCRATCH[0] - SAVE0_BASE
               for at, _, _ in container.copied):
        at = SCRIPT_SCRATCH[0] - SAVE0_BASE
        save0[at:at + SCRIPT_SCRATCH[1]] = bytes(SCRIPT_SCRATCH[1])
        report.note(at, SCRIPT_SCRATCH[1],
                    "per-script scratch: zeroed, as DUNGEON $202A does on "
                    "every area change")
    at, slots = container.cache
    outdoors = dos_savegame.outdoors(savgam)
    report.note(at, slots, apply_file_cache(save0, savgam, container))
    for at, what in (
            (container.disk_hint, "the disk side the loader will ask for"),
            (container.current_geo, "the SQRDATA number LOADFILES reloads" if
             outdoors else "the map LOADFILES reloads"),
            (container.current_script, "the script id"),
            (container.indoors, "outdoors -- 0 boots into travel mode" if
             outdoors else "indoors")):
        report.note(at, 1, f"{what}, from the area the DOS party is in")
    if container.picture_buffer is not None:
        at, size = container.picture_buffer
        save0[at:at + size] = bytes(size)
        # Not a map -- #309 (Eight files still call Curse's picture buffer a
        # map region, which is what it was guessed to be before anybody read
        # it).  Zero is measured rather than inherited: the engine zeroes the
        # buffer itself before every decode and reads nothing from it before
        # then, watched in the running game
        # (`docs/181-curse-picture-buffer.md`).
        report.note(at, size,
                    "`ANIMATE00`'s picture buffer -- the decoded glyphs and "
                    "colours of the picture in the view window, which on "
                    "ENCAMP is the camp scene: zeroed, and the engine "
                    "rebuilds it before it draws. Nothing in the DOS save "
                    "corresponds to it")

    changed = apply_quest_flags(save0, savgam, shape, container.quest_flags)
    report.note(*container.quest_flags,
                "quest flags: the DOS word array, narrowed to bytes")
    for address, what in apply_position(save0, savgam, shape):
        report.note(address - SAVE0_BASE, 1, what)
    note, complaints = apply_clock(save0, savgam, shape)
    report.note(container.clock, dos_savegame.CLOCK_DIGITS, note)
    report.warnings.extend(complaints)
    # "differed from the template's" until #118 removed the template, after
    # which the sentence described something that no longer exists: from
    # nothing the payload is zero, so what this counts is the DOS party's own
    # set flags.  It is a count either way, so the wording says what was
    # compared rather than naming a save that may not be there.
    report.warnings.append(
        f"{changed} of {container.quest_flags[1]} quest-flag bytes "
        f"differed from what the payload already held")
    if save1 is not None:
        at = BITMAP_BUFFER[0] - SAVE1_BASE
        save1[at:at + BITMAP_BUFFER[1]] = bytes(BITMAP_BUFFER[1])
        report.note(save1_at + at, BITMAP_BUFFER[1],
                    f"SAVEDGAME1 ${BITMAP_BUFFER[0]:04X} -- the bitmap "
                    f"buffer: zeroed, and a save with all "
                    f"{BITMAP_BUFFER[1]} of these zero was indistinguishable "
                    f"from the control on load, on a walk, in a fight and "
                    f"through an area change (#118)")
        if animate is not None:
            if len(animate) != ANIMATE_SIZE:
                raise DosRecordError(
                    f"{ANIMATE_FILE.decode()} is {ANIMATE_SIZE} payload "
                    f"bytes on every POOL side; this one is {len(animate)}")
            at = ANIMATE_AT - SAVE1_BASE
            save1[at:at + len(animate)] = animate
            report.note(save1_at + at, len(animate),
                        f"SAVEDGAME1 ${ANIMATE_AT:04X} -- "
                        f"{ANIMATE_FILE.decode()} as the loader leaves it, "
                        f"read off the player's own game disk. The cache says "
                        f"the file is resident and this is the file (#102)")

    # Anything still without a source was left to whatever the payload already
    # held -- somebody else's save, when the payload came from one.  With an
    # `icon` and an `animate` given there is nothing here, and `unwritten`
    # being empty is what "built from nothing" means.
    report.unwritten = [i for i in range(report.total)
                        if i not in report.sources]
    for i in report.unwritten:
        report.sources[i] = (
            f"{report.address(i)}: not converted -- left as the template "
            f"save had it")
    return report


def new_save(folder: str | pathlib.Path, slot: str,
             icon: "bytes | IconParts",
             animate: bytes, portraits: PortraitTables | None = None,
             game=None) -> tuple[bytearray, bytearray, C64SaveReport]:
    """A whole C64 save from a DOS one, owing nothing to another save (#118).

    `icon` is either the 36-byte combat icon every character gets, or the
    C64's own option tables as an `IconParts`, in which case each character
    gets the figure his own DOS record names instead (#130).  `animate` is
    `ANIMATE00`'s payload; both come off the player's own game disks, and
    there is no default for either -- a conversion that cannot read them is
    one that would have to invent bytes, and it refuses instead.  `portraits`
    is the creation menu's two tables (#57); unlike `icon` and `animate` it
    is not required -- a party converted without it keeps its own records
    but arrives with the sheet portrait switched off, which is the same
    thing an engine-written save does when the player has turned it off.

    Returns the two payloads and the report, whose `unwritten` is empty.
    """
    container = c64_save.container_for(game)
    save0 = bytearray(container.payload_size)
    save1 = (bytearray() if container.roster_in_payload
             else bytearray(container.game.roster_size))
    report = convert_save(folder, slot, save0, save1 or None,
                          icon=icon, animate=animate, portraits=portraits,
                          game=container)
    if report.unwritten:
        raise DosRecordError(
            f"{len(report.unwritten)} bytes of the save have no source and "
            f"were left zero by accident rather than by measurement; the "
            f"first is {report.address(report.unwritten[0])}")
    return save0, save1, report


def save_disk(save0: bytes, save1: bytes, game=None):
    """A `.d64` carrying exactly the two files a save disk needs (#118).

    Thirteen of the player's fifteen `PORSAVE*.D64` hold `SAVEDGAME1` and
    `SAVEDGAME0` and nothing else, in that directory order, so that is what
    this writes.  Built onto `D64.blank()` with the drive's own interleave,
    the result reproduces a disk the 1541 wrote everywhere but the two files'
    final-sector slack, on all 13 (`tests/test_d64_blank.py`).
    """
    from .d64 import D64, attach_load_address
    game = game or games.POOL_OF_RADIANCE
    disk = D64.blank()
    if not game.roster_in_payload:
        disk.write_file(game.roster_file,
                        attach_load_address(game.roster_load_address, save1))
    disk.write_file(game.save_file,
                    attach_load_address(game.save_load_address, save0))
    return disk


# ---------------------------------------------------------------------------
# The whole save, the other way: a C64 save becomes DOS files (#26)
# ---------------------------------------------------------------------------
#: Where a retarget looks for `ECL<n>.DAX` when the caller names no game
#: directory: the save directory itself, then its parent, which is where the
#: archives keep it (`GAME/POOLRAD/SAVE` inside `GAME/POOLRAD`).
ECL_DAX = "ECL{dax}.DAX"


def c64_wall_triple(save0: bytes,
                    container: "c64_save.Container | None" = None
                    ) -> tuple[int, int, int]:
    """The wallset triple a DOS save wants, out of the C64 loaded-files cache.

    Cache slots 15-17 hold the three `WALLSET` pieces, and the DOS save holds
    the same three numbers as words -- PORSAVE13's Slums (2,4,1) is DOS slot
    J's, PORSAVE's Sokol Keep (1,5,9) is slot B's.  An empty C64 slot becomes
    an empty DOS word.

    **The same slots in Curse and Silver Blades, at the container's own
    cache offset** (#299): the Curse disk `WISH-SPEC-curse-dual-classed`
    holds `81 82 83` there and both played DOS Curse containers hold
    `(1, 2, 3)` in their square block; the Silver Blades disk
    `WISH-SPEC-ssb-d-engine-resave` holds `95 FF FF` and all four played
    DOS Silver Blades containers hold `(21, $FFFF, $FFFF)`.  Where the DOS
    value lands is `dos_savegame.put_wall_block`'s business.

    **New Phlan is the exception**: the C64 loads no `WALLSET` there at all
    and every slot reads `$FF`, where DOS slot A holds `(0, $FFFF, $FFFF)`.
    So this returns three empties for a New Phlan save, which is not what the
    DOS engine's own save says -- and is measured to draw the identical view
    anyway, `work/p60/run3` Z0.
    """
    container = c64_save.container_for(container)
    at = container.cache[0] + CACHE_WALLSET
    out = []
    for b in save0[at:at + CACHE_WALLSET_PIECES]:
        v = b & ~FILE_CACHE_RELOAD & 0xFF
        out.append(dos_savegame.EMPTY if v == CACHE_UNSET else v)
    return tuple(out)


def dos_dax_number(game: "str | pathlib.Path | None", area: int
                   ) -> "int | None":
    """Which `ECL<n>.DAX` in the DOS game directory holds this area's
    script -- the number the container's byte 0 and `$5012` want.

    **The C64 side number is not that number in Silver Blades** (#299).
    Pool of Radiance and Curse pack their scripts into one `ECL<n>.DAX` per
    C64 side, so `areas.Area.disk` is the DOS number too -- 29 of 29 Pool
    of Radiance rows with a block and 24 of 24 Curse ones, checked file by
    file against the archives.  Silver Blades has three DOS containers for
    six C64 sides: `ECL1.DAX` holds `$03`, `$10`, `$20`-`$22`, `ECL2.DAX`
    holds `$11` and `$30`-`$44`, and `ECL3.DAX` holds `$50`-`$63`, so the
    table's disk column names a `ECL4.DAX` that does not exist for area
    `$40`.  The table is right for what it is -- the side the C64 loader
    asks for -- and this reads the DOS answer off the DOS files instead.

    None when no container holds the block, which is the case for both
    titles' overland ids (`$1E`), and for a directory with no `ECL` files.
    """
    if not game:
        return None
    root = pathlib.Path(game)
    for path in sorted(root.glob("ECL*.DAX")):
        stem = path.stem[3:]
        if not stem.isdigit():
            continue
        try:
            index = dos_savegame.dax_index(path.read_bytes(), path.name)
        except dos_savegame.DosSaveError:
            continue
        if any(bid == area for bid, *_ in index):
            return int(stem)
    return None


#: Which way a converted party faces on the travel grid, and **the one field
#: an outdoor conversion cannot carry** (#190).
#:
#: The C64 keeps its travel heading at `$033D` -- eight-way, one of eight
#: rather than one of four (`docs/137-wilderness-automap.md`) -- and `$033D`
#: is page 3, outside the `$4900`-`$64FF` that `SAVEDGAME0` is an image of.
#: So no C64 saved game holds one, and there is nothing to read.  The DOS
#: byte 12803 is live out there by contrast: it prints the facing letter on
#: the status line, it reads 0, 0, 0 and 2 across the four engine-written
#: overland saves in `work/p50-outdoor` and `work/p59-wallset/keep`, and the
#: engine rewrote a written 0 to 2 after two steps in both of #190's runs.
#:
#: **The C64's own `$49C2` is not the answer**, tempting as it is: outdoors
#: that byte is the *dungeon* facing, frozen with the square beside it at
#: whatever the party last faced indoors.  Writing it here would put a
#: direction on the DOS status line derived from an unrelated moment, which
#: is wrong data that looks right.  North is a value the engine itself
#: writes, and the byte's whole account is in the report's provenance note.
#:
#: **This is a note and no longer a line a player reads** -- #248 (The DOS
#: export pane's outdoor-facing drop line carries a memory address and a raw
#: byte number in front of a player).  It went verbatim into
#: `report.dropped`, so `editor/exports.py`'s pane showed `$033D`,
#: `$4900-$64FF` and "byte 12803" to somebody exporting an outdoor party,
#: which is what `.claude/rules/gui-text.md` calls a developer's note that
#: escaped.  `report.note` is where an address belongs: those never leave the
#: byte-by-byte accounting.
#:
#: **Nothing replaced it, on purpose.**  Every word a player reads is
#: Donald's to approve (`.claude/rules/gui-text.md`), so a new sentence is
#: proposed on #248 rather than shipped here.  The player is told nothing
#: today, which is also where `.claude/rules/conversions.md` points -- the
#: DOS engine rewrites the byte on the party's first step, measured in both
#: of #190's runs, so a converted party faces north for as long as it stands
#: still and is right from then on.
OUTDOOR_FACING = 0
OUTDOOR_FACING_WHY = (
    "which way the party faces on the travel grid: north. The C64 keeps its "
    "outdoor heading at $033D, which is page 3 and outside the $4900-$64FF a "
    "save is an image of, so no C64 save carries one -- while byte 12803 is "
    "live on DOS and prints the facing letter. 0 is north, which is what three "
    "of the four engine-written overland saves here hold, and the engine "
    "rewrites it as soon as the party moves")

#: The three reasons a DOS variable this conversion cannot source is written
#: **zero** rather than left at somebody else's value.  Each is the head of a
#: reason string in :data:`SAVGAM_UNSOURCED`, so a reader can tell the three
#: apart without reading twenty lines of table.
ENGINE_REBUILT = ("one of the nine words the engine rewrote by itself when it "
                  "loaded a hand-built save and the party moved (#59)")
DOS_ONLY = ("DOS engine state with no C64 counterpart -- above $4AF9, which "
            "no ECL script in the thirty-script corpus references (#59)")
ENCOUNTER_STATE = ("the pending-encounter record: it changes together with "
                   "the message buffer beside it, and a converted party has "
                   "no encounter pending")

#: Words of `$4900`-`$52FF` no C64 save can source, written **zero** with the
#: reason each is nobody's (#26).  The mirror of :data:`WRITE_UNSOURCED` for
#: the character record, and of `HEADER_ZEROED` for the C64 save: a zero this
#: conversion can say why it wrote, rather than a byte belonging to whichever
#: party the template save was made by.
#:
#: `(address, words, why)`.  Everything in the variable space this table does
#: not name and no field writes reads zero in every genuine specimen anyway --
#: 2407 of the 2560 words -- so this list is only what a specimen has ever
#: been seen to hold.
#:
#: **What settles them is the running game, not the census.**  A save built
#: with every one of these zero loads, walks, fights and changes area under
#: DOSBox: `docs/117-save-conversion.md`, "A DOS save from nothing".  That is
#: the same bar #118 held the C64 direction's 192 header bytes to.
SAVGAM_UNSOURCED: tuple[tuple[int, int, str], ...] = (
    (0x49F0, 2, f"the previous square -- {ENGINE_REBUILT}"),
    (0x49FC, 1, "ECL0F's own scratch -- the one script of thirty that names "
                "it saves it, overwrites it and puts it back, so no value "
                "outlives a visit. The ports disagree on it besides: DOS "
                "reads 6 or 4 by area where the C64 reads 2"),
    (0x49FD, 2, "the two wall colours, which the arriving area's own ECL "
                "prologue writes on entry -- ECL00 opens `SAVE [$6E7D],"
                "[$49FD] / SAVE 10,[$49FE]` and ECL14 the same with 9, and "
                "the engine rewrote 10 to 9 by itself after loading a save "
                "moved into the Slums (#59)"),
    (0x4DB8, 1, DOS_ONLY), (0x4DC3, 1, DOS_ONLY), (0x4E0C, 1, DOS_ONLY),
    (0x4FA8, 1, DOS_ONLY), (0x4FC0, 2, DOS_ONLY), (0x4FC6, 1, DOS_ONLY),
    (0x4FC8, 1, DOS_ONLY),
    (0x4FD2, 2, ENGINE_REBUILT),
    (0x5079, 1, ENGINE_REBUILT),
    (0x507A, 4, DOS_ONLY + " -- and zero in all eleven indoor specimens. "
                "$507A-$507C are also the only three words of the array an "
                "**outdoor** save holds and an indoor one does not, and the "
                "engine writes them for itself out there: ten overland saves "
                "seeded with zero in all three came back holding values "
                "(#59), so zero is the measured value in both worlds rather "
                "than merely the one nobody objected to"),
    (0x507F, 2, DOS_ONLY),
    (0x5082, 1, ENGINE_REBUILT),
    (0x5200, 1, ENGINE_REBUILT),
    (0x5202, 6, ENCOUNTER_STATE),
    (0x5208, 1, ENGINE_REBUILT),
    (0x520A, 6, ENCOUNTER_STATE),
    (dos_savegame.ENCOUNTER_TEXT,
     dos_savegame.VAR_LAST - dos_savegame.ENCOUNTER_TEXT + 1,
     "the encounter and monster message buffers, one ASCII character per "
     "word -- a converted party is not being shouted at"),
)

#: The 274 bytes of the character table and the UI scratch after it that are
#: not the six filenames: 32 heap bytes inside each 41-byte entry, then 82
#: bytes of menu text.  Written zero.
#:
#: They are display scratch, and the evidence is what is in them: readable
#: fragments of the game's own menu words -- `Camp: ` in a Pool of Radiance
#: save, `Choose a FUNCTION` in a Silver Blades one -- and the engine rewrote
#: 55 of them on its own resave with nothing visible changing.  What made
#: that a measurement rather than a reading is the run: a save with all 274
#: zero loads and plays (`docs/117-save-conversion.md`, "A DOS save from
#: nothing").
PARTY_TABLE_SCRATCH = ("display scratch: 32 heap bytes after each filename "
                       "and 82 bytes of menu text, zeroed")

#: Saved-game words written to a value **measured in the running game**, as
#: `(address, value, why)`.  Distinct from `dos_savegame.SAVGAM_CONSTANTS`,
#: whose values are what every specimen holds: what is written here is what
#: the game was watched *doing something with*.
#:
#: `$49FF` was in :data:`SAVGAM_UNSOURCED` as "unnamed: 3 in every specimen,
#: and referenced by none of the thirty scripts", and zero there is what made
#: a converted party **faceless whatever its records said** (#57).  Measured,
#: DOSBox, `tools/portraitshot.py`: the same six converted records that draw
#: their portraits on the shipped saved game draw nothing on a from-nothing
#: one, and the difference bisects to this single word -- `$49FF = 0` no
#: portrait, `= 3` the portrait, `= 1` the portrait, everything else in the
#: file identical and the match against `HEAD<n>.DAX` pixel for pixel.  So it
#: gates the sheet portrait and is not a constant nobody reads.
#:
#: **3 rather than 1**, though both were seen to work: 3 is what all three
#: engine-written Pool of Radiance saved games hold, and a value the engine
#: writes is a better answer than a value that merely worked once.  The C64
#: holds 1 at the same address in fourteen of Donald's saves and `$81` in two
#: more, so the ports do not agree on it and it is not converted across.
#:
#: **What it means is still unknown** and this does not claim otherwise --
#: only what it does.
#: The word `savgam_writes` skips when no portrait crossed -- see there.
PORTRAIT_DRAWN = 0x49FF

SAVGAM_MEASURED: tuple[tuple[int, int, str], ...] = (
    (0x49FF, 3, "the sheet portrait is not drawn at all when this word is "
                "zero (#57), and 3 is what all three engine-written saved "
                "games hold. What it means is unknown"),
)

# ---------------------------------------------------------------------------
# The same account for Curse of the Azure Bonds and Secret of the Silver
# Blades (#299).  Every address below is the file's word index named Pool of
# Radiance's way -- `$49FC` is word `$FC`, which the later titles' scripts
# call `$4BFC` -- because that is how `dos_savegame.word_offset` and every
# census on this machine name them.  The VM's own address for a word above
# `$4CFF` is in `docs/163-dos-vm-address-map.md`: `$503F` is `$6E3F`.
# ---------------------------------------------------------------------------
#: Where the three engines' save routines mirror two engine globals into
#: the variable array just before writing it, read off each `GAME.OVR`
#: (Pool of Radiance `0x1FECE`, Curse `0x1F8D4`, Silver Blades `0x26AE0`):
#: word `$FC` takes a one-byte mode global and word `$FF` takes
#: `2 * flagA + flagB`.  The loaders put them straight back
#: (Silver Blades `0x26457`-`0x26482`).  Each later title's initialiser
#: sets the mode byte to 4 and both flags to 1 -- Curse `GAME.OVR:0xF9FA`,
#: `0xF9C6` and `0xF9CB`; Silver Blades `0x1078E`, `0x10752` and `0x10757`
#: -- and the fourteen Curse and Silver Blades containers on this machine,
#: shipped stubs included, all hold 4 and 3.  Pool of Radiance's initialiser
#: sets its mode byte to 1 and its containers read 6 or 4 by area, which is
#: why its own account zeroes `$49FC` and gates `$49FF` on the portrait.
LATER_MODE_WORD = 0x49FC
LATER_FLAGS_WORD = 0x49FF
#: `$6DE1` in the VM's own naming.  The routine at Curse `GAME.OVR:0x832F`
#: (Silver Blades `0x9295`) stores `$FF` into it and zeroes the two
#: rest-interruption words after it; it is compared against `$FF` at three
#: sites in each title.  Zero in the four shipped stubs, 255 in all six
#: played later-title containers, and 255 in every Pool of Radiance one,
#: which is why `dos_savegame.SAVGAM_CONSTANTS` already writes it there.
LATER_BEGUN_WORD = 0x4FE1

#: Words written to a value every engine-written container of the title
#: holds, per title, as `(address, value, why)`.  The mirror of
#: `dos_savegame.SAVGAM_CONSTANTS`, which is Pool of Radiance's; the sets
#: differ, and a writer that used Pool of Radiance's for Silver Blades would
#: put 16 and 1 into two words every Silver Blades container holds at zero.
SAVGAM_CONSTANTS_LATER: dict[str, tuple[tuple[int, int, str], ...]] = {
    "curse-of-the-azure-bonds": (
        (LATER_MODE_WORD, 4, "the engine's mode byte, mirrored into the "
                             "array by the save routine (GAME.OVR:0x1F8D4) "
                             "and set to 4 by the initialiser (0xF9FA); 4 "
                             "in all 8 Curse containers here"),
        (LATER_FLAGS_WORD, 3, "two engine flags packed as 2*a+b by the "
                              "save routine (GAME.OVR:0x1F8E2), both set to "
                              "1 by the initialiser (0xF9C6, 0xF9CB); 3 in "
                              "all 8 Curse containers here"),
        (LATER_BEGUN_WORD, 255, "written $FF by GAME.OVR:0x832F, the routine "
                                "that also zeroes the rest-interruption "
                                "words, and compared against $FF at three "
                                "sites; 255 in both played Curse containers "
                                "and in every Pool of Radiance one"),
        (0x506D, 16, "16 in both played Curse containers and in every Pool "
                     "of Radiance one, 0 in the four Curse stubs and in "
                     "every Silver Blades container; read at two GAME.OVR "
                     "sites (0x7791, 0x7BCC) that dispatch on it and "
                     "written by nothing in the overlay. PROBABLE: the "
                     "played value, from one party's two saves"),
        (0x50F6, 1, "1 in both played Curse containers and in every Pool of "
                    "Radiance one, 0 in the four Curse stubs and in every "
                    "Silver Blades container; no site in the overlay "
                    "touches it. PROBABLE: the played value, from one "
                    "party's two saves"),
    ),
    "secret-of-the-silver-blades": (
        (LATER_MODE_WORD, 4, "the engine's mode byte, mirrored into the "
                             "array by the save routine (GAME.OVR:0x26AE0) "
                             "and set to 4 by the initialiser (0x1078E); 4 "
                             "in all 6 Silver Blades containers here"),
        (LATER_FLAGS_WORD, 3, "two engine flags packed as 2*a+b by the "
                              "save routine (GAME.OVR:0x26AEE), both set to "
                              "1 by the initialiser (0x10752, 0x10757), "
                              "and unpacked again by the loader (0x26457); "
                              "3 in all 6 Silver Blades containers here"),
        (LATER_BEGUN_WORD, 255, "written $FF by GAME.OVR:0x9295, the routine "
                                "that also zeroes the rest-interruption "
                                "words, and compared against $FF at three "
                                "sites; 255 in all four played Silver "
                                "Blades containers, 0 in the two stubs"),
    ),
}

#: Words of the later titles' variable arrays that some engine-written
#: container holds live and this conversion writes **zero**, with the
#: reason each is nobody's -- the later-title `SAVGAM_UNSOURCED`.  The
#: evidence is per title: the six Curse containers (two played, four
#: stubs) and six Silver Blades ones (four played, two stubs) in
#: `~/wish-specimens/por-dos` and the archives, `tools/dossavcensus.py`.
#: Everything else in the array reads zero in every one of them and is
#: swept by `savgam_zeroes`.
LATER_SCRIPT_REFILLED = ("the arriving area's own script writes it from its "
                         "entry code, so no value outlives a load")
SAVGAM_UNSOURCED_LATER: tuple[tuple[int, int, str], ...] = (
    (0x49F0, 2, f"the previous square -- {ENGINE_REBUILT}; (3,12) in both "
                f"played Curse containers and in three Silver Blades ones, "
                f"0 in the fourth and in every stub"),
    (0x49FD, 2, f"the two wall colours -- {LATER_SCRIPT_REFILLED}: ECL01 "
                f"is one of the 19 Curse scripts that write $4BFD and the "
                f"25 that write $4BFE, and Silver Blades' scripts write "
                f"them 8 and 16 times (#192, #193). The C64 holds 8 where "
                f"DOS Curse holds 11, so the C64 byte is not the DOS one"),
    (0x4FA8, 1, "the training hall's class filter or level word, file "
                "offset 0xD51 (#249, #234): 20 in the three Silver Blades "
                "containers this project poked it to 20 in before the "
                "engine resaved them, 0 in every other later-title "
                "container -- our own poke read back, not a value the "
                "engine writes outside a hall"),
    (0x4FC6, 1, f"{DOS_ONLY}; $6DC6 in the VM's naming, read at two "
                f"GAME.OVR sites and written by none; 99 in the played "
                f"Curse containers, 80 in the played Silver Blades ones, 0 "
                f"in every stub"),
    (0x4FD2, 2, "the rest-interruption interval and chance, $6DD2/$6DD3 "
                "(docs/163-dos-vm-address-map.md): zeroed by the same "
                "routine that sets $4FE1 (GAME.OVR:0x833C, 0x8347) and "
                "written by the area script on ENCAMP; (1,100) in the "
                "played Curse containers, 0 in every Silver Blades one"),
    (0x503F, 1, "the ECL VM's division remainder: GAME.OVR:0x0B1F (Curse) "
                "and 0x0DD4 (Silver Blades) are the arithmetic handler's "
                "divide arm storing the remainder into VM word $6E3F, the "
                "one site in either overlay that writes it; nothing in "
                "either overlay reads it and no script of either title "
                "names it (tools/dosptrfields.py, tools/eclcensus.py). 4 "
                "in both played Curse containers, 0 everywhere else"),
    (0x5079, 3, f"the VM's own working registers $6E79-$6E7B, {ENGINE_REBUILT}"
                f"; no site in either overlay reaches them by "
                f"displacement, so they are written through the VM's own "
                f"store. 11/8/4 in a played Curse container, 7 in one "
                f"Silver Blades one, 0 in every stub"),
    (dos_savegame.ENCOUNTER_TEXT,
     dos_savegame.VAR_LAST - dos_savegame.ENCOUNTER_TEXT + 1,
     "the encounter and monster message buffers, one ASCII character per "
     "word -- WEAPONERS OF CORMYR in the played Curse containers, PRIVATE "
     "RESIDENCE in three Silver Blades ones -- and a converted party is "
     "not being shouted at"),
)


def savgam_constants(shape: "dos_savegame.DosSaveShape"
                     ) -> tuple[tuple[int, int, str], ...]:
    """The words written to a measured constant for this title."""
    if shape is dos_savegame.SAVE_POOL_OF_RADIANCE:
        return dos_savegame.SAVGAM_CONSTANTS
    return SAVGAM_CONSTANTS_LATER[shape.key]


def savgam_unsourced(shape: "dos_savegame.DosSaveShape"
                     ) -> tuple[tuple[int, int, str], ...]:
    """The words written zero with a reason, for this title."""
    if shape is dos_savegame.SAVE_POOL_OF_RADIANCE:
        return SAVGAM_UNSOURCED
    return SAVGAM_UNSOURCED_LATER


#: The three bytes at `+$E7`-`+$E9` of a later title's C64 header, copied
#: into words `$49E7`-`$49E9` (#299).  They cross the other way already:
#: `c64_save.SECRET_OF_THE_SILVER_BLADES.copied` takes all three from the
#: DOS save and Curse's takes two, because that title's scripts write them
#: at their heads and `DUNGEON` reads them.  Measured at the same index on
#: both ports: `1,1,1` in every played Silver Blades container and in both
#: Silver Blades C64 disks, `0,0,0` in every Curse container and disk.
#: Pool of Radiance zeroes them on the C64 side and its DOS containers hold
#: them at zero, so they stay in its sweep.
LATER_HEADER_COPIED = (0xE7, 3)


def retarget_reason(area: int) -> str | None:
    """Why this area cannot be a retarget target, or `None` if it can.

    Two kinds, both of which the C64 converter refuses in the other
    direction: an area this project has no row for, and one whose script
    picks its map at run time or loads none at all.  Unapproved wording.

    **The travel grid was a third and is not any more** (#190).  It was
    refused because no DOS retarget onto a travel window had ever been
    driven; one has now, and an outdoor area needs no `GEO` for the same
    reason `where.geos` is not consulted for it -- the overland loads none.
    `WILDERNESS`, the refusal Donald wrote for it, has gone with it.

    **An empty wallset triple is not a reason.**  New Phlan is the one area
    the C64 loads no `WALLSET` for, and a save retargeted there with all
    three words empty draws a view pixel-identical to one carrying DOS's own
    `(0, $FFFF, $FFFF)` -- `work/p60/run3`, Z0 against `run2`'s X3.
    """
    where = areas.area(area)
    if where is None:
        return (f"area {area} is not an area of Pool of Radiance, so there is "
                f"no map file and no script to name")
    if where.outdoors:
        return None
    if where.dynamic_geo or not where.geos:
        return UNSUPPORTED_LOCATION
    return None


def conversion_reason(area: int,
                      title: "str | None" = None) -> str | None:
    """Why a *conversion* cannot write this area, or `None` if it can.

    `title` is the game's title as `goldbox.areas` names it, Pool of
    Radiance's by default; a Curse or Silver Blades id is looked up in that
    title's own table (#299).

    **A conversion is not a retarget, and the difference is where the map
    comes from** (#276).  :func:`retarget_reason` refuses six areas because
    the caller names an area the party has never been in, so `goldbox/areas.py`
    is the only source for which `GEO` has to be resident and four of those
    areas load no map of their own while two pick theirs at run time.

    Converting a save, the resident map is **a word in the save being
    converted** -- `$49C5`, which `savgam_writes` now reads out of the C64
    save's own bytes.  So none of those six is a gap any more, and refusing
    them means refusing a party standing in the training hall, which is
    exactly the fault `#257 (A DOS save made in the training hall converts as
    though the party were in New Phlan)` fixed on the way in.

    What is left is the one refusal the save cannot answer: an area with no
    row, which has no `ECL<n>.DAX` to lift the script out of and no disk
    number to write.

    CONFIRMED for area 11, the training hall: a C64 save made there converts
    and DOS Pool of Radiance loads it, with the party standing in the school
    (`#276`, and `WISH-SPEC-por-c64-hall-resave` is the input).  PROBABLE for
    areas 3, 5, 8, 19 and 30 -- the same argument and no C64 save made in any
    of them exists on this machine to run it with.
    """
    title = title or areas.POOL_OF_RADIANCE
    where = areas.area_in(area, title)
    if where is None:
        return (f"area {area} is not an area of {title}, so there is "
                f"no map file and no script to name")
    return None


def _area_dax(area: int, template: "pathlib.Path | None",
              game: "str | pathlib.Path | None",
              title: "str | None" = None) -> tuple["areas.Area", int]:
    """The area's row and the DOS `ECL<n>.DAX` number that holds it.

    The number comes off the DOS game directory's own files
    (:func:`dos_dax_number`), because in Silver Blades the C64 side is not
    the DOS container (#299).  With no game directory -- the template
    experiment, Pool of Radiance only -- the table's side stands in, which
    is the same number for every Pool of Radiance and Curse row that has a
    block.  The two are compared where both are known, and a disagreement
    in a title where they are measured equal is refused rather than
    written.
    """
    title = title or areas.POOL_OF_RADIANCE
    why = conversion_reason(area, title)
    if why is not None:
        raise DosRecordError(why)
    where = areas.area_in(area, title)
    dax = dos_dax_number(game, area)
    if dax is None:
        if game:
            # Silver Blades' side is not its DOS number, so the file that
            # is missing cannot be named there; everywhere else it can.
            missing = ("ECL<n>.DAX"
                       if title == areas.SECRET_OF_THE_SILVER_BLADES
                       else ECL_DAX.format(dax=where.disk))
            raise DosRecordError(
                f"no {missing} in the game directory holds area {area}'s "
                f"script, and the game's own files are the only copy of it; "
                f"without it the save would carry somebody else's area")
        if title != areas.POOL_OF_RADIANCE:
            raise DosRecordError(
                f"a {title} conversion needs the DOS game directory, whose "
                f"ECL<n>.DAX files say which container holds area {area}")
        dax = where.disk
    elif title != areas.SECRET_OF_THE_SILVER_BLADES and dax != where.disk:
        raise DosRecordError(
            f"area {area} is in ECL{dax}.DAX where the area table puts it "
            f"on side {where.disk}; the two are measured equal in every "
            f"{title} row and this game directory disagrees")
    return where, dax


def _area_script(area: int, template: "pathlib.Path | None",
                 game: "str | pathlib.Path | None",
                 title: "str | None" = None, dax: "int | None" = None
                 ) -> bytes:
    """The area's own `ECL<n>.DAX` block, or a refusal saying why not.

    Three refusals, and all three used to be a warning with the party left
    standing on the template's square: an area with no legal answer, no game
    directory to read the script out of, and a container that does not hold
    the block.  Each of them ends with a save the party has never been in;
    the file loads, so nothing says so afterwards.

    **The first of the three is `conversion_reason` and not
    `retarget_reason`** (#276): this is the conversion path, whose party
    brings its own resident map with it.
    """
    if dax is None:
        _where, dax = _area_dax(area, template, game, title)
    data = _read_ecl_dax(template, game, dax)
    if data is None:
        raise DosRecordError(
            f"no {ECL_DAX.format(dax=dax)} in the game directory, and "
            f"the game's own files are the only copy of area {area}'s script; "
            f"without it the save would carry somebody else's area")
    try:
        return dos_savegame.dax_block(data, area)
    except dos_savegame.DosSaveError as e:
        raise DosRecordError(
            f"{ECL_DAX.format(dax=dax)} is unreadable: {e}") from e


def _note_word(report: "SaveReport", address: int, words: int,
               why: str, shape: "dos_savegame.DosSaveShape | None" = None
               ) -> None:
    """Provenance for `words` VM words, at the file offset they live at."""
    report.note(dos_savegame.word_offset(address, shape), 2 * words, why)


def c64_title(save0: bytes, title=None) -> games.Game:
    """Which C64 title a `SAVEDGAME0` payload belongs to.

    `title` is a `goldbox.games.Game`, its key, or None.  **A 7424-byte
    payload is refused without one**: Curse of the Azure Bonds and Secret
    of the Silver Blades write the same size, their DOS containers differ
    (13149 against 5469 bytes, one staging a script and one not), and
    guessing between them would build a save the wrong engine loads
    (#299).  Pool of Radiance's 7168 bytes name themselves.
    """
    if title is not None:
        game = games.by_key(getattr(title, "key", title))
        if len(save0) != game.save_size:
            raise DosRecordError(
                f"a {game.title} save is {game.save_size} bytes; this is "
                f"{len(save0)}")
        return game
    if len(save0) == games.POOL_OF_RADIANCE.save_size:
        return games.POOL_OF_RADIANCE
    same = [g.title for g in games.GAMES if g.save_size == len(save0)]
    raise DosRecordError(
        f"a {len(save0)}-byte C64 save is one of {', '.join(same) or 'no'} "
        f"titles; say which with `title=`")


def savgam_writes(savgam: bytearray, report: "SaveReport", save0: bytes,
                  slot: str, count: int, script: "bytes | None", *,
                  portraits: bool = False, game=None,
                  dax: "int | None" = None) -> None:
    """Write everything a C64 save sources into a `SAVGAM<slot>.DAT` buffer.

    `savgam` is modified in place and every byte written gets a line in
    `report.sources`, so what is *not* written is countable afterwards --
    which is the whole of how "no template" is checked rather than asserted.

    `script` is the party's own area's `ECL<n>.DAX` block, and there is no
    path here without one: the load path reads the staged script and dies in
    `Load3DMap` when it is somebody else's (#60), and a conversion that
    cannot read the game's files has nothing to put there but a stranger's
    area.  The caller refuses instead.  **Silver Blades stages none**, and
    passes None.

    **`game` is the C64 title** (`goldbox.games.Game`, or None for Pool of
    Radiance), and it chooses both ends of the join (#299): the C64 offsets
    come from `c64_save.container_for(game)` and the DOS ones from
    `dos_savegame.save_shape_for(game.key)`, whose size `savgam` must
    already be.  `dax` is the DOS `ECL<n>.DAX` number holding the area,
    from `_area_dax`; with none the area table's side stands in, which is
    right for Pool of Radiance and Curse and wrong for Silver Blades.

    **A party on the travel grid takes a different value in four places**
    (#190), and everything else about the write is the same: `$49C5` = 0
    rather than the resident GEO, the wallset triple is the overland's own
    measured `(0, $FFFF, $FFFF)` rather than the C64 cache's, the square is
    the travel pair at `$49C3`/`$49C4`, and `$49E6` = 0 is what boots the
    engine into travel mode.  `put_tail_state` takes the fifth.

    **`$49C5` and `$49F2` are two different words, and each is read from its
    own address in the C64 save** (#276).  `$49F2` is the area, always;
    `$49C5` is the resident map, and the two part company for an area whose
    script loads none of its own, such as the training hall -- writing the
    area id into both there names `GEO0B`, a map no script loads.  This used
    to derive `$49C5` from `area`, which is `retarget`'s own default and is
    right for the areas that load their own map and wrong for the six
    `retarget_reason` refuses before this can run.
    """
    game = games.by_key(getattr(game, "key", game)) if game else \
        games.POOL_OF_RADIANCE
    container = c64_save.container_for(game)
    shape = dos_savegame.save_shape_for(game.key)
    later = shape is not dos_savegame.SAVE_POOL_OF_RADIANCE
    if len(savgam) != shape.size:
        raise DosRecordError(
            f"a {shape.title} saved game is {shape.size} bytes; the buffer "
            f"is {len(savgam)}")
    area = save0[container.current_script]
    geo = save0[container.current_geo]
    where = areas.area_in(area, game.title)
    if dax is None:
        dax = where.disk
    x, y, facing = save0[container.position:container.position + 3]
    indoors = not where.outdoors

    # Outdoors the C64's own cache slots 15-17 read `$FF` -- the travel grid
    # loads no `WALLSET` on either port -- which would make the triple
    # `($FFFF, $FFFF, $FFFF)` where every engine-written outdoor DOS save
    # holds `(0, $FFFF, $FFFF)`.  So the measured overland value is written
    # instead of the empty read, and `OUTDOOR_WALLSET` carries the evidence.
    wallset = (c64_wall_triple(save0, container) if indoors
               else dos_savegame.OUTDOOR_WALLSET)
    dos_savegame.retarget(savgam, area=area, dax=dax,
                          wallset=wallset, script=script,
                          outdoors=not indoors, geo=geo, shape=shape)
    report.note(shape.head, shape.dax_bytes,
                f"the DAX container number, {dax}, for area "
                f"{area} ({where.name or where.ecl})"
                + ("" if dax == where.disk else
                   f" -- the DOS ECL{dax}.DAX that holds the block, not "
                   f"the C64 side {where.disk} (#299)"))
    _note_word(report, dos_savegame.AREA, 1,
               "the resident GEO, the C64's own $49C5" if indoors else
               "zero: the overland names no GEO, which is what an outdoor "
               "DOS save holds here in 10 of 10 -- and it is not the C64's "
               "own $49C5, which outdoors holds the SQRDATA number (#59)",
               shape)
    _note_word(report, dos_savegame.SCRIPT, 1, "the area's script id", shape)
    _note_word(report, dos_savegame.DISK, 1,
               "the DAX container number again -- the geo load reads "
               "this word and not the header byte (#59)", shape)
    wallset_why = (
        "the wallset triple, from the C64 loaded-files cache "
        "slots 15-17, which carry the same three numbers" if indoors
        else "the overland wallset triple (0,$FFFF,$FFFF), which the "
        "engine writes for itself out there -- it replaced a seeded "
        "(1,5,9) three times of three, and no outdoor load reads it "
        "(#59, #190)")
    if shape.unnamed:
        report.note(shape.wall_block, shape.unnamed,
                    f"the twelve-byte block inside the square block: "
                    f"{wallset_why}, interleaved with its wall-index map "
                    f"(#253, #299)")
    else:
        _note_word(report, dos_savegame.WALLSET, 3, wallset_why, shape)
        _note_word(report, dos_savegame.WALLMAP, 3,
                   "the wall-index map that goes with the triple", shape)
    if shape.script_buffer is not None:
        start, end = shape.script_buffer
        report.note(start, end - start,
                    f"the area's own ECL{dax}.DAX block from byte "
                    f"{dos_savegame.ECL_HEADER} on, then zero to the end of "
                    f"the buffer -- which is what an engine-written save "
                    f"holds past its script's end, 6 of 6 (#59)")
    dos_savegame.put_word(savgam, dos_savegame.INDOORS, 1 if indoors else 0,
                          shape)
    _note_word(report, dos_savegame.INDOORS, 1,
               "indoors" if indoors else "outdoors -- 0 boots the engine "
               "into travel mode", shape)

    if indoors:
        dos_savegame.put_position(savgam, x, y, facing, shape)
        report.note(shape.pos_x, 3,
                    f"the square ({x},{y}) facing {facing}, the C64's own "
                    f"facing doubled")
    else:
        tx, ty = save0[container.travel_position:container.travel_position + 2]
        dos_savegame.put_travel_square(savgam, tx, ty, shape)
        _note_word(report, dos_savegame.TRAVEL_X, 2,
                   f"the travel square ({tx},{ty}), window-local, the C64's "
                   f"own $49C3/$49C4 -- the same pair at the same address on "
                   f"both ports (#47, #59)", shape)
        # 12801/12802 are the square the party last stood on **indoors**,
        # frozen on both ports the moment it reached the grid -- C64
        # `DUNGEON $1A3C` copies `$C04B` into `$49C0` only while `$49E6` is
        # set, and DOS freezes 12801/12802 the same way.  So the C64's own
        # stale pair is what belongs in the DOS one: same field, same
        # meaning, and nothing reads either out here.
        #
        # 12803 is the exception and is the one field this conversion
        # **cannot** carry outdoors.  See OUTDOOR_FACING.
        dos_savegame.put_position(savgam, x, y, OUTDOOR_FACING, shape)
        report.note(shape.pos_x, 2,
                    f"the stale indoor square ({x},{y}) the party left the "
                    f"grid on, the C64's own $49C0/$49C1 -- frozen on both "
                    f"ports out here and read by neither")
        # The note keeps the addresses; the player-facing copy of this
        # sentence is gone (#248, and see OUTDOOR_FACING above).
        report.note(shape.pos_facing, 1, OUTDOOR_FACING_WHY)
    dos_savegame.put_tail_state(savgam, indoors=indoors, shape=shape)
    where_stood = "indoors" if indoors else "outdoors"
    if later:
        report.note(shape.tail_scratch, 4,
                    f"the four tail bytes, {dos_savegame.LATER_TAIL_ZERO}")
    else:
        report.note(dos_savegame.SCRATCH_BYTE, 4,
                    f"the four tail bytes: 12804 at the value an "
                    f"engine-written save of a party standing {where_stood} "
                    f"has held (the engine rewrites it anyway), the low "
                    f"byte of $5200, the view mode from $49E6, and the "
                    f"constant {dos_savegame.TAIL_CONSTANT}")
    dos_savegame.put_party_size(savgam, count, shape)
    _note_word(report, dos_savegame.PARTY_SIZE, 1, f"the party size, {count}",
               shape)
    report.note(shape.party_size_byte, 1, f"the party size again, {count}")

    dos_savegame.put_character_files(savgam, slot, shape)
    for n in range(dos_savegame.PARTY_ENTRIES):
        report.note(
            shape.party_table + n * dos_savegame.PARTY_ENTRY,
            dos_savegame.PARTY_NAME_LEN,
            f"CHRDAT{slot.upper()}{n + 1}, which is what the engine loads "
            f"the party from -- not the slot letter at the LOAD menu (#59)")

    # The quest flags: the C64 byte at the same ECL address, widened to a
    # word.  The window is the container's own, because where the page
    # ends is per title -- Pool of Radiance stops at `$4AF8` with its wall
    # triples after it, and the later titles use the page to `$4AFF`
    # (`quest_flags`, #193).  A later-title payload offset is a word index
    # directly: `+$120` is word `$120`, which Pool of Radiance calls `$4A20`.
    first, size = container.quest_flags
    for i in range(size):
        dos_savegame.put_word(savgam, dos_savegame.VAR_BASE + first + i,
                              save0[first + i], shape)
    _note_word(report, dos_savegame.VAR_BASE + first, size,
               "a quest flag: the C64 byte at the same ECL address, widened "
               "to a word", shape)
    for addr in SHARED_SCRATCH:
        dos_savegame.put_word(savgam, addr, save0[addr - SAVE0_BASE], shape)
        _note_word(report, addr, 1,
                   "script scratch: the C64 byte at the same ECL address, "
                   "widened to a word", shape)
    if later:
        first, size = LATER_HEADER_COPIED
        for i in range(size):
            dos_savegame.put_word(savgam, dos_savegame.VAR_BASE + first + i,
                                  save0[first + i], shape)
        _note_word(report, dos_savegame.VAR_BASE + first, size,
                   "a per-area byte the arriving script writes and DUNGEON "
                   "reads: the C64 byte at the same ECL address, widened to "
                   "a word -- 1,1,1 in every Silver Blades container and "
                   "disk, 0,0,0 in every Curse one (#193, #299)", shape)

    digits = [save0[container.clock + i]
              for i in range(dos_savegame.CLOCK_DIGITS)]
    dos_savegame.put_clock(savgam, digits, shape)
    _note_word(report, dos_savegame.CLOCK, dos_savegame.CLOCK_DIGITS,
               "a clock digit, the C64's own byte at the same address", shape)

    for address, value, why in savgam_constants(shape):
        dos_savegame.put_word(savgam, address, value, shape)
        _note_word(report, address, 1, f"a documented constant: {why}", shape)

    if later:
        # `$49FF` is in the title's own constants above -- the later
        # titles draw no sheet portrait (`draws_sheet_portrait`), so the
        # word is the engine's two flags and not a portrait gate.
        return
    for address, value, why in SAVGAM_MEASURED:
        if address == PORTRAIT_DRAWN and not portraits:
            # **Only when a portrait actually crossed.** Every specimen that
            # holds 3 here also holds a real menu position in its records;
            # "drawing enabled, position 0" is a combination nobody has run,
            # and a conversion with no game directory produces exactly that
            # -- `portrait_tables` returns nothing and both bytes stay zero.
            # Writing 3 there would be inventing a state rather than
            # reproducing a measured one (#57).
            continue
        dos_savegame.put_word(savgam, address, value, shape)
        _note_word(report, address, 1, f"measured in the running game: {why}",
                   shape)


def savgam_zeroes(savgam: bytearray, report: "SaveReport",
                  shape: "dos_savegame.DosSaveShape | None" = None) -> None:
    """Account for every byte of the file :func:`savgam_writes` left zero.

    Called only when the buffer started zeroed, because that is the only case
    in which "not written" and "written zero" are the same thing.  Three
    groups: the words no C64 save can source, named one at a time in
    :data:`SAVGAM_UNSOURCED` (:data:`SAVGAM_UNSOURCED_LATER` for Curse and
    Silver Blades); the character table's heap scratch; and the remainder of
    the variable space, which reads zero in every genuine specimen of the
    title.
    """
    shape = dos_savegame.save_shape_for(
        len(savgam) if shape is None else shape)
    for address, words, why in savgam_unsourced(shape):
        _note_word(report, address, words, f"zeroed -- {why}", shape)
    for n in range(dos_savegame.PARTY_ENTRIES):
        at = (shape.party_table + n * dos_savegame.PARTY_ENTRY
              + dos_savegame.PARTY_NAME_LEN)
        report.note(at, dos_savegame.PARTY_ENTRY - dos_savegame.PARTY_NAME_LEN,
                    PARTY_TABLE_SCRATCH)
    report.note(shape.size - dos_savegame.UI_SCRATCH,
                dos_savegame.UI_SCRATCH, PARTY_TABLE_SCRATCH)
    # The sweep, and the one claim here that rests on a census rather than on
    # a run: these words read zero in all four engine-written containers on
    # this machine, which is 2407 of the 2560 and the same count #59 got from
    # its eleven **indoor** specimens.  Over all twenty-one, ten of them
    # overland, it got 2402: the five words in the difference are `$49C3`,
    # `$49C4` and `$507A`-`$507C`, and every one of them is written or
    # declared above -- so an **outdoor** save this conversion writes is
    # covered by the same sweep and there is no sixth word (#59, #190).
    # An earlier note here said six, on three overland specimens that lived
    # under `work/` and are gone; the sixth belonged to a specimen nobody can
    # re-read.  `tools/dossavcensus.py` re-takes the count in a second, and
    # what catches a word this line is wrong about is
    # `test_every_nonzero_word_a_real_saved_game_holds_is_written_or_declared`,
    # which reads the player's own saves.
    # The later titles' sweep rests on the same kind of count over their own
    # containers: 2516 of 2560 words are zero in every Curse and Silver
    # Blades container on this machine (`tools/dossavcensus.py --title`),
    # and every one of the live words is written or declared above (#299).
    rest = [i for i in range(shape.var_offset,
                             shape.var_offset + 2 * shape.var_words)
            if i not in report.sources]
    for i in rest:
        report.sources[i] = (
            f"zeroed: this word reads zero in every genuine {shape.title} "
            f"specimen on this machine, and nothing in a C64 save "
            f"corresponds to it")


def write_dos_save(save0: bytes, save1: bytes | None,
                   template: str | pathlib.Path | None,
                   out: str | pathlib.Path,
                   slot: str = "A",
                   game: str | pathlib.Path | None = None,
                   title=None) -> "SaveReport":
    """Write a C64 save into a DOS save directory.

    `save0` and `save1` are the C64 `SAVEDGAME0`/`SAVEDGAME1` payloads; `out`
    is where the new files go.  `game` is the DOS game directory, the one
    holding `ECL<n>.DAX`, and it is **not optional in practice**: the party's
    own area's script has to be staged in the save or the game exits to DOS
    on load, and the game's files are the only copy of it.

    **`title` is the C64 title** -- a `goldbox.games.Game`, its key, or
    None for Pool of Radiance -- and it chooses both ends of the join
    (#299): the payload is read through `c64_save.container_for(title)`
    and the DOS file is built to `dos_savegame.save_shape_for(title)`, so a
    Curse party comes out as a 13149-byte `SAVGAM<slot>.DAT` with its
    script staged and a Silver Blades one as 5469 bytes with none.  A
    7424-byte payload is refused without it, because Curse and Silver
    Blades are the same size on the C64 and different files on DOS.

    **`template` is `None` for a conversion**, and :func:`new_dos_save` is
    the call that says so.  Passing a DOS save directory builds the file on
    top of that save's `SAVGAM<slot>.DAT` instead, which is what this used to
    do always and is now only for an experiment that wants to vary one region
    against a known-good file: every byte the conversion does not write then
    belongs to a different party in a different place, and
    `SaveReport.unwritten` counts them.

    With no template the buffer starts at 13137 zero bytes and every one of
    them is accounted for -- written from the C64 party, written to a
    measured constant, or written zero with the reason it is nobody's in
    :data:`SAVGAM_UNSOURCED`.

    **The slot is cleared first.**  `CHRDAT<slot>1`-`6` and their `.ITM` and
    `.SPC` are removed from `out` before anything is written, so a party
    smaller than the one converted here last time does not arrive with the
    remainder of that one still in it (#68).  Only those eighteen names are
    touched; whatever else `out` holds is the user's.

    What is then written: `CHRDAT<slot><n>.SAV` for each character and its
    `.ITM` **only when the character carries something** -- a zero-length
    `.ITM` is not how the engine says "no items", it is how it says "one item,
    from whatever the heap held" (`ITM_OMITTED_WHEN_EMPTY`, #62) -- its `.SPC`
    **only when the character has an innate effect** (#61), and
    `SAVGAM<slot>.DAT` copied from the template and rewritten:

    * the quest flags, from the C64 bytes -- the two ports index them by the
      same ECL address;
    * **the script scratch** (#59), the same copy for the same reason:
      `$49EB` and the whole `$4A00`-`$4A1F` window, which
      `docs/141-dos-savegame.md` grades CONFIRMED as the same fields on both
      ports.  What they mean is still unknown; where they come from is not;
    * **the clock** (#67), the same unconditional copy: six digit words at
      `$49C6`-`$49CB`, which are the C64's own six bytes at its own addresses;
    * **the party size** (#67), into both the word at `$503E` and byte 12808;
    * **the place** (#60), always and not only when it differs from the
      template's: every write `dos_savegame.RETARGET_WRITES` lists, including
      the area's own script lifted out of `ECL<n>.DAX`.

    **An area it cannot write, it refuses.**  There is no fallback to the
    template's square any more: a party that arrives standing where a
    stranger stood, carrying that stranger's script, is wrong data that looks
    right.  Donald's ruling on the same question in the other direction,
    2026-08-27: *"We should never attempt to write a save file if we don't
    have the game disks and we need them.  That would mean making up data,
    which we will not do."*
    """
    from .items import items_for_slot
    from .savegame import SaveGame0, SaveGame1

    template = pathlib.Path(template) if template is not None else None
    out = pathlib.Path(out)
    if template is not None and out.resolve() == template.resolve():
        raise DosRecordError(
            "the output directory is the template; the template is read-only")
    out.mkdir(parents=True, exist_ok=True)

    # `slot` is interpolated straight into filenames and into the paths this
    # function *deletes*, and `pathlib`'s `/` splits an embedded separator into
    # components -- so a slot of `../../x` would unlink outside `out` entirely.
    # It is also written into the save as `slot.upper()` while the files on
    # disk take it verbatim, which on a case-insensitive filesystem produces a
    # save naming `CHRDATA1` beside a file called `CHRDATa1`. One check closes
    # both: the engine's own slots are a single letter.
    if len(str(slot)) != 1 or not str(slot).isalpha():
        raise DosRecordError(
            f"a save slot is a single letter, not {slot!r}")

    c64 = c64_title(save0, title)
    container = c64_save.container_for(c64)
    shape = dos_savegame.save_shape_for(c64.key)
    sg = SaveGame0.from_bytes(bytes(save0), c64)
    if c64.roster_in_payload:
        # Every later title keeps the roster inside the one payload, and
        # `load_save` hands back a `SaveGame1` over that page; a caller
        # passing `save1` for such a title has a second copy of the same
        # bytes, so the payload's own page is the one read.
        sg1 = SaveGame1(sg.roster_page(), c64)
    else:
        sg1 = SaveGame1(bytes(save1), c64) if save1 is not None else None
    party = sg.characters
    if len(party) > 6:
        raise DosRecordError(
            f"a DOS save holds six characters; this save has {len(party)}")

    # Read the template's save, and the area's script, before anything in
    # `out` is touched: a missing `SAVGAM<slot>.DAT` or an area with no legal
    # answer must fail with the slot still as the last conversion left it,
    # not half cleared.
    savgam = bytearray(shape.size) if template is None else \
        bytearray((template / f"SAVGAM{slot}{shape.suffix}").read_bytes())
    if len(savgam) != shape.size:
        raise DosRecordError(
            f"the template's SAVGAM{slot}{shape.suffix} is {len(savgam)} "
            f"bytes, not the {shape.size} a {shape.title} save is")
    c64_area = save0[container.current_script]
    where, dax = _area_dax(c64_area, template, game, c64.title)
    # Silver Blades stages no script (`script_bytes` = 0) and reloads the
    # area's from `ECL<dax>.DAX` on load; the number is all it needs.
    script = (_area_script(c64_area, template, game, c64.title, dax)
              if shape.script_buffer is not None else None)

    # The unit a conversion overwrites is the *slot*, not the characters this
    # party happens to fill.  Converting one character into a directory that
    # held six left `CHRDAT<slot>2`-`6` behind, and the engine loads the party
    # from the six filenames in `SAVGAM<slot>.DAT` (#59), so it read five
    # strangers back (#68).  Only the engine's own six names are removed, by
    # enumeration rather than by glob: nothing else in `out` is ours to touch.
    # **Every character is converted before anything in `out` is touched.**
    # The clear below removes the slot's six names, and a `write()` that
    # raises partway through the party -- `_encode` refuses a field whose
    # length is wrong -- would otherwise leave characters 1..N-1 replaced,
    # N..6 deleted and gone, and `SAVGAM<slot>.DAT` still naming all six. That
    # is #68's own failure reached through the write path instead of the
    # leftover path, and it is worse, because the save then names files that
    # are not there.
    report = SaveReport(total=shape.size)
    # The sheet portrait crosses through the creation menu's own tables, and
    # they are in the game's own `START.EXE` -- the directory this function
    # already needs for the party's area script (#57).  A directory that
    # cannot answer for them costs the party its faces and nothing else, so
    # it is reported rather than raised.  **Only Pool of Radiance draws
    # one** (`draws_sheet_portrait`, #300): a Curse or Silver Blades party
    # has no face to lose, so nothing is looked up and nothing is said.
    faces, why_not = (portrait_tables(game) if draws_sheet_portrait(c64.key)
                      else (None, ""))
    if faces is None and why_not:
        # A warning rather than a `converted` line: `converted` is what *did*
        # cross, and `editor/exports.py`'s `losses` does not read it, so the
        # one sentence saying why every character lost its face would not
        # have reached the person doing the conversion.
        report.warnings.append(
            f"no character's sheet portrait crossed, because {why_not}")
    built = []
    for char_slot in party:
        block = sg1.roster(char_slot.index) if sg1 is not None else None
        inv = [i.raw for i in items_for_slot(bytes(save0), char_slot.index)]
        char = c64_codec.read(char_slot.record, roster=block, inventory=inv,
                              game=c64, source=f"C64 slot {char_slot.index}")
        rec, itm, spc, one = write(char, portraits=faces)
        built.append((char, rec, itm, spc, one, char_slot))
    record_shape = write_shape(built[0][0]) if built else shape_for(c64.key)
    suffixes = (".SAV", record_shape.item_suffix, record_shape.effect_suffix)

    # **The two ports list the party from opposite ends** (#101).  The C64
    # displays the highest occupied slot first -- its own `ENCAMP > ALTER >
    # ORDER` asks `WHO TAKES POSITION #1?` over a list headed by the character
    # in slot 5 -- and DOS displays `CHRDAT<slot>1` first.  So the file order
    # is the reverse of the slot order, and `party_order` at `0x0BF`, which
    # is 0-5 in file order in every DOS specimen, is renumbered to match
    # rather than left as the C64's slot index.
    #
    # **That renumbering is now what the DOS loader would have done anyway**
    # (#305): the byte is the character's combat-icon slot, the loader hands
    # out the lowest free one of eight as it reads the six filenames in order,
    # and a party with no NPC therefore comes out numbered by file position.
    # So this line stops the record disagreeing with itself before the game
    # ever sees it, rather than deciding anything the game will keep.
    built.reverse()
    order = FIELDS_BY_NAME_FOR[record_shape.key]["party_order"].offset
    for position, entry in enumerate(built):
        record = bytearray(entry[1])
        record[order] = position
        built[position] = (entry[0], bytes(record)) + entry[2:]

    # The unit a conversion overwrites is the *slot*, not the characters this
    # party happens to fill.  Converting one character into a directory that
    # held six left `CHRDAT<slot>2`-`6` behind, and the engine loads the party
    # from the six filenames in `SAVGAM<slot>.DAT` (#59), so it read five
    # strangers back (#68).  Only the engine's own six names are removed, by
    # enumeration rather than by glob: nothing else in `out` is ours to touch.
    cleared = _clear_slot(out, slot, suffixes)
    if cleared:
        report.converted.append(
            f"slot {slot} was already written here: {cleared} stale "
            f"CHRDAT{slot}<n> file(s) from the previous party removed")
    for n, (char, rec, itm, spc, one, char_slot) in enumerate(built, start=1):
        stem = out / f"CHRDAT{slot}{n}"
        stem.with_suffix(".SAV").write_bytes(rec)
        # A character carrying nothing gets **no `.ITM` file at all**, and an
        # empty one is not the same thing: the engine reads a zero-length
        # `.ITM` as one item of whatever the heap held, draws it on the sheet
        # (`WEAPON 254 PASSS`), and writes it into the save on the next resave.
        # See ITM_OMITTED_WHEN_EMPTY.  Nothing is unlinked here: the slot was
        # cleared above, so "not written" and "not present" are the same.
        # The suffix is the title's own: `.ITM`, `.SWG` or `.STF` (#113).
        if itm:
            stem.with_suffix(record_shape.item_suffix).write_bytes(itm)
        # A character with no innate effects gets no `.SPC`, which is what the
        # engine's own save writes for one with nothing running (#61): every
        # human in the archives' twelve saved parties has no file at all.
        if spc:
            stem.with_suffix(record_shape.effect_suffix).write_bytes(spc)
        who = char.get("name", f"slot {char_slot.index}")
        report.dropped.extend(d for d in one.dropped
                              if d not in report.dropped)
        report.warnings.extend(f"{who}: {w}" for w in one.warnings)

    savgam_writes(savgam, report, save0, slot, len(party), script,
                  portraits=bool(faces), game=c64, dax=dax)
    if template is None:
        savgam_zeroes(savgam, report, shape)
    x, y, facing = save0[container.position:container.position + 3]
    hour, minute, day, month = dos_savegame.clock(bytes(savgam))
    # Where the party is standing, said in the terms of the world it is in.
    # Outdoors `$49C0`/`$49C1` are the frozen square it left the grid on, so
    # a report that printed them would name a place the party is not, and the
    # world coordinate is what the game's own status line shows.
    if where.outdoors:
        tx, ty = dos_savegame.travel_square(bytes(savgam))
        world = tx + dos_savegame.WINDOW_X_OFFSET.get(c64_area, 0)
        stood = (f"on the travel grid at ({tx},{ty}), window-local -- world "
                 f"({world},{ty}) on the status line")
    else:
        stood = f"at ({x},{y}) facing {facing}"
    script_line = (f", including the area's own script out of "
                   f"{ECL_DAX.format(dax=dax)}" if script is not None else
                   f"; the script is not staged, {shape.title} reloads it "
                   f"from {ECL_DAX.format(dax=dax)}")
    report.converted.extend((
        f"the place: area {c64_area}, {where.name or where.ecl}, {stood} -- "
        f"every write dos_savegame.RETARGET_WRITES names{script_line}",
        f"the party's filenames: CHRDAT{slot.upper()}1-"
        f"{dos_savegame.PARTY_ENTRIES}, which is what the engine loads from",
        f"quest flags: {container.quest_flags[1]} C64 bytes widened to "
        f"words at the same ECL addresses",
        f"the script scratch: $49EB and $4A00-$4A1F, {len(SHARED_SCRATCH)} "
        f"more C64 bytes widened to words at the same ECL addresses",
        f"the clock: {hour}:{minute:02d}, day {day} month {month} -- the "
        f"C64's own six digit bytes at $49C6-$49CB",
        f"the party size, {len(party)}, into both $503E and byte "
        f"{shape.party_size_byte}",
    ))

    # What is left is what the file owes to somebody else's save, and it is
    # empty when there was no template.  `new_dos_save` refuses on it rather
    # than returning a save with a stranger's byte in it (#26).
    report.unwritten = [i for i in range(shape.size)
                        if i not in report.sources]
    for i in report.unwritten:
        report.sources[i] = (
            f"{report.address(i)}: not converted -- left as the template "
            f"had it")
    (out / f"SAVGAM{slot}{shape.suffix}").write_bytes(bytes(savgam))
    return report


def _clear_slot(out: pathlib.Path, slot: str,
                suffixes: Sequence[str]) -> int:
    """Remove `CHRDAT<slot>1`-`6` and their siblings; return how many.

    Only the engine's own six names in the title's own suffixes, by
    enumeration rather than by glob: nothing else in `out` is ours to touch
    (#68).
    """
    cleared = 0
    for n in range(1, dos_savegame.PARTY_ENTRIES + 1):
        stale = out / f"CHRDAT{slot}{n}"
        for suffix in suffixes:
            path = stale.with_suffix(suffix)
            if path.exists():
                path.unlink()
                cleared += 1
    return cleared


def new_dos_save(save0: bytes, save1: bytes | None,
                 out: str | pathlib.Path, slot: str,
                 game: str | pathlib.Path, title=None) -> "SaveReport":
    """A whole DOS save from a C64 one, owing nothing to another save (#26).

    The mirror of :func:`new_save`, and the same refusal: `game` is the DOS
    game directory the area's own `ECL<n>.DAX` is read out of, there is no
    default for it, and a conversion that cannot read it would have to invent
    an area rather than write the one the party is standing in.

    `title` is the C64 title, as :func:`c64_title` takes it; a Curse or
    Silver Blades payload needs it, and the whole save then comes out in
    that title's own container -- 13149 bytes with the script staged, or
    5469 without (#299).

    Returns the report, whose `unwritten` is empty.  A byte here with no
    source is a byte written zero by accident instead of by measurement, and
    the difference between those two is invisible in the file.
    """
    # **Built somewhere else first, and moved in only once it is known
    # good.**  The refusal below used to fire *after* `write_dos_save` had
    # already cleared the slot and written all seven files, so a caller who
    # hit it was left with exactly the save this function exists to refuse --
    # a stranger's bytes on disk, with nothing about the directory saying so.
    # The sibling refusal in `_area_script` gets this right by firing before
    # anything is written; this one could not, because the count it refuses on
    # is only known at the end.  So the write goes to a staging directory on
    # the same filesystem and `out` is not touched at all unless the count is
    # zero.
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    staging = pathlib.Path(tempfile.mkdtemp(prefix=f".wish-{slot}-", dir=out))
    try:
        report = write_dos_save(save0, save1, None, staging, slot, game=game,
                                title=title)
        if report.unwritten:
            raise DosRecordError(
                f"{len(report.unwritten)} bytes of the saved game have no "
                f"source and were left zero by accident rather than by "
                f"measurement; the first is "
                f"{report.address(report.unwritten[0])}")

        # The slot is the unit a conversion overwrites, and the clearing has
        # to happen here rather than in `write_dos_save`, which only ever saw
        # the empty staging directory.  Same enumeration, same reason (#68),
        # in the title's own suffixes.
        record_shape = shape_for(c64_title(save0, title).key)
        cleared = _clear_slot(
            out, slot, (".SAV", record_shape.item_suffix,
                        record_shape.effect_suffix))
        if cleared:
            report.converted.append(
                f"slot {slot} was already written here: {cleared} stale "
                f"CHRDAT{slot}<n> file(s) from the previous party removed")
        for built in sorted(staging.iterdir()):
            shutil.move(str(built), str(out / built.name))
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return report


def _read_ecl_dax(template: "pathlib.Path | None",
                  game: str | pathlib.Path | None, dax: int) -> bytes | None:
    """`ECL<n>.DAX` from the game directory, or from beside the template."""
    name = ECL_DAX.format(dax=dax)
    if game:
        roots = [pathlib.Path(game)]
    elif template is not None:
        roots = [template, template.parent]
    else:
        return None
    for root in roots:
        path = root / name
        if path.is_file():
            return path.read_bytes()
    return None


if __name__ == "__main__":  # pragma: no cover - convenience
    import sys

    from .yaml_io import to_yaml

    if len(sys.argv) < 3:
        print("usage: python3 -m goldbox.dos <dos-save-dir> <slot> [game.d64]")
        raise SystemExit(2)
    print(to_yaml(export_party(sys.argv[1], sys.argv[2],
                               sys.argv[3] if len(sys.argv) > 3 else None)))
