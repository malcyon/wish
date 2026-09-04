"""The icon editor's own model: an icon is a WEAPON and a HEAD, not 18 cells.

`goldbox/icons.py` reads the 36 bytes an icon *is*. This reads the much smaller set
of icons the game can actually *make*, which is a different question and the one
an editor has to answer. Offering 253 screen codes in each of 18 cells offers
about 10^43 icons, essentially all of them nonsense; the game's own ICON menu
offers two lists.

**Where this comes from.** `SPELLN64` (disk 3, loads at `$AF00`, entry `$AF24`)
is the icon editor, reached by ENCAMP > ALTER > ICON and during character
creation. Its data file is `SPELLE64` at `$A700`. The menus are plain text in
the overlay: `ICON: PARTS COLOR SIZE EXIT`, then `PARTS: WEAPON HEAD EXIT`.

Four option tables, chosen in pairs by size:

| size | weapons | heads |
|---|---|---|
| small (`0x099` bit 0 clear) | 28 at `$A9E0` | 14 at `$AAD0` |
| large (bit 0 set)           | 35 at `$A800` | 23 at `$A8F0` |

Both counts and pointers are read from the overlay rather than hardcoded here --
`$B0DA` holds `1C 0E 23 17` and `$B0DE` the four addresses -- so a different
build would be read correctly rather than silently mis-parsed.

**The game offers exactly two sizes**, LARGE and SMALL, which is what its own
ALTER > ICON > SIZE menu shows. `GEN $0958` sets `0x099` from a race table --
dwarf, gnome and halfling 0; elf, half-elf and human 1 -- and the `$A9E0` set,
the one the 0 races get, is the one that draws a smaller head lower down. So 0
is small and 1 is large, which is also what the game shows for a dwarf.

**Size is never written back.** No `STA $6B99` exists in `SPELLN64`: choosing
SIZE only switches which lists this session offers. So an icon may legally mix a
large body with a small head, and one on our disks does -- HOGARTH's. That is
why `legal_shapes` explores both pairs together rather than one at a time.

Reconstruction is the evidence: 17 of the 18 distinct shapes on our disks come
out of a (weapon, head) pair exactly, and the 18th is HOGARTH's mixed-size one.

**`SPELLE64` is byte-identical in Pool of Radiance, Curse of the Azure Bonds
and Secret of the Silver Blades**, and so are the four counts; what moves is
where it loads. The later two put it at `$8E00`, `$1900` below Pool of
Radiance's `$A700`, so their pointers read `$8F00`/`$8FF0`/`$90E0`/`$91D0`.
That is why the base is *fitted from the pointers* rather than named here: the
class table is the file's first page and the first option table follows it, so
`base = lowest pointer - 0x100`. Every one of the eight shipped icons in Curse
and in Silver Blades then reconstructs from a (weapon, head) pair, where the
hardcoded `$A700` raised `IndexError` on both.
"""

from __future__ import annotations

from dataclasses import dataclass

from .d64 import D64, load_payload

PARTS_FILE = b"SPELLE64"
EDITOR_FILE = b"SPELLN64"
PARTS_BASE = 0xA700             # where SPELLE64 loads in Pool of Radiance
EDITOR_BASE = 0xAF00            # where SPELLN64 loads in Pool of Radiance

COUNTS = 0xB0DA                 # four bytes, indexed by size*2 + (0 weapon, 1 head)
POINTERS = 0xB0DE               # four little-endian addresses, same order
FILLERS = 0xABC0                # 81 zero-terminated strings

#: `SPELLE64`'s own shape, as **file** offsets, which is what transfers. The
#: class byte per glyph fills the first page; the four option tables follow at
#: `$F0` apart; the filler strings follow those. All three hold in every title
#: that ships the file, because the file is the same bytes in each.
CLASSES_SIZE = 0x100            # PARTS_BASE + this is the first option table
FILLERS_OFFSET = FILLERS - PARTS_BASE

#: Where the counts and the four pointers sit **in `SPELLN64`**, rather than in
#: the address space it is relocated into. Pool of Radiance, Curse and Silver
#: Blades all carry `1C 0E 23 17` here, though the three overlays differ in
#: length and in 285 of the bytes around it.
COUNTS_OFFSET = COUNTS - EDITOR_BASE
POINTERS_OFFSET = POINTERS - EDITOR_BASE

#: One option table: six 40-entry arrays, pose 1 then pose 2 of each.
TABLE_STRIDE = 0x28
PRIMARY = 0x00                  # the glyph this option is built around
START_CELL = 0x50               # where that glyph goes, 0-8 within the pose
FILLER_INDEX = 0xA0             # which filler string draws the rest

