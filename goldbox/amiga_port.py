"""The Amiga port of the Gold Box character record, as deltas from DOS's.

`#470 (Give the project a neutral title beside its neutral character record,
with one port per platform a title shipped on)`'s stage 4b moved this out of
`goldbox/amiga.py`, which was the Amiga *codec* -- the code that reads and
writes the bytes -- and left it re-exporting every name here under both its
old spelling and its new one; that codec has since been renamed and split
into `amiga_por.py`, `amiga_later.py`, `amiga_pod.py` and `amiga_shared.py`.
The four roles this project names, and the
convention that the platform is the prefix and the role is the noun:

* the **title** -- the rules a Gold Box game plays by, on any machine
  (`goldbox/titles.py`);
* the **deltas** -- the ways one title's character record departs from Pool
  of Radiance's.  :class:`AmigaDeltas` is the Amiga's, `DosDeltas` the DOS
  one (`goldbox/dos_port.py`);
* the **container** -- a save file (`goldbox/dos_savegame.py`'s
  `DosContainer`);
* the **machine** -- a live, running game's addresses (`automap/amiga.py`'s
  `AmigaMachine`).

`AmigaShape` was the class's name before that stage, and `goldbox/amiga_later.py`
still answers to it and to `CURSE_SHAPE`, `SILVER_BLADES_SHAPE`,
`AMIGA_SHAPES` and `AMIGA_SHAPES_BY_SIZE`.

**Nothing here imports `amiga_por`, `amiga_later`, `amiga_pod` or
`amiga_shared`.**  The dependency runs one way --
codec on port, never back -- so that a reader wanting to know what an Amiga
record looks like never has to load the 6,000 lines that read one.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import dos_port


class AmigaRecordError(ValueError):
    """A buffer that is not an Amiga Gold Box character record."""


# ---------------------------------------------------------------------------
# The Amiga Pool of Radiance effect file: 10 bytes where DOS spends 9
# ---------------------------------------------------------------------------
#: One `.spc` node.  `#55` located the extra byte at offset 1, on 62 records;
#: the party shipped on Amiga disk 1 agrees on 6 more, and its payload bytes
#: 2-5 read `00 00 FF 00` -- `goldbox/dos_codec.py`'s `INNATE_PAYLOAD` exactly, which is
#: DOS's bytes 1-4.  So the pad is at 1 and everything after it is DOS's four
#: payload bytes and four pointer bytes in order.
AMIGA_POR_EFFECT_SIZE = 10
AMIGA_POR_EFFECT_PAD = 1


# ---------------------------------------------------------------------------
# Amiga Curse of the Azure Bonds and Secret of the Silver Blades (#55)
# ---------------------------------------------------------------------------
#
# Two more ports of the same record, and neither is a second field table:
# each reads `goldbox/dos_port.py`'s own field table for its title through a
# shift map, big-endian, exactly as `goldbox/amiga_por.py`'s Amiga Pool of
# Radiance reader does.
# `AmigaDeltas` is that map as data, so a third title is a row rather than a
# module.
#
# **Silver Blades is where the evidence is strongest, because the two ports
# ship the same six characters.**  `SAVE/savgamA.sav` on Amiga disk 1 carries
# Guy de Valois, PAINE, EPONA, MALACHITE, DOMINIC and MORGAINE, and the DOS
# archives ship `CHRDATA1`-`CHRDATA6` with those same six names.  Read through
# the map below, **every one of the 85 fields in the DOS Silver Blades table
# decodes to the byte-for-byte value its DOS twin holds, in 6 of 6
# characters**, with three groups of exceptions and no others:
#
#   * `effect_chain` and `heap_104`, which are live pointers -- an Amiga heap
#     address against a DOS far pointer.  They cannot agree and must not be
#     converted;
#   * MALACHITE's four saving throws and eight thief percentages, where the
#     two ports' shipped copies of that character genuinely differ.  One
#     specimen of six; the other five agree on both groups.
#
# That is what makes the Silver Blades offsets CONFIRMED rather than
# consistent: a wrong offset anywhere would have shown up as a mismatch in a
# field whose value is not zero, and 6 x 85 comparisons produced twenty
# mismatches, all of them named above.
#
# **Curse has no such twin** -- the eleven `SAVE/*.guy` pregens on Amiga disk 1
# are ARIEL, BJORN DARKSTONE, GALAIN and so on, and the DOS archives ship
# MATHEW, MARK, TRAVIS and so on.  So its map rests on three things instead:
# fields whose value is forced (a dwarf's `size` of 1, a level-5 magic-user's
# `4 2 1` spell slots, 25 000 experience split between a character's classes),
# the arithmetic identity `money + sum(weight x quantity) = encumbrance` on
# 15 of 15 specimens, and **23 constants that hold across all 12 DOS records
# and all 15 Amiga ones and agree byte for byte at the mapped offsets** --
# including `attack_forms`' eight-byte `02 00 01 00 02 00 00 00` and
# `field_10c_10f`' four-byte `00 01 00 00`.
#
# The five rules the shift maps are made of, all three titles:
#
#   1. **The name is 16 NUL-padded bytes** where DOS spends a count byte and
#      fifteen.  Same width, so nothing after it moves.
#   2. **Every `u16` and `u32` is big-endian.**  It is a 68000.
#   3. **A `u16` or `u32` field is even-aligned**, and a pad byte goes in
#      ahead of it when the DOS offset is odd.  That is where every insertion
#      in all three titles comes from, and two of Silver Blades' three are
#      located to the byte because the field either side of them is non-zero.
#   4. **The record is padded to an even length.**  Curse's 422 + 5 = 427 is
#      odd and the record is 428; Silver Blades' 340 is even and there is no
#      trailing byte.  Pool of Radiance's 285 + 2 = 287 pads to 288.
#   5. **Silver Blades, and only Silver Blades, packs the spellbook into
#      bits** -- see `goldbox/amiga_later.py`'s `AMIGA_SSB_SPELLBOOK_BYTES`.
#
#: The name field, all three titles: 16 bytes, NUL-padded, no count byte.
AMIGA_NAME_SIZE = 16


@dataclass(frozen=True)
class AmigaDeltas:
    """One title's Amiga record, as a difference from its DOS record.

    **The deltas: the ways this title's record departs from Pool of
    Radiance's**, which is what the word means throughout this project and
    what `goldbox/dos_port.py`'s `DosDeltas` means by it on the other port.
    Never the record's own form -- that is a layout, and `goldbox/layout.py`
    holds the model for one.

    Everything here is a *map onto* `goldbox/dos_port.py`, never a copy of
    it: `offset` turns a DOS offset into an Amiga one and `AmigaCharacter`
    reads the DOS field table through it, so a correction to the DOS side
    reaches the Amiga side with no second edit.
    """

    key: str
    title: str
    dos: dos_port.DosDeltas
    record_size: int
    #: `(first DOS offset, bytes inserted before it)`, ascending.
    shifts: tuple[tuple[int, int], ...]
    #: DOS offsets whose Amiga counterpart cannot be placed, because an
    #: insertion sits somewhere inside a run that reads zero on both ports.
    unplaced: tuple[range, ...] = ()
    #: Bytes the spellbook takes on the Amiga when it is a bitmask rather
    #: than DOS's one byte per spell.  `None` means the spellbook is laid
    #: out DOS's way.
    spellbook_bytes: int | None = None
    #: One item node.  `None` where no specimen carries an item.
    item_size: int | None = None
    item_shifts: tuple[tuple[int, int], ...] = ()
    item_unplaced: tuple[range, ...] = ()
    #: Bytes of NUL-separated display text before the item's `next` pointer.
    item_text: int = 0x02A
    #: One effect node: DOS's nine plus a pad byte at offset 1.
    effect_size: int = AMIGA_POR_EFFECT_SIZE
    #: The byte past the last field, present only to make the record even.
    trailing_pad: int | None = None

    def offset(self, dos_offset: int) -> int:
        """Where a DOS record offset lands in this title's Amiga record.

        Raises rather than guessing for an offset inside an unplaced window,
        or inside a re-encoded spellbook, so a caller that wants those bytes
        has to say so and read them raw.
        """
        if self.spellbook_bytes is not None:
            book = self.dos_field("spellbook")
            if book.offset <= dos_offset < book.offset + book.size:
                raise AmigaRecordError(
                    f"DOS offset {dos_offset:#05x} is inside the "
                    f"{self.title} spellbook, which the Amiga packs into "
                    f"{self.spellbook_bytes} bytes of bitmask; there is no "
                    f"one-to-one Amiga offset for it")
        for window in self.unplaced:
            if dos_offset in window:
                raise AmigaRecordError(
                    f"DOS offset {dos_offset:#05x} is inside "
                    f"{window.start:#05x}-{window.stop - 1:#05x}, where an "
                    f"insertion has not been located; there is no Amiga "
                    f"offset to give")
        shift = 0
        for first, amount in self.shifts:
            if dos_offset >= first:
                shift = amount
        return dos_offset + shift

    def item_offset(self, dos_offset: int) -> int:
        """Where a DOS item offset lands in this title's Amiga item node."""
        if self.item_size is None:
            raise AmigaRecordError(
                f"no Amiga {self.title} item node has been measured: no "
                f"specimen on this machine carries an item")
        for window in self.item_unplaced:
            if dos_offset in window:
                raise AmigaRecordError(
                    f"DOS item offset {dos_offset:#05x} is inside "
                    f"{window.start:#05x}-{window.stop - 1:#05x}, where the "
                    f"insertion has not been located")
        shift = 0
        for first, amount in self.item_shifts:
            if dos_offset >= first:
                shift = amount
        return dos_offset + shift

    def dos_field(self, name: str):
        """One `goldbox/dos_port.py` field of this title's DOS record."""
        for f in dos_port.layout_for(self.dos):
            if f.name == name:
                return f
        raise AmigaRecordError(
            f"no field called {name!r} in the DOS {self.title} record")


