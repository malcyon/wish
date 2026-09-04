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
from typing import Any, Sequence

from . import areas, c64_codec, dos_savegame, neutral, traits
from .c64_codec import Report
from .dos_layout import (
    CLASS_NUMBERS,
    EFFECT_SIZE,
    FIELDS_BY_NAME,
    FIELDS_BY_NAME_FOR,
    ITEM_FIELDS_BY_NAME,
    ITEM_SIZE,
    LAYOUT,
    POOL_OF_RADIANCE,
    RECORD_SIZE,
    SPELLBOOK_SPELLS,
    DosShape,
    DosShapeError,
    shape_for,
)
from .layout import Confidence, Field, Kind
from .neutral import NeutralCharacter, Provenance
from .portraits import PortraitError, PortraitTables, tables_from_dos
from .record import CharacterRecord

__all__ = [
    "DosRecordError",
    "WrongTitleError",
    "CANNOT_CONVERT",
    "CLASS_SLOTS_FOR_CLASS",
    "CLASS_BIT_FOR_SLOT",
    "class_bits_for",
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
    Pool of Radiance's alone**, because that is the only pair whose two ports
    have been measured against each other.  Raising here is the difference
    between "not yet" and a conversion that silently reads the wrong bytes.

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


def item_to_c64(record: bytes) -> bytes:
    """Project one 63-byte DOS item onto the C64's sixteen bytes.

    Not a guess at a conversion: it *is* the evidence.  Applied to every item
    in the eight `ITEM*.DAX` files it reproduces **157 of the 163 distinct
    item records on the C64 game disks byte for byte**, which is what fixes
    every offset -- including that readied and the hidden-name mask share the
    C64's byte +6 where DOS spends a byte on each, and that cursed is bit 7 of
    +7.  The six that do not match are items the two ports hand out in
    different places, not near misses.  The write-up,
    `work/reports/dos-items.md`, is lost; asserted in `tests/test_dosbox.py`.
    """
    if len(record) != ITEM_SIZE:
        raise DosRecordError(f"a DOS item is {ITEM_SIZE} bytes; got {len(record)}")
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
INNATE_EFFECTS = frozenset({18, 26, 47, 48, 90, 97, 107, 124})

#: Bytes 1-4 of a `.SPC` record for an innate effect.  A record is nine bytes:
#: the effect id, these four, and a four-byte far pointer to the next record.
#: Every innate specimen in the archives -- 26, 47, 90, 97, 107 and 124, over
#: three races and 32 files -- reads `00 00 FF 00`, and the only record that
#: differs is a running spell: `BLESS` carries `02 00 01 00`, so `0xFF` in
#: byte 3 is what a permanent effect looks like beside a spell's remaining
#: duration.  18 and 48 have no specimen anywhere -- nobody in the archives is
#: a gnome -- so those two are this shape by analogy.  PROBABLE.
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

#: Race code -> the innate ids a **C64** record cannot hand over, because the
#: C64 engine either works them out when the blow lands or keeps them inside
#: another field, and stores no trait id for them at all.
#:
#: Two races have a DOS specimen, and each is written the whole set the
#: engine's own save holds for it:
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
#: **The gnome is not here and that is deliberate**, and there are *four* ids
#: at stake rather than the three this note used to name -- 48 was left out.
#: 18 is the gnome's own THAC0 bonus and 48 his own armour-class bonus; 47 is
#: named for gnomes as well as dwarves; 97 is named for all three sturdy races
#: where 90 is the dwarf's and the halfling's only, so a gnome would not get
#: 90 at all.  Nobody in any save the archives hold is a gnome, so every one of
#: the four would be a guess.  A converted gnome is reported instead.
RACE_COMBAT_EFFECTS: dict[int, tuple[int, ...]] = {
    1: (90, 97, 26, 47),
    5: (90, 97),
}

#: Races the C64 gives a constitution save bonus to.  `goldbox/levels.py`
#: reads the same three out of the game's own `GEN`.  On the C64 that bonus
#: lives inside the five saving-throw bytes; on DOS it lives in the `.SPC`
#: records above, and the five bytes on disk are not where the engine reads it
#: from -- see #191 (A converted dwarf loses his constitution bonus to saving
#: throws).
STURDY_RACES = (1, 3, 5)

#: The race with an innate effect this conversion cannot name.  Kept apart
#: from `RACE_COMBAT_EFFECTS` because the entry that is missing is the point.
UNWITNESSED_RACE = 3

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


def class_bits_for(char: "DosCharacter") -> int:
    """The class bitmask a record's level arrays imply.

    The OR of `CLASS_BIT_FOR_SLOT` over every slot set in the current
    per-class level array **and** in the former one, where the title has a
    former one.  Equal to the stored `class_bits` in 54 of 54 shipped records
    across all four titles, which is what makes it a check on the layout: a
    shape one byte out moves one array or the other and the two stop agreeing.
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
    ("class_bits", "class_bits"),
    ("hp_rolled", "hp_rolled"),
    ("party_order", "party_order"),
    ("hp_current", "hp_current"),
    ("thac0_current", "thac0"),
    ("armour_class", "armour_class"),
    ("movement_current", "roster_movement"),
)

#: DOS fields deliberately left behind, and why.  Reported, never silent.
DROPPED: tuple[tuple[str, str], ...] = (
    ("encumbrance", "derived -- money plus item weight; the C64 has no such "
                    "field and recomputes what it needs"),
    ("item_chain", "live heap state: the DOS item list is a chain of far "
                   "pointers, the C64 has sixteen fixed slots"),
    ("icon_colours", "six pairs of 4-bit colour indices for the DOS combat "
                     "icon; the C64 draws its own 36-byte icon and numbers "
                     "no such thing"),
    ("heap_104", "live heap pointers"),
    ("effect_chain", "live pointer to the effect list; the effects "
                     "themselves come from the .SPC file"),
    ("item_count", "implied by the C64's sixteen fixed slots"),
    ("portrait_head", "the sheet portrait's head: a menu position, which "
                      "needs the game's own creation tables to become the "
                      "C64's HEADnn id. Carried when `to_neutral` is given "
                      "them, dropped when it is not (#57)"),
    ("portrait_body", "see portrait_head; the body half of the same pair"),
    ("icon_head", "DOS art: CHEAD.DAX, the combat icon's head. The C64 "
                  "stores the drawn 36-byte icon instead of an index"),
    ("icon_body", "DOS art: CBODY.DAX, likewise"),
    ("icon_dimension", "the C64 has one size byte where DOS has two fields; "
                       "the C64's carries the other one"),
    ("strength_bonus", "a boolean on DOS; the C64's aligned byte is a "
                       "strength *index* and is computed instead"),
    ("hands_used", "live combat state"),
    ("unnamed_0ab", "one unattributed byte, stable per character"),
    ("field_83_87", "unattributed; Curse's importer copies it without naming "
                    "it either"),
    ("field_10c_10f", "unattributed; 00 01 00 00 in all 24 specimens, inside "
                      "the combat tail"),
)

#: Drops the **player** is not shown, though the conversion still knows them.
#:
#: Every name here is still in :data:`DROPPED`, so `field_disposition` still
#: accounts for it and `goldbox/dos_layout.py` still carries its field note --
#: what changes is only the list in front of somebody importing a save.  Each
#: of these three is a value the C64 works out for itself, so there is nothing
#: for a player to see go missing: encumbrance is money plus item weight,
#: item_count is implied by the sixteen fixed slots, and strength_bonus is a
#: boolean the C64 replaces with a computed strength index.
#:
#: Donald, 2026-08-27: *"We do not need to report derived lines as being
#: dropped. The user will not notice the difference."*
UNREPORTED_DROPS = frozenset({"encumbrance", "item_count", "strength_bonus"})

#: The three DOS icon fields that become :data:`COMBAT_ICON_DROP`'s one line.
#: All three say the same thing to a player -- the DOS combat figure does not
#: come across -- and three offsets do not make that any clearer.
ICON_DROPS = frozenset({"icon_head", "icon_body", "icon_dimension"})

#: What the player is told instead, in place of those three.  Donald's words,
#: approved 2026-08-27.  It is true because the conversion composes the icon
#: the game's own character creation writes (#118); if a conversion ever
#: carries the DOS figure across (#130), this sentence stops being true and
#: goes back to naming the fields.
COMBAT_ICON_DROP = ("Combat icons: set to the game's own default, since DOS "
                    "art does not convert")


#: DOS fields converted by a rule rather than by a copy.  Named here so the
#: disposition check below can see them; the rules themselves are in
#: `to_c64_record`.
TRANSFORMED: tuple[tuple[str, str], ...] = (
    ("name_length", "folded into the C64's 20-byte NUL-padded name"),
    ("name_text", "re-padded into the C64's 20-byte name"),
    ("spellbook", "56 bytes packed into 56 bits; the ids are identical"),
    ("spells_memorised", "reversed: DOS fills from the end, the C64 from the "
                         "start. The arrangement is not carried and does not "
                         "need to be -- the C64 engine ignores position "
                         "entirely and repacks the field itself by the first "
                         "camp (#110, goldbox/layout.py 0x020)"),
    ("class_levels", "permuted from class number to class bit"),
    ("spells_castable_cleric", "packed into the C64's high nibbles"),
    ("spells_castable_magic_user", "packed into the C64's low nibbles"),
    ("size", "1/2 on DOS becomes 0/1 on the C64"),
    ("turn_power", "one DOS byte for the C64's two turning bytes"),
    ("attack_forms", "copied as a block"),
    ("roster_tail", "copied as a block into the C64's roster tail"),
)


def field_disposition() -> dict[str, str]:
    """Every declared DOS field and what the conversion does with it.

    The test that keeps this module honest: a field declared in
    `goldbox/dos_layout.py` and named nowhere here would be a field silently
    dropped, which `docs/117-save-conversion.md` forbids.  The shape is
    `goldbox/neutral.py`'s, so every direction reports its drops the same way.
    """
    return neutral.disposition(DIRECT, TRANSFORMED, DROPPED, "the C64's")


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
    if not dos.is_pool_of_radiance:
        raise WrongTitleError(
            f"{dos.shape.title} records read, but only Pool of Radiance "
            f"converts: no other pair of ports has been measured against "
            f"each other (#53)",
            title=dos.shape.title)
    out = NeutralCharacter("DOS", source=dos.source)

    # -- the name: a count byte and fifteen characters -----------------------
    out.set("name", dos.name, "the DOS count byte and text at 0x000",
            FIELDS_BY_NAME["name_text"].confidence, Provenance.RESHAPED)

    # -- everything the two ports encode the same way ------------------------
    for dos_name, _ in DIRECT:
        f = FIELDS_BY_NAME[dos_name]
        out.set(dos_name, dos.get(dos_name),
                f"DOS {dos_name} @{f.offset:#05x} ({f.confidence})",
                f.confidence)

    # -- the spellbook: one byte per spell ------------------------------------
    out.set("spells_known", dos.spells_known,
            "DOS spellbook @0x033, one byte per spell",
            FIELDS_BY_NAME["spellbook"].confidence)

    # -- memorised spells, put into the neutral order: highest first ---------
    out.set("spells_memorised", dos.spells_memorised,
            "DOS 0x01C, reversed into the neutral highest-first order",
            FIELDS_BY_NAME["spells_memorised"].confidence)

    # -- the per-class levels, named rather than numbered --------------------
    raw_levels = dos.raw("class_levels")
    out.set("levels", {name: raw_levels[n] for n, name, _ in CLASS_LEVEL_SLOTS},
            "DOS class_levels @0x096, permuted from class number to class bit",
            FIELDS_BY_NAME["class_levels"].confidence)

    # -- spell slots: two triples, by class ----------------------------------
    out.set("spells_castable",
            {"cleric": tuple(dos.raw("spells_castable_cleric")),
             "magic-user": tuple(dos.raw("spells_castable_magic_user"))},
            "DOS 0x0B2 (cleric) and 0x0B5 (magic-user)",
            FIELDS_BY_NAME["spells_castable_cleric"].confidence)

    # -- size: DOS 1 small / 2 medium, the neutral 0 small / 1 large ---------
    out.set("size_small", max(0, dos.get("size") - 1),
            "DOS size @0x0C0, less one", FIELDS_BY_NAME["size"].confidence)

    out.set("turn_power", dos.get("turn_power"), "DOS 0x076",
            FIELDS_BY_NAME["turn_power"].confidence)
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
    # An **innate** effect that cannot be carried is the opposite and is
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
    carried_portrait: set[str] = set()
    for name, art_of, stem in (("portrait_head", "head_art", "HEAD"),
                               ("portrait_body", "body_art", "BODY")):
        if portraits is None:
            continue
        f = FIELDS_BY_NAME[name]
        position = dos.get(name)
        art = getattr(portraits, art_of)(position)
        if art is None:
            out.drop(f"DOS {name} @{f.offset:#05x}: {position} is not one of "
                     f"the positions the creation menu offers, so no C64 "
                     f"{stem}nn id corresponds to it")
            continue
        out.set(name, art,
                f"DOS {name} @{f.offset:#05x} = menu position {position}, "
                f"which is {stem}{art:02X} in {portraits.source}",
                f.confidence, Provenance.RESHAPED)
        carried_portrait.add(name)

    # -- what the DOS record holds and no neutral field does ------------------
    # `UNREPORTED_DROPS` and `ICON_DROPS` are still in `DROPPED`, so
    # `field_disposition` still accounts for every one of them; what they are
    # kept out of is the list a person reads.
    for name, why in DROPPED:
        if name in UNREPORTED_DROPS or name in ICON_DROPS:
            continue
        if name in carried_portrait:
            continue
        out.drop(f"DOS {name} @{FIELDS_BY_NAME[name].offset:#05x}: {why}")
    out.drop(COMBAT_ICON_DROP)
    return out


def to_c64_record(dos: DosCharacter,
                  icon: bytes | None = None) -> tuple[CharacterRecord, Report]:
    """Build a 580-byte C64 character record from a DOS one.

    A DOS read and a C64 write with the neutral record between them, which is
    all this function is now.  `icon` is the 36-byte combat icon; DOS has no
    equivalent -- its art is a different set -- so with none given the field
    is left zero and reported.

    The report names no character: it is one character's provenance, and which
    character that is belongs to the caller, which is the only thing that
    knows the slot and the marching position.  `convert_save` prefixes each of
    its own notes that way (#107).
    """
    return c64_codec.write(to_neutral(dos), icon=icon)


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
    """A whole-save conversion's report: what was carried, and what was not.

    `sources` covers all 13137 bytes of `SAVGAM<slot>.DAT` and `carried` is
    the same account written for a person -- one line per field taken from
    the C64 save -- because a reader who wants to know whether the clock came
    across should not have to read 13137 provenance lines to find out.
    `warnings` is still only for what could not be done.
    """

    #: One line per field taken from the C64 save and written into the DOS one.
    carried: list[str] = dataclasses.field(default_factory=list)

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
        lines = [f"  carried: {c}" for c in self.carried]
        if self.unwritten:
            lines.append(f"  {len(self.unwritten)} bytes left to the "
                         f"template, from {self.address(self.unwritten[0])}")
        return lines


def item_from_c64(record: bytes) -> bytes:
    """Project one C64 sixteen-byte item onto the DOS 63 bytes.

    The inverse of :func:`item_to_c64` for every field the two ports share:
    the C64's two packed bytes come apart into DOS's readied, hidden and
    cursed bytes, everything else is a straight copy.  The 46 bytes the C64
    has no words for are left empty, and each is a documented empty value
    rather than a guess: the rendered line at `0x001` is a cache the game
    rewrites whenever it draws the list, and NULL at `0x02A` is the chain's
    own last-item marker.
    """
    if len(record) != 16:
        raise DosRecordError(f"a C64 item is 16 bytes; got {len(record)}")
    at = {n: ITEM_FIELDS_BY_NAME[n].offset for n in
          ("type_index", "name1", "name2", "name3", "plus", "plus_save",
           "readied", "hidden", "cursed", "weight", "quantity", "value",
           "charges", "effect", "power")}
    r = record
    out = bytearray(ITEM_SIZE)
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
    # One DOS byte where the C64 has two turning bytes; the C64 *reader*
    # supplies the caster's, which is the pairing `to_neutral` uses too.
    ("turn_power", "turn_power"),
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
    ("thac0_current", "thac0_current"),
    ("armour_class", "armour_class"),
    ("movement_current", "movement_current"),
)

#: Neutral fields the DOS writer takes by a rule rather than by a copy.
WRITE_TRANSFORMED: tuple[tuple[str, str], ...] = (
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
)

#: Neutral fields the DOS writer takes nothing from, and why.  Reported by
#: `Writer.finish` for any character that carries one, never silent.
WRITE_DROPPED: tuple[tuple[str, str], ...] = (
    ("infravision", "DOS does not store it; the DOS engine derives what it "
                    "needs from the race byte"),
    ("npc", "no attributed DOS field holds it"),
    ("encumbrance", "recomputed from money and item weight -- the identity "
                    "the DOS engine itself uses -- rather than copied"),
)

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
                      "tables can be read**: the C64's HEADnn id is a "
                      "position in the same fourteen-entry menu DOS indexes "
                      "(#57). Zero only when they cannot be read or the id "
                      "is not one the menu offers, and reported when it is. "
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
    ("field_83_87", b"\x00\x00\x01\x00\x00",
     "00 00 01 00 00 in all 24 DOS specimens"),
    ("strength_bonus", b"\x01", "1 in all 24 DOS specimens"),
    ("field_10c_10f", b"\x00\x01\x00\x00",
     "00 01 00 00 in all 24 DOS specimens"),
)

#: Fields written to a **measured default** rather than carried from the
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
     "(#112, three fights). The C64's own icon colours are not carried "
     "across -- it has seven colour parts to DOS's six and one 3-bit "
     "colour per part against DOS's two 4-bit ones, so a correspondence "
     "would be a choice rather than a conversion"),
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
     "cannot be diffed against itself"),
)


def identity_byte(record: bytes | bytearray) -> int:
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
    """
    f = FIELDS_BY_NAME["unnamed_0ab"]
    body = bytearray(record)
    body[f.offset:f.end] = bytes(f.size)
    return hashlib.blake2b(bytes(body), digest_size=1).digest()[0]


#: What :func:`write` does with every field `goldbox/dos_layout.py` declares --
#: the *output-side* account, over DOS field names, where
#: :func:`write_field_disposition` accounts over the neutral vocabulary.
#: `tests/test_doswriter.py` fails if a field is declared in the layout and
#: named nowhere here, so a new field cannot be skipped in silence.
WRITE_TARGETS: dict[str, str] = (
    {dos_name: f"from neutral {n}" for n, dos_name in WRITE_DIRECT}
    | {"name_length": "from neutral name, the count byte",
       "name_text": "from neutral name, fifteen ASCII",
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


def write(char: NeutralCharacter,
          portraits: PortraitTables | None = None
          ) -> tuple[bytes, bytes, bytes, WriteReport]:
    """Build a 285-byte DOS record and its `.ITM` and `.SPC` payloads from a
    neutral character.

    The reverse of :func:`to_neutral`, and the writer #26 asked for: with it,
    C64 to DOS is `c64_codec.read` plus this, and nothing else.  Returns
    `(record, itm, spc, report)`.

    `portraits` is the creation menu's two tables, from
    :func:`portrait_tables`.  With them the sheet portrait crosses -- the C64
    art id the neutral record carries becomes the menu position DOS stores --
    and without them the pair is left zero and reported, which is what a
    converted party looked like before #57: no face on the sheet.

    Every byte of both outputs is justified in the report: it came from a
    neutral value, it was computed by a named rule, it is a documented
    constant, or it is a zero the report names as having no source --
    the live heap and the three unattributed runs, which the round-trip test
    masks *by this same list* rather than by whatever happened to differ.
    """
    rec = bytearray(RECORD_SIZE)
    rep = WriteReport()
    port = char.port
    w = neutral.Writer(char, rep, into="DOS", dropped=WRITE_DROPPED)
    use, emit = w.use, w.emit

    def put(v: neutral.Value, dos_name: str, extra: str = "",
            value: Any = None) -> None:
        f = FIELDS_BY_NAME[dos_name]
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
        text = str(name.value)[:15].encode("ascii", "replace")
        if len(str(name.value)) > 15:
            rep.warnings.append(
                f"Name {str(name.value)!r} is longer than the DOS fifteen "
                f"characters; truncated")
        rec[0x000] = len(text)
        rec[0x001:0x001 + len(text)] = text
        emit(name, "name_length/name_text", 0x000, 16,
             ", length-prefixed into one count byte and fifteen ASCII")

    # -- everything the two ports encode the same way ------------------------
    for neutral_name, dos_name in WRITE_DIRECT:
        v = use(neutral_name)
        if v is not None:
            put(v, dos_name)

    # -- the spellbook: one byte per spell, ids 1..56 -------------------------
    known = use("spells_known")
    if known is not None:
        book = bytearray(SPELLBOOK_SPELLS)
        for sid in known.value:
            if 1 <= int(sid) <= SPELLBOOK_SPELLS:
                book[int(sid) - 1] = 1
            else:
                rep.warnings.append(
                    f"Spell id {sid} is outside the DOS book's ids 1-56")
        put(known, "spellbook", ", unpacked to one byte per spell",
            value=bytes(book))

    # -- memorised spells: sixteen slots, filled from the end ----------------
    memorised = use("spells_memorised")
    if memorised is not None:
        ids = [int(i) for i in memorised.value][:16]
        if len(memorised.value) > 16:
            rep.warnings.append(
                f"{len(memorised.value)} spells memorised and DOS has "
                f"sixteen slots; the rest dropped")
        put(memorised, "spells_memorised",
            " reversed -- DOS fills its sixteen slots from the end",
            value=bytes(16 - len(ids)) + bytes(reversed(ids)))

    # -- the per-class level array: indexed by the class number --------------
    levels = use("levels")
    if levels is not None:
        raw = bytearray(8)
        for cname, lv in levels.value.items():
            n = _DOS_CLASS_SLOT.get(cname)
            if n is None:
                if lv:
                    rep.warnings.append(
                        f"{port} carries {cname} level {lv}, and the DOS "
                        f"eight-slot array has no {cname} slot")
                continue
            raw[n] = min(int(lv), 0xFF)
        put(levels, "class_levels",
            ", permuted from class name to class number", value=bytes(raw))

    # -- spell slots: two three-byte runs ------------------------------------
    castable = use("spells_castable")
    if castable is not None:
        for school, dos_name in (
                ("cleric", "spells_castable_cleric"),
                ("magic-user", "spells_castable_magic_user")):
            triple = (tuple(castable.value.get(school, ())) + (0, 0, 0))[:3]
            put(castable, dos_name, f", the {school} run",
                value=bytes(min(int(n), 0xFF) for n in triple))

    # -- size: neutral 0 small / 1 large, DOS 1 small / 2 medium -------------
    size = use("size_small")
    if size is not None:
        put(size, "size", " plus one -- DOS stores 1 small / 2 medium",
            value=int(size.value) + 1)

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
    portraits_written: set[str] = set()
    for pname, lookup, stem in (("portrait_head", "head_position", "HEAD"),
                                ("portrait_body", "body_position", "BODY")):
        v = use(pname)
        position = None
        if v is not None and portraits is not None:
            position = getattr(portraits, lookup)(int(v.value))
        if position is not None:
            put(v, pname,
                f", the position of {stem}{int(v.value):02X} in the creation "
                f"menu ({portraits.source})", value=position)
            portraits_written.add(pname)
        elif v is not None:
            rep.dropped.append(
                f"{pname}: {port} carries {stem}{int(v.value):02X} and " +
                ("the creation menu does not offer it, so the DOS record "
                 "has no position for it"
                 if portraits is not None else
                 "the creation menu's own tables were not available to turn "
                 "it into the position the DOS record stores"))

    # -- the inventory becomes the .ITM file ---------------------------------
    itm = b""
    projected: list[bytes] = []
    inventory = use("inventory")
    if inventory is not None:
        projected = [bytes(i) for i in inventory.value]
        itm = b"".join(item_from_c64(i) for i in projected)
        if projected:
            emit(inventory, "the .ITM file", RECORD_SIZE, len(itm),
                 ", each sixteen-byte record unpacked onto the DOS 63")
            for n in range(len(projected)):
                base = RECORD_SIZE + n * ITEM_SIZE
                rep.note(base, 0x02A,
                         f"item {n}: the rendered-line cache, left empty -- "
                         f"the game rewrites it whenever it draws the list")
                rep.note(base + 0x02A, 4,
                         f"item {n}: next pointer left NULL -- the loader "
                         f"rebuilds the chain, measured by its own resave")

    # -- the innate effects become the .SPC file -----------------------------
    # Running spells are not written, which is what the game's own C64
    # importer does: it reads a `.spc` and keeps only the racial and
    # constitutional ids.  A character with none gets no file, the state the
    # engine itself writes for a party member with nothing running.
    innate = use("innate_effects")
    carried = [int(e) for e in innate.value] if innate is not None else []
    race = int(w.get("race", 0) or 0)
    derived = [e for e in RACE_COMBAT_EFFECTS.get(race, ())
               if e not in carried]
    keep = derived + [e for e in carried if e in INNATE_EFFECTS]

    spc = b"".join(bytes((e,)) + INNATE_PAYLOAD + EFFECT_NEXT_NULL
                   for e in keep)
    base = RECORD_SIZE + len(itm)
    for n, e in enumerate(keep):
        at = base + n * EFFECT_SIZE
        whence = (f"derived from race {race} -- the C64 works this one out "
                  f"at combat time and stores it nowhere"
                  if e in derived else f"{port} innate_effects")
        rep.note(at, 1, f".SPC record {n}: effect {e} "
                        f"({traits.describe(e)}), {whence}")
        rep.note(at + 1, 4,
                 f".SPC record {n}: INNATE_PAYLOAD, the four bytes every "
                 f"innate specimen in the archives holds")
        rep.note(at + 5, 4,
                 f".SPC record {n}: next pointer NULL -- the loader allocates "
                 f"a node per record and relinks them, and the count comes "
                 f"from the file's length")
    for e in carried:
        if e not in INNATE_EFFECTS:
            rep.dropped.append(
                f"innate_effects {e} ({traits.describe(e)}): not one of the "
                f"ids the game's own importer keeps, so it is an item power "
                f"or a running effect rather than an innate one and no .SPC "
                f"record is written for it")
    if race == UNWITNESSED_RACE:
        rep.dropped.append(
            "A gnome's four innate racial bonuses -- his to-hit against "
            "kobolds and goblins, his armour class against gnolls and "
            "bugbears and against giants, and his constitution bonus to "
            "saving throws: no gnome appears in any DOS save we hold, so "
            "the effect ids the DOS engine writes for one are unmeasured "
            "and are not guessed at")

    # -- computed, not copied ------------------------------------------------
    count = min(len(projected), 0xFF)
    rec[FIELDS_BY_NAME["item_count"].offset] = count
    rep.note(FIELDS_BY_NAME["item_count"].offset, 1,
             f"item_count: computed -- the {count} records of the .ITM file")
    money = sum(int(w.get(k, 0)) for k in _COINS)
    weight = sum(int.from_bytes(i[8:10], "little") * (i[10] or 1)
                 for i in projected)
    _encode(FIELDS_BY_NAME["encumbrance"], rec,
            min(money + weight, 0xFFFF))
    rep.note(FIELDS_BY_NAME["encumbrance"].offset, 2,
             "encumbrance: computed -- money plus item weight x quantity, "
             "the identity the DOS engine itself uses")

    # -- documented constants ------------------------------------------------
    for cname, data, why in WRITE_CONSTANTS:
        f = FIELDS_BY_NAME[cname]
        rec[f.offset:f.end] = data
        rep.note(f.offset, f.size, f"{cname}: {why}")

    # -- measured defaults, where the source holds no matching value --------
    # The provenance note carries both halves: why this value, and what the
    # source held that is not being carried.  It does **not** go in
    # `rep.dropped`, which is read by a person in the conversion pane -- that
    # is a sentence for Donald to approve rather than one to model on the
    # sibling lines already there (`.claude/rules/gui-text.md`).
    for dname, data, why, lost in WRITE_DEFAULTS:
        f = FIELDS_BY_NAME[dname]
        rec[f.offset:f.end] = data
        rep.note(f.offset, f.size,
                 f"{dname}: {data.hex()} -- {why}. Not carried: {lost}")

    # -- bytes with no source: live heap and the unattributed ----------------
    # The portrait pair is in that list because it is what a conversion with
    # no game directory still writes, and a note here would overwrite the
    # provenance of a portrait that *was* carried.
    for uname, why in WRITE_UNSOURCED:
        if uname in portraits_written:
            continue
        f = FIELDS_BY_NAME[uname]
        rep.note(f.offset, f.size, f"{uname}: zero -- {why}")

    # -- derived from the record, once everything else in it is written ------
    # Last, so the digest covers the finished record: a field written after
    # this would change the character without changing its identity byte.
    # `WRITE_DERIVED` is the declaration the tests read; the rule itself is
    # per field, and there is one.
    (_derived_name, _derived_why), = WRITE_DERIVED
    f = FIELDS_BY_NAME[_derived_name]
    rec[f.offset] = identity_byte(rec)
    rep.note(f.offset, f.size,
             f"{_derived_name}: {rec[f.offset]:#04x} -- {_derived_why}")

    # -- the gaps, zero in every specimen held -------------------------------
    for f in LAYOUT:
        if f.name.startswith("gap_"):
            rep.note(f.offset, f.size, f"{f.name}: zero ({f.note})")

    # -- the closing sweep: unwritten fields, then the reader's own drops ----
    w.finish()
    rep.total = RECORD_SIZE + len(itm) + len(spc)
    return bytes(rec), itm, spc, rep


def write_field_disposition() -> dict[str, str]:
    """Every neutral field and what :func:`write` does with it.

    The DOS writer's twin of `goldbox.c64_codec.field_disposition`, over the
    neutral vocabulary; `WRITE_TARGETS` is the same account over the DOS
    layout's own names, and the tests hold both complete.
    """
    return neutral.disposition(WRITE_DIRECT, WRITE_TRANSFORMED, WRITE_DROPPED,
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

    Everything DOS keeps and the C64 does not is carried as a `_`-prefixed
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


def quest_flags(save: bytes) -> bytes:
    """`$4A20`-`$4AF8` as the C64's 217 bytes: read the word, keep the byte.

    Every nonzero word in the window is 1, 2, 3 or 255 across three saves of
    two parties -- the flag alphabet, nothing wider -- and the runs the
    quest-flag report names are set and clear together.  A base off by one
    would straddle them.
    """
    out = bytearray()
    for addr in range(FLAGS_FIRST, FLAGS_LAST + 1):
        out.append(dos_savegame.word(save, addr) & 0xFF)
    return bytes(out)


def apply_quest_flags(save0: bytearray, savgam: bytes) -> int:
    """Copy the flags into a C64 `SAVEDGAME0` payload. Returns bytes changed.

    `SAVEDGAME0` is a verbatim image of `$4900`-`$64FF`, so the C64 offset of
    an address is the address less `$4900`.
    """
    flags = quest_flags(savgam)
    base = FLAGS_FIRST - SAVE0_BASE
    changed = sum(1 for i, b in enumerate(flags) if save0[base + i] != b)
    save0[base:base + len(flags)] = flags
    return changed


#: The six clock digits and the largest value each holds -- sub-minute,
#: minute units, minute tens, hour, day, month (#58).  `$49C6` means the same
#: six things on both ports, which is what makes the copy below unconditional.
CLOCK_LIMITS = (10, 10, 6, 24, 30, 12)


def apply_clock(save0: bytearray, savgam: bytes) -> tuple[str, list[str]]:
    """Copy the DOS clock into a `SAVEDGAME0` payload, digit for digit.

    The mirror of what `write_dos_save` does the other way (#67), and for the
    same reason: the time of day is a value the party carries, not one the
    engine derives on load, so a conversion that does not write it leaves the
    template's clock in place.  Two DOS saves reading 10:15 and 22:15 both
    arrived at 21:15, which was `PORSAVE13`'s time (#103).

    Returns the report line and any complaints, because a digit above what
    its field holds means the six words are not the clock we think they are.
    """
    digits = [dos_savegame.word(savgam, dos_savegame.CLOCK + i)
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


def apply_position(save0: bytearray, savgam: bytes) -> tuple:
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
    x, y, facing = dos_savegame.position(savgam)
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
#: All 193 of them were written as zero in a converted save that was then
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
    (0x49F3, 9), (0x49FC, 1), (0x49FD, 2), (0x49FF, 1),
    (0x4AF9, 135), (0x4BD9, 7),
)

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
#: `apply_file_cache` raises both.  The wilderness refusal came off it in #50,
#: once #59's outdoor saves settled where a DOS save keeps the travel square,
#: and came off `retarget_reason` -- the other direction -- in #190, once an
#: outdoor DOS retarget had actually been driven.  `WILDERNESS`, Donald's own
#: wording for it, is gone with the last thing that raised it: neither
#: direction refuses a party on the travel grid now.
NOT_AN_AREA = ("the DOS party is in area {area}, which is not an area of Pool "
               "of Radiance, so there is no map file and no disk to name")
UNSUPPORTED_LOCATION = "Saves from this location are not supported."


def _sqrdata_number(name: str) -> int:
    """`SQRDATA05` -> 5.  Hex digits, like `geo_number`'s."""
    return int(name[len("SQRDATA"):], 16)


def apply_file_cache(save0: bytearray, savgam: bytes) -> str:
    """Point a `SAVEDGAME0` payload at the area the DOS party is standing in.

    The cache is rewritten to `$FF` in all twenty-five slots with slot 2 =
    the area's `GEO` number, slot 8 = the area id and slot 11 = `ANIMATE00`
    -- the file `SAVEDGAME1`'s own tail holds (#102) -- plus the three bytes
    outside the cache that make those findable: the disk hint `$49EA`, the
    map `$49C5` and the script id `$49F2`.  Returns the one line the report
    puts against the cache.

    That is `docs/140-loaded-files-cache.md`'s recipe and is the shape both
    live tests used.  Outdoors the same recipe with slot 4 in slot 2's
    role -- `SQRDATA` where a dungeon has a `GEO` -- which is the outdoor form
    #47 proved live twice, plus `$49E6` = 0, which is on its own what boots
    the engine into travel mode.  It still refuses rather than guesses for
    two kinds of area: one this project has no row for, and one whose script
    picks its map at run time or loads none at all.

    **It applies to a template standing in the area too** (#121).  That case
    used to return early and keep the template's own cache, on the reasoning
    that the game wrote it and it names more files than a converted save
    needs.  It was the only path here that preferred an inherited value to a
    computed one, and it cost 29 bytes of somebody else's save.  One of the
    two live tests of the recipe is itself a same-area case -- PORSAVE13 in
    the Slums -- so the branch that went is the one already proven
    unnecessary.
    """
    at = FILE_CACHE[0] - SAVE0_BASE
    there = dos_savegame.current_area(savgam)
    where = areas.area(there)
    if where is None:
        raise DosRecordError(NOT_AN_AREA.format(area=there))
    savgam_outdoors = dos_savegame.outdoors(savgam)
    if savgam_outdoors != where.outdoors:
        raise DosRecordError(
            f"the save's own $49E6 says "
            f"{'outdoors' if savgam_outdoors else 'indoors'}, but script id "
            f"{there} ({where.name or where.ecl}) is marked "
            f"{'outdoors' if where.outdoors else 'indoors'} in "
            "goldbox/areas.py -- these two disagree and neither is trusted "
            "over the other")
    if where.outdoors:
        sqr = _sqrdata_number(where.sqrdata)
        save0[at:at + FILE_CACHE[1]] = (
            bytes([FILE_CACHE_EMPTY]) * FILE_CACHE[1])
        save0[at + CACHE_SQRDATA] = sqr
        save0[at + CACHE_ECL] = there
        save0[at + CACHE_ANIMATE] = ANIMATE_RESIDENT
        save0[DISK_HINT - SAVE0_BASE] = where.disk
        save0[CURRENT_GEO - SAVE0_BASE] = sqr   # $49C5 holds the SQRDATA
        save0[CURRENT_SCRIPT - SAVE0_BASE] = there   # number outdoors (#47)
        save0[INDOORS - SAVE0_BASE] = 0
        return (f"loaded-files cache: $FF in all twenty-five, then slot 4 = "
                f"{where.sqrdata}, slot 8 = {where.ecl} and slot 11 = "
                f"ANIMATE00; outdoors no GEO loads at all, and $49E6 = 0 is "
                f"what boots into travel mode")
    if where.dynamic_geo or len(where.geos) < 1:
        raise DosRecordError(UNSUPPORTED_LOCATION)

    geo = areas.geo_number(where.geos[0])
    save0[at:at + FILE_CACHE[1]] = bytes([FILE_CACHE_EMPTY]) * FILE_CACHE[1]
    save0[at + CACHE_GEO] = geo
    save0[at + CACHE_ECL] = there
    save0[at + CACHE_ANIMATE] = ANIMATE_RESIDENT
    save0[DISK_HINT - SAVE0_BASE] = where.disk
    save0[CURRENT_GEO - SAVE0_BASE] = geo
    save0[CURRENT_SCRIPT - SAVE0_BASE] = there
    save0[INDOORS - SAVE0_BASE] = 1
    return (f"loaded-files cache: $FF in all twenty-five, then slot 2 = "
            f"{where.geos[0]}, slot 8 = {where.ecl} and slot 11 = ANIMATE00; "
            f"the arriving script refills the rest")


def marching_slot(index: int, count: int) -> int:
    """Which C64 save slot a party member at DOS marching position `index` goes in.

    **The C64 lists the party from the highest slot down** (#101).  Its own
    `ENCAMP > ALTER > ORDER` screen asks `WHO TAKES POSITION #1?` over a list
    headed by BRUTUS, and BRUTUS is in slot 5 of `work/p3/W1.D64`, an
    engine-written save whose slots 0-5 are MALCYON, LADY KATHERINE, ROLAND,
    SILAS, MAGNUS, BRUTUS.  The main panel lists the same six in the same
    order, and so does `PORSAVE13`.

    DOS is the other way round: `party_order` at `0x0BF` is 0 for the
    first-listed character, and the file order is the marching order.  So the
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
                 icon: bytes | None = None,
                 animate: bytes | None = None) -> C64SaveReport:
    """Write a DOS save into C64 `SAVEDGAME0` / `SAVEDGAME1` payloads.

    Both payloads are modified in place, and **the conversion writes every
    byte of both** when it is given an `icon` and an `animate`: hand it two
    zeroed buffers and the result is a whole save owing nothing to anybody
    else's (#118).  :func:`new_save` is that call, and is what the import
    uses.

    `icon` is the 36-byte combat icon every converted character gets, which
    only the caller can supply because it is composed from the player's own
    game disk -- `goldbox.iconparts.IconParts.default_icon`.  `animate` is
    `ANIMATE00`'s 852-byte payload off the same disks, which goes at `$8400`.
    Leave either out and that region keeps whatever the payload already held,
    which is only ever right when the payload came from a real C64 save;
    `Report.unwritten` is what says so afterwards.

    The report covers both files: an offset below `len(save0)` is a
    `SAVEDGAME0` offset and one at or above it is `SAVEDGAME1`'s (#120).
    `Report.unwritten` is empty when nothing was left to the payload.
    """
    party = read_party(folder, slot)
    savgam = pathlib.Path(folder).joinpath(f"SAVGAM{slot}.DAT").read_bytes()
    save1_at = len(save0)
    report = C64SaveReport(
        total=len(save0) + (0 if save1 is None else len(save1)),
        save0_size=len(save0))

    # First, because `apply_position` writes the travel square over
    # `$49C3`-`$49C4` when the DOS party is outdoors.
    header_zeroed = sum(size for _, size in HEADER_ZEROED)
    for address, size in HEADER_ZEROED:
        at = address - SAVE0_BASE
        save0[at:at + size] = bytes(size)
        report.note(at, size,
                    f"zero: no part of the conversion computes it, and a save "
                    f"with all {header_zeroed} of these written as zero "
                    f"loaded, walked, fought and changed area (#118)")
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

    for index, char in enumerate(party):
        place = marching_slot(index, len(party))
        rec, one = to_c64_record(char, icon=icon)
        # `party_order` in a roster block is the record's slot index, not the
        # marching position -- `goldbox/layout.py` 0x10D, and identity in every
        # engine-written save read.  It follows the slot the record lands in.
        rec.set("party_order", place)
        raw = rec.to_bytes()
        who = f"slot {place}: {char.name}, {index + 1} in the DOS marching order"
        at = SLOT_AREA - SAVE0_BASE + place * SLOT_STRIDE
        save0[at:at + SLOT_STRIDE] = raw[:SLOT_STRIDE]
        report.note(at, SLOT_STRIDE, f"{who} -- the converted record")
        at = ITEM_AREA - SAVE0_BASE + place * SLOT_STRIDE
        save0[at:at + SLOT_STRIDE] = raw[0x120:0x220]
        report.note(at, SLOT_STRIDE, f"{who} -- the converted inventory")
        at = ICON_TABLE - SAVE0_BASE + place * ICON_SIZE
        save0[at:at + ICON_SIZE] = raw[0x220:0x244]
        report.note(at, ICON_SIZE, f"{who} -- " + (
            "the combat icon the game's own character creation writes, "
            "composed from the player's own disk. The DOS character's own "
            "icon_head, icon_body and icon_colours are not carried: the two "
            "ports draw from different art and the palettes have not been "
            "compared (#57)" if icon is not None else
            "icon from the record, which is zero"))
        if save1 is not None:
            at = place * ROSTER_STRIDE
            save1[at:at + ROSTER_STRIDE] = raw[0x100:0x120]
            report.note(save1_at + at, ROSTER_STRIDE,
                        f"SAVEDGAME1 ${SAVE1_BASE + at:04X} -- {who} -- the "
                        f"converted roster block: the derived combat numbers "
                        f"the character record does not hold")
        report.dropped.extend(d for d in one.dropped if d not in report.dropped)
        report.warnings.extend(f"{char.name}: {w}" for w in one.warnings)

    # The party fills slots `len(party) - 1` down to 0, so everything above it
    # is somebody else's and would otherwise walk into the converted party
    # (#104).  The whole slot goes, not the `DROP`-style name byte the engine
    # writes: `ZSLOT8` zeroed slots 6-11, item blocks 6-11, icons 6-7 and
    # roster blocks 6-7 on the one template in 99 whose slots 6 and 7 hold a
    # seventh and an eighth character -- 555 non-zero bytes of a stranger's
    # party wiped -- and the party list showed six, the party walked five
    # squares and won a fight (#118, `work/p118-step3/runF.log`).
    for place in range(len(party), SLOT_TOTAL):
        for base in (SLOT_AREA, ITEM_AREA):
            at = base - SAVE0_BASE + place * SLOT_STRIDE
            save0[at:at + SLOT_STRIDE] = bytes(SLOT_STRIDE)
            report.note(at, SLOT_STRIDE,
                        f"slot {place}: zeroed entire -- not this party's, and "
                        f"a party that carried none of these fought and won "
                        f"(#118)")
        if place < SLOT_COUNT:
            at = ICON_TABLE - SAVE0_BASE + place * ICON_SIZE
            save0[at:at + ICON_SIZE] = bytes(ICON_SIZE)
            report.note(at, ICON_SIZE,
                        f"slot {place}: combat icon zeroed -- nothing draws "
                        f"an icon for a slot with no character in it")
        if save1 is not None and place < SLOT_COUNT:
            at = place * ROSTER_STRIDE
            save1[at:at + ROSTER_STRIDE] = bytes(ROSTER_STRIDE)
            report.note(save1_at + at, ROSTER_STRIDE,
                        f"SAVEDGAME1 ${SAVE1_BASE + at:04X} -- slot {place}: "
                        f"roster block zeroed, `roster_in_use` with it")
    if len(party) < SLOT_COUNT:
        report.warnings.append(
            f"Slots {len(party)}-{SLOT_COUNT - 1} emptied: a DOS save holds "
            f"six characters and a C64 save eight")

    for base, size in EFFECT_ARRAYS:
        at = base - SAVE0_BASE
        save0[at:at + size] = bytes(size)
        report.note(at, size, "active effects: zeroed, which is 'none running'")
    at = SCRIPT_SCRATCH[0] - SAVE0_BASE
    save0[at:at + SCRIPT_SCRATCH[1]] = bytes(SCRIPT_SCRATCH[1])
    report.note(at, SCRIPT_SCRATCH[1],
                "per-script scratch: zeroed, as DUNGEON $202A does on every "
                "area change")
    at = FILE_CACHE[0] - SAVE0_BASE
    outdoors = dos_savegame.outdoors(savgam)
    report.note(at, FILE_CACHE[1], apply_file_cache(save0, savgam))
    for address, what in (
            (DISK_HINT, "the POOL side the loader will ask for"),
            (CURRENT_GEO, "the SQRDATA number LOADFILES reloads" if
             outdoors else "the map LOADFILES reloads"),
            (CURRENT_SCRIPT, "the script id"),
            (INDOORS, "outdoors -- 0 boots into travel mode" if outdoors
             else "indoors")):
        report.note(address - SAVE0_BASE, 1,
                    f"{what}, from the area the DOS party is in")

    changed = apply_quest_flags(save0, savgam)
    report.note(FLAGS_FIRST - SAVE0_BASE, FLAGS_LAST - FLAGS_FIRST + 1,
                "quest flags: the DOS word array, narrowed to bytes")
    for address, what in apply_position(save0, savgam):
        report.note(address - SAVE0_BASE, 1, what)
    note, complaints = apply_clock(save0, savgam)
    report.note(dos_savegame.CLOCK - SAVE0_BASE, dos_savegame.CLOCK_DIGITS,
                note)
    report.warnings.extend(complaints)
    # "differed from the template's" until #118 removed the template, after
    # which the sentence described something that no longer exists: from
    # nothing the payload is zero, so what this counts is the DOS party's own
    # set flags.  It is a count either way, so the wording says what was
    # compared rather than naming a save that may not be there.
    report.warnings.append(
        f"{changed} of {FLAGS_LAST - FLAGS_FIRST + 1} quest-flag bytes "
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
            f"{report.address(i)}: carried through from the template save")
    return report


def new_save(folder: str | pathlib.Path, slot: str, icon: bytes,
             animate: bytes) -> tuple[bytearray, bytearray, C64SaveReport]:
    """A whole C64 save from a DOS one, owing nothing to another save (#118).

    `icon` is the 36-byte combat icon each character gets and `animate` is
    `ANIMATE00`'s payload; both come off the player's own game disks, and
    there is no default for either -- a conversion that cannot read them is
    one that would have to invent bytes, and it refuses instead.

    Returns the two payloads and the report, whose `unwritten` is empty.
    """
    save0, save1 = bytearray(SAVE0_SIZE), bytearray(SAVE1_SIZE)
    report = convert_save(folder, slot, save0, save1,
                          icon=icon, animate=animate)
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
    from . import games
    from .d64 import D64, attach_load_address
    game = game or games.POOL_OF_RADIANCE
    disk = D64.blank()
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


def c64_wall_triple(save0: bytes) -> tuple[int, int, int]:
    """The wallset triple a DOS save wants, out of the C64 loaded-files cache.

    Cache slots 15-17 hold the three `WALLSET` pieces, and the DOS save holds
    the same three numbers as words -- PORSAVE13's Slums (2,4,1) is DOS slot
    J's, PORSAVE's Sokol Keep (1,5,9) is slot B's.  An empty C64 slot becomes
    an empty DOS word.

    **New Phlan is the exception**: the C64 loads no `WALLSET` there at all
    and every slot reads `$FF`, where DOS slot A holds `(0, $FFFF, $FFFF)`.
    So this returns three empties for a New Phlan save, which is not what the
    DOS engine's own save says -- and is measured to draw the identical view
    anyway, `work/p60/run3` Z0.
    """
    at = FILE_CACHE[0] - SAVE0_BASE + CACHE_WALLSET
    out = []
    for b in save0[at:at + CACHE_WALLSET_PIECES]:
        v = b & ~FILE_CACHE_RELOAD & 0xFF
        out.append(dos_savegame.EMPTY if v == CACHE_UNSET else v)
    return tuple(out)


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
#: writes, and it is said out loud in the report instead.
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
#: the same bar #118 held the C64 direction's 193 header bytes to.
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
#: more, so the ports do not agree on it and it is not carried across.
#:
#: **What it means is still unknown** and this does not claim otherwise --
#: only what it does.
SAVGAM_MEASURED: tuple[tuple[int, int, str], ...] = (
    (0x49FF, 3, "the sheet portrait is not drawn at all when this word is "
                "zero (#57), and 3 is what all three engine-written saved "
                "games hold. What it means is unknown"),
)


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


def _area_script(area: int, template: "pathlib.Path | None",
                 game: "str | pathlib.Path | None") -> bytes:
    """The area's own `ECL<n>.DAX` block, or a refusal saying why not.

    Three refusals, and all three used to be a warning with the party left
    standing on the template's square: an area with no legal answer, no game
    directory to read the script out of, and a container that does not hold
    the block.  Each of them ends with a save the party has never been in;
    the file loads, so nothing says so afterwards.
    """
    why = retarget_reason(area)
    if why is not None:
        raise DosRecordError(why)
    where = areas.area(area)
    data = _read_ecl_dax(template, game, where.disk)
    if data is None:
        raise DosRecordError(
            f"no {ECL_DAX.format(dax=where.disk)} in the game directory, and "
            f"the game's own files are the only copy of area {area}'s script; "
            f"without it the save would carry somebody else's area")
    try:
        return dos_savegame.dax_block(data, area)
    except dos_savegame.DosSaveError as e:
        raise DosRecordError(
            f"{ECL_DAX.format(dax=where.disk)} is unreadable: {e}") from e


def _note_word(report: "SaveReport", address: int, words: int,
               why: str) -> None:
    """Provenance for `words` VM words, at the file offset they live at."""
    report.note(dos_savegame.word_offset(address), 2 * words, why)


def savgam_writes(savgam: bytearray, report: "SaveReport", save0: bytes,
                  slot: str, count: int, script: bytes) -> None:
    """Write everything a C64 save sources into a `SAVGAM<slot>.DAT` buffer.

    `savgam` is modified in place and every byte written gets a line in
    `report.sources`, so what is *not* written is countable afterwards --
    which is the whole of how "no template" is checked rather than asserted.

    `script` is the party's own area's `ECL<n>.DAX` block, and there is no
    path here without one: the load path reads the staged script and dies in
    `Load3DMap` when it is somebody else's (#60), and a conversion that
    cannot read the game's files has nothing to put there but a stranger's
    area.  The caller refuses instead.

    **A party on the travel grid takes a different value in four places**
    (#190), and everything else about the write is the same: `$49C5` = 0
    rather than the area id, the wallset triple is the overland's own
    measured `(0, $FFFF, $FFFF)` rather than the C64 cache's, the square is
    the travel pair at `$49C3`/`$49C4`, and `$49E6` = 0 is what boots the
    engine into travel mode.  `put_tail_state` takes the fifth.
    """
    area = save0[CURRENT_SCRIPT - SAVE0_BASE]
    where = areas.area(area)
    x, y, facing = (save0[PARTY_X - SAVE0_BASE], save0[PARTY_Y - SAVE0_BASE],
                    save0[PARTY_FACING - SAVE0_BASE])
    indoors = not where.outdoors

    # Outdoors the C64's own cache slots 15-17 read `$FF` -- the travel grid
    # loads no `WALLSET` on either port -- which would make the triple
    # `($FFFF, $FFFF, $FFFF)` where every engine-written outdoor DOS save
    # holds `(0, $FFFF, $FFFF)`.  So the measured overland value is written
    # instead of the empty read, and `OUTDOOR_WALLSET` carries the evidence.
    wallset = (c64_wall_triple(save0) if indoors
               else dos_savegame.OUTDOOR_WALLSET)
    dos_savegame.retarget(savgam, area=area, dax=where.disk,
                          wallset=wallset, script=script,
                          outdoors=not indoors)
    report.note(dos_savegame.DAX_NUMBER, 1,
                f"the DAX container number, {where.disk}, for area "
                f"{area} ({where.name or where.ecl})")
    _note_word(report, dos_savegame.AREA, 1,
               "the area id" if indoors else
               "zero: the overland names no GEO, which is what an outdoor "
               "DOS save holds here in 10 of 10 -- and it is not the C64's "
               "own $49C5, which outdoors holds the SQRDATA number (#59)")
    _note_word(report, dos_savegame.SCRIPT, 1, "the area's script id")
    _note_word(report, dos_savegame.DISK, 1,
               "the DAX container number again -- the geo load reads "
               "this word and not the header byte (#59)")
    _note_word(report, dos_savegame.WALLSET, 3,
               "the wallset triple, from the C64 loaded-files cache "
               "slots 15-17, which carry the same three numbers" if indoors
               else "the overland wallset triple (0,$FFFF,$FFFF), which the "
               "engine writes for itself out there -- it replaced a seeded "
               "(1,5,9) three times of three, and no outdoor load reads it "
               "(#59, #190)")
    _note_word(report, dos_savegame.WALLMAP, 3,
               "the wall-index map that goes with the triple")
    start, end = dos_savegame.ECL_BUFFER
    report.note(start, end - start,
                f"the area's own ECL{where.disk}.DAX block from byte "
                f"{dos_savegame.ECL_HEADER} on, then zero to the end of "
                f"the buffer -- which is what an engine-written save "
                f"holds past its script's end, 6 of 6 (#59)")
    dos_savegame.put_word(savgam, dos_savegame.INDOORS, 1 if indoors else 0)
    _note_word(report, dos_savegame.INDOORS, 1,
               "indoors" if indoors else "outdoors -- 0 boots the engine "
               "into travel mode")

    if indoors:
        dos_savegame.put_position(savgam, x, y, facing)
        report.note(dos_savegame.POS_X, 3,
                    f"the square ({x},{y}) facing {facing}, the C64's own "
                    f"facing doubled")
    else:
        tx, ty = (save0[dos_savegame.TRAVEL_X - SAVE0_BASE],
                  save0[dos_savegame.TRAVEL_Y - SAVE0_BASE])
        dos_savegame.put_travel_square(savgam, tx, ty)
        _note_word(report, dos_savegame.TRAVEL_X, 2,
                   f"the travel square ({tx},{ty}), window-local, the C64's "
                   f"own $49C3/$49C4 -- the same pair at the same address on "
                   f"both ports (#47, #59)")
        # 12801/12802 are the square the party last stood on **indoors**,
        # frozen on both ports the moment it reached the grid -- C64
        # `DUNGEON $1A3C` copies `$C04B` into `$49C0` only while `$49E6` is
        # set, and DOS freezes 12801/12802 the same way.  So the C64's own
        # stale pair is what belongs in the DOS one: same field, same
        # meaning, and nothing reads either out here.
        #
        # 12803 is the exception and is the one field this conversion
        # **cannot** carry outdoors.  See OUTDOOR_FACING.
        dos_savegame.put_position(savgam, x, y, OUTDOOR_FACING)
        report.note(dos_savegame.POS_X, 2,
                    f"the stale indoor square ({x},{y}) the party left the "
                    f"grid on, the C64's own $49C0/$49C1 -- frozen on both "
                    f"ports out here and read by neither")
        report.note(dos_savegame.POS_FACING, 1, OUTDOOR_FACING_WHY)
        report.dropped.append(OUTDOOR_FACING_WHY)
    dos_savegame.put_tail_state(savgam, indoors=indoors)
    where_stood = "indoors" if indoors else "outdoors"
    report.note(dos_savegame.SCRATCH_BYTE, 4,
                f"the four tail bytes: 12804 at the value an engine-written "
                f"save of a party standing {where_stood} has held (the "
                f"engine rewrites it anyway), the low byte of $5200, the "
                f"view mode from $49E6, and the constant "
                f"{dos_savegame.TAIL_CONSTANT}")
    dos_savegame.put_party_size(savgam, count)
    _note_word(report, dos_savegame.PARTY_SIZE, 1, f"the party size, {count}")
    report.note(dos_savegame.PARTY_SIZE_BYTE, 1,
                f"the party size again, {count}")

    dos_savegame.put_character_files(savgam, slot)
    for n in range(dos_savegame.PARTY_ENTRIES):
        report.note(
            dos_savegame.PARTY_TABLE + n * dos_savegame.PARTY_ENTRY,
            dos_savegame.PARTY_NAME_LEN,
            f"CHRDAT{slot.upper()}{n + 1}, which is what the engine loads "
            f"the party from -- not the slot letter at the LOAD menu (#59)")

    for addr in range(FLAGS_FIRST, FLAGS_LAST + 1):
        dos_savegame.put_word(savgam, addr, save0[addr - SAVE0_BASE])
    _note_word(report, FLAGS_FIRST, FLAGS_LAST - FLAGS_FIRST + 1,
               "a quest flag: the C64 byte at the same ECL address, widened "
               "to a word")
    for addr in SHARED_SCRATCH:
        dos_savegame.put_word(savgam, addr, save0[addr - SAVE0_BASE])
        _note_word(report, addr, 1,
                   "script scratch: the C64 byte at the same ECL address, "
                   "widened to a word")

    digits = [save0[dos_savegame.CLOCK + i - SAVE0_BASE]
              for i in range(dos_savegame.CLOCK_DIGITS)]
    dos_savegame.put_clock(savgam, digits)
    _note_word(report, dos_savegame.CLOCK, dos_savegame.CLOCK_DIGITS,
               "a clock digit, the C64's own byte at the same address")

    for address, value, why in dos_savegame.SAVGAM_CONSTANTS:
        dos_savegame.put_word(savgam, address, value)
        _note_word(report, address, 1, f"a documented constant: {why}")

    for address, value, why in SAVGAM_MEASURED:
        dos_savegame.put_word(savgam, address, value)
        _note_word(report, address, 1, f"measured in the running game: {why}")


def savgam_zeroes(savgam: bytearray, report: "SaveReport") -> None:
    """Account for every byte of the file :func:`savgam_writes` left zero.

    Called only when the buffer started zeroed, because that is the only case
    in which "not written" and "written zero" are the same thing.  Three
    groups: the words no C64 save can source, named one at a time in
    :data:`SAVGAM_UNSOURCED`; the character table's heap scratch; and the
    remainder of the variable space, which reads zero in every genuine
    specimen.
    """
    for address, words, why in SAVGAM_UNSOURCED:
        _note_word(report, address, words, f"zeroed -- {why}")
    for n in range(dos_savegame.PARTY_ENTRIES):
        at = (dos_savegame.PARTY_TABLE + n * dos_savegame.PARTY_ENTRY
              + dos_savegame.PARTY_NAME_LEN)
        report.note(at, dos_savegame.PARTY_ENTRY - dos_savegame.PARTY_NAME_LEN,
                    PARTY_TABLE_SCRATCH)
    report.note(dos_savegame.SAVGAM_SIZE - dos_savegame.UI_SCRATCH,
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
    rest = [i for i in range(dos_savegame.VAR_OFFSET,
                             dos_savegame.VAR_OFFSET
                             + 2 * dos_savegame.VAR_WORDS)
            if i not in report.sources]
    for i in rest:
        report.sources[i] = (
            "zeroed: this word reads zero in every genuine specimen on this "
            "machine, and nothing in a C64 save corresponds to it")


def write_dos_save(save0: bytes, save1: bytes | None,
                   template: str | pathlib.Path | None,
                   out: str | pathlib.Path,
                   slot: str = "A",
                   game: str | pathlib.Path | None = None) -> "SaveReport":
    """Write a C64 save into a DOS save directory.

    `save0` and `save1` are the C64 `SAVEDGAME0`/`SAVEDGAME1` payloads; `out`
    is where the new files go.  `game` is the DOS game directory, the one
    holding `ECL<n>.DAX`, and it is **not optional in practice**: the party's
    own area's script has to be staged in the save or the game exits to DOS
    on load, and the game's files are the only copy of it.

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

    sg = SaveGame0.from_bytes(bytes(save0))
    sg1 = SaveGame1(bytes(save1)) if save1 is not None else None
    party = sg.characters
    if len(party) > 6:
        raise DosRecordError(
            f"a DOS save holds six characters; this save has {len(party)}")

    # Read the template's save, and the area's script, before anything in
    # `out` is touched: a missing `SAVGAM<slot>.DAT` or an area with no legal
    # answer must fail with the slot still as the last conversion left it,
    # not half cleared.
    savgam = bytearray(dos_savegame.SAVGAM_SIZE) if template is None else \
        bytearray((template / f"SAVGAM{slot}.DAT").read_bytes())
    c64_area = save0[CURRENT_SCRIPT - SAVE0_BASE]
    script = _area_script(c64_area, template, game)

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
    report = SaveReport(total=dos_savegame.SAVGAM_SIZE)
    # The sheet portrait crosses through the creation menu's own tables, and
    # they are in the game's own `START.EXE` -- the directory this function
    # already needs for the party's area script (#57).  A directory that
    # cannot answer for them costs the party its faces and nothing else, so
    # it is reported rather than raised.
    faces, why_not = portrait_tables(game)
    if faces is None:
        # A warning rather than a `carried` line: `carried` is what *did*
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
                              source=f"C64 slot {char_slot.index}")
        rec, itm, spc, one = write(char, portraits=faces)
        built.append((char, rec, itm, spc, one, char_slot))

    # **The two ports list the party from opposite ends** (#101).  The C64
    # displays the highest occupied slot first -- its own `ENCAMP > ALTER >
    # ORDER` asks `WHO TAKES POSITION #1?` over a list headed by the character
    # in slot 5 -- and DOS displays `CHRDAT<slot>1` first.  So the file order
    # is the reverse of the slot order, and `party_order` at `0x0BF`, which is
    # 0-5 in file order in every DOS specimen, is renumbered to match rather
    # than left as the C64's slot index.
    built.reverse()
    order = FIELDS_BY_NAME["party_order"].offset
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
    cleared = 0
    for n in range(1, dos_savegame.PARTY_ENTRIES + 1):
        stale = out / f"CHRDAT{slot}{n}"
        for suffix in (".SAV", ".ITM", ".SPC"):
            path = stale.with_suffix(suffix)
            if path.exists():
                path.unlink()
                cleared += 1

    if cleared:
        report.carried.append(
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
        if itm:
            stem.with_suffix(".ITM").write_bytes(itm)
        # A character with no innate effects gets no `.SPC`, which is what the
        # engine's own save writes for one with nothing running (#61): every
        # human in the archives' twelve saved parties has no file at all.
        if spc:
            stem.with_suffix(".SPC").write_bytes(spc)
        who = char.get("name", f"slot {char_slot.index}")
        report.dropped.extend(d for d in one.dropped
                              if d not in report.dropped)
        report.warnings.extend(f"{who}: {w}" for w in one.warnings)

    savgam_writes(savgam, report, save0, slot, len(party), script)
    if template is None:
        savgam_zeroes(savgam, report)
    where = areas.area(c64_area)
    x, y, facing = (save0[PARTY_X - SAVE0_BASE], save0[PARTY_Y - SAVE0_BASE],
                    save0[PARTY_FACING - SAVE0_BASE])
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
    report.carried.extend((
        f"the place: area {c64_area}, {where.name}, {stood} -- every write "
        f"dos_savegame.RETARGET_WRITES names, including the area's own "
        f"script out of {ECL_DAX.format(dax=where.disk)}",
        f"the party's filenames: CHRDAT{slot.upper()}1-"
        f"{dos_savegame.PARTY_ENTRIES}, which is what the engine loads from",
        f"quest flags: {FLAGS_LAST - FLAGS_FIRST + 1} C64 bytes widened to "
        f"words at the same ECL addresses",
        f"the script scratch: $49EB and $4A00-$4A1F, {len(SHARED_SCRATCH)} "
        f"more C64 bytes widened to words at the same ECL addresses",
        f"the clock: {hour}:{minute:02d}, day {day} month {month} -- the "
        f"C64's own six digit bytes at $49C6-$49CB",
        f"the party size, {len(party)}, into both $503E and byte "
        f"{dos_savegame.PARTY_SIZE_BYTE}",
    ))

    # What is left is what the file owes to somebody else's save, and it is
    # empty when there was no template.  `new_dos_save` refuses on it rather
    # than returning a save with a stranger's byte in it (#26).
    report.unwritten = [i for i in range(dos_savegame.SAVGAM_SIZE)
                        if i not in report.sources]
    for i in report.unwritten:
        report.sources[i] = f"{report.address(i)}: carried from the template"
    (out / f"SAVGAM{slot}.DAT").write_bytes(bytes(savgam))
    return report


def new_dos_save(save0: bytes, save1: bytes | None,
                 out: str | pathlib.Path, slot: str,
                 game: str | pathlib.Path) -> "SaveReport":
    """A whole DOS save from a C64 one, owing nothing to another save (#26).

    The mirror of :func:`new_save`, and the same refusal: `game` is the DOS
    game directory the area's own `ECL<n>.DAX` is read out of, there is no
    default for it, and a conversion that cannot read it would have to invent
    an area rather than write the one the party is standing in.

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
        report = write_dos_save(save0, save1, None, staging, slot, game=game)
        if report.unwritten:
            raise DosRecordError(
                f"{len(report.unwritten)} bytes of the saved game have no "
                f"source and were left zero by accident rather than by "
                f"measurement; the first is "
                f"{report.address(report.unwritten[0])}")

        # The slot is the unit a conversion overwrites, and the clearing has
        # to happen here rather than in `write_dos_save`, which only ever saw
        # the empty staging directory.  Same enumeration, same reason (#68).
        cleared = 0
        for n in range(1, dos_savegame.PARTY_ENTRIES + 1):
            stale = out / f"CHRDAT{slot}{n}"
            for suffix in (".SAV", ".ITM", ".SPC"):
                path = stale.with_suffix(suffix)
                if path.exists():
                    path.unlink()
                    cleared += 1
        if cleared:
            report.carried.append(
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
