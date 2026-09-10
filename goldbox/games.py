"""Shim: this module moved to `goldbox/c64_port.py`.

`#470 (Give the project a neutral title beside its neutral character record,
with one port per platform a title shipped on)`'s stage 5 renamed this file so
the platform is the prefix and the role is the noun, alongside
`goldbox/dos_port.py` and `goldbox/amiga_port.py`. Nothing inside it changed --
`Game` is still `Game`, and `GAMES`, `BY_KEY`, `BY_SAVE_FILE`, `BY_TITLE`,
`by_title`, `by_key`, `detect`, `detect_from_names` and `DEFAULT` all kept
their names. `Game` becomes `C64Container` in stage 7, once
`goldbox/dos_savegame.py`'s `DosContainer` has a sibling to be renamed to
match.

Every name is re-exported here, so nothing importing this module has to
change before stage 9 takes the callers off and deletes it.

**Import `goldbox.c64_port` in anything new.** This module exists to keep 145
existing importers working until stage 9 moves them; it is not a place to add
a 146th.
"""

from __future__ import annotations

from .c64_port import *  # noqa: F401,F403
