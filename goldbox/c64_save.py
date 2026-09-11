"""One C64 title's saved game: the file on the disk and the map of its bytes.

A `C64Container` says how big a title's save file is, what it is called and
where it loads, **and** what is *inside* it -- which pages are characters,
which are items, where the names and the roster are, which header bytes a
conversion computes and which it writes as a measured zero.  A table, not a
class hierarchy: what differs between the titles is a handful of numbers.

**The two halves were two classes until `#470 (Give the project a neutral
title beside its neutral character record, with one port per platform a title
shipped on)`'s stage 7.**  `goldbox.games.Game` held the disk geometry for six
titles and `Container` held the payload map for three, so a reader asking
*"where does this save load?"* and *"what is at `+$C7`?"* went to two
different classes about one file, and the two kept their own copies of the
same offsets.  They are one class now, with six rows; `goldbox.c64_port.Game`
is this class under its old name until stage 9 deletes the alias.

**Three of the six rows have no measured payload map**, and that is the point
of `measured` rather than an oversight.  Champions of Krynn, Death Knights of
Krynn and Gateway to the Savage Frontier have their geometry from one shipped
pre-generated party each and nobody here has read a save of them, so
:func:`container_for` refuses them exactly as it did when they had no row at
all.  A title answering with another title's offsets is the defect
`#460 (goldbox/games.py has no Pools of Darkness entry, so every lookup
answers with Pool of Radiance's tables for it)` names, one class over.

**Every offset here is a payload offset**, so the same number means the same
thing in both titles -- Pool of Radiance's save image loads at `$4900` and
Curse of the Azure Bonds' at `$4B00`, and every field anybody has looked at
sits at the same distance into the payload.  That is not a convenience: it is
the finding.  The same routine appears in both titles' `DUNGEON` with every
operand `$200` apart -- Pool of Radiance's clock tick at `$0DEC` reads
`INC $49C6,X / CMP $0E4D,X / STA $49C6,X` and Curse's at `$0D4F` reads
`INC $4BC6,X / CMP $0DB0,X / STA $4BC6,X`, instruction for instruction -- and
the two ports' `ECL` bytecode is the same bytes, so the scripts cannot name
different addresses (`#192` step 0a).

What is **not** the same is the container around those bytes.  Pool of
Radiance writes two files, `SAVEDGAME0` at `$4900` and `SAVEDGAME1` at
`$8300`, and keeps twelve character pages, twelve item pages and its roster in
the second file; every later title writes **one** file of exactly 7426 bytes,
a `$1D00` payload holding eight character pages, a table of the party's names
where Pool of Radiance's ninth character page would be, eight item pages,
`ANIMATE00`'s picture buffer and the roster at the end.  Measured on the
player's own disks for Curse, Silver Blades, Champions of Krynn, Death Knights
of Krynn and Gateway to the Savage Frontier.  The write-up,
`work/reports/goldbox-inventory.md`, is lost; the per-title base addresses are
asserted in `tests/test_curse.py::test_the_addresses_are_the_ones_measured`.

Confidence: Pool of Radiance's row and Curse of the Azure Bonds' are each
measured on that title's own engine-written saves.  Secret of the Silver
Blades' is not -- the only save of it anybody here has is the one SSI shipped
-- so its rows are read out of that title's own overlays and its `ECL`
bytecode wherever the code says anything at all, and graded where they are
made.
"""

from __future__ import annotations

import dataclasses

from . import titles
from .titles import (
    CLASS_BITS_CLASSIC,
    CLASS_BITS_KRYNN,
    CLASS_BITS_WITH_PALADIN_RANGER,
    RACES_CURSE,
    RACES_FORGOTTEN_REALMS,
    RACES_KRYNN,
    RACES_SILVER_BLADES,
    Title,
)

__all__ = [
    "C64Container",
    "Container",
    "Region",
    "HEADER_SIZE",
    "SLOT_STRIDE",
    "ITEM_AREA_OFFSET",
    "ICON_TABLE_OFFSET",
    "ROSTER_PAGE",
    "NAMES_LOAD_ADDRESS_POOL",
    "NAMES_LOAD_ADDRESS_LATER",
    "POSITION_OFFSET",
    "SHOWN_CLOCK_OFFSET",
    "CLOCK_OFFSET",
    "INDOORS_FLAG_OFFSET",
    "TRAVEL_POSITION_OFFSET",
    "POOL_OF_RADIANCE",
    "CURSE_OF_THE_AZURE_BONDS",
    "SECRET_OF_THE_SILVER_BLADES",
    "CHAMPIONS_OF_KRYNN",
    "DEATH_KNIGHTS_OF_KRYNN",
    "GATEWAY_TO_THE_SAVAGE_FRONTIER",
    "CONTAINERS",
    "container_for",
]


#: A run of payload bytes and the sentence its report line carries.
Region = tuple[int, int, str]


