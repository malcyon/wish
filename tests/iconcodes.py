"""The set of icons the game's ICON menu can make, computed once per process.

`IconParts.legal_screen_codes` explores every menu sequence and takes several
seconds for the full set, so every test that needs it shares one result rather
than building its own.
"""

import functools

from gamedata import game_file

from goldbox.iconparts import IconParts


def fresh_parts() -> IconParts:
    """The option tables, read off the player's character-creation disk."""
    return IconParts(game_file("SPELLE64"), game_file("SPELLN64"))


@functools.lru_cache(maxsize=None)
def legal_screen_codes(
        sizes: tuple[str, ...] = ("small", "large")) -> frozenset[bytes]:
    """`IconParts.legal_screen_codes(sizes)`, frozen so no caller can change
    what the next one sees. A missing disk raises the skip and is not cached."""
    return frozenset(fresh_parts().legal_screen_codes(sizes))
