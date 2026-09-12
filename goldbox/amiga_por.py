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

import contextlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Sequence

from . import areas, dos_port, dos_savegame, neutral, world_state
from .amiga_adf import AmigaDisk, AmigaDiskError
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
# The three insertions, measured on fourteen specimens (#27):
#
#   * `0x07F` -- one pad byte, zero in 14 of 14, ahead of the effect-chain
#     pointer.  DOS keeps an offset word and a segment word there; the Amiga
#     keeps one `u32` and a 68000 compiler even-aligns it.
#   * somewhere in DOS `0x083`-`0x087` -- **located to a window, not a byte**.
#     That region is zero in 12 of the 14, so no file differential can place
#     it; what would is a ramp probe under the emulator.  The money block
#     that follows is `u16`, so alignment says the pad is at the end of the
#     window, but that is inference and is not graded.
#   * `0x11F`, the last byte -- 285 + 2 is odd, and the struct is padded to an
#     even size.  Junk in 3 of 14 and zero in the rest, which is what an
#     uninitialised pad looks like.
#
# So a DOS offset maps to an Amiga offset by adding 0 below `0x07F`, 1 through
# the effect pointer, and 2 from the money block on.
AMIGA_POR_RECORD_SIZE = 288
AMIGA_POR_NAME_SIZE = 16          # NUL-padded, where DOS has a count byte
AMIGA_POR_PAD = 0x07F             # the first insertion
AMIGA_POR_TAIL_PAD = 0x11F        # the third
#: `(first DOS offset, bytes inserted before it)`, ascending.
AMIGA_POR_SHIFTS = ((0x000, 0), (0x07F, 1), (0x088, 2))
#: DOS offsets whose Amiga counterpart cannot be placed: the second insertion
#: is somewhere inside this run, so every byte of it is suspect.
AMIGA_POR_UNPLACED = range(0x083, 0x088)


def amiga_por_offset(dos_offset: int) -> int:
    """Where a DOS record offset lands in the Amiga one.

    Raises for the unplaced window rather than guessing: a caller that wants
    those bytes has to say so and read them raw.
    """
    if dos_offset in AMIGA_POR_UNPLACED:
        raise AmigaRecordError(
            f"DOS offset {dos_offset:#05x} is inside {AMIGA_POR_UNPLACED.start:#05x}"
            f"-{AMIGA_POR_UNPLACED.stop - 1:#05x}, where the second insertion "
            f"has not been located; there is no Amiga offset to give")
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
        """Four bytes big-endian, spanning DOS's 24-bit field and `gap_0af`.

        The Amiga's field is `u32`, and the shift stays at +2 across it -- so
        DOS's unexplained `gap_0af` is experience's fourth byte and the DOS
        field is a `u32le`.  PROBABLE: 14 of 14 Amiga specimens decode to
        experience totals in their class's band or just past a level cap.
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
#   * experience -- one `u32` on the Amiga, spanning DOS's 24-bit field *and*
#     the byte `goldbox/dos_port.py` calls `gap_0af`.  PROBABLE: the DOS field
#     is a `u32le` and the gap is its fourth byte.  Written that way, which
#     is lossless either way round because the fourth byte is zero below
#     16 777 216 experience and no Gold Box character reaches it;
#   * the two live pointers -- the effect chain and each item's `next` -- are
#     written NULL rather than converted.  They are Amiga heap addresses.
#
# Two regions are **not** transposed and are reported instead of guessed:
#
#   * DOS `0x083`-`0x087`, where the second insertion has not been located.
#     Those five bytes are written zero, which is what the Amiga's own six
#     read in 11 of the 14 that could show anything.  DOS's own specimens
#     hold `00 00 01 00 00` in 24 of 24, and copying that constant in would
#     be putting a DOS value into a record built from an Amiga one --
#     inheriting rather than measuring.  `goldbox/dos_codec.py` drops the field anyway;
#   * the Amiga's trailing byte at `0x11F`, which DOS does not have.
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
    function for the four rules and the two regions left blank.
    """
    out = bytearray(DOS_RECORD_SIZE)
    count, text = _amiga_por_name(char.raw)
    out[0] = count
    out[1:1 + len(text)] = text

    exp = dos_port.FIELDS_BY_NAME["experience"]
    at = amiga_por_offset(exp.offset)
    out[exp.offset:exp.offset + 4] = int.from_bytes(
        char.raw[at:at + 4], "big").to_bytes(4, "little")

    skip = {"name_length", "name_text", "experience", "gap_0af",
            "field_83_87", "effect_chain"}
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
    disagrees with, a name that fills all sixteen bytes, and the unplaced
    window.

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
    out.drop("Amiga 0x083-0x087: the second insertion is not located, so "
             "those bytes were written zero rather than guessed")
    # No "DOS" (#389): this reader does not yet know which port the
    # character is going to -- an Amiga Pool of Radiance save converts to
    # the C64 as well as to DOS (`tests/test_amigatoc64.py`), and naming DOS
    # here named the wrong destination for that direction.
    # No marker: a drop line goes to `wish/debuglog.py` and to a `--report`
    # printout, never to a pane, since Donald's ruling of 2026-09-08
    # (`.claude/rules/conversions.md`).  `editor/exports.py`'s pane is the
    # one that still draws `report.dropped`, and it reads a C64 save rather
    # than an Amiga one, so no reader on this side reaches it.
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
#   * experience -- DOS's 24-bit field and `gap_0af` become one Amiga `u32be`
#     at `0x0AE`;
#   * the two live pointers -- the effect chain at `0x080` and each item's
#     `next` at `0x02A` -- are written NULL.  The receiving engine allocates a
#     node per `.spc` record and per `.itm` record on load and relinks them
#     itself, which is what the reader measured in the other direction.
#
# Three bytes have no DOS source and are written rather than converted:
#
#   * `0x07F`, the first insertion: zero in 20 of 20 specimens;
#   * `0x089`ish, the second: see AMIGA_POR_FIELD_83_87 below;
#   * `0x11F`, the trailing pad: junk in 5 of 20 and zero in 15, which is what
#     an uninitialised pad looks like.  Zero is the value fifteen specimens
#     hold and it is what the writer emits.

#: Amiga `0x084`-`0x089`: DOS's `field_83_87` under the `+1` shift, plus the
#: second insertion, whichever of the last three bytes it is.
#:
#: **This narrows the unplaced insertion and the measurement is new.**  DOS
#: holds `00 00 01 00 00` at `0x083`-`0x087` in 24 of 24 specimens.  On the
#: Amiga the `01` reads at `0x086` in **8 of 20** -- all six `CHRDATA<n>.sav`
#: the game itself wrote on disk 1, and two of the fourteen `.cha` exports --
#: and `0x086` is `amiga_por_offset(0x085)`, which is where DOS's `01` lands
#: if the insertion is *after* it.  A pad at `0x084`, `0x085` or `0x086` would
#: put the `01` at `0x087`, and no specimen reads 1 there.  So the insertion
#: is one of `0x087`, `0x088` and `0x089`; the other twelve specimens read six
#: zeros and say nothing either way.  All three candidates are zero in all
#: twenty, so these six bytes are right whichever of them it turns out to be.
AMIGA_POR_FIELD_83_87 = b"\x00\x00\x01\x00\x00\x00"
AMIGA_POR_FIELD_83_87_AT = 0x084
#: Where DOS's `01` lands in that window, and so the last Amiga offset the
#: shift map is now *measured* to place rather than merely to assume.
AMIGA_POR_INSERTION_AFTER = 0x086
#: What is left of the second insertion: one of these three, all zero in all
#: twenty specimens, which is why a writer does not have to know which.
#: `AMIGA_POR_UNPLACED` is deliberately **not** narrowed to match -- the
#: reader's refusal is a guard against guessing and this reading is PROBABLE,
#: resting on the DOS constant being the same field on both ports.
AMIGA_POR_INSERTION_CANDIDATES = (0x087, 0x088, 0x089)
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
    (AMIGA_POR_FIELD_83_87_AT, len(AMIGA_POR_FIELD_83_87),
     "DOS's field_83_87 plus the second insertion, written as the six bytes "
     "all six of the game's own disk-1 records hold; twelve of the fourteen "
     "exported .cha files hold six zeros instead, so this one is written "
     "rather than converted"),
    (AMIGA_POR_TAIL_PAD, 1,
     "the trailing pad, which the 285-byte DOS record has no room for; zero "
     "in 15 of 20 and uninitialised junk in the other five"),
)