# --- the offsets every measured title agrees on -----------------------------
# Each is the default of the field named beside it, and the field is what a
# row may move; these are the names the rest of the tree reads, re-exported
# by `goldbox/c64_port.py` so that `games.HEADER_SIZE` still answers.  The
# one that is not obvious is the icon table: 8 icons of 36 bytes from $2E0
# end exactly at $400, the start of the slot area, in both games where it has
# been read.
HEADER_SIZE = 0x400            # C64Container.slot_area
SLOT_STRIDE = 0x100            # C64Container.slot_stride
ITEM_AREA_OFFSET = 0x1000      # C64Container.item_area
ICON_TABLE_OFFSET = 0x2E0      # C64Container.icon_table
ROSTER_PAGE = 0x100            # C64Container.roster_size

# --- item names -------------------------------------------------------------
# `ITEMNAMES` is 256 low bytes, 256 high bytes, then the strings, and the
# pointers are ABSOLUTE, so the file is unreadable without its load address --
# which is not the one in its PRG header ($3000 on Curse, $1517 on Gateway).
# Each value below is fitted: it is the only base at which entry 1 lands on
# "BATTLE AXE", the first string, at payload offset $201 in all six titles.
NAMES_LOAD_ADDRESS_POOL = 0x6F00
NAMES_LOAD_ADDRESS_LATER = 0x9E00

# --- payload offsets a running machine needs --------------------------------
# Both are inside the save image, so both follow `save_load_address`.
POSITION_OFFSET = 0x0C0        # x, y, facing -- the copy the game *saves*

# The three digits of the clock the status line draws -- minute units, tens,
# hour -- which are the second, third and fourth of the six one-byte digits
# `C64Container.clock` starts at `+$C6`.  The first is a sub-minute tick
# nothing ever prints, which is why the two constants sit a byte apart:
# `automap.target` folds three bytes as `c[2] * 60 + c[1] * 10 + c[0]`, and at
# `+$C6` that is minute tens times sixty.  Read out of the tick loop and the
# status-line printer in all three titles by `tools/c64clock.py`
# (`docs/30-savegame-layout.md`); the name says which of the two facts it is,
# which is what `#470` renamed it for.
SHOWN_CLOCK_OFFSET = 0x0C7

#: Pre-#470 name, kept so nothing importing it breaks before stage 9. `#470
#: (Give the project a neutral title beside its neutral character record, with
#: one port per platform a title shipped on)`.
CLOCK_OFFSET = SHOWN_CLOCK_OFFSET

# The travel grid's own two facts, both inside the save image and both
# Pool of Radiance measurements (`docs/113-world-map.md`,
# `docs/118-debug-mode.md`, `docs/140-loaded-files-cache.md`).  `$49E6` is
# non-zero in a `GEO` area and zero on the grid; `$49C3`/`$49C4` is the
# window-local square out there, x then y, and it is not consulted unless the
# flag says to.
INDOORS_FLAG_OFFSET = 0x0E6    # C64Container.indoors
TRAVEL_POSITION_OFFSET = 0x0C3  # C64Container.travel_position

# --- the addresses that are not in the save image ----------------------------
# `LIVE_POSITION_GOLDBOX`, `MODE_FLAG_POOL` and `MODE_FLAG_LATER` are in
# `automap/c64.py`, with the measurements behind each of them, because they
# are addresses in a *running* game rather than offsets into a save file and a
# running machine is `automap/`'s.  No alias is left for them anywhere under
# `goldbox/`, and that is forced rather than chosen: the alias would have to
# import `automap`, and `tests/test_wish.py::test_goldbox_imports_no_transport`
# forbids that -- it is what keeps `editor/`'s promise that it never talks to
# an emulator.


#: What a row built outside the registry gets before `__post_init__` looks up
#: its key: a `Title` with nothing in it, which is never the answer a row
#: keeps.  The lookup mirrors `automap.c64._machine`, which gives a `Game`
#: whose key `goldbox/titles.py` does not know a `Title` of its own with no
#: tables in it.
_UNKNOWN_RULES = Title(key="", title="")


