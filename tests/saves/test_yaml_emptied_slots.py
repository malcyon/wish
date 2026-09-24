"""A C64 item slot the game emptied keeps its bytes through a YAML import.

Built on a synthetic save, so it runs where there are no game disks.
"""

from __future__ import annotations

import gamedata

from goldbox.d64 import D64
from goldbox.items import ITEM_AREA_BASE, ITEM_SIZE
from goldbox.savegame import SAVE0_LOAD_ADDRESS, SaveGame0
from goldbox.yaml_io import export_save, import_into

BASE = ITEM_AREA_BASE - SAVE0_LOAD_ADDRESS
LIVE_0 = bytes.fromhex("08000008000000000a00000200000000")
EMPTIED = bytes.fromhex("00000009000000000500040000000000")
LIVE_2 = bytes.fromhex("090000090000800005000f0000000000")


def _save(tmp_path):
    src = gamedata.synthetic_save(tmp_path)
    img = D64.open(str(src))
    sg = SaveGame0.from_prg(img.read_file(b"SAVEDGAME0"))
    payload = bytearray(sg.to_bytes())
    for n in range(16):
        payload[BASE + n * ITEM_SIZE:BASE + (n + 1) * ITEM_SIZE] = bytes(ITEM_SIZE)
    for n, block in enumerate((LIVE_0, EMPTIED, LIVE_2)):
        payload[BASE + n * ITEM_SIZE:BASE + (n + 1) * ITEM_SIZE] = block
    img.write_file_inplace(b"SAVEDGAME0", SaveGame0(bytes(payload)).to_prg())
    img.save(str(src))
    return src


def _run(src, tmp_path, edit=None):
    data = export_save(str(src))
    if edit:
        edit(data["party"][0]["items"])
    out = tmp_path / "out.d64"
    changes = import_into(str(src), data, str(out))
    blocks = SaveGame0.from_prg(D64.open(str(out)).read_file(b"SAVEDGAME0")).to_bytes()
    return changes, out, [blocks[BASE + n * ITEM_SIZE:BASE + (n + 1) * ITEM_SIZE]
                          for n in range(16)]


def test_no_edit_round_trip_changes_nothing(tmp_path):
    src = _save(tmp_path)
    changes, out, _ = _run(src, tmp_path)
    assert changes == []
    assert out.read_bytes() == src.read_bytes()


def test_added_item_fills_the_emptied_slot(tmp_path):
    src = _save(tmp_path)
    new = LIVE_0.hex()

    def add(items):
        items.append({"name": "NEW", "raw": new})

    changes, _, blocks = _run(src, tmp_path, add)
    assert len(changes) == 1 and "item 1 added" in changes[0]
    assert blocks[1] == bytes.fromhex(new)
    assert blocks[2] == LIVE_2


def test_removed_item_zeroes_its_slot_and_spares_the_emptied_one(tmp_path):
    src = _save(tmp_path)
    changes, _, blocks = _run(src, tmp_path, lambda items: items.pop())
    assert len(changes) == 1 and "item 2 removed" in changes[0]
    assert blocks[2] == bytes(ITEM_SIZE)
    assert blocks[1] == EMPTIED
