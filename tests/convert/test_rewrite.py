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


def _synthetic_dos(deltas):
    """A DOS character and the C64 record the editor would build from it.

    The record is what the DOS writer itself makes of a filled neutral
    character, so nothing here is a copy of anybody's save.
    """
    neutral = _filled(_game(deltas))
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


def _synthetic_amiga_por():
    pool = _game(dos_port.POOL_OF_RADIANCE)
    record, itm, spc, _rep = amiga_por.write_por(_filled(pool))
    char = amiga_por.por_character(record, itm, spc)
    rec, _ = dos_codec.to_c64_record(amiga_por.to_dos_character(char))
    return char, rec


def _synthetic_amiga_later(deltas):
    char, _rep = amiga_later.write_later(_filled(_game(deltas.dos)),
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


def test_the_amiga_pool_record_has_no_span_for_field_83_87():
    """The second insertion has not been located inside the run
    `field_83_87` straddles, so there is no offset to copy it to and the
    engine's own bytes stay there.  It is the only such field."""
    spans, unplaced = rewrite.amiga_por_spans()
    assert unplaced == ["field_83_87"]
    assert "field_83_87" not in {s.name for s in spans}
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


@pytest.mark.parametrize("deltas", (CURSE_DELTAS, SILVER_BLADES_DELTAS),
                         ids=lambda d: d.key)
def test_a_synthetic_amiga_later_no_op_rewrite_returns_the_original(deltas):
    char, rec = _synthetic_amiga_later(deltas)
    out = rewrite.rewrite_amiga_later(char, rec, rec, _game(deltas.dos))
    assert out.raw == char.raw
    assert out.block_bytes() == char.block_bytes()


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

    assert out.get("gold") == 4321
    assert amiga_later.to_neutral_later(out).get("gold") == 4321
    spans, _unplaced = rewrite.amiga_later_spans(deltas)
    assert _moved(char.raw, out.raw, spans) == _gold_moves(deltas.dos)


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
        assert out.raw == char.raw, label
        assert out.block_bytes() == char.block_bytes(), label
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
