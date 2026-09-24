"""A Silver Blades joined scroll, read and converted in every direction.

A mage who uses `ITEMS > JOIN` on two scrolls holds one item with the scrolls
chained off it.  DOS writes the chain into the `.STF` file straight after the
head and counts only the head in `item_count`; the Amiga does the same in its
saved game; the C64 has no joined scroll and holds the same scrolls one to a
slot.  `docs/215-the-dos-experience-award-and-the-scroll-bundle.md` has the
engine code each rule here is read from.

**Every byte here is composed from the documented format**, following what
the JOIN routine (`SECRET GAME.OVR` `0x29391`) makes -- the head's type,
names, weight, quantity and value, and a live far pointer in each node's
chain field -- so nothing is sliced out of anybody's save.  No save on this
machine holds a joined scroll (`tools/dos/dosscrollbundle.py census`).  The
two tests at the end that need the archives' shipped Silver Blades party
skip without them.
"""

from __future__ import annotations

import pytest
from support.neutralrecords import _filled

from goldbox import (
    amiga_later,
    amiga_savegame,
    c64_codec,
    c64_port,
    dos_codec,
    dos_port,
    rewrite,
)
from goldbox.amiga_port import SILVER_BLADES_DELTAS
from goldbox.neutral import ScrollBundle

SSB = dos_port.SECRET_OF_THE_SILVER_BLADES
GAME = c64_port.SECRET_OF_THE_SILVER_BLADES
STRIDE = SSB.item_size
F = dos_port.ITEM_FIELDS_BY_NAME

#: Two far pointers of the kind the engine leaves in a node's chain field and
#: its `next`: heap addresses the loader overwrites, never a value to keep.
LIVE = bytes.fromhex("1000a53c")
STALE = bytes.fromhex("5e0034a1")


def _item(type_index: int, *, spells=(0, 0, 0), weight: int = 0,
          quantity: int = 0, value: int = 0, plus: int = 0) -> bytearray:
    out = bytearray(STRIDE)
    out[F["type_index"].offset] = type_index
    out[F["plus"].offset] = plus
    out[F["weight"].offset:F["weight"].offset + 2] = weight.to_bytes(2, "little")
    out[F["quantity"].offset] = quantity
    out[F["value"].offset:F["value"].offset + 2] = value.to_bytes(2, "little")
    at = F["charges"].offset
    out[at:at + 3] = bytes(spells)
    return out


SWORD = _item(18, weight=60, value=2000, plus=1)
PLATE = _item(5, weight=450, value=4000, plus=1)
SCROLL_A = _item(0x27, spells=(1, 2, 3), weight=1, value=300)
SCROLL_B = _item(0x27, spells=(4, 0, 0), weight=1, value=100)
SCROLL_C = _item(0x28, spells=(0x80 | 5, 6, 0), weight=1, value=200)


def _joined(*scrolls: bytearray) -> bytes:
    """A joined scroll as the `.STF` file holds it: the head JOIN makes, then
    each scroll copied whole, every node but the last pointing on."""
    head = _item(dos_codec.SCROLL_BUNDLE_TYPE, weight=len(scrolls),
                 quantity=len(scrolls),
                 value=sum(int.from_bytes(s[0x3A:0x3C], "little")
                           for s in scrolls))
    head[F["name1"].offset] = 0x27
    head[F["name2"].offset] = len(scrolls)
    head[F["name3"].offset] = 0x4D
    tail = dos_codec.ITEM_TAIL[0]
    head[tail:tail + 4] = LIVE
    out = bytes(head)
    for n, scroll in enumerate(scrolls):
        node = bytearray(scroll)
        node[0x2A:0x2E] = STALE
        if n + 1 < len(scrolls):
            node[tail:tail + 4] = LIVE
        out += bytes(node)
    return out


def _record(item_count: int) -> bytes:
    """A 439-byte Silver Blades record made by this project's own writer from
    a filled neutral character, with the count set by hand."""
    record, _itm, _spc, _rep = dos_codec.write(_filled(GAME), deltas=SSB)
    out = bytearray(record)
    out[dos_port.FIELDS_BY_NAME_FOR[SSB.key]["item_count"].offset] = item_count
    return bytes(out)


