"""A DOS or Amiga scroll saved while its spell is being scribed.

Both add 128 to the spell's byte and a camp save keeps it.  The C64 cancels a
scribe before its own camp save and reads bit 7 of a scroll's third byte as an
item-effect code, so only the C64 write clears the mark; DOS and Amiga keep it.
"""

from __future__ import annotations

import pytest
from support.neutralrecords import _filled

from goldbox import amiga_later, c64_port, dos_codec, dos_port
from goldbox.amiga_port import SILVER_BLADES_DELTAS

SSB = dos_port.SECRET_OF_THE_SILVER_BLADES
GAME = c64_port.SECRET_OF_THE_SILVER_BLADES
STRIDE = SSB.item_size
F = dos_port.ITEM_FIELDS_BY_NAME
MARKED = (129, 130, 245)


def _item(type_index: int, spells) -> bytes:
    out = bytearray(STRIDE)
    out[F["type_index"].offset] = type_index
    out[F["weight"].offset] = 1
    at = F["charges"].offset
    out[at:at + 3] = bytes(spells)
    return bytes(out)


def _neutral(tmp_path, *items: bytes):
    record, _itm, _spc, _rep = dos_codec.write(_filled(GAME), deltas=SSB)
    out = bytearray(record)
    out[dos_port.FIELDS_BY_NAME_FOR[SSB.key]["item_count"].offset] = len(items)
    path = tmp_path / "CHRDATA1.SAV"
    path.write_bytes(bytes(out))
    (tmp_path / "CHRDATA1.STF").write_bytes(b"".join(items))
    return dos_codec.to_neutral(dos_codec.read_character(path))


@pytest.mark.parametrize("kind", [0x27, 0x28])
def test_a_marked_scroll_reaches_the_c64_with_bit_7_clear_and_nothing_else_changed(
        tmp_path, kind):
    marked = _neutral(tmp_path, _item(kind, MARKED))
    plain = _neutral(tmp_path, _item(kind, tuple(b & 0x7F for b in MARKED)))
    rec, _ = dos_codec.neutral_to_c64_record(marked)
    ref, _ = dos_codec.neutral_to_c64_record(plain)
    slot = rec.get_raw("inventory")[:16]
    assert tuple(slot[13:16]) == (1, 2, 117)
    assert rec.to_bytes() == ref.to_bytes()


def test_the_neutral_inventory_still_carries_the_mark(tmp_path):
    char = _neutral(tmp_path, _item(0x27, MARKED))
    assert tuple(char.get("inventory")[0][13:16]) == MARKED


def test_a_non_scroll_item_keeps_a_high_byte_in_its_effect_bytes(tmp_path):
    char = _neutral(tmp_path, _item(18, (200, 201, 202)))
    rec, _ = dos_codec.neutral_to_c64_record(char)
    assert tuple(rec.get_raw("inventory")[13:16]) == (200, 201, 202)


def test_the_roster_scribe_queue_bytes_are_written_zero(tmp_path):
    rec, _ = dos_codec.neutral_to_c64_record(
        _neutral(tmp_path, _item(0x27, MARKED)))
    assert rec.to_bytes()[0x101:0x103] == bytes(2)


def test_dos_to_dos_keeps_the_mark(tmp_path):
    char = _neutral(tmp_path, _item(0x27, MARKED))
    _record, itm, _spc, _rep = dos_codec.write(char, deltas=SSB)
    at = F["charges"].offset
    assert tuple(itm[at:at + 3]) == MARKED


def test_dos_to_amiga_keeps_the_mark(tmp_path):
    char = _neutral(tmp_path, _item(0x27, MARKED))
    built, _report = amiga_later.write_later(char, SILVER_BLADES_DELTAS)
    block = built.block_bytes()
    # The scroll's spells in a Silver Blades node: `0x3F`-`0x41`.
    at = SILVER_BLADES_DELTAS.record_size + 0x3F
    assert tuple(block[at:at + 3]) == MARKED
