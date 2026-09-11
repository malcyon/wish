"""Amiga Curse of the Azure Bonds and Secret of the Silver Blades.

The two later titles' Amiga records, read out of a saved game's party block and
written back into one.  Their per-title deltas -- how each departs from its own
DOS record -- are `AmigaDeltas` in `goldbox/amiga_port.py`; this module is the
code that reads and writes them.

`#470 (Give the project a neutral title beside its neutral character record,
with one port per platform a title shipped on)`'s stage 10 split
`goldbox/amiga_codec.py` by title.  Pool of Radiance is in
`goldbox/amiga_por.py`, Pools of Darkness in `goldbox/amiga_pod.py`, and
`goldbox/amiga_shared.py` holds what more than one of them needs.

**Three names come from `goldbox/amiga_por.py`** -- :class:`PorWriteReport`,
`amiga_por_effect_to_dos` and `amiga_por_effect_from_dos`.  They are Amiga-wide
rather than that title's: the ten-byte effect node is the same on all three
titles and the write report's contract is every Amiga writer's.  That module's
docstring says why they still wear Pool of Radiance's spelling and what the
real fix is.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Sequence

from . import dos_layout, games, neutral
from .amiga_por import (
    PorWriteReport,
    amiga_por_effect_from_dos,
    amiga_por_effect_to_dos,
)
from .amiga_port import (
    AMIGA_DELTAS,
    AMIGA_DELTAS_BY_SIZE,
    AMIGA_LATER_ITEM_SHIFTS,  # noqa: F401  re-exported for pre-#470 callers
    AMIGA_NAME_SIZE,
    AMIGA_POR_EFFECT_PAD,
    AMIGA_SSB_SCROLL_CHAIN,
    CURSE_DELTAS,
    SILVER_BLADES_DELTAS,
    AmigaDeltas,
    AmigaRecordError,
)
from .amiga_shared import ABILITY_KEYS
from .layout import Confidence, Kind
from .neutral import NeutralCharacter
from .portraits import neutral_menu

if TYPE_CHECKING:          # avoided at runtime: goldbox.dos_codec is the
    from .iconparts import DosIcon  # heavier module and this file only needs
    # the name



# ---------------------------------------------------------------------------
# Amiga Curse of the Azure Bonds and Secret of the Silver Blades (#55)
# ---------------------------------------------------------------------------
#
# The two later titles' record deltas -- `AmigaDeltas`, the two rows and the
# registry, and the item-node facts they are built from -- moved to
# `goldbox/amiga_port.py` in #470's stage 4b, so the port's own module holds
# what an Amiga record looks like and this one holds only the code that reads
# and writes it.  Every name is imported at the head of this file and every
# pre-#470 spelling still answers here, so `amiga.AmigaShape` and
# `amiga.CURSE_SHAPE` keep working until stage 9 moves the callers off them.
AmigaShape = AmigaDeltas
CURSE_SHAPE = CURSE_DELTAS
SILVER_BLADES_SHAPE = SILVER_BLADES_DELTAS
AMIGA_SHAPES = AMIGA_DELTAS
AMIGA_SHAPES_BY_SIZE = AMIGA_DELTAS_BY_SIZE



AMIGA_SSB_SPELLBOOK_BYTES = 15
AMIGA_SSB_SPELLBOOK_AT = 0x071


# ---------------------------------------------------------------------------
# The status word, named from the routine that draws it (#28, step 3)
# ---------------------------------------------------------------------------
#
# **Both later Amiga titles number the nine states the way DOS does**, so
# `goldbox/neutral.py`'s `STATUS_NAMES` is their table as well and `status`
# crosses by name with nothing to translate.  That is not an assumption from
# the shift map: it is two string tables in two binaries, each reached by the
# routine that paints the party panel.
#
#   * `/Secret` `0x196EA`: `tst.b $144(a2)`, and where that is zero
#     `move.b $143(a2), d0; ext.w; ext.l; asl.l #2; lea g30fc, a0;
#     move.l (a0, d0.l), -(a7)` -- a nine-entry `char *` table at file offset
#     `0x4F9B8` pointing at `Okay`, `Animated`, `tempgone`, `Running`,
#     `Unconscious`, `Dying`, `Dead`, `Petrified`, `Gone`.  The same table is
#     indexed a second time at `0x2208C`, off the current character.
#   * `/Curse` `0x1A38E`: `tst.b $19b(a2)`, and where that is zero
#     `move.w $19a(a2)` into a helper at `0x352E8` that fetches block
#     `status + 0x2C` of text library `0x13`.  That library is
#     `DISKA/STRINGS.GLB`, and its blocks 44 to 52 read `Okay`, `Animated`,
#     `tempgone`, `Running`, `Unconscious`, `Dying`, `Dead`, `Stoned`,
#     `Gone` -- DOS's own ninth word where `/Secret` says `Petrified`.
#
# Amiga `0x143` is DOS `0x1A6` under `SILVER_BLADES_DELTAS` and Amiga `0x19A`
# is DOS `0x195` under `CURSE_DELTAS`, and both are the **first byte of
# `field_10c_10f`** -- the same field DOS Pool of Radiance keeps the status in
# at `0x10C` (#235).  Each title's unpacker copies those bytes one at a time
# rather than as a run, which is a third routine agreeing that they are three
# separate fields.
#
#: The DOS field whose first byte is the status the party panel draws.
AMIGA_LATER_STATUS_FIELD = "field_10c_10f"

#: The byte after the status, and **it is not DOS Pool of Radiance's `active`
#: flag on the evidence there is.**  Where it is non-zero the panel draws
#: `(Helpless)` or `(Casting)` in place of the status word, which is combat
#: state rather than "the game has taken this character out of the party".
#: UNKNOWN, and not converted.  What would settle it: knock a character down in
#: an Amiga Curse fight, save, and read the byte; and put a character in the
#: state that draws the name red and read it again.
AMIGA_LATER_STATUS_GATE = 1

# ---------------------------------------------------------------------------
# What the loader needs of a block it did not write (#28, step 4)
# ---------------------------------------------------------------------------
#
# The saved game's per-character loader -- `/Curse` `0x25056`, `/Secret`
# `0x268C0` -- reads the record and then **decides whether an item node
# follows by testing the pointer the record itself carries**:
#
#     read(fd, record, 0x1AC)              ; 0x154 in /Secret
#     tst.l   $152(a0)                     ; $fe(a0) in /Secret
#     beq     no items
#     alloc(&record[0x152], 0x42)          ; overwrites the tested value
#     read(fd, record[0x152], 0x42)
#     a3 = record[0x152]
#   loop:
#     tst.l   $2a(a3)                      ; the node's own next pointer
#     beq     done
#     alloc(&a3[0x2a], 0x42); read(...); a3 = a3->next
#
# and the effect chain the same way from `$f2(a0)` / `$96(a0)`, ten bytes a
# node, next at node offset 6.  **The stored pointer is a boolean.**  Its
# value is never dereferenced: `alloc` overwrites it with the address it
# returns before the `read` that fills the node.  `item_count` is not
# consulted by the loader at all.
#
# So a saved game we write must carry a **non-zero** head where nodes follow
# and a **zero** one where they do not, and a wrong answer is not a cosmetic
# fault: every character is read from one file descriptor in sequence, so a
# head left NULL in front of a node that is really there leaves the stream
# mid-block and every later character in the party reads rubbish.
#
# That is the opposite of the Pool of Radiance rule, where `.itm` and `.spc`
# are separate files and the chain is rebuilt from the file's length -- which
# is why `write_por` writes NULL and this must not.
#
# Corroborated on **21 of 21 records** off the shipped disks, independently of
# the code: the eleven Curse `.guy` pregens, the four characters in
# `SAVE/savgamA.dat` and the six in `SAVE/savgamA.sav` all carry a non-zero
# head exactly when a node follows, a non-zero `next` on every node but the
# last, and zero on the last.  The addresses step by 66 along an item chain
# and by 10 along an effect chain, which is what a heap of those node sizes
# looks like.
#
#: What to put in a chain field when a node follows and the record's own value
#: cannot be kept.  Any non-zero longword does; 1 is chosen because it cannot
#: be mistaken for an Amiga heap address in a dump.
AMIGA_LATER_CHAIN_PRESENT = 1
#: The item node's own next pointer, and the effect node's.
AMIGA_LATER_ITEM_NEXT = 0x02A
AMIGA_LATER_EFFECT_NEXT = 0x006


def _chain_bytes(present: bool, current: int) -> bytes:
    """Four big-endian bytes for a chain field, keeping what is there.

    A value whose truth already matches what follows is left alone, so a
    saved game read and written back is byte for byte the file it came from;
    only a field that would lie to the loader is changed.
    """
    if bool(current) == present:
        return current.to_bytes(4, "big")
    return (AMIGA_LATER_CHAIN_PRESENT if present else 0).to_bytes(4, "big")


@dataclass(frozen=True)
class AmigaItem:
    """One item node of a later Amiga Gold Box title.

    Curse's is **66 bytes** where DOS spends 63, Silver Blades' is **70**,
    and the first 66 of each are the same layout -- see
    `AMIGA_LATER_ITEM_SHIFTS` for the constructor both titles build one with.
    The insertion Amiga Pool of Radiance does not have is the pad at `0x02F`,
    ahead of `name1`: the same Chain Mail reads `37 00 30 37` at `0x02E`
    there and `37 00 00 30 37` here.

    `charges` is at **`0x03F`**, not `0x03E`.  The nine nodes in
    `SAVE/savgamA.dat` read 52 at `0x03B` and 47 at `0x03E` in 9 of 9, which
    looked like a field; the constructor writes neither, and both are
    uninitialised stack copied out of the `ITEM<n>` template loader.
    """

    raw: bytes
    deltas: AmigaDeltas

    @classmethod
    def from_bytes(cls, data: bytes | bytearray,
                   deltas: AmigaDeltas = CURSE_DELTAS) -> "AmigaItem":
        if deltas.item_size is None or len(data) != deltas.item_size:
            raise AmigaRecordError(
                f"an Amiga {deltas.title} item node is {deltas.item_size} "
                f"bytes, got {len(data)}")
        return cls(bytes(data), deltas)

    @property
    def shape(self) -> AmigaDeltas:
        """Pre-#470 name for :attr:`deltas`, so old callers keep reading."""
        return self.deltas

    @property
    def text(self) -> str:
        """The cached display line: the first NUL-terminated run.

        **Never a source.**  It is whatever the ITEMS screen last painted --
        one specimen reads `" Yes  Shield "` with the READY column baked in
        and the other eight do not -- and `goldbox/dos.py` says the same of
        the DOS buffer, which goes stale the same way.
        """
        return self.raw[:self.deltas.item_text].split(b"\0")[0].decode("latin1")

    @property
    def words(self) -> list[str]:
        """Every NUL-separated run in the text buffer, display line first."""
        block = self.raw[:self.deltas.item_text].rstrip(b"\0")
        return [p.decode("latin1") for p in block.split(b"\0")]

    @property
    def next(self) -> int:
        """The next node's Amiga heap address, `u32` big-endian, 0 at the
        end of a character's chain."""
        at = self.deltas.item_text
        return int.from_bytes(self.raw[at:at + 4], "big")

    def get(self, field_name: str):
        """One field, by its `goldbox/dos_layout.py` item-table name."""
        f = dos_layout.item_field_by_name(field_name)
        at = self.deltas.item_offset(f.offset)
        chunk = self.raw[at:at + f.size]
        if f.kind in (Kind.U16LE, Kind.UINT_LE):
            return int.from_bytes(chunk, "big")
        if f.kind is Kind.I8:
            return int.from_bytes(chunk, "big", signed=True)
        if f.kind is Kind.U8:
            return chunk[0]
        return chunk

    def to_dos_bytes(self) -> bytes:
        """This node as the 63 bytes `goldbox/dos_layout.py` describes.

        The same re-cut :meth:`AmigaPorItem.to_dos_bytes` makes, through this
        title's own item shift map: the display text becomes DOS's count byte
        and 41, every `u16` is byte-swapped, and the `next` far pointer is
        written NULL because it is a live Amiga heap address.

        **Silver Blades' node is 70 bytes and the last four are not converted.**
        `AMIGA_SSB_SCROLL_CHAIN` heads a scroll's extra spell nodes, and the
        63 bytes DOS's shared item table describes have no room for it; DOS
        Silver Blades' own item is 67 bytes and `#254` is where its last four
        are being read.
        """
        out = bytearray(dos_layout.ITEM_SIZE)
        text = self.raw[:self.deltas.item_text]
        line = text.split(b"\0")[0]
        size = dos_layout.ITEM_FIELDS_BY_NAME["text"].size
        out[0] = min(len(line), size)
        out[1:1 + size] = text[:size].ljust(size, b"\0")
        for f in dos_layout.ITEM_LAYOUT:
            if f.name in ("text_length", "text", "next"):
                continue
            at = self.deltas.item_offset(f.offset)
            chunk = self.raw[at:at + f.size]
            if f.kind in (Kind.U16LE, Kind.UINT_LE):
                chunk = chunk[::-1]
            out[f.offset:f.offset + f.size] = chunk
        return bytes(out)


