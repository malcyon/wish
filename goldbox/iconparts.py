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

import pathlib
from dataclasses import dataclass

import yaml

from .assets import asset_path
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

#: The fourteen cells no head option in either list ever writes -- measured
#: over all 37 head options, not assumed from :data:`HEAD_CELLS`.  A shape's
#: bytes here are the weapon's alone, which is what makes
#: :meth:`IconParts.recognise` able to name the weapon exactly.
WEAPON_ONLY_CELLS = tuple(c for c in range(CELLS_PER_POSE * 2)
                          if c not in HEAD_CELLS)

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

# -- converting a DOS figure -------------------------------------------------
#
# DOS keeps a character's combat figure as a body, a head, a size and six
# colour pairs (`goldbox/dos_port.py` at `0x0BE`, `0x0BD`, `0x0C0`,
# `0x0C1`); the C64 keeps eighteen screen codes and eighteen colours.  Neither
# side stores the other's, and the two sets of art do not correspond index for
# index -- the DOS list is 32 bodies and 14 heads, the C64's 35 large weapons,
# 28 small ones, 23 large heads and 14 small ones, and the highest overlap
# between any pair of *bitmaps* is 0.782 where the same art drawn twice would
# be 0.95 (#130).  So which C64 option each DOS one becomes is a judgement
# about what the figure *shows* -- a bow is a bow, a robed caster is a robed
# caster -- and it is Donald's judgement rather than a measurement.
#
# It lives in `tools/iconproposal.yaml`, one line a row, and is read from
# there at run time rather than copied into this file.  A copy would be a
# second source: Donald edits the YAML by hand, and a table here would either
# go quietly out of step with his edit or fail the build for having been
# edited, both of which have already happened once.

#: Donald's table, the single source.  `tools/iconproposal.py` draws it and
#: `dos_icon_tables` reads it; nothing else may hold a second copy.
#:
#: It stays in `tools/` -- Donald edits it where he has already been shown it
#: -- and reaches a frozen build through `goldbox.assets.asset_path`, the
#: resolver `#351 (The Windows build shows no logo in About and a black
#: square on the taskbar, because the artist's SVGs are not in the package)`
#: added: `sys._MEIPASS` when frozen, this checkout otherwise. `wish.spec`'s
#: `DATAS` carries `tools/iconproposal.yaml` alongside it, which is what
#: `#315 (A frozen Wish cannot convert a combat figure, because the table it
#: needs lives outside the package)` was waiting on.
PROPOSAL_PATH = asset_path("tools", "iconproposal.yaml")

#: Donald's table for the other direction, `tools/iconreverse.yaml` -- which
#: DOS option each C64 one becomes, drafted by `tools/iconreverse.py` and
#: corrected by hand the way `PROPOSAL_PATH` was (#320, "Draft it, you
#: correct it").  Reached the same way and for the same reason: a frozen
#: build has no `tools/` checkout, so `goldbox.assets.asset_path` plus
#: `wish.spec`'s `DATAS` is what `#315`'s resolver was for.
REVERSE_PATH = asset_path("tools", "iconreverse.yaml")

#: Record bytes `0x0C1`-`0x0C6` in order, and which C64 part class each one
#: paints.  `GAME.OVR:0x1E55C` builds its recolour lookup from the table at
#: `ds:0x3CF5` -- `0A 01 02 03 04 06 07` -- so `0x0C1` is the body, `0x0C2`
#: the arm, `0x0C3` the leg, `0x0C4` the hair and face, `0x0C5` the shield and
#: `0x0C6` the weapon (#130, and confirmed in the running game on #112).
DOS_PAIR_CLASSES = ("body", "arm", "leg", "hair", "shield", "weapon")

#: The C64's seventh part, CAP, which DOS has no pair for: every DOS hat and
#: plume is drawn in pixel values 5 and 13, which the recolour lookup never
#: touches, so a DOS hat is always magenta.  Purple is the C64's magenta.
DOS_CAP_COLOUR = 4

#: DOS `size` `@0x0C0` is 1 small and 2 medium; the C64 keeps the same
#: distinction one lower at `0x099`.  Anything else is a record this reader
#: does not understand, and a monster's zero is one of them.
DOS_SIZES = {1: "small", 2: "large"}


