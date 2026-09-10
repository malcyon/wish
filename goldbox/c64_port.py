"""Which Gold Box title a save came from, as data rather than as code.

Six C64 titles share one engine and one 580-byte character record. What differs
between them is a handful of *numbers* -- the save file's name, where it loads,
and whether the party roster is a second file or the last page of the first --
so this module is a table, not a class hierarchy.

**Pool of Radiance is the outlier.** It writes two files, `SAVEDGAME0` at
`$4900` and `SAVEDGAME1` at `$8300`, and keeps the roster in the second. Every
later title writes **one** file of exactly 7426 bytes: a `$1D00` payload of
header `$400`, twelve `$100` character slots, twelve `$100` item pages, and a
final `$100` page that is Pool of Radiance's roster folded in. Measured on the
player's own disks for Curse, Silver Blades, Champions of Krynn, Death Knights
of Krynn and Gateway to the Savage Frontier. The write-up,
`work/reports/goldbox-inventory.md`, is lost; the per-title base addresses are
asserted in `tests/test_curse.py::test_the_addresses_are_the_ones_measured`.

**The offsets inside the payload are identical in all six.** Items at `$1000`,
the combat-icon table at `$2E0`, the slot area at `$400`, the position triple at
`$C0`, the loaded-file cache and area byte at `$2C0`. Only the base moves, which
is why nothing here is a subclass and why `goldbox/items.py`, `goldbox/icons.py` and
`editor/inventory.py` -- all of which work in payload offsets -- needed no
change at all.

Confidence: Pool of Radiance and Curse are CONFIRMED (saves written by both
games round-trip byte-identically). The other four have their geometry from one
shipped pre-generated party each, which fixes the layout but not the header
fields; no player save of them has ever been read here.
"""

from __future__ import annotations

from dataclasses import dataclass

# The races and class bits a title's own rules define now live in
# `goldbox/titles.py`, as `Title.races` and `Title.class_bits` -- a fact about
# the title rather than about the C64 disk -- and are imported back here so
# that a `Game` row's tuple is the very same object as its `Title`'s
# (`#470 (Give the project a neutral title beside its neutral character
# record, with one port per platform a title shipped on)`, stage 1). Every
# name below is re-exported so nothing that imported it from here has to
# change.
from .titles import (  # noqa: F401
    CLASS_BITS_CLASSIC,
    CLASS_BITS_KRYNN,
    CLASS_BITS_WITH_PALADIN_RANGER,
    RACES_CURSE,
    RACES_FORGOTTEN_REALMS,
    RACES_KRYNN,
    RACES_SILVER_BLADES,
    class_table,
    classes_to_names,
    race_table,
)
from .titles import (
    UnknownTitleError as UnknownGameError,
)

# Every title in the family agrees on these, so they are constants rather than
# fields. The one that is not obvious is the icon table: 8 icons of 36 bytes
# from $2E0 end exactly at $400, the start of the slot area, in both games where
# it has been read.
HEADER_SIZE = 0x400
SLOT_STRIDE = 0x100
ITEM_AREA_OFFSET = 0x1000
ICON_TABLE_OFFSET = 0x2E0
ROSTER_PAGE = 0x100

# --- item names -------------------------------------------------------------
# `ITEMNAMES` is 256 low bytes, 256 high bytes, then the strings, and the
# pointers are ABSOLUTE, so the file is unreadable without its load address --
# which is not the one in its PRG header ($3000 on Curse, $1517 on Gateway).
# Each value below is fitted: it is the only base at which entry 1 lands on
# "BATTLE AXE", the first string, at payload offset $201 in all six titles.
NAMES_LOAD_ADDRESS_POOL = 0x6F00
NAMES_LOAD_ADDRESS_LATER = 0x9E00

# --- payload offsets a running machine needs --------------------------------
# Both are inside the save image, so both follow `save_load_address` and
# neither is a per-title field.
POSITION_OFFSET = 0x0C0        # x, y, facing -- the copy the game *saves*

# The three digits of the clock the status line draws -- minute units, tens,
# hour -- which are the second, third and fourth of the six one-byte digits
# `goldbox.c64_save.Container.clock` starts at `+$C6`. The first is a
# sub-minute tick nothing ever prints, which is why the two constants sit a
# byte apart: `automap.target` folds three bytes as `c[2] * 60 + c[1] * 10 +
# c[0]`, and at `+$C6` that is minute tens times sixty. Read out of the tick
# loop and the status-line printer in all three titles by `tools/c64clock.py`
# (`docs/30-savegame-layout.md`); the name says which of the two facts it is,
# which is what `#470` renamed it for.
SHOWN_CLOCK_OFFSET = 0x0C7

