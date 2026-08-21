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
of Krynn and Gateway to the Savage Frontier; see
`work/reports/goldbox-inventory.md`.

**The offsets inside the payload are identical in all six.** Items at `$1000`,
the combat-icon table at `$2E0`, the slot area at `$400`, the position triple at
`$C0`, the loaded-file cache and area byte at `$2C0`. Only the base moves, which
is why nothing here is a subclass and why `por/items.py`, `por/icons.py` and
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


@dataclass(frozen=True)
class Game:
    """One title's save-container geometry.

    `roster_file` is the whole difference between the two shapes. When it is
    None the roster is `roster_offset` bytes into the main payload; when it is
    set the roster is that separate file, and `roster_offset` is an offset
    within *it*.
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

    # -- derived ----------------------------------------------------------
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
)

CURSE_OF_THE_AZURE_BONDS = Game(
    key="curse-of-the-azure-bonds",
    title="Curse of the Azure Bonds",
    save_file=b"SAVEAZURE",
    save_load_address=0x4B00,
    save_size=0x1D00,
    roster_offset=0x1C00,
    disk_glob="CURSE*.[dD]64",
)

SECRET_OF_THE_SILVER_BLADES = Game(
    key="secret-of-the-silver-blades",
    title="Secret of the Silver Blades",
    save_file=b"SAVEDBASH",
    save_load_address=0x4B00,
    save_size=0x1D00,
    roster_offset=0x1C00,
    disk_glob="SILVER*.[dD]64",
)

CHAMPIONS_OF_KRYNN = Game(
    key="champions-of-krynn",
    title="Champions of Krynn",
    save_file=b"SAVEDRAGN",
    save_load_address=0x4000,
    save_size=0x1D00,
    roster_offset=0x1C00,
    disk_glob="*[cC]hampions*.[dD]64",
)

DEATH_KNIGHTS_OF_KRYNN = Game(
    key="death-knights-of-krynn",
    title="Death Knights of Krynn",
    save_file=b"SAVEDEATH",
    save_load_address=0x4000,
    save_size=0x1D00,
    roster_offset=0x1C00,
    disk_glob="*[dD]eath*[kK]nights*.[dD]64",
)

GATEWAY_TO_THE_SAVAGE_FRONTIER = Game(
    key="gateway-to-the-savage-frontier",
    title="Gateway to the Savage Frontier",
    save_file=b"SAVEGATEWAY",
    save_load_address=0x4B00,
    save_size=0x1D00,
    roster_offset=0x1C00,
    disk_glob="GATE*.[dD]64",
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