@dataclasses.dataclass(frozen=True)
class C64Container:
    """One title's saved game: the file on the disk, and the map of its bytes.

    `roster_file` is the whole difference between the two shapes.  When it is
    None the roster is `roster_offset` bytes into the main payload; when it is
    set the roster is that separate file, and `roster_offset` is an offset
    within *it*.

    `races`, `class_bits` and `item_names_load_address` are the three things
    that are per-title *content* rather than per-title geometry.  Each may be
    None, and None means "we do not know", not "there are none": a caller that
    gets None must show the raw number rather than invent a name for it.

    **Every field from `slot_area` down is the payload map, and it is a
    measurement only where `measured` is True.**  The defaults are what the
    three measured titles agree on, so an unmeasured row answers with
    plausible numbers nobody has checked; :func:`container_for` and
    :data:`CONTAINERS` are the two doors, and both refuse the unmeasured three.
    """

    # -- the title, and the disk ------------------------------------------
    key: str                       # stable identifier, written into the YAML
    title: str                     # what a person calls it
    save_file: bytes               # the payload file's directory name
    save_load_address: int
    save_size: int                 # payload, excluding the 2-byte PRG header
    roster_file: bytes | None = None
    roster_load_address: int | None = None
    roster_size: int = ROSTER_PAGE
    roster_offset: int = 0
    disk_glob: str = "*.[dD]64"

    #: The title whose C64 release this is -- the rules, apart from any
    #: machine.  `races` and `class_bits` below are its own tuples, passed in
    #: rather than read through so that `dataclasses.replace(row, races=None)`
    #: still means what it meant when this was `goldbox.games.Game`; a row
    #: built outside the registry resolves this from `key` in `__post_init__`.
    #:
    #: It is spelled `rules` rather than `title` because `title` is taken:
    #: `#470`'s D1 settled the display name as `.title` on both classes, and
    #: about 125 sites read it off a container expecting the string.
    rules: Title = _UNKNOWN_RULES

    # Pairs rather than dicts so the descriptor stays hashable and frozen.
    races: tuple[tuple[int, str], ...] | None = None
    class_bits: tuple[tuple[int, str], ...] | None = None
    item_names_load_address: int | None = None

    # -- the payload map ---------------------------------------------------
    #: Has anybody here read a save of this title?  False for Champions of
    #: Krynn, Death Knights of Krynn and Gateway to the Savage Frontier, whose
    #: geometry above is measured and whose payload map below is not.
    measured: bool = False

    # -- the pages ---------------------------------------------------------
    #: Where the character slots begin, and how many pages of them the file
    #: actually has.  `party_slots` is how many a party member can occupy;
    #: `record_pages` is how many the file carries, which is more than that
    #: in Pool of Radiance because combat fills four more.
    slot_area: int = HEADER_SIZE
    slot_stride: int = SLOT_STRIDE
    party_slots: int = 8
    record_pages: int = 12
    #: The party's names again, sixteen bytes each, or None for a title that
    #: keeps no such table.
    name_table: int | None = None
    name_stride: int = 16
    #: Which index that table is keyed by.  False -- Curse of the Azure
    #: Bonds' -- means entry *n* is the name of the character in slot *n*.
    #: True means entry *n* is the *n*th character of the marching order,
    #: which is the reverse, because the C64 fills slots from the top down.
    #: **Nothing in either engine reads what we write here**: the table is a
    #: scratch buffer `GEN` clears and refills from the save disk's directory
    #: before every read (`docs/216-the-c64-name-table.md`).  The field stays
    #: because a table written the other way round is still wrong on the
    #: disk, and it is what `SECRET_OF_THE_SILVER_BLADES` below describes.
    names_in_marching_order: bool = False
    #: The item pages, one per slot, and how many the file carries.
    item_area: int = ITEM_AREA_OFFSET
    item_pages: int = 12
    #: The combat-icon table: eight icons of 36 bytes, ending exactly where
    #: the slot area begins.
    icon_table: int = ICON_TABLE_OFFSET
    icon_size: int = 36
    #: `ANIMATE00`'s picture buffer: the decoded glyphs and colours of
    #: whatever picture was in the view window when the save was written,
    #: which on `ENCAMP` is always the camp scene.  None for a title whose
    #: save does not span it.
    #:
    #: **Not a map**, though it was called one until #309 (Eight files still
    #: call Curse's picture buffer a map region, which is what it was guessed
    #: to be before anybody read it).  It is not a region the game keeps
    #: anything in: a Curse or Silver Blades save is one KERNAL `SAVE` of
    #: `$4B00`-`$67FF` and `$6300` is simply what lies between the item pages
    #: and the roster.  `docs/181-curse-picture-buffer.md` has the decode,
    #: the two specimens matching a frame byte for byte, and the driven
    #: session in which nothing read the region before the engine zeroed it.
    picture_buffer: tuple[int, int] | None = None
    #: How far apart the roster blocks sit.  Where they *are* is
    #: `roster_offset` above, which is an offset into this payload unless
    #: `roster_file` names a second file, and then it is an offset into that.
    #: The two were separate fields, `Game.roster_offset` and a
    #: `Container.roster_offset` that was None wherever the first was a real
    #: number, until `#470`'s stage 7 merged them; `roster_in_payload` is the
    #: question every caller was actually asking and it now has one answer.
    roster_stride: int = 0x20

    # -- the header --------------------------------------------------------
    #: The loaded-files cache: 25 slots, one per file kind.
    cache: tuple[int, int] = (0x2C0, 25)
    #: Does a converted save have to set bit 7 on the slots it fills?
    #:
    #: **The two titles are the reverse of each other, and getting it wrong
    #: is a save whose cache the loader reads as something else.**  Pool of
    #: Radiance ORs the bit on the *load* path -- `GEN $25DE` is
    #: `LDA $4BC0,X / ORA #$80 / STA $6E13,X` over all 25 -- so whatever a
    #: save carries is discarded and set again.  Curse ORs it on the *save*
    #: path and copies raw on load: `CAMP $0CBC` and `GEN $1F9F` are
    #: `LDA $7F13,X / ORA #$80 / STA $4DC0,X`, and `GEN $1F55` is
    #: `LDA $4DC0,X / STA $7F13,X` with no `ORA` (`#192` step 0e).
    cache_bit7: bool = False
    #: The byte the loader asks the player for a disk side by.
    disk_hint: int = 0xEA
    #: The map `LOADFILES` reloads, the script id, and the indoors flag.
    current_geo: int = 0xC5
    current_script: int = 0xF2
    indoors: int = INDOORS_FLAG_OFFSET
    #: The party's square and facing, the travel-grid square, the six clock
    #: digits, and the quest-flag page.
    #:
    #: **The flag page ends in a different place in each title**, so this is
    #: `(offset, length)` rather than a shared constant.  Pool of Radiance's
    #: stops at `+$1F8` because `+$1FA` and `+$1FD` are its wallset and
    #: wallmap triples; Curse of the Azure Bonds and Secret of the Silver
    #: Blades keep their wall triples elsewhere and their scripts use the
    #: page to the end -- see `goldbox.dos.quest_flags`.
    position: int = POSITION_OFFSET
    travel_position: int = TRAVEL_POSITION_OFFSET
    clock: int = 0xC6
    quest_flags: tuple[int, int] = (0x120, 0xD9)
    #: The switch that decides whether the character sheet draws a portrait.
    portrait_switch: int = 0xFF

    #: Header runs a conversion writes as zero, with what measured each.
    zeroed: tuple[Region, ...] = ()
    #: Header runs a conversion copies out of the DOS save, at the same
    #: distance into that title's own ECL variable array.
    copied: tuple[Region, ...] = ()

    def __post_init__(self) -> None:
        """Resolve `rules` from `key` for a row built outside the registry.

        The registry's own six rows pass their `Title` in.  A row somebody
        builds by hand -- a test's made-up title, or `dataclasses.replace` of
        one of the six -- gets the registry's `Title` if its key names one and
        a tables-free `Title` of its own if it does not, which is the same
        answer `automap.c64._machine` has given such a row since stage 6.
        """
        if self.rules is _UNKNOWN_RULES:
            object.__setattr__(
                self, "rules",
                titles.BY_KEY.get(self.key)
                or Title(key=self.key, title=self.title,
                         races=self.races, class_bits=self.class_bits))

    # -- derived: the file -------------------------------------------------
    @property
    def payload_size(self) -> int:
        return self.save_size

    @property
    def save_prg_size(self) -> int:
        """What the file measures on disk, load address included."""
        return self.save_size + 2

    @property
    def files(self) -> tuple[bytes, ...]:
        """Every directory entry that makes up a save."""
        if self.roster_file is None:
            return (self.save_file,)
        return (self.save_file, self.roster_file)

    @property
    def roster_in_payload(self) -> bool:
        return self.roster_file is None

    def matches_payload(self, prg: bytes) -> bool:
        """Does this PRG look like this title's save? Size and load address.

        A corroborator, not the discriminator -- Curse's own side B carries a
        2032-byte `SAVEAZURE` that is a truncated demo party, and this is how
        that is told from the real thing.
        """
        return (len(prg) == self.save_prg_size
                and len(prg) >= 2
                and prg[0] | (prg[1] << 8) == self.save_load_address)

    # -- derived: the title's own tables -----------------------------------
    @property
    def travel_grid(self) -> bool:
        """`goldbox.titles.Title.travel_grid`, for a caller holding a row.

        Does this title have a square-engine overland at all? **True for Pool
        of Radiance only.**
        """
        return bool(self.rules.travel_grid)

    @property
    def race_names(self) -> dict[int, str] | None:
        """Race code -> name, or None when this title's list is unknown."""
        return None if self.races is None else dict(self.races)

    @property
    def class_bit_names(self) -> dict[int, str] | None:
        """Class bit -> name, or None when this title's list is unknown."""
        return None if self.class_bits is None else dict(self.class_bits)

    # -- derived: the payload map ------------------------------------------
    def slot(self, index: int) -> int:
        return self.slot_area + index * self.slot_stride

    def items(self, index: int) -> int:
        return self.item_area + index * self.slot_stride

    def icon(self, index: int) -> int:
        return self.icon_table + index * self.icon_size

    def name(self, index: int) -> int:
        if self.name_table is None:
            raise ValueError(f"{self.title} keeps no name table")
        return self.name_table + index * self.name_stride

    def name_index(self, slot: int, party: int) -> int:
        """Which table entry belongs to the character in `slot`.

        `party` is how many characters the party has, because a marching-order
        table is indexed from the top slot down and the top slot is
        `party - 1` -- the same arithmetic `goldbox.dos.marching_slot` does
        in the other direction.
        """
        return (party - 1 - slot) if self.names_in_marching_order else slot

    # -- the save image's regions, live ------------------------------------
    # Each is one of the payload offsets above raised to a live address by
    # `save_load_address`, and each reads the row's own field rather than the
    # module constant, so the file and the running machine cannot come to
    # disagree about where a region sits.  `automap.c64.C64Machine` computes
    # the same addresses from the same fields, and
    # `tests/test_c64machine.py::test_the_machine_answers_what_game_answers`
    # pins that the two agree for all six titles.  `goldbox/savegame.py` reads
    # `slot_area_base` and `roster_base` and cannot reach the machine, which is
    # why they are here as well as there.

    @property
    def slot_area_base(self) -> int:
        return self.save_load_address + self.slot_area

    @property
    def item_area_base(self) -> int:
        return self.save_load_address + self.item_area

    @property
    def icon_table_base(self) -> int:
        return self.save_load_address + self.icon_table

    @property
    def save_position_base(self) -> int:
        """The save image's own copy of the party square.

        Refreshed only when the game saves, so it names the square the party
        stood on at the last save.  `automap.c64.C64Machine.live_position` is
        the one that moves.
        """
        return self.save_load_address + self.position

    @property
    def clock_base(self) -> int:
        """The three clock digits the status line draws, live.

        `automap.c64.C64Machine.shown_clock_base` under its pre-#470 name --
        and it is **not** the whole clock, which is six digits from `clock` at
        `+$C6`.  See :data:`SHOWN_CLOCK_OFFSET` above, which is this one past
        that one and is what the machine computes from.
        """
        return self.save_load_address + self.clock + 1

    @property
    def indoors_flag_base(self) -> int | None:
        """`$49E6`: zero on the travel grid, non-zero in a `GEO` area.

        None unless `travel_grid`, the same refusal
        `automap.c64.C64Machine.live_position` makes for the same reason:
        reading this on a title with no travel grid would answer a byte of
        unrelated resident code as though it meant something.
        """
        return (self.save_load_address + self.indoors
                if self.travel_grid else None)

    @property
    def travel_position_base(self) -> int | None:
        """`$49C3`/`$49C4`: the window-local travel-grid square, x then y.

        None unless `travel_grid`, for the same reason as `indoors_flag_base`.
        """
        return (self.save_load_address + self.travel_position
                if self.travel_grid else None)

    @property
    def roster_base(self) -> int:
        """The roster's live address, wherever it lives."""
        if self.roster_file is None:
            return self.save_load_address + self.roster_offset
        return self.roster_load_address + self.roster_offset

    # -- pre-#470 spellings, kept until stage 9 ----------------------------
    @property
    def game(self) -> "C64Container":
        """This row, under the name `Container.game` used to answer by.

        The disk geometry was a `goldbox.games.Game` the container pointed at
        until stage 7 merged the two, so `container.game.key` and
        `container.key` are now the same string off the same object.
        """
        return self

    @property
    def slot_count(self) -> int:
        """`party_slots`, under the name `goldbox.games.Game` gave it."""
        return self.party_slots


