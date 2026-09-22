"""Amiga Pool of Radiance: the character record, the save slot and the disk.

`CHRDATA<n>.sav` on an Amiga Pool of Radiance save disk is the 285-byte DOS
record of `goldbox/dos_port.py` byte-swapped and three bytes wider, so nothing
here is a second field table; the whole reader is a transposition and
`goldbox.dos_codec` does the reading.  Around it sit the save slot
(`savgam<letter>.dat`), the ten-byte slot list the picker reads, and the disk
those live on.

`#470 (Give the project a neutral title beside its neutral character record,
with one port per platform a title shipped on)`'s stage 10 split
`goldbox/amiga_codec.py` by title.  Pools of Darkness is in
`goldbox/amiga_pod.py`, Curse and Silver Blades in `goldbox/amiga_later.py`,
and `goldbox/amiga_shared.py` holds what more than one of them needs.

**Three names here are read by `goldbox/amiga_later.py` as well**, and they are
the one place the split did not fall out cleanly: :class:`PorWriteReport`,
:func:`amiga_por_effect_to_dos` and :func:`amiga_por_effect_from_dos`.  All
three are facts about the Amiga rather than about this title -- the ten-byte
effect node is the same on all three titles, and the write report's contract is
every Amiga writer's -- and they wear this title's spelling because it is the
one they were decoded on.  They stay here rather than moving to
`goldbox/amiga_shared.py` because :class:`PorWriteReport`'s `total` defaults to
:data:`AMIGA_POR_RECORD_SIZE`, which a dataclass evaluates when the class is
defined and no deferred import can supply -- so moving them would move Pool of
Radiance's own record length out of Pool of Radiance's file.  Renaming them is
the real answer and it is a change of its own.

:func:`to_neutral` takes a Curse or Silver Blades record as well, and hands it
to `goldbox.amiga_later.to_neutral_later`.  That import is deferred, so this
module still imports nothing of another title's at the top.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence

from . import dos_port, neutral
from .amiga_port import (
    AMIGA_POR_EFFECT_PAD,
    AMIGA_POR_EFFECT_SIZE,
    AmigaRecordError,
)
from .layout import Kind
from .neutral import NeutralCharacter
from .portraits import neutral_menu

if TYPE_CHECKING:          # avoided at runtime: goldbox.dos_codec is the
    from .iconparts import DosIcon  # heavier module and this file only needs
    # the name


# ---------------------------------------------------------------------------
# Amiga Pool of Radiance: the same record as DOS, big-endian, three bytes wider
# ---------------------------------------------------------------------------
#
# `CHRDATA<n>.sav` on an Amiga Pool of Radiance save disk, and `<NAME>.cha`
# where a party has been exported, is **288 bytes**: the 285-byte DOS record
# of `goldbox/dos_port.py` with the multi-byte fields byte-swapped, the name
# re-encoded, and three insertions.  Nothing here is a second field table --
# the DOS one is read through a shift map, so the two cannot drift apart.
#
# The three insertions, each located to the byte:
#
#   * `0x07F` -- one pad byte, zero in 20 of 20 specimens, ahead of the
#     effect-chain pointer.  DOS keeps an offset word and a segment word
#     there; the Amiga keeps one `u32` and a 68000 compiler even-aligns it.
#   * `0x089` -- one pad byte before the `u16` money block, zero in 20 of 20.
#     `docs/124-amiga-port.md` §1.21 has the two readings that place it:
#     `/program` tests `0x085` against `0x7F` and masks `0x086` with 7, which
#     are DOS's control byte and treasure share; and Amiga Curse's Pool of
#     Radiance importer copies this record's `0x084`-`0x088` into Curse's own
#     `field_83_87` at `0x0F6`-`0x0FA`, one byte for one.
#   * `0x11F`, the last byte -- 285 + 2 is odd, and the struct is padded to an
#     even size.  Junk in 5 of 20 and zero in the rest, which is what an
#     uninitialised pad looks like.
#
# So a DOS offset maps to an Amiga offset by adding 0 below `0x07F`, 1 through
# `field_83_87`, and 2 from the money block on.
AMIGA_POR_RECORD_SIZE = 288
AMIGA_POR_NAME_SIZE = 16          # NUL-padded, where DOS has a count byte
AMIGA_POR_PAD = 0x07F             # the first insertion
AMIGA_POR_MONEY_PAD = 0x089       # the second, ahead of the money block
AMIGA_POR_TAIL_PAD = 0x11F        # the third
#: `(first DOS offset, bytes inserted before it)`, ascending.
AMIGA_POR_SHIFTS = ((0x000, 0), (0x07F, 1), (0x088, 2))


def amiga_por_offset(dos_offset: int) -> int:
    """Where a DOS record offset lands in the Amiga one.

    Every DOS offset has an answer: all three insertions are located, so the
    map has no window it has to refuse.
    """
    shift = 0
    for first, amount in AMIGA_POR_SHIFTS:
        if dos_offset >= first:
            shift = amount
    return dos_offset + shift


@dataclass(frozen=True)
class AmigaPorCharacter:
    """One Amiga Pool of Radiance character, read through the DOS table.

    `items` and `effects` are the sibling `.itm` and `.spc` files when there
    are any; an exported `.cha` normally has neither, and the record's own
    `item_count` is what says how much of a `.itm` belongs here.
    """

    raw: bytes
    source: str = ""
    items: tuple["AmigaPorItem", ...] = ()
    effects: tuple[bytes, ...] = ()

    @classmethod
    def from_bytes(cls, data: bytes | bytearray, source: str = "",
                   items: Sequence["AmigaPorItem"] = (),
                   effects: Sequence[bytes] = ()) -> "AmigaPorCharacter":
        if len(data) != AMIGA_POR_RECORD_SIZE:
            raise AmigaRecordError(
                f"an Amiga Pool of Radiance record is "
                f"{AMIGA_POR_RECORD_SIZE} bytes, got {len(data)}; the Amiga "
                f"Curse record is 428 and Pools of Darkness's .pc is 484")
        return cls(bytes(data), source, tuple(items), tuple(effects))

    @property
    def name(self) -> str:
        raw = self.raw[:AMIGA_POR_NAME_SIZE]
        return raw.split(b"\0")[0].decode("latin1")

    def get(self, field_name: str):
        """One field, by its `goldbox/dos_port.py` name.

        `U16LE` and `UINT_LE` fields are read big-endian, which is the whole
        of the difference outside the name and the shifts.
        """
        f = dos_port.FIELDS_BY_NAME.get(field_name)
        if f is None:
            raise AmigaRecordError(f"no field called {field_name!r}")
        at = amiga_por_offset(f.offset)
        chunk = self.raw[at:at + f.size]
        if f.kind in (Kind.U16LE, Kind.UINT_LE):
            return int.from_bytes(chunk, "big")
        if f.kind is Kind.I8:
            return int.from_bytes(chunk, "big", signed=True)
        if f.kind is Kind.U8:
            return chunk[0]
        return chunk

    @property
    def abilities(self) -> list[int]:
        return [self.get(k) for k in ("strength", "intelligence", "wisdom",
                                      "dexterity", "constitution", "charisma")]

    @property
    def experience(self) -> int:
        """Four bytes big-endian, the Amiga's `u32` where DOS keeps a `u32le`.

        The shift stays at +2 across all four bytes.  PROBABLE: 14 of 14
        Amiga specimens decode to experience totals in their class's band or
        just past a level cap.
        """
        at = amiga_por_offset(dos_experience_offset())
        return int.from_bytes(self.raw[at:at + 4], "big")

    @property
    def effect_chain(self) -> int:
        """The `.spc` chain head, `u32` big-endian where DOS keeps two words."""
        return int.from_bytes(self.raw[0x080:0x084], "big")

    @property
    def money(self) -> dict[str, int]:
        return {k: self.get(k) for k in
                ("copper", "silver", "electrum", "gold", "platinum", "gems",
                 "jewelry")}


def dos_experience_offset() -> int:
    return dos_port.FIELDS_BY_NAME["experience"].offset


def read_amiga_por(path) -> AmigaPorCharacter:
    """One Amiga Pool of Radiance `.cha` or `CHRDATA<n>.sav`.

    The sibling `.itm` and `.spc` are read too where they are there.  The
    record's own `item_count` is what says how many of the `.itm` belong to
    this character -- an export zeroes it, and a stale `.itm` left beside one
    would otherwise hand it somebody else's gear.  `goldbox/dos_codec.py` reads the DOS
    files the same way and for the same reason.
    """
    import pathlib

    path = pathlib.Path(path)
    return por_character(path.read_bytes(), _sibling_bytes(path, ".itm"),
                         _sibling_bytes(path, ".spc"), source=str(path))


def por_character(record: bytes, itm: bytes = b"", spc: bytes = b"",
                  source: str = "") -> AmigaPorCharacter:
    """One Amiga Pool of Radiance character, from the three files' bytes.

    What :func:`read_amiga_por` does once it has read the files, and the way
    in for a caller whose files are not on the host filesystem at all --
    :func:`read_por_slot` reads them straight out of an `.adf`.  The record's
    own `item_count` is what says how much of the `.itm` belongs here, and
    the shorter of the two wins, exactly as the path-based reader has it.
    """
    char = AmigaPorCharacter.from_bytes(record, source=source)
    count = min(char.get("item_count"), len(itm) // AMIGA_POR_ITEM_SIZE)
    items = [AmigaPorItem.from_bytes(
        itm[i * AMIGA_POR_ITEM_SIZE:(i + 1) * AMIGA_POR_ITEM_SIZE])
        for i in range(count)]
    effects = [spc[i:i + AMIGA_POR_EFFECT_SIZE]
               for i in range(0, len(spc), AMIGA_POR_EFFECT_SIZE)
               if len(spc[i:i + AMIGA_POR_EFFECT_SIZE]) == AMIGA_POR_EFFECT_SIZE]
    return AmigaPorCharacter.from_bytes(record, source, items, effects)


def _sibling_bytes(path, suffix: str) -> bytes:
    """A `.itm` or `.spc` beside the record, on either case of the name."""
    for candidate in (path.with_suffix(suffix), path.with_suffix(suffix.upper())):
        if candidate.exists() and candidate != path:
            return candidate.read_bytes()
    return b""


# ---------------------------------------------------------------------------
# The Amiga Pool of Radiance item file: 65 bytes where DOS spends 63
# ---------------------------------------------------------------------------
#
# `CHRDATA<n>.itm` beside the record, one 65-byte node per item, and the
# record's own `item_count` says how many belong to that character -- 3, 3, 3,
# 3, 3 and 2 against files of 195, 195, 195, 195, 195 and 130 bytes on the
# party shipped on Amiga disk 1, which is 6 of 6 exact.
#
# It is the DOS 63-byte record with **two insertions**, and the whole of the
# decode is one arithmetic identity that cannot be satisfied by accident:
# `money + sum(weight x quantity)` equals the record's own derived
# encumbrance word for **all six characters**, which fixes the money offsets,
# the 65-byte stride, the weight and quantity offsets and the byte order
# together.  Seventeen item nodes, nine distinct items; every weight is the
# published AD&D one (Long Sword 60, Chain Mail 300, Shield 100, Darts 5) and
# every value matches the price the item's own cached display line carries.
#
#   * DOS's count byte is gone.  The Amiga writes **NUL-separated text** from
#     offset 0 -- `Chain Mail\0Mail\0          75\0` -- so the display line is
#     the first NUL-terminated run, and 42 bytes serve where DOS spends a
#     length byte and 41.
#   * One pad in DOS `0x035`-`0x037`, which even-aligns the `u16` weight at
#     Amiga `0x038`.  Zero in all 17, so which of the three is UNKNOWN.
#   * One pad at Amiga `0x03B`, and this one **is** located to the byte:
#     quantity is measured at `0x03A` (60, on the only stack in the corpus,
#     against a display line reading `60 Darts`) and value at `0x03C`.
#
# `readied` at `0x034` is the flag `#55 (Decode the Amiga Curse and Silver
# Blades records)` could not confirm on Curse, where every specimen was
# readied: the un-readied darts read 0 here and their display line reads
# ` No `, and every other item reads 1 and draws ` Yes `.
AMIGA_POR_ITEM_SIZE = 65
#: Bytes of NUL-separated display text before the `next` pointer.
AMIGA_POR_ITEM_TEXT = 0x02A
#: `(first DOS item offset, bytes inserted before it)`, ascending.
AMIGA_POR_ITEM_SHIFTS = ((0x000, 0), (0x037, 1), (0x03A, 2))
#: The first insertion is one byte somewhere in here; all three read zero.
AMIGA_POR_ITEM_PAD_WINDOW = range(0x035, 0x038)
#: The second insertion, located to the byte between quantity and value.
AMIGA_POR_ITEM_PAD = 0x03B


def amiga_por_item_offset(dos_offset: int) -> int:
    """Where a DOS item offset lands in the Amiga one.

    Unlike the record's map this one never refuses: both insertions sit past
    the last field a caller reads by DOS offset, and the text field is
    re-cut rather than shifted.
    """
    shift = 0
    for first, amount in AMIGA_POR_ITEM_SHIFTS:
        if dos_offset >= first:
            shift = amount
    return dos_offset + shift


@dataclass(frozen=True)
class AmigaPorItem:
    """One 65-byte node of an Amiga Pool of Radiance `.itm` file."""

    raw: bytes

    @classmethod
    def from_bytes(cls, data: bytes | bytearray) -> "AmigaPorItem":
        if len(data) != AMIGA_POR_ITEM_SIZE:
            raise AmigaRecordError(
                f"an Amiga Pool of Radiance item is {AMIGA_POR_ITEM_SIZE} "
                f"bytes, got {len(data)}; the Amiga Curse item is 66 and the "
                f"DOS item is {dos_port.ITEM_SIZE}")
        return cls(bytes(data))

    def get(self, field_name: str):
        """One field, by its `goldbox/dos_port.py` item name, big-endian."""
        f = dos_port.ITEM_FIELDS_BY_NAME.get(field_name)
        if f is None:
            raise AmigaRecordError(f"no item field called {field_name!r}")
        at = amiga_por_item_offset(f.offset)
        chunk = self.raw[at:at + f.size]
        if f.kind in (Kind.U16LE, Kind.UINT_LE):
            return int.from_bytes(chunk, "big")
        if f.kind is Kind.I8:
            return int.from_bytes(chunk, "big", signed=True)
        if f.kind is Kind.U8:
            return chunk[0]
        return chunk

    @property
    def display_line(self) -> str:
        """The line the game last drew -- **never a source**.

        Stale by construction on both ports: the buffer is written over in
        place, so `Chain Mail\\0Mail\\0` is a short name sitting on the tail of
        a longer one, and the ` Yes `/` No ` column appears only on the items
        the ITEMS screen last painted it onto.  `goldbox/dos_codec.py` records the same
        of the DOS buffer, where a stack of darts reads `11 Darts` over a
        quantity of 8.
        """
        return self.raw[:AMIGA_POR_ITEM_TEXT].split(b"\0")[0].decode(
            "ascii", "replace")

    @property
    def next_node(self) -> int:
        """The heap address of the next item, `u32` big-endian, NULL last."""
        return int.from_bytes(self.raw[0x02A:0x02E], "big")

    def to_dos_bytes(self) -> bytes:
        """This item as the 63 bytes `goldbox/dos_port.py` describes.

        The `next` far pointer is written NULL rather than converted: it is a
        live Amiga heap address, and the DOS engine rebuilds its own chain
        from the file's length regardless (`goldbox/dos_codec.py`, `EFFECT_NEXT_NULL`
        records the same measurement for the effect chain).
        """
        out = bytearray(dos_port.ITEM_SIZE)
        text = self.raw[:AMIGA_POR_ITEM_TEXT]
        line = text.split(b"\0")[0]
        size = dos_port.ITEM_FIELDS_BY_NAME["text"].size
        out[0] = min(len(line), size)
        out[1:1 + size] = text[:size].ljust(size, b"\0")
        for f in dos_port.ITEM_LAYOUT:
            if f.name in ("text_length", "text", "next"):
                continue
            at = amiga_por_item_offset(f.offset)
            chunk = self.raw[at:at + f.size]
            if f.kind in (Kind.U16LE, Kind.UINT_LE):
                chunk = chunk[::-1]
            out[f.offset:f.offset + f.size] = chunk
        return bytes(out)


# ---------------------------------------------------------------------------
# The Amiga Pool of Radiance effect file: 10 bytes where DOS spends 9
# ---------------------------------------------------------------------------
# The two constants that name it, `AMIGA_POR_EFFECT_SIZE` and
# `AMIGA_POR_EFFECT_PAD`, are in `goldbox/amiga_port.py` with the
# rest of what an Amiga record looks like (#470).


def amiga_por_effect_to_dos(node: bytes) -> bytes:
    """One 10-byte Amiga `.spc` node as DOS's nine bytes.

    The duration is a `u16` big-endian at 2 where DOS keeps it little-endian
    at 1, and the four-byte next pointer is written NULL: it is a live heap
    address, and the DOS engine rebuilds the chain from the file's length --
    measured three ways under DOSBox-X, `goldbox/dos_codec.py`'s `EFFECT_NEXT_NULL`.
    """
    if len(node) != AMIGA_POR_EFFECT_SIZE:
        raise AmigaRecordError(
            f"an Amiga effect node is {AMIGA_POR_EFFECT_SIZE} bytes, "
            f"got {len(node)}")
    return bytes((node[0], node[3], node[2], node[4], node[5])) + bytes(4)


# ---------------------------------------------------------------------------
# Amiga Pool of Radiance -> the neutral record (#27)
# ---------------------------------------------------------------------------
#
# The reader's last mile, and it is a transposition rather than a second
# codec.  `to_dos_record` re-cuts the 288 bytes into the 285 `goldbox/dos_codec.py`
# already knows how to read, and `goldbox.dos_codec.to_neutral` does the rest -- so
# every grade, every drop and every provenance line the DOS side earned on 24
# specimens carries over, and there is no second neutral bridge to drift.
#
# What the re-cut has to do, and nothing else:
#
#   * the name -- 16 NUL-padded bytes become DOS's count byte and fifteen;
#   * the `u16` and `u32` fields -- big-endian becomes little-endian;
#   * experience -- one `u32` on the Amiga, DOS's four-byte `u32le`, so a
#     total above 16 777 215 is written in full;
#   * the two live pointers -- the effect chain and each item's `next` -- are
#     written NULL rather than converted.  They are Amiga heap addresses.
#
# One byte is **not** transposed: the Amiga's trailing pad at `0x11F`, which
# DOS does not have.  `field_83_87` is transposed like anything else --
# `0x084`-`0x088` are DOS's `0x083`-`0x087`, so the control byte and the
# treasure share cross.
DOS_RECORD_SIZE = dos_port.RECORD_SIZE


def _amiga_por_name(raw: bytes) -> tuple[int, bytes]:
    """The 16 NUL-padded bytes as DOS's count byte and fifteen."""
    text = raw[:AMIGA_POR_NAME_SIZE]
    line = text.split(b"\0")[0]
    size = dos_port.FIELDS_BY_NAME["name_text"].size
    return min(len(line), size), text[:size].ljust(size, b"\0")


