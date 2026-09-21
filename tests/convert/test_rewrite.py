from __future__ import annotations

"""The differential rewrite: an edited character goes back into its own save
without converting the fields nobody touched (#511).

`goldbox/rewrite.py` renders the character twice -- once as it was read, once
as it was edited -- and copies only the spans the two renderings disagree
about.  Two things follow and this file holds both:

* **a save with no edit in it is byte-identical**, on every specimen on this
  machine and on synthetic records that need none;
* **an edited field lands, and nothing else moves** -- including a field the
  writer renders differently from the engine's own bytes, which keeps the
  engine's.  `docs/223-the-differential-rewrite.md` is the census of where
  those are.

The synthetic half needs no game data at all: a neutral character goes
through the port's own writer to make the "engine's" record, so the fixture
is generated rather than a slice of anybody's save.
"""

import pytest
from gamedata import needs_specimens, specimen_root
from support.neutralrecords import _filled

from goldbox import (
    amiga_later,
    amiga_por,
    amiga_savegame,
    c64_codec,
    c64_port,
    dos_codec,
    dos_port,
    rewrite,
)
from goldbox.amiga_adf import AmigaDisk
from goldbox.amiga_port import CURSE_DELTAS, SILVER_BLADES_DELTAS
from goldbox.iconparts import amiga_combat_icon

DOS_TITLES = (dos_port.POOL_OF_RADIANCE,
              dos_port.CURSE_OF_THE_AZURE_BONDS,
              dos_port.SECRET_OF_THE_SILVER_BLADES)


# --- making a character with no game data at all ----------------------------
def _game(deltas):
    return c64_port.by_key(deltas.key)


def _blocks(count: int) -> list[bytes]:
    """`count` distinct C64 item blocks, each a different item.

    Byte 0 is `type_index` and 1 to 3 the three name words, which together
    say which item a slot holds; the weight and the quantity are what
    `encumbrance` is computed from.
    """
    out = []
    for n in range(count):
        block = bytearray(c64_codec.ITEM_SIZE)
        block[0] = 10 + n
        block[1], block[2], block[3] = 20 + n, 30 + n, 40 + n
        block[8:10] = (10 * (n + 1)).to_bytes(2, "little")   # weight
        block[10] = 1                                        # quantity
        block[11:13] = (5 * (n + 1)).to_bytes(2, "little")   # value
        out.append(bytes(block))
    return out


def _neutral(game, items: int):
    neutral = _filled(game)
    neutral.set("inventory", _blocks(items), "made up")
    return neutral