@dataclass(frozen=True)
class DosIconTables:
    """Which C64 option each DOS one becomes, and which colour each colour."""

    weapons: dict[int, int]         # DOS icon_body -> C64 weapon option
    heads: dict[int, int]           # DOS icon_head -> C64 head option
    ega_to_c64: tuple[int, ...]     # 16 EGA indices -> the C64's eight


def dos_icon_tables(path: "pathlib.Path | str | None" = None,
                    title: str | None = None,
                    size: str | None = None) -> DosIconTables:
    """Read the three tables out of :data:`PROPOSAL_PATH`.

    `title` is a `goldbox.c64_port.C64Container.key` such as
    `"secret-of-the-silver-blades"`, and `size` is `"small"` or `"large"`.
    With neither, this is exactly the base table every conversion has
    always read (#330). Where a title's own `overrides:` section names a
    row, its `c64` replaces the base table's for that DOS index only; every
    other row is untouched.

    **The base tables serve both sizes**, which is right for all but a
    handful of rows: the C64 draws a small character from a 28-weapon and
    14-head list where a large one has 35 and 23, and the shared designs are
    redrawn rather than scaled. So a row chosen against the large picture
    can be the wrong answer for a halfling, and the base table carries a
    top-level `small:` or `large:` section for those, applying to every
    title alike -- Curse ships the identical art to Pool of Radiance's and
    Silver Blades' own redraws change none of these answers (#330, #335).
    A title's own `overrides:` section may hold a `small:` or `large:`
    subsection too, for a row that is only right for *that* title at one
    size. Either way, a size-specific row wins over a size-free one at the
    same level.

    **The merge order is base, then base size, then title, then title
    size** -- each level replacing only the rows it names, so a row no
    level touches keeps whatever the level below it said. With no `size`
    given, neither size section is applied, which keeps `dos_icon_tables()`
    with no arguments meaning exactly what it has always meant.

    **The conversion passes both.** `goldbox.dos_codec.write_c64_save` builds
    `dos_icon_tables(title=container.game.key, size=which)` once per size
    and threads it through `_icon_for` into :meth:`IconParts.dos_icon`, so
    a converted character reaches the rows his own title and size name:
    Silver Blades' head 10 to C64 head 9 small and 2 large, and its small
    body 11 to an empty-handed C64 option where every other title keeps the
    armed one (`#335 (Two combat-figure rows describe Pool of Radiance's
    art, and Silver Blades draws those two options differently)`). A caller
    that passes neither still gets exactly the base table, which is what
    every reader of the numbering alone wants.
    """
    source = pathlib.Path(path or PROPOSAL_PATH)
    try:
        data = yaml.safe_load(source.read_text())
    except OSError as exc:
        raise FileNotFoundError(
            f"the combat-figure table is not at {source}; without it a DOS "
            f"figure has no C64 option to become") from exc
    weapons = {int(k): v["c64"] for k, v in data["weapons"].items()}
    heads = {int(k): v["c64"] for k, v in data["heads"].items()}
    if size:
        base_size = data.get(size) or {}
        weapons.update({int(k): v["c64"]
                        for k, v in (base_size.get("weapons") or {}).items()})
        heads.update({int(k): v["c64"]
                      for k, v in (base_size.get("heads") or {}).items()})
    override = (data.get("overrides") or {}).get(title) if title else None
    if override:
        #: A title's section may name rows directly -- those apply at both
        #: sizes -- and may hold a `small:` or `large:` section naming rows
        #: for that size alone.  The C64 draws a small character from
        #: shorter lists than a large one and the two are different
        #: pictures, so a row that is right for a human can be wrong for a
        #: halfling; Donald asked for exactly that on 2026-09-05.  A
        #: size-specific row wins over a size-free one, which is the only
        #: order that lets a section say "this everywhere, except small".
        for section in (override, override.get(size) or {} if size else {}):
            weapons.update({int(k): v["c64"]
                            for k, v in (section.get("weapons") or {}).items()})
            heads.update({int(k): v["c64"]
                          for k, v in (section.get("heads") or {}).items()})
    return DosIconTables(
        weapons=weapons, heads=heads,
        ega_to_c64=tuple(data["colours"][i]["c64"]
                         for i in sorted(data["colours"])))