#: `#470`'s pre-stage-7 name for this class, kept until stage 9 moves the
#: callers off it.  `goldbox.c64_port.Game` is the same object again.
Container = C64Container


#: What every entry of Pool of Radiance's zeroing list was measured by, said
#: once rather than eleven times.  All 192 bytes were written as zero in a
#: converted save that was then loaded, walked, taken into a random encounter
#: and taken through an area change in VICE (`#118`), and 48 of the 56 that
#: were unattributed before that run are zero in all 99 C64 save payloads on
#: this machine.
_POOL_ZERO = ("zero: no part of the conversion computes it, and a save with "
              "all 192 of these written as zero loaded, walked, fought and "
              "changed area (#118)")

#: And what Curse's list rests on, which is a different measurement.  Every
#: byte of the header outside the square, the clock, the eight named bytes,
#: the cache and the icon table is **zero in both engine-written Curse saves
#: on this machine** -- `work/issue32/specimens/A-no-items.D64`, taken before
#: the party had walked anywhere, and `D-curse-party-with-items.D64`, taken in
#: Tilverton after shopping.  So a zero here is the value the engine itself
#: writes rather than a value nobody has looked at.  PROBABLE: two saves of
#: one party, and `#192` step 3 is the run that loads one back.
_CURSE_ZERO = ("zero: what both engine-written Curse saves hold there, and "
               "what the same address is written as in a Pool of Radiance "
               "save that was loaded, walked and fought in (#118, #192)")