# ---------------------------------------------------------------------------
# The item node of the two later Amiga titles, read from the constructor
# ---------------------------------------------------------------------------
#
# Curse's node is **66 bytes** and Silver Blades' **70**, and the first 66 of
# each are the same layout.  It is not argued from specimens: each executable
# carries a constructor that allocates the node, clears it and then writes
# fifteen named arguments into it, one field at a time -- `/Curse` at file
# offset `0x1C1EA`, `/Secret` at `0x1B862`, instruction for instruction the
# same routine.  The arguments arrive in `goldbox/dos_port.py`'s own item
# order, so the two tables can be laid beside each other:
#
#     type_index -> 0x2E   name1..3 -> 0x30 0x31 0x32   plus -> 0x33
#     plus_save  -> 0x34   readied  -> 0x35   hidden -> 0x36  cursed -> 0x37
#     weight (u16be) -> 0x38   quantity -> 0x3A   value (u16be) -> 0x3C
#     charges -> 0x3F   effect -> 0x40   power -> 0x41
#
# **Nothing is written at `0x2F`, `0x3B` or `0x3E`.**  Those three are the
# insertions, and the constructor's `setmem(node, size, 0)` is why an item the
# game builds itself reads zero in all three.  The nine nodes in
# `SAVE/savgamA.dat` read `0x7F`, 52 and 47 there instead because they came
# through the other path -- the `ITEM<n>` template loader at `/Curse`
# `0x1F2D6`, which unpacks each 63-byte template into a stack struct it never
# clears and copies all 66 bytes into the node.  Uninitialised stack, copied
# nine times.
#
# This **refutes** the reading `#55 (Decode the Amiga Curse and Silver Blades
# records)` carried until 2026-09-05, that `0x3E` was `charges` and 47 was a
# Chain Mail's charge count.  `charges` is at `0x3F` and reads zero, which is
# what a Chain Mail should hold.
#
# Silver Blades adds a **fourth pointer at `0x42`**, `u32` big-endian, which
# the unpacker clears (`/Secret` `0x28194`) and which is non-NULL only on a
# scroll: an item whose `type_index` is `0x49` chains `quantity` further
# 70-byte nodes through it, each carrying three more spell ids in the bytes
# the constructor calls `charges`, `effect` and `power`.  `/Secret` `0xDE`
# walks it, and the vault writer at `0x3D6D2` writes those nodes out after
# the item itself.  Curse has no such field and no room for one.
#
#: `(first DOS item offset, bytes inserted before it)`, ascending -- the same
#: three insertions in both later Amiga titles.
AMIGA_LATER_ITEM_SHIFTS = ((0x000, 0), (0x02F, 1), (0x03A, 2), (0x03C, 3))