def to_dos_record(char: AmigaPorCharacter) -> bytes:
    """The 288-byte Amiga record re-cut as the 285-byte DOS one.

    Not a conversion between games -- the same record in the other port's
    shape, so that `goldbox/dos_codec.py` can read it.  Every byte written came from a
    named Amiga field or is a documented zero; see the note above this
    function for the four rules and the one byte left behind, the Amiga's
    trailing pad at `0x11F`.
    """
    out = bytearray(DOS_RECORD_SIZE)
    count, text = _amiga_por_name(char.raw)
    out[0] = count
    out[1:1 + len(text)] = text

    exp = dos_port.FIELDS_BY_NAME["experience"]
    at = amiga_por_offset(exp.offset)
    out[exp.offset:exp.offset + 4] = int.from_bytes(
        char.raw[at:at + 4], "big").to_bytes(4, "little")

    skip = {"name_length", "name_text", "experience", "effect_chain"}
    for f in dos_port.LAYOUT:
        if f.name in skip:
            continue
        at = amiga_por_offset(f.offset)
        chunk = char.raw[at:at + f.size]
        if f.kind in (Kind.U16LE, Kind.UINT_LE):
            chunk = chunk[::-1]
        out[f.offset:f.offset + f.size] = chunk
    return bytes(out)