SPACE = 0x20
NOT_A_PART = 0x0F
CAP, HAIR = 2, 3                # the two classes with the overwrite rule
HEAD_CELLS = (0, 1, 9, 10)      # what a head owns and a weapon change preserves
ALWAYS_HEAD_CELLS = (1, 10)     # the head's own; 0 and 9 are shared with the weapon
CELLS_PER_POSE = 9

PART_CLASSES = ("weapon", "body", "cap", "hair", "shield", "arm", "leg")

#: Bit 3 of a colour byte tells the VIC-II to draw that cell in multicolour.
#: `colours_for` sets it from the glyph's own class byte; the cells holding no
#: part carry whatever the table was seeded with, which is where
#: :data:`DEFAULT_BACKGROUND` comes in.
MULTICOLOUR = 0x08

# -- what a character the engine rolled itself carries -----------------------
#
# The icon table at `$4BE0` is seeded before any character exists, so creation
# inherits this rather than computing it: the game's own character creation
# wrote the same 36 bytes for **8 of 8 newly created characters**, across four
# classes and five races, and independently of the size bit -- a dwarf, a
# halfling and a gnome all got the *large* figure (#57).  So this is a value
# with evidence, which is what `.claude/rules/conversions.md` distinguishes
# from one inherited from somebody else's save.
#
# It is stored as the choices rather than as the bytes.  `(large, weapon 0,
# head 1)` is a pair of menu positions the way `portrait_head = 3` is a
# number; the 36 bytes it turns into are the game's own art and do not belong
# in this repository.  :meth:`IconParts.default_icon` reads them off the
# player's disk at the moment they are needed.
#
# Confirmed against the player's own saves: slots 6 and 7 -- the NPC-only
# slots nobody has ever edited -- carry exactly these 36 bytes on **28 of 28**
# (14 save disks x 2 slots), and no slot 0-5 on any of them does.
DEFAULT_SIZE = "large"
DEFAULT_WEAPON = 0
DEFAULT_HEAD = 1
#: One colour per part, read back out of the measured bytes by
#: :meth:`part_colours`.  Weapon 0 is empty hands and head 1 wears nothing, so
#: the weapon, cap and shield classes own no cell in this figure and no colour
#: of theirs was measured.  Keyed by class index, off `PART_CLASSES` rather
#: than written as numbers, so reordering that tuple cannot silently repaint
#: the figure.
DEFAULT_PART_COLOURS = {PART_CLASSES.index(part): colour for part, colour in
                        (("body", 6), ("hair", 7), ("arm", 6), ("leg", 6))}
#: The colour behind the four cells this figure leaves as spaces.  It is not
#: zero: the seeded table holds `$0E` there, which is this 6 with
#: :data:`MULTICOLOUR` set.  A space draws nothing, so it is invisible either
#: way -- but writing it is what makes the composed icon the engine's bytes
#: rather than merely one that looks like them.
DEFAULT_BACKGROUND = 6


@dataclass(frozen=True)
class Option:
    """One entry in one of the four lists -- a whole weapon or a whole head."""

    index: int
    kind: str                   # "weapon" or "head"
    size: str                   # "small" or "large"

    @property
    def label(self) -> str:
        return f"{self.size} {self.kind} {self.index}"


