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
machine holds a joined scroll (`tools/dos/dosscrollbundle.py sweep`).  The
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


def _joined(*scrolls: bytearray, readied: bool = False) -> bytes:
    """A joined scroll as the `.STF` file holds it: the head JOIN makes, then
    each scroll copied whole, every node but the last pointing on."""
    head = _item(dos_codec.SCROLL_BUNDLE_TYPE, weight=len(scrolls),
                 quantity=len(scrolls),
                 value=sum(int.from_bytes(s[0x3A:0x3C], "little")
                           for s in scrolls))
    head[F["readied"].offset] = int(readied)
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
    """A sword, a joined scroll of two, and plate mail after it: the file holds
    five records for three heads, and `item_count` is three."""
    return bytes(SWORD) + _joined(SCROLL_A, SCROLL_B) + bytes(PLATE)


def _read(tmp_path, itm: bytes, count: int) -> dos_codec.DosCharacter:
    path = tmp_path / "CHRDATA1.SAV"
    path.write_bytes(_record(count))
    (tmp_path / "CHRDATA1.STF").write_bytes(itm)
    return dos_codec.read_character(path)


def _spells(block: bytes) -> tuple[int, int, int]:
    return block[13], block[14], block[15]


def _slots(rec) -> list[bytes]:
    """The occupied slots in the order the C64 screen draws them, slot 15
    first."""
    raw = rec.get_raw("inventory")
    return [raw[n * 16:(n + 1) * 16] for n in reversed(range(16))
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
    """The DOS recount walks the head items only (`0x3A2C7`), so the scrolls
    behind the head add nothing of their own.  That the head itself weighs
    `weight x quantity`, 2 x 2 here, is UNVERIFIED: the routine has not been
    read for it, so this pins the project's own formula and not the engine's."""
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


def test_an_export_beside_a_file_holding_a_joined_scroll_reads_it(tmp_path):
    """The engine's loader reads the item file to its end whatever the count,
    so a count of 0 still gives the sword, the joined scroll and the plate."""
    char = _read(tmp_path, _pack_file(), 0)
    assert len(char.items) == 3
    assert [s.get("type_index") for s in char.items[1].subnodes] == [0x27, 0x27]


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


def _crowded(ordinary: int, scrolls: int) -> bytes:
    return (b"".join(bytes(_item(10 + n, weight=10)) for n in range(ordinary))
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
    raw[32:48] = bytes(16)        # the first scroll, in slot 2 of 0 to 3
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


def test_a_joined_scroll_across_slot_sixteen_is_written_back_whole(tmp_path):
    """Fifteen items and a joined pair: the second scroll is the seventeenth
    node, past the sheet's sixteen, and an edit elsewhere must still write
    the head and both scrolls."""
    original = _crowded(15, 2)
    char = _read(tmp_path, original, 16)
    rec, _ = dos_codec.to_c64_record(char)
    assert len(_slots(rec)) == 16
    after = c64_codec.CharacterRecord(rec.to_bytes(), rec.stored_size)
    after.gold = 1234
    out = rewrite.rewrite_dos(char, rec, after, GAME)
    assert out.items == original
    assert len(dos_codec.item_nodes(out.items, STRIDE)) == 16


def _amiga_char(tmp_path, live_in_scrolls: bool = False):
    """The Amiga character, optionally with a live `next` and chain pointer
    in each scroll, as a running game leaves them."""
    _neutral, built, _report = _amiga(tmp_path)
    block = bytearray(built.block_bytes())
    if live_in_scrolls:
        size = SILVER_BLADES_DELTAS.item_size
        for node in (2, 3):
            at = SILVER_BLADES_DELTAS.record_size + node * size
            for off in (amiga_later.AMIGA_LATER_ITEM_NEXT,
                        amiga_later.AMIGA_SSB_SCROLL_CHAIN):
                block[at + off:at + off + 4] = LIVE
    char, _end = amiga_later._amiga_block(bytes(block), 0,
                                          SILVER_BLADES_DELTAS)
    rec, _ = dos_codec.neutral_to_c64_record(amiga_later.to_neutral_later(char))
    return char, rec


def test_deleting_a_scroll_of_an_amiga_joined_scroll_leaves_the_other_alone(
        tmp_path):
    """The Amiga pack is a sword, a joined pair and plate mail; deleting the
    first scroll on the sheet leaves a scroll with no next and no chain."""
    char, rec = _amiga_char(tmp_path, live_in_scrolls=True)
    raw = bytearray(rec.get_raw("inventory"))
    raw[32:48] = bytes(16)        # the first scroll, in slot 2 of 0 to 3
    after = c64_codec.CharacterRecord(rec.to_bytes(), rec.stored_size)
    after.set_raw("inventory", bytes(raw))
    out = rewrite.rewrite_amiga_later(char, rec, after, GAME)
    items = out.character.items
    assert [it.get("type_index") for it in items] == [18, 0x27, 5]
    kept = items[1].raw
    assert items[1].get("charges") == 4
    nxt = amiga_later.AMIGA_LATER_ITEM_NEXT
    chain = amiga_later.AMIGA_SSB_SCROLL_CHAIN
    assert kept[nxt:nxt + 4] == bytes(4) and kept[chain:chain + 4] == bytes(4)


def test_an_amiga_edit_elsewhere_leaves_the_joined_scroll_bytes_alone(
        tmp_path):
    char, rec = _amiga_char(tmp_path)
    after = c64_codec.CharacterRecord(rec.to_bytes(), rec.stored_size)
    after.gold = 1234
    out = rewrite.rewrite_amiga_later(char, rec, after, GAME)
    size = SILVER_BLADES_DELTAS.item_size
    start = SILVER_BLADES_DELTAS.record_size
    assert out.character.block_bytes()[start:start + 5 * size] == \
        char.block_bytes()[start:start + 5 * size]


def test_an_amiga_to_c64_pack_over_sixteen_stops_the_write(tmp_path):
    """The neutral record's branch of the guard: fifteen items and a joined
    pair are seventeen scrolls and items for sixteen slots."""
    neutral = dos_codec.to_neutral(_read(tmp_path, _crowded(15, 2), 16))
    assert dos_codec.c64_slots_needed(neutral) == 17
    with pytest.raises(dos_codec.JoinedScrollsDoNotFit) as caught:
        dos_codec.write_c64_save(bytearray(0x1D00), None, None, [neutral])
    assert (caught.value.needed, caught.value.slots) == (17, 16)


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


# --- the player chooses what stays behind (#432) -----------------------------
A_SLOT = bytes.fromhex("27000000000000000100002c01010203")
B_SLOT = bytes.fromhex("27000000000000000100006400040000")
C_SLOT = bytes.fromhex("28000000000000000100 00c8000506 00".replace(" ", ""))


def _plain(n: int) -> bytes:
    return dos_codec.item_to_c64(bytes(_item(10 + n, weight=10)))


def _party_file(ordinary: int, *scrolls: bytearray) -> bytes:
    return (b"".join(bytes(_item(10 + n, weight=10)) for n in range(ordinary))
            + _joined(*scrolls))


def _named(tmp_path, name: str, ordinary: int, *scrolls: bytearray):
    """A neutral character holding `ordinary` items and one joined scroll."""
    char = dos_codec.to_neutral(
        _read(tmp_path, _party_file(ordinary, *scrolls), ordinary + 1))
    char.set("name", name, "made up")
    return char


def _write_save(party, leave=None):
    from goldbox import c64_save, world_state
    from goldbox import dos_savegame as sg
    container = sg.SAVE_SECRET_OF_THE_SILVER_BLADES
    savgam = bytearray(container.size)
    sg.put_word(savgam, sg.INDOORS, 1, container)
    sg.put_position(savgam, 7, 13, 0, container)
    state = world_state.from_dos(bytes(savgam), container)
    cont = c64_save.container_for(GAME)
    save0 = bytearray(cont.payload_size)
    report = dos_codec.write_c64_save(save0, None, state, party, game=GAME,
                                      leave=leave)
    return save0, cont, report


def _slots_by_name(save0, cont, name: str) -> list[bytes]:
    for place in range(8):
        at = cont.slot(place)
        if bytes(save0[at:at + len(name)]) == name.encode():
            at = cont.items(place)
            return [bytes(save0[at + n * 16:at + n * 16 + 16])
                    for n in reversed(range(16))]
    raise AssertionError(f"no slot holds {name}")


def _over_by_one(tmp_path):
    return _read(tmp_path, _party_file(15, SCROLL_A, SCROLL_B), 16)


def test_pack_overflow_lists_every_unit_of_the_member_who_does_not_fit(
        tmp_path):
    (over,) = dos_codec.pack_overflow([_over_by_one(tmp_path)])
    assert (over.members, over.needed, over.limit, over.over) == \
        ((0,), 17, 16, 1)
    assert [(u.kind, u.indices) for u in over.units] == \
        [("item", (n,)) for n in range(15)] + [
            ("joined", (15, 16)), ("scroll", (15,)), ("scroll", (16,))]
    assert over.units[-1].bundle == 0 and over.units[0].bundle is None
    assert len(over.items[0]) == 17


def test_pack_overflow_ignores_a_pack_without_a_joined_scroll_and_one_that_fits(
        tmp_path):
    assert dos_codec.pack_overflow(
        [_read(tmp_path, _crowded(14, 2), 15)]) == ()
    assert dos_codec.pack_overflow([_read(tmp_path, _pack_file(), 3)]) == ()


def test_pack_overflow_is_built_for_the_c64_and_the_amiga_only(tmp_path):
    with pytest.raises(ValueError):
        dos_codec.pack_overflow([_over_by_one(tmp_path)], port="dos")


def test_leave_behind_dissolves_a_joined_scroll_that_loses_a_scroll():
    a, b, c, ordinary = (bytes([n]) * 16 for n in (0x27, 0x28, 0x27, 9))
    head = bytes((0x49,)) + bytes(15)
    inventory = [ordinary, a, b, c, ordinary, a, b]
    bundles = (ScrollBundle(1, 3, head), ScrollBundle(5, 2, head))
    left, kept = dos_codec.leave_behind(inventory, bundles, {2})
    assert left == [ordinary, a, c, ordinary, a, b]
    assert kept == (ScrollBundle(4, 2, head),)
    left, kept = dos_codec.leave_behind(inventory, bundles, {0})
    assert kept == (ScrollBundle(0, 3, head), ScrollBundle(4, 2, head))
    with pytest.raises(dos_codec.DosRecordError):
        dos_codec.leave_behind(inventory, bundles, {7})


def test_no_choice_raises_and_names_every_member_who_does_not_fit(tmp_path):
    a = _named(tmp_path, "AAA", 15, SCROLL_A, SCROLL_B)
    b = _named(tmp_path, "BBB", 14, SCROLL_A, SCROLL_A)
    c = _named(tmp_path, "CCC", 14, SCROLL_A, SCROLL_B, SCROLL_C, SCROLL_A)
    with pytest.raises(dos_codec.JoinedScrollsDoNotFit) as caught:
        _write_save([a, b, c])
    exc = caught.value
    assert [o.members for o in exc.overflow] == [(0,), (2,)]
    assert [o.needed for o in exc.overflow] == [17, 18]
    assert (exc.name, exc.needed, exc.slots) == ("AAA", 17, 16)
    with pytest.raises(dos_codec.JoinedScrollsDoNotFit) as caught:
        _write_save([a, b, c], leave={0: {3}})
    assert [o.members for o in caught.value.overflow] == [(2,)]


@pytest.mark.parametrize("neutral", [False, True])
def test_leaving_one_item_writes_the_other_sixteen_slots(tmp_path, neutral):
    char = _over_by_one(tmp_path)
    party = [dos_codec.to_neutral(char)] if neutral else [char]
    save0, cont, report = _write_save(party, leave={0: {3}})
    name = "ROUNDTRIP"
    assert _slots_by_name(save0, cont, name) == \
        [_plain(n) for n in range(15) if n != 3] + [A_SLOT, B_SLOT]
    assert len(report.left_behind) == 1
    assert "inventory item 3" in report.left_behind[0]


@pytest.mark.parametrize("neutral", [False, True])
def test_leaving_one_scroll_of_the_pair_leaves_the_other_a_plain_scroll(
        tmp_path, neutral):
    char = _over_by_one(tmp_path)
    party = [dos_codec.to_neutral(char)] if neutral else [char]
    save0, cont, report = _write_save(party, leave={0: {15}})
    assert _slots_by_name(save0, cont, "ROUNDTRIP") == \
        [_plain(n) for n in range(15)] + [B_SLOT]
    assert report.left_behind[0].count("spells 1 2 3") == 1


def test_leaving_the_whole_pair_leaves_the_sixteenth_slot_empty(tmp_path):
    save0, cont, report = _write_save([_over_by_one(tmp_path)],
                                      leave={0: {15, 16}})
    assert _slots_by_name(save0, cont, "ROUNDTRIP") == \
        [bytes(16)] + [_plain(n) for n in range(15)]
    assert len(report.left_behind) == 2


def test_two_members_overflowing_are_each_cut_and_the_third_is_untouched(
        tmp_path):
    a = _named(tmp_path, "AAA", 15, SCROLL_A, SCROLL_B)
    b = _named(tmp_path, "BBB", 14, SCROLL_A, SCROLL_A)
    c = _named(tmp_path, "CCC", 14, SCROLL_A, SCROLL_B, SCROLL_C, SCROLL_A)
    save0, cont, report = _write_save([a, b, c],
                                      leave={0: {3}, 2: {14, 15}})
    assert _slots_by_name(save0, cont, "AAA") == \
        [_plain(n) for n in range(15) if n != 3] + [A_SLOT, B_SLOT]
    assert _slots_by_name(save0, cont, "BBB") == \
        [_plain(n) for n in range(14)] + [A_SLOT, A_SLOT]
    assert _slots_by_name(save0, cont, "CCC") == \
        [_plain(n) for n in range(14)] + [C_SLOT, A_SLOT]
    assert len(report.left_behind) == 3
    assert not any("inventory" in line
                   for line in report.losses + report.dropped)
    assert not any("left behind" in w for w in report.warnings)


def test_a_choice_for_a_member_who_fits_or_out_of_range_is_refused(tmp_path):
    a = _named(tmp_path, "AAA", 15, SCROLL_A, SCROLL_B)
    b = _named(tmp_path, "BBB", 14, SCROLL_A, SCROLL_A)
    with pytest.raises(dos_codec.DosRecordError, match="fits"):
        _write_save([a, b], leave={1: {0}, 0: {3}})
    with pytest.raises(dos_codec.DosRecordError):
        _write_save([a, b], leave={0: {17}})


# --- the Amiga loader keeps 120 scrolls in joined scrolls, so unjoin first ---
def _scroll(n: int, *, readied: bool = False) -> bytearray:
    """A scroll of its own weight 10 with spells that tell it from the rest."""
    out = _item(0x27, spells=(1 + n % 117, 0, 0), weight=10, value=300 + n)
    out[F["hidden"].offset] = 4
    out[F["readied"].offset] = int(readied)
    return out


def _party_member(tmp_path, name: str, *units: bytes):
    """A neutral character whose pack is `units`, each a whole item or a
    joined scroll as the `.STF` file holds it."""
    char = dos_codec.to_neutral(_read(tmp_path, b"".join(units), len(units)))
    char.set("name", name, "made up")
    return char


def _bundle_of(n: int, first: int, *, readied: bool = False) -> bytes:
    return _joined(*[_scroll(first + k) for k in range(n)], readied=readied)


STAFF = bytes(_item(21, weight=40, value=10))


def _specimen_u(tmp_path, *, readied: bool = False):
    """Specimen U's party: PAINE twelve joined scrolls of ten, one of two and
    the staff; Guy one of three; a third member two loose scrolls."""
    paine = _party_member(
        tmp_path, "PAINE",
        *[_bundle_of(10, 10 * k, readied=readied) for k in range(12)],
        _bundle_of(2, 120, readied=readied), STAFF)
    guy = _party_member(tmp_path, "GUY", _bundle_of(3, 130, readied=readied))
    third = _party_member(tmp_path, "THIRD", bytes(_scroll(140)),
                          bytes(_scroll(141)))
    return [paine, guy, third]


def _fresh_state():
    from goldbox import dos_savegame, world_state
    container = dos_savegame.container_for(SSB.key)
    return world_state.from_dos(bytes(container.size), container)


def _amiga_party(built: bytes):
    return amiga_savegame.parse(
        built, amiga_savegame.container_for(SSB.key)).characters


def _dos_weight(raw: bytes) -> int:
    """`weight x (quantity or 1)` of one DOS-layout item, the engine's own sum
    for a pack: a joined scroll's head counts and its scrolls do not."""
    return (int.from_bytes(raw[F["weight"].offset:F["weight"].offset + 2],
                           "little") * (raw[F["quantity"].offset] or 1))


def _sixteen_weight(raw: bytes) -> int:
    """`_dos_weight` of an item as the neutral pack holds it, sixteen bytes."""
    return int.from_bytes(raw[8:10], "little") * (raw[10] or 1)


def test_unjoin_gives_each_scroll_the_heads_weight_and_readied_flag():
    scrolls = [bytes(_scroll(n)) for n in range(3)]
    inventory = [dos_codec.item_to_c64(s) for s in scrolls]
    head = dos_codec.item_to_c64(bytes(_item(
        dos_codec.SCROLL_BUNDLE_TYPE, weight=3, quantity=3)))
    head = bytearray(head)
    head[6] |= 0x80
    bundle = ScrollBundle(0, 3, bytes(head))
    out, left = dos_codec.unjoin(inventory, (bundle,), {0})
    assert left == ()
    for before, after in zip(inventory, out):
        assert after[8:10] == bytes((3, 0)) and after[6] & 0x80
        assert after[6] & 0x7F == before[6] & 0x7F == 4
        assert after[:6] == before[:6] and after[10:] == before[10:]
        assert after[13:] == before[13:]
    # An unreadied head clears the flag on scrolls that held it.
    head[6] &= 0x7F
    held = [bytes(r) for r in inventory]
    held[0] = held[0][:6] + bytes((held[0][6] | 0x80,)) + held[0][7:]
    out, _left = dos_codec.unjoin(held, (bundle._replace(head=bytes(head)),),
                                  {0})
    assert not any(r[6] & 0x80 for r in out)
    with pytest.raises(dos_codec.DosRecordError):
        dos_codec.unjoin(inventory, (bundle,), {1})


def test_the_choice_takes_the_joined_scrolls_of_two_and_three_never_ten(
        tmp_path):
    party = _specimen_u(tmp_path)
    assert dos_codec.amiga_unjoin_choice(party) == {0: (12,), 1: (0,)}


def test_a_party_at_exactly_the_limit_is_left_alone(tmp_path):
    party = [_party_member(
        tmp_path, "PAINE", *[_bundle_of(10, 10 * k) for k in range(12)])]
    assert dos_codec.amiga_unjoin_choice(party) == {}
    assert dos_codec.pack_overflow(party, "amiga") == ()
    same, lines = dos_codec.unjoined_for_amiga(party)
    assert lines == [] and all(a is b for a, b in zip(same, party))
    built, report = amiga_savegame.new_savegame(_fresh_state(), party, "A")
    assert report.unjoined == []
    (char,) = _amiga_party(built)
    expected, _ = amiga_later.write_later(
        amiga_savegame._at_figure_slot(party[0], 0), SILVER_BLADES_DELTAS)
    assert char.block_bytes() == expected.block_bytes()


def test_the_limit_is_read_when_the_choice_is_made(tmp_path, monkeypatch):
    party = _specimen_u(tmp_path)
    monkeypatch.setattr(amiga_later, "AMIGA_SSB_JOINED_SCROLL_LIMIT", 123)
    # Two scrolls out, and the pair is the cheaper row than the three.
    assert dos_codec.amiga_unjoin_choice(party) == {0: (12,)}
    # Seven out is more than the pair and the three, and a joined scroll of
    # ten needs nine rows PAINE has not got.
    monkeypatch.setattr(amiga_later, "AMIGA_SSB_JOINED_SCROLL_LIMIT", 118)
    assert dos_codec.amiga_unjoin_choice(party) is None


def test_specimen_u_converts_and_every_scroll_arrives(tmp_path):
    party = _specimen_u(tmp_path)
    built, report = amiga_savegame.new_savegame(_fresh_state(), party, "A")
    paine, guy, third = _amiga_party(built)
    assert amiga_later.joined_scroll_count([paine, guy, third]) == 120
    assert [len(it.subnodes) for it in paine.items] == \
        [10] * 12 + [0, 0, 0]
    assert [len(it.subnodes) for it in guy.items] == [0, 0, 0]
    assert len(report.unjoined) == 2 and report.losses == []
    # The unjoined scrolls are loose, each keeping its spells, value and
    # hidden byte, with the head's weight (the scroll count) in place of its
    # own 10.
    for char, first, count in ((paine, 120, 2), (guy, 130, 3)):
        loose = [bytes(it.to_dos_bytes()) for it in char.items
                 if not it.subnodes and it.raw[0x2E] == 0x27]
        assert len(loose) == count
        for n, raw in enumerate(loose):
            want = _scroll(first + n)
            assert raw[F["charges"].offset] == want[F["charges"].offset]
            assert raw[F["value"].offset:F["value"].offset + 2] == \
                want[F["value"].offset:F["value"].offset + 2]
            assert raw[F["hidden"].offset] == 4
            assert raw[F["weight"].offset] == count
    # The Amiga's own sum, a scroll apiece, comes to the DOS sum, a head
    # times its quantity: the encumbrance neither port draws on a screen
    # stays where the source put it.
    for char, source in zip((paine, guy), party):
        amiga_sum = sum(_dos_weight(it.to_dos_bytes()) for it in char.items)
        dos_sum = sum(
            _sixteen_weight(bytes(b.head)) for b in source.get("scroll_bundles")
        ) + sum(_sixteen_weight(bytes(raw)) for n, raw in
                enumerate(source.get("inventory"))
                if not any(b.first <= n < b.first + b.count
                           for b in source.get("scroll_bundles")))
        assert amiga_sum == dos_sum


def test_an_unjoined_readied_scroll_stays_readied(tmp_path):
    party = _specimen_u(tmp_path, readied=True)
    built, _report = amiga_savegame.new_savegame(_fresh_state(), party, "A")
    _paine, guy, _third = _amiga_party(built)
    scrolls = [it for it in guy.items if it.raw[0x2E] == 0x27]
    assert len(scrolls) == 3
    assert all(it.to_dos_bytes()[F["readied"].offset] for it in scrolls)


def test_the_unjoin_is_on_the_provenance_of_the_pack(tmp_path):
    party = _specimen_u(tmp_path)
    (paine, guy, third), lines = dos_codec.unjoined_for_amiga(party)
    assert "unjoined" in paine.fields["inventory"].origin
    assert "unjoined" in guy.fields["inventory"].origin
    assert "scroll_bundles" not in guy.fields
    assert len(paine.get("scroll_bundles")) == 12
    assert third is party[2] and len(lines) == 2


def _specimen_l(tmp_path):
    """PAINE: twelve joined scrolls of ten, one of two and three ordinary
    items, sixteen rows, so the pair cannot be unjoined without a free row."""
    return [_party_member(
        tmp_path, "PAINE",
        *[_bundle_of(10, 10 * k) for k in range(12)], _bundle_of(2, 120),
        *[bytes(_item(10 + n, weight=10)) for n in range(3)])]


def test_a_party_no_unjoin_can_fit_is_refused_with_what_it_needs(tmp_path):
    party = _specimen_l(tmp_path)
    assert dos_codec.amiga_unjoin_choice(party) is None
    (over,) = dos_codec.pack_overflow(party, "amiga")
    assert (over.port, over.scope, over.members, over.limit, over.needed) == \
        ("amiga", "party", (0,), 120, 122)
    assert [u.kind for u in over.units].count("joined") == 13
    with pytest.raises(amiga_savegame.AmigaJoinedScrollsDoNotFit) as raised:
        amiga_savegame.new_savegame(_fresh_state(), party, "A")
    assert raised.value.needed == 122 and raised.value.overflow == over
    # It is not the C64's class, which the editor answers with a window for
    # one character.
    assert not isinstance(raised.value, dos_codec.JoinedScrollsDoNotFit)


def test_leaving_one_ordinary_item_lets_the_pair_be_unjoined(tmp_path):
    party = _specimen_l(tmp_path)
    ordinary = len(party[0].get("inventory")) - 1
    assert dos_codec.pack_overflow(party, "amiga", {0: {ordinary}}) == ()
    built, report = amiga_savegame.new_savegame(
        _fresh_state(), party, "A", leave={0: {ordinary}})
    (paine,) = _amiga_party(built)
    assert amiga_later.joined_scroll_count([paine]) == 120
    assert len(report.unjoined) == 1
    assert [bool(it.subnodes) for it in paine.items] == \
        [True] * 12 + [False, False, False, False]


def test_a_choice_for_a_member_out_of_range_is_refused_for_the_amiga(tmp_path):
    with pytest.raises(dos_codec.DosRecordError):
        dos_codec.pack_overflow(_specimen_l(tmp_path), "amiga", {3: {0}})


# --- the engine's own specimens, from DOSBox, through Save As to the Amiga ---
def _save_as_amiga(tmp_path, name: str):
    from gamedata import specimen

    from editor import roster, saveplan
    from goldbox.amiga_adf import AmigaDisk
    from tools.convert import convertdrops

    ssb = c64_port.SECRET_OF_THE_SILVER_BLADES
    party = roster.Party(str(specimen(name) / "SAVGAMA.DAT"))
    amiga = convertdrops.amiga_game_disks(tmp_path).get(ssb.key)
    disk_one = convertdrops.amiga_disks_one(tmp_path).get(ssb.key)
    if amiga is None or disk_one is None:
        pytest.skip(f"needs {ssb.key}'s own Amiga disks")
    try:
        assets = saveplan.resolve_assets(party.source, "amiga",
                                         game_files=convertdrops.game_files,
                                         amiga_disk=amiga,
                                         amiga_disk_one=disk_one)
    except saveplan.MissingAssets:
        pytest.skip(f"needs {ssb.key}'s own C64 disks")
    plan = saveplan.prepare_save_as(party, "amiga", tmp_path / "out.adf",
                                    assets)
    (image,) = plan.files
    written = AmigaDisk(bytearray(plan.files[image]))
    chars = amiga_savegame.read_slot(written, "A", ssb.key).characters
    return plan, chars, party


def test_specimen_u_saved_as_amiga_holds_120_and_loses_nothing(tmp_path):
    plan, chars, _party = _save_as_amiga(tmp_path, "ssb-wish4-joined-u125")
    assert amiga_later.joined_scroll_count(chars) == 120
    assert len(plan.report.unjoined) == 2
    assert plan.report.losses == [] and plan.report.dropped == []
    paine = next(c for c in chars if c.name == "PAINE")
    assert [len(it.subnodes) for it in paine.items].count(10) == 12


def test_specimen_c_saved_as_amiga_unjoins_nothing(tmp_path):
    plan, chars, _party = _save_as_amiga(tmp_path, "ssb-wish4-joined-c115")
    assert amiga_later.joined_scroll_count(chars) == 115
    assert plan.report.unjoined == []


def test_specimen_l_saved_as_amiga_names_the_party_overflow(tmp_path):
    from gamedata import specimen
    with pytest.raises(amiga_savegame.AmigaJoinedScrollsDoNotFit) as raised:
        _save_as_amiga(tmp_path, "ssb-wish4-joined-l122")
    assert raised.value.needed == 122
    assert specimen("ssb-wish4-joined-l122")


def _through_save_as_drive(tmp_path, name: str) -> dict:
    """`tools/convert/saveasdrive` Save As of an engine-written specimen to a
    new Amiga disk, the route the driven acceptance tools use."""
    from conftest import load_tools_module
    from gamedata import specimen

    from tools.convert import convertdrops

    ssb = c64_port.SECRET_OF_THE_SILVER_BLADES
    amiga = convertdrops.amiga_game_disks(tmp_path).get(ssb.key)
    disk_one = convertdrops.amiga_disks_one(tmp_path).get(ssb.key)
    if amiga is None or disk_one is None:
        pytest.skip(f"needs {ssb.key}'s own Amiga disks")

    class Window:
        game_files_for = staticmethod(convertdrops.game_files)

    return load_tools_module("saveasdrive").save_as(
        Window(), specimen(name) / "SAVGAMA.DAT", "amiga", tmp_path / "out",
        amiga_disk=amiga, amiga_disk_one=disk_one, source_slot="A")


def test_save_as_drive_reports_the_unjoined_scrolls_of_specimen_u(tmp_path):
    report = _through_save_as_drive(tmp_path, "ssb-wish4-joined-u125")
    if report.get("refused", [""])[0] == "MissingAssets":
        pytest.skip("needs the player's Silver Blades disks")
    assert "refused" not in report, report
    assert len(report["unjoined"]) == 2
    assert report["losses"] == [] and report["left_behind"] == []


def test_save_as_drive_reports_nothing_unjoined_for_specimen_c(tmp_path):
    report = _through_save_as_drive(tmp_path, "ssb-wish4-joined-c115")
    if report.get("refused", [""])[0] == "MissingAssets":
        pytest.skip("needs the player's Silver Blades disks")
    assert "refused" not in report, report
    assert report["unjoined"] == []


def test_save_as_drive_stops_specimen_l_naming_the_party_overflow(tmp_path):
    report = _through_save_as_drive(tmp_path, "ssb-wish4-joined-l122")
    if report.get("refused", [""])[0] == "MissingAssets":
        pytest.skip("needs the player's Silver Blades disks")
    assert report["refused"][0] == "AmigaJoinedScrollsDoNotFit"
    assert "122" in report["refused"][1] and "written" not in report