#: DOS fields the record writer places itself rather than through the shift
#: map: the name is re-cut, experience spans two DOS fields, and the unplaced
#: window has no per-byte map to shift through.
_POR_SPECIAL = frozenset(
    {"name_length", "name_text", "experience", "gap_0af", "field_83_87"})


def _por_special(f) -> bool:
    """True for a DOS field `from_dos_record` writes by hand.

    A function rather than a bare `in` so the shift-map guard in
    `tests/test_amiga.py` asks the writer what it special-cases instead of
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

    out[AMIGA_POR_FIELD_83_87_AT:
        AMIGA_POR_FIELD_83_87_AT + len(AMIGA_POR_FIELD_83_87)] = \
        AMIGA_POR_FIELD_83_87

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
    `editor.convert.amiga_combat_icon` for an Amiga or DOS source, or with
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
             f"experience: one u32 big-endian spanning DOS's 24-bit field and "
             f"gap_0af -- {converted('experience')}")
    rep.note(AMIGA_POR_PAD, 1,
             "0x07F: the first insertion, a pad ahead of the effect pointer. "
             "Zero in 20 of 20 Amiga specimens")
    rep.note(AMIGA_POR_FIELD_83_87_AT, len(AMIGA_POR_FIELD_83_87),
             "0x084-0x089: DOS's field_83_87 constant plus the second "
             "insertion. 00 00 01 00 00 00 in all six records Amiga Pool of "
             "Radiance itself wrote on disk 1; the insertion is one of the "
             "last three bytes and all three are zero in all twenty")
    rep.note(AMIGA_POR_TAIL_PAD, 1,
             "0x11F: the trailing pad DOS has no room for. Zero in 15 of 20 "
             "specimens and uninitialised junk in the other five")

    for f in dos_port.LAYOUT:
        if _por_special(f):
            continue
        rep.note(amiga_por_offset(f.offset), f.size, converted(f.name))

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
POR_SLOT_LIST_NAME = "save"
POR_SLOT_LIST = f"/{POR_SAVE_DRAWER}/{POR_SLOT_LIST_NAME}"
POR_SLOT_LIST_SIZE = 10
#: Ten legal slots, which is exactly what the ten-byte list holds.
POR_SLOT_LETTERS = "ABCDEFGHIJ"
#: The volume a Pool of Radiance *save disk* carries, as against the game
#: disk's own `poolgame` (#36).
#:
#: `LOAD SAVED GAME` prompts `PATH FOR SAVE  RETURN = POOLSAVE:` and the
#: default is a **volume name**, not a drawer on the game disk -- which is why
#: a bare RETURN on the game disk raises Kickstart's *please insert volume
#: POOLSAVE* requester and `docs/124-amiga-port.md` §1.8 had to type `SAVE/`
#: instead.  `Put save disk in any drive` sits beside both the load and the
#: save path in `/program`, and "any drive" is what a volume lookup means.
POR_SAVE_VOLUME = "POOLSAVE"
POR_SAVEGAME_SIZE = 13141
POR_CHARACTER_TABLE = 12813
POR_CHARACTER_TABLE_STRIDE = 41
POR_CHARACTER_TABLE_NAME = 8


def _por_slot_letter(slot: str) -> str:
    """One of the ten letters the list can hold, upper-cased, or a refusal.

    `len` first: `"AB" in "ABCDEFGHIJ"` is true, and a membership test on its
    own would accept a two-letter slot and write files nobody can load.
    """
    letter = slot.upper()
    if len(letter) != 1 or letter not in POR_SLOT_LETTERS:
        raise AmigaRecordError(
            f"a Pool of Radiance save slot is one of {POR_SLOT_LETTERS}; "
            f"got {slot!r}")
    return letter


def por_savegame_filename(slot: str) -> str:
    """`savgamA.dat`, the case the shipped disk uses."""
    return f"savgam{_por_slot_letter(slot)}.dat"


def por_save_path(name: str, drawer: str = POR_SAVE_DRAWER) -> str:
    """Where a save file sits, given which kind of disk it is on (#36).

    The game builds every one of these names by sticking a filename on the
    end of whatever the player typed at `PATH FOR SAVE`, so the answer to
    that prompt is the whole difference between the two shapes:

    | answered | opens | `drawer` |
    |---|---|---|
    | `SAVE/` on the game disk | `SAVE/save` | `"save"` |
    | `POOLSAVE:`, the prompt's own default | `POOLSAVE:save` | `""` |

    An empty `drawer` is therefore the root of a save disk, and it is a real
    case rather than a degenerate one: it is what the game asks for when the
    player presses RETURN.
    """
    return f"/{drawer}/{name}" if drawer else f"/{name}"


def _remove_if_there(disk, path: str) -> bool:
    """Delete `path` if the disk has one, and say whether it did.

    Narrow on purpose, and that is the whole reason it exists: the only thing
    it swallows is the file not being there, which is the ordinary case when a
    slot is written over a shorter party.  A blind `except Exception` around
    `remove_file` would also swallow a looping hash chain and a drawer where a
    file was expected, and leave the disk half rewritten with nothing said.
    """
    try:
        entry = disk.lookup(path)
    except AmigaDiskError:
        return False
    if entry.is_dir:
        raise AmigaRecordError(
            f"{path!r} is a drawer on this disk, not a save file; refusing to "
            f"remove it")
    disk.remove_file(path)
    return True


@contextlib.contextmanager
def _all_or_nothing(disk):
    """Put the disk back exactly as it was if anything inside raises.

    `AmigaDisk.write_file` allocates the replacement before it frees the
    original (§1.10), so a write that runs the disk out of blocks stops part
    way through and leaves a filesystem that is neither what it was nor what
    it meant to be.  A slot is several files, so the window is several writes
    wide: three characters of six on the disk is exactly the state
    :func:`write_por_slot` exists to refuse.

    The snapshot is the whole image and the undo is `AmigaDisk.restore`, which
    is cheap enough at 880K that being clever about it would buy nothing.
    """
    snapshot = disk.to_bytes()
    try:
        yield
    except BaseException:
        disk.restore(snapshot)
        raise


def read_slot_list(disk, drawer: str = POR_SAVE_DRAWER) -> list[str]:
    """The slots the picker will offer.

    A disk with no `save/save` returns an empty list: the file is what the
    picker reads, so a disk without one offers nothing whatever else is in
    the drawer.

    Any letter counts wherever it sits, rather than only in its own byte.
    The game writes each letter at its own index (:func:`slot_list_bytes`), so
    on a disk the game wrote the two readings agree; a letter out of place is
    a file somebody else made badly, and reading it as present and writing it
    back in its proper place is a repair rather than a loss.
    """
    try:
        raw = disk.read_file(por_save_path(POR_SLOT_LIST_NAME, drawer))
    except AmigaDiskError:
        return []
    out: list[str] = []
    for byte in raw[:POR_SLOT_LIST_SIZE]:
        letter = chr(byte).upper()
        if letter in POR_SLOT_LETTERS and letter not in out:
            out.append(letter)
    return out


def slot_list_bytes(slots: Sequence[str]) -> bytes:
    """The ten bytes for a set of slots: each letter in its own place.

    **The file is a ten-slot array indexed by letter, not a list**, so the
    order the letters are given in cannot matter: `A` is byte 0 and `J` is
    byte 9, and a slot that does not exist is a space.  Measured in the
    running game on 2026-09-01 (#109) -- Amiga Pool of Radiance was made to
    save to `D` and then to `B` from one loaded party, and `save/save` came
    back `"AB D      "`, with the gap at byte 2 where `C` would go.  That is
    neither the sorted `ABD` nor the creation-order `ADB` this module used to
    guess between; both would have closed the gap.

    So a compacted list is wrong even though the picker would still draw the
    same four letters from it: the game reads this array back into memory and
    stores the next save's letter at that letter's own index, which in a
    compacted list is somebody else's entry.
    """
    out = bytearray(b" " * POR_SLOT_LIST_SIZE)
    for slot in slots:
        letter = _por_slot_letter(slot)
        out[POR_SLOT_LETTERS.index(letter)] = ord(letter)
    return bytes(out)


def por_save_drawer(disk) -> str:
    """Which of the two shapes of Pool of Radiance save disk this one is (#36).

    The game builds every save name by sticking a filename on the end of
    whatever the player answered at `PATH FOR SAVE`, and there are two
    answers.  On the game's own disk 1 the saves sit in a `save` drawer, so
    `/save` is a **drawer** holding the slot-list file `/save/save`; on a
    `POOLSAVE` save disk they sit at the root, so `/save` is the slot-list
    **file** itself.  That one difference is the whole test, and it is read
    off the disk rather than passed in by a caller who would have to know.

    Returns the drawer name :func:`por_save_path` takes -- `"save"` or the
    empty string.  A disk with no `/save` at all has never had a game saved
    to it and is refused, because every other answer here would be a guess
    about a disk that holds no saves either way.
    """
    try:
        entry = disk.lookup(f"/{POR_SAVE_DRAWER}")
    except AmigaDiskError:
        raise AmigaRecordError(
            f"{disk.volume_name!r} has no {POR_SLOT_LIST_NAME!r}, so it is "
            f"neither a Pool of Radiance game disk with a save drawer nor a "
            f"POOLSAVE save disk") from None
    return POR_SAVE_DRAWER if entry.is_dir else ""


def por_slots_present(disk, drawer: str | None = None) -> list[str]:
    """The slot letters this disk actually holds files for, A first.

    **Not `read_slot_list`, and the two answer different questions.** That
    one reads `save/save`, the ten-byte array the picker draws its menu
    from; this one asks which slots have a `savgam<letter>.dat` and a first
    character file to read.  A slot the picker offers and the disk has lost
    the files for would be listed by the first and not by the second, and it
    is the second a reader wants.
    """
    drawer = por_save_drawer(disk) if drawer is None else drawer
    out = []
    for letter in POR_SLOT_LETTERS:
        try:
            disk.lookup(por_save_path(por_savegame_filename(letter), drawer))
            disk.lookup(por_save_path(por_filename(letter, 1), drawer))
        except AmigaDiskError:
            continue
        out.append(letter)
    return out


#: An Amiga party standing on the travel grid used to be refused as the
#: *source* of a conversion, because no Amiga saved game made outdoors had
#: ever been read.  Two saved games the Amiga game itself made on the
#: travel grid -- the run of `#321 (An Amiga Pool of Radiance conversion
#: refuses a party standing on the travel grid, because no outdoor Amiga
#: saved game has ever been read)`, 2026-09-07 -- hold the travel square at
#: `goldbox.dos_savegame.TRAVEL_X` and `TRAVEL_Y`, exactly where the DOS
#: container keeps it: `(7, 29)` and `(7, 28)` against `20,29` and `20,28`
#: on the game's own status line, which prints the world coordinate where
#: the save holds the window-local one.  So the map `docs/196-the-amiga-
#: saved-game-built.md` §2 gives holds outdoors as well, on 2 of 2, and
#: reading an outdoor Amiga save is a measured thing rather than a guess --
#: `#376 (An Amiga party on the travel grid still cannot be converted to the
#: C64 or DOS, because the reader refuses one)` lifted the guard.


def read_por_state(savgam: bytes, source: str = "") -> "world_state.WorldState":
    """An Amiga slot's saved game, as the place and clock a writer takes.

    The reader for every conversion whose **source** is an Amiga Pool of
    Radiance slot -- `#353 (Convert an Amiga Pool of Radiance save to the
    C64, so a party standing in the Slums on the Amiga arrives there in
    VICE)` and `#354 (Convert an Amiga Pool of Radiance save to DOS, so a
    party standing in the Slums on the Amiga arrives there under DOSBox)`
    both call it.  Reads a party on the travel grid rather than refusing
    one, since `#376 (An Amiga party on the travel grid still cannot be
    converted to the C64 or DOS, because the reader refuses one)`.

    `goldbox.world_state.from_amiga` does the reading and refuses nothing;
    :func:`por_state_from_amiga` is the same reader for the other
    direction, where the Amiga file is the one being written.
    """
    if len(savgam) != POR_SAVEGAME_SIZE:
        raise AmigaRecordError(
            f"an Amiga Pool of Radiance saved game is {POR_SAVEGAME_SIZE} "
            f"bytes, got {len(savgam)}")
    return world_state.from_amiga(savgam, source=source)


def _por_slot_file(disk, letter: str, index: int, suffix: str,
                   drawer: str) -> "bytes | None":
    """One character's `.sav`, `.itm` or `.spc`, or `None` when it is absent.

    Absence is the ordinary case for all three: a party of four leaves
    `CHRDAT<slot>5.sav` off the disk entirely, and a character carrying
    nothing has no `.itm`.  `read_amiga_por` answers the same question with
    `_sibling_bytes` on the host filesystem.
    """
    try:
        return disk.read_file(
            por_save_path(por_filename(letter, index, suffix), drawer))
    except AmigaDiskError:
        return None


def read_por_slot(disk, slot: str, drawer: str | None = None):
    """One Amiga save slot: its party, and the saved game around it.

    `(list[goldbox.dos_codec.DosCharacter], savgam_bytes)` -- the pair
    `goldbox.dos_codec.write_c64_save` and `goldbox.dos_codec.new_dos_save_from` take,
    once `goldbox.world_state.from_amiga` has turned the second into a
    place and a clock.  This is the Amiga end of
    `#353 (Convert an Amiga Pool of Radiance save to the C64, so a party
    standing in the Slums on the Amiga arrives there in VICE)` and
    `#354 (Convert an Amiga Pool of Radiance save to DOS, so a party
    standing in the Slums on the Amiga arrives there under DOSBox)`.

    `tools/porslot.py`'s `read_slot` does the same reading through a
    temporary directory, because `read_amiga_por` wanted a path.  This one
    reads the blocks straight off the `AmigaDisk` -- the `.sav`, the `.itm`
    and the `.spc` of each character, and then the slot's own
    `savgam<letter>.dat` -- so nothing is written to the host filesystem to
    convert a save.

    **The party stops at the first missing `.sav`.**  The engine fills the
    saved game's character table only as far as the party goes
    (:func:`retarget_savegame`), and a one-character slot is a real case:
    `work/issue105`'s `savgamE.dat` is one the Amiga game itself wrote.

    Raises `AmigaRecordError` for a slot with no characters and for one with
    characters and no saved game -- the second being a half-written disk
    rather than an absent slot, which is why it is a different sentence.
    """
    letter = _por_slot_letter(slot)
    drawer = por_save_drawer(disk) if drawer is None else drawer
    party = []
    for index in range(1, POR_PARTY_MAX + 1):
        here = [_por_slot_file(disk, letter, index, suffix, drawer)
                for suffix in (".sav", ".itm", ".spc")]
        if here[0] is None:
            break
        party.append(to_dos_character(por_character(
            here[0], here[1] or b"", here[2] or b"",
            source=f"{disk.volume_name}:"
                   f"{por_save_path(por_filename(letter, index), drawer)}")))
    if not party:
        raise AmigaRecordError(
            f"slot {letter} has no {por_filename(letter, 1)} on "
            f"{disk.volume_name!r}")
    try:
        savegame = disk.read_file(
            por_save_path(por_savegame_filename(letter), drawer))
    except AmigaDiskError:
        raise AmigaRecordError(
            f"slot {letter} has {len(party)} character file(s) on "
            f"{disk.volume_name!r} but no "
            f"{por_savegame_filename(letter)}, so there is nothing to say "
            f"where the party is standing") from None
    if len(savegame) != POR_SAVEGAME_SIZE:
        raise AmigaRecordError(
            f"an Amiga Pool of Radiance saved game is {POR_SAVEGAME_SIZE} "
            f"bytes, got {len(savegame)}")
    return party, savegame


def retarget_savegame(save: bytes, slot: str) -> bytes:
    """Point a saved game's character table at another slot's files.

    Entries of eight plain bytes at 12813, stride 41: `CHRDATA1` becomes
    `CHRDATB1` and so on.  The engine loads the party named here rather than
    the party named by the slot letter, so a saved game copied to another slot
    without this loads the party it came from -- measured the other way round,
    by the game's own save to slot B rewriting all six (#28 §1.9b).

    **Only the entries that hold a name are rewritten, because the engine
    fills only as many as the party has** (#316).  `savgamE.dat` of
    `work/issue105`, which Amiga Pool of Radiance itself wrote for a
    one-character party, holds `CHRDATE1` in entry 0 and Amiga heap addresses
    in entries 1 to 7; this used to demand a `CHRDAT` name in all six and
    would have refused it.  A saved game with none at all is still refused,
    which is what keeps the guard: that is a file this function has been
    handed by mistake.
    """
    letter = _por_slot_letter(slot)
    if len(save) != POR_SAVEGAME_SIZE:
        raise AmigaRecordError(
            f"an Amiga Pool of Radiance saved game is {POR_SAVEGAME_SIZE} "
            f"bytes, got {len(save)}")
    out = bytearray(save)
    named = 0
    for n in range(POR_PARTY_MAX):
        at = POR_CHARACTER_TABLE + n * POR_CHARACTER_TABLE_STRIDE
        if not out[at:at + POR_CHARACTER_TABLE_NAME].startswith(b"CHRDAT"):
            continue
        out[at + 6] = ord(letter)
        named += 1
    if not named:
        raise AmigaRecordError(
            f"no entry of the character table at {POR_CHARACTER_TABLE} holds "
            f"a CHRDAT<slot><n> name; this is not a saved game this function "
            f"can point at another slot")
    return bytes(out)


def write_por_slot(disk, slot: str, characters: Sequence[NeutralCharacter],
                   savegame: bytes | None = None,
                   drawer: str = POR_SAVE_DRAWER,
                   icons: "list | None" = None) -> list[str]:
    """Write a whole save slot onto an Amiga disk, slot list and all.

    Returns the paths written, in the order they were written.  `disk` is an
    open `goldbox.amiga_adf.AmigaDisk`, which is mutated in place -- the caller
    decides whether to `save()` it, so a run that raises leaves the caller's
    file untouched.

    **It refuses a slot it cannot list.**  The check runs before anything is
    written, and the list is read back off the disk afterwards; a slot the
    picker will not offer is a slot the player cannot load, so writing one and
    reporting success is worse than refusing (#109).

    **And it is all or nothing.**  Every write happens inside
    :func:`_all_or_nothing`, so a disk that runs out of blocks half way
    through a six-character party comes back byte for byte as it was.

    `savegame` is pointed at this slot's own character files if it is given.
    Without one the character files land in the drawer and the slot still
    cannot be loaded, so it is required unless the slot already has a saved
    game of its own.

    `drawer` is `save` for a copy of the game disk and `""` for the root of a
    `POOLSAVE` save disk -- see :func:`por_save_path`, which is the whole of
    the difference between the two.

    `icons` is each character's own `goldbox.iconparts.DosIcon`, `None`
    where there is none, in the same order as `characters` -- `write_por`'s
    own `icon` argument, threaded through per character (#422). Left out,
    every character's icon is `None` and every figure is written zero,
    exactly as before this parameter existed.
    """
    if icons is None:
        icons = [None] * len(characters)
    letter = _por_slot_letter(slot)
    if not 1 <= len(characters) <= POR_PARTY_MAX:
        raise AmigaRecordError(
            f"a Pool of Radiance party is 1 to {POR_PARTY_MAX} characters; "
            f"got {len(characters)}")

    with _all_or_nothing(disk):
        # Feasibility first: nothing is written for a slot the picker will not
        # be told about.
        wanted = slot_list_bytes(read_slot_list(disk, drawer) + [letter])

        savegame_path = por_save_path(
            por_savegame_filename(letter), drawer)
        if savegame is None:
            try:
                disk.lookup(savegame_path)
            except AmigaDiskError:
                raise AmigaRecordError(
                    f"slot {letter} has no {savegame_path} on this disk and "
                    f"none was given; the character files alone are not a "
                    f"slot the game can load") from None

        written: list[str] = []
        for index, (char, icon) in enumerate(zip(characters, icons), start=1):
            record, itm, spc, rep = write_por(char, icon=icon)
            if rep.unaccounted:
                raise AmigaRecordError(
                    f"{len(rep.unaccounted)} bytes of character {index} have "
                    f"no provenance; refusing to write an unexplained record")
            stem = por_save_path(por_filename(letter, index, ""), drawer)
            disk.write_file(stem + ".sav", record)
            written.append(stem + ".sav")
            for suffix, payload in ((".itm", itm), (".spc", spc)):
                if payload:
                    disk.write_file(stem + suffix, payload)
                    written.append(stem + suffix)
                else:
                    # A character carrying nothing gets no file, and a stale
                    # one from whoever held this slot before would hand him
                    # somebody else's gear -- the engine reads the record's
                    # own count, but the file is what the count indexes into.
                    _remove_if_there(disk, stem + suffix)

        # Any file the previous occupant of this slot left for a character
        # this party does not have. A six-character save followed by a
        # four-character one would otherwise leave CHRDAT?5 and CHRDAT?6 on
        # the disk, loadable and belonging to somebody else.
        for index in range(len(characters) + 1, POR_PARTY_MAX + 1):
            stem = por_save_path(por_filename(letter, index, ""), drawer)
            for suffix in (".sav", ".itm", ".spc"):
                _remove_if_there(disk, stem + suffix)

        if savegame is not None:
            disk.write_file(savegame_path,
                            retarget_savegame(savegame, letter))
            written.append(savegame_path)

        slot_list = por_save_path(POR_SLOT_LIST_NAME, drawer)
        disk.write_file(slot_list, wanted)
        written.append(slot_list)
        if letter not in read_slot_list(disk, drawer):
            raise AmigaRecordError(
                f"slot {letter} is still not in {slot_list} after writing "
                f"it; the picker would not offer it")
        return written


#: The empty file the game disk ships in its save drawer, listing the
#: characters `ADD CHARACTER TO PARTY` can reach.  Zero bytes on disk 1, and
#: `/program` opens it by name for reading; a save disk without one would meet
#: `file not found,check your save path` the first time somebody opened that
#: menu.  One block, so it goes on every disk this writes.
POR_CHARACTER_LIST_NAME = "charlist.txt"


def make_por_save_disk(slot: str, characters: Sequence[NeutralCharacter],
                       savegame: bytes,
                       volume: str = POR_SAVE_VOLUME,
                       icons: "list | None" = None) -> AmigaDisk:
    """A save disk with one slot on it, formatted from nothing (#36).

    This is what a player can actually be handed: an 880K OFS floppy named
    `POOLSAVE` carrying a converted party and no game code at all.  Put it in
    any drive beside the game disk and the answer to `PATH FOR SAVE  RETURN =
    POOLSAVE:` is RETURN -- the prompt's own default, which is a volume name
    rather than a drawer, and which is why `Put save disk in any drive` sits
    beside both the load and the save path in the game's own `/program`.

    `savegame` is the 13,141-byte `savgam<letter>.dat` the slot is wrapped in.
    It used to have to come off the player's game disk; since #316 it is built
    from the save being converted by :func:`new_por_savegame`, so the party
    arrives on its own square at its own clock rather than on SSI's.  The
    caller builds it, because only the caller knows which save is being
    converted and which Amiga disk 2 the area's script can be read from.

    `icons` is :func:`write_por_slot`'s own argument, passed straight
    through -- each character's own `goldbox.iconparts.DosIcon`, `None`
    where there is none, in the same order as `characters` (#422).
    """
    disk = AmigaDisk.blank(volume)
    disk.write_file(por_save_path(POR_CHARACTER_LIST_NAME, ""), b"")
    write_por_slot(disk, slot, characters, savegame, drawer="", icons=icons)
    return disk


# ---------------------------------------------------------------------------
# The Amiga Pool of Radiance saved game, built rather than copied (#316)
# ---------------------------------------------------------------------------
#
# `savgam<letter>.dat` is where the party is standing, what time it is and how
# far through the story it has got, and until this existed a converted party
# was wrapped in one copied off the player's own disk 1 -- so the party was
# theirs and the place, the clock and the quest flags were SSI's.  That is a
# template, and `.claude/rules/conversions.md` rules it out: every byte nobody
# has attributed silently keeps a value belonging to a different party in a
# different place.
#
# **The DOS map is the Amiga map.**  `docs/141-dos-savegame.md` was established
# by differential analysis under DOSBox, and the same addresses hold the same
# meanings here, big-endian, because the three ports share one ECL address
# space.  Read against the shipped `savgamA.dat`, which is a New Phlan party:
# `$49FE` = 10 is `ECL00`'s own constant, `$4FD2`/`$4FD3` = (1, 101) is New
# Phlan's rest pair, `$4AFA`-`$4AFC` = (0, $FFFF, $FFFF) is New Phlan's
# wallset triple, `$5012` = 3 is New Phlan's container, and `$5082` = `$5200`
# = tail byte 12804 exactly as the DOS page says.  So this is `goldbox.dos_codec`'s
# `savgam_writes` in another endianness rather than a second map.
#
# **The four bytes between the two files** (13141 against DOS's 13137): the
# Amiga has no container byte at the front, and its tail is thirteen bytes
# where DOS's is eight.  The five extra are 12805-12809 -- two the square
# struct pads to and the first three of wallset entry 0, which the game's
# 10-byte write runs into -- and nothing reads any of them.  5 - 1 = 4.
#
# **The corpus cannot settle a field and this is why.**  There are ten distinct
# Amiga Pool of Radiance saved games on this machine, the shipped one and nine
# the engine wrote, and every one of them is at (0,4) facing west at 05:48 in
# New Phlan.  Diffing all ten gives 148 differing bytes, every one of them the
# party size or inside the 328-byte character table; the whole variable array
# and the whole script buffer are identical.  So no Amiga saved game here can
# be differenced into a map, the map has to come from the code and from the
# DOS page, and the proof has to come from the running game.

#: The variable array: 2560 big-endian words at the front of the file, indexed
#: by the ECL address the bytecode itself uses.  DOS spends a container byte
#: ahead of its copy and the Amiga does not, which is why the offset has no
#: `+ 1` in it.
POR_VAR_BASE = 0x4900
POR_VAR_WORDS = 2560
POR_VAR_OFFSET = 0
POR_VAR_LAST = POR_VAR_BASE + POR_VAR_WORDS - 1

#: `(start, end)` of the staged area script, and how much of the `.dax` block
#: is header rather than script.  Live on load: DOS dies in `Load3DMap` when
#: the buffer holds somebody else's area (#60), and the Amiga loader reads the
#: same buffer back into the same globals.
POR_ECL_BUFFER = (5120, 12800)
POR_ECL_HEADER = 2

#: The thirteen-byte tail, in the order the save routine writes it.
POR_POS_X, POR_POS_Y, POR_POS_FACING = 12800, 12801, 12802
#: The wall art in front of the party, `fn(x, y, facing)`, recomputed by the
#: step routine at `/program` `0x2ec1c`.
POR_WALL_BYTE = 12803
#: What the engine leaves in :data:`POR_WALL_BYTE` **outdoors**, where there
#: is no wall in front of anybody: 14, in both engine-written outdoor Amiga
#: saved games (`#321 (An Amiga Pool of Radiance conversion refuses a party
#: standing on the travel grid, because no outdoor Amiga saved game has ever
#: been read)`, 2026-09-07).  It did not move across an overland step that
#: changed the square and the facing, and it is the same 14 DOS's own
#: engine-written outdoor saves hold at `goldbox.dos_savegame.SCRATCH_BYTE`.
POR_WALL_OUTDOORS = 14
#: A square property, `fn(x, y)` at `0x2ec54`, and the low byte of `$5200`.
#: The two engine-written outdoor saves hold 1 here with `$5200` = 1, keeping
#: that relationship; this writer leaves `$5200` zero, so it writes zero.
POR_SQUARE_PROPERTY = 12804
#: `(start, end)` of the five bytes nothing reads: two the struct pads to and
#: the first three of wallset entry 0.  The write is ten bytes long and the
#: struct is seven (`docs/165-amiga-savegame.md`).
POR_SQUARE_PAD = (12805, 12810)
#: The view type.  The code beside the write names **1 = 3D and 2 = overland**
#: and that second value is not what the engine stores: two saved games the
#: Amiga game itself made on the travel grid hold **3**, which is what DOS
#: holds at `goldbox.dos_savegame.VIEW_MODE_BYTE` in 10 of 10 outdoor
#: specimens.  So the two ports agree after all, and 2 belongs to a mode
#: nothing here has seen -- `#321 (An Amiga Pool of Radiance conversion
#: refuses a party standing on the travel grid, because no outdoor Amiga
#: saved game has ever been read)`, 2026-09-07.
POR_VIEW_TYPE = 12810
POR_VIEW_TYPE_3D = 1
POR_VIEW_TYPE_OVERLAND = 3
#: What the code beside the write calls the overland, and what no saved game
#: on this machine has ever held.  Kept named so the disagreement above is
#: readable rather than looking like a typo.
POR_VIEW_TYPE_CODE_OVERLAND = 2
#: The game mode.  A save is taken from camp, so this is 2 in every saved game
#: the engine writes -- all ten here.
POR_GAME_MODE = 12811
POR_GAME_MODE_CAMP = 2
POR_PARTY_SIZE_BYTE = 12812
#: Eight 41-byte name slots, of which the first `count` are used.
POR_NAME_SLOTS = 8

#: The empty wallset word, and the words the triple and its index map live in.
POR_EMPTY = 0xFFFF
POR_WALLSET = 0x4AFA
POR_WALLMAP = 0x4AFD


def por_word_offset(address: int) -> int:
    """File offset of the variable-array word for an ECL address."""
    if not POR_VAR_BASE <= address <= POR_VAR_LAST:
        raise AmigaRecordError(
            f"${address:04X} is outside the Amiga Pool of Radiance variable "
            f"array ${POR_VAR_BASE:04X}-${POR_VAR_LAST:04X}")
    return POR_VAR_OFFSET + 2 * (address - POR_VAR_BASE)


def por_word(save: bytes, address: int) -> int:
    at = por_word_offset(address)
    return int.from_bytes(save[at:at + 2], "big")


def por_put_word(save: bytearray, address: int, value: int) -> None:
    at = por_word_offset(address)
    save[at:at + 2] = (value & 0xFFFF).to_bytes(2, "big")


#: `PorSaveState` is now `WorldState` under its old name (`#352 (Lift
#: PorSaveState into one WorldState that every port's saved-game reader
#: fills and both container writers take)`): `por_savegame_writes` below only
#: ever reads the ten fields Pool of Radiance needed, and a `WorldState` is
#: a strict superset of those, so nothing here has to convert one into the
#: other.  The three `por_state_from_*` readers are one-line wrappers of
#: `goldbox.world_state`'s three general ones, each keeping the one thing
#: that was Amiga-specific about it.  **They no longer refuse an outdoor
#: party**: the two bytes that had never been seen were measured on
#: 2026-09-07, on two saved games the Amiga game itself made on the travel
#: grid (`#316 (Write the Amiga Pool of Radiance saved game from the source
#: save, so a converted party arrives where it was standing)`, `#321 (An
#: Amiga Pool of Radiance conversion refuses a party standing on the travel
#: grid, because no outdoor Amiga saved game has ever been read)`).
PorSaveState = world_state.WorldState


def por_state_from_c64(save0: bytes, source: str = "") -> PorSaveState:
    """A C64 Pool of Radiance `SAVEDGAME0` payload, as a place and a clock."""
    return world_state.from_c64(save0, source=source)


def por_state_from_dos(savgam: bytes, source: str = "") -> PorSaveState:
    """A DOS `SAVGAM<slot>.DAT`, as a place and a clock."""
    return world_state.from_dos(savgam, source=source)


def por_state_from_amiga(savgam: bytes, source: str = "") -> PorSaveState:
    """An Amiga `savgam<letter>.dat`, as a place and a clock.

    Here so the writer can be checked against the game's own file: read a
    shipped saved game through this, hand the result back to
    :func:`new_por_savegame`, and every byte that differs has to be one the
    writer *declares* it cannot source.  A round trip masked by the declared
    list rather than by the diff is the test
    `.claude/rules/conversions.md` asks for.
    """
    if len(savgam) != POR_SAVEGAME_SIZE:
        raise AmigaRecordError(
            f"an Amiga Pool of Radiance saved game is {POR_SAVEGAME_SIZE} "
            f"bytes, got {len(savgam)}")
    return world_state.from_amiga(savgam, source=source)


#: The travel grid used to be refused here, because two bytes of an outdoor
#: Amiga saved game had never been seen.  **Both were measured on 2026-09-07**
#: and both agree with DOS: byte 12810, the view type, is
#: :data:`POR_VIEW_TYPE_OVERLAND` = 3, and byte 12803, the wall in front, is
#: :data:`POR_WALL_OUTDOORS` = 14.  A party bought passage from New Phlan's
#: harbour master, sailed to the west landing and camped and saved there
#: twice, one overland step apart, in Amiga Pool of Radiance under WinUAE;
#: `tools/porboat.py` staged the eight bytes that put it in front of the
#: harbour master and the engine wrote everything else.  `#321 (An Amiga Pool
#: of Radiance conversion refuses a party standing on the travel grid,
#: because no outdoor Amiga saved game has ever been read)` and
#: `docs/196-the-amiga-saved-game-built.md` have the numbers.
#:
#: What an outdoor container needs beyond those two, all of it now written by
#: :func:`por_savegame_writes` and all of it the same as DOS's outdoor path
#: (`#190 (A C64 party standing on the travel grid cannot be written into a
#: DOS save)`): `$49E6` = 0, `$49C5` = 0, the travel square in
#: `$49C3`/`$49C4`, the area in `$49F2`, the wallset triple
#: `(0, $FFFF, $FFFF)`, and the indoor square left stale in bytes 12800-12801
#: while the facing at 12802 stays live.

#: Why an area cannot be written, or `None`.  Two refusals, and both are about
#: the script rather than about the party.
#:
#: `ecl.dax` on disk 2 holds blocks 0-11 and 13-29.  Area 30 (`ECL1E`) has no
#: Amiga block at all -- 29 of the C64's 30, which
#: `docs/117-save-conversion.md` already recorded -- so a party standing there
#: has no script to stage and the save would carry somebody else's area.
POR_NO_AMIGA_SCRIPT = ("area {area} has no script in the Amiga game's own "
                       "ecl.dax, so there is nothing to stage in the saved "
                       "game and the party would arrive in somebody else's "
                       "area")


def por_conversion_reason(area: int) -> "str | None":
    """Why this area cannot be converted to the Amiga, or `None` if it can.

    The mirror of `goldbox.dos_codec.conversion_reason`.  An area with no row has no
    disk number and no script.  **The three travel windows are no longer
    refused**: areas 25, 26 and 27 have blocks in `ecl.dax` and the two bytes
    that stopped this were measured (`#321 (An Amiga Pool of Radiance
    conversion refuses a party standing on the travel grid, because no
    outdoor Amiga saved game has ever been read)`).  Whether `ecl.dax` holds
    the block is checked by :func:`por_area_script`, which is the only place
    that can see the player's own disk.
    """
    where = areas.area(area)
    if where is None:
        return (f"area {area} is not an area of Pool of Radiance, so there is "
                f"no script to stage")
    return None


def por_area_script(ecl_dax: bytes, area: int) -> bytes:
    """The area's own block of the Amiga `ecl.dax`, unpacked.

    The block **including** its two-byte header; the writer stages it from
    byte :data:`POR_ECL_HEADER` on, which is the relationship the shipped save
    has with block 0 -- byte for byte over all 7468 bytes.
    """
    from . import amiga_dax

    why = por_conversion_reason(area)
    if why is not None:
        raise AmigaRecordError(why)
    try:
        return amiga_dax.block(ecl_dax, area, "ecl.dax")
    except amiga_dax.AmigaDaxError as e:
        raise AmigaRecordError(
            f"{POR_NO_AMIGA_SCRIPT.format(area=area)} ({e})") from e


#: The reasons a word this conversion cannot source is written **zero** rather
#: than left at somebody else's value.  Each is the head of a reason string in
#: :data:`POR_SAVGAM_UNSOURCED`.
POR_ENGINE_REBUILT = (
    "one of the words the Amiga engine rewrites for itself: it came back "
    "non-zero from the game's own ENCAMP > SAVE of a party loaded out of a "
    "container built here with it zero, in both WinUAE runs of #316 -- and "
    "the same word is engine-rebuilt on DOS (#59, #26)")
POR_ENGINE_ONLY = (
    "engine state with no counterpart in a C64 or DOS save -- above $4AF9, "
    "which no ECL script in the thirty-script corpus references (#59)")
POR_ENCOUNTER_STATE = (
    "the pending-encounter record: it changes together with the message "
    "buffer beside it, and a converted party has no encounter pending")

#: Words of `$4900`-`$52FF` no source save can answer for, written **zero**
#: with the reason each is nobody's.  The Amiga counterpart of
#: `goldbox.dos_codec.SAVGAM_UNSOURCED`, and it is that list address for address --
#: which is a finding rather than a convenience.  **Every one of the 92
#: distinct nonzero words the ten Amiga saved games on this machine hold is
#: either written by :func:`por_savegame_writes` or named here**, with nothing
#: left over.
POR_SAVGAM_UNSOURCED: tuple[tuple[int, int, str], ...] = (
    (0x49F0, 2, f"the previous square -- {POR_ENGINE_REBUILT}"),
    (0x49FC, 1, "an engine byte the save routine copies into the array and "
                "the loader copies back out (`g3d3e`, "
                "`docs/165-amiga-savegame.md`). The three ports disagree on "
                "it -- the Amiga reads 1, DOS 6 or 4 by area, the C64 2 -- so "
                "there is nothing to convert"),
    (0x49FD, 2, "the two wall colours, which the arriving area's own ECL "
                "prologue writes on entry: `ECL00` opens `SAVE [$6E7D],"
                "[$49FD] / SAVE 10,[$49FE]` and `ECL14` the same with 9. "
                "Measured in the running game: both WinUAE runs of #316 wrote "
                "zero here, and the engine's own resave of a party standing "
                "in the Slums came back holding the Slums' 9"),
    (0x4DB8, 1, POR_ENGINE_ONLY), (0x4DC3, 1, POR_ENGINE_ONLY),
    (0x4E0C, 1, POR_ENGINE_ONLY), (0x4FA8, 1, POR_ENGINE_ONLY),
    (0x4FC0, 2, POR_ENGINE_ONLY), (0x4FC6, 1, POR_ENGINE_ONLY),
    (0x4FC8, 1, POR_ENGINE_ONLY),
    (0x4FD2, 2, "the rest-interruption pair `$6DD2`/`$6DD3` -- how many "
                "five-minute passes between checks and the chance of one. The "
                "area's own script writes them on ENCAMP and the area-init "
                "routine zeroes them on load. Measured: both WinUAE runs of "
                "#316 wrote zero and the engine's resave in the Slums came "
                "back with the Slums' own (24, 24), which is docs/141's "
                "figure for that area"),
    (0x5079, 1, POR_ENGINE_REBUILT),
    (0x507A, 4, POR_ENGINE_ONLY + " -- and the overland script's own loop "
                "registers, rewritten on the first step out there (#59)"),
    (0x507F, 2, POR_ENGINE_ONLY),
    (0x5082, 1, POR_ENGINE_REBUILT),
    (0x5200, 1, POR_ENGINE_REBUILT),
    (0x5202, 6, POR_ENCOUNTER_STATE),
    (0x5208, 1, POR_ENGINE_REBUILT),
    (0x520A, 6, POR_ENCOUNTER_STATE),
    (0x5227, POR_VAR_LAST - 0x5227 + 1,
     "the encounter and monster message buffers, one ASCII character per "
     "word -- a converted party is not being shouted at. The shipped Amiga "
     "save is still holding `YOU HAVE SURPRISED A PARTY OF  ORCS.`"),
)

#: The 32 bytes of heap after each of the eight names in the character table.
#: Written zero, and the same 274 bytes DOS zeroes: display scratch, and the
#: evidence is what is in them -- the engine's own menu words, and the ten
#: Amiga saved games differ from each other in almost nothing else.
POR_TABLE_SCRATCH = ("display scratch: the 33 bytes after each of the eight "
                     "names in the character table, zeroed")

#: Words written to a value **measured** rather than sourced, as
#: `(address, value, why)`.
#:
#: `$49FF` gates the sheet portrait on the C64 (`LIBRARY $48A9`, bit 7) and on
#: DOS, where zero left a converted party faceless whatever its records said
#: (#57).  **It gates nothing on the Amiga**: that port draws no portrait on
#: a character sheet at all, and no box for one -- where the other two put a
#: face it puts `GOLD`, `ENCUMBRANCE` and `MOVEMENT`, watched on seven sheets
#: across two WinUAE sessions on 2026-09-07
#: (`#322 (Nobody has looked at an Amiga Pool of Radiance character sheet to
#: see whether it draws a portrait at all)`, `docs/206-three-amiga-questions.md`).
#: Writing 3 stays right -- it is what 17 of the 19 Amiga saved games here
#: hold, the two exceptions being a container we built with no portrait
#: crossed and the engine's resave of it, which inherited that zero rather
#: than choosing it -- so nothing a player sees changes; what changed is the
#: reason (`#441 (A converted Amiga save's provenance claims three words are
#: zero in every saved game, and they are not)`).  The Amiga's own code
#: calls it `2 * g63d1 + g63d0`, split back into two engine bytes on load,
#: and it is the same 3 all three engine-written DOS ones hold.  PROBABLE
#: for the Amiga: the value is the engine's own on both ports that have been
#: bisected, and no Amiga run has bisected it.  Nobody has opened an Amiga
#: character sheet at all: `#322 (Nobody has looked at an Amiga Pool of
#: Radiance character sheet to see whether it draws a portrait at all)`.
POR_SAVGAM_MEASURED: tuple[tuple[int, int, str], ...] = (
    (0x49FF, 3, "the word that gates the sheet portrait on the two ports "
                "where it has been bisected, and 3 is what it reads in "
                "every Amiga and DOS saved game measured except our own "
                "builds with no portrait crossed and their engine resaves, "
                "which inherit that zero rather than choosing it -- re-run "
                "`tools/amigasavegame.py --sweep` for a current count "
                "(#57, #441)"),
)


@dataclass
class PorSaveReport(neutral.Report):
    """Where every byte of a built `savgam<letter>.dat` came from.

    `sources` covers all 13141 bytes, so what is *not* written is countable --
    which is the whole of how "no template" is checked rather than asserted.
    """

    total: int = POR_SAVEGAME_SIZE
    #: One line per field taken from the source save, for a person to read.
    converted: list[str] = field(default_factory=list)
    #: Offsets nothing wrote.  **Empty when the buffer started from zeroes**,
    #: and that is what makes "no template" checkable rather than asserted.
    unwritten: list[int] = field(default_factory=list)

    def address(self, offset: int) -> str:
        """`$4A20` for a variable, `the script buffer`, or `byte 12800`."""
        if POR_VAR_OFFSET <= offset < POR_VAR_OFFSET + 2 * POR_VAR_WORDS:
            word = POR_VAR_BASE + (offset - POR_VAR_OFFSET) // 2
            return f"${word:04X}"
        if POR_ECL_BUFFER[0] <= offset < POR_ECL_BUFFER[1]:
            return "the script buffer"
        return f"byte {offset}"

    def summary_notes(self) -> list[str]:
        lines = [f"  converted: {c}" for c in self.converted]
        if self.unwritten:
            lines.append(f"  {len(self.unwritten)} bytes unwritten, from "
                         f"{self.address(self.unwritten[0])}")
        return lines


def _por_note_word(report: PorSaveReport, address: int, words: int,
                   why: str) -> None:
    report.note(por_word_offset(address), 2 * words, why)


def por_savegame_writes(save: bytearray, report: PorSaveReport,
                        state: PorSaveState, slot: str, count: int,
                        script: bytes, *, portraits: bool = False) -> None:
    """Write everything the source save answers for into a 13141-byte buffer.

    `save` is modified in place and every byte written gets a line in
    `report.sources`.  `script` is the party's own area's `ecl.dax` block,
    header and all; there is no path here without one, because the buffer is
    live on load and a save carrying a stranger's area is a party standing
    somewhere it has never been.
    """
    where = areas.area(state.area)
    why = por_conversion_reason(state.area)
    if why is not None:
        raise AmigaRecordError(why)

    outdoors = state.outdoors
    por_put_word(save, dos_savegame.AREA, 0 if outdoors else state.geo)
    _por_note_word(report, dos_savegame.AREA, 1,
                   "zero, which is what both engine-written outdoor Amiga "
                   "saves hold: a travel window loads a SQRDATA rather than "
                   "a GEO and $49E6 is what picks the file type (#321)"
                   if outdoors else
                   "the resident GEO, the source save's own $49C5 -- which is "
                   "not the area id for a script that loads no map of its own")
    por_put_word(save, dos_savegame.SCRIPT, state.area)
    _por_note_word(report, dos_savegame.SCRIPT, 1,
                   f"the area the party is in, {state.area} "
                   f"({where.name or where.ecl})")
    por_put_word(save, dos_savegame.DISK, where.disk)
    _por_note_word(report, dos_savegame.DISK, 1,
                   f"the container number, {where.disk}. The Amiga keeps it "
                   f"only here: it has no header byte where DOS has one")
    wallset = (dos_savegame.OUTDOOR_WALLSET if outdoors else state.wallset)
    for i, w in enumerate(wallset):
        por_put_word(save, POR_WALLSET + i, w)
    _por_note_word(report, POR_WALLSET, 3,
                   "the overland wallset triple (0, $FFFF, $FFFF), which is "
                   "the engine's own out here rather than whatever the party "
                   "left the grid on -- both Amiga saved games made outdoors "
                   "hold it, as do six DOS ones (#190, #321)"
                   if outdoors else
                   "the wallset triple, the source save's own three "
                   "WALLDEF/8X8D block ids")
    for i, w in enumerate(dos_savegame.wall_map(wallset)):
        por_put_word(save, POR_WALLMAP + i, w)
    _por_note_word(report, POR_WALLMAP, 3,
                   "the wall-index map that goes with the triple")

    body = script[POR_ECL_HEADER:]
    start, end = POR_ECL_BUFFER
    if len(body) > end - start:
        raise AmigaRecordError(
            f"area {state.area}'s script is {len(body)} bytes and the "
            f"buffer holds {end - start}")
    save[start:start + len(body)] = body
    report.note(start, end - start,
                f"the area's own ecl.dax block {state.area} from byte "
                f"{POR_ECL_HEADER} on, then zero to the end of the buffer -- "
                f"which is what the shipped saved game holds past its "
                f"script's end, byte for byte over 7468 bytes")

    por_put_word(save, dos_savegame.INDOORS, 0 if outdoors else 1)
    _por_note_word(report, dos_savegame.INDOORS, 1,
                   "outdoors" if outdoors else "indoors")
    if outdoors:
        travel_x, travel_y = state.travel
        por_put_word(save, dos_savegame.TRAVEL_X, travel_x)
        por_put_word(save, dos_savegame.TRAVEL_Y, travel_y)
        _por_note_word(report, dos_savegame.TRAVEL_X, 2,
                       f"the travel square ({travel_x},{travel_y}), "
                       f"window-local, the source save's own. The Amiga "
                       f"keeps it where DOS does and the status line prints "
                       f"the world coordinate instead (#321)")
    else:
        _por_note_word(report, dos_savegame.TRAVEL_X, 2,
                       "zeroed: this party is indoors, so this build "
                       "writes no travel square here. That is not the same "
                       "as reading zero in every Amiga saved game -- the "
                       "sweep finds these two words non-zero in the saved "
                       "games made on the travel grid; re-run "
                       "`tools/amigasavegame.py --sweep` for a current "
                       "count (#441)")

    save[POR_POS_X] = state.x
    save[POR_POS_Y] = state.y
    save[POR_POS_FACING] = state.facing * dos_savegame.FACING_SCALE
    report.note(POR_POS_X, 3,
                f"the indoor square ({state.x},{state.y}) the party left, "
                f"which the engine freezes out here, and facing "
                f"{state.facing}, which stays live and steps with the party"
                if outdoors else
                f"the square ({state.x},{state.y}) facing {state.facing}, the "
                f"source save's own, doubled the way both ports store it")
    save[POR_WALL_BYTE] = POR_WALL_OUTDOORS if outdoors else 0
    report.note(POR_WALL_BYTE, 1,
                f"the wall in front of the party: {POR_WALL_OUTDOORS}, which "
                f"is what both saved games the Amiga game itself made on the "
                f"travel grid hold, unmoved across a step that changed the "
                f"square and the facing (#321). DOS holds the same 14 there "
                f"outdoors"
                if outdoors else
                "the wall art in front of the party: zero. It is a function "
                "of the map and the facing and the step routine recomputes it "
                "(/program 0x2ec1c). Measured: the engine's own ENCAMP > SAVE "
                "of a party loaded out of a container written this way came "
                "back holding zero too, in both WinUAE runs of #316")
    save[POR_SQUARE_PROPERTY] = 0
    report.note(POR_SQUARE_PROPERTY, 1,
                "the square property: zero. It is the low byte of $5200, "
                "which nothing can source, and the same step routine "
                "rewrites it. The engine's own resave holds zero here too "
                "(#316), and its own outdoor saves hold 1 with $5200 at 1, "
                "which is the same relationship (#321)")
    pad_start, pad_end = POR_SQUARE_PAD
    report.note(pad_start, pad_end - pad_start,
                "five bytes nothing reads: two the seven-byte square struct "
                "pads to and the first three of wallset entry 0, which the "
                "game's own ten-byte write runs into. Zero in all ten Amiga "
                "saved games here")
    save[POR_VIEW_TYPE] = (POR_VIEW_TYPE_OVERLAND if outdoors
                           else POR_VIEW_TYPE_3D)
    report.note(POR_VIEW_TYPE, 1,
                f"the view type: {POR_VIEW_TYPE_OVERLAND}, the travel grid. "
                f"Both saved games the Amiga game itself made out there hold "
                f"it, and it is what DOS holds in 10 of 10 outdoor specimens "
                f"-- not the 2 the code beside the write names (#321)"
                if outdoors else
                "the view type: 1, the 3D view, from the code beside the "
                "write and 1 in all ten Amiga saved games")
    save[POR_GAME_MODE] = POR_GAME_MODE_CAMP
    report.note(POR_GAME_MODE, 1,
                "the game mode: 2, camp. A save is taken from camp, so this "
                "is what the engine writes -- 2 in all ten")

    por_put_word(save, dos_savegame.PARTY_SIZE, count)
    _por_note_word(report, dos_savegame.PARTY_SIZE, 1,
                   f"the party size, {count}")
    save[POR_PARTY_SIZE_BYTE] = count
    report.note(POR_PARTY_SIZE_BYTE, 1, f"the party size again, {count}")

    letter = _por_slot_letter(slot)
    for n in range(POR_NAME_SLOTS):
        at = POR_CHARACTER_TABLE + n * POR_CHARACTER_TABLE_STRIDE
        if n < count:
            save[at:at + POR_CHARACTER_TABLE_NAME] = \
                f"CHRDAT{letter}{n + 1}".encode("ascii")
            report.note(at, POR_CHARACTER_TABLE_NAME,
                        f"CHRDAT{letter}{n + 1}, which is what the engine "
                        f"loads the party from -- not the slot letter at the "
                        f"picker (#28)")
        else:
            report.note(at, POR_CHARACTER_TABLE_NAME,
                        f"an unused name slot: this party has {count} "
                        f"characters and the table holds {POR_NAME_SLOTS}")
        report.note(at + POR_CHARACTER_TABLE_NAME,
                    POR_CHARACTER_TABLE_STRIDE - POR_CHARACTER_TABLE_NAME,
                    POR_TABLE_SCRATCH)

    for i, address in enumerate(range(dos_savegame.FLAGS_FIRST,
                                      dos_savegame.FLAGS_LAST + 1)):
        por_put_word(save, address, state.flags[i])
    _por_note_word(report, dos_savegame.FLAGS_FIRST,
                   dos_savegame.FLAGS_LAST - dos_savegame.FLAGS_FIRST + 1,
                   "a quest flag: the source save's own value at the same ECL "
                   "address, which is the address all three ports share")
    for address, value in state.scratch.items():
        por_put_word(save, address, value)
        _por_note_word(report, address, 1,
                       "script scratch: the source save's own value at the "
                       "same ECL address")

    for i, digit in enumerate(state.clock):
        por_put_word(save, dos_savegame.CLOCK + i, digit)
    _por_note_word(report, dos_savegame.CLOCK, dos_savegame.CLOCK_DIGITS,
                   "a clock digit, the source save's own")

    for address, value, why in dos_savegame.SAVGAM_CONSTANTS:
        por_put_word(save, address, value)
        _por_note_word(report, address, 1, f"a documented constant: {why}")
    for address, value, why in POR_SAVGAM_MEASURED:
        if address == 0x49FF and not portraits:
            _por_note_word(report, address, 1,
                           "zeroed: no portrait crossed for this party, "
                           "so this build does not write the word that "
                           "gates the sheet portrait on the other two "
                           "ports. That is not the same as reading zero in "
                           "every Amiga saved game -- the sweep finds it "
                           "non-zero in most of the saved games examined, "
                           "including the one SSI shipped; re-run "
                           "`tools/amigasavegame.py --sweep` for a current "
                           "count (#441)")
            continue
        por_put_word(save, address, value)
        _por_note_word(report, address, 1, f"measured: {why}")


def por_savegame_zeroes(save: bytearray, report: PorSaveReport) -> None:
    """Account for every byte :func:`por_savegame_writes` left zero."""
    for address, words, why in POR_SAVGAM_UNSOURCED:
        _por_note_word(report, address, words, f"zeroed -- {why}")
    rest = [i for i in range(POR_VAR_OFFSET,
                             POR_VAR_OFFSET + 2 * POR_VAR_WORDS)
            if i not in report.sources]
    for i in rest:
        report.sources[i] = (
            "zeroed: this word reads zero in every Amiga saved game swept "
            "so far, and nothing in a C64 or DOS save corresponds to it -- "
            "run `tools/amigasavegame.py --sweep` to re-take the "
            "measurement (docs/165-amiga-savegame.md, \"Still open\")")


def new_por_savegame(state: PorSaveState, slot: str, count: int,
                     ecl_dax: bytes, *, portraits: bool = False
                     ) -> "tuple[bytes, PorSaveReport]":
    """Build all 13141 bytes of a `savgam<letter>.dat` from 13141 zeroes.

    `ecl_dax` is the whole of `/ecl.dax` off the player's Amiga disk 2, which
    is the only copy of the party's area's script.  `count` is how many
    characters the slot holds; `slot` is the letter, which is what the eight
    `CHRDAT` names in the table are built from.

    Returns the file and a report whose `sources` covers every byte and whose
    `unwritten` is empty.  There is no template and no argument for one.
    """
    if not 1 <= count <= POR_PARTY_MAX:
        raise AmigaRecordError(
            f"a Pool of Radiance party is 1 to {POR_PARTY_MAX} characters; "
            f"got {count}")
    script = por_area_script(ecl_dax, state.area)
    save = bytearray(POR_SAVEGAME_SIZE)
    report = PorSaveReport(total=POR_SAVEGAME_SIZE)
    por_savegame_writes(save, report, state, slot, count, script,
                        portraits=portraits)
    por_savegame_zeroes(save, report)
    where = areas.area(state.area)
    report.converted = [
        (f"the party is on the travel grid in "
         f"{where.name or where.ecl} at "
         f"({state.travel[0]},{state.travel[1]}), window-local"
         if state.outdoors else
         f"the party is in {where.name or where.ecl} at "
         f"({state.x},{state.y}) facing "
         f"{'NESW'[state.facing % 4]}"),
        f"the clock reads {state.clock[3]:02d}:"
        f"{state.clock[2]}{state.clock[1]}",
        f"{sum(1 for f in state.flags if f)} quest flags are set",
    ]
    report.unwritten = [i for i in range(POR_SAVEGAME_SIZE)
                        if i not in report.sources]
    return bytes(save), report