#: Pre-#470 name, kept so nothing importing it breaks before stage 9. `#470
#: (Give the project a neutral title beside its neutral character record, with
#: one port per platform a title shipped on)`.
CLOCK_OFFSET = SHOWN_CLOCK_OFFSET

# The travel grid's own two facts, both inside the save image and both
# Pool of Radiance measurements (`docs/113-world-map.md`, `docs/118-debug-mode.md`,
# `docs/140-loaded-files-cache.md`). `$49E6` is non-zero in a `GEO` area and
# zero on the grid; `$49C3`/`$49C4` is the window-local square out there, x
# then y, and it is not consulted unless the flag says to.
INDOORS_FLAG_OFFSET = 0x0E6
TRAVEL_POSITION_OFFSET = 0x0C3

# --- the addresses that are not in the save image ----------------------------
# `LIVE_POSITION_GOLDBOX`, `MODE_FLAG_POOL` and `MODE_FLAG_LATER` moved to
# `automap/c64.py`, with the measurements behind each of them, when `#470
# (Give the project a neutral title beside its neutral character record, with
# one port per platform a title shipped on)`'s stage 6 gave the C64 a
# `C64Machine` beside the Amiga's `AmigaMachine`. They are addresses in a
# *running* game rather than offsets into a save file, and a running machine is
# `automap/`'s.
#
# **No alias is left behind for them here, and that is forced rather than
# chosen.** Every other rename in this ticket leaves the old name working; this
# one cannot, because the alias would have to import `automap` and
# `tests/test_wish.py::test_goldbox_imports_no_transport` forbids that -- it is
# what keeps `editor/`'s promise that it never talks to an emulator. So the
# callers moved in the same commit instead, which is the shape stage 4c already
# used for a renamed parameter: one commit is one revert.


