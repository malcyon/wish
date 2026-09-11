"""Shim: this module moved to `goldbox/amiga_codec.py`.

`#470 (Give the project a neutral title beside its neutral character record,
with one port per platform a title shipped on)`'s stage 8 renamed this file so
the platform is the prefix and the role is the noun, beside
`goldbox/c64_codec.py` and `goldbox/dos_codec.py`. Nothing inside it changed:
every class, constant and function kept its name, and `AmigaDeltas` still
lives next door in `goldbox/amiga_port.py` and is re-exported from the codec
as stage 4b left it.

**Stage 10 then split that module by title**, so what stands behind this shim
is `goldbox/amiga_pod.py`, `goldbox/amiga_por.py`, `goldbox/amiga_later.py`
and `goldbox/amiga_shared.py`, with `goldbox/amiga_codec.py` a shim of its own
in front of them. Five names went in that stage rather than moving --
`DROPPED`, `DIRECT`, `TRANSFORMED`, `field_disposition` and `write`, every one
of them the Pools of Darkness writer's alone -- so this module no longer
answers to any of the five. `goldbox/amiga_codec.py`'s docstring names what
each became.

**`goldbox/amiga_codec.py` declares no `__all__`**, so the wildcard below
carries all 303 of its public names, including the ones it imports from
elsewhere and re-exports -- `AmigaDeltas`, `CURSE_DELTAS` and the rest. What a
wildcard never carries is an underscore name, and the tests reach 22 of them
here, so those are listed by hand. All 325 module-level names were checked by
identity: `goldbox.amiga.X is goldbox.amiga_codec.X`.

**Import `goldbox.amiga_codec` in anything new.** This module exists to keep
the existing importers working until stage 9 moves them; it is not a place to
add another.
"""

from __future__ import annotations

from .amiga_codec import *  # noqa: F401,F403
from .amiga_codec import (  # noqa: F401  a wildcard carries no underscore name
    _DISAMBIGUATING_DIGITS,
    _POR_SPECIAL,
    _SOURCE_OF,
    _all_or_nothing,
    _amiga_block,
    _amiga_por_name,
    _chain_bytes,
    _class_names,
    _classes_of,
    _later_effect_nodes,
    _later_name_bytes,
    _later_spellbook_bytes,
    _name,
    _por_name_bytes,
    _por_note_word,
    _por_slot_file,
    _por_slot_letter,
    _por_special,
    _races,
    _remove_if_there,
    _sibling_bytes,
    _unique_pc_filename,
)