def to_dos_character(char: AmigaPorCharacter):
    """The whole Amiga character as the `goldbox.dos_codec.DosCharacter` the C64
    and DOS container writers take -- record, items and effects together.

    :func:`to_dos_record` re-cuts the 288 bytes; this is that plus the two
    sibling files, `AmigaPorItem.to_dos_bytes` and
    :func:`amiga_por_effect_to_dos` being the same re-cut for a 65-byte item
    node and a 10-byte effect node.  It is not a conversion between games --
    the same character in the other port's shape.

    `goldbox.dos_codec.write_c64_save` takes a `list[DosCharacter]` rather than a
    list of neutral records, because the combat figure crosses through
    `icon_head`, `icon_body`, `icon_colours` and `size`, which a neutral
    record has no field for; so this, and not :func:`to_neutral`, is what
    `#353 (Convert an Amiga Pool of Radiance save to the C64, so a party
    standing in the Slums on the Amiga arrives there in VICE)` hands it.
    """
    # Deferred: `goldbox.dos_codec` is the heavier module, and this and
    # :func:`to_neutral` are its only callers here.
    from . import dos_codec as _dos

    return _dos.DosCharacter(
        to_dos_record(char),
        [_dos.DosItem(it.to_dos_bytes()) for it in char.items],
        [amiga_por_effect_to_dos(e) for e in char.effects],
        source=char.source)