def _pack_file() -> bytes:
    """A sword, a joined scroll of two, and plate mail after it: four heads'
    worth of records would be five, and `item_count` is three."""
    return bytes(SWORD) + _joined(SCROLL_A, SCROLL_B) + bytes(PLATE)


def _read(tmp_path, itm: bytes, count: int) -> dos_codec.DosCharacter:
    path = tmp_path / "CHRDATA1.SAV"
    path.write_bytes(_record(count))
    (tmp_path / "CHRDATA1.STF").write_bytes(itm)
    return dos_codec.read_character(path)


def _spells(block: bytes) -> tuple[int, int, int]:
    return block[13], block[14], block[15]


def _slots(rec) -> list[bytes]:
    raw = rec.get_raw("inventory")
    return [raw[n * 16:(n + 1) * 16] for n in range(16)
            if any(raw[n * 16:(n + 1) * 16])]


# --- reading DOS -------------------------------------------------------------
def test_the_plate_mail_after_a_joined_scroll_is_still_in_the_pack(tmp_path):
    """The player's case: `item_count` 3, five records, and the last item is
    the plate mail -- which a reader slicing the first three records lost."""
    char = _read(tmp_path, _pack_file(), 3)
    assert [it.get("type_index") for it in char.items] == [18, 0x49, 5]
    assert char.items[2].get("weight") == 450
    joined = char.items[1]
    assert [s.get("type_index") for s in joined.subnodes] == [0x27, 0x27]
    assert [s.get("charges") for s in joined.subnodes] == [1, 4]


def test_the_engines_own_encumbrance_counts_the_head_and_not_its_scrolls(
        tmp_path):
    """The DOS recount walks the head items only (`0x3A2C7`), so the joined
    scroll weighs its head's `weight x quantity`: 2 x 2 here."""
    char = _read(tmp_path, _pack_file(), 3)
    assert char.expected_encumbrance() == \
        sum(char.money.values()) + 60 + 2 * 2 + 450


def test_a_joined_scroll_whose_scrolls_run_off_the_file_is_named(tmp_path):
    """A truncated file, not a game state: the engine would read short
    records into the missing nodes."""
    itm = _pack_file()[:2 * STRIDE + STRIDE]          # head and one scroll
    with pytest.raises(dos_codec.DosRecordError,
                       match=r"CHRDATA1\.STF: item 1 is a joined scroll of 2"):
        _read(tmp_path, itm, 3)


def test_an_export_beside_a_stale_file_holding_a_joined_scroll_has_no_items(
        tmp_path):
    assert _read(tmp_path, _pack_file(), 0).items == ()


# --- DOS to the neutral record, and back -------------------------------------
def test_the_neutral_pack_is_the_scrolls_in_the_joined_scrolls_place(tmp_path):
    out = dos_codec.to_neutral(_read(tmp_path, _pack_file(), 3))
    inventory = out.get("inventory")
    assert [b[0] for b in inventory] == [18, 0x27, 0x27, 5]
    assert [_spells(b) for b in inventory[1:3]] == [(1, 2, 3), (4, 0, 0)]
    (bundle,) = out.get("scroll_bundles")
    assert (bundle.first, bundle.count) == (1, 2)
    assert bundle.head[0] == 0x49 and bundle.head[10] == 2
    assert bundle.head[1:4] == bytes((0x27, 2, 0x4D))


def test_dos_to_dos_writes_the_same_file_but_the_pointers(tmp_path):
    """Round-trip byte for byte, masking only what `write` declares it leaves
    NULL: each record's rendered-line cache, `next` and chain pointer."""
    original = _pack_file()
    itm = dos_codec.write(dos_codec.to_neutral(_read(tmp_path, original, 3)),
                          deltas=SSB)[1]
    assert len(itm) == len(original) == 5 * STRIDE
    masked = [(0, 0x2A), (0x2A, 4), dos_codec.ITEM_TAIL]
    for n in range(5):
        a = bytearray(original[n * STRIDE:(n + 1) * STRIDE])
        b = bytearray(itm[n * STRIDE:(n + 1) * STRIDE])
        for at, size in masked:
            a[at:at + size] = bytes(size)
        assert a == b, n
    assert not any(any(itm[n * STRIDE + at:n * STRIDE + at + size])
                   for n in range(5) for at, size in masked[1:])


