#!/usr/bin/env python3
"""Where each C64 Gold Box title keeps a fight, and one reader for all three.

`automap/combat.py` reads a running fight, and every address in it is Pool of
Radiance's. That is right for the window, which only opens on a title whose
addresses have been measured, and wrong for `tools/c64/session.py`, which is asked
to drive Curse of the Azure Bonds and Secret of the Silver Blades as well: at
Pool of Radiance's addresses a Curse party standing on the combat floor reads
as no fight at all (`#334`).

**`CombatMemory`, `BY_KEY`, `memory_for` and `read_battle` now live in
`automap/combat.py`** -- moved there for `#39 (Combat view and combat log for
Curse and Silver Blades)`, because `automap/`'s own combat window wants the
same per-title table and a second copy of it would drift. This module keeps
its docstring, since the derivation write-up (`#334`) belongs beside the
history that produced it, and re-exports the moved names so nothing that
already imports from here breaks.

**Two of the six addresses are not per-title at all.** The parameter block is
`$0600` and the camera origin `$037E` in all three, which is a reading rather
than an assumption: `GDRIVE00`, the square engine that draws the arena, names
the same twenty absolute addresses `$0600`-`$061B` and the same `$037E`/`$037F`
in the same order and at the same relative code positions in every one of the
three binaries.

Where the parameter block's *contents* come from is the one structural
difference. Pool of Radiance loads them off a `SQRPACI<nn>` file; the later two
ship no such file and their `COM.PREP` writes the block as immediate constants
-- Curse `$1436`-`$147E`, Silver Blades `$14AC`-`$14F4`, identical value for
value. That does not change the reading, because the block is read at run time
in both cases.

Nothing here opens a disk or writes anything. `docs/101-combat-view.md` has
Pool of Radiance's map of a fight; `#334` has where the later two's came from.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from automap.combat import (  # noqa: E402, F401
    BY_KEY,
    CAMERA,
    PARAMS,
    PARAMS_LEN,
    CombatMemory,
    geometry_from_params,
    memory_for,
    read_battle,
)