def to_neutral(char) -> NeutralCharacter:
    """One Amiga character in the neutral record, whichever title wrote it.

    The Amiga third of `goldbox/neutral.py`'s reader set, beside
    `goldbox.c64_codec.read` and `goldbox.dos_codec.to_neutral`.  It reports what it could
    not convert rather than filling it in: an item file the record's own count
    disagrees with, a name that fills all sixteen bytes, and the trailing pad
    DOS has no room for.

    An `AmigaCharacter` -- Curse or Silver Blades -- goes to
    :func:`to_neutral_later`, which reads its own title's field table.  The
    rest of this function is Pool of Radiance's, and re-cuts the record into
    the DOS one so that `goldbox.dos_codec.to_neutral` does the reading.

    **That includes the sheet portrait, and the table it uses is the right
    one.** The Amiga record stores the creation menu's position exactly as
    DOS does, `goldbox.dos_codec.to_neutral` falls back to
    `goldbox.portraits.neutral_menu`, and that is what the neutral record
    spells a position with on every port.  Passing the Amiga's own table in
    here would resolve the position against the Amiga's art numbering and
    hand the destination a byte in the wrong port's spelling (#480).
    """
    # Deferred, and the only reach out of this module: `goldbox/amiga_later.py`
    # is another title's codec and nothing else here touches it.
    from . import amiga_later

    if isinstance(char, amiga_later.AmigaCharacter):
        return amiga_later.to_neutral_later(char)
    # Deferred: `goldbox.dos_codec` is the heavier module and this is its only caller.
    from . import dos_codec as _dos

    out = _dos.to_neutral(to_dos_character(char))
    out.port = "Amiga"
    out.source = char.source
    out.warnings.append(
        "Read from a 288-byte Amiga Pool of Radiance record re-cut to the "
        "285-byte DOS one by goldbox.amiga_por.to_dos_record; the provenance lines "
        "name the DOS field table, which is the table both ports share")

    line, _ = _amiga_por_name(char.raw)
    if line >= dos_port.FIELDS_BY_NAME["name_text"].size:
        out.warnings.append(
            f"The Amiga name fills all {AMIGA_POR_NAME_SIZE} bytes with no "
            f"terminator; DOS holds fifteen, so it was truncated")
    stored = char.get("item_count")
    if stored != len(char.items):
        out.warnings.append(
            f"The record counts {stored} items and {len(char.items)} were "
            f"read from the .itm file; the shorter of the two was used")
    # No "DOS" (#389): this reader does not yet know which port the
    # character is going to -- an Amiga Pool of Radiance save converts to
    # the C64 as well as to DOS (`tests/convert/test_amigatoc64.py`), and naming DOS
    # here named the wrong destination for that direction.
    # No marker: a drop line goes to `wish/debuglog.py` and to a `--report`
    # printout, never to a pane, since Donald's ruling of 2026-09-08
    # (`.claude/rules/conversions.md`).  `editor/exports.py`, whose pane
    # once drew `report.dropped` for a C64 save, is deleted (`#52`), and no
    # pane reads this reader's drop text at all now.
    out.drop("Amiga 0x11F: the trailing pad, which the neutral record has "
             "no room for.")
    # There is no loop here reporting the effects the neutral record cannot
    # hold, and there should not be one.  `_dos.to_neutral`, called above,
    # now **converts** every non-innate node at duration zero in
    # `granted_effects` -- the same nodes, since `amiga_por_effect_to_dos`
    # recut them on the way in -- so an Amiga-to-Amiga or Amiga-to-DOS
    # conversion writes the ring's record back rather than losing it, and a
    # report line saying it was lost would be untrue.  Only a writer that
    # cannot take the field says so, which is `goldbox/c64_codec.py` and
    # `goldbox.amiga_pod.write_pod`, each in its own words.  A loop here
    # reported every loss twice while there was one
    # (#238 (An Amiga conversion's report shows an unconverted effect twice,
    # once from goldbox.amiga.to_neutral and once from goldbox.dos.to_neutral)).
    return out


