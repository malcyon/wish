"""A DOS Pool item whose type byte is 0 survives an item add or delete.

The engine builds such an item when its treasure roll leaves the type unset.
It is a real item, so adding another or deleting a neighbour must not take its
slot or drop its record.
"""
from __future__ import annotations

import shutil

import pytest
from gamedata import specimen
from support.editorwindow import make_root

from editor.roster import Party
from editor.window import EditorBinding

SPECIMENS = ("por-793-treasure-type0-item", "por-793-type0-readied")
NAME = "THRENDER GRONE"
RECORD = 63          # one `.ITM` record: the item block plus its name text


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _open(tmp_path, name):
    folder = tmp_path / "save"
    shutil.copytree(specimen(name), folder)
    folder.chmod(0o755)
    for copied in folder.iterdir():
        copied.chmod(0o644)
    path = next(folder.glob("SAVGAM?.DAT"))
    w = EditorBinding(make_root(), str(path))
    index = next(i for i, m in enumerate(w.party.members)
                 if m.name.strip() == NAME)
    return w, path, index


def _type_zero_blocks(inventory):
    return [r for r in inventory.raws if r[0] == 0 and any(r)]


def _itm(path, index):
    return next(path.parent.glob(f"CHRDAT?{index + 1}.ITM"))


@pytest.mark.parametrize("name", SPECIMENS)
def test_adding_an_item_keeps_the_type_zero_item(app, tmp_path, name):
    w, path, index = _open(tmp_path, name)
    inventory = w.party.members[index].inventory
    kept = _type_zero_blocks(inventory)
    assert kept, "the specimen holds no type-0 item"
    live = next(r for r in inventory.raws if r[0])
    before = _itm(path, index).stat().st_size

    slot = inventory.add(live)
    assert not inventory.original[slot][0] and not any(inventory.original[slot])
    w._edited()
    w.save(interactive=False)

    reread = Party(str(path)).members[index].inventory
    assert _type_zero_blocks(reread) == kept
    assert _itm(path, index).stat().st_size == before + RECORD


@pytest.mark.parametrize("name", SPECIMENS)
def test_deleting_an_item_keeps_the_type_zero_item(app, tmp_path, name):
    w, path, index = _open(tmp_path, name)
    inventory = w.party.members[index].inventory
    kept = _type_zero_blocks(inventory)
    assert kept, "the specimen holds no type-0 item"
    before = _itm(path, index).stat().st_size
    victim = next(n for n, r in enumerate(inventory.raws) if r[0])

    inventory.delete(victim)
    assert _type_zero_blocks(inventory) == kept
    w._edited()
    w.save(interactive=False)

    reread = Party(str(path)).members[index].inventory
    assert _type_zero_blocks(reread) == kept
    assert _itm(path, index).stat().st_size == before - RECORD


def test_an_amiga_pool_member_keeps_a_type_zero_block_on_add_and_delete():
    from editor.roster import _ITEMS_AT, Party
    from goldbox import c64_port
    from goldbox.record import CharacterRecord

    type_zero = bytes([0, 0, 0, 0, 0, 0, 6]) + bytes(9)
    live = bytes([1, 0, 0, 9]) + bytes(12)
    raw = bytearray(CharacterRecord.blank().to_bytes())
    raw[_ITEMS_AT:_ITEMS_AT + 48] = live + type_zero + live
    record = CharacterRecord.from_bytes(bytes(raw))

    party = Party.__new__(Party)
    party.members, party.port = [], "amiga"
    party.game = c64_port.POOL_OF_RADIANCE
    party._append_converted(1, record, None, {})
    inventory = party.members[0].inventory

    assert inventory.add(live) == 3
    assert inventory.raws[1] == type_zero
    inventory.delete(0)
    assert type_zero in inventory.raws
