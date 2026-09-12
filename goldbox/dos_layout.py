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

# The pre-#470 spellings, under the names the 85 importers of this shim
# still use. They live here rather than in `goldbox/dos_port.py` because
# this file is the one that exists to be deleted, and the old names
# should go with it rather than be left in a permanent module nothing
# asks them of.
from .dos_port import DELTAS as SHAPES  # noqa: F401
from .dos_port import (  # noqa: F401
    DELTAS_BY_KEY,
    FIELDS_BY_NAME_FOR,
    LAYOUTS,
    Confidence,
    Field,
    Kind,
)
from .dos_port import DELTAS_BY_KEY as SHAPES_BY_KEY  # noqa: F401
from .dos_port import DELTAS_BY_SIZE as SHAPES_BY_SIZE  # noqa: F401
from .dos_port import DosDeltas as DosShape  # noqa: F401
from .dos_port import DosDeltasError as DosShapeError  # noqa: F401
from .dos_port import deltas_for as shape_for  # noqa: F401