def describe_unconverted_effect(node: bytes) -> str:
    """One drop line for a `.spc` node a destination cannot hold.

    Names what the character had, from the node's first byte, and leaves the
    caller to add why its own destination could not take it.  Only a writer
    that cannot take `granted_effects` says any of this: the neutral record
    holds the node, so DOS and Amiga write it back, and it is the C64 -- ten
    trait slots of one number each -- that has to explain itself.

    A node with rounds left never reaches here at all.  It was going to
    expire anyway, and Donald ruled on 2026-08-27 that those need no report;
    `goldbox.dos_codec.to_neutral` is where that line is drawn, on the duration.

    **What it says, and what it deliberately does not.** Donald's wording,
    2026-09-04: what the character had, and what it means for them. No
    effect id, no module name, no issue number -- `AGENTS.md` says anything
    a user reads in the interface carries no address or offset, and the
    lines already in this list had been carrying both. He was shown the
    longer form that named `goldbox.dos_codec.INNATE_EFFECTS` and `#232 (An
    item-granted effect is dropped on the way through the neutral record,
    with no report)` and took this one instead; finding the code from the
    effect's name is one grep, and the player is not the one who should be
    paying for it.
    """
    from . import traits

    # `[:1].upper()`, never `str.capitalize()`: `.claude/rules/gui-text.md`
    # bans it because it lower-cases the rest, and effect 61's own name is
    # "wearing a Ring of Fire Resistance" -- `capitalize()` renders that as
    # "Wearing a ring of fire resistance" and takes the item's name with it.
    said = traits.describe(node[0])
    return (f"{said[:1].upper()}{said[1:]}: the character "
            f"arrives without it")


# ---------------------------------------------------------------------------
# The neutral record -> Amiga Pool of Radiance (#105)
# ---------------------------------------------------------------------------
#
# The writing half of the reader above, and the same transposition run
# backwards: `goldbox.dos_codec.write` builds the 285-byte DOS record, its `.ITM` and
# its `.SPC` out of the neutral character, and everything here re-cuts those
# three into the Amiga's 288, 65 and 10.  There is no second field table and
# no second set of conversion rules -- a field DOS drops is dropped here for
# DOS's reason, and a field DOS derives is derived here by DOS's rule.
#
# The four rules `to_dos_record` names are simply reversed:
#
#   * the name -- DOS's count byte and fifteen become 16 NUL-padded bytes.
#     Composed rather than copied: the count says how much of the fifteen is
#     the name, and the rest is NUL.  Measured: all twenty genuine specimens
#     are NUL to the end of the sixteen, with nothing past the terminator;
#   * `u16` and `u32` fields -- little-endian becomes big-endian;
#   * experience -- DOS's `u32le` becomes one Amiga `u32be` at `0x0AE`;
#   * the two live pointers -- the effect chain at `0x080` and each item's
#     `next` at `0x02A` -- are written NULL.  The receiving engine allocates a
#     node per `.spc` record and per `.itm` record on load and relinks them
#     itself, which is what the reader measured in the other direction.
#
# Three bytes have no DOS source and are written rather than converted, and
# all three are pads:
#
#   * `0x07F`, the first insertion: zero in 20 of 20 specimens;
#   * `0x089`, the second, ahead of the `u16` money block: zero in 20 of 20;
#   * `0x11F`, the trailing pad: junk in 5 of 20 and zero in 15, which is what
#     an uninitialised pad looks like.  Zero is the value fifteen specimens
#     hold and it is what the writer emits.
#
# `field_83_87` itself is converted, at `0x084`-`0x088`, which is what carries
# a companion's control byte and his treasure share.  Placed there, the six
# records the game itself wrote on disk 1 read `00 00 01 00 00` -- DOS's own
# constant in 24 of 24 DOS records -- and the one companion among the twenty
# specimens reads `0xB2` at `0x085`, the byte `/program` writes at `0x00B196`
# while it builds a joining character's record.  `0xB3` is the other value it
# stores there, at `0x010290`, when it takes a character over.
#
# The window's other three bytes -- `0x084`, `0x087` and `0x088`, DOS's first,
# fourth and fifth -- cross as well, on
# `goldbox.dos_codec.set_window_source`, because no engine site reads them and
# so they have no neutral name.  The companion's `0xFF` at `0x084` is the one
# non-zero any of the three has shown in twenty specimens (#614).

#: The Amiga offset of the `u32be` experience total.
AMIGA_POR_EXPERIENCE = 0x0AE

