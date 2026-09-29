"""Which Gold Box title a C64 save came from: the registry, and the lookups.

Six C64 titles share one engine and one 580-byte character record. What
differs between them is a handful of *numbers* -- the save file's name, where
it loads, and whether the party roster is a second file or the last page of
the first -- so the descriptor is a table, not a class hierarchy.

**The table itself is `goldbox/c64_save.py`.** `#470 (Give the project a
neutral title beside its neutral character record, with one port per platform
a title shipped on)`'s stage 7 merged this module's `Game` into that module's
`C64Container`, because a reader asking *"where does this save load?"* and
*"what is at `+$C7`?"* was going to two different classes about one file and
each kept its own copy of the same offsets.

What is left here is the registry -- the six rows in order, the three lookup
dictionaries, and `detect`, which is how a disk in a drive turns into a title.
`wish/preferences.py` takes `list(GAMES)[:2]`, so Pool of Radiance and Curse
of the Azure Bonds stay first.
"""

from __future__ import annotations

from .c64_save import (
    CHAMPIONS_OF_KRYNN,
    CURSE_OF_THE_AZURE_BONDS,
    DEATH_KNIGHTS_OF_KRYNN,
    GATEWAY_TO_THE_SAVAGE_FRONTIER,
    POOL_OF_RADIANCE,
    SECRET_OF_THE_SILVER_BLADES,
    C64Container,
)
from .titles import UnknownTitleError

GAMES: tuple[C64Container, ...] = (
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
#: The reverse of `C64Container.roster_prefix`, for the three titles that have
#: one measured. A disk's directory names a title this way when it carries no
#: save game at all -- see `detect_from_roster`.
BY_ROSTER_PREFIX = {g.roster_prefix: g for g in GAMES if g.roster_prefix is not None}


def by_title(title: str | None) -> C64Container | None:
    """The title a person named, or None. Never falls back to a default.

    The windows carry the game as a plain string -- see `AutomapState.title` --
    and this is the one place that turns it back into a descriptor. None for an
    unrecognised name on purpose: a caller that needs an address has to notice
    it does not have one.
    """
    return BY_TITLE.get(title) if title else None


def by_key(key: str) -> C64Container:
    try:
        return BY_KEY[key]
    except KeyError:
        raise UnknownTitleError(
            f"{key!r} is not a title this tool knows. "
            f"Try one of: {', '.join(sorted(BY_KEY))}") from None


def detect_from_names(names) -> C64Container | None:
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


def detect(disk, default: C64Container | None = None) -> C64Container | None:
    """The title a D64 holds a save for, or `default`."""
    found = detect_from_names(e.name for e in disk.directory())
    return found if found is not None else default


def title_of_roster_file(name) -> C64Container | None:
    """The title whose prefix byte stands in front of this filename, or None.

    `name` is a parked character's own directory name -- byte 0 is the prefix
    `GEN` writes there, byte 1 on is the name itself.  Bytes and a `str` both
    work, matching what `DirEntry.name` and `entry.name` already hand back
    elsewhere in this file.
    """
    if isinstance(name, str):
        if not name:
            return None
        key = ord(name[0])
    else:
        name = bytes(name)
        if not name:
            return None
        key = name[0]
    return BY_ROSTER_PREFIX.get(key)


def detect_from_roster(disk) -> C64Container | None:
    """The one title every parked character file on this disk names.

    None when the disk carries none, and None when they disagree -- a
    disagreement is `ADD CHARACTER TO PARTY` having reached across titles, not
    a reason to guess one of them.  Matches on the filename alone, the same
    test the engine's own `ADD FROM:` directory scan makes
    (`docs/216-the-c64-name-table.md`), not on the file's contents.
    """
    found = {title_of_roster_file(e.name) for e in disk.directory()
             if e.is_prg and not e.is_empty}
    found.discard(None)
    if len(found) == 1:
        return next(iter(found))
    return None
