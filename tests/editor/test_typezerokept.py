"""A DOS Pool item whose type byte is 0 is shown and survives an edit.

The engine builds such an item when its treasure roll leaves the type unset.
It is a real item, so the Items tab lists it as "Unnamed item", and adding
another or deleting a neighbour must not take its slot or drop its record.
"""
from __future__ import annotations

import shutil

import pytest
from gamedata import specimen
from PyQt6.QtCore import Qt
from support.editorwindow import make_root

from editor.inventory import NAME as NAME_COL
from editor.inventory import READIED_COL
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


def _open_again(path, index):
    return Party(str(path)).members[index].inventory, path, index


def _type_zero_blocks(inventory):
    return [r for r in inventory.raws if r[0] == 0 and any(r)]


def _itm(path, index):
    return next(path.parent.glob(f"CHRDAT?{index + 1}.ITM"))


def _select(w, index):
    w.roster.selectRow(index)
    return w.party.members[index].inventory


def _cell(w, slot, col):
    return w.items.data(w.items.index(w.items.row_of(slot), col))


@pytest.mark.parametrize("name", SPECIMENS)
def test_the_type_zero_item_is_listed_as_unnamed_item(app, tmp_path, name):
    w, _path, index = _open(tmp_path, name)
    inventory = _select(w, index)
    slot = next(n for n, r in enumerate(inventory.raws)
                if r[0] == 0 and any(r))

    assert inventory.used == 3
    assert w._describe_inventory(w.party.members[index]).startswith(
        "3 of 16 slots used")
    assert _cell(w, slot, NAME_COL) == "Unnamed item"
    inventory.names = {1: "X"}      # what an open game disk supplies
    assert _cell(w, slot, NAME_COL) == "Unnamed item"
    # The treasure specimen holds the item unreadied; the other has it readied.
    assert _cell(w, slot, READIED_COL) == (
        "Yes" if name == "por-793-type0-readied" else "No")


@pytest.mark.parametrize("name", SPECIMENS)
def test_selecting_the_unnamed_item_titles_its_details(app, tmp_path, name):
    w, _path, index = _open(tmp_path, name)
    inventory = _select(w, index)
    slot = next(n for n, r in enumerate(inventory.raws)
                if r[0] == 0 and any(r))
    table = w._child("inventory")
    table.setCurrentIndex(w.items.index(w.items.row_of(slot), NAME_COL))

    assert w._show_traits() == "Unnamed item"
    assert w.traits.rows == []


def test_the_changes_window_names_the_unnamed_item(app, tmp_path):
    w, path, index = _open(tmp_path, "por-793-type0-readied")
    inventory = _select(w, index)
    slot = next(n for n, r in enumerate(inventory.raws)
                if r[0] == 0 and any(r))
    before = {f.name: f.read_bytes() for f in path.parent.iterdir()}

    assert w.items.setData(
        w.items.index(w.items.row_of(slot), READIED_COL),
        Qt.CheckState.Unchecked.value, Qt.ItemDataRole.CheckStateRole)
    w._edited()
    assert f"item {slot} Unnamed item readied True -> False" in w.preview_text()
    w.save(interactive=False)

    itm = _itm(path, index)
    old, new = before[itm.name], itm.read_bytes()
    assert len(old) == len(new)
    assert [i for i, (a, b) in enumerate(zip(old, new)) if a != b] == [
        2 * RECORD + 0x34]
    assert Party(str(path)).members[index].inventory.raws[slot][6] & 0x80 == 0


@pytest.mark.parametrize("name", SPECIMENS)
def test_an_untouched_type_zero_save_writes_nothing(app, tmp_path, name):
    w, path, index = _open(tmp_path, name)
    inventory = _select(w, index)
    slot = next(n for n, r in enumerate(inventory.raws)
                if r[0] == 0 and any(r))
    w._child("inventory").setCurrentIndex(
        w.items.index(w.items.row_of(slot), NAME_COL))
    before = {f.name: f.read_bytes() for f in path.parent.iterdir()}

    assert w.preview_text().endswith("No changes to write")
    assert w.save(interactive=False) == "no changes"
    assert {f.name: f.read_bytes() for f in path.parent.iterdir()} == before
    assert not any(p.is_dir() for p in path.parent.iterdir())


@pytest.mark.parametrize("name", SPECIMENS)
def test_adding_an_item_keeps__the_type_zero_item(app, tmp_path, name):
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
def test_an_item_added_through_the_model_leaves_the_old_records_byte_for_byte(
        app, tmp_path, name):
    w, path, index = _open(tmp_path, name)
    inventory = _select(w, index)
    live = next(r for r in inventory.raws if r[0])
    old = _itm(path, index).read_bytes()

    assert w.items.add(live) == 3
    w._edited()
    w.save(interactive=False)

    new = _itm(path, index).read_bytes()
    for n in range(0, len(old), RECORD):
        assert old[n:n + RECORD] in [new[i:i + RECORD]
                                     for i in range(0, len(new), RECORD)]
    reopened, _path, _i = _open_again(path, index)
    slot = next(n for n, r in enumerate(reopened.raws)
                if r[0] == 0 and any(r))
    assert reopened.used == 4
    assert reopened.item(slot).raw[0] == 0


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
