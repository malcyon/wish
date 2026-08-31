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

# Every title in the family agrees on these, so they are constants rather than
# fields. The one that is not obvious is the icon table: 8 icons of 36 bytes
# from $2E0 end exactly at $400, the start of the slot area, in both games where
# it has been read.
HEADER_SIZE = 0x400
SLOT_STRIDE = 0x100
ITEM_AREA_OFFSET = 0x1000
ICON_TABLE_OFFSET = 0x2E0
ROSTER_PAGE = 0x100

# --- race codes -------------------------------------------------------------
# The record's race byte at 0x072 indexes a table of names the game itself
# carries, and that table is NOT the same in every title. Each list below was
# read off the player's disks twice over, from two independent places, and then
# checked against the six-character party each title ships inside its own save.
#
# Where the table lives:
#
# * Pool of Radiance, Curse and Gateway keep it in `LIBRARY`, reached through a
#   pointer table the resident code indexes with `LDA table,X / STA $07`. Base
#   $2C48 for Pool of Radiance and $2DC8 for the other two -- fitted, not read,
#   by scoring how many of the 66-odd pointers land on a string start (63 of 66
#   at $2C48 against 14 at the next best).
# * Silver Blades and the two Krynn titles fold the labels into `ITEMNAMES`'s
#   own 256-entry string pool, at pool index `140 + race`.
#
# And what generation offers: `GEN` carries the character-creation menu, and in
# Pool of Radiance, Curse and Gateway it is followed by the six bytes
# `01 02 03 04 05 07` -- the menu-entry-to-race-code map, which is why human is
# 7 in all three even though only six races can be rolled. Silver Blades and
# the Krynn titles have no such array, so their menu order *is* the code order.
#
# CONFIRMED for all six: every one of the 36 shipped pre-generated characters
# decodes to a race its class allows. The decisive ones are the rule cases --
# a paladin or a Knight of Solamnia must be human, a ranger human or half-elf --
# and Champions' TRAPSPRINGER, race 5, who is a kender by name.

#: Pool of Radiance and Gateway to the Savage Frontier, identically.
RACES_FORGOTTEN_REALMS = ((1, "dwarf"), (2, "elf"), (3, "gnome"),
                          (4, "half-elf"), (5, "halfling"), (6, "half-orc"),
                          (7, "human"), (8, "monster"))

#: Curse drops half-orc from generation but keeps human at 7: its label table
#: points BOTH 6 and 7 at HUMAN. 6 is left out here on purpose -- naming it
#: "half-orc" would contradict what the game prints, and naming it "human"
#: would give two codes one name and let an import silently rewrite a 7 as a 6.
#: A Pool of Radiance half-orc carried across shows as a bare `6`, which is the
#: honest answer.
RACES_CURSE = ((1, "dwarf"), (2, "elf"), (3, "gnome"), (4, "half-elf"),
               (5, "halfling"), (7, "human"), (8, "monster"))

#: Silver Blades drops half-orc and re-orders the rest, so human moves to 6.
#: Codes 1-6 are the generation menu in menu order; 0 also prints ELF.
RACES_SILVER_BLADES = ((1, "elf"), (2, "half-elf"), (3, "dwarf"),
                       (4, "gnome"), (5, "halfling"), (6, "human"))

#: Krynn: a different list entirely, and the only one that is **0-based** --
#: Death Knights' CELESTE is race 0, which is why 0 had to be a real race
#: rather than the "monster" it is in the Realms titles.
RACES_KRYNN = ((0, "silvanesti elf"), (1, "qualinesti elf"), (2, "half-elf"),
               (3, "mountain dwarf"), (4, "hill dwarf"), (5, "kender"),
               (6, "human"))

# --- class bits -------------------------------------------------------------
# 0x0EB, one bit per class. The low four are the whole story in Pool of
# Radiance; the later titles add classes above them.
#
# **The bit number is the slot number in the per-class level array**, and that
# array is eight bytes at 0x0C9-0x0D0, not four. Bit 4 is the knight at 0x0CD,
# bit 6 the paladin at 0x0CF, bit 7 the ranger at 0x0D0 -- so
# `class_bits == sum(1 << i for every non-zero slot i)` holds uniformly, on all
# 36 shipped characters in all six titles. It is a cross-title check, not a
# Pool of Radiance quirk, and `tests/test_gametables.py` asserts it.
#
# (An early report, since lost, said the rule fails for the
# 0x10/0x40/0x80 classes. It read only the first four slots of an eight-slot
# array; the levels are in the slots it did not read.)
CLASS_BITS_CLASSIC = ((1, "magic-user"), (2, "cleric"), (4, "thief"),
                      (8, "fighter"))

