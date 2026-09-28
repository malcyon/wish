"""`amigaporslot.import_slot`: the character-file selection regex.

Built for #664 (Save As and File > Convert refuse a Pool of Radiance party
with a companion to the Amiga, because the Amiga writers stop at six
characters), whose 2026-09-28 comment found `import_slot` still capping the
files it copies at six even after `PARTY_MAX` was widened to eight.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from support.amigarecords import sample, synthetic_savegame  # noqa: E402

from goldbox import amiga_savegame  # noqa: E402
from tools.amiga import amigaporslot  # noqa: E402


def _por_disk(letter: str, count: int):
    characters = [sample(name=f"MEMBER{n}") for n in range(1, count + 1)]
    return amiga_savegame.make_por_save_disk(letter, characters, synthetic_savegame(letter))


def test_import_slot_copies_every_member_of_a_seven_character_party():
    source = _por_disk("A", 7)
    dest = _por_disk("B", 1)

    amigaporslot.import_slot(dest, "B", source, "A")

    names = {entry.name.upper() for entry in dest.entries() if not entry.is_dir
             and entry.name.upper().startswith("CHRDATB") and entry.name.upper().endswith(".SAV")}
    assert names == {f"CHRDATB{n}.SAV" for n in range(1, 8)}


def test_import_slot_copies_the_full_eight_member_maximum():
    source = _por_disk("A", amiga_savegame.PARTY_MAX)
    dest = _por_disk("B", 1)

    amigaporslot.import_slot(dest, "B", source, "A")

    names = {entry.name.upper() for entry in dest.entries() if not entry.is_dir
             and entry.name.upper().startswith("CHRDATB") and entry.name.upper().endswith(".SAV")}
    assert names == {f"CHRDATB{n}.SAV" for n in range(1, amiga_savegame.PARTY_MAX + 1)}