POOL_OF_RADIANCE = C64Container(
    key="pool-of-radiance",
    title="Pool of Radiance",
    rules=titles.POOL_OF_RADIANCE,
    save_file=b"SAVEDGAME0",
    save_load_address=0x4900,
    save_size=0x1C00,
    roster_file=b"SAVEDGAME1",
    roster_load_address=0x8300,
    roster_size=0x0800,
    disk_glob="POOL*.[dD]64",
    races=RACES_FORGOTTEN_REALMS,
    class_bits=CLASS_BITS_CLASSIC,
    item_names_load_address=NAMES_LOAD_ADDRESS_POOL,
    measured=True,
    zeroed=(
        (0x0C3, 2, _POOL_ZERO), (0x0CC, 26, _POOL_ZERO),
        (0x0E7, 3, _POOL_ZERO), (0x0EB, 5, _POOL_ZERO),
        (0x0F0, 2, _POOL_ZERO), (0x0F3, 9, _POOL_ZERO),
        (0x0FC, 1, _POOL_ZERO), (0x0FD, 2, _POOL_ZERO),
        (0x1F9, 135, _POOL_ZERO), (0x2D9, 7, _POOL_ZERO),
    ),
)

#: Curse of the Azure Bonds.  Four rows differ from Pool of Radiance's and
#: each has its own measurement:
#:
#: * **the disk hint is `+$EE`, not `+$EA`.**  `CAMP $0C87` is
#:   `LDA $7F12 / STA $2BE6 / STA $4BEE` on the save path and `GEN $2008` is
#:   `LDA $4BEE / STA $7F12` on the load path; `+$EE` reads 2 in all three
#:   engine-written Curse saves, whose files are on side 2, and `+$EA` reads
#:   0 in all three and is named by nothing in 411 files (`#192` step 0e).
#:   So Pool of Radiance's five-byte zeroing run from `+$EB` is split in two
#:   here, and `+$EE` is written from the area's own row.
#: * **`+$E7` and `+$E8` are copied, not zeroed.**  Four area scripts write
#:   them at their heads and `DUNGEON $1502` reads them; nobody has said what
#:   they hold, so the party's own value crosses rather than a zero.
#: * **the per-script scratch `+$100`-`+$11F` is copied.**  `DUNGEON $21BA`,
#:   the `NEWECL` handler, clears it **only when the script id changes**
#:   (`CMP $7F1B / BEQ` guarding `LDX #$1F / LDA #$00 / STA $4C00,X`), so a
#:   save taken inside an area is carrying live scratch its own script reads
#:   on the next step.  Pool of Radiance zeroes it because `DUNGEON $202A`
#:   does the same clear and its converted saves always arrive somewhere.
#: * **the party's names have a table of their own** at `+$C00`, where Pool
#:   of Radiance's ninth character page would be.  Sixteen bytes each **in
#:   slot order**: in both engine-written specimens name *n* is the name in
#:   the record at slot *n*, for six characters and for four.
CURSE_OF_THE_AZURE_BONDS = C64Container(
    key="curse-of-the-azure-bonds",
    title="Curse of the Azure Bonds",
    rules=titles.CURSE_OF_THE_AZURE_BONDS,
    save_file=b"SAVEAZURE",
    save_load_address=0x4B00,
    save_size=0x1D00,
    disk_glob="CURSE*.[dD]64",
    races=RACES_CURSE,
    class_bits=CLASS_BITS_WITH_PALADIN_RANGER,
    item_names_load_address=NAMES_LOAD_ADDRESS_LATER,
    measured=True,
    party_slots=8,
    record_pages=8,
    name_table=0xC00,
    item_pages=8,
    picture_buffer=(0x1800, 0x400),
    roster_offset=0x1C00,
    cache_bit7=True,
    disk_hint=0xEE,
    quest_flags=(0x120, 0xE0),
    zeroed=(
        (0x0C3, 2, _CURSE_ZERO), (0x0CC, 26, _CURSE_ZERO),
        (0x0E9, 1, _CURSE_ZERO),
        (0x0EA, 1,
         "zero: this is Pool of Radiance's disk hint and Curse does not use "
         "it -- no absolute-mode instruction in 411 files names it, against "
         "three that name +$EE, and it reads 0 in all three engine-written "
         "Curse saves whose files are on side 2 (#192 step 0e)"),
        (0x0EB, 3, _CURSE_ZERO),
        (0x0EF, 1, _CURSE_ZERO),
        (0xC80, 0x380,
         "zero: the name table fills the first 128 bytes of its page and the "
         "rest of the page is zero in all three engine-written Curse saves"),
        (0x0F0, 2, _CURSE_ZERO), (0x0F3, 9, _CURSE_ZERO),
        (0x0FC, 1,
         "zero: the two ports disagree about it -- the DOS save holds 4 and "
         "both engine-written C64 saves hold 2 -- so it is a loader value "
         "each port keeps for itself rather than a variable the party "
         "carries, and Pool of Radiance's own zero here was loaded, walked "
         "and fought in (#118)"),
        (0x0FD, 2,
         "zero: nineteen of Curse's area scripts write +$FE and nine write "
         "+$FD from their own entry code, so the arriving script refills "
         "both (#192 step 0e)"),
        (0x200, 128, _CURSE_ZERO), (0x2D9, 7, _CURSE_ZERO),
    ),
    copied=(
        (0x0E7, 2,
         "from the DOS save: four area scripts write these two at their "
         "heads and DUNGEON $1502 reads them, and nobody has said what they "
         "hold -- so the party's own value crosses rather than a zero "
         "(#192 step 0e)"),
        (0x100, 0x20,
         "the per-script scratch, from the DOS save: DUNGEON $21BA clears it "
         "only when the script id changes, so a save taken inside an area is "
         "carrying live scratch its own script reads on the next step "
         "(#192 step 0a)"),
    ),
)

