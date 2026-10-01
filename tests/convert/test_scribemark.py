"""A DOS or Amiga scroll saved while its spell is being scribed.

Both add 128 to the spell's byte and a camp save keeps it.  The C64 cancels a
scribe before its own camp save and reads bit 7 of a scroll's third byte as an
item-effect code, so only the C64 write clears the mark; DOS and Amiga keep it.
"""

from __future__ import annotations

import pytest
from gamedata import specimen_root
from support.amigalaterwrite import _verified
from support.neutralrecords import _filled

from goldbox import amiga_later, c64_codec, c64_port, dos_codec, dos_port, rewrite
from goldbox.amiga_port import CURSE_DELTAS, SILVER_BLADES_DELTAS

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


#: Each title's mage and cleric scroll type ids (`dos_codec.C64_SCROLL_TYPES`).
TITLES = {"pool": (dos_port.POOL_OF_RADIANCE, c64_port.POOL_OF_RADIANCE,
                   (0x3D, 0x3E)),
          "curse": (dos_port.CURSE_OF_THE_AZURE_BONDS,
                    c64_port.CURSE_OF_THE_AZURE_BONDS, (0x3D, 0x3E)),
          "silver-blades": (SSB, GAME, (0x27, 0x28))}
SCROLL_CASES = [pytest.param(title, kind, id=f"{title}-{kind:#x}")
                for title, (_d, _g, kinds) in TITLES.items() for kind in kinds]


def _resized(item: bytes, stride: int) -> bytes:
    """A Silver Blades item cut or padded to another title's stride: the
    fields the tests use all sit below byte 63."""
    return item[:stride].ljust(stride, b"\0")


def _neutral(tmp_path, *items: bytes, title="silver-blades"):
    deltas, game, _kinds = TITLES[title]
    stride = deltas.item_size
    items = tuple(_resized(i, stride) for i in items)
    record, _itm, _spc, _rep = dos_codec.write(_filled(game), deltas=deltas)
    out = bytearray(record)
    out[dos_port.FIELDS_BY_NAME_FOR[deltas.key]["item_count"].offset] = len(items)
    path = tmp_path / "CHRDATA1.SAV"
    path.write_bytes(bytes(out))
    (tmp_path / f"CHRDATA1{deltas.item_suffix}").write_bytes(b"".join(items))
    return dos_codec.to_neutral(dos_codec.read_character(path))


@pytest.mark.parametrize(("title", "kind"), SCROLL_CASES)
def test_a_marked_scroll_reaches_the_c64_with_bit_7_clear_and_nothing_else_changed(
        tmp_path, title, kind):
    marked = _neutral(tmp_path, _item(kind, MARKED), title=title)
    ordinary = _neutral(tmp_path, _item(kind, tuple(b & 0x7F for b in MARKED)),
                     title=title)
    rec, _ = dos_codec.neutral_to_c64_record(marked)
    ref, _ = dos_codec.neutral_to_c64_record(ordinary)
    slot = rec.get_raw("inventory")[:16]
    assert tuple(slot[13:16]) == (1, 2, 117)
    assert rec.to_bytes() == ref.to_bytes()


@pytest.mark.parametrize("title", ["pool", "curse"])
def test_a_pool_or_curse_trident_keeps_bit_7(tmp_path, title):
    """0x27 is a trident here, not a scroll: its `+13`-`+15` are not spells."""
    trident = (0, 0, 0x81)
    rec, _ = dos_codec.neutral_to_c64_record(
        _neutral(tmp_path, _item(0x27, trident), title=title))
    assert tuple(rec.get_raw("inventory")[13:16]) == trident


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