def test_the_written_record_counts_three_items_and_weighs_the_head(tmp_path):
    record, itm, _spc, _rep = dos_codec.write(
        dos_codec.to_neutral(_read(tmp_path, _pack_file(), 3)), deltas=SSB)
    table = dos_port.FIELDS_BY_NAME_FOR[SSB.key]
    assert record[table["item_count"].offset] == 3
    back = dos_codec.DosCharacter(
        record, dos_codec.item_nodes(itm, STRIDE), deltas=SSB)
    stored = int.from_bytes(record[table["encumbrance"].span], "little")
    assert stored == back.expected_encumbrance()
    assert [len(it.subnodes) for it in back.items] == [0, 2, 0]


# --- to the C64, which holds the scrolls one to a slot -----------------------
def test_dos_to_c64_puts_every_scroll_in_a_slot_of_its_own(tmp_path):
    rec, _rep = dos_codec.to_c64_record(_read(tmp_path, _pack_file(), 3))
    slots = _slots(rec)
    assert [s[0] for s in slots] == [18, 0x27, 0x27, 5]
    assert [_spells(s) for s in slots[1:3]] == [(1, 2, 3), (4, 0, 0)]


def test_the_c64_writer_reports_nothing_dropped_for_the_join(tmp_path):
    _rec, report = dos_codec.to_c64_record(_read(tmp_path, _pack_file(), 3))
    assert not [d for d in report.dropped if "scroll_bundles" in d]
    assert not [d for d in report.losses if "inventory" in d]


def test_c64_to_dos_writes_the_scrolls_as_items_of_their_own(tmp_path):
    """The C64 has no join, so its scrolls come back separate: four head
    items, no type-0x49 record, every spell in its place."""
    rec, _rep = dos_codec.to_c64_record(_read(tmp_path, _pack_file(), 3))
    record, itm, _spc, _r = dos_codec.write(c64_codec.read(rec, game=GAME),
                                            deltas=SSB)
    items = dos_codec.item_nodes(itm, STRIDE)
    assert [it.get("type_index") for it in items] == [18, 0x27, 0x27, 5]
    assert [it.get("charges") for it in items[1:3]] == [1, 4]
    count = dos_port.FIELDS_BY_NAME_FOR[SSB.key]["item_count"].offset
    assert record[count] == 4


def _crowded(plain: int, scrolls: int) -> bytes:
    return (b"".join(bytes(_item(10 + n, weight=10)) for n in range(plain))
            + _joined(*[SCROLL_A] * scrolls))


def test_a_pack_that_fits_sixteen_slots_converts_whole(tmp_path):
    """Fourteen items and a joined pair: sixteen C64 slots exactly."""
    char = _read(tmp_path, _crowded(14, 2), 15)
    assert dos_codec.c64_slots_needed(char) == 16
    rec, _rep = dos_codec.to_c64_record(char)
    assert len(_slots(rec)) == 16


def test_a_pack_the_c64_cannot_hold_stops_the_write_rather_than_losing_one(
        tmp_path):
    """Fifteen items and a joined pair need seventeen slots.  The choice of
    what stays behind is the player's, and nothing asks for it yet, so the
    whole-save writer refuses rather than dropping the seventeenth."""
    char = _read(tmp_path, _crowded(15, 2), 16)
    assert dos_codec.c64_slots_needed(char) == 17
    with pytest.raises(dos_codec.JoinedScrollsDoNotFit) as caught:
        dos_codec.write_c64_save(bytearray(0x1D00), None, None, [char])
    assert (caught.value.needed, caught.value.slots) == (17, 16)


# --- to the Amiga, which keeps the join --------------------------------------
def _amiga(tmp_path):
    neutral = dos_codec.to_neutral(_read(tmp_path, _pack_file(), 3))
    built, report = amiga_later.write_later(neutral, SILVER_BLADES_DELTAS)
    return neutral, built, report


