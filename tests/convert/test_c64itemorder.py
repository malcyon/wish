from __future__ import annotations

"""A character's item list keeps the order the player sees across the C64.

The C64's ITEMS screen draws slot 15 first and slot 0 last; DOS draws the
`.ITM` records in file order.  The neutral `inventory` is top row first, so
the C64 writer and reader each reverse the slot order.
"""

import pytest
from support.neutralrecords import _filled

from goldbox import c64_codec, dos_codec, dos_port, rewrite
from goldbox.items import ITEM_SIZE
from tests.gamedata import specimen_root

POOL = dos_port.POOL_OF_RADIANCE


def _blocks(n: int) -> list[bytes]:
    return [bytes([0x0A + i]) + bytes(15) for i in range(n)]


def _slot_types(rec) -> list[int | None]:
    raw = rec.get_raw("inventory")
    return [raw[n * ITEM_SIZE] if any(raw[n * ITEM_SIZE:(n + 1) * ITEM_SIZE])
            else None for n in range(c64_codec.ITEM_SLOTS)]


def _neutral(n: int):
    char = _filled()
    char.set("inventory", _blocks(n), "made up")
    return char


def test_the_first_item_goes_to_the_highest_slot_and_the_slots_stay_packed():
    rec, _ = c64_codec.write(_neutral(5))
    assert _slot_types(rec) == [0x0E, 0x0D, 0x0C, 0x0B, 0x0A] + [None] * 11


def test_a_full_pack_puts_item_zero_in_slot_fifteen():
    rec, _ = c64_codec.write(_neutral(16))
    assert _slot_types(rec) == [0x0A + 15 - n for n in range(16)]


def test_a_pack_past_sixteen_keeps_the_first_sixteen_top_first():
    rec, _ = c64_codec.write(_neutral(20))
    assert _slot_types(rec)[15] == 0x0A and _slot_types(rec)[0] == 0x19


def test_the_reader_lists_slot_fifteen_first():
    rec, _ = c64_codec.write(_neutral(5))
    back = c64_codec.read(rec)
    assert [b[0] for b in back.get("inventory")] == [0x0A + n for n in range(5)]


def test_a_c64_slot_order_reaches_dos_with_the_top_row_as_record_zero():
    rec, _ = c64_codec.write(_neutral(4))
    raw = bytearray(rec.get_raw("inventory"))
    # Slot 3 is the highest occupied slot, so it is the first row.
    assert raw[3 * ITEM_SIZE] == 0x0A
    neutral = c64_codec.read(rec)
    itm = dos_codec.write(neutral, deltas=POOL)[1]
    stride = POOL.item_size
    nodes = dos_codec.item_nodes(itm, stride)
    assert [n.get("type_index") for n in nodes] == [0x0A, 0x0B, 0x0C, 0x0D]


def test_dos_to_c64_to_dos_keeps_the_item_file_order():
    neutral = _neutral(6)
    direct = dos_codec.write(neutral, deltas=POOL)[1]
    rec, _ = c64_codec.write(neutral)
    assert dos_codec.write(c64_codec.read(rec), deltas=POOL)[1] == direct


def test_a_same_port_c64_edit_leaves_every_slot_position_alone():
    """The rewrite maps a slot back to the port's item by rank, so an edit to
    one slot changes only that slot's item and moves nothing else."""
    neutral = _neutral(4)
    rec, _ = c64_codec.write(neutral)
    before = rec
    after = c64_codec.CharacterRecord(rec.to_bytes(), rec.stored_size)
    after.gold = 1234
    edits = rewrite._item_edits(before, after, 4)
    assert [(e.index, e.after[0]) for e in edits] == \
        [(0, 0x0A), (1, 0x0B), (2, 0x0C), (3, 0x0D)]


def test_the_xavier_specimen_reads_in_the_order_the_c64_screen_draws():
    from goldbox import items
    from goldbox.d64 import D64
    from goldbox.savegame import load_save
    root = specimen_root()
    path = (root / "por-c64" /
            "WISH-SPEC-por-790-scribe-e-c64-game-resave.D64") if root else None
    if path is None or not path.is_file():
        pytest.skip("the #790 C64 specimen is not on this machine")
    game, save0, save1 = load_save(D64.open(str(path)))
    found = None
    for slot in save0.characters:
        slots = [i.raw for i in
                 items.items_for_slot(save0.to_bytes(), slot.index)]
        char = c64_codec.read(slot.record, inventory=slots, game=game,
                              roster=save1.roster(slot.index)
                              if save1 is not None else None)
        if str(char.get("name")).strip().upper() == "XAVIER":
            found = (char, slots)
    assert found is not None
    char, slots = found
    assert len(slots) == 15
    # Wish wrote this disk's slots 0 to 14 as DOS records 0 to 14, the
    # necklace in slot 0 and the scribed scroll in slot 14; the C64 draws
    # slot 14 first, so the scroll heads the neutral list.
    assert [bytes(i) for i in char.get("inventory")] == slots[::-1]