@dataclass(frozen=True)
class Game:
    """One title's save-container geometry.

    `roster_file` is the whole difference between the two shapes. When it is
    None the roster is `roster_offset` bytes into the main payload; when it is
    set the roster is that separate file, and `roster_offset` is an offset
    within *it*.

    `races`, `class_bits` and `item_names_load_address` are the three things
    that are per-title *content* rather than per-title geometry. Each may be
    None, and None means "we do not know", not "there are none": a caller that
    gets None must show the raw number rather than invent a name for it.
    """

    key: str                       # stable identifier, written into the YAML
    title: str                     # what a person calls it
    save_file: bytes               # the payload file's directory name
    save_load_address: int
    save_size: int                 # payload, excluding the 2-byte PRG header
    roster_file: bytes | None = None
    roster_load_address: int | None = None
    roster_size: int = ROSTER_PAGE
    roster_offset: int = 0
    slot_count: int = 8            # the party; slots 8-11 are combat scratch
    record_slot_count: int = 12
    disk_glob: str = "*.[dD]64"

    # Pairs rather than dicts so the descriptor stays hashable and frozen.
    races: tuple[tuple[int, str], ...] | None = None
    class_bits: tuple[tuple[int, str], ...] | None = None
    item_names_load_address: int | None = None

    # -- moved to `automap.c64.C64Machine` by `#470`'s stage 6 -------------
    # `live_position` and `mode_flag` were fields here. Both are addresses in
    # a running game rather than offsets into a save file, so both are now
    # `C64Machine`'s -- and neither can be left as a read-through, because a
    # read-through would import `automap` from `goldbox` and
    # `tests/test_wish.py::test_goldbox_imports_no_transport` forbids it. Ask
    # `automap.c64.machine_for(game)` for either.

    @property
    def travel_grid(self) -> bool:
        """`goldbox.titles.Title.travel_grid` under its pre-#470 name.

        Does this title have a square-engine overland at all? **True for Pool
        of Radiance only.** It is a fact about the title's own rules rather
        than about a C64 disk, which is why `#470`'s stage 6 moved it to
        `Title`; this stays as a read-through until stage 9 deletes it. A
        `Game` whose key `goldbox/titles.py` does not know answers False,
        which is what an unregistered row answered when this was a field.
        """
        from .titles import BY_KEY
        found = BY_KEY.get(self.key)
        return bool(found is not None and found.travel_grid)

    # -- derived ----------------------------------------------------------
    @property
    def race_names(self) -> dict[int, str] | None:
        """Race code -> name, or None when this title's list is unknown."""
        return None if self.races is None else dict(self.races)

    @property
    def class_bit_names(self) -> dict[int, str] | None:
        """Class bit -> name, or None when this title's list is unknown."""
        return None if self.class_bits is None else dict(self.class_bits)

    @property
    def files(self) -> tuple[bytes, ...]:
        """Every directory entry that makes up a save."""
        if self.roster_file is None:
            return (self.save_file,)
        return (self.save_file, self.roster_file)

    @property
    def roster_in_payload(self) -> bool:
        return self.roster_file is None

    @property
    def save_prg_size(self) -> int:
        """What the file measures on disk, load address included."""
        return self.save_size + 2

    # -- the save image's regions, live ------------------------------------
    # `automap.c64.C64Machine` computes each of these as well, from
    # `goldbox.c64_save.Container`'s own offsets rather than from the module
    # constants above, and `tests/test_c64machine.py` pins that the two agree
    # for all six titles. They are duplicated for exactly one stage: these are
    # what `goldbox/savegame.py` reads, `goldbox/` may not import `automap`,
    # and `#470`'s stage 7 is where `C64Container` absorbs them.

    @property
    def slot_area_base(self) -> int:
        return self.save_load_address + HEADER_SIZE

    @property
    def item_area_base(self) -> int:
        return self.save_load_address + ITEM_AREA_OFFSET

    @property
    def icon_table_base(self) -> int:
        return self.save_load_address + ICON_TABLE_OFFSET

    @property
    def save_position_base(self) -> int:
        """The save image's own copy of the party square.

        Refreshed only when the game saves, so it names the square the party
        stood on at the last save. `C64Machine.live_position` is the one that
        moves.
        """
        return self.save_load_address + POSITION_OFFSET

    @property
    def clock_base(self) -> int:
        """The three clock digits the status line draws, live.

        `C64Machine.shown_clock_base` under its pre-#470 name -- and it is
        **not** the whole clock, which is six digits from
        `goldbox.c64_save.Container.clock` at `+$C6`. See
        `SHOWN_CLOCK_OFFSET` above.
        """
        return self.save_load_address + SHOWN_CLOCK_OFFSET

    @property
    def indoors_flag_base(self) -> int | None:
        """`$49E6`: zero on the travel grid, non-zero in a `GEO` area.

        None unless `travel_grid`, the same refusal `C64Machine.live_position`
        makes for the same reason: reading this on a title with no travel grid
        would answer a byte of unrelated resident code as though it meant
        something.
        """
        return (self.save_load_address + INDOORS_FLAG_OFFSET
                if self.travel_grid else None)

    @property
    def travel_position_base(self) -> int | None:
        """`$49C3`/`$49C4`: the window-local travel-grid square, x then y.

        None unless `travel_grid`, for the same reason as `indoors_flag_base`.
        """
        return (self.save_load_address + TRAVEL_POSITION_OFFSET
                if self.travel_grid else None)

    @property
    def roster_base(self) -> int:
        """The roster's live address, wherever it lives."""
        if self.roster_file is None:
            return self.save_load_address + self.roster_offset
        return self.roster_load_address + self.roster_offset

    def matches_payload(self, prg: bytes) -> bool:
        """Does this PRG look like this title's save? Size and load address.

        A corroborator, not the discriminator -- Curse's own side B carries a
        2032-byte `SAVEAZURE` that is a truncated demo party, and this is how
        that is told from the real thing.
        """
        return (len(prg) == self.save_prg_size
                and len(prg) >= 2
                and prg[0] | (prg[1] << 8) == self.save_load_address)


POOL_OF_RADIANCE = Game(
    key="pool-of-radiance",
    title="Pool of Radiance",
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
)

CURSE_OF_THE_AZURE_BONDS = Game(
    key="curse-of-the-azure-bonds",
    title="Curse of the Azure Bonds",
    save_file=b"SAVEAZURE",
    save_load_address=0x4B00,
    save_size=0x1D00,
    roster_offset=0x1C00,
    disk_glob="CURSE*.[dD]64",
    races=RACES_CURSE,
    class_bits=CLASS_BITS_WITH_PALADIN_RANGER,
    item_names_load_address=NAMES_LOAD_ADDRESS_LATER,
)

