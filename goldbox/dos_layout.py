"""Shim: this module moved to `goldbox/dos_port.py`.

`#470 (Give the project a neutral title beside its neutral character record,
with one port per platform a title shipped on)`'s stage 3 renamed this file
so the platform is the prefix and the role is the noun, alongside
`goldbox/c64_codec.py`. `DosShape` became `DosDeltas`, `DosShapeError`
became `DosDeltasError`, and `shape_for` became `deltas_for`. Stage 3b
finished the registries the same way: `SHAPES`, `SHAPES_BY_KEY` and
`SHAPES_BY_SIZE` became `DELTAS`, `DELTAS_BY_KEY` and `DELTAS_BY_SIZE`. Every
old name is re-exported here too, so nothing importing this module has to
change before stage 9 takes the callers off and deletes it.

**Import `goldbox.dos_port` in anything new.** This module exists to keep 81
existing importers working until stage 9 moves them; it is not a place to add
an eighty-second.
"""

from __future__ import annotations

from .dos_port import *  # noqa: F401,F403
from .dos_port import (  # noqa: F401
    DELTAS_BY_KEY,
    FIELDS_BY_NAME_FOR,
    LAYOUTS,
    SHAPES_BY_KEY,
    Confidence,
    Field,
    Kind,
)