@dataclass(frozen=True)
class C64IconTables:
    """Which DOS option a C64 one becomes, and which DOS colour pair a C64
    colour becomes -- the reverse of :class:`DosIconTables` (#320)."""

    #: `(size, C64 weapon option) -> DOS icon_body`.  Keyed by size because a
    #: C64 option number means a different drawing at each size -- large
    #: weapon 3 and small weapon 3 are different pictures out of different
    #: tables -- so `tools/iconreverse.yaml` gives the two sizes complete,
    #: separate lists rather than one table with exceptions.
    weapons: dict[tuple[str, int], int]
    #: `(size, C64 head option) -> DOS icon_head`, the same shape.
    heads: dict[tuple[str, int], int]
    #: C64 icon colour 0-7 -> the `(low, high)` EGA pair a DOS `icon_colours`
    #: byte holds for it.
    colours: dict[int, tuple[int, int]]


def c64_icon_tables(path: "pathlib.Path | str | None" = None,
                    title: str | None = None) -> C64IconTables:
    """Read the reverse table out of :data:`REVERSE_PATH`.

    Independent of `tools/iconreverse.py`'s own reader, the way
    :func:`dos_icon_tables` is independent of `tools/iconproposal.py`'s: that
    module's `load_tables` also draws the sheets Donald corrects, and a
    second copy of the parsing here would go out of step with a YAML
    structure change nobody remembered to mirror.

    The base section (`weapons:`/`heads:` at the top level) is the **large**
    lists in full, and `small:` is the **small** lists in full -- not a base
    plus exceptions, because a C64 option number is a different drawing at
    each size and there is no size-free answer to fall back to.

    `title` is a `goldbox.c64_port.C64Container.key`, the mirror of
    :func:`dos_icon_tables`'s own argument (`#452 (A Silver Blades combat
    figure does not survive a round trip through the C64, because the
    reverse table has no per-title rows)`). `tools/iconproposal.yaml`'s
    `overrides:` section is many-to-one *per title* -- Silver Blades' own
    `heads: 10: {c64: 2}` (`#335`) lands on the same C64 large head 2 that
    DOS heads 4 and 6 already reach in the base table -- so the base
    reverse table, which serves every title alike, can only name one of
    them. A title's own `overrides:` section here names the other: at the
    top level for a row that applies at both sizes, or under `small:` for
    one that applies at the small size only, the same two-level shape the
    base table already has. **A size a title's section does not mention is
    untouched** -- there is no size-free row to fall through to within an
    override, because there never is one in the base table either.

    With no `title`, this is exactly the base table every reader before
    `#452` used. `goldbox.dos_codec.c64_party` now passes `title=c64.key` -- the
    C64 title being read, `c64_save.container_for(game).game.key`, the
    mirror of `write_c64_save`'s own `container.game.key` -- so a Silver
    Blades character converted to the C64 and home again comes back reading
    its own title's rows.
    """
    source = pathlib.Path(path or REVERSE_PATH)
    try:
        data = yaml.safe_load(source.read_text())
    except OSError as exc:
        raise FileNotFoundError(
            f"the C64-to-DOS combat-figure table is not at {source}; "
            f"without it a C64 icon has no DOS figure to become") from exc
    weapons: dict[tuple[str, int], int] = {}
    heads: dict[tuple[str, int], int] = {}
    for size, section in (("large", data), ("small", data.get("small") or {})):
        for kind, target in (("weapons", weapons), ("heads", heads)):
            for k, row in (section.get(kind) or {}).items():
                target[(size, int(k))] = row["dos"]
    override = (data.get("overrides") or {}).get(title) if title else None
    if override:
        for size, section in (("large", override),
                              ("small", override.get("small") or {})):
            for kind, target in (("weapons", weapons), ("heads", heads)):
                for k, row in (section.get(kind) or {}).items():
                    target[(size, int(k))] = row["dos"]
    colours = {int(k): tuple(row["dos"])
              for k, row in (data.get("colours") or {}).items()}
    return C64IconTables(weapons=weapons, heads=heads, colours=colours)


