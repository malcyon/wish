"""The control byte's offset in each DOS title, and how a value reads.

`tools/controlbyte.py` derives the offset from each title's own shape rather
than tabulating it, so the derivation is the thing that can silently go wrong:
if `field_83_87` ever moves or changes width, the census would keep printing
partitions of whatever byte happened to land there.  These pin it against the
four offsets `tools/dosbyteimm.py` finds the engines' own compares at --
`0x084`, `0x0F7`, `0x0FF`, `0x147`, one per title's `GAME.OVR`
(`docs/195-three-dos-record-bytes-named-from-the-overlays.md`).

No game data is read here; the shapes are this project's own declarations.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import dos_port as dl  # noqa: E402
from tools import controlbyte  # noqa: E402

#: Where each engine's own `cmp ..., 80h` reaches, measured per title.
MEASURED = {
    "pool-of-radiance": 0x084,
    "curse-of-the-azure-bonds": 0x0F7,
    "secret-of-the-silver-blades": 0x0FF,
    "pools-of-darkness": 0x147,
}


@pytest.mark.parametrize("key,offset", sorted(MEASURED.items()))
def test_the_control_byte_lands_where_the_engine_compares_it(key, offset):
    shape = dl.DELTAS_BY_KEY[key]
    control, share = controlbyte.dos_offsets(shape)
    assert control == offset
    assert share == offset + 1


def test_the_control_byte_is_inside_the_run_it_is_derived_from():
    """The four-byte titles dropped the run's **first** byte, not its last.

    Curse's own Pool of Radiance importer copies `0x083`-`0x087` into
    `0x0F6`-`0x0FA` one for one, so the control byte is the fourth from the
    end of the run in every title.  A shape that shrank the run at the other
    end would still pass the offsets above by luck; this says which end.
    """
    for shape in dl.DELTAS:
        run = dl.FIELDS_BY_NAME_FOR[shape.key]["field_83_87"]
        control, share = controlbyte.dos_offsets(shape)
        assert run.offset <= control < run.offset + run.size
        assert control == run.offset + run.size - 4
        assert share < run.offset + run.size


def test_a_value_reads_as_a_player_character_or_as_a_morale():
    assert controlbyte.reading(0x00) == "player character (trainer bit 0)"
    assert controlbyte.reading(0x01) == "player character (trainer bit 1)"
    # The trainer bit is the C64's; DOS keeps that flag in the share byte.
    assert controlbyte.reading(0x01, "dos") == "player character"
    # Stored halved, so 0x32 in the low seven bits is 100 per cent.
    assert controlbyte.reading(0xB2) == "engine-driven, morale 100, NPC_Berzerk"
    assert controlbyte.reading(0xB3) == "engine-driven, morale 100, PC_Berzerk"
    assert controlbyte.reading(0x80) == "engine-driven, morale 0"
    assert controlbyte.reading(0xB1) == "engine-driven, morale 98"
    # Curse's SECSET64 $0A1C clamps the doubled value at 100.
    assert controlbyte.reading(0xFF) == "engine-driven, morale 100"