#: Amiga record bytes with no DOS source: the three insertions and the live
#: heap pointer.  The round-trip test masks **this list** plus `goldbox.dos_codec`'s own
#: `WRITE_UNSOURCED`, `WRITE_CONSTANTS` and computed fields, rather than
#: whatever happens to differ -- so a new difference fails instead of being
#: absorbed.  `(first offset, size, why)`.
POR_WRITE_UNSOURCED: tuple[tuple[int, int, str], ...] = (
    (AMIGA_POR_PAD, 1,
     "the first insertion, a pad ahead of the effect pointer; zero in 20 of "
     "20 specimens, so zero is the value and not a guess"),
    (0x080, 4,
     "the effect chain: a live Amiga heap address. The engine allocates a "
     "node per .spc record on load and writes the head itself, which is what "
     "goldbox.dos_codec.WRITE_UNSOURCED records for the DOS field it maps onto"),
    (AMIGA_POR_MONEY_PAD, 1,
     "the second insertion, a pad ahead of the u16 money block; zero in 20 "
     "of 20 specimens, and the five bytes before it are DOS's field_83_87, "
     "which is converted rather than written"),
    (AMIGA_POR_TAIL_PAD, 1,
     "the trailing pad, which the 285-byte DOS record has no room for; zero "
     "in 15 of 20 and uninitialised junk in the other five"),
)

#: DOS fields the record writer places itself rather than through the shift
#: map: the name is re-cut and experience spans two DOS fields.
_POR_SPECIAL = frozenset({"name_length", "name_text", "experience"})


def _por_special(f) -> bool:
    """True for a DOS field `from_dos_record` writes by hand.

    A function rather than a bare `in` so the shift-map guard in
    `tests/amiga/test_amiga.py` asks the writer what it special-cases instead of
    keeping its own copy of the list and drifting from it.
    """
    return f.name in _POR_SPECIAL


#: The AmigaDOS drawer a Pool of Radiance save slot lives in, and the file
#: names inside it: `CHRDAT<slot><n>.sav` with `.itm` and `.spc` beside it,
#: read off disk 1 and confirmed by the game's own save to slot B (#28).
POR_SAVE_DRAWER = "save"
POR_PARTY_MAX = 6


def por_filename(slot: str, index: int, suffix: str = ".sav") -> str:
    """`CHRDATA1.sav` and its siblings, for slot `A` and index 1.

    The engine loads a party from the names in the saved game's character
    table rather than from the slot letter, but it writes them in this shape
    and the shipped disk carries them in it -- so anything we write uses it
    too.
    """
    if len(slot) != 1 or not slot.isalpha():
        raise AmigaRecordError(f"a save slot is one letter; got {slot!r}")
    if not 1 <= index <= POR_PARTY_MAX:
        raise AmigaRecordError(
            f"a Pool of Radiance party is 1 to {POR_PARTY_MAX}; got {index}")
    return f"CHRDAT{slot.upper()}{index}{suffix}"


@dataclass
class PorWriteReport(neutral.Report):
    """Where every byte of an Amiga Pool of Radiance write came from.

    Offsets `0` to `AMIGA_POR_RECORD_SIZE - 1` are the record;
    `AMIGA_POR_RECORD_SIZE` and up are the `.itm` payload and then the `.spc`.
    **Every** byte has to be explained, not only the non-zero ones -- which is
    where this differs from `Report` above and agrees with
    `goldbox.dos_codec.WriteReport`, because unlike the Pools of Darkness `.pc` this
    record's zeroes are fields rather than untouched heap.
    """

    total: int = AMIGA_POR_RECORD_SIZE

    @property
    def unaccounted(self) -> list[int]:  # type: ignore[override]
        """Offsets this conversion cannot explain. Should be empty."""
        return [i for i in range(self.total) if i not in self.sources]

    def summary_notes(self) -> list[str]:
        if self.unaccounted:
            return [f"  UNACCOUNTED: {len(self.unaccounted)} bytes"]
        return []


def _por_name_bytes(record: bytes) -> bytes:
    """DOS's count byte and fifteen as the Amiga's sixteen NUL-padded."""
    size = dos_port.FIELDS_BY_NAME["name_text"].size
    count = min(record[0], size)
    return record[1:1 + count].ljust(AMIGA_POR_NAME_SIZE, b"\0")


def from_dos_record(record: bytes) -> bytes:
    """The 285-byte DOS record re-cut as the 288-byte Amiga one.

    The exact inverse of :func:`to_dos_record` for every byte either port
    sources, and the note above this function says what happens to the three
    the Amiga has and DOS does not.
    """
    if len(record) != DOS_RECORD_SIZE:
        raise AmigaRecordError(
            f"a DOS Pool of Radiance record is {DOS_RECORD_SIZE} bytes, "
            f"got {len(record)}")
    out = bytearray(AMIGA_POR_RECORD_SIZE)
    out[:AMIGA_POR_NAME_SIZE] = _por_name_bytes(record)

    exp = dos_port.FIELDS_BY_NAME["experience"]
    assert amiga_por_offset(exp.offset) == AMIGA_POR_EXPERIENCE
    out[AMIGA_POR_EXPERIENCE:AMIGA_POR_EXPERIENCE + 4] = int.from_bytes(
        record[exp.offset:exp.offset + 4], "little").to_bytes(4, "big")

    for f in dos_port.LAYOUT:
        if _por_special(f):
            continue
        at = amiga_por_offset(f.offset)
        chunk = record[f.offset:f.offset + f.size]
        if f.kind in (Kind.U16LE, Kind.UINT_LE):
            chunk = chunk[::-1]
        out[at:at + f.size] = chunk
    # The effect chain is a live Amiga heap address; the engine rebuilds it.
    out[0x080:0x084] = bytes(4)
    return bytes(out)