#: What Silver Blades' zeroing list rests on, and it is a weaker measurement
#: than either of the other two: **there is one Secret of the Silver Blades
#: save on this machine and it is the one SSI shipped on side 6**, so a zero
#: here is what that file holds rather than what an engine-written save of a
#: played party holds.  Every byte of the header outside the square, the
#: clock, the named bytes, the cache and the icon table is zero in it.  The
#: `#193` step-3 resave is what turns this into a measurement of the engine.
_SILVER_ZERO = ("zero: what the one Secret of the Silver Blades save on this "
                "machine holds there, and what the same address is written as "
                "in a Pool of Radiance save that was loaded, walked and "
                "fought in (#118, #193)")

#: Secret of the Silver Blades.  **The container is Curse of the Azure Bonds'
#: byte for byte under a different file name** -- one 7424-byte `SAVEDBASH` at
#: `$4B00`, header `$400`, eight character pages, a name table at `+$C00`,
#: eight item pages at `+$1000`, the picture buffer at `+$1800` and the
#: roster at `+$1C00` (`tests/test_silverblades.py`).  Three rows differ from
#: Curse's, and each was read out of this title's own overlays rather than
#: assumed:
#:
#: * **the cache bit and the disk hint are Curse's, and the code says so.**
#:   `CAMP $0CA5` is `LDX #$18 / LDA $7F13,X / ORA #$80 / STA $4DC0,X` on the
#:   save path with `LDA $4BF2 / ORA #$80 / STA $4DC8` after it, `GEN $2469`
#:   is the same loop, and `GEN $2424` is `LDA $4DC0,X / STA $7F13,X` with no
#:   `ORA` on the load path -- so a converted save must set bit 7 itself.
#:   `CAMP $0C65` is `LDA $7F12 / STA $4BEE` and `GEN $228E` is
#:   `LDA $4BEE / STA $7F12`, so `+$EE` is the disk hint here too; `+$EA` is
#:   named twice in `DUNGEON $0B0E`, which stores a table byte into it and
#:   reads it back three instructions later, so nothing in the save reaches
#:   that read.  CONFIRMED.
#: * **`+$E7`-`+$E9` and `+$FD`-`+$FE` are copied rather than zeroed.**  An
#:   address census over all 22 of this title's scripts, both ports
#:   (`tools/eclcensus.py`), gives `$4BE7` and `$4BE8` 18 writes and **no
#:   reads** over seventeen scripts, `$4BE9` 10 writes over seven, `$4BFD` 8
#:   and `$4BFE` 16.  They are per-area constants an arriving script sets, and
#:   the party's own value is in the DOS save at the same ECL address, so the
#:   conversion writes that rather than a zero nobody has measured.  Curse
#:   zeroes `+$FD`/`+$FE` and its engine put 8 and 9 back unasked, which is
#:   the same fact from the other side.
#: * **the name table is a scratch buffer, and its order describes two disks
#:   rather than the engine.**  `GEN` clears all 256 bytes and refills them
#:   from the save disk's own directory before every one of its three reads,
#:   so whatever the file holds never reaches a screen (`docs/216-the-c64-
#:   name-table.md`, read out of the running machine on both titles for
#:   `#435`).  The earlier reading here -- that entry *n* runs in marching
#:   order where the slots run the other way, from the shipped `SAVEDBASH`
#:   against two engine-written Curse saves -- is refuted: an engine
#:   `SAVE CURRENT GAME` after a removal stored a **one**-entry table beside
#:   a five-character party, which no ordering explains.  `#439` is the one
#:   consequence a player can reach, and it runs through the directory rather
#:   than through this block.  CONFIRMED.
SECRET_OF_THE_SILVER_BLADES = C64Container(
    key="secret-of-the-silver-blades",
    title="Secret of the Silver Blades",
    rules=titles.SECRET_OF_THE_SILVER_BLADES,
    save_file=b"SAVEDBASH",
    save_load_address=0x4B00,
    save_size=0x1D00,
    disk_glob="SILVER*.[dD]64",
    races=RACES_SILVER_BLADES,
    class_bits=CLASS_BITS_WITH_PALADIN_RANGER,
    item_names_load_address=NAMES_LOAD_ADDRESS_LATER,
    measured=True,
    party_slots=8,
    record_pages=8,
    name_table=0xC00,
    names_in_marching_order=True,
    item_pages=8,
    picture_buffer=(0x1800, 0x400),
    roster_offset=0x1C00,
    cache_bit7=True,
    disk_hint=0xEE,
    quest_flags=(0x120, 0xE0),
    zeroed=(
        (0x0C3, 2, _SILVER_ZERO), (0x0CC, 26, _SILVER_ZERO),
        (0x0EA, 1,
         "zero: DUNGEON $0B0E stores a byte it has just read out of its own "
         "table here and reads it back at $0B1E, so nothing in the save "
         "reaches that read -- and Pool of Radiance's disk hint is at +$EE "
         "in this title, named by CAMP, GEN and LINKER (#193)"),
        (0x0EB, 3, _SILVER_ZERO),
        (0x0EF, 1, _SILVER_ZERO),
        (0xC80, 0x380,
         "zero: the name table fills the first 128 bytes of its page and the "
         "rest of the page is zero in the shipped save"),
        (0x0F0, 2, _SILVER_ZERO), (0x0F3, 9, _SILVER_ZERO),
        (0x0FC, 1,
         "zero: the two ports disagree about it -- all five DOS Silver "
         "Blades containers on this machine hold 4 and the shipped C64 save "
         "holds 2 -- so it is a loader value each port keeps for itself "
         "rather than a variable the party carries, and Curse's converted "
         "save booted with a zero here (#192, #193)"),
        (0x200, 128, _SILVER_ZERO), (0x2D9, 7, _SILVER_ZERO),
    ),
    copied=(
        (0x0E7, 3,
         "from the DOS save: seventeen of this title's area scripts write "
         "+$E7 and +$E8 at their heads and seven write +$E9, none of the "
         "twenty-two ever reads one, and DUNGEON does -- so the party's own "
         "value crosses rather than a zero (#193)"),
        (0x0FD, 2,
         "from the DOS save: per-area constants four scripts write into +$FD "
         "and fourteen into +$FE, read by DUNGEON and by no script (#193)"),
        (0x100, 0x20,
         "the per-script scratch, from the DOS save: the NEWECL handler "
         "clears it only when the script id changes, so a save taken inside "
         "an area is carrying live scratch its own script reads on the next "
         "step (#192 step 0a, #193)"),
    ),
)