#: Silver Blades only: a `u32be` at the end of the 70-byte node, NULL except
#: on a scroll, where it heads a chain of further nodes holding the rest of
#: the scroll's spell ids.
AMIGA_SSB_SCROLL_CHAIN = 0x042

#: Curse of the Azure Bonds: the 422-byte DOS record, 428 bytes on the Amiga.
#:
#: Five insertions, and only two of them are located to the byte.
#:
#: **Every insertion is located to the byte, and none of it rests on a
#: specimen.**  `/Curse` carries a routine at file offset `0x270A6` that
#: expands a packed 422-byte record -- the DOS layout, byte for byte -- into
#: the 428-byte Amiga one, field group by field group, and its 26 copy
#: boundaries all land on a `goldbox/dos_port.py` Curse field boundary.  It
#: opens `setmem(record, 0x1AC, 0)`, which is 428, and the monster loader at
#: `0x26306` calls it after decompressing `MON<n>CHA` to `0x1A6` = 422 bytes.
#: `tools/amigaunpack.py` prints the map; `docs/166-amiga-records-from-the-code.md`
#: has the working.
#:
#:   * the pad is at Amiga **`0x0FB`**, not anywhere in `0x0F9`-`0x0FB`: the
#:     routine copies DOS `0x0F6`-`0x0F8` to `0x0F6`, DOS `0x0F9` and `0x0FA`
#:     one byte each to the same offsets, and then the fourteen money bytes
#:     from DOS `0x0FB` to Amiga `0x0FC`.  So `field_83_87` is at
#:     `0x0F6`-`0x0FA` at shift 0 and is readable;
#:   * **each of the three spell-slot arrays is six bytes on the Amiga where
#:     DOS spends five**, and that is the whole of the three-byte insertion
#:     between `hp_rolled` and `experience_award`.  Three routines index them as
#:     `record[0x12E + 6 * class + (level - 1)]` -- `/Curse` `0x288`, `0x482`
#:     and `0x9F4`, with `class` read from byte 0 of a 16-byte spell-table
#:     entry (0 cleric, 1 druid, 2 magic-user) and `level` from byte 1.  So
#:     the cleric array is `0x12E`-`0x133`, the **druid array `0x134`-`0x139`**
#:     and the magic-user array `0x13A`-`0x13F`, and the sixth byte of each
#:     has no DOS counterpart.  `/Secret`'s Curse-import routine at `0x26F64`
#:     reads the same three bases out of a Curse record, which is a second
#:     binary agreeing;
#:   * DOS's `experience_award`/`experience_per_hit_point` pair is therefore
#:     at Amiga `0x140`-`0x142`, `experience_award` a `u16`: the unpacker
#:     byte-swaps the word at Amiga `0x140` the way it swaps age, the money
#:     block and experience;
#:   * one at Amiga `0x151`, between `item_count` and the item pointer array.
#:     The count is at `0x150` -- forced by `428 + 66 x count + 10 x effects`
#:     matching the block length in 4 of 4 played characters -- and the
#:     pointers are at `0x152`, which is where `/Curse`'s saved-game writer
#:     starts the item chain (`docs/165-amiga-savegame.md`);
#:   * the trailing byte at `0x1AB`, which makes 427 into 428.
#:
#: **`sex` is at Amiga `0x11A` and `alignment` at `0x11C`** -- the two fields
#: reading GALAIN's sheet on screen could not place, because one sheet cannot
#: separate a byte from its neighbours.  The unpacker copies DOS `0x119`,
#: `0x11A` and `0x11B` to those three offsets, one byte at a time.
#:
#: Thirteen of these offsets were also **read off the game's own character
#: sheet** under WinUAE, on GALAIN in `SAVE/savgamA.dat` -- race at `0x074`,
#: age at `0x076`, class at `0x075`, the class levels at `0x10A`, the money
#: block at `0x0FC`, experience at `0x128`, hit points at `0x078` and
#: `0x1A9`, armour class at `0x19F` stored `60 - AC`, THAC0 base at `0x073`,
#: encumbrance at `0x18C` and movement at `0x0E4` and `0x1AA`.
#: `docs/124-amiga-port.md` §1.11 has the sheet beside the record. That is
#: the instrument reading this map's other anchors could not be: a number a
#: person read on a screen, not an arithmetic identity between two files.
CURSE_DELTAS = AmigaDeltas(
    key="curse-of-the-azure-bonds",
    title="Curse of the Azure Bonds",
    dos=dos_port.CURSE_OF_THE_AZURE_BONDS,
    record_size=428,
    shifts=((0x000, 0), (0x0FB, 1), (0x132, 2), (0x137, 3), (0x13C, 4),
            (0x14D, 5)),
    item_size=66,
    item_shifts=AMIGA_LATER_ITEM_SHIFTS,
    trailing_pad=0x1AB,
)