def test_dos_to_amiga_writes_the_head_and_then_its_scrolls(tmp_path):
    _neutral, built, _report = _amiga(tmp_path)
    block = built.block_bytes()
    size = SILVER_BLADES_DELTAS.item_size
    nodes = [block[SILVER_BLADES_DELTAS.record_size + n * size:][:size]
             for n in range(5)]
    assert [n[0x2E] for n in nodes] == [18, 0x49, 0x27, 0x27, 5]
    assert nodes[1][0x3A] == 2                    # the head's quantity
    # `next` is set on heads only: the loader tests the head's own to decide
    # whether another head follows, and reads the scrolls by the count.
    assert [bool(int.from_bytes(n[0x2A:0x2E], "big")) for n in nodes] == \
        [True, True, False, False, False]
    count_at = SILVER_BLADES_DELTAS.offset(
        SILVER_BLADES_DELTAS.dos_field("item_count").offset)
    assert block[count_at] == 3


def test_every_byte_of_the_amiga_block_is_accounted_for(tmp_path):
    _neutral, built, report = _amiga(tmp_path)
    block = built.block_bytes()
    assert report.total == len(block)
    assert [i for i in range(len(block)) if i not in report.sources] == []


def test_amiga_to_dos_gives_back_the_joined_scroll(tmp_path):
    """DOS -> Amiga -> DOS: the joined scroll and the plate mail after it
    both arrive, and the item file is the one DOS -> DOS writes."""
    neutral, built, _report = _amiga(tmp_path)
    char, end = amiga_later._amiga_block(built.block_bytes(), 0,
                                         SILVER_BLADES_DELTAS)
    assert end == len(built.block_bytes())
    back = amiga_later.to_neutral_later(char)
    assert back.get("scroll_bundles") == neutral.get("scroll_bundles")
    assert back.get("inventory") == neutral.get("inventory")
    direct = dos_codec.write(neutral, deltas=SSB)[1]
    assert dos_codec.write(back, deltas=SSB)[1] == direct


def test_a_block_whose_joined_scroll_runs_off_the_data_is_refused(tmp_path):
    _neutral, built, _report = _amiga(tmp_path)
    block = built.block_bytes()
    cut = SILVER_BLADES_DELTAS.record_size + 3 * SILVER_BLADES_DELTAS.item_size
    with pytest.raises(amiga_later.AmigaRecordError, match="joined scroll"):
        amiga_later._amiga_block(block[:cut], 0, SILVER_BLADES_DELTAS)


# --- the neutral record's own checks -----------------------------------------
def test_a_bundle_that_is_not_a_run_of_scrolls_is_refused():
    inventory = [bytes(dos_codec.item_to_c64(bytes(SWORD)))]
    head = bytes((0x49,)) + bytes(15)
    with pytest.raises(dos_codec.DosRecordError, match="not a run of scrolls"):
        dos_codec.bundled_item_units(inventory, [ScrollBundle(0, 1, head)],
                                     STRIDE)


def test_a_63_byte_title_writes_the_scrolls_as_items_of_their_own():
    scrolls = [dos_codec.item_to_c64(bytes(s[:63]))
               for s in (SCROLL_A, SCROLL_B)]
    head = bytes((0x49, 0x27, 2, 0x4D)) + bytes(12)
    units = dos_codec.bundled_item_units(scrolls, [ScrollBundle(0, 2, head)],
                                         dos_port.ITEM_SIZE)
    assert [len(records) for _head, records in units] == [1, 1]


# --- the editor writing a DOS or Amiga save back in place --------------------
def test_a_dos_save_with_nothing_edited_is_written_back_byte_for_byte(tmp_path):
    char = _read(tmp_path, _pack_file(), 3)
    rec, _ = dos_codec.to_c64_record(char)
    out = rewrite.rewrite_dos(char, rec, rec, GAME)
    assert out.items == _pack_file()
    assert out.record == char.to_bytes()


def test_an_edit_elsewhere_leaves_the_joined_scroll_whole(tmp_path):
    char = _read(tmp_path, _pack_file(), 3)
    rec, _ = dos_codec.to_c64_record(char)
    after = c64_codec.CharacterRecord(rec.to_bytes(), rec.stored_size)
    after.gold = 1234
    out = rewrite.rewrite_dos(char, rec, after, GAME)
    assert out.items == _pack_file()