@dataclass(frozen=True)
class IconChoice:
    """What :meth:`IconParts.recognise` read back out of an icon's cells."""

    weapon_size: str                # which of the two weapon lists
    weapon: int
    head_size: str                  # which of the two head lists
    head: int
    #: Every other `(size, option)` head that draws cells 1 and 10 the same
    #: way, so a caller can see that the head was not decidable rather than
    #: being handed one number as though it were.
    alternatives: tuple[tuple[str, int], ...] = ()
    #: Whether composing `weapon` then `head` reproduces the icon exactly.
    exact: bool = True


@dataclass(frozen=True)
class DosIcon:
    """A combat figure ready to write into a DOS record, and where it came
    from -- built by :meth:`IconParts.dos_icon_from_c64` for a C64 source
    (#320) and by `editor.convert.amiga_combat_icon` for an Amiga one, whose
    record already stores these bytes and has no C64 icon behind it (#379).

    `figure_source` and `colours_source` are what `goldbox.dos_codec.write`'s
    report quotes next to `icon_head`/`icon_body` and `icon_colours`
    respectively -- one sentence fragment each, following "`icon_head: 10 --
    `". `write` no longer builds that sentence itself, and no longer assumes
    every `DosIcon` came off a C64 record's eighteen screen codes: the
    provenance belongs to whoever built the icon, since only the builder
    knows which port it is describing (#379, "The DOS writer's byte
    accounting says an Amiga party's combat figure was recognised off C64
    screen codes").
    """

    head: int                        # DOS icon_head
    body: int                        # DOS icon_body
    colours: bytes                   # the six DOS icon_colours bytes
    figure_source: str               # quoted beside icon_head and icon_body
    colours_source: str              # quoted beside icon_colours
    #: The menu choices the C64 icon itself decoded to, so a caller can say
    #: which C64 weapon and head this DOS figure came from and whether the
    #: head was ambiguous.  `None` for a source with no C64 menu behind it --
    #: an Amiga record's `icon_head`/`icon_body` are DOS numbers already, not
    #: a weapon or head option `recognise` chose, so there is no real
    #: `IconChoice` to put here (#379).
    choice: "IconChoice | None" = None


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
        self._lookup: tuple[dict, list] | None = None
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

    # -- a DOS character's own figure -------------------------------------

    def dos_icon(self, head: int, body: int, size: str, colours: bytes,
                 tables: "DosIconTables | None" = None) -> bytes:
        """The 36 bytes a DOS character's own combat figure becomes.

        `head` and `body` are the DOS record's `icon_head` and `icon_body`,
        `size` is `"small"` or `"large"` off its `size` byte, and `colours`
        is its six `icon_colours` pairs.  The result is eighteen screen codes
        and eighteen colours, composed out of this disk's own option tables
        the way the ICON menu composes one -- so every icon this returns is
        an icon the game itself can make.

        **Also what an Amiga Curse or Silver Blades record's own combat
        icon becomes**, unchanged: those four values are DOS's own fields
        holding DOS's own numbers, read out of both engines' drawing
        routines rather than inferred (`#396 (Whether an Amiga Curse or
        Silver Blades record's combat-icon fields share DOS's own numbering
        is unmeasured)`, `docs/199-amiga-combat-icons.md`).  A caller
        composing for one of those two titles should pass `tables=
        dos_icon_tables(title=..., size=size)`, so Silver Blades' own
        redrawn head 10 and body 11 (`#335`) apply to its Amiga art too --
        it is identical to the DOS art these four values already describe.

        **A row that lands past a small character's own list is composed
        large.**  The C64 offers a small character 28 weapons and 14 heads
        against a large one's 35 and 23, and six of the thirty-two weapon
        rows and three of the fourteen head rows name an option only the
        large list has.  Size is never written back by the ICON menu
        (`SPELLN64` has no store to `0x099`), so a mixed icon is one the
        game's own menus reach and one is on the player's disks already --
        HOGARTH's.  The head glyph starts at cell 1 in both lists, so a large
        head on a small figure sits where a head always sits.

        The colour half takes the **low** nibble of each pair, which is the
        part's main colour; the high nibble is a highlight and the C64 keeps
        one colour a part, so it has nowhere to go.  The cap has no DOS pair
        at all -- a DOS hat is drawn in pixel values the record cannot
        recolour -- and gets :data:`DOS_CAP_COLOUR`.
        """
        tables = tables or dos_icon_tables()
        if head not in tables.heads:
            raise ValueError(f"DOS icon head {head} is not one of "
                             f"{len(tables.heads)} the table names")
        if body not in tables.weapons:
            raise ValueError(f"DOS icon body {body} is not one of "
                             f"{len(tables.weapons)} the table names")
        weapon, c64_head = tables.weapons[body], tables.heads[head]
        shape = bytes([SPACE] * (CELLS_PER_POSE * 2))
        shape = self.apply(shape, self.size_for(size, "weapon", weapon),
                           "weapon", weapon)
        shape = self.apply(shape, self.size_for(size, "head", c64_head),
                           "head", c64_head)
        seed = bytes([DEFAULT_BACKGROUND | MULTICOLOUR] * len(shape))
        return shape + self.colours_for(
            shape, dos_part_colours(colours, tables), seed)

    def size_for(self, size: str, kind: str, option: int) -> str:
        """`size`, unless only the large list is long enough to hold `option`.

        Public because `tools/iconproposal.py` needs the same rule to draw a
        mixed row on a proposal sheet -- the crash `#325 (The small head
        sheet will not draw at all, because two of its rows use a head the
        small list does not have)` fixed was that sheet's own `c64_figure`
        recomputing this for the weapon and never for the head, so a head
        past the small list hit `_apply`'s guard instead of composing large.
        """
        return "large" if option >= self.count("small", kind) else size

    # -- reading a C64 icon back into menu choices -------------------------

    def _recognisers(self) -> tuple[dict, list]:
        """The two lookups :meth:`recognise` answers from, built once.

        A dict from the fourteen weapon-only cells to `(size, option)`, and a
        list of every head option with the four head cells it draws on its
        own.  Both are built from :meth:`apply`, so they say what the game's
        own editor would draw rather than what a table here claims.
        """
        if self._lookup is None:
            blank = bytes([SPACE] * (CELLS_PER_POSE * 2))
            weapons: dict[bytes, tuple[str, int]] = {}
            heads: list[tuple[str, int, bytes]] = []
            for size in ("small", "large"):
                for option in range(self.count(size, "weapon")):
                    drawn = self.apply(blank, size, "weapon", option)
                    weapons[bytes(drawn[c] for c in WEAPON_ONLY_CELLS)] = (
                        size, option)
                for option in range(self.count(size, "head")):
                    drawn = self.apply(blank, size, "head", option)
                    heads.append((size, option,
                                  bytes(drawn[c] for c in ALWAYS_HEAD_CELLS)))
            self._lookup = (weapons, heads)
        return self._lookup

    def recognise(self, shape: bytes, prefer: str = "large") -> "IconChoice":
        """Which menu choices drew these eighteen screen codes.

        A C64 record stores the drawn cells rather than an index, so the
        conversion out of the C64 has to read the choices back.  The
        arithmetic is not a search: the fourteen cells of
        :data:`WEAPON_ONLY_CELLS` are the weapon's alone, and **all 63 weapon
        options draw a different fourteen** -- so the weapon, and which of
        the two lists it came from, are read straight out of a dict.

        The head is not always decidable and this says so rather than
        guessing quietly.  Seven of the 23 large heads are another head with
        a hair glyph added in cells 0 and 9 -- (0,18), (4,22), (5,17),
        (7,20), (8,13), (9,14), (12,19) -- and small heads 0 and 5 are the
        identical drawing.  So the head is first matched on cells 1 and 10,
        which no weapon in either list ever writes, and then narrowed to
        whichever of those compose with this weapon into exactly `shape`.
        `head` is the first survivor, at `prefer`'s size where there is a
        choice, and `alternatives` names the rest -- an icon whose head this
        cannot pin down says so instead of handing back one number as though
        it were certain.

        `exact` is True when composing the two answers reproduces `shape`
        byte for byte.  False means the icon carries a cell left behind by an
        earlier choice, which the weapon that came after would not paint
        over -- legal, on the player's own disks, and drawn by the game
        exactly as stored.  47 of the 222 icons on this machine's three C64
        disk sets are like that, over 7 of their 35 distinct shapes.

        Raises `ValueError` for a shape no weapon option drew, which is a
        hand-authored icon or a figure with no weapon chosen at all.
        """
        if len(shape) != CELLS_PER_POSE * 2:
            raise ValueError(f"an icon shape is {CELLS_PER_POSE * 2} screen "
                             f"codes, not {len(shape)}")
        weapons, heads = self._recognisers()
        hit = weapons.get(bytes(shape[c] for c in WEAPON_ONLY_CELLS))
        if hit is None:
            raise ValueError(
                f"no weapon option in either list draws {bytes(shape).hex()}; "
                f"this icon was not composed by the game's own ICON menu")
        weapon_size, weapon = hit
        wanted = bytes(shape[c] for c in ALWAYS_HEAD_CELLS)
        matches = [(size, option) for size, option, cells in heads
                   if cells == wanted]
        matches.sort(key=lambda m: (m[0] != prefer, m[1]))
        if not matches:
            raise ValueError(
                f"no head option draws cells {ALWAYS_HEAD_CELLS} of "
                f"{bytes(shape).hex()}; this icon was not composed by the "
                f"game's own ICON menu")
        # Cells 0 and 9 settle most of the ties: the seven large heads that
        # are another head with hair added draw the same 1 and 10 and differ
        # only there.  So prefer a head that composes with this weapon into
        # exactly these eighteen bytes, and fall back to the looser match
        # for an icon carrying a cell an earlier choice left behind.
        base = self.apply(bytes([SPACE] * len(shape)), weapon_size,
                          "weapon", weapon)
        exact = [m for m in matches
                 if self.apply(base, m[0], "head", m[1]) == bytes(shape)]
        chosen = exact or matches
        head_size, head = chosen[0]
        return IconChoice(weapon_size=weapon_size, weapon=weapon,
                          head_size=head_size, head=head,
                          alternatives=tuple(chosen[1:]),
                          exact=bool(exact))

    # -- a C64 character's own figure, the other direction (#320) --------

    def dos_icon_from_c64(self, icon: bytes,
                          tables: "C64IconTables | None" = None,
                          prefer: str = "large") -> "DosIcon":
        """The DOS `icon_head`, `icon_body` and six `icon_colours` bytes a
        C64 character's own combat icon becomes.

        `icon` is the 36 bytes a C64 record's icon table holds -- eighteen
        screen codes then eighteen colours, the shape :meth:`dos_icon` and
        :meth:`default_icon` both return.  It is read back into the menu
        choices that drew it (:meth:`recognise`) and each is looked up in
        `tools/iconreverse.yaml` through `tables`, Donald's own judgement
        (#320) the way `tools/iconproposal.yaml` is his for the DOS-to-C64
        direction.

        **Where the head is ambiguous**, `recognise` already resolved it:
        `IconChoice.head` is the first of the candidates that compose back
        into this icon's own bytes exactly, which is what the two
        candidates share -- they draw the *same picture* here, so either
        answers the question "what does this icon look like" the same way.
        A caller that wants to know it was ambiguous reads `choice.
        alternatives` off the result; this method does not guess among
        pictures that differ, only among numbers that do not.

        Raises `ValueError` when `icon` was not composed by the game's own
        ICON menu (see :meth:`recognise`), or when `tables` has no row for
        the weapon or head `recognise` named -- which none of the shipped
        table's 100 rows should, since `tests/test_iconreverse.py` pins one
        for every option the game offers; a `KeyError` here means `tables`
        came from somewhere else.

        The colour half takes :meth:`part_colours` per class and looks each
        up in `tables.colours`; a part this icon draws nothing of -- an
        empty-handed weapon, no cap, no shield -- has no colour to read, and
        gets :data:`DEFAULT_BACKGROUND`'s own row, which is invisible either
        way because nothing of that part is drawn.
        """
        if len(icon) != CELLS_PER_POSE * 4:
            raise ValueError(f"a combat icon is {CELLS_PER_POSE * 4} bytes "
                             f"(shape and colours), not {len(icon)}")
        shape, colours = icon[:CELLS_PER_POSE * 2], icon[CELLS_PER_POSE * 2:]
        tables = tables or c64_icon_tables()
        choice = self.recognise(shape, prefer=prefer)
        try:
            body = tables.weapons[(choice.weapon_size, choice.weapon)]
        except KeyError:
            raise ValueError(
                f"no row in tools/iconreverse.yaml for the C64 "
                f"{choice.weapon_size} weapon {choice.weapon}") from None
        try:
            head = tables.heads[(choice.head_size, choice.head)]
        except KeyError:
            raise ValueError(
                f"no row in tools/iconreverse.yaml for the C64 "
                f"{choice.head_size} head {choice.head}") from None
        per_class = self.part_colours(colours, shape)
        dos_colours = bytearray(6)
        for i, part in enumerate(DOS_PAIR_CLASSES):
            c64_colour = per_class.get(PART_CLASSES.index(part),
                                       DEFAULT_BACKGROUND)
            low, high = tables.colours.get(c64_colour,
                                           (c64_colour & 7,
                                            (c64_colour & 7) | 8))
            dos_colours[i] = (high << 4) | low
        figure_source = (
            "the C64 source record's own combat icon, recognised off its "
            "eighteen screen codes and looked up through "
            f"tools/iconreverse.yaml (#320, weapon {choice.weapon_size} "
            f"{choice.weapon}, head {choice.head_size} {choice.head})")
        colours_source = (
            "the C64 source record's own combat icon colours, converted "
            "through the same table's colour rows (#320)")
        return DosIcon(head=head, body=body, colours=bytes(dos_colours),
                      figure_source=figure_source,
                      colours_source=colours_source, choice=choice)

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