def _synthetic_dos(deltas, items: int = 1):
    """A DOS character and the C64 record the editor would build from it.

    The record is what the DOS writer itself makes of a filled neutral
    character, so nothing here is a copy of anybody's save.
    """
    neutral = _neutral(_game(deltas), items)
    record, itm, spc, _rep = dos_codec.write(neutral, deltas=deltas)
    stride = deltas.item_size
    items = [dos_codec.DosItem(itm[n * stride:(n + 1) * stride], stride)
             for n in range(len(itm) // stride)]
    effects = [spc[n * dos_port.EFFECT_SIZE:(n + 1) * dos_port.EFFECT_SIZE]
               for n in range(len(spc) // dos_port.EFFECT_SIZE)]
    char = dos_codec.DosCharacter(record, items=items, effects=effects,
                                  deltas=deltas)
    rec, _ = dos_codec.to_c64_record(char)
    return char, rec


def _synthetic_amiga_por(items: int = 1):
    pool = _game(dos_port.POOL_OF_RADIANCE)
    record, itm, spc, _rep = amiga_por.write_por(_neutral(pool, items))
    char = amiga_por.por_character(record, itm, spc)
    rec, _ = dos_codec.to_c64_record(amiga_por.to_dos_character(char))
    return char, rec


def _synthetic_amiga_later(deltas, items: int = 1):
    char, _rep = amiga_later.write_later(_neutral(_game(deltas.dos), items),
                                         deltas=deltas)
    rec, _ = dos_codec.neutral_to_c64_record(
        amiga_later.to_neutral_later(char))
    return char, rec


def _edited(rec, **fields):
    """A copy of the record with those fields set."""
    out = c64_codec.CharacterRecord(rec.to_bytes(), rec.stored_size)
    for name, value in fields.items():
        setattr(out, name, value)
    return out


def _moved(original: bytes, written: bytes, spans) -> set[str]:
    return {s.name for s in spans
            if original[s.at:s.at + s.size] != written[s.at:s.at + s.size]}


def _gold_moves(deltas) -> set[str]:
    """What a gold edit is expected to move, and why each one.

    `encumbrance` is money plus item weight times quantity, which the DOS
    engine itself rebuilds, so a coin edit moves it; `unnamed_0ab` is
    `goldbox.dos_codec.identity_byte`, a digest of every other byte of the
    record, so any edit at all moves it -- on the two later titles, which
    are the ones that write it.  Pool of Radiance declares the field and
    drops it, writing zero, so no edit moves it there.

    **That the identity byte moves is a choice rather than a proof.**  The
    engine drew its byte at random when the character was made and reads it
    only to tell two same-named characters apart; writing a digest over it
    keeps a save converting to the same bytes twice running and costs about
    one chance in 256 of a collision.  Never copying the span is the other
    choice, and this test pins whichever one the code makes rather than
    arguing it is right -- `docs/223-the-differential-rewrite.md`.
    """
    later = deltas is not dos_port.POOL_OF_RADIANCE
    return {"gold", "encumbrance"} | ({"unnamed_0ab"} if later else set())


# --- the span maps ----------------------------------------------------------
def test_every_dos_field_has_a_span_on_every_title():
    """A DOS record is the layout and nothing else, so nothing is unplaced --
    the second list is empty and the first tiles the table."""
    for deltas in DOS_TITLES:
        spans, unplaced = rewrite.dos_spans(deltas)
        assert unplaced == []
        table = dos_port.FIELDS_BY_NAME_FOR[deltas.key]
        assert {s.name for s in spans} == set(table)
        for span in spans:
            assert (span.at, span.size) == (table[span.name].offset,
                                            table[span.name].size)


def test_every_amiga_pool_field_has_a_span():
    """All three insertions are located, so every DOS field has an Amiga
    offset to copy to -- `field_83_87` included, at 0x084 for five bytes."""
    spans, unplaced = rewrite.amiga_por_spans()
    assert unplaced == []
    assert rewrite.Span("field_83_87", 0x084, 5) in spans
    assert ("name", 0, amiga_por.AMIGA_POR_NAME_SIZE) in spans


def test_the_silver_blades_spellbook_is_its_own_bitmask_span():
    """Silver Blades packs DOS's 117 flag bytes into fifteen of mask, so the
    span is the Amiga's own run rather than a shifted DOS one."""
    spans, _unplaced = rewrite.amiga_later_spans(SILVER_BLADES_DELTAS)
    book = next(s for s in spans if s.name == "spellbook")
    assert book.at == amiga_later.AMIGA_SSB_SPELLBOOK_AT
    assert book.size == SILVER_BLADES_DELTAS.spellbook_bytes

    curse = rewrite.amiga_later_spans(CURSE_DELTAS)[0]
    book = next(s for s in curse if s.name == "spellbook")
    assert book.size == CURSE_DELTAS.dos_field("spellbook").size


# --- the no-op, on records that need no game data ---------------------------
@pytest.mark.parametrize("deltas", DOS_TITLES, ids=lambda d: d.key)
def test_a_synthetic_dos_no_op_rewrite_returns_the_original_bytes(deltas):
    char, rec = _synthetic_dos(deltas)
    out = rewrite.rewrite_dos(char, rec, rec, _game(deltas))
    assert out.record == char.to_bytes()
    assert out.items == b"".join(rewrite.node_bytes(i) for i in char.items)
    assert out.effects == b"".join(bytes(e) for e in char.effects)


def test_a_synthetic_amiga_pool_no_op_rewrite_returns_the_original_bytes():
    char, rec = _synthetic_amiga_por()
    out = rewrite.rewrite_amiga_por(
        char, rec, rec, _game(dos_port.POOL_OF_RADIANCE))
    assert out.record == char.raw
    assert out.items == b"".join(rewrite.node_bytes(i) for i in char.items)
    assert out.effects == b"".join(bytes(e) for e in char.effects)
    assert out.moved == ()


@pytest.mark.parametrize("deltas", (CURSE_DELTAS, SILVER_BLADES_DELTAS),
                         ids=lambda d: d.key)
def test_a_synthetic_amiga_later_no_op_rewrite_returns_the_original(deltas):
    char, rec = _synthetic_amiga_later(deltas)
    out = rewrite.rewrite_amiga_later(char, rec, rec, _game(deltas.dos))
    assert out.character.raw == char.raw
    assert out.character.block_bytes() == char.block_bytes()
    assert out.moved == ()


# --- an edit lands, and nothing else moves ----------------------------------
@pytest.mark.parametrize("deltas", DOS_TITLES, ids=lambda d: d.key)
def test_an_edited_field_reaches_the_dos_record_and_nothing_else(deltas):
    """Gold on the sheet becomes gold in the record, read back through the
    DOS reader's own neutral conversion, and the only bytes that moved are
    that field's."""
    char, before = _synthetic_dos(deltas)
    after = _edited(before, gold=4321)
    out = rewrite.rewrite_dos(char, before, after, _game(deltas))

    written = dos_codec.DosCharacter(out.record, items=char.items,
                                     effects=char.effects, deltas=deltas)
    assert written.get("gold") == 4321
    assert dos_codec.to_neutral(written).get("gold") == 4321

    spans, _unplaced = rewrite.dos_spans(deltas)
    assert _moved(char.to_bytes(), out.record, spans) == _gold_moves(deltas)


def test_an_edited_field_reaches_an_amiga_pool_record_and_nothing_else():
    char, before = _synthetic_amiga_por()
    after = _edited(before, gold=4321)
    out = rewrite.rewrite_amiga_por(
        char, before, after, _game(dos_port.POOL_OF_RADIANCE))

    written = amiga_por.AmigaPorCharacter.from_bytes(out.record)
    assert written.get("gold") == 4321
    spans, _unplaced = rewrite.amiga_por_spans()
    assert _moved(char.raw, out.record, spans) == \
        _gold_moves(dos_port.POOL_OF_RADIANCE)


@pytest.mark.parametrize("deltas", (CURSE_DELTAS, SILVER_BLADES_DELTAS),
                         ids=lambda d: d.key)
def test_an_edited_field_reaches_an_amiga_later_record_and_nothing_else(
        deltas):
    char, before = _synthetic_amiga_later(deltas)
    after = _edited(before, gold=4321)
    out = rewrite.rewrite_amiga_later(char, before, after, _game(deltas.dos))

    written = out.character
    assert written.get("gold") == 4321
    assert amiga_later.to_neutral_later(written).get("gold") == 4321
    spans, _unplaced = rewrite.amiga_later_spans(deltas)
    assert _moved(char.raw, written.raw, spans) == _gold_moves(deltas.dos)


@pytest.mark.parametrize("deltas", DOS_TITLES, ids=lambda d: d.key)
def test_the_engines_own_bytes_survive_a_field_the_writer_disagrees_with(
        deltas):
    """The whole point of the differential.  `save_breath` is a field the
    census finds the writer renders differently from the engine's byte on
    real saves; here the original's byte is set to something the writer
    would never produce, an unrelated field is edited, and the engine's byte
    is still there afterwards."""
    char, before = _synthetic_dos(deltas)
    table = dos_port.FIELDS_BY_NAME_FOR[deltas.key]
    span = table["save_breath"]
    tampered = bytearray(char.to_bytes())
    tampered[span.offset] ^= 0x5A
    engine = dos_codec.DosCharacter(bytes(tampered), items=char.items,
                                    effects=char.effects, deltas=deltas)

    after = _edited(before, gold=99)
    out = rewrite.rewrite_dos(engine, before, after, _game(deltas))
    assert out.record[span.offset] == tampered[span.offset]
    assert out.record[span.offset] != char.to_bytes()[span.offset]


# --- items ------------------------------------------------------------------
def _with_item(rec, slot: int, block: bytes):
    out = c64_codec.CharacterRecord(rec.to_bytes(), rec.stored_size)
    inv = bytearray(out.get_raw("inventory"))
    size = c64_codec.ITEM_SIZE
    inv[slot * size:(slot + 1) * size] = block
    out.set_raw("inventory", bytes(inv))
    return out


def _slot(rec, n: int) -> bytes:
    size = c64_codec.ITEM_SIZE
    return rec.get_raw("inventory")[n * size:(n + 1) * size]


@pytest.mark.parametrize("deltas", DOS_TITLES, ids=lambda d: d.key)
def test_an_item_quantity_edit_changes_one_byte_of_the_item_file(deltas):
    char, before = _synthetic_dos(deltas)
    assert len(char.items) == 1
    block = bytearray(_slot(before, 0))
    block[10] = (block[10] + 3) & 0xFF            # the C64's quantity byte
    after = _with_item(before, 0, bytes(block))

    out = rewrite.rewrite_dos(char, before, after, _game(deltas))
    original = b"".join(rewrite.node_bytes(i) for i in char.items)
    assert len(out.items) == len(original)
    moved = [n for n in range(len(original)) if out.items[n] != original[n]]
    quantity = dos_port.ITEM_FIELDS_BY_NAME["quantity"].offset
    assert moved == [quantity]
    assert out.items[quantity] == block[10]


@pytest.mark.parametrize("deltas", DOS_TITLES, ids=lambda d: d.key)
def test_an_added_item_grows_the_file_by_one_stride_and_the_count(deltas):
    char, before = _synthetic_dos(deltas)
    added = bytes(range(1, 17))
    after = _with_item(before, 1, added)

    out = rewrite.rewrite_dos(char, before, after, _game(deltas))
    stride = deltas.item_size
    assert len(out.items) == len(char.items) * stride + stride
    assert out.items[:stride] == rewrite.node_bytes(char.items[0])
    assert out.items[stride:] == dos_codec.item_from_c64(added, stride)

    count = dos_port.FIELDS_BY_NAME_FOR[deltas.key]["item_count"].offset
    assert out.record[count] == char.get("item_count") + 1


@pytest.mark.parametrize("deltas", DOS_TITLES, ids=lambda d: d.key)
def test_a_deleted_item_shrinks_the_file_and_the_count(deltas):
    char, before = _synthetic_dos(deltas)
    after = _with_item(before, 0, bytes(c64_codec.ITEM_SIZE))

    out = rewrite.rewrite_dos(char, before, after, _game(deltas))
    assert out.items == b""
    count = dos_port.FIELDS_BY_NAME_FOR[deltas.key]["item_count"].offset
    assert out.record[count] == 0


def test_an_item_edit_reaches_an_amiga_pool_item_node():
    char, before = _synthetic_amiga_por()
    assert len(char.items) == 1
    block = bytearray(_slot(before, 0))
    block[10] = (block[10] + 3) & 0xFF
    after = _with_item(before, 0, bytes(block))

    out = rewrite.rewrite_amiga_por(
        char, before, after, _game(dos_port.POOL_OF_RADIANCE))
    original = b"".join(rewrite.node_bytes(i) for i in char.items)
    moved = [n for n in range(len(original)) if out.items[n] != original[n]]
    assert moved == [amiga_por.amiga_por_item_offset(
        dos_port.ITEM_FIELDS_BY_NAME["quantity"].offset)]


def test_a_record_whose_slots_disagree_with_the_character_is_refused():
    """The sixteen C64 slots are what ties a C64 item to the port's own, so a
    record holding a different number of them than the character it came from
    is a mismatch nobody can resolve."""
    deltas = dos_port.POOL_OF_RADIANCE
    char, before = _synthetic_dos(deltas)
    wrong = dos_codec.DosCharacter(char.to_bytes(), items=(),
                                   effects=char.effects, deltas=deltas)
    with pytest.raises(rewrite.RewriteError):
        rewrite.rewrite_dos(wrong, before, before, _game(deltas))


def test_three_records_of_different_lengths_are_refused():
    with pytest.raises(rewrite.RewriteError):
        rewrite.patch(bytes(4), bytes(4), bytes(5), [])


# --- the six port and title pairs, on records that need no game data --------
#: Every pair the editor can open: the three DOS titles, Amiga Pool of
#: Radiance, and the two later Amiga titles.  Each entry is the kind of
#: rewrite and the deltas that title is written through.
PORTS = (("dos", dos_port.POOL_OF_RADIANCE),
         ("dos", dos_port.CURSE_OF_THE_AZURE_BONDS),
         ("dos", dos_port.SECRET_OF_THE_SILVER_BLADES),
         ("amiga-por", dos_port.POOL_OF_RADIANCE),
         ("amiga-later", CURSE_DELTAS),
         ("amiga-later", SILVER_BLADES_DELTAS))


def _port_id(port) -> str:
    kind, deltas = port
    return f"{kind}-{deltas.key}"


def _make(port, items: int):
    kind, deltas = port
    if kind == "dos":
        return _synthetic_dos(deltas, items)
    if kind == "amiga-por":
        return _synthetic_amiga_por(items)
    return _synthetic_amiga_later(deltas, items)


def _rewrite(port, char, before, after, game=None):
    """The port's own rewrite.  `game` is left out by default, which is what
    exercises the per-title container each one falls back to."""
    kind, _deltas = port
    if kind == "dos":
        return rewrite.rewrite_dos(char, before, after, game)
    if kind == "amiga-por":
        return rewrite.rewrite_amiga_por(char, before, after, game)
    return rewrite.rewrite_amiga_later(char, before, after, game)


def _written_record(port, out) -> bytes:
    return out.character.raw if port[0] == "amiga-later" else out.record


def _read_back(port, out, into):
    """The rewritten character read back through the port's own reader.

    DOS goes through the files, because `read_character` is where the
    record's `item_count` meets the item file: a count that lies about the
    file is what it refuses, and a count short of it is what silently loses
    the items past it.
    """
    kind, deltas = port
    if kind == "dos":
        into.mkdir(parents=True, exist_ok=True)
        path = into / "CHRDATA1.SAV"
        path.write_bytes(out.record)
        path.with_suffix(deltas.item_suffix).write_bytes(out.items)
        path.with_suffix(deltas.effect_suffix).write_bytes(out.effects)
        return dos_codec.read_character(path)
    if kind == "amiga-por":
        return amiga_por.por_character(out.record, out.items, out.effects)
    return amiga_later._amiga_block(out.character.block_bytes(), 0, deltas)[0]


def _types(char) -> list[int]:
    """Each item's `type_index`, which says which item it is."""
    return [it.get("type_index") for it in char.items]


def _money(char) -> int:
    return sum(char.money.values())


def _fuzzed(rec, name: str):
    """A copy of the record with one added to the first byte of `name`."""
    out = c64_codec.CharacterRecord(rec.to_bytes(), rec.stored_size)
    raw = bytearray(out.get_raw(name))
    raw[0] = (raw[0] + 1) & 0xFF
    out.set_raw(name, bytes(raw))
    return out


@pytest.mark.parametrize("port", PORTS, ids=_port_id)
def test_five_items_take_a_delete_a_swap_a_replace_and_an_add(port, tmp_path):
    """The four things a player can do to the inventory, each read back
    through the port's own reader: the file holds the items the sheet holds,
    in the sheet's order, and the record's count is the file's length."""
    char, before = _make(port, 5)
    assert _types(char) == [10, 11, 12, 13, 14]
    empty = bytes(c64_codec.ITEM_SIZE)
    other = _blocks(9)[8]                      # type_index 18, a ninth item

    cases = {
        "delete": (_with_item(before, 2, empty), [10, 11, 13, 14]),
        "swap": (_with_item(_with_item(before, 1, _slot(before, 3)),
                            3, _slot(before, 1)),
                 [10, 13, 12, 11, 14]),
        "replace": (_with_item(before, 0, other), [18, 11, 12, 13, 14]),
        "add": (_with_item(before, 5, other), [10, 11, 12, 13, 14, 18]),
    }
    for name, (after, expected) in cases.items():
        written = _read_back(port, _rewrite(port, char, before, after),
                             tmp_path / name)
        assert _types(written) == expected, name
        assert written.get("item_count") == len(expected), name
        assert len(written.items) == len(expected), name


@pytest.mark.parametrize("port", PORTS, ids=_port_id)
def test_a_twenty_item_character_keeps_the_four_the_sheet_never_saw(
        port, tmp_path):
    """Deleting one item out of twenty leaves nineteen, not fifteen.

    The C64 record has sixteen item slots and these ports have no such
    limit, so the two renderings a rewrite compares see sixteen items where
    the character has twenty.  The count and the encumbrance are therefore
    settled against the whole list rather than taken from the writer --
    without that, the record would say fifteen over a file of nineteen
    nodes and the next read would return fifteen items.
    """
    char, before = _make(port, 20)
    assert len(char.items) == 20
    hidden = [rewrite.node_bytes(i) for i in char.items[16:]]

    after = _with_item(before, 0, bytes(c64_codec.ITEM_SIZE))
    out = _rewrite(port, char, before, after)
    written = _read_back(port, out, tmp_path)

    assert written.get("item_count") == 19
    if port[0] == "amiga-later":
        # `block_bytes` writes the count itself, so the block always agrees;
        # the record handed back has to agree as well, for a caller reading
        # that rather than the block.
        assert out.character.get("item_count") == 19
    assert len(written.items) == 19
    assert _types(written) == [11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21,
                               22, 23, 24, 25, 26, 27, 28, 29]
    assert [rewrite.node_bytes(i) for i in written.items[15:]] == hidden
    # The engine's own identity, over all nineteen rather than the fifteen
    # the sheet could see: money plus weight times quantity.
    assert written.get("encumbrance") == _money(written) + sum(
        it.get("weight") * (it.get("quantity") or 1) for it in written.items)


@pytest.mark.parametrize("port", PORTS, ids=_port_id)
def test_an_edit_that_reaches_no_field_of_this_port_is_refused(port):
    """`turn_power` is a C64 field none of the six ports writes, so an edit
    to it would be thrown away silently.  A caller is told instead."""
    char, before = _make(port, 1)
    after = _fuzzed(before, "turn_power")
    assert after.to_bytes() != before.to_bytes()
    with pytest.raises(rewrite.RewriteError):
        _rewrite(port, char, before, after)


@pytest.mark.parametrize("port", PORTS, ids=_port_id)
def test_a_rewrite_with_no_game_renders_through_the_titles_own_tables(port):
    """`game` is what says whose race, class and spell tables the C64
    record's indices are in, so a rewrite that left it out would render
    Curse and Silver Blades through Pool of Radiance's."""
    kind, deltas = port
    char, before = _make(port, 1)
    after = _edited(before, gold=4321)
    own = _game(deltas.dos if kind == "amiga-later" else deltas)
    assert _written_record(port, _rewrite(port, char, before, after)) == \
        _written_record(port, _rewrite(port, char, before, after, own))


def test_another_titles_tables_would_render_a_different_record():
    """What the default above is for: the container is not decoration."""
    deltas = dos_port.CURSE_OF_THE_AZURE_BONDS
    char, before = _synthetic_dos(deltas)
    after = _edited(before, gold=4321)
    assert rewrite.rewrite_dos(char, before, after).record != \
        rewrite.rewrite_dos(char, before, after,
                            _game(dos_port.POOL_OF_RADIANCE)).record


@pytest.mark.parametrize("port", PORTS, ids=_port_id)
def test_the_result_names_what_moved_and_what_has_no_span(port):
    """A caller cannot see from the bytes which fields landed, so the
    rewrite says: `moved` is what it wrote, `unplaced` what this port's span
    map has no offset for at all."""
    char, before = _make(port, 1)
    out = _rewrite(port, char, before, _edited(before, gold=4321))
    assert "gold" in out.moved
    assert out.unplaced == ()


@pytest.mark.parametrize("port", PORTS, ids=_port_id)
def test_an_item_edit_alone_is_not_taken_for_an_edit_that_vanished(port,
                                                                   tmp_path):
    """An item's value is in the item file and not in the record, so a
    record that moves nowhere is the right answer here -- the refusal above
    must not fire on it."""
    char, before = _make(port, 2)
    block = bytearray(_slot(before, 1))
    block[11] = (block[11] + 7) & 0xFF                   # the value word
    written = _read_back(port, _rewrite(port, char, before,
                                        _with_item(before, 1, bytes(block))),
                         tmp_path)
    assert written.items[1].get("value") == char.items[1].get("value") + 7


def test_a_replaced_item_does_not_keep_the_old_items_cached_line():
    """A slot whose `type_index` or name words change holds a different
    item, so the node is rendered fresh rather than patched: patching would
    leave the old item's cached display line under the new item's name."""
    deltas = dos_port.POOL_OF_RADIANCE
    char, before = _synthetic_dos(deltas, 2)
    stride = deltas.item_size
    node = bytearray(rewrite.node_bytes(char.items[0]))
    node[0] = 10
    node[1:11] = b"LONG SWORD"                  # the line the game drew
    engine = dos_codec.DosCharacter(
        char.to_bytes(),
        items=[dos_codec.DosItem(bytes(node), stride), char.items[1]],
        effects=char.effects, deltas=deltas)
    assert engine.items[0].display_line == "LONG SWORD"

    other = _blocks(9)[8]
    out = rewrite.rewrite_dos(engine, before, _with_item(before, 0, other))
    written = dos_codec.DosItem(out.items[:stride], stride)
    assert written.get("type_index") == other[0]
    assert written.display_line == ""
    assert "item 0: replaced" in out.moved


def test_a_stored_count_that_disagrees_with_its_own_item_file_is_left_alone():
    """A record whose `item_count` is not the number of items it was read
    with keeps the engine's byte through a save with no edit in it -- the
    count is written only when the item list changes length."""
    deltas = dos_port.POOL_OF_RADIANCE
    char, before = _synthetic_dos(deltas, 3)
    at = dos_port.FIELDS_BY_NAME_FOR[deltas.key]["item_count"].offset
    stale = bytearray(char.to_bytes())
    stale[at] = 7
    engine = dos_codec.DosCharacter(bytes(stale), items=char.items,
                                    effects=char.effects, deltas=deltas)

    assert rewrite.rewrite_dos(engine, before, before).record == bytes(stale)
    out = rewrite.rewrite_dos(engine, before,
                              _with_item(before, 0, bytes(c64_codec.ITEM_SIZE)))
    assert out.record[at] == 2


# --- the specimens ----------------------------------------------------------
def _dos_parties():
    for folder in sorted(specimen_root().glob("*-dos/WISH-SPEC-*")):
        if not folder.is_dir():
            continue
        for slot in dos_codec.slots_available(folder):
            party = dos_codec.read_party(folder, slot)
            try:
                game = c64_port.by_key(party[0].deltas.key)
            except c64_port.UnknownGameError:
                continue                  # Pools of Darkness has no C64 port
            yield f"{folder.name}/{slot}", party, game


def _amiga_later_characters():
    root = specimen_root()
    for path in sorted(list(root.glob("coab-amiga/WISH-SPEC-*/savgam?.dat"))
                       + list(root.glob("ssb-amiga/WISH-SPEC-*/savgam?.sav"))):
        save = amiga_savegame.parse(path.read_bytes())
        for char in save.characters:
            yield f"{path.parent.name}/{path.name}", char


def _amiga_por_characters():
    for image in sorted(specimen_root().glob("por-amiga/WISH-SPEC-*/*.adf")):
        disk = AmigaDisk(bytearray(image.read_bytes()))
        drawer = amiga_savegame.por_save_drawer(disk)
        for slot in amiga_savegame.por_slots_present(disk):
            for index in range(1, amiga_savegame.PARTY_MAX + 1):
                files = [amiga_savegame._por_file(disk, slot, index, suffix,
                                                  drawer)
                         for suffix in (".sav", ".itm", ".spc")]
                if files[0] is None:
                    break
                yield (f"{image.parent.name}/{slot}{index}",
                       amiga_por.por_character(files[0], files[1] or b"",
                                               files[2] or b""))


@needs_specimens
def test_every_dos_specimen_rewrites_to_the_bytes_it_came_from():
    seen = 0
    for label, party, game in _dos_parties():
        for char in party:
            rec, _ = dos_codec.to_c64_record(char)
            out = rewrite.rewrite_dos(char, rec, rec, game)
            assert out.record == char.to_bytes(), f"{label} {char.name}"
            assert out.items == b"".join(rewrite.node_bytes(i) for i in char.items)
            assert out.effects == b"".join(bytes(e) for e in char.effects)
            seen += 1
    assert seen >= 6, f"only {seen} DOS specimen characters were read"


@needs_specimens
def test_every_amiga_pool_specimen_rewrites_to_the_bytes_it_came_from():
    seen = 0
    pool = c64_port.by_key(dos_port.POOL_OF_RADIANCE.key)
    for label, char in _amiga_por_characters():
        rec, _ = dos_codec.to_c64_record(amiga_por.to_dos_character(char))
        out = rewrite.rewrite_amiga_por(char, rec, rec, pool)
        assert out.record == char.raw, label
        assert out.items == b"".join(rewrite.node_bytes(i) for i in char.items)
        assert out.effects == b"".join(bytes(e) for e in char.effects), label
        seen += 1
    assert seen >= 6, f"only {seen} Amiga Pool characters were read"


@needs_specimens
def test_every_amiga_later_specimen_rewrites_to_the_bytes_it_came_from():
    seen = 0
    for label, char in _amiga_later_characters():
        game = c64_port.by_key(char.deltas.key)
        rec, _ = dos_codec.neutral_to_c64_record(
            amiga_later.to_neutral_later(char))
        out = rewrite.rewrite_amiga_later(char, rec, rec, game)
        assert out.character.raw == char.raw, label
        assert out.character.block_bytes() == char.block_bytes(), label
        seen += 1
    assert seen >= 6, f"only {seen} Amiga Curse or Silver Blades characters"


@needs_specimens
def test_an_edit_lands_on_every_dos_specimen_and_moves_nothing_else():
    """Gold, on every DOS character on this machine: the field the sheet set
    is the only one whose bytes changed, whatever else the writer would have
    rendered differently."""
    for label, party, game in _dos_parties():
        for char in party:
            before, _ = dos_codec.to_c64_record(char)
            after = _edited(before, gold=char.get("gold") ^ 0x1234)
            out = rewrite.rewrite_dos(char, before, after, game)
            spans, _unplaced = rewrite.dos_spans(char.deltas)
            assert _moved(char.to_bytes(), out.record, spans) == \
                _gold_moves(char.deltas), f"{label} {char.name}"


@needs_specimens
def test_the_combat_figure_is_never_disturbed_on_a_dos_specimen():
    """`icon` defaults to the character's own figure, so the three fields
    `#130 (A converted DOS party arrives with six identical combat figures,
    not its own)` is about stay where they were through any edit."""
    for label, party, game in _dos_parties():
        for char in party:
            before, _ = dos_codec.to_c64_record(char)
            after = _edited(before, gold=char.get("gold") ^ 0x1234)
            out = rewrite.rewrite_dos(char, before, after, game)
            written = dos_codec.DosCharacter(out.record, deltas=char.deltas)
            for name in ("icon_head", "icon_body", "icon_colours"):
                assert written.get(name) == char.get(name), f"{label} {name}"
            assert amiga_combat_icon(written).head == \
                amiga_combat_icon(char).head
