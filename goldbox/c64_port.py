"""Which Gold Box title a C64 save came from: the registry, and the lookups.

Six C64 titles share one engine and one 580-byte character record. What
differs between them is a handful of *numbers* -- the save file's name, where
it loads, and whether the party roster is a second file or the last page of
the first -- so the descriptor is a table, not a class hierarchy.

**The table itself is `goldbox/c64_save.py`.** `#470 (Give the project a
neutral title beside its neutral character record, with one port per platform
a title shipped on)`'s stage 7 merged this module's `Game` into that module's
`Container`, because a reader asking *"where does this save load?"* and
*"what is at `+$C7`?"* was going to two different classes about one file and
each kept its own copy of the same offsets. `Game` is `C64Container` under its
old name, and stays one until stage 9 moves the callers off it.

What is left here is the registry -- the six rows in order, the three lookup
dictionaries, and `detect`, which is how a disk in a drive turns into a title.
`wish/preferences.py` takes `list(GAMES)[:2]`, so Pool of Radiance and Curse
of the Azure Bonds stay first.
"""

from __future__ import annotations

# The save container's geometry, its payload map and the offsets they share
# now live in `goldbox/c64_save.py`. Every name below is re-exported so that
# nothing importing it from here -- or from the `goldbox/games.py` shim, which
# wildcards this module -- has to change before stage 9.
from .c64_save import (  # noqa: F401
    CHAMPIONS_OF_KRYNN,
    CLOCK_OFFSET,
    CURSE_OF_THE_AZURE_BONDS,
    DEATH_KNIGHTS_OF_KRYNN,
    GATEWAY_TO_THE_SAVAGE_FRONTIER,
    HEADER_SIZE,
    ICON_TABLE_OFFSET,
    INDOORS_FLAG_OFFSET,
    ITEM_AREA_OFFSET,
    NAMES_LOAD_ADDRESS_LATER,
    NAMES_LOAD_ADDRESS_POOL,
    POOL_OF_RADIANCE,
    POSITION_OFFSET,
    ROSTER_PAGE,
    SECRET_OF_THE_SILVER_BLADES,
    SHOWN_CLOCK_OFFSET,
    SLOT_STRIDE,
    TRAVEL_POSITION_OFFSET,
    C64Container,
)

# The races and class bits a title's own rules define live in
# `goldbox/titles.py`, as `Title.races` and `Title.class_bits` -- a fact about
# the title rather than about the C64 disk -- and are imported back here so
# that nothing that reached them through this module has to change
# (`#470`, stage 1).
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

#: `goldbox.c64_save.C64Container` under the name it carried while the disk
#: geometry and the payload map were two classes. Stage 9 deletes the alias.
Game = C64Container


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
