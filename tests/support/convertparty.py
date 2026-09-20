"""Helpers `test_convert` shares with the test files that reuse them."""
from __future__ import annotations

import pathlib

from gamedata import game_file

from goldbox.savegame import SaveGame0, SaveGame1

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures"


def _fixture_payloads() -> tuple[bytes, bytes]:
    sg = SaveGame0.from_prg((FIXTURES / "savedgame0.bin").read_bytes())
    sg1 = SaveGame1.from_prg((FIXTURES / "savedgame1.bin").read_bytes())
    return sg.to_bytes(), sg1.to_bytes()


def _six_icon_party() -> "tuple[bytes, bytes, object]":
    """BRUTUS's own committed fixture, cloned into all six slots with six
    different names and six different combat icons.

    The same shape `tests/convert/test_doswriter.py`'s own
    `test_a_c64_party_of_six_different_icons_gets_six_different_dos_figures`
    builds at `goldbox.dos_codec`'s own layer -- nothing here is the game's own
    saved bytes, only its documented icon format applied six times to one
    committed fixture. Returns `(save0, save1, IconParts)` so a caller needs
    to read `SPELLE64`/`SPELLN64` only once.
    """
    from goldbox import c64_save
    from goldbox.iconparts import (
        DEFAULT_BACKGROUND,
        DEFAULT_PART_COLOURS,
        MULTICOLOUR,
        IconParts,
    )
    from goldbox.savegame import HEADER_SIZE, SLOT_STRIDE

    parts = IconParts(game_file("SPELLE64"), game_file("SPELLN64"))
    save0, save1 = _fixture_payloads()
    container = c64_save.container_for(None)

    figures = [("large", 0, 0), ("large", 7, 4), ("large", 11, 9),
              ("small", 3, 2), ("small", 16, 7), ("large", 21, 12)]
    names = (b"ONE", b"TWO", b"THREE", b"FOUR", b"FIVE", b"SIX")
    base = bytearray(save0)
    slot0 = bytes(base[HEADER_SIZE:HEADER_SIZE + SLOT_STRIDE])
    for i, (size, weapon, head) in enumerate(figures):
        off = HEADER_SIZE + i * SLOT_STRIDE
        base[off:off + SLOT_STRIDE] = slot0
        base[off:off + len(names[i])] = names[i]
        base[off + len(names[i]):off + 20] = bytes(20 - len(names[i]))
        shape = parts.compose(size, weapon, head)
        seed = bytes([DEFAULT_BACKGROUND | MULTICOLOUR] * len(shape))
        icon = shape + parts.colours_for(shape, DEFAULT_PART_COLOURS, seed)
        at = container.icon(i)
        base[at:at + container.icon_size] = icon
    return bytes(base), save1, parts