SECRET_OF_THE_SILVER_BLADES = Game(
    key="secret-of-the-silver-blades",
    title="Secret of the Silver Blades",
    save_file=b"SAVEDBASH",
    save_load_address=0x4B00,
    save_size=0x1D00,
    roster_offset=0x1C00,
    disk_glob="SILVER*.[dD]64",
    races=RACES_SILVER_BLADES,
    class_bits=CLASS_BITS_WITH_PALADIN_RANGER,
    item_names_load_address=NAMES_LOAD_ADDRESS_LATER,
)

CHAMPIONS_OF_KRYNN = Game(
    key="champions-of-krynn",
    title="Champions of Krynn",
    save_file=b"SAVEDRAGN",
    save_load_address=0x4000,
    save_size=0x1D00,
    roster_offset=0x1C00,
    disk_glob="*[cC]hampions*.[dD]64",
    races=RACES_KRYNN,
    class_bits=CLASS_BITS_KRYNN,
    item_names_load_address=NAMES_LOAD_ADDRESS_LATER,
)

DEATH_KNIGHTS_OF_KRYNN = Game(
    key="death-knights-of-krynn",
    title="Death Knights of Krynn",
    save_file=b"SAVEDEATH",
    save_load_address=0x4000,
    save_size=0x1D00,
    roster_offset=0x1C00,
    disk_glob="*[dD]eath*[kK]nights*.[dD]64",
    races=RACES_KRYNN,
    class_bits=CLASS_BITS_KRYNN,
    item_names_load_address=NAMES_LOAD_ADDRESS_LATER,
)

GATEWAY_TO_THE_SAVAGE_FRONTIER = Game(
    key="gateway-to-the-savage-frontier",
    title="Gateway to the Savage Frontier",
    save_file=b"SAVEGATEWAY",
    save_load_address=0x4B00,
    save_size=0x1D00,
    roster_offset=0x1C00,
    disk_glob="GATE*.[dD]64",
    races=RACES_FORGOTTEN_REALMS,
    class_bits=CLASS_BITS_WITH_PALADIN_RANGER,
    item_names_load_address=NAMES_LOAD_ADDRESS_LATER,
)

GAMES: tuple[Game, ...] = (
    POOL_OF_RADIANCE,
    CURSE_OF_THE_AZURE_BONDS,
    SECRET_OF_THE_SILVER_BLADES,
    CHAMPIONS_OF_KRYNN,
    DEATH_KNIGHTS_OF_KRYNN,
    GATEWAY_TO_THE_SAVAGE_FRONTIER,
)

#: What a caller gets when nothing says otherwise. Pool of Radiance, because
#: every existing caller predates this module and means it.
DEFAULT = POOL_OF_RADIANCE

BY_KEY = {g.key: g for g in GAMES}
BY_SAVE_FILE = {g.save_file: g for g in GAMES}
BY_TITLE = {g.title: g for g in GAMES}


def by_title(title: str | None) -> Game | None:
    """The title a person named, or None. Never falls back to a default.

    The windows carry the game as a plain string -- see `AutomapState.title` --
    and this is the one place that turns it back into a descriptor. None for an
    unrecognised name on purpose: a caller that needs an address has to notice
    it does not have one.
    """
    return BY_TITLE.get(title) if title else None


def by_key(key: str) -> Game:
    try:
        return BY_KEY[key]
    except KeyError:
        raise UnknownGameError(
            f"{key!r} is not a title this tool knows. "
            f"Try one of: {', '.join(sorted(BY_KEY))}") from None


def detect_from_names(names) -> Game | None:
    """The title whose save file appears in a directory listing, or None.

    The save file's name is the discriminator: no two titles share one, and no
    disk carries two. Deliberately name-only -- a truncated or absent payload is
    a *loading* error with a message worth reading, not a reason to guess a
    different game.
    """
    wanted = {bytes(n) for n in names}
    for game in GAMES:
        if game.save_file in wanted:
            return game
    return None


def detect(disk, default: Game | None = None) -> Game | None:
    """The title a D64 holds a save for, or `default`."""
    found = detect_from_names(e.name for e in disk.directory())
    return found if found is not None else default