@dataclass(frozen=True)
class AmigaCharacter:
    """One Amiga Curse or Silver Blades character, read through the DOS table.

    `items` and `effects` are the nodes that follow the record -- inside the
    saved game for a played character, and after the record in a `.guy` file
    for a pregenerated one.  Neither title keeps them in sibling files the
    way Pool of Radiance's `.itm` and `.spc` do.

    An effect node is the same ten bytes in all three Amiga titles, so
    `amiga_por_effect_to_dos` reads one of these too.  **The id space is
    per-title**: 107 is an elf in Curse and PAINE's ranger effect in Silver
    Blades is 105, so an id must never be converted from one title to another.
    """

    raw: bytes
    deltas: AmigaDeltas
    source: str = ""
    items: tuple[AmigaItem, ...] = ()
    effects: tuple[bytes, ...] = ()

    @classmethod
    def from_bytes(cls, data: bytes | bytearray,
                   deltas: AmigaDeltas | int | None = None,
                   source: str = "",
                   items: Sequence[AmigaItem] = (),
                   effects: Sequence[bytes] = ()) -> "AmigaCharacter":
        if deltas is None:
            deltas = len(data)
        if isinstance(deltas, int):
            got = AMIGA_DELTAS_BY_SIZE.get(deltas)
            if got is None:
                # Deferred, and on the error path only: the two lengths below
                # belong to the other titles' modules and nothing here reads
                # either title's record.
                from .amiga_pod import RECORD_LENGTH
                from .amiga_por import AMIGA_POR_RECORD_SIZE

                raise AmigaRecordError(
                    f"{deltas} bytes names no Amiga Gold Box record: Curse is "
                    f"{CURSE_DELTAS.record_size}, Silver Blades "
                    f"{SILVER_BLADES_DELTAS.record_size}, Pool of Radiance "
                    f"{AMIGA_POR_RECORD_SIZE} and Pools of Darkness's .pc "
                    f"{RECORD_LENGTH}")
            deltas = got
        if len(data) != deltas.record_size:
            raise AmigaRecordError(
                f"an Amiga {deltas.title} record is {deltas.record_size} "
                f"bytes, got {len(data)}")
        return cls(bytes(data), deltas, source, tuple(items), tuple(effects))

    @property
    def shape(self) -> AmigaDeltas:
        """Pre-#470 name for :attr:`deltas`, so old callers keep reading."""
        return self.deltas

    @property
    def name(self) -> str:
        return self.raw[:AMIGA_NAME_SIZE].split(b"\0")[0].decode("latin1")

    def get(self, field_name: str):
        """One field, by its `goldbox/dos_layout.py` name.

        `U16LE` and `UINT_LE` are read big-endian, which -- outside the name,
        the shifts and Silver Blades' spellbook -- is the whole of the
        difference between the two ports.
        """
        f = self.deltas.dos_field(field_name)
        at = self.deltas.offset(f.offset)
        # Every byte, not just the first: `field_83_87` straddles the window
        # its own insertion is in, and a field half of which is placed is a
        # field nobody has read.
        for i in range(1, f.size):
            self.deltas.offset(f.offset + i)
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
        """The six scores.  Both later titles store `(current, maximum)`
        pairs where Pool of Radiance stores one byte; this is the current."""
        return [self.get(k)[0] for k in ABILITY_KEYS]

    @property
    def money(self) -> dict[str, int]:
        return {k: self.get(k) for k in
                ("copper", "silver", "electrum", "gold", "platinum", "gems",
                 "jewelry")}

    @property
    def experience(self) -> int:
        return self.get("experience")

    @property
    def spellbook(self) -> list[int]:
        """The spell ids the character has in the book, ascending.

        Curse reads DOS's byte array straight; Silver Blades unpacks
        `AMIGA_SSB_SPELLBOOK_BYTES` of bitmask, LSB first, id = bit + 1.
        """
        book = self.deltas.dos_field("spellbook")
        if self.deltas.spellbook_bytes is None:
            at = self.deltas.offset(book.offset)
            raw = self.raw[at:at + book.size]
            return [i + dos_layout.SPELLBOOK_FIRST_ID
                    for i, v in enumerate(raw) if v]
        at = book.offset            # shift is zero where the book begins
        mask = self.raw[at:at + self.deltas.spellbook_bytes]
        return [i + dos_layout.SPELLBOOK_FIRST_ID
                for i in range(8 * len(mask))
                if mask[i // 8] >> (i % 8) & 1]

    @property
    def effect_chain(self) -> int:
        """The effect list head, `u32` big-endian, where DOS keeps an offset
        word and a segment word."""
        return int.from_bytes(self.get("effect_chain"), "big")

    @property
    def item_chain(self) -> int:
        """The item list head, `u32` big-endian: the first slot of the DOS
        record's 56-byte pointer array, which is what the saved game's writer
        walks and its loader tests."""
        return int.from_bytes(self.get("item_chain")[:4], "big")

    @property
    def status(self) -> int:
        """The state the party panel puts into words, 0 to 8.

        `AMIGA_LATER_STATUS_FIELD`'s first byte, indexing
        `goldbox.neutral.STATUS_NAMES` -- **DOS's own numbering**, read out of
        the string table each title's panel routine indexes.
        """
        return self.get(AMIGA_LATER_STATUS_FIELD)[0]

    @property
    def spell_slots(self) -> dict[str, tuple[int, ...]]:
        """Each spell-slot array, at the width the Amiga record gives it.

        Curse widens all three arrays to **six** bytes where DOS spends five
        and Silver Blades keeps DOS's seven, so the width is taken from the
        shift map -- the distance from one array's Amiga base to the next
        field's -- rather than from the DOS field's own size.  The key is the
        class the array belongs to, or the DOS field's name where nobody has
        attributed it.
        """
        table = dos_layout.layout_for(self.deltas.dos)
        out: dict[str, tuple[int, ...]] = {}
        for n, f in enumerate(table):
            if not f.name.startswith("spells_castable"):
                continue
            at = self.deltas.offset(f.offset)
            end = (self.deltas.offset(table[n + 1].offset)
                   if n + 1 < len(table) else self.deltas.record_size)
            out[f.name[len("spells_castable_"):].replace("_", "-")] = tuple(
                self.raw[at:end])
        return out

    def block_bytes(self) -> bytes:
        """The record, its item nodes and its effect chain, as a saved game
        holds them -- and as the loader will accept them.

        The three chain fields the loader tests are made to match what
        actually follows (`_chain_bytes`), and `item_count` is set to the
        number of nodes there really are; everything else is the bytes this
        object was read from.  A block read out of a saved game and written
        back through here is byte for byte the block that came in, because
        `_amiga_block` read the nodes by that same count and a chain field
        whose truth already matches is left alone.
        """
        record = bytearray(self.raw)
        record[self.deltas.offset(
            self.deltas.dos_field("item_count").offset)] = len(self.items)
        at = self.deltas.offset(self.deltas.dos_field("item_chain").offset)
        record[at:at + 4] = _chain_bytes(bool(self.items), self.item_chain)
        at = self.deltas.offset(self.deltas.dos_field("effect_chain").offset)
        record[at:at + 4] = _chain_bytes(bool(self.effects), self.effect_chain)

        items = []
        for n, item in enumerate(self.items):
            raw = bytearray(item.raw)
            here = AMIGA_LATER_ITEM_NEXT
            raw[here:here + 4] = _chain_bytes(n + 1 < len(self.items),
                                              item.next)
            items.append(bytes(raw))
        effects = []
        for n, node in enumerate(self.effects):
            raw = bytearray(node)
            here = AMIGA_LATER_EFFECT_NEXT
            raw[here:here + 4] = _chain_bytes(
                n + 1 < len(self.effects),
                int.from_bytes(node[here:here + 4], "big"))
            effects.append(bytes(raw))
        return bytes(record) + b"".join(items) + b"".join(effects)


def party_block_bytes(characters: Sequence[AmigaCharacter]) -> bytes:
    """A saved game's whole character region, in marching order.

    The party is a plain concatenation of :meth:`AmigaCharacter.block_bytes`
    with no separator and no index: the loader reads the party-count word and
    then reads one block after another off the same file descriptor, so the
    blocks' own lengths are what tell it where each begins.
    """
    return b"".join(c.block_bytes() for c in characters)


def _amiga_block(data: bytes, at: int, deltas: AmigaDeltas,
                 source: str = "") -> "tuple[AmigaCharacter, int]":
    """One character and everything hanging off it, and where it ends.

    The layout is **record, then `item_count` item nodes, then the effect
    chain**, and it is the same inside a saved game as it is in a `.guy`
    file.  CONFIRMED on the four played Curse characters, whose blocks are
    570, 590, 636 and 600 bytes: `428 + 66 x items + 10 x effects` is exact
    in 4 of 4, and the effect count is what the chain's own NULL terminator
    says it is.
    """
    end = at + deltas.record_size
    if end > len(data):
        raise AmigaRecordError(
            f"a {deltas.title} record wants {deltas.record_size} bytes at "
            f"{at:#x} and only {len(data) - at} are there")
    record = data[at:end]
    count = record[deltas.offset(deltas.dos_field("item_count").offset)]
    items = []
    for _ in range(count):
        if deltas.item_size is None:
            raise AmigaRecordError(
                f"{deltas.title} carries {count} items and no Amiga item node "
                f"of that title has ever been measured")
        items.append(AmigaItem.from_bytes(data[end:end + deltas.item_size],
                                          deltas))
        end += deltas.item_size
    effects = []
    if int.from_bytes(record[deltas.offset(deltas.dos_field(
            "effect_chain").offset):][:4], "big"):
        while end + deltas.effect_size <= len(data):
            node = data[end:end + deltas.effect_size]
            end += deltas.effect_size
            effects.append(node)
            if not int.from_bytes(node[6:10], "big"):
                break
        else:
            raise AmigaRecordError(
                f"the effect chain of the {deltas.title} record at {at:#x} "
                f"runs off the end of the data without a NULL next pointer")
    return AmigaCharacter.from_bytes(record, deltas, source, items,
                                     effects), end


def read_amiga_guy(path) -> AmigaCharacter:
    """One `SAVE/<NAME>.guy` -- an Amiga Curse pregenerated character.

    The eleven on Amiga Curse disk 1 are 428, 438, 458 and 468 bytes, which
    is 0, 1, 3 and 4 effect nodes, and the ids land on the right race in 11
    of 11: 107 for the two elves, 124 for the two half-elves, the dwarves'
    97/26/47, the gnome's 97/18/47/48 and 8 for the paladin.
    """
    import pathlib
    p = pathlib.Path(path)
    char, end = _amiga_block(p.read_bytes(), 0, CURSE_DELTAS, str(p))
    if end != p.stat().st_size:
        raise AmigaRecordError(
            f"{p.name} is {p.stat().st_size} bytes and its record, items and "
            f"effects account for {end}")
    return char


def looks_like_amiga_record(data: bytes, at: int, deltas: AmigaDeltas) -> bool:
    """Whether a character record plausibly starts here.

    Two things a saved game's other bytes do not do together: **16 bytes of
    printable ASCII terminated and padded with NUL**, and **six
    `(current, maximum)` ability pairs of equal, legal bytes** at `0x010`.
    On the two saved games this project has, it finds the four Curse
    characters at `0x3219`, `0x3453`, `0x36A1` and `0x391D` and the six
    Silver Blades ones at `0x1417` onwards, and nothing else in 22 454 bytes.

    **It would miss a character whose abilities have been drained**, because
    the pair test wants current and maximum equal and a drained score is
    below its maximum.  Every specimen this project has is undrained, so the
    looser test has never been needed; a saved game taken after a shadow or
    a wight is what would need it.
    """
    if at < 0 or at + deltas.record_size > len(data):
        return False
    name = data[at:at + AMIGA_NAME_SIZE]
    stop = name.find(b"\0")
    if stop < 1 or any(name[stop:]):
        return False
    if not all(0x20 <= b < 0x7F for b in name[:stop]):
        return False
    for i in range(6):
        low, high = data[at + 0x10 + 2 * i], data[at + 0x11 + 2 * i]
        if low != high or not 1 <= low <= 25:
            return False
    return True


def party_in_savegame(data: bytes, deltas: AmigaDeltas) -> list[AmigaCharacter]:
    """Every character block in an Amiga `savgam<slot>.dat` or `.sav`.

    A scan rather than a parse: the saved game's own table of contents is
    `#28 (Decode an Amiga saved game, not just a character file)`'s to find,
    and this needs only the character blocks.  `looks_like_amiga_record` says
    what the signature is and what it found.
    """
    found: list[AmigaCharacter] = []
    at = 0
    while at + deltas.record_size <= len(data):
        if looks_like_amiga_record(data, at, deltas):
            char, at = _amiga_block(data, at, deltas, "savegame")
            found.append(char)
        else:
            at += 1
    return found


# ---------------------------------------------------------------------------
# Amiga Curse and Silver Blades -> the neutral record (#28, step 3)
# ---------------------------------------------------------------------------
#
# The third and fourth readers in `goldbox/neutral.py`'s set, beside
# `goldbox.c64_codec.read`, `goldbox.dos.to_neutral` and `to_neutral` above.
#
# **It does not go through `goldbox.dos.to_neutral` the way the Amiga Pool of
# Radiance reader does, and that is not a choice.**  That reader re-cuts its
# record into the 285-byte DOS one and hands it over, so every grade and every
# provenance line the DOS side earned carries across.  `goldbox.dos.to_neutral`
# raises `WrongTitleError` for anything but Pool of Radiance -- no other pair
# of ports has been measured against each other yet (#53) -- so there is
# nothing here to hand a Curse record to.  What this reader shares with it
# instead is the **field table**: every value below is read through
# `goldbox/dos_layout.py`'s own table for the title, at that field's own
# confidence, so a correction there reaches here with no second edit.
#
# Two conventions come from what landed for the DOS side on 2026-09-04 and are
# followed rather than reinvented:
#
#   * `granted_effects` carries **whole nine-byte effect records** -- the id,
#     a little-endian duration of zero, the value the effect carries and the
#     flag the engine reads when the item comes off -- because what a ring
#     does is in the record rather than in the id (#232);
#   * `status` is converted as a **name** (#235).  Here the name costs nothing:
#     both later Amiga titles index `neutral.STATUS_NAMES` in DOS's own order,
#     which is measured rather than assumed -- see
#     `AMIGA_LATER_STATUS_FIELD` above for the two string tables.
#
#: Fields of the title's DOS table with a neutral home of the same name.
#: Taken from `goldbox.dos.DIRECT` at call time rather than copied, because a
#: field that changes meaning there must not go on meaning the old thing here.
#: Every one of the forty-seven is in both later titles' tables.
#:
#: **A field leaving `goldbox.dos.DIRECT` leaves this reader too, in silence**,
#: which is how `class_bits` came to be dropped (#292); the two tests that
#: `later_field_disposition` backs are what catch it, so keep them.
#:
#: What is **not** here and is converted by a rule below: the class mask, the
#: abilities, the name, the spellbook, the memorised spells, the level
#: arrays, the spell-slot arrays, size, turn power, the status and its flag,
#: the attack forms, the roster tail, the effect records and the items.
#: `abilities_second` is one more: it has no DOS field name of its own, so it
#: never appears in `later_field_disposition`'s table, the same way DOS's own
#: `field_disposition` never names it either.
#:
#: **The combat icon is a fourth kind of "not here", by design rather than by
#: omission.** `icon_head`, `icon_body` and `icon_colours` are TRANSFORMED
#: below -- and `icon_dimension` stays DROPPED -- but none of the three is
#: ever set on the `NeutralCharacter` this function returns, the same way
#: `goldbox.dos.to_neutral` neither sets nor drops them for a DOS source
#: (watched: a synthetic DOS record with a chosen figure comes back from
#: `goldbox.dos.to_neutral` with no `icon_head` field and nothing in
#: `dropped`). The neutral vocabulary has nowhere to put a combat figure --
#: the C64 stores drawn cells, not an index -- so both readers leave these
#: three silent and the actual conversion is a raw-record bypass:
#: `editor.convert.amiga_combat_icon` reads them straight off this
#: `AmigaCharacter` (or off a `DosCharacter`, for Pool of Radiance) and hands
#: the result to `goldbox.dos.write`'s own `icon` argument, which
#: `goldbox.amiga.write_later` now takes too (#396, #319,
#: docs/199-amiga-combat-icons.md).
LATER_TRANSFORMED: tuple[tuple[str, str], ...] = (
    ("class_bits", "reread from the level array into the shared bit order, "
                   "the way the DOS reader rereads its own: this port gives "
                   "the paladin and the ranger one bit between them, where "
                   "the neutral record and the C64 give the ranger a bit of "
                   "its own"),
    ("name_length", "there is no count byte: the Amiga name is 16 bytes "
                    "terminated and padded with NUL"),
    ("name_text", "the sixteen NUL-padded bytes, as the neutral name"),
    ("spellbook", "the spell ids in the book, ascending; Silver Blades' 15 "
                  "bytes of bitmask are unpacked and Curse's 100 flags read "
                  "straight"),
    ("spells_memorised", "reversed, the way the DOS reader reads its own: "
                         "highest first"),
    ("class_levels", "named rather than numbered, into the neutral levels "
                     "map"),
    ("former_class_levels", "named rather than numbered, into the neutral "
                            "former_levels map, non-zero entries only "
                            "(#256)"),
    ("former_level", "the same level again; not read separately -- it is "
                     "the DOS reader's disagreement check, and this reader "
                     "shares the field table rather than the check"),
    ("spells_castable_cleric", "into the neutral spells_castable map, at the "
                               "Amiga's own array width"),
    ("spells_castable_druid", "into the same map"),
    ("spells_castable_magic_user", "into the same map"),
    ("size", "1/2 on DOS becomes 0/1 in the neutral size_small"),
    ("attack_forms", "copied as a block"),
    ("roster_tail", "copied as a block"),
    ("field_10c_10f", "its first byte becomes the neutral status, by name, "
                      "and its second the active flag; the last two are not "
                      "converted"),
    ("encumbrance", "copied, and it is money plus item weight -- a writer "
                    "that recomputes it should"),
    ("icon_head", "the combat icon's head: DOS's own CHEAD.DAX index, read "
                  "by the same routine at the same offset both Amiga "
                  "binaries carry (#396, docs/199-amiga-combat-icons.md). "
                  "Converted the way `goldbox.dos`'s own icon_head is -- "
                  "the caller who has a raw record in hand builds a "
                  "`goldbox.iconparts.DosIcon` from it (`editor.convert."
                  "amiga_combat_icon`) rather than through this reader's "
                  "own neutral vocabulary, which has nowhere to put a "
                  "combat figure (#379)"),
    ("icon_body", "the combat icon's body: DOS's own CBODY.DAX index, "
                  "likewise -- see icon_head"),
    ("icon_colours", "the six DOS icon_colours pairs, unchanged: both "
                     "Amiga binaries recolour with DOS's own six-byte part "
                     "table (docs/199-amiga-combat-icons.md) -- see "
                     "icon_head"),
) + tuple(
    (name, "a (base, current) pair here as it is on DOS from Curse onwards; "
           "the first byte crosses as the neutral score and the second goes "
           "to abilities_second, and neither codec claims to know which the "
           "engine treats as current")
    for name in neutral.ABILITIES
)

#: Fields the read leaves behind, and why.  Every one is reported: a drop that
#: nobody names is what `docs/117-save-conversion.md` forbids.
LATER_DROPPED: tuple[tuple[str, str], ...] = (
    ("item_chain", "live heap state: the head of the Amiga's item list, "
                   "which the loader overwrites with the address it "
                   "allocates. The items themselves are converted"),
    ("item_count", "implied by the inventory that is converted"),
    ("effect_chain", "live heap state, the same way; the effect records "
                     "themselves are converted"),
    ("heap_104", "live heap pointers -- two longwords the saved game's own "
                 "loader clears outright"),
    ("hands_used", "live combat state"),
    ("unnamed_0ab", "one unattributed byte, stable per character"),
    ("strength_bonus", "a boolean on DOS, derived from strength"),
    ("icon_dimension", "the combat icon's size: 1 for every player character "
                       "(#396, docs/199-amiga-combat-icons.md), and the C64 "
                       "has one size byte where DOS and the Amiga both keep "
                       "two fields -- see icon_head's LATER_TRANSFORMED "
                       "entry for the other three combat-icon fields, which "
                       "this reader used to drop alongside it"),
    ("portrait_head", "the sheet portrait's head: a position in the Amiga's "
                      "own creation menu, and nobody has read that menu's "
                      "tables out of the Amiga executables. Reading them is "
                      "what would let the portrait cross, exactly as it did "
                      "for DOS"),
    ("portrait_body", "see portrait_head; the body half of the same pair"),
    ("field_83_87", "five bytes in Curse and four in Silver Blades that DOS "
                    "calls unknown, one of which is the share of treasure a "
                    "character takes. **Not zero in a record the Amiga "
                    "engine wrote**, which this line claimed until "
                    "2026-09-07: the four played Curse characters in "
                    "SAVE/savgamA.dat hold 00 00 01 00 00 and five of the "
                    "six Silver Blades ones hold 00 01 00 00, which is "
                    "`goldbox.dos.FIELD_83_87` byte for byte. The eleven "
                    ".guy pregens and Silver Blades' MALACHITE hold zeros, "
                    "and they were what the old reading rested on. The "
                    "reader still drops the whole run and `write_later` "
                    "writes the DOS constant, which is what the engine "
                    "writes. **Only one of the remaining bytes is genuinely "
                    "homeless**: the neutral record has no field for a "
                    "treasure share, and no specimen has separated it from "
                    "the run's other constant bytes. The control byte -- "
                    "byte 1 of Curse's run, byte 0 of Silver Blades' -- is "
                    "no longer one of them: `to_neutral_later` reads it into "
                    "`npc` and `npc_control_byte` itself now, the same index "
                    "`goldbox.dos.to_neutral` computes (#386, closed "
                    "2026-09-07)"),
    ("spells_castable_unattributed", "Silver Blades' fourth spell-slot "
                                     "array, which no character of either "
                                     "port sets a byte of and no class has "
                                     "been shown to use"),
    ("turn_class", "the row of the turning matrix an undead creature "
                   "answers to, read off the *target* rather than the "
                   "caster: 0 for every player character, and the neutral "
                   "record has no field for it. The DOS reader drops it for "
                   "the same reason (#297, docs/178-turning-undead.md)"),
    ("paladin_cures", "how many times the paladin may still CURE DISEASE, "
                      "named in `goldbox/dos_layout.py` from the Curse "
                      "decompilation and measured 1 for every paladin and 0 "
                      "for everybody else. The neutral record has no field "
                      "for it, so nothing here can take it; the DOS writer "
                      "derives it from the class instead (#299)"),
)

#: The plain-English half of `LATER_DROPPED`, and the only one that reaches
#: the report.  It is read in the debug log and in a `--report` printout
#: rather than in a pane: Donald ruled on 2026-09-08 that a drop list is this
#: project's own accounting and goes to `wish/debuglog.py`
#: (`.claude/rules/conversions.md`), so no entry here carries a
#: `(NOT APPROVED)` marker.  Written for a reader all the same, because a bug
#: report quotes it: `.claude/rules/gui-text.md` keeps a memory address, a file offset
#: and a bare issue number out of anything shown in the interface, and the
#: entries above carry all three kinds of detail on purpose -- so the reader
#: composes its report from this table and never from those.  A name with no
#: entry here is a drop the report stays silent about; only the fields whose
#: loss a player could notice have one, which is the same line
#: `goldbox/dos.py` draws with `UNREPORTED_DROPS`.
LATER_DROPPED_PLAYER_TEXT: dict[str, str] = {
    "item_chain": "Item list bookkeeping: the list's own internal links, "
                  "which the game rebuilds when it loads the party",
    "effect_chain": "The running-effects list's own internal link; the "
                    "effects themselves are kept separately",
    "heap_104": "Internal game state kept only while the game is running, "
                "not shown to the player",
    "hands_used": "Which hand is holding a weapon right now; set again the "
                  "next time the character fights",
    "unnamed_0ab": "One byte in the character record nobody has identified "
                   "yet",
    # icon_head, icon_body and icon_colours came off this table on
    # 2026-09-07 (#396, #319): the combat icon is DOS's own art, DOS's own
    # numbering and DOS's own colour pairs, and converts rather than drops.
    # icon_dimension stays on `LATER_DROPPED` -- the C64 has one size byte
    # where the Amiga keeps two -- but carries no line here, matching
    # Donald's ruling on the identical DOS line, 2026-09-06: "All PCs are
    # the same size, so it doesn't matter. Just leave that line out during
    # conversions."
    "portrait_head": "Character portrait (head): the character-creation art "
                     "this game chooses portraits from has not been read, so "
                     "the portrait cannot be matched",
    "portrait_body": "Character portrait (body): the character-creation art "
                     "this game chooses portraits from has not been read, so "
                     "the portrait cannot be matched",
    # No marker on the line below: every entry in this table becomes a drop
    # line, and a drop line goes to `wish/debuglog.py` rather than to a pane
    # since Donald's ruling of 2026-09-08 (`.claude/rules/conversions.md`,
    # *"a drop line is therefore never a string Donald words"*).
    "field_83_87": "Treasure share: how this character's cut of the "
                   "party's loot is set has not been converted yet, so it "
                   "resets to the game's own default",
    "spells_castable_unattributed": "A fourth list of spell slots that no "
                                    "character of this game uses and no "
                                    "class has been shown to own",
}

#: The one thing the neutral record cannot say about these two titles, and it
#: is a classification rather than a byte: which effect records are **innate**
#: -- a property of the race or the class -- and which an item granted.
#: `goldbox.dos.INNATE_EFFECTS` is Pool of Radiance's id space and must not be
#: applied here: 107 is an elf in Curse where Silver Blades' PAINE carries 105
#: for a ranger, so the two titles do not even share one namespace with each
#: other.  Everything at duration zero therefore goes into `granted_effects`
#: whole, and this warning says so.
LATER_EFFECT_SPLIT_UNKNOWN = (
    "The effects that never expire are all converted together: which of them "
    "are racial or class properties and which came from an item cannot be "
    "told apart yet for this game, because the list of built-in effects has "
    "only ever been read for Pool of Radiance")


def later_field_disposition(deltas: AmigaDeltas) -> dict[str, str]:
    """Every field of this title's DOS table, and what the read does with it.

    The test that keeps the reader honest, and the same shape
    `goldbox.dos.field_disposition` returns: a field the table declares and
    this names nowhere would be a field dropped in silence.  `gap_` fields are
    the bytes no field of the DOS table claims and are accounted for here as a
    group rather than one at a time.
    """
    from . import dos_codec as _dos

    declared = {f.name for f in dos_layout.layout_for(deltas.dos)}
    direct = [(n, n) for n, _ in _dos.DIRECT
              if n in declared and n not in _dos.ABILITY_ORDER]
    transformed = [(n, why) for n, why in LATER_TRANSFORMED if n in declared]
    dropped = [(n, why) for n, why in LATER_DROPPED if n in declared]
    dropped += [(n, "bytes no field of the DOS table for this title claims")
                for n in sorted(declared) if n.startswith("gap_")]
    return neutral.disposition(direct, transformed, dropped, "the neutral")


def to_neutral_later(char: AmigaCharacter) -> NeutralCharacter:
    """One Amiga Curse or Silver Blades character in the neutral record.

    Every value is read through `goldbox/dos_layout.py`'s table for the
    title, at that field's own confidence, so a writer asking for a grade it
    will stand behind gets the same answer it would get from a DOS record of
    the same title.  What the record holds and no neutral field does is named
    on the way past rather than lost -- `LATER_DROPPED` is the whole list and
    :func:`later_field_disposition` is the test that it is.
    """
    from . import dos_codec as _dos

    deltas = char.deltas
    table = dos_layout.FIELDS_BY_NAME_FOR[deltas.dos.key]
    out = NeutralCharacter("Amiga", source=char.source,
                           game=games.by_key(deltas.key))

    def grade(name: str) -> Confidence:
        return table[name].confidence

    out.set("name", char.name,
            f"the Amiga {AMIGA_NAME_SIZE}-byte NUL-padded name at 0x000",
            grade("name_text"), neutral.Provenance.RESHAPED)

    for name, _ in _dos.DIRECT:
        if name in _dos.ABILITY_ORDER:
            continue                      # a (base, current) pair; see below
        f = table[name]
        value = char.get(name)
        if isinstance(value, (bytes, bytearray)):
            # `#294`, the shape rather than one field of it: a name in
            # `DIRECT` whose base table declares it `U8`/`I8` is read back
            # raw the moment a later title's `sizes` widens it -- the check
            # `goldbox/dos_layout.py:layout_for` itself makes.  The abilities
            # are the only field this has happened to today; the next one
            # would otherwise reach here as a silent byte-pair copy, exactly
            # as the abilities did before this fix.
            raise AmigaRecordError(
                f"{deltas.title} {name} is {f.size} raw bytes on this port "
                f"and `to_neutral_later`'s DIRECT loop copies it as a "
                f"number: it needs the same kind of exception the abilities "
                f"got, not a straight copy")
        out.set(name, value,
                f"Amiga {deltas.title} {name} @{deltas.offset(f.offset):#05x} "
                f"({f.confidence}), read big-endian through the DOS table",
                f.confidence)

    # -- the abilities, a DOS-shaped pair carrying the same asymmetry --------
    # `goldbox.dos.DIRECT` hands every name in `ABILITY_ORDER` back as a
    # two-byte `RAW` chunk rather than a number (`goldbox/dos_layout.py`'s
    # `sizes` widen every one of the seven), so the loop above would
    # otherwise pass the pair whole into a field the neutral record and
    # `goldbox.c64_codec.write` both expect to be a score -- which is
    # `#294`.  DOS's own reader steps around the same widening with a
    # `continue` at the top of its `DIRECT` loop and a second pass that calls
    # `_ability_pair`; this is that second pass, written locally because
    # `_ability_pair` takes a `DosCharacter` and this reader has no DOS record
    # to hand it -- `char.get(name)` already returns the same two raw bytes
    # `_ability_pair` reads with `dos.raw(name)`.
    #
    # Which byte is which is no longer an inference from the DOS engine: for
    # `#406 (An Amiga Curse or Silver Blades character converted from the
    # Amiga keeps a temporary strength boost or drain for good, the same
    # crossed-pair bug as #404)` both `/Curse` and `/Secret` were read
    # directly.  Each recomputes one ability from a character's items and
    # running spells with the identical shape DOS's own recompute has
    # (`docs/204-the-dos-ability-pair.md`): it seeds from `$10(a0, d0.l)`
    # (byte 0, the permanent score) and `$1d(a0)` (the permanent percentile),
    # walks the effects, and stores the result to `$11(a0)` (byte 1, the
    # score in force) and `$1c(a0)` (the percentile in force) --
    # `/Curse` file offset `0xf5ee` seeding and `0xf9ce`-`0xf9ec` storing,
    # `/Secret` file offset `0x131f8`/`0x13202` seeding and
    # `0x13608`-`0x13612` storing.  Byte 0 is written only once elsewhere in
    # either binary (character creation's roll), the same shape `#401` found
    # in five DOS engines.  So for the six ability scores byte 1 is the
    # score in force and byte 0 is `abilities_second`'s permanent copy,
    # exactly `goldbox.dos._PERMANENT_FIRST`'s asymmetry; exceptional
    # strength runs the other way and keeps its existing order.
    second: dict[str, int] = {}
    for name in _dos.ABILITY_ORDER:
        f = table[name]
        pair = char.get(name)
        if name == "exceptional_strength":
            in_force, permanent, which = pair[0], pair[-1], "first"
        else:
            in_force, permanent, which = pair[-1], pair[0], "second"
        out.set(name, in_force,
                f"Amiga {deltas.title} {name} @{deltas.offset(f.offset):#05x} "
                f"({f.confidence}), the {which} of its two bytes, the score "
                f"in force (#406, docs/204-the-dos-ability-pair.md)",
                f.confidence)
        second[name] = permanent
    out.set("abilities_second", second,
            f"Amiga {deltas.title} keeps every ability twice; these are the "
            f"permanent score for the six abilities and the permanent "
            f"percentile for exceptional strength (#406)",
            Confidence.CONFIRMED, neutral.Provenance.RESHAPED)

    # -- the class mask, which is not a copy on this port either -------------
    # The Amiga stores this field exactly as DOS does, ambiguity and all:
    # Silver Blades' shipped PAINE reads `$40` with 8 in the ranger's level
    # slot and GUY DE VALOIS reads `$40` with 8 in the paladin's, so the byte
    # alone does not say which class it is and the level array is what
    # settles it.  Copying it would make an Amiga ranger a C64 paladin, the
    # defect `goldbox.dos.neutral_class_bits` exists to stop; and after
    # `class_bits` left `_dos.DIRECT` the loop above stopped setting the
    # field at all, which left the C64 record with no class bit set (#292).
    f = table["class_bits"]
    former = char.get("former_class_levels") if (
        "former_class_levels" in table) else b""
    out.set("class_bits",
            _dos.neutral_class_bits_from(char.get("class_bits"),
                                         char.get("class_levels"), former),
            f"Amiga {deltas.title} class_bits @{deltas.offset(f.offset):#05x} "
            f"({f.confidence}), reread from the level array because the "
            f"paladin and the ranger share one bit here as they do on DOS",
            f.confidence, neutral.Provenance.RESHAPED)

    out.set("spells_known", char.spellbook,
            "the Amiga spellbook, "
            + ("15 bytes of bitmask unpacked least significant bit first"
               if deltas.spellbook_bytes else "one byte per spell"),
            grade("spellbook"))

    memorised = [b for b in reversed(char.get("spells_memorised")) if b]
    out.set("spells_memorised", memorised,
            "the Amiga memorised region, reversed into the neutral "
            "highest-first order",
            grade("spells_memorised"))
    if not memorised:
        out.warnings.append(
            "No character of this game on any disk here has a spell "
            "memorised, so the order they are stored in has not been checked "
            "for it; the order the other games use was assumed")

    slots = table["class_levels"].size
    named = _dos.CLASS_LEVEL_SLOTS[:slots]
    raw = char.get("class_levels")
    out.set("levels", {name: raw[n] for n, name, _ in named},
            f"Amiga class_levels @"
            f"{deltas.offset(table['class_levels'].offset):#05x}, permuted "
            f"from class number to class name",
            grade("class_levels"))

    # -- the class a dual-classed human left, where the title has one -------
    if "former_class_levels" in table:
        fc = table["former_class_levels"]
        former_raw = char.get("former_class_levels")
        out.set("former_levels",
                {name: former_raw[n] for n, name, _ in named
                 if n < len(former_raw) and former_raw[n]},
                f"Amiga former_class_levels @{deltas.offset(fc.offset):#05x}, "
                f"permuted from class number to class name, non-zero "
                f"entries only",
                grade("former_class_levels"))

    castable = dict(char.spell_slots)
    castable.pop("unattributed", None)
    out.set("spells_castable", castable,
            "the Amiga spell-slot arrays, "
            + ("six bytes each where DOS spends five"
               if deltas is CURSE_DELTAS else "seven bytes each, as DOS"),
            grade("spells_castable_cleric"))

    out.set("size_small", max(0, char.get("size") - 1),
            "the Amiga size byte, less one", grade("size"))
    out.set("attack_forms", char.get("attack_forms"),
            f"Amiga attack_forms @"
            f"{deltas.offset(table['attack_forms'].offset):#05x}",
            grade("attack_forms"))
    out.set("roster_tail", char.get("roster_tail"),
            f"Amiga roster_tail @"
            f"{deltas.offset(table['roster_tail'].offset):#05x}",
            grade("roster_tail"))
    out.set("encumbrance", char.get("encumbrance"),
            f"Amiga encumbrance @"
            f"{deltas.offset(table['encumbrance'].offset):#05x}",
            grade("encumbrance"))

    tail = char.get(AMIGA_LATER_STATUS_FIELD)
    at = deltas.offset(table[AMIGA_LATER_STATUS_FIELD].offset)
    if tail[0] < len(neutral.STATUS_NAMES):
        out.set("status", neutral.STATUS_NAMES[tail[0]],
                f"Amiga status @{at:#05x} = {tail[0]}, the same "
                f"{len(neutral.STATUS_NAMES)} status words in the same order "
                f"the DOS record indexes",
                Confidence.CONFIRMED, neutral.Provenance.RESHAPED)
    else:
        out.drop(f"The character's status: this save holds {tail[0]} there "
                 f"and the game has only {len(neutral.STATUS_NAMES)} states")
    out.set("active", bool(tail[AMIGA_LATER_STATUS_GATE]),
            f"Amiga @{at + AMIGA_LATER_STATUS_GATE:#05x}: the flag the engine "
            f"clears whenever the status leaves okay or animated",
            Confidence.PROBABLE)

    granted = [amiga_por_effect_to_dos(e) for e in char.effects]
    granted = [e for e in granted if int.from_bytes(e[1:3], "little") == 0]
    if granted:
        out.set("granted_effects", granted,
                "the Amiga effect nodes that never expire, each re-cut to "
                "the nine bytes the DOS .SPC record holds",
                Confidence.PROBABLE)
        out.warnings.append(LATER_EFFECT_SPLIT_UNKNOWN)

    out.set("inventory", [_dos.item_to_c64(it.to_dos_bytes())
                          for it in char.items],
            f"the {deltas.item_size}-byte Amiga item nodes, each re-cut to the "
            f"63 DOS holds and projected onto sixteen",
            Confidence.CONFIRMED)

    # -- the NPC control byte: bit 7 says the engine drives this character --
    # The second byte of `field_83_87`'s five-byte run in Curse, the first of
    # Silver Blades' four -- `goldbox.dos.to_neutral` computes the same index
    # the same way (#303), and this reader used to leave the whole run on
    # `LATER_DROPPED` without ever taking the one byte that has a home
    # (`#386 (An Amiga Curse or Silver Blades companion converts to an
    # ordinary character, because the later-titles reader never looks at the
    # control byte)`).
    f83 = table["field_83_87"]
    control_raw = char.get("field_83_87")
    control_index = 1 if len(control_raw) == 5 else 0
    control_offset = deltas.offset(f83.offset) + control_index
    control = control_raw[control_index]
    out.set("npc", bool(control & 0x80),
            f"bit 7 of Amiga {deltas.title} field_83_87 "
            f"@{control_offset:#05x}, the same control byte "
            f"`goldbox.dos.to_neutral` reads",
            Confidence.CONFIRMED)
    if control & 0x80:
        out.set("npc_control_byte", control,
                f"Amiga {deltas.title} field_83_87 @{control_offset:#05x}, "
                f"unchanged -- bit 7 plus the low seven bits of morale, "
                f"stored halved",
                Confidence.PROBABLE)

    declared = {f.name for f in dos_layout.layout_for(deltas.dos)}
    for name, _why in LATER_DROPPED:
        if name in declared and name in LATER_DROPPED_PLAYER_TEXT:
            out.drop(LATER_DROPPED_PLAYER_TEXT[name])
    return out


# ---------------------------------------------------------------------------
# The neutral record -> Amiga Curse and Silver Blades (#384)
# ---------------------------------------------------------------------------
#
# The third Amiga writer, and it is built the way :func:`write_por` is rather
# than as a new invention: `goldbox.dos.write` does the conversion, because
# **the Amiga record is the title's DOS record in another shape**, and what
# is here is the re-cut plus the handful of bytes the Amiga has and DOS does
# not.  Every grade and every provenance line the DOS side earned crosses
# with it.
#
# Three things differ from Pool of Radiance's writer, each measured:
#
#   1. **The chain fields are booleans the loader tests**, so a record with
#      nodes behind it must carry a non-zero head where `write_por` writes
#      NULL.  :meth:`AmigaCharacter.block_bytes` already does that, which is
#      why this returns an `AmigaCharacter` rather than loose bytes -- the
#      party goes to `tools/amigasavegame.py`'s `rebuild` as blocks.
#   2. **Silver Blades' spellbook is packed into bits**, LSB first.
#   3. **The effect chain is not `goldbox.dos.write`'s `.SPC` payload.**  See
#      :func:`_later_effect_nodes` for the measurement that says why.

#: Amiga record bytes with no DOS counterpart, per title: `(offset, size,
#: why)`.  The round trip masks **this list** plus `goldbox.dos`'s own
#: `WRITE_UNSOURCED`, `WRITE_UNSOURCED_LATER`, `WRITE_CONSTANTS`,
#: `WRITE_DEFAULTS` and `WRITE_DERIVED`, rather than whatever happens to
#: differ, so a new difference fails instead of being absorbed.
#:
#: Every value is zero and every one is measured rather than assumed: the 21
#: specimens `tools/amigarecords.py` pulls off the disks -- eleven Curse
#: `.guy` pregens, the four played Curse characters in `SAVE/savgamA.dat` and
#: the six shipped Silver Blades characters in `SAVE/savgamA.sav` -- read 0 at
#: all six Curse offsets in 15 of 15 and at all three Silver Blades ones in
#: 6 of 6.
LATER_WRITE_UNSOURCED: dict[str, tuple[tuple[int, int, str], ...]] = {
    CURSE_DELTAS.key: (
        (0x0FB, 1, "the pad ahead of the fourteen money bytes, which the "
                   "record unpacker at /Curse 0x270A6 skips over; 0 in 15 "
                   "of 15"),
        (0x133, 1, "the sixth byte of the cleric spell-slot array, which "
                   "DOS spends five on; 0 in 15 of 15"),
        (0x139, 1, "the sixth byte of the druid array; 0 in 15 of 15"),
        (0x13F, 1, "the sixth byte of the magic-user array; 0 in 15 of 15"),
        (0x151, 1, "the pad between item_count at 0x150 and the item "
                   "pointer array at 0x152; 0 in 15 of 15"),
        (0x1AB, 1, "the trailing byte that makes 427 into 428, and the "
                   "reason setmem clears 0x1AC; 0 in 15 of 15"),
    ),
    SILVER_BLADES_DELTAS.key: (
        (0x095, 1, "the pad ahead of the u32 effect chain at 0x096; 0 in 6 "
                   "of 6"),
        (0x0C7, 1, "the pad ahead of the u32 experience at 0x0C8; 0 in 6 of "
                   "6"),
        (0x0FD, 1, "the pad between item_count at 0x0FC and the item "
                   "pointer array at 0x0FE; 0 in 6 of 6"),
    ),
}

#: Amiga bytes the **engine** recomputes from the readied weapon when it
#: loads a saved game, so a resave differing here is the engine's own
#: arithmetic and not a loss.  `LATER_WRITE_UNSOURCED` is the load-time
#: counterpart for bytes nothing sources at all; this is for bytes the
#: writer does source, correctly, and the loader overwrites anyway.  Masked
#: in the resave diff beside it (`#402 (Amiga Curse recomputes thac0_current
#: and a roster_tail byte on load, and no declared list says so)`).
#:
#: **CURSE ONLY, one WinUAE run, 2026-09-07, lane `wish384`.** A party
#: `write_later` converted from `WISH-SPEC-curse-52-dialog-converted-resave.D64`
#: was loaded in Amiga Curse of the Azure Bonds, drawn, and saved back
#: through `ENCAMP > SAVE`. Against the engine's own resave
#: (`WISH-SPEC-coab-amiga-converted-resave/savgamC.dat`): MATHEW's
#: `thac0_current` moved `0x2F` to `0x2A` and PHILIPPE's the same field moved
#: `0x29` to `0x28`; MATHEW's sheet drew `THAC0 18`, which is `60 - 0x2A`, so
#: the recomputed value is the one a player reads and the stored one never
#: reached the screen. MATHEW's `roster_tail`'s sixth byte -- one of the
#: eight running attack-form bytes the field's own note in
#: `goldbox/dos_layout.py` describes -- moved `0x08` to `0x02` the same way.
#: The other five characters and the whole Silver Blades party in the same
#: run did not move at either byte, which says nothing either way: their
#: converted values already agreed with what the engine would have
#: recomputed. `docs/203-a-converted-later-amiga-party-in-the-running-game.md`.
#:
#: **Silver Blades is UNMEASURED, not confirmed absent.** Its converted
#: party happened to already agree, which proves nothing; staging an
#: impossible value (`tools/cursethac0.py` uses `0x0A`, THAC0 50) into a
#: converted Silver Blades record and reading a resave back would settle it
#: in one boot.
#:
#: **Only the one measured byte of `roster_tail` is here, not the whole
#: nine-byte field.** The other eight have never been seen to move, so they
#: stay outside the mask and a real regression in them would still be
#: caught.
LATER_WRITE_DERIVED: dict[str, tuple[tuple[int, int, str], ...]] = {
    CURSE_DELTAS.key: (
        (0x19E, 1, "thac0_current, recomputed on load from the readied "
                   "weapon"),
        (0x1A5, 1, "roster_tail's sixth byte, one of the eight running "
                   "attack-form bytes, recomputed the same way"),
    ),
    SILVER_BLADES_DELTAS.key: (),
}

#: The item node's three insertions, the same in both later titles.  **Zero
#: is what the game itself writes**: each executable's item constructor
#: (`/Curse` `0x1C1EA`, `/Secret` `0x1B862`) opens `setmem(node, size, 0)`
#: and then writes fifteen named arguments, none of which lands on one of
#: these.  The nine nodes in Curse's `SAVE/savgamA.dat` read 0 at `0x02F` in
#: 9 of 9 and 52 and 47 at the other two in 9 of 9, which is uninitialised
#: stack the `ITEM<n>` template loader copied -- a different code path from
#: the one a converted item takes, and not a value to reproduce.
AMIGA_LATER_ITEM_PADS = (0x02F, 0x03B, 0x03E)

#: Bytes of a written item node with no neutral source, and what they are.
#: The round trip masks these; everything else in the node has to match.
LATER_ITEM_WRITE_UNSOURCED: tuple[tuple[int, int, str], ...] = (
    (0x000, 0x02A,
     "the rendered display line, left NUL. It is a cache the game composes "
     "when it draws the ITEMS screen and writes back -- watched happening in "
     "Amiga Pool of Radiance (`docs/182-amiga-por-in-the-running-game.md`), "
     "where a node of 42 NUL bytes still drew YES LONG SWORD, every column "
     "coming from a field and none from this buffer"),
    (0x02A, 4,
     "the next pointer: a live Amiga heap address in a record the game "
     "wrote, and here a 1 or a 0 according to whether another node follows, "
     "which is all the loader's tst.l reads"),
    (0x02F, 1,
     "the insertion ahead of name1; 0 in 9 of 9 nodes and 0 is what the "
     "item constructor's setmem writes"),
    (0x03B, 1,
     "an insertion the item constructor never writes. The nine nodes on "
     "Curse disk 1 read 52 here in 9 of 9 because they came through the "
     "ITEM<n> template loader, which copies an uninitialised stack struct; "
     "a node the game builds itself is zero"),
    (0x03E, 1, "the same, reading 47 in 9 of 9 for the same reason"),
)

#: An effect node's byte at offset 1, which Pool of Radiance and Curse treat
#: as a pad and **Silver Blades does not**.
#:
#: CONFIRMED zero for Curse: 24 of 24 nodes -- the eleven `.guy` pregens, the
#: four played characters on disk 1 and both saved games of
#: `~/wish-specimens/coab-amiga`.  CONFIRMED zero for Amiga Pool of Radiance
#: on 62 records and for the party shipped on its disk 1 (#55).
#:
#: **Non-zero in 3 of the 5 Silver Blades nodes anywhere**, and the same
#: three values in all eight Amiga Silver Blades saved games on this machine,
#: including four the engine itself wrote: GUY DE VALOIS' effect `0x08`
#: carries `0x2E`, PAINE's `0x69` carries `0x6D`, MALACHITE's `0x2F` carries
#: `0x64`, and MALACHITE's other two (`0x1A`, `0x61`) carry zero.
#:
#: **It is not a DOS field.**  The DOS twins of those same three characters
#: -- `CHRDATA1.SFX`, `CHRDATA2.SFX` and `CHRDATA4.SFX` in the archives'
#: Silver Blades save directory -- are 9 and 27 bytes and read
#: `08 00 00 FF 00`, `69 00 00 FF 00` and `2F 00 00 FF 00`: zero in the
#: corresponding place, three of three.  So the value has no neutral source
#: and a converted character loses it.
#:
#: **CONFIRMED, from the code, as nothing** -- `#387`, settled and written up
#: at `docs/202-the-amiga-effect-node-pad.md`.  It is the alignment pad a C
#: compiler leaves in front of the node's `UWORD` duration at offset 2: both
#: titles keep effect nodes in a fixed-size pool `AllocMem`'d with no
#: `MEMF_CLEAR` and never cleared afterwards, the ten-byte constructor both
#: binaries share takes five arguments and ends in five stores that skip
#: offset 1, and a census of every load of a node's chain-head field --
#: 42 sites in `/Curse`, 39 in `/Secret`, plus the removal routine, the 97
#: per-effect expiry handlers, the 24 callees reached with a node live, and
#: every indexed access in both binaries -- finds **zero** that reach it.
#: `0x2E`, `0x6D` and `0x64` are whatever the Amiga's public memory held
#: under the pool's first three slots when SSI saved that party in 1990,
#: copied faithfully from file to file since; `#384`'s own converted party
#: went through the running game twice with zero there and came back with
#: zero still there.  Writing zero is therefore not a loss: nothing reads
#: this byte and nothing ever will.
AMIGA_LATER_EFFECT_UNKNOWN = 1

#: Bytes of a written effect node with no neutral source.
LATER_EFFECT_WRITE_UNSOURCED: tuple[tuple[int, int, str], ...] = (
    (AMIGA_LATER_EFFECT_UNKNOWN, 1,
     "the byte Silver Blades keeps beside the effect id and no other Gold "
     "Box record has: see AMIGA_LATER_EFFECT_UNKNOWN. Written zero -- a "
     "pad nothing computes and nothing consults, not a loss, though 3 of "
     "the 5 Silver Blades nodes anybody has ever seen hold something else "
     "there"),
    (AMIGA_LATER_EFFECT_NEXT, 4,
     "the next pointer: a live Amiga heap address in a record the game "
     "wrote, and here a 1 or a 0 according to whether another node follows"),
)


def later_unsourced_offsets(deltas: AmigaDeltas) -> tuple[int, ...]:
    """Amiga record offsets no DOS field of this title reaches.

    Computed from the shift map rather than listed, so
    :data:`LATER_WRITE_UNSOURCED` cannot quietly disagree with the map it is
    about -- `tests/test_amigalaterwrite.py` asserts the two are the same
    offsets.
    """
    covered: set[int] = set()
    if deltas.spellbook_bytes is not None:
        covered.update(range(AMIGA_SSB_SPELLBOOK_AT,
                             AMIGA_SSB_SPELLBOOK_AT + deltas.spellbook_bytes))
    for f in dos_layout.layout_for(deltas.dos):
        try:
            at = deltas.offset(f.offset)
        except AmigaRecordError:
            continue                      # the re-encoded spellbook, above
        covered.update(range(at, at + f.size))
    return tuple(sorted(set(range(deltas.record_size)) - covered))


def later_write_shape(char: NeutralCharacter,
                      deltas: "AmigaDeltas | str | None" = None) -> AmigaDeltas:
    """Which Amiga record :func:`write_later` will build for this character.

    **The title is the character's, not the caller's**, exactly as
    `goldbox.dos.write_shape` decides it: a conversion is between two ports
    of the same title and never between titles
    (`.claude/rules/conversions.md`).  `deltas` overrides it for a caller
    that has already resolved the title.

    Pool of Radiance is refused by name rather than by falling through, since
    :func:`write_por` is its writer and a caller that lands here has the
    wrong one.
    """
    if deltas is None:
        game = char.game
        key = getattr(game, "key", game) or dos_layout.POOL_OF_RADIANCE.key
    else:
        key = getattr(deltas, "key", deltas)
    for known in AMIGA_DELTAS:
        if known.key == key:
            return known
    if key in (dos_layout.POOL_OF_RADIANCE.key, "pools-of-darkness"):
        raise AmigaRecordError(
            f"{key} has its own Amiga writer: write_por for Pool of "
            f"Radiance and write for Pools of Darkness")
    raise AmigaRecordError(
        f"no Amiga record of {key} has been decoded; the two this writes "
        f"are {' and '.join(s.title for s in AMIGA_DELTAS)}")


@dataclass
class LaterWriteReport(PorWriteReport):
    """Where every byte of an Amiga Curse or Silver Blades block came from.

    The same contract :class:`PorWriteReport` states -- **every** byte
    explained, not only the non-zero ones -- over the whole block rather than
    over one file: offsets `0` to `deltas.record_size - 1` are the record,
    then one item node after another, then the effect chain, which is the
    order the loader reads them in.
    """

    total: int = 0


def _later_name_bytes(record: bytes, deltas: AmigaDeltas) -> bytes:
    """DOS's count byte and its text as the Amiga's 16 NUL-padded bytes."""
    size = deltas.dos_field("name_text").size
    count = min(record[0], size)
    return record[1:1 + count].ljust(AMIGA_NAME_SIZE, b"\0")[:AMIGA_NAME_SIZE]


def _later_spellbook_bytes(record: bytes, deltas: AmigaDeltas) -> bytes:
    """Silver Blades' 117 DOS flag bytes as 15 bytes of mask, LSB first.

    The inverse of :attr:`AmigaCharacter.spellbook`'s unpacking, and the same
    bit order `/Secret`'s own record unpacker at `0x28260` uses: it sets bit
    `i mod 8` of `record[0x71 + i / 8]` through a mask table reading
    `01 02 04 08 10 20 40 80`.
    """
    book = deltas.dos_field("spellbook")
    mask = bytearray(deltas.spellbook_bytes or 0)
    for i in range(book.size):
        if record[book.offset + i]:
            mask[i // 8] |= 1 << (i % 8)
    return bytes(mask)


def from_dos_record_later(record: bytes, deltas: AmigaDeltas) -> bytes:
    """This title's DOS record re-cut as its Amiga one.

    The exact inverse of :meth:`AmigaCharacter.get` for every byte either
    port sources; :data:`LATER_WRITE_UNSOURCED` says what happens to the
    six (Curse) or three (Silver Blades) the Amiga has and DOS does not.

    **The chain fields are left as `goldbox.dos.write` wrote them, which is
    zero**, and :meth:`AmigaCharacter.block_bytes` sets them to match what
    actually follows.  Writing them here would be writing a value the loader
    tests without knowing what it will be tested against.
    """
    if len(record) != deltas.dos.record_size:
        raise AmigaRecordError(
            f"a DOS {deltas.title} record is {deltas.dos.record_size} bytes, "
            f"got {len(record)}")
    out = bytearray(deltas.record_size)
    out[:AMIGA_NAME_SIZE] = _later_name_bytes(record, deltas)
    for f in dos_layout.layout_for(deltas.dos):
        if f.name in ("name_length", "name_text"):
            continue
        if deltas.spellbook_bytes is not None and f.name == "spellbook":
            book = _later_spellbook_bytes(record, deltas)
            out[AMIGA_SSB_SPELLBOOK_AT:
                AMIGA_SSB_SPELLBOOK_AT + len(book)] = book
            continue
        at = deltas.offset(f.offset)
        chunk = record[f.offset:f.offset + f.size]
        if f.kind in (Kind.U16LE, Kind.UINT_LE):
            chunk = chunk[::-1]
        out[at:at + f.size] = chunk
    return bytes(out)


def amiga_later_item_from_dos(item: bytes, deltas: AmigaDeltas) -> bytes:
    """One DOS item node of this title as the Amiga's 66 or 70 bytes.

    The display text is left NUL and the `next` pointer NULL; the caller
    relinks the chain through :meth:`AmigaCharacter.block_bytes`, which is
    what the loader's `tst.l` reads.

    **Silver Blades' last four bytes go through the same shift map as the
    rest.**  They are DOS's `ITEM_TAIL` at `0x03F`, zero in 48 of 48 records
    driven out of the DOS game, and they land on the Amiga's
    :data:`AMIGA_SSB_SCROLL_CHAIN` -- which is a chain head the vault writer
    at `/Secret` `0x3D6D2` follows, so NULL is not merely the value that was
    there but the only value that can be right while no further nodes are
    written.  A Silver Blades scroll carrying more than three spell ids is
    the case that would need them, and DOS's own 67-byte item has room for
    exactly three, so nothing crosses this way that the DOS record could
    hold (#254).
    """
    if deltas.item_size is None:
        raise AmigaRecordError(
            f"no Amiga {deltas.title} item node has been measured")
    if len(item) != deltas.dos.item_size:
        raise AmigaRecordError(
            f"a DOS {deltas.title} item is {deltas.dos.item_size} bytes, got "
            f"{len(item)}")
    out = bytearray(deltas.item_size)
    for f in dos_layout.ITEM_LAYOUT:
        if f.name in ("text_length", "text", "next"):
            continue
        at = deltas.item_offset(f.offset)
        chunk = item[f.offset:f.offset + f.size]
        if f.kind in (Kind.U16LE, Kind.UINT_LE):
            chunk = chunk[::-1]
        out[at:at + f.size] = chunk
    for n in range(dos_layout.ITEM_SIZE, deltas.dos.item_size):
        out[deltas.item_offset(n)] = item[n]
    return bytes(out)


#: Why the effect chain is built here rather than taken from
#: `goldbox.dos.write`'s `.SPC` payload, and it is a measurement rather than
#: a preference.
#:
#: `to_neutral_later` cannot tell an innate effect from an item's grant in
#: these two titles (:data:`LATER_EFFECT_SPLIT_UNKNOWN`), so it puts every
#: node at duration zero into `granted_effects`.  `goldbox.dos.write` then
#: adds the racial ids **again**, from its own table, and writes both: run
#: over the 21 specimens, the three Curse dwarves and gnomes come back with
#: 7, 7 and 8 effect records where the game wrote 3, 3 and 4, and Silver
#: Blades' MALACHITE with 5 where the game wrote 3.  The other 17 are
#: unchanged.  Writing that into an Amiga block would put a dwarf's
#: infravision in the chain twice.
#:
#: So the chain here is the neutral record's own effect records and nothing
#: else: `granted_effects` whole, then `innate_effects` as DOS's own
#: `id + INNATE_PAYLOAD` for any id the grants do not already carry.  An
#: Amiga source reproduces exactly, a C64 source brings the ten trait slots
#: `goldbox.c64_codec` reads into `innate_effects`, and a DOS source brings
#: both halves of its own `.SPC` file.  **Nothing is derived from a race
#: table**, which is `#293`'s shape: `goldbox.dos.RACE_COMBAT_EFFECTS` is
#: Pool of Radiance's, and Curse's own BJORN DARKSTONE, HOLLAND and SUNDRA
#: contradict it -- 3 of 3 carry the ids that table names bar one it adds.
LATER_EFFECTS_FROM_NEUTRAL = (
    "The effects in the character's own record are written as they are; "
    "none is derived from the character's race")


def _later_effect_nodes(char: NeutralCharacter) -> list[bytes]:
    """The Amiga effect chain for this character, one 10-byte node each.

    :data:`LATER_EFFECTS_FROM_NEUTRAL` says why this reads the neutral
    record instead of `goldbox.dos.write`'s `.SPC` payload.

    **The id check below is a guard against an invariant held elsewhere, and
    it has never fired.**  Every reader in the tree fills these two lists as
    disjoint sets: `c64_codec.read_c64` puts every trait-slot id in
    `innate_effects` and sets `granted_effects` never;
    `goldbox.dos.to_neutral` partitions on `INNATE_EFFECTS` by construction;
    `to_neutral_later` puts everything in `granted_effects`.  So no id has
    ever been in both, and the `continue` has never dropped a node.  It is
    here because a reader that stopped holding that invariant would otherwise
    write the same effect twice -- which is the bug
    :data:`LATER_EFFECTS_FROM_NEUTRAL` records, arriving from the other
    side.  **A node it skipped would vanish silently**, with nothing in
    `report.dropped`, so if a future reader can overlap the two lists this
    needs a report rather than a `continue` (found by the review of
    `39ceb7a`, 2026-09-07).
    """
    from . import dos_codec as _dos

    nodes: list[bytes] = []
    seen: set[int] = set()
    for g in char.get("granted_effects", ()) or ():
        record = bytes(g)[:5].ljust(5, b"\0") + bytes(4)
        seen.add(record[0])
        nodes.append(amiga_por_effect_from_dos(record))
    for e in char.get("innate_effects", ()) or ():
        if int(e) in seen:
            continue
        seen.add(int(e))
        nodes.append(amiga_por_effect_from_dos(
            bytes((int(e),)) + _dos.INNATE_PAYLOAD + bytes(4)))
    return nodes


def write_later(char: NeutralCharacter,
                deltas: "AmigaDeltas | str | None" = None,
                icon: "DosIcon | None" = None
                ) -> tuple[AmigaCharacter, LaterWriteReport]:
    """Build an Amiga Curse or Silver Blades character block.

    Returns `(character, report)`.  The `AmigaCharacter` is what
    `tools/amigasavegame.py`'s `rebuild` takes, and
    :meth:`AmigaCharacter.block_bytes` is the bytes the loader reads -- with
    `item_count` and the two chain heads set to match what actually follows,
    which is the thing `write_por` must *not* do and this must.

    `goldbox.dos.write` does the conversion, so every drop, every warning
    and every provenance line comes from the DOS side and the lines added
    here are the pads, the re-encoded spellbook and the effect chain.

    `icon` is this character's own combat figure -- `icon_head`, `icon_body`
    and the six `icon_colours` bytes -- passed straight through to
    `goldbox.dos.write`'s own `icon` argument, which is where it is actually
    written: the neutral vocabulary has nowhere to put a combat figure, so
    `LATER_TRANSFORMED`'s entries for these three names describe this
    bypass rather than anything this function's own body does with `char`.
    Build one with `editor.convert.amiga_combat_icon`, which reads the
    numbers straight off a source record that already stores DOS's own
    ones -- an `AmigaCharacter` of either later title, or a `DosCharacter`
    for Pool of Radiance -- or with `goldbox.iconparts.IconParts.
    dos_icon_from_c64` for a C64 source (#396, #319,
    docs/199-amiga-combat-icons.md).  With none given, `icon_head` and
    `icon_body` are written zero and `icon_colours` the game's own
    freshly-made default, exactly as before this parameter existed.
    """
    from . import dos_codec as _dos

    deltas = later_write_shape(char, deltas)
    # `recompute_thief_skills=False`: the DOS record here is a stepping
    # stone to an Amiga one, and the two thief-skill recomputes in
    # `goldbox.dos.write` rest on DOS's and the C64's own routines (#431,
    # #440). Nobody has read Amiga Curse's, so this record keeps the source's
    # bytes rather than carrying another port's answer into an Amiga save.
    # `into="Amiga"` (#389, A conversion to the Amiga tells the player what
    # DOS does with their character): otherwise a drop line this function
    # cannot place names DOS to a player who is not converting to DOS.
    # `neutral_menu`, not the Amiga's own table: a conversion crosses the
    # sheet portrait as a menu position and every port resolves it against
    # the same table (#480, `write_por` above). Neither of these two titles
    # draws a sheet portrait on any port (#300), so this answers `None` for
    # both and nothing is looked up -- it is here so the two writers cannot
    # drift apart the day one of them turns out to need it.
    record, itm, spc, dosrep = _dos.write(
        char, deltas=deltas.dos, icon=icon,
        recompute_thief_skills=False, into="Amiga",
        portraits=neutral_menu(deltas.dos.key))
    out = from_dos_record_later(record, deltas)

    stride = deltas.dos.item_size
    items = [AmigaItem.from_bytes(
        amiga_later_item_from_dos(itm[n * stride:(n + 1) * stride], deltas),
        deltas) for n in range(len(itm) // stride)]
    effects = _later_effect_nodes(char)
    built = AmigaCharacter.from_bytes(out, deltas, char.source or "converted",
                                      items, effects)
    # Read the patched block back, so the object this returns holds the same
    # `item_count` and chain heads its own `block_bytes` writes.  Without
    # this the record says nought items while the block behind it holds
    # sixteen, and a caller reading `built.item_chain` is told NULL when a
    # node follows -- the one value the loader actually tests.
    block = built.block_bytes()
    built, end = _amiga_block(block, 0, deltas)
    if end != len(block):
        raise AmigaRecordError(
            f"the {deltas.title} block written for {char.get('name', '?')} is "
            f"{len(block)} bytes and reading it back accounts for {end}")
    built = replace(built, source=char.source or "converted")

    rep = LaterWriteReport()
    rep.dropped = list(dosrep.dropped)
    rep.warnings = list(dosrep.warnings)
    rep.warnings.append(
        f"Written as a {deltas.record_size}-byte Amiga {deltas.title} record "
        f"by re-cutting the {deltas.dos.record_size}-byte DOS one built by "
        f"goldbox.dos.write; the provenance lines name the DOS field each "
        f"byte was transposed from, which is the field table both ports "
        f"share")
    rep.warnings.append(LATER_EFFECTS_FROM_NEUTRAL)
    rep.total = len(block)

    def converted(name: str) -> str:
        f = deltas.dos_field(name)
        return dosrep.sources.get(f.offset, f"{name}: no DOS provenance")

    rep.note(0, AMIGA_NAME_SIZE,
             f"name: {AMIGA_NAME_SIZE} NUL-padded bytes composed from DOS's "
             f"count byte and its text -- {converted('name_length')}")
    for at, size, why in LATER_WRITE_UNSOURCED[deltas.key]:
        rep.note(at, size, f"{at:#05x}: {why}")
    for f in dos_layout.layout_for(deltas.dos):
        if f.name in ("name_length", "name_text"):
            continue
        if deltas.spellbook_bytes is not None and f.name == "spellbook":
            rep.note(AMIGA_SSB_SPELLBOOK_AT, deltas.spellbook_bytes,
                     f"spellbook: {deltas.spellbook_bytes} bytes of bitmask, "
                     f"least significant bit first -- {converted('spellbook')}")
            continue
        rep.note(deltas.offset(f.offset), f.size, converted(f.name))
    for name in ("item_count", "item_chain", "effect_chain"):
        f = deltas.dos_field(name)
        rep.note(deltas.offset(f.offset), 1 if name == "item_count" else 4,
                 f"{name}: what the loader reads -- the count of nodes "
                 f"written, and a chain head that is non-zero exactly when a "
                 f"node follows")

    base = deltas.record_size
    for n in range(len(items)):
        at = base + n * deltas.item_size
        dos_base = deltas.dos.record_size + n * stride
        rep.note(at, deltas.item_text,
                 f"item {n}: the rendered-line cache, left NUL -- the game "
                 f"rewrites it whenever it draws the list")
        rep.note(at + AMIGA_LATER_ITEM_NEXT, 4,
                 f"item {n}: next pointer, non-zero exactly when another "
                 f"node follows -- the loader's own tst.l")
        for f in dos_layout.ITEM_LAYOUT:
            if f.name in ("text_length", "text", "next"):
                continue
            rep.note(at + deltas.item_offset(f.offset), f.size,
                     dosrep.sources.get(dos_base + f.offset,
                                        f"item {n}: {f.name}"))
        for pad in AMIGA_LATER_ITEM_PADS:
            rep.note(at + pad, 1,
                     f"item {n}: the insertion at {pad:#05x}, zero because "
                     f"the game's own item constructor clears the node and "
                     f"never writes here")
        for i in range(dos_layout.ITEM_SIZE, stride):
            rep.note(at + deltas.item_offset(i), 1,
                     f"item {n}: Silver Blades' scroll chain at "
                     f"{AMIGA_SSB_SCROLL_CHAIN:#05x}, NULL because no "
                     f"further spell node follows (#254)")

    base += len(items) * (deltas.item_size or 0)
    for n in range(len(effects)):
        at = base + n * deltas.effect_size
        rep.note(at, 1, f"effect {n}: the id, from the neutral record")
        # A pad on both titles (#387, docs/202-the-amiga-effect-node-pad.md):
        # zero in 24 of 24 Curse nodes, and on Silver Blades the byte no
        # instruction in either binary ever reads, so the three shipped
        # nodes that hold `0x2E`, `0x6D` or `0x64` are stale memory rather
        # than something this writer fails to reproduce.
        if deltas is SILVER_BLADES_DELTAS:
            rep.note(at + AMIGA_POR_EFFECT_PAD, 1,
                     f"effect {n}: "
                     f"{LATER_EFFECT_WRITE_UNSOURCED[0][2]}")
        else:
            rep.note(at + AMIGA_POR_EFFECT_PAD, 1,
                     f"effect {n}: the extra byte, a pad. Zero in every Pool "
                     f"of Radiance and Curse record read (68)")
        rep.note(at + 2, 2, f"effect {n}: duration, byte-swapped")
        rep.note(at + 4, 2, f"effect {n}: the value the effect carries and "
                            f"the flag the engine reads when the item comes "
                            f"off")
        rep.note(at + AMIGA_LATER_EFFECT_NEXT, 4,
                 f"effect {n}: next pointer, non-zero exactly when another "
                 f"node follows -- the loader's own tst.l")
    return built, rep
