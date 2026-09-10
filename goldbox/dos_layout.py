"""Shim: this module moved to `goldbox/dos_port.py`.

`#470 (Give the project a neutral title beside its neutral character record,
with one port per platform a title shipped on)`'s stage 3 renamed this file
so the platform is the prefix and the role is the noun, alongside
`goldbox/c64_codec.py`. `DosShape` became `DosDeltas`, `DosShapeError`
became `DosDeltasError`, and `shape_for` became `deltas_for` -- all three
old names are re-exported here too, so nothing importing this module has to
change before stage 9 takes the callers off and deletes it.

**Import `goldbox.dos_port` in anything new.** This module is 81 importers'
worth of history, not a place to add a tenth-first.
"""

from __future__ import annotations

from .dos_port import *  # noqa: F401,F403
from .dos_port import (  # noqa: F401
    FIELDS_BY_NAME_FOR,
    LAYOUTS,
    SHAPES_BY_KEY,
    Confidence,
    Field,
    Kind,
)