#: The two parts whose **high** nibble is the colour a player sees, where every
#: other part's is the low one.
#:
#: A DOS colour byte holds two 4-bit colours, and the C64 has one colour for
#: the whole part, so the conversion has to pick the one that covers more of
#: the shape.  Counted pixel by pixel over the shipped art (`tools/dosnibbles.py`):
#: the high nibble covers **56-65% of the leg in 32 of 32 bodies** and
#: **68-72% of the shield in 8 of 8 that carry one**, and the low nibble wins
#: everywhere else.
#:
#: Reading the low nibble for all six was invisible for 222 of 296 records,
#: because both nibbles of the default colour set land on the same C64 colour
#: through Donald's own match table -- and then MAGNUS's yellow shield came out
#: black, which is what made it findable (#130).
DOS_HIGH_NIBBLE_PARTS = frozenset({"leg", "shield"})


def dos_part_colours(icon_colours: bytes,
                     tables: "DosIconTables | None" = None) -> dict[int, int]:
    """The seven C64 part colours a DOS record's six colour pairs become.

    Keyed by part class, which is what :meth:`IconParts.colours_for` takes.
    Each DOS byte holds two colours and the C64 keeps one, so the nibble that
    covers more of that part is the one taken -- see `DOS_HIGH_NIBBLE_PARTS`.
    """
    tables = tables or dos_icon_tables()
    out = {}
    for i, part in enumerate(DOS_PAIR_CLASSES):
        byte = icon_colours[i]
        ega = (byte >> 4) if part in DOS_HIGH_NIBBLE_PARTS else (byte & 0x0F)
        out[PART_CLASSES.index(part)] = tables.ega_to_c64[ega]
    out[PART_CLASSES.index("cap")] = DOS_CAP_COLOUR
    return out


def dos_size(size_byte: int) -> str:
    """DOS `size` `@0x0C0` as the C64's own word for it."""
    try:
        return DOS_SIZES[size_byte]
    except KeyError:
        raise ValueError(
            f"DOS size {size_byte} is neither 1 (small) nor 2 (medium); "
            f"every player record any title writes holds one of those") from None