# --- the three whose payload map nobody here has read ----------------------
# Each has its geometry -- file name, load address, size, roster page, disk
# glob, item-name base -- from one shipped pre-generated party, which fixes
# the layout but not the header fields.  Not one carries `measured=True`, so
# `container_for` refuses all three and `CONTAINERS` has no entry for any of
# them, exactly as it did when they had no row in this module at all.  What
# they are here for is the four places that walk every C64 title for its
# *disk*: `automap/paths.py`, `wish/preferences.py`, `wish/window.py` and
# `goldbox/savegame.py`.

CHAMPIONS_OF_KRYNN = C64Container(
    key="champions-of-krynn",
    title="Champions of Krynn",
    rules=titles.CHAMPIONS_OF_KRYNN,
    save_file=b"SAVEDRAGN",
    save_load_address=0x4000,
    save_size=0x1D00,
    roster_offset=0x1C00,
    disk_glob="*[cC]hampions*.[dD]64",
    races=RACES_KRYNN,
    class_bits=CLASS_BITS_KRYNN,
    item_names_load_address=NAMES_LOAD_ADDRESS_LATER,
)

DEATH_KNIGHTS_OF_KRYNN = C64Container(
    key="death-knights-of-krynn",
    title="Death Knights of Krynn",
    rules=titles.DEATH_KNIGHTS_OF_KRYNN,
    save_file=b"SAVEDEATH",
    save_load_address=0x4000,
    save_size=0x1D00,
    roster_offset=0x1C00,
    disk_glob="*[dD]eath*[kK]nights*.[dD]64",
    races=RACES_KRYNN,
    class_bits=CLASS_BITS_KRYNN,
    item_names_load_address=NAMES_LOAD_ADDRESS_LATER,
)

