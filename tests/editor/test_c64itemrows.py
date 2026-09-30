from __future__ import annotations

"""The Items tab lists a character's items in the order the game draws them:
the highest filled slot first, the filled rows above the empty ones, and every
edit acting on the slot its row shows.
"""

from PyQt6.QtCore import Qt

from editor.inventory import NAME, NUMBER, QTY, Inventory, InventoryModel

ITEM_NAMES = {n: f"ITEM{n}" for n in range(1, 40)}


def _block(type_index: int, quantity: int = 1) -> bytes:
    block = bytearray(16)
    block[0] = type_index
    block[3] = type_index
    block[10] = quantity
    return bytes(block)


def _model(filled: int = 4) -> InventoryModel:
    blocks = [_block(n + 1) for n in range(filled)] + \
        [bytes(16)] * (16 - filled)
    return InventoryModel(Inventory.from_blocks(blocks, ITEM_NAMES))


def _names(model) -> list[str]:
    return [model.data(model.index(r, NAME)) for r in range(16)]


def test_the_highest_filled_slot_is_the_top_row_and_empty_rows_stay_below():
    model = _model()
    assert _names(model)[:4] == ["ITEM4", "ITEM3", "ITEM2", "ITEM1"]
    assert set(_names(model)[4:]) == {"—"}


def test_the_number_column_keeps_showing_the_slot():
    model = _model()
    assert [model.data(model.index(r, NUMBER)) for r in range(6)] == \
        ["3", "2", "1", "0", "4", "5"]


def test_an_edit_lands_on_the_slot_its_row_shows():
    model = _model()
    assert model.setData(model.index(0, QTY), 9)          # the top row: slot 3
    assert [model.inventory.item(n).quantity for n in range(4)] == [1, 1, 1, 9]


def test_a_row_delete_removes_the_item_that_row_shows():
    model = _model()
    assert model.delete(1)                                  # ITEM3, slot 2
    assert _names(model)[:3] == ["ITEM4", "ITEM2", "ITEM1"]
    assert not model.delete(10)                             # an empty row


def test_an_added_item_takes_the_first_free_slot_and_heads_the_list():
    model = _model()
    assert model.add(_block(20)) == 4
    assert _names(model)[:2] == ["ITEM20", "ITEM4"]
    assert model.inventory.item(4).type_index == 20


def test_a_hole_keeps_its_row_below_the_filled_ones():
    blocks = [_block(1), bytes(16), _block(3)] + [bytes(16)] * 13
    model = InventoryModel(Inventory.from_blocks(blocks, ITEM_NAMES))
    assert _names(model)[:2] == ["ITEM3", "ITEM1"]
    assert not model.flags(model.index(2, QTY)) & Qt.ItemFlag.ItemIsEditable


def test_a_dos_characters_converted_record_lists_dos_record_zero_first():
    """The roster builds a DOS save's Items tab from the C64 record the
    conversion writes, so the top row is the `.ITM` file's first record."""
    from support.neutralrecords import _filled

    from editor.roster import _ITEMS_AT
    from goldbox import dos_codec

    char = _filled()
    char.set("inventory", [_block(n + 1) for n in range(4)], "made up")
    record, _report = dos_codec.neutral_to_c64_record(char)
    raw = record.to_bytes()
    model = InventoryModel(Inventory.from_blocks(
        [raw[_ITEMS_AT + n * 16:_ITEMS_AT + (n + 1) * 16] for n in range(16)],
        ITEM_NAMES))
    assert _names(model)[:4] == ["ITEM1", "ITEM2", "ITEM3", "ITEM4"]