class IconParts:
    """The four option tables and the drawing rules that use them."""

    def __init__(self, parts: bytes, editor: bytes):
        self._parts = parts
        self._editor = editor
        counts = self._at(editor, COUNTS_OFFSET, 4)
        addrs = self._at(editor, POINTERS_OFFSET, 8)
        self.tables: dict[tuple[str, str], tuple[int, int]] = {}
        # Order in both tables is small-weapon, small-head, large-weapon,
        # large-head -- `$A9E0` first, and `$A9E0` is the set with the smaller
        # head, which record `0x099` = 0 selects.
        for i, (size, kind) in enumerate((("small", "weapon"), ("small", "head"),
                                          ("large", "weapon"), ("large", "head"))):
            self.tables[(size, kind)] = (addrs[i * 2] | (addrs[i * 2 + 1] << 8),
                                         counts[i])
        #: Where `SPELLE64` loads in *this* title, fitted from the pointers the
        #: editor overlay carries. Never assumed: a wrong base makes every
        #: table offset negative, and a negative index reads the file's tail
        #: rather than raising, so the drawing comes out as plausible rubbish.
        self.base = min(a for a, _ in self.tables.values()) - CLASSES_SIZE
        # The fit has to be checked, not merely made. It is a rule now rather
        # than a constant, so it runs against a title nobody has looked at and
        # against a `SPELLE64`/`SPELLN64` pair that do not belong together --
        # and a base that is wrong but *in range* is the failure this project
        # has shipped before: every index lands somewhere and the drawing is
        # plausible rubbish. `_at` guards the editor blob's own offsets;
        # `_apply` indexes `self._parts` directly, so the guard belongs here.
        if self.base < 0 or self.base % 0x100:
            raise ValueError(
                f"the icon parts fit to ${self.base:04X}, which is not a page "
                f"boundary; this is not a SPELLE64/SPELLN64 pair")
        for (size, kind), (addr, count) in self.tables.items():
            end = addr - self.base + count * 2
            if addr < self.base or end > len(parts):
                raise ValueError(
                    f"the {size} {kind} table runs to ${end:04X}, past the "
                    f"{len(parts)} bytes of this file")
        self.classes = parts[0:CLASSES_SIZE]
        self.fillers = self._read_fillers()

    # -- construction ----------------------------------------------------

    @classmethod
    def load(cls, disk: D64 | str) -> "IconParts":
        """Read both files off the character-creation disk (POOL3)."""
        return cls(load_payload(disk, PARTS_FILE),
                   load_payload(disk, EDITOR_FILE))

    @staticmethod
    def _at(blob: bytes, start: int, length: int) -> bytes:
        if start < 0 or start + length > len(blob):
            raise ValueError(f"offset ${start:04X} is outside this file")
        return blob[start:start + length]

    def _read_fillers(self) -> list[bytes]:
        out, current = [], bytearray()
        for byte in self._parts[FILLERS_OFFSET:]:
            if byte:
                current.append(byte)
            else:
                out.append(bytes(current))
                current.clear()
        return out

    # -- the tables ------------------------------------------------------

    def count(self, size: str, kind: str) -> int:
        return self.tables[(size, kind)][1]

    def options(self, size: str, kind: str) -> list[Option]:
        return [Option(i, kind, size) for i in range(self.count(size, kind))]

    def part_class(self, glyph: int) -> int:
        """0 weapon, 1 body, 2 cap, 3 hair, 4 shield, 5 arm, 6 leg; $0F none."""
        return self.classes[glyph] & 0x7F

    def multicolour(self, glyph: int) -> bool:
        """Bit 7 of the class byte: add 8 to whatever colour the part carries."""
        return bool(self.classes[glyph] & 0x80)

    # -- drawing ---------------------------------------------------------

    def _put(self, shape: bytearray, glyph: int, cell: int) -> None:
        """Write one glyph, honouring the overwrite rule at `$B209`.

        A cap or hair glyph will not paint over a head cell that already holds
        something which is neither a space nor another cap or hair. That is what
        stops a head from erasing the weapon's shoulders.
        """
        if self.part_class(glyph) in (CAP, HAIR) and cell in HEAD_CELLS:
            under = shape[cell]
            if under != SPACE and self.part_class(under) not in (CAP, HAIR):
                return
        shape[cell] = glyph

    def _apply(self, shape: bytearray, size: str, kind: str, option: int) -> None:
        """Draw one option into both poses: primary glyph, then its filler."""
        base, count = self.tables[(size, kind)]
        if not 0 <= option < count:
            raise ValueError(f"{size} {kind} {option} is not one of {count}")
        start = base - self.base
        for pose in range(2):
            first = pose * CELLS_PER_POSE
            off = start + pose * TABLE_STRIDE
            glyph = self._parts[off + PRIMARY + option]
            cell = self._parts[off + START_CELL + option] + first
            filler = self._parts[off + FILLER_INDEX + option]
            self._put(shape, glyph, cell)
            at = first
            for extra in self.fillers[filler] if filler else b"":
                if at == cell:          # the primary already has this cell
                    at += 1
                self._put(shape, extra, at)
                at += 1

    def apply(self, shape: bytes, size: str, kind: str, option: int) -> bytes:
        """`shape` with one part changed, exactly as the ICON menu would.

        Changing the weapon preserves the head: `$B26F`/`$B29B` save cells 0, 1,
        9 and 10 before drawing and restore them into whatever the new weapon
        left as space. Without that the two menu items would not be independent,
        and the reachable set would be much smaller than it is.
        """
        out = bytearray(shape)
        if kind == "weapon":
            # Cells 1 and 10 are the head's own and always come back; 0 and 9
            # are shared with the weapon and only survive if they hold hair.
            kept = [(cell, out[cell] if (cell in ALWAYS_HEAD_CELLS
                                         or self.part_class(out[cell]) == HAIR)
                     else SPACE)
                    for cell in HEAD_CELLS]
            self._apply(out, size, kind, option)
            for cell, glyph in kept:
                if self.part_class(glyph) in (CAP, HAIR) and out[cell] == SPACE:
                    out[cell] = glyph
        else:
            self._apply(out, size, kind, option)
        return bytes(out)

    def compose(self, size: str, weapon: int, head: int) -> bytes:
        """A whole icon shape from scratch: weapon first, then head."""
        shape = bytes([SPACE] * (CELLS_PER_POSE * 2))
        shape = self.apply(shape, size, "weapon", weapon)
        return self.apply(shape, size, "head", head)

    def default_icon(self) -> bytes:
        """The 36 bytes the game gives a character it has just rolled (#57).

        Eighteen screen codes and eighteen colours, composed out of this
        disk's own option tables rather than stored -- see
        :data:`DEFAULT_SIZE` for what was measured and on what sample.

        This is what a conversion from a port with no C64 icon writes.  Zero
        is refused: screen code 0 in `CHARPIC00` is a real glyph, so a zeroed
        icon draws as a 3x3 block of black hooks on the combat floor (#57,
        seen in a fight).
        """
        shape = self.compose(DEFAULT_SIZE, DEFAULT_WEAPON, DEFAULT_HEAD)
        seed = bytes([DEFAULT_BACKGROUND | MULTICOLOUR] * len(shape))
        return shape + self.colours_for(shape, DEFAULT_PART_COLOURS, seed)

    # -- the legal set ---------------------------------------------------

    def legal_shapes(self, sizes: tuple[str, ...] = ("small", "large")) -> set[bytes]:
        """Every shape reachable by any sequence of menu choices.

        Not the product of the two lists. A weapon preserves the head cells, so
        the order of edits matters and mixing the two size pairs reaches shapes
        neither pair reaches alone -- 15328 against the 805 + 392 a naive
        "one weapon times one head" count would predict.
        """
        seed = bytes([SPACE] * (CELLS_PER_POSE * 2))
        seen = {seed}
        frontier = [seed]
        while frontier:
            nxt = []
            for shape in frontier:
                for size in sizes:
                    for kind in ("weapon", "head"):
                        for option in range(self.count(size, kind)):
                            made = self.apply(shape, size, kind, option)
                            if made not in seen:
                                seen.add(made)
                                nxt.append(made)
            frontier = nxt
        seen.discard(seed)
        return seen

    # -- colour ----------------------------------------------------------

    def part_colours(self, icon_colours: bytes, shape: bytes) -> dict[int, int]:
        """The seven COLOR-menu values implied by an icon, keyed by part class.

        The menu offers one colour per part -- WEAPON BODY CAP HAIR SHIELD ARM
        LEG -- and every cell of a class carries it, so reading any one cell of
        a class back gives the value the menu was left on. Cells disagreeing
        (only hand-authored icons do) are resolved by majority.
        """
        votes: dict[int, dict[int, int]] = {}
        for cell, glyph in enumerate(shape):
            klass = self.part_class(glyph)
            if klass >= len(PART_CLASSES):
                continue
            value = icon_colours[cell] & 0x07
            votes.setdefault(klass, {}).setdefault(value, 0)
            votes[klass][value] += 1
        return {k: max(v, key=v.get) for k, v in votes.items()}

    def colours_for(self, shape: bytes, per_class: dict[int, int],
                    existing: bytes = b"") -> bytes:
        """The 18 colour bytes a shape must carry, given a colour per part.

        `colour[cell] = C[class(glyph)] | (8 if the glyph's class byte has bit
        7)` -- `$B2F0`/`$B400`. So the colour half is not free either: every
        cell of one part shares a colour, and bit 3 belongs to the glyph, not
        to the player.

        **Cells holding no part are left alone.** A space has class `$0F`, the
        rule says nothing about it, and the byte there is whatever it last was.
        Computing one anyway is what made this disagree with all eight icons in
        a save: it invented colour 1 for background cells carrying 14.
        """
        out = bytearray(existing[:len(shape)] or bytes(len(shape)))
        for cell, glyph in enumerate(shape):
            klass = self.part_class(glyph)
            if klass >= len(PART_CLASSES):
                continue
            base = per_class.get(klass, 0) & 0x07
            out[cell] = base | (MULTICOLOUR if self.multicolour(glyph) else 0)
        return bytes(out)