GATEWAY_TO_THE_SAVAGE_FRONTIER = C64Container(
    key="gateway-to-the-savage-frontier",
    title="Gateway to the Savage Frontier",
    rules=titles.GATEWAY_TO_THE_SAVAGE_FRONTIER,
    save_file=b"SAVEGATEWAY",
    save_load_address=0x4B00,
    save_size=0x1D00,
    roster_offset=0x1C00,
    disk_glob="GATE*.[dD]64",
    races=RACES_FORGOTTEN_REALMS,
    class_bits=CLASS_BITS_WITH_PALADIN_RANGER,
    item_names_load_address=NAMES_LOAD_ADDRESS_LATER,
)


#: The titles whose payload map has been measured, and **only** those three.
#: Every caller that reads a header offset, a page address or a zeroing list
#: comes through here or through :func:`container_for`, so a `.get()` that
#: answers None is the refusal rather than an accident.  The whole six are
#: `goldbox.c64_port.GAMES`, in that order.
CONTAINERS: dict[str, C64Container] = {
    c.key: c for c in (POOL_OF_RADIANCE, CURSE_OF_THE_AZURE_BONDS,
                       SECRET_OF_THE_SILVER_BLADES) if c.measured}


def container_for(game=None) -> C64Container:
    """The container for a title, Pool of Radiance's by default.

    Takes a `C64Container`, a key, anything carrying one as `.key`, or None --
    the same shape `goldbox.spells.for_game` takes, so a caller holding any of
    them does not have to convert first.  A title with no measured payload map
    raises: handing back another title's header offsets would be inventing its
    geometry, and an unrecognised key is more likely a typo than a new title.

    **A row is not enough; `measured` is what this asks.**  Champions of
    Krynn, Death Knights of Krynn and Gateway to the Savage Frontier are
    `C64Container`s now -- they were `goldbox.games.Game`s and nothing else
    before `#470`'s stage 7 -- and passing one in raises exactly as passing
    its key always has.  `zeroed == ()` would have served as the discriminator
    today and is not the question being asked: a measured title is allowed an
    empty zeroing list, and Pool of Radiance's `copied` is empty already.
    """
    if isinstance(game, C64Container):
        if game.measured:
            return game
        key = game.key
    else:
        key = getattr(game, "key", game)
    if key is None:
        return POOL_OF_RADIANCE
    try:
        return CONTAINERS[key]
    except KeyError:
        raise KeyError(
            f"no saved-game container measured for {key!r}; "
            f"{', '.join(sorted(CONTAINERS))} are the ones this project has "
            f"read a save of") from None