#: Secret of the Silver Blades: the 439-byte DOS record, 340 on the Amiga.
#:
#: The spellbook is the whole of the difference in size, and the three
#: insertions are what is left.  Two are located to the byte:
#:
#:   * Amiga `0x095`, ahead of the `u32` effect chain at `0x096` -- the eight
#:     thief percentages fill `0x08D`-`0x094` on MALACHITE and the chain is
#:     non-zero on four of the six, so the pad has nowhere else to be;
#:   * Amiga `0x0C7`, ahead of the `u32` experience at `0x0C8` -- `0x0C6` is
#:     `unnamed_0ab`, distinct in all six, and `0x0C8` reads 200 000 or
#:     100 000 big-endian, which is what the DOS twin holds;
#:   * Amiga `0x0FD`, between `item_count` at `0x0FC` and the item pointer
#:     array at `0x0FE`.
#:
#: All three are now **CONFIRMED from the code rather than from the six
#: specimens**: `/Secret` expands a packed 439-byte record -- the DOS layout
#: -- into this one at file offset `0x281A2`, opening with
#: `setmem(record, 0x154, 0)`, and its 22 copy boundaries all land on a
#: `goldbox/dos_port.py` Silver Blades field boundary.  It copies DOS
#: `0x0F3`+8 to Amiga `0x08D`, skips DOS's four-byte `effect_chain`, and
#: resumes at Amiga `0x09A`, which puts the pad at `0x095`; it copies DOS
#: `0x121`+11 to `0x0BC` and DOS `0x12C`+13 to `0x0C8`, which puts the pad at
#: `0x0C7`; and it copies DOS `0x14E`+19 to `0x0EA` and DOS `0x161`+69 to
#: `0x0FE`, which puts the pad at `0x0FD`.  The last of those was PROBABLE
#: and is now measured.  `docs/166-amiga-records-from-the-code.md`.
#:
#: **`sex` is at Amiga `0x0BA` and `alignment` at `0x0BB`**, from the two
#: single-byte copies of DOS `0x11F` and `0x120`.
#:
#: The **four spell-slot arrays are seven bytes each and are not widened**,
#: unlike Curse's: `/Secret` `0x5D4` indexes them as
#: `record[0x0CE + 7 * class + (level - 1)]`, and the unpacker copies each of
#: the four as its own seven bytes.
SILVER_BLADES_DELTAS = AmigaDeltas(
    key="secret-of-the-silver-blades",
    title="Secret of the Silver Blades",
    dos=dos_port.SECRET_OF_THE_SILVER_BLADES,
    record_size=340,
    shifts=((0x000, 0), (0x0E6, -102), (0x0FB, -101), (0x12C, -100),
            (0x161, -99)),
    spellbook_bytes=15,
    item_size=70,
    item_shifts=AMIGA_LATER_ITEM_SHIFTS,
)

#: Every Amiga title's deltas, and the size that names each.  The
#: three sizes are distinct, as the DOS four are, so a reader handed a
#: nameless file can say which title it belongs to.
AMIGA_DELTAS = (CURSE_DELTAS, SILVER_BLADES_DELTAS)
AMIGA_DELTAS_BY_SIZE = {s.record_size: s for s in AMIGA_DELTAS}