def test_deleting_a_scroll_on_the_sheet_leaves_the_other_one_whole(tmp_path):
    """The sheet shows the two scrolls in two slots; deleting the first
    leaves a scroll that is no longer joined to anything, so it is written
    as a scroll of its own and the head goes with the join."""
    char = _read(tmp_path, _pack_file(), 3)
    rec, _ = dos_codec.to_c64_record(char)
    raw = bytearray(rec.get_raw("inventory"))
    raw[16:32] = bytes(16)                          # the first scroll
    after = c64_codec.CharacterRecord(rec.to_bytes(), rec.stored_size)
    after.set_raw("inventory", bytes(raw))
    out = rewrite.rewrite_dos(char, rec, after, GAME)
    items = dos_codec.item_nodes(out.items, STRIDE)
    assert [it.get("type_index") for it in items] == [18, 0x27, 5]
    assert items[1].get("charges") == 4
    kept = items[1].to_bytes()
    assert not any(kept[0x2A:0x2E]) and not any(kept[0x3F:0x43])
    count = dos_port.FIELDS_BY_NAME_FOR[SSB.key]["item_count"].offset
    assert out.record[count] == 3


def test_an_amiga_save_with_nothing_edited_is_written_back_byte_for_byte(
        tmp_path):
    _neutral, built, _report = _amiga(tmp_path)
    char, _end = amiga_later._amiga_block(built.block_bytes(), 0,
                                          SILVER_BLADES_DELTAS)
    rec, _ = dos_codec.neutral_to_c64_record(amiga_later.to_neutral_later(char))
    out = rewrite.rewrite_amiga_later(char, rec, rec, GAME)
    assert out.character.block_bytes() == char.block_bytes()


# --- a whole saved game, off the archives' shipped Silver Blades party -------
def _shipped_party():
    from support.dossave import _game_dirs
    folder = _game_dirs().get("SECRET")
    if folder is None or not (folder / "SAVGAMA.DAT").is_file():
        pytest.skip("needs the archives' shipped Silver Blades saves")
    return folder


def _with_joined_scrolls(folder, tmp_path, bundles: int, per: int):
    """The shipped party, the first character's pack replaced by `bundles`
    joined scrolls of `per` composed scrolls each -- on the neutral record,
    so the shipped files are only read."""
    from goldbox import dos_savegame, world_state
    container = dos_savegame.container_for(SSB.key)
    dos = (folder / f"SAVGAMA{container.suffix}").read_bytes()
    party = [dos_codec.to_neutral(c)
             for c in dos_codec.read_party(folder, "A")]
    scroll = dos_codec.item_to_c64(bytes(SCROLL_A))
    head = bytes((0x49, 0x27, per, 0x4D)) + bytes(12)
    party[0].set("inventory", [scroll] * (bundles * per), "composed")
    party[0].set("scroll_bundles",
                 tuple(ScrollBundle(n * per, per, head)
                       for n in range(bundles)), "composed")
    return world_state.from_dos(dos, container), party


def test_a_party_holding_120_joined_scrolls_converts_to_an_amiga_save(
        tmp_path):
    state, party = _with_joined_scrolls(_shipped_party(), tmp_path, 12, 10)
    built, report = amiga_savegame.new_savegame(state, party, "A")
    assert report.unwritten == []
    save = amiga_savegame.parse(built, amiga_savegame.container_for(SSB.key))
    first = save.characters[0]
    assert [len(it.subnodes) for it in first.items] == [10] * 12
    assert amiga_later.to_neutral_later(first).get("inventory") == \
        party[0].get("inventory")


def test_a_party_the_amiga_loader_would_cut_short_is_not_written(tmp_path):
    """Over 120 scrolls in joined scrolls the loader throws a joined scroll
    away (`/Secret` `0x269C2`), so the writer stops rather than write it."""
    state, party = _with_joined_scrolls(_shipped_party(), tmp_path, 13, 10)
    with pytest.raises(amiga_savegame.AmigaSaveError, match="130 scrolls"):
        amiga_savegame.new_savegame(state, party, "A")