def amiga_por_item_from_dos(item: bytes) -> bytes:
    """One DOS 63-byte item node as the Amiga's 65.

    The display text is left NUL and the `next` pointer NULL.

    **The chain is CONFIRMED**: the engine relinked one we wrote all-NULL, 17
    nodes of 17, and the last came back NULL (`docs/124-amiga-port.md`
    §1.12a).

    **The display text is CONFIRMED as a render the engine composes**, and
    leaving it NUL is right. Watched in Amiga Pool of Radiance under WinUAE on
    2026-09-05 (`docs/182-amiga-por-in-the-running-game.md`): a party whose 17
    item nodes all held 42 NUL bytes drew `YES LONG SWORD`, `YES BANDED MAIL`
    and `YES SHIELD` on its ITEMS screen, and a converted DOS character drew
    `YES FLAIL` and `YES BANDED MAIL`. Nothing in a row comes from this
    buffer: the name from `name1`, `name2` and `name3`, the ready column from
    `readied`, the count from `quantity` and the price from `value`.

    **And the engine writes the render back into the buffer, which is what
    makes it a cache.** Two nodes written NUL, loaded, drawn on ITEMS and
    saved came back holding `Flail \0lail \0` and `Banded Mail \0Mail \0` --
    the current render, then the tail of a longer earlier one, exactly the
    shape the game's own shipped nodes have. `' Yes  Flail '` is twelve
    characters and `'Flail \0'` is seven, so what survives from index 7 is
    `'lail '`; `' Yes  Banded Mail '` is eighteen against thirteen, leaving
    `'Mail '`. It is composed at least twice, once with the ready column and
    once without. Until ITEMS is opened the buffer stays NUL through a load, a
    camp and a save, which is why the earlier measurement said the engine did
    not compose it.
    """
    if len(item) != dos_port.ITEM_SIZE:
        raise AmigaRecordError(
            f"a DOS Pool of Radiance item is {dos_port.ITEM_SIZE} bytes, "
            f"got {len(item)}")
    out = bytearray(AMIGA_POR_ITEM_SIZE)
    for f in dos_port.ITEM_LAYOUT:
        if f.name in ("text_length", "text", "next"):
            continue
        at = amiga_por_item_offset(f.offset)
        chunk = item[f.offset:f.offset + f.size]
        if f.kind in (Kind.U16LE, Kind.UINT_LE):
            chunk = chunk[::-1]
        out[at:at + f.size] = chunk
    return bytes(out)


def amiga_por_effect_from_dos(node: bytes) -> bytes:
    """One DOS 9-byte `.SPC` record as the Amiga's 10.

    The inverse of :func:`amiga_por_effect_to_dos`: a pad at offset 1, the
    duration byte-swapped into `0x02`, and the four-byte next pointer NULL.
    """
    if len(node) != dos_port.EFFECT_SIZE:
        raise AmigaRecordError(
            f"a DOS effect record is {dos_port.EFFECT_SIZE} bytes, "
            f"got {len(node)}")
    return bytes((node[0], 0, node[2], node[1], node[3], node[4])) + bytes(4)


