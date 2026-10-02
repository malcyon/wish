"""`amiga_savegame.area_script` looks an area up in block 0 of the Amiga `ECL.GLB`."""
from __future__ import annotations

import pathlib
import struct

import pytest

from goldbox import amiga_savegame
from goldbox.amiga_savegame import AmigaSaveError, area_script


def _glib(blocks: list[bytes]) -> bytes:
    """A GLIB container of `blocks`, built here and not read from any game."""
    head = b"GLIB" + struct.pack(">I", 0) + struct.pack(">HH", len(blocks), 0)
    head += b"DATA"
    start = len(head) + 4 * (len(blocks) + 1)
    offsets, at = [], start
    for block in blocks:
        offsets.append(at)
        at += len(block)
    offsets.append(at)
    return head + struct.pack(f">{len(offsets)}I", *offsets) + b"".join(blocks)


def _table(pairs: list[tuple[int, int]], count: int | None = None) -> bytes:
    count = len(pairs) if count is None else count
    return struct.pack(">H", count) + b"".join(
        struct.pack(">HH", a, b) for a, b in pairs)


def _library(pairs: list[tuple[int, int]]) -> bytes:
    blocks = [_table(pairs)] + [bytes([i]) * (3 + i)
                                for i in range(1, 1 + max(b for _a, b in pairs))]
    return _glib(blocks)


def test_the_world_map_resolves_through_the_table():
    pairs = [(1, 1), (0x50, 23)] + [(0x60 + i, i + 2) for i in range(21)]
    data = _library(pairs)
    assert area_script(data, 0x50) == bytes([23]) * 26


def test_an_area_in_the_sixteens_gets_its_own_block_and_not_the_block_of_that_number():
    data = _library([(1, 1), (0x10, 5), (0x11, 6), (0x32, 16)])
    assert area_script(data, 0x10) == bytes([5]) * 8
    assert area_script(data, 0x32) == bytes([16]) * 19


def test_an_area_the_table_does_not_name_raises():
    data = _library([(1, 1), (2, 2)])
    with pytest.raises(AmigaSaveError, match="no script for area 3"):
        area_script(data, 3)


@pytest.mark.parametrize("table", [
    _table([(1, 1), (2, 2)], count=3),            # count past the block
    _table([(1, 1), (2, 2)], count=1),            # count short of the block
    _table([(1, 1), (2, 9)]),                      # block number past the file
    _table([(1, 0)]),                              # block 0 is the table itself
    b"\x00",                                       # no room for a count
])
def test_a_table_that_does_not_fit_the_file_raises_and_never_indexes_by_area(table):
    data = _glib([table, b"aa", b"bbb"])
    with pytest.raises(AmigaSaveError):
        area_script(data, 1)


# -- the player's own disks ---------------------------------------------------


def _amiga_curse_glb() -> bytes:
    from goldbox.amiga_adf import AmigaDisk
    from tools.amiga import amigasaves
    for _label, image in amigasaves.images():
        try:
            return AmigaDisk(image).read_file("/DISKB/ECL.GLB")
        except Exception:
            continue
    pytest.skip("needs the player's Amiga Curse disk B")


def _c64_scripts() -> dict[int, bytes]:
    from automap import gamedisks
    from goldbox.d64 import D64
    try:
        root = pathlib.Path(str(gamedisks.find("curse-of-the-azure-bonds")))
    except Exception:
        pytest.skip("needs the player's C64 Curse disks")
    out: dict[int, bytes] = {}
    for path in sorted(root.glob("CURSE_?.D64")):
        img = D64.open(path)
        for entry in img.iter_directory():
            name = entry.name.decode("latin1").rstrip("\xa0 ")
            if (len(name) == 5 and name.startswith("ECL")
                    and name[3:] not in ("64", "65")):
                try:
                    out.setdefault(int(name[3:], 16), img.read_file(name)[2:])
                except ValueError:
                    continue
    if not out:
        pytest.skip("needs the player's C64 Curse disks")
    return out


def test_every_area_in_the_players_curse_table_resolves_to_the_c64_script():
    glb = _amiga_curse_glb()
    blocks = amiga_savegame._glib_blocks(glb)
    count = int.from_bytes(blocks[0][:2], "big")
    pairs = [struct.unpack_from(">HH", blocks[0], 2 + 4 * i)
             for i in range(count)]
    assert count == 25
    c64 = _c64_scripts()
    longer = []
    differ = []
    for area, block in pairs:
        assert area_script(glb, area) == blocks[block]
        if area not in c64 or blocks[block] == c64[area]:
            continue
        if blocks[block][:-1] == c64[area]:
            longer.append(area)
        else:
            differ.append(area)
    # Measured: 15 identical, six with one trailing byte more, $12 differing
    # in one byte and $31 and $32 differing throughout (the Amiga port's own
    # edits), and $52 having no C64 script.
    assert sorted(longer) == [0x03, 0x10, 0x20, 0x23, 0x30, 0x43]
    assert sorted(differ) == [0x12, 0x31, 0x32]