#: Curse, Silver Blades and Gateway. CONFIRMED for Curse, whose shipped party
#: has two characters literally named PALADIN (0x40) and RANGER (0x80); the
#: same two names sit at the same places in all three titles' label tables.
CLASS_BITS_WITH_PALADIN_RANGER = CLASS_BITS_CLASSIC + ((0x40, "paladin"),
                                                       (0x80, "ranger"))

#: Krynn adds the Knight of Solamnia at 0x10. PROBABLE: Champions' STRONGSWORD
#: and Death Knights' SIR DRYDEN are single-class 0x10, lawful good, and the
#: label pool carries KNIGHT and KNIGHT OF THE ROSE.
CLASS_BITS_KRYNN = CLASS_BITS_CLASSIC + ((0x10, "knight"), (0x40, "paladin"),
                                         (0x80, "ranger"))

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
CLOCK_OFFSET = 0x0C7           # minute units, tens, hour

#: Where the **engine** keeps the party's square while the game runs, which is
#: not where it writes it when the game saves. `$C04B` x, `$C04C` y, `$C04D`
#: facing.
#:
#: MEASURED, three times over, and not inferred from anything:
#:
#: * Pool of Radiance -- `$1A3C` is `if $49E6 then copy $C04B..$C04D into
#:   $49C0..$49C2`, and 29 of its 30 area scripts write it (`docs/118` §);
#: * Curse of the Azure Bonds -- found by intersecting two 64K dumps taken
#:   either side of a step, one candidate left (`docs/120` §4);
#: * Secret of the Silver Blades -- the same triple, confirmed unchanged over
#:   nine steps and three refusals (`docs/121` §5).
#:
#: `docs/138-multiple-games.md` records it as CONFIRMED for those three titles
#: and for no others, which is why the Krynn titles and Gateway leave
#: `live_position` None below.
LIVE_POSITION_GOLDBOX = 0xC04B

#: `LINKER`'s dispatch byte in Pool of Radiance: which overlay is running, and
#: `2` is COMBAT. Outside the save image like `live_position`, and like it a
#: measurement of one title rather than a family constant -- `LINKER` is
#: 136 bytes of resident code at `$2B80`.
#:
#: CONFIRMED: "`$6E11` is the mode flag" in `docs/50-experiments.md` reads the
#: outer loop itself -- `LDA $6E11`, index the overlay name table, load it at
#: `$0800`, call it.
MODE_FLAG_POOL = 0x6E11