def write_por(char: NeutralCharacter,
             icon: "DosIcon | None" = None) -> tuple[bytes, bytes, bytes,
                                                      PorWriteReport]:
    """Build an Amiga Pool of Radiance record and its `.itm` and `.spc`.

    Returns `(record, itm, spc, report)`, the same shape `goldbox.dos_codec.write`
    returns -- and it is `goldbox.dos_codec.write` that does the conversion, because
    the Amiga record *is* the DOS record in another shape.  So every drop,
    every warning and every provenance line this report carries was earned on
    the DOS side against 24 DOS specimens, and the only lines added here are
    the three bytes the Amiga has and DOS does not.

    **A character carrying nothing gets no `.itm` file**, and an empty file is
    not the same thing as no file: `goldbox.dos_codec.ITM_OMITTED_WHEN_EMPTY` records
    what handing the DOS engine a zero-length one did (#62).  The caller sees
    `b""` and must not write a file for it.

    `icon` is this character's own combat figure -- `icon_head`, `icon_body`
    and the six `icon_colours` bytes -- passed straight through to
    `goldbox.dos_codec.write`'s own `icon` argument, the same bypass
    `goldbox.amiga_later.write_later` takes for Curse and Silver Blades (#396,
    #319, docs/199-amiga-combat-icons.md).  Build one with
    `goldbox.iconparts.amiga_combat_icon` for an Amiga or DOS source, or with
    `goldbox.iconparts.IconParts.dos_icon_from_c64` for a C64 source
    (#422).  With none given, `icon_head` and `icon_body` are written zero
    and `icon_colours` the game's own freshly-made default, exactly as
    before this parameter existed.

    **The sheet portrait crosses as a menu position**, resolved through
    `goldbox.portraits.neutral_menu` -- the same table every other direction
    resolves against, and deliberately not the Amiga's own.  All seven ports
    of Pool of Radiance draw the same twelve body slots in the same order:
    the slot is the character's identity and each port's stored byte is only
    its own index into its own art, so position 8 converts to position 8 and
    the Amiga engine then draws its own eighth body.  Asking here for
    `stored_tables(..., port="amiga")` instead looks a neutral value up in
    the wrong numbering and reports a drop for a body the Amiga offers
    (#480); `docs/188-the-sheet-portrait-per-title.md` opens with why that is
    settled.  `AMIGA_POOL_OF_RADIANCE_MENU` is for drawing the Amiga's art.
    """
    from . import dos_codec as _dos

    # `into="Amiga"` (#389, A conversion to the Amiga tells the player what
    # DOS does with their character): without it, a drop line this function
    # cannot place is composed as though it were a straight DOS write and
    # names DOS to a player who is not converting to DOS.
    record, itm, spc, dosrep = _dos.write(
        char, icon=icon, into="Amiga",
        portraits=neutral_menu(dos_port.POOL_OF_RADIANCE.key))
    out = from_dos_record(record)

    items = [amiga_por_item_from_dos(
        itm[n * dos_port.ITEM_SIZE:(n + 1) * dos_port.ITEM_SIZE])
        for n in range(len(itm) // dos_port.ITEM_SIZE)]
    effects = [amiga_por_effect_from_dos(
        spc[n * dos_port.EFFECT_SIZE:(n + 1) * dos_port.EFFECT_SIZE])
        for n in range(len(spc) // dos_port.EFFECT_SIZE)]
    amiga_itm = b"".join(items)
    amiga_spc = b"".join(effects)

    rep = PorWriteReport()
    rep.dropped = list(dosrep.dropped)
    rep.warnings = list(dosrep.warnings)
    rep.warnings.append(
        "Written as a 288-byte Amiga Pool of Radiance record by re-cutting "
        "the 285-byte DOS one built by goldbox.dos_codec.write; the provenance lines "
        "name the DOS field each byte was transposed from, which is the "
        "field table both ports share")
    # `#308 (Does Amiga Pool of Radiance drop the space out of a character's
    # name when it saves?)`: the engine strips every space out of every name
    # on its own first save, including a name typed into its own name-entry
    # box thirty seconds earlier -- nothing on our side causes it and
    # nothing on our side can prevent it, so the record keeps the player's
    # name with its space and this warns him what the game will do to it.
    # Silent for a name with no space, which the engine leaves alone.
    name_value = str(char.get("name", ""))
    if " " in name_value:
        rep.warnings.append(
            f"WARNING: Spaces in names are dropped on the Amiga. "
            f"{name_value} will become {name_value.replace(' ', '')}.")
    rep.total = AMIGA_POR_RECORD_SIZE + len(amiga_itm) + len(amiga_spc)

    def converted(name: str) -> str:
        f = dos_port.FIELDS_BY_NAME[name]
        return dosrep.sources.get(f.offset, f"{name}: no DOS provenance")

    rep.note(0, AMIGA_POR_NAME_SIZE,
             f"name: {AMIGA_POR_NAME_SIZE} NUL-padded bytes composed from "
             f"DOS's count byte and fifteen -- {converted('name_length')}")
    rep.note(AMIGA_POR_EXPERIENCE, 4,
             f"experience: one u32 big-endian from DOS's four-byte field -- "
             f"{converted('experience')}")
    rep.note(AMIGA_POR_PAD, 1,
             "0x07F: the first insertion, a pad ahead of the effect pointer. "
             "Zero in 20 of 20 Amiga specimens")
    rep.note(AMIGA_POR_MONEY_PAD, 1,
             "0x089: the second insertion, a pad ahead of the money block. "
             "Zero in 20 of 20 Amiga specimens")
    rep.note(AMIGA_POR_TAIL_PAD, 1,
             "0x11F: the trailing pad DOS has no room for. Zero in 15 of 20 "
             "specimens and uninitialised junk in the other five")

    for f in dos_port.LAYOUT:
        if _por_special(f):
            continue
        at = amiga_por_offset(f.offset)
        if f.name == "field_83_87":
            # Noted byte by byte: the control byte and the treasure share
            # carry their own DOS provenance, and one line for the whole run
            # would hide both behind the constant the rest of it holds.
            for i in range(f.size):
                rep.note(at + i, 1, dosrep.sources.get(
                    f.offset + i, converted(f.name)))
            continue
        rep.note(at, f.size, converted(f.name))

    for n in range(len(items)):
        base = AMIGA_POR_RECORD_SIZE + n * AMIGA_POR_ITEM_SIZE
        dos_base = _dos.RECORD_SIZE + n * dos_port.ITEM_SIZE
        rep.note(base, AMIGA_POR_ITEM_TEXT,
                 f"item {n}: the rendered-line cache, left NUL -- the game "
                 f"rewrites it whenever it draws the list")
        rep.note(base + 0x02A, 4,
                 f"item {n}: next pointer left NULL -- the loader rebuilds "
                 f"the chain")
        for f in dos_port.ITEM_LAYOUT:
            if f.name in ("text_length", "text", "next"):
                continue
            rep.note(base + amiga_por_item_offset(f.offset), f.size,
                     dosrep.sources.get(dos_base + f.offset,
                                        f"item {n}: {f.name}"))
        for pad in list(AMIGA_POR_ITEM_PAD_WINDOW) + [AMIGA_POR_ITEM_PAD]:
            if base + pad not in rep.sources:
                rep.sources[base + pad] = (
                    f"item {n}: pad at {pad:#05x}, zero in all 17 nodes read")

    base = AMIGA_POR_RECORD_SIZE + len(amiga_itm)
    dos_base = _dos.RECORD_SIZE + len(itm)
    for n in range(len(effects)):
        at = base + n * AMIGA_POR_EFFECT_SIZE
        dos_at = dos_base + n * dos_port.EFFECT_SIZE
        rep.note(at, 1, dosrep.sources.get(dos_at, f".spc record {n}: id"))
        rep.note(at + AMIGA_POR_EFFECT_PAD, 1,
                 f".spc record {n}: the extra byte, a pad. Zero in every "
                 f"Pool of Radiance and Curse record read (68)")
        # The Amiga keeps the duration big-endian where DOS keeps it little,
        # so the two bytes swap and the value and flag follow unchanged.
        rep.note(at + 2, 2,
                 dosrep.sources.get(dos_at + 1,
                                    f".spc record {n}: duration, byte-swapped"))
        rep.note(at + 4, 2,
                 dosrep.sources.get(dos_at + 3, f".spc record {n}: payload"))
        rep.note(at + 6, 4,
                 dosrep.sources.get(dos_at + 5,
                                    f".spc record {n}: next pointer NULL"))

    return out, amiga_itm, amiga_spc, rep


# ---------------------------------------------------------------------------
# A whole Amiga Pool of Radiance save slot, and the list the picker reads (#109)
# ---------------------------------------------------------------------------
#
# `save/save` is **the slot list**, not a note about which slot is current.
# Ten bytes, one per slot, indexed by letter: `A` is byte 0 and `J` is byte 9,
# and a slot that does not exist is a space.  `"A         "` on the shipped
# disk, `"AB        "` after the game saved to B (#36), and `"AB D      "`
# after it was made to save to D and then to B (#109) -- the gap at byte 2 is
# where `C` would go, and it is what says this is an array and not a list.
# A disk carrying a complete slot B that does not name B here is offered only
# `A` at the picker -- measured, one run wasted on it -- so a writer that puts
# the files down and leaves this alone has written a slot the player cannot
# load and reported success.
#
# Hence the rule this module enforces: **a slot that cannot be listed is not
# written.**  The feasibility check runs before anything touches the disk, and
# the list is read back afterwards, because a silent failure here is invisible
# until somebody boots the game.
#
# The saved game names its own party.  Six 41-byte entries at 12813 hold
# `CHRDATA1`...`CHRDATA6` as eight plain bytes with no count byte, and the
# engine loads from *those* names rather than from the slot letter -- which is
# why saving to slot B rewrote all six to `CHRDATB<n>` (#28, §1.9b).  So a
# saved game moved to another slot has to be pointed at the files it will
# actually find, or the party that loads is the one it came from.