def test_a_marked_scroll_on_an_amiga_party_reaches_the_c64_with_bit_7_clear(
        tmp_path):
    char = _neutral(tmp_path, _item(0x27, MARKED))
    built, _report = amiga_later.write_later(char, SILVER_BLADES_DELTAS)
    amiga, _end = amiga_later._amiga_block(built.block_bytes(), 0,
                                           SILVER_BLADES_DELTAS)
    neutral = amiga_later.to_neutral_later(amiga)
    assert tuple(neutral.get("inventory")[0][13:16]) == MARKED
    rec, _ = dos_codec.neutral_to_c64_record(neutral)
    assert tuple(rec.get_raw("inventory")[13:16]) == (1, 2, 117)


def test_a_marked_amiga_curse_scroll_reaches_the_c64_with_bit_7_clear(
        tmp_path):
    """Made up: no Amiga Curse scroll has been read, so its type id is taken
    to be the DOS one, which the Amiga node keeps."""
    char = _neutral(tmp_path, _item(0x3D, MARKED), title="curse")
    built, _report = amiga_later.write_later(char, CURSE_DELTAS)
    amiga, _end = amiga_later._amiga_block(built.block_bytes(), 0,
                                           CURSE_DELTAS)
    neutral = amiga_later.to_neutral_later(amiga)
    assert tuple(neutral.get("inventory")[0][13:16]) == MARKED
    rec, _ = dos_codec.neutral_to_c64_record(neutral)
    assert tuple(rec.get_raw("inventory")[13:16]) == (1, 2, 117)


# --- the game-written mid-scribe save (Silver Blades, MORGAINE's scroll) -----
MORGAINE_SLOT = 6
MID = "dos-ssb-745-mid-scribe"
AFTER = "dos-ssb-745-after-reload"
REST_COUNTDOWN_AT = 0x69


def _morgaine(name, slot):
    root = specimen_root()
    where = None if root is None else root / "ssb-dos" / f"WISH-SPEC-{name}"
    if where is None or not where.is_dir():
        pytest.skip(f"needs specimen ssb-dos/WISH-SPEC-{name}")
    _verified(where)
    return dos_codec.read_character(
        where / f"CHRDAT{slot}{MORGAINE_SLOT}.SAV")


def test_the_game_written_mid_scribe_save_converts_as_the_reloaded_one_does():
    mid = _morgaine(MID, "D")
    after = _morgaine(AFTER, "F")
    mid_rec, _ = dos_codec.to_c64_record(mid)
    rec, _ = dos_codec.to_c64_record(after)
    assert mid.name == after.name
    assert mid_rec.get_raw("inventory") == rec.get_raw("inventory")
    assert mid_rec.get_raw("inventory")[:16].hex(" ") == (
        "27 66 27 28 02 00 00 00 0a 00 00 b8 0b 71 6f 11")
    assert mid_rec.to_bytes()[0x101:0x103] == bytes(2)
    assert rec.to_bytes()[0x101:0x103] == bytes(2)


def test_saving_the_mid_scribe_save_in_place_keeps_the_file_the_game_wrote():
    char = _morgaine(MID, "D")
    game = c64_port.by_key(char.deltas.key)
    before, _ = dos_codec.to_c64_record(char)
    assert char.to_bytes()[REST_COUNTDOWN_AT] == 4
    scroll_at = F["charges"].offset

    def scroll_bytes(itm):
        return bytes(itm[scroll_at:scroll_at + 3])

    out = rewrite.rewrite_dos(char, before, before, game)
    assert out.record == char.to_bytes()
    assert scroll_bytes(out.items) == bytes((0x71, 0x6F, 0x91))

    after = c64_codec.CharacterRecord(before.to_bytes(), before.stored_size)
    after.hp_current = before.hp_current - 1
    edited = rewrite.rewrite_dos(char, before, after, game)
    assert edited.record[REST_COUNTDOWN_AT] == 4
    assert scroll_bytes(edited.items) == bytes((0x71, 0x6F, 0x91))



def test_every_title_with_c64_deltas_has_a_scroll_type_row():
    assert set(dos_codec.C64_SCROLL_TYPES) == set(c64_codec.DELTAS_BY_KEY)