#: The same byte in Curse of the Azure Bonds and Secret of the Silver Blades,
#: and it is **not** Pool of Radiance's plus anything the save image moved by:
#: `LINKER` is its own resident, so the flag went `$6E11` -> `$7F11` while the
#: save image went `$4900` -> `$4B00`.
#:
#: Read out of the loader's own first instruction, which is where the address
#: is an absolute operand and so does not depend on where `LINKER` loads:
#: `LINKER` on `CURSE_A.D64` and on `SILVER-1.D64` both begin `AD 11 7F`,
#: `LDA $7F11`, then index a name table of ten entries and `JSR $0800`. **The
#: name table is Pool of Radiance's, entry for entry** -- `GEN`, `DUNGEON`,
#: `COMBAT`, `INIT`, `COM.PREP`, `POST.COM`, two dead slots, `FINAL`, `CAMP` --
#: so `2` is COMBAT in all three titles and `automap.actions.COMBAT` needs no
#: per-title value.
#:
#: CONFIRMED for both, each in its own driven session on pool slot 2. `LINKER`
#: is resident at `$2D00` in both -- byte-identical to the disk copy -- and the
#: flag was sampled across every overlay change the session made: Curse world
#: `1`, camp `9`, world `1`, roster `0`, world `1`; Silver Blades credits `3`
#: `INIT`, roster `0` `GEN`, world `1`, treasure `5` `POST.COM`, world `1`.
#: `LDA #$09 / STA $7F11` sits at `$100E` in Curse's resident `DUNGEON`, where
#: Pool of Radiance's `DUNGEON $10B1` writes `9`.
#:
#: **`2` was sampled live on Silver Blades**, at the end of 228 driven steps:
#: `1` -> `4` `COM.PREP` -> `2` with `MOVE VIEW AIM TURN QUICK DONE` on the
#: command bar, and `identify` refusing because `$7F11` is 2. That is also the
#: first live sighting of `4` in any title. On Curse it was not: no session has
#: reached a fight there, so `2` rests on the dispatch table alone -- which is
#: the same table, so the risk is small and it is written down rather than
#: glossed. `docs/50-experiments.md`, "the later titles' mode flag is `$7F11`";
#: issue #29.
MODE_FLAG_LATER = 0x7F11


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

    #: The engine's live x/y/facing triple. **Not geometry**: it sits outside
    #: the save image, so it cannot be derived from `save_load_address` and has
    #: to be measured on a running machine, one title at a time. None means
    #: nobody has measured this title's -- and a reader must then refuse rather
    #: than fall back to another title's, because a wrong address yields a
    #: plausible square instead of an error.
    live_position: int | None = None

    #: The loader's resident-overlay flag -- the byte an action has to read
    #: before it writes, because `2` is combat and half of them are illegal
    #: there. **Not geometry either**: it is a byte of the loader's own
    #: resident page, not of the save image, so it neither follows
    #: `save_load_address` nor transfers. None means nobody has found this
    #: title's, and every action then refuses: an unmeasured address reads as
    #: "not combat" whatever the machine is doing, which is a gate that is
    #: open rather than a gate that is missing.
    mode_flag: int | None = None

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
        stood on at the last save. `live_position` is the one that moves.
        """
        return self.save_load_address + POSITION_OFFSET

    @property
    def clock_base(self) -> int:
        """The game clock, which *is* live at its save-image address."""
        return self.save_load_address + CLOCK_OFFSET

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
    live_position=LIVE_POSITION_GOLDBOX,
    mode_flag=MODE_FLAG_POOL,
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
    live_position=LIVE_POSITION_GOLDBOX,
    mode_flag=MODE_FLAG_LATER,
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
    live_position=LIVE_POSITION_GOLDBOX,
    mode_flag=MODE_FLAG_LATER,
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
    # live_position and mode_flag stay None: nobody has run this title under
    # a monitor, and $C04B and $6E11 are measurements of other games, not
    # family constants.
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
    # live_position and mode_flag stay None: nobody has run this title under
    # a monitor, and $C04B and $6E11 are measurements of other games, not
    # family constants.
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
    # live_position and mode_flag stay None: nobody has run this title under
    # a monitor, and $C04B and $6E11 are measurements of other games, not
    # family constants.
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


class UnknownGameError(ValueError):
    """Raised when a key names no title we know."""


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


# ---------------------------------------------------------------------------
# The per-title tables, resolved
# ---------------------------------------------------------------------------
# `race`, `char_class` and `class_bits` are *indices into this title's own
# tables* wherever they appear -- in a C64 record, in `goldbox/neutral.py`'s
# vocabulary, in the YAML. Turning one into a name therefore needs the title,
# and every codec needs the same answer. These live here, beside the tables
# themselves, so that a codec asking for a name imports a table module rather
# than another codec: `goldbox/yaml_io.py` and `goldbox/amiga.py` both need this and
# neither may reach for the other.
def race_table(game: "Game | None") -> dict[int, str]:
    """Race code -> name for a title, or Pool of Radiance's.

    Empty when the title's list is unknown, so a caller shows the raw number
    rather than inventing a name for it.
    """
    if game is None:
        return dict(DEFAULT.races or ())
    return game.race_names or {}


def class_table(game: "Game | None") -> list[tuple[int, str]]:
    """The bit -> name pairs for a title, or Pool of Radiance's four.

    A title whose list we do not know gets an empty table, which makes
    :func:`classes_to_names` hand back the raw bitmask rather than a wrong
    name.
    """
    if game is None:
        return list(DEFAULT.class_bits or ())
    return list(game.class_bits or ())


def classes_to_names(bits: int, game: "Game | None" = None) -> list[str]:
    """The classes a bitmask holds, named -- or the mask itself, unnamed."""
    names = [name for bit, name in class_table(game) if bits & bit]
    if not names:                       # unknown encoding: keep it visible
        return [bits]
    return names
