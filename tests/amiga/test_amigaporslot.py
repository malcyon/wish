"""`amigaporslot.import_slot`: the character-file selection regex.

It copies up to `PARTY_MAX` (eight) character files, not six.
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
