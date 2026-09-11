"""Shim: this module split by title into four.

`#470 (Give the project a neutral title beside its neutral character record,
with one port per platform a title shipped on)`'s stage 10 took the 5,770 lines
that were here and put each title's own code in its own file, because Donald
read a drop census that reported one title's list as another's and asked for
*"clear separation between platforms and titles"*:

| file | what is in it |
|---|---|
| `goldbox/amiga_pod.py` | Pools of Darkness' `Save/NAME.pc` |
| `goldbox/amiga_por.py` | Pool of Radiance's record, save slot and disk |
| `goldbox/amiga_later.py` | Curse of the Azure Bonds and Secret of the Silver Blades |
| `goldbox/amiga_shared.py` | what more than one of them needs, and no title fact |

**Five names are gone rather than moved**, and they are what the stage was
asked to remove: `DROPPED`, `DIRECT`, `TRANSFORMED`, `field_disposition` and
`write` all read as the Amiga's and were **Pools of Darkness'** alone.  They
are `POD_WRITE_DROPPED`, `POD_WRITE_DIRECT`, `POD_WRITE_TRANSFORMED`,
`pod_write_field_disposition` and `write_pod` in `goldbox/amiga_pod.py`.  No
alias is left for any of them: the unprefixed spelling is the defect, it had
already put a false number in front of a reader, and three test files were its
only callers.

**Everything else answers here unchanged.** None of the four modules declares
an `__all__`, so the wildcards below carry all of their public names; what a
wildcard never carries is an underscore name, and the tests reach 22 of those,
so each is listed by hand.  Every module-level name was checked by identity
against the file as it stood before the split.

**Import the module the name lives in for anything new.** This shim exists to
keep the existing importers working until `#470`'s stage 9 moves them; it is
not a place to add another.
"""

from __future__ import annotations

from .amiga_later import *  # noqa: F401,F403
from .amiga_later import (  # noqa: F401  a wildcard carries no underscore name
    _amiga_block,
    _chain_bytes,
    _later_effect_nodes,
    _later_name_bytes,
    _later_spellbook_bytes,
)
from .amiga_pod import *  # noqa: F401,F403
from .amiga_pod import (  # noqa: F401  a wildcard carries no underscore name
    _DISAMBIGUATING_DIGITS,
    _SOURCE_OF,
    _class_names,
    _classes_of,
    _races,
    _unique_pc_filename,
)
from .amiga_por import *  # noqa: F401,F403
from .amiga_por import (  # noqa: F401  a wildcard carries no underscore name
    _POR_SPECIAL,
    _all_or_nothing,
    _amiga_por_name,
    _por_name_bytes,
    _por_note_word,
    _por_slot_file,
    _por_slot_letter,
    _por_special,
    _remove_if_there,
    _sibling_bytes,
)
from .amiga_shared import *  # noqa: F401,F403
from .amiga_shared import _name  # noqa: F401  a wildcard carries no underscore
