"""Boundary characters through the two Amiga re-cuts: `#516 (Generate boundary
characters and check every writer's field widths, since no real save reaches a
limit and the corpus cannot find a wrong one)`, stage 7.

`goldbox.amiga_por.write_por` and `goldbox.amiga_later.write_later` both call
`goldbox.dos_codec.write` and re-cut what it returns, so this checks the
**transposition** and not the DOS conversion again: the sixteen-byte NUL-padded
name built from DOS's count byte, the four-byte big-endian experience, Pool of
Radiance's three insertions, the item and effect nodes, and the item count and
chain heads that `write_later` sets and `write_por` must leave alone.

The characters are the ones the DOS sweep in `tests/records/test_boundary.py`
already uses: `tools/records/boundarychars.py` for Pool of Radiance and
`tools/records/laterchars.py` for every legal Curse and Secret of the Silver
Blades combination plus each title's deepest caster.  All are read as though off
a C64 record, which is the route a conversion into the Amiga takes.

Pools of Darkness stays out: `goldbox.amiga_pod.write_pod` refuses the
generator's base character and is its own writer rather than a re-cut of the DOS
record, so a sweep there would report the two gaps its own issues already track
and not a width.
"""

from __future__ import annotations

import pytest

from goldbox import amiga_later, amiga_por, dos_codec, dos_port
from goldbox import items as items_mod
from goldbox.layout import Kind
from goldbox.portraits import neutral_menu
from tools.records import boundarychars, doswidths, laterchars

POR = boundarychars.GAME
_LATER_CASES = [(combo.game, combo.name, laterchars.build(combo))
                for game in laterchars.GAMES
                for combo in laterchars.combinations(game)]
_LATER_CASES += [(game, "deepest caster", laterchars.caster(game))
                 for game in laterchars.GAMES]

_POR_PROVENANCE = ("Written as a 288-byte Amiga Pool of Radiance record by "
                   "re-cutting the 285-byte DOS one")
_LATER_PROVENANCE = "Written as a "
_LATER_EFFECTS = amiga_later.LATER_EFFECTS_FROM_NEUTRAL
#: `goldbox.dos_codec.write`'s own line for a name past DOS's fifteen.
_NAME_TRUNCATED = "Name '"
_SPACE_IN_NAME = "WARNING: Spaces in names are dropped on the Amiga."

_NAME_LENGTHS = [0, 1, 15, 16, 20, 21]


def _only(warnings, allowed):
    """Every warning starts with one of the `allowed` prefixes and each prefix
    is used exactly once, so a new warning fails the test rather than passing
    unnoticed and a named one going missing fails it too."""
    unknown = [w for w in warnings if not w.startswith(tuple(allowed))]
    assert unknown == [], unknown
    for prefix in allowed:
        assert sum(w.startswith(prefix) for w in warnings) == 1, (
            prefix, warnings)


def _active(game: str) -> list[str]:
    """Every neutral field the DOS writer copies or transforms in `game`."""
    d = dos_codec.write_field_disposition(game)
    return [name for name, why in d.items()
            if not why.startswith(("dropped:", "derived:", "constant:"))]


def _held(levels) -> dict:
    return {k: v for k, v in (levels or {}).items() if v}


def _mismatches(char, back, game, skip=()) -> dict:
    """`{field: (wanted, read back)}` for every field the case sets that the
    DOS writer copies or transforms, less the ones the writer recomputes."""
    out = {}
    for field in _active(game):
        if (field in doswidths.RECOMPUTED or field in skip
                or char.get(field) is None):
            continue
        want, got = char.get(field), back.get(field)
        if field == "levels":
            want, got = _held(want), _held(got)
        if want != got:
            out[field] = (want, got)
    return out


def _distinct(char):
    """The four flags and shares in `field_83_87` and the combat tail, each at a
    value that no default shares, so a re-cut that loses one shows."""
    char.set("npc", True, "boundary")
    char.set("npc_control_byte", 0x9F, "boundary")
    char.set("treasure_share", 3, "boundary")
    char.set("hostile", True, "boundary")
    char.set("quickfight", True, "boundary")
    return char


def _swap(kind, chunk: bytes) -> bytes:
    return chunk[::-1] if kind in (Kind.U16LE, Kind.UINT_LE) else chunk


def _two_different_bytes(dos_item: bytes):
    """The weight and the value each have two different bytes, or the
    comparison above could not tell a swap from a copy."""
    for name in ("weight", "value"):
        f = dos_port.ITEM_FIELDS_BY_NAME[name]
        pair = dos_item[f.offset:f.offset + 2]
        assert pair[0] != pair[1], (name, pair.hex())


def _dos_effects(spc: bytes):
    return [(n[0], int.from_bytes(n[1:3], "little"), n[3], n[4])
            for n in (spc[i:i + dos_port.EFFECT_SIZE]
                      for i in range(0, len(spc), dos_port.EFFECT_SIZE))]


def _amiga_effects(spc: bytes, size: int = 10):
    """Effect nodes decoded by hand: id, pad, big-endian duration, value, flag,
    next pointer."""
    nodes = [spc[i:i + size] for i in range(0, len(spc), size)]
    assert all(len(n) == size for n in nodes), len(spc)
    return ([(n[0], int.from_bytes(n[2:4], "big"), n[4], n[5]) for n in nodes],
            [n[1] for n in nodes], [n[6:10] for n in nodes])


def _weighted(char, count: int):
    """`count` items whose weight and cost each have two different bytes, so a
    byte swap in the item re-cut shows."""
    char.set("inventory",
             [items_mod.build_item(type_index=1, quantity=1,
                                   weight_tenths=(i + 1) << 8 | 0x40 + i,
                                   cost_gp=(i + 2) << 8 | 0x50 + i)
              for i in range(count)], "boundary")
    return char


# --- Pool of Radiance ---------------------------------------------------------

def _por_readback(char):
    rec, itm, spc, rep = amiga_por.write_por(char)
    back = amiga_por.to_neutral(amiga_por.por_character(rec, itm, spc))
    return rec, itm, spc, rep, back


@pytest.mark.parametrize("name", sorted(boundarychars.CASES))
def test_por_a_boundary_character_writes_and_reads_back_whole(name):
    char = boundarychars.CASES[name]()
    rec, itm, spc, rep, back = _por_readback(char)

    assert len(rec) == amiga_por.AMIGA_POR_RECORD_SIZE == 288
    assert rep.dropped == [], (name, rep.dropped)
    _only(rep.warnings, [_POR_PROVENANCE])
    assert _mismatches(char, back, POR) == {}, name


@pytest.mark.parametrize("name", sorted(boundarychars.CASES))
def test_por_the_memorised_list_and_the_spellbook_come_back_whole(name):
    char = boundarychars.CASES[name]()
    *_, back = _por_readback(char)
    assert back.get("spells_memorised") == char.get("spells_memorised")
    assert back.get("spells_known") == char.get("spells_known")


def test_por_the_deepest_caster_memorises_all_twenty():
    char = boundarychars.CASES["caster"]()
    *_, back = _por_readback(char)
    assert len(back.get("spells_memorised")) == 20


@pytest.mark.parametrize("length", _NAME_LENGTHS)
def test_por_the_name_is_sixteen_bytes_built_from_dos_fifteen(length):
    char = boundarychars._base()
    char.set("name", "N" * length, "boundary")
    rec, _, _, rep, back = _por_readback(char)
    kept = "N" * min(length, 15)
    assert amiga_por.AMIGA_POR_NAME_SIZE == 16
    assert rec[:16] == kept.encode().ljust(16, b"\0")
    assert rec[15] == 0, "the sixteenth byte is always the terminator"
    assert back.get("name") == kept
    assert rep.dropped == []
    _only(rep.warnings, [_POR_PROVENANCE]
          + ([_NAME_TRUNCATED] if length > 15 else []))
    assert [line.startswith(_NAME_TRUNCATED) for line in rep.losses] == (
        [True] if length > 15 else []), rep.losses


def test_por_a_space_in_the_name_is_reported_once():
    char = boundarychars._base()
    char.set("name", "A B", "boundary")
    _, _, _, rep, _ = _por_readback(char)
    _only(rep.warnings, [_POR_PROVENANCE, _SPACE_IN_NAME])


@pytest.mark.parametrize("value", [0, 1, 0x01020304, 0xFFFFFFFF])
def test_por_experience_is_one_big_endian_u32(value):
    char = boundarychars._base()
    char.set("experience", value, "boundary")
    rec, *_, back = _por_readback(char)
    at = amiga_por.AMIGA_POR_EXPERIENCE
    assert rec[at:at + 4] == value.to_bytes(4, "big")
    assert back.get("experience") == value


@pytest.mark.parametrize("name", sorted(boundarychars.CASES))
def test_por_the_three_insertions_and_the_chain_are_written_not_converted(
        name):
    rec, *_ = amiga_por.write_por(boundarychars.CASES[name]())
    assert rec[0x07F] == 0, "the first insertion"
    assert rec[0x080:0x084] == bytes(4), "the effect chain head"
    assert rec[amiga_por.AMIGA_POR_MONEY_PAD] == 0, "the second insertion"
    assert rec[0x11F] == 0, "the trailing pad"


def test_por_a_companion_keeps_his_control_byte_and_his_share():
    """`field_83_87` is converted, not written over.

    The Amiga engine reads `0x085` as the control byte -- `/program` tests it
    against `0x7F` and stores `0xB2` and `0xB3` into it -- and masks `0x086`
    with 7 for the treasure split, so a companion who arrives with `0x085`
    zero is an ordinary player character on the other side.
    """
    char = _distinct(boundarychars.CASES["warrior"]())
    drec, *_ = dos_codec.write(char, into="Amiga",
                               portraits=neutral_menu(POR))
    rec, _itm, _spc, rep, back = _por_readback(char)
    window = dos_port.FIELDS_BY_NAME["field_83_87"]
    assert rec[0x084:0x089] == drec[window.span]
    assert rec[0x085] == 0x9F, "bit 7 plus the morale the source held"
    assert rec[0x086] == 3, "the treasure share, masked with 7 by the engine"
    assert (back.get("npc"), back.get("npc_control_byte")) == (True, 0x9F)
    assert back.get("treasure_share") == 3
    assert rep.dropped == []


@pytest.mark.parametrize("items", [0, 1, 16])
@pytest.mark.parametrize("effects", [0, 1, 5])
def test_por_the_item_count_is_dos_and_no_pointer_is_set(items, effects):
    char = _weighted(boundarychars._base(), items)
    char.set("granted_effects",
             [boundarychars._effect(61, value=n + 1) for n in range(effects)],
             "boundary")
    char.set("running_effects", [], "boundary")
    rec, itm, spc, rep, back = _por_readback(char)
    count_at = amiga_por.amiga_por_offset(
        dos_port.FIELDS_BY_NAME["item_count"].offset)
    assert rec[count_at] == items
    assert len(itm) == items * amiga_por.AMIGA_POR_ITEM_SIZE
    assert rec[0x080:0x084] == bytes(4)
    for n in range(items):
        node = itm[n * 65:(n + 1) * 65]
        assert node[0x02A:0x02E] == bytes(4), n
        assert node[:0x02A] == bytes(0x02A), n
    _, pads, nexts = _amiga_effects(spc)
    assert len(pads) == effects
    assert set(pads) <= {0} and all(n == bytes(4) for n in nexts)
    assert len(back.get("inventory")) == items


@pytest.mark.parametrize("name", sorted(boundarychars.CASES))
def test_por_every_effect_node_is_the_dos_node_byte_swapped(name):
    char = boundarychars.CASES[name]()
    _, _, dspc, _ = dos_codec.write(
        char, into="Amiga", portraits=neutral_menu(POR))
    _, _, spc, _ = amiga_por.write_por(char)
    got, pads, nexts = _amiga_effects(spc)
    assert got == _dos_effects(dspc) and got
    assert set(pads) == {0} and all(n == bytes(4) for n in nexts)


def test_por_a_duration_that_fills_its_two_bytes_is_swapped_not_truncated():
    char = boundarychars._base()
    char.set("granted_effects", [], "boundary")
    char.set("running_effects",
             [boundarychars._effect(1, value=1, minutes=0x0102)], "boundary")
    _, _, spc, *_ = amiga_por.write_por(char)
    assert spc[2:4] == b"\x01\x02"


def test_por_every_item_field_arrives_big_endian_at_its_own_offset():
    char = _weighted(boundarychars._base(), 16)
    _, ditm, _, _ = dos_codec.write(
        char, into="Amiga", portraits=neutral_menu(POR))
    _, itm, _, _ = amiga_por.write_por(char)
    assert len(itm) == 16 * 65 and len(ditm) == 16 * dos_port.ITEM_SIZE
    for n in range(16):
        dnode = ditm[n * dos_port.ITEM_SIZE:(n + 1) * dos_port.ITEM_SIZE]
        anode = itm[n * 65:(n + 1) * 65]
        for f in dos_port.ITEM_LAYOUT:
            if f.name in ("text_length", "text", "next"):
                continue
            at = amiga_por.amiga_por_item_offset(f.offset)
            assert anode[at:at + f.size] == _swap(
                f.kind, dnode[f.offset:f.offset + f.size]), (n, f.name)
        _two_different_bytes(dnode)


def test_por_every_field_the_record_holds_arrives_unchanged():
    """Every DOS field the re-cut does not write by hand lands at its shifted
    offset with only the multi-byte fields swapped, and every Amiga byte no DOS
    field reaches is one of the named pads.  This is what sees `hostile` and
    `quickfight`, which the Amiga reader does not read back."""
    char = _distinct(boundarychars.CASES["warrior"]())
    drec, *_ = dos_codec.write(char, into="Amiga",
                               portraits=neutral_menu(POR))
    rec, *_ = amiga_por.write_por(char)
    by_hand = {"name_length", "name_text", "experience", "effect_chain"}
    covered = set(range(0x10)) | set(range(0x0AE, 0x0B2)) | set(
        range(0x07F, 0x084)) | {amiga_por.AMIGA_POR_MONEY_PAD, 0x11F}
    for f in dos_port.LAYOUT:
        if f.name in by_hand:
            continue
        at = amiga_por.amiga_por_offset(f.offset)
        covered.update(range(at, at + f.size))
        assert rec[at:at + f.size] == _swap(
            f.kind, drec[f.offset:f.offset + f.size]), f.name
    assert sorted(set(range(len(rec))) - covered) == [], (
        "an Amiga byte no field accounts for")


# --- Curse of the Azure Bonds and Secret of the Silver Blades ---------------

def _later_readback(char):
    built, rep = amiga_later.write_later(char)
    return built, rep, amiga_later.to_neutral_later(built)


#: What comes back different from what was set, and why, by neutral field.  The
#: reader either has nowhere to put the value or the DOS writer works out the
#: byte itself.  The bytes for `hostile` and `quickfight` are asserted by
#: `test_later_every_field_the_record_holds_arrives_unchanged`.
_LATER_NOT_READ_BACK = {
    "portrait_head": "neither title draws a sheet portrait (#300)",
    "portrait_body": "neither title draws a sheet portrait (#300)",
    "innate_effects": "the reader cannot tell innate effects from an item's "
                      "grants, so all of them read back as granted",
    "hostile": "the last two bytes of field_10c_10f are not read",
    "quickfight": "the last two bytes of field_10c_10f are not read",
    "unnamed_0ab": "the identity byte the DOS writer digests from the record",
}


@pytest.mark.parametrize("game,name,char", _LATER_CASES,
                         ids=[f"{g}-{n}" for g, n, _ in _LATER_CASES])
def test_later_a_legal_character_writes_and_reads_back_whole(game, name, char):
    char = doswidths.c64_sourced(char)
    built, rep, back = _later_readback(char)

    assert len(built.raw) == built.deltas.record_size
    assert rep.dropped == [], (game, name, rep.dropped)
    _only(rep.warnings, [_LATER_PROVENANCE, _LATER_EFFECTS])
    # A dual-classed character who has regained his old class carries both in
    # the source's level array; DOS never stores that, so the old slot stays
    # zero and the class he left comes back as `former_levels` (#408).
    former = char.get("former_levels") or {}
    held = {k: v for k, v in _held(char.get("levels")).items()
            if k not in former}
    assert _held(back.get("levels")) == held, (game, name)
    assert (back.get("former_levels") or {}) == former, (game, name)
    # `unnamed_0ab` differs only when the record's digest moves it off the
    # value the case set, which the combinations do not always do.
    differ = set(_mismatches(char, back, game,
                             skip=("levels", "former_levels")))
    assert differ - {"unnamed_0ab"} == set(_LATER_NOT_READ_BACK) - {
        "unnamed_0ab"}, (game, name)
    assert differ <= set(_LATER_NOT_READ_BACK), (game, name)


@pytest.mark.parametrize("game", laterchars.GAMES)
def test_later_the_deepest_caster_memorises_his_whole_list(game):
    char = doswidths.c64_sourced(laterchars.caster(game))
    built, rep, back = _later_readback(char)
    wanted = laterchars.DEEPEST[game]["memorised"]
    assert back.get("spells_memorised") == list(range(1, wanted + 1))
    allotted = dos_port.FIELDS_BY_NAME_FOR[game]["spells_memorised"].size
    assert wanted < allotted, (game, wanted, allotted)
    assert back.get("spells_known") == char.get("spells_known")
    assert rep.dropped == []


@pytest.mark.parametrize("game", laterchars.GAMES)
def test_later_the_deepest_caster_counts_are_forty_and_sixty_four(game):
    assert laterchars.DEEPEST[game]["memorised"] == {
        "curse-of-the-azure-bonds": 40,
        "secret-of-the-silver-blades": 64}[game]
    assert dos_port.FIELDS_BY_NAME_FOR[game]["spells_memorised"].size == {
        "curse-of-the-azure-bonds": 84,
        "secret-of-the-silver-blades": 75}[game]


@pytest.mark.parametrize("length", _NAME_LENGTHS)
@pytest.mark.parametrize("game", laterchars.GAMES)
def test_later_the_name_is_sixteen_bytes_built_from_dos_fifteen(game, length):
    char = doswidths.c64_sourced(laterchars.caster(game))
    char.set("name", "N" * length, "boundary")
    built, rep, back = _later_readback(char)
    kept = "N" * min(length, 15)
    assert amiga_later.AMIGA_NAME_SIZE == 16
    assert built.raw[:16] == kept.encode().ljust(16, b"\0")
    assert built.raw[15] == 0, "the sixteenth byte is always the terminator"
    assert back.get("name") == kept
    assert rep.dropped == []
    _only(rep.warnings, [_LATER_PROVENANCE, _LATER_EFFECTS]
          + ([_NAME_TRUNCATED] if length > 15 else []))
    assert [line.startswith(_NAME_TRUNCATED) for line in rep.losses] == (
        [True] if length > 15 else []), rep.losses


@pytest.mark.parametrize("value", [0, 1, 0x01020304, 0xFFFFFFFF])
@pytest.mark.parametrize("game", laterchars.GAMES)
def test_later_experience_is_one_big_endian_u32(game, value):
    char = doswidths.c64_sourced(laterchars.caster(game))
    char.set("experience", value, "boundary")
    built, _, back = _later_readback(char)
    f = dos_port.FIELDS_BY_NAME_FOR[game]["experience"]
    at = built.deltas.offset(f.offset)
    assert f.size == 4
    assert built.raw[at:at + 4] == value.to_bytes(4, "big")
    assert back.get("experience") == value


@pytest.mark.parametrize("effects", [0, 1, 5])
@pytest.mark.parametrize("items", [0, 1, 16])
@pytest.mark.parametrize("game", laterchars.GAMES)
def test_later_the_count_and_chain_heads_match_what_follows(game, items,
                                                            effects):
    char = _weighted(doswidths.c64_sourced(laterchars.caster(game)), items)
    char.set("granted_effects",
             [boundarychars._effect(61, value=n + 1) for n in range(effects)],
             "boundary")
    char.set("running_effects", [], "boundary")
    char.set("innate_effects", [], "boundary")
    built, rep, back = _later_readback(char)
    deltas = built.deltas
    block = built.block_bytes()
    assert len(block) == (deltas.record_size + items * deltas.item_size
                          + effects * deltas.effect_size)
    assert built.get("item_count") == items
    assert (built.item_chain != 0) == (items > 0)
    assert (built.effect_chain != 0) == (effects > 0)
    assert len(back.get("inventory")) == items

    at = deltas.record_size
    for n in range(items):
        node = block[at + n * deltas.item_size:at + (n + 1) * deltas.item_size]
        nxt = int.from_bytes(
            node[amiga_later.AMIGA_LATER_ITEM_NEXT:
                 amiga_later.AMIGA_LATER_ITEM_NEXT + 4], "big")
        assert (nxt != 0) == (n + 1 < items), (game, "item", n)
    at += items * deltas.item_size
    for n in range(effects):
        node = block[at + n * deltas.effect_size:
                     at + (n + 1) * deltas.effect_size]
        nxt = int.from_bytes(
            node[amiga_later.AMIGA_LATER_EFFECT_NEXT:
                 amiga_later.AMIGA_LATER_EFFECT_NEXT + 4], "big")
        assert (nxt != 0) == (n + 1 < effects), (game, "effect", n)


@pytest.mark.parametrize("game", laterchars.GAMES)
def test_later_every_effect_node_is_the_neutral_effect_byte_swapped(game):
    char = doswidths.c64_sourced(laterchars.caster(game))
    char.set("granted_effects",
             [boundarychars._effect(61, value=12),
              boundarychars._effect(5, value=1, minutes=0)], "boundary")
    char.set("running_effects",
             [boundarychars._effect(1, value=1, minutes=0x0102)], "boundary")
    char.set("innate_effects", [], "boundary")
    built, rep, back = _later_readback(char)
    wanted = [(bytes(n)[0], int.from_bytes(bytes(n)[1:3], "little"),
               bytes(n)[3], bytes(n)[4])
              for n in (char.get("granted_effects")
                        + char.get("running_effects"))]
    stream = b"".join(built.effects)
    got, pads, _ = _amiga_effects(stream, built.deltas.effect_size)
    assert got == wanted and len(wanted) == 3
    assert stream[2:4] == wanted[0][1].to_bytes(2, "big")
    assert stream[2 * built.deltas.effect_size + 2:
                  2 * built.deltas.effect_size + 4] == b"\x01\x02"


@pytest.mark.parametrize("game", laterchars.GAMES)
def test_later_every_item_field_arrives_big_endian_at_its_own_offset(game):
    char = _weighted(doswidths.c64_sourced(laterchars.caster(game)), 16)
    built, _, _ = _later_readback(char)
    deltas = built.deltas
    _, ditm, _, _ = dos_codec.write(
        char, deltas=deltas.dos, recompute_thief_skills=False, into="Amiga",
        portraits=neutral_menu(deltas.dos.key))
    stride = deltas.dos.item_size
    assert len(built.items) == 16 and len(ditm) == 16 * stride
    for n, item in enumerate(built.items):
        dnode = ditm[n * stride:(n + 1) * stride]
        for f in dos_port.ITEM_LAYOUT:
            if f.name in ("text_length", "text", "next"):
                continue
            at = deltas.item_offset(f.offset)
            assert item.raw[at:at + f.size] == _swap(
                f.kind, dnode[f.offset:f.offset + f.size]), (game, n, f.name)
        _two_different_bytes(dnode)


@pytest.mark.parametrize("game", laterchars.GAMES)
def test_later_every_field_the_record_holds_arrives_unchanged(game):
    """Every DOS field of the title lands at its shifted offset with only the
    multi-byte fields swapped, `hostile` and `quickfight` included."""
    char = _distinct(doswidths.c64_sourced(laterchars.caster(game)))
    built, rep, _ = _later_readback(char)
    deltas = built.deltas
    drec, *_ = dos_codec.write(
        char, deltas=deltas.dos, recompute_thief_skills=False, into="Amiga",
        portraits=neutral_menu(deltas.dos.key))
    by_hand = {"name_length", "name_text", "item_count", "item_chain",
               "effect_chain"}
    if deltas.spellbook_bytes is not None:
        by_hand.add("spellbook")
    checked = 0
    for f in dos_port.layout_for(deltas.dos):
        if f.name in by_hand:
            continue
        at = deltas.offset(f.offset)
        assert built.raw[at:at + f.size] == _swap(
            f.kind, drec[f.offset:f.offset + f.size]), (game, f.name)
        checked += 1
    assert checked == len(dos_port.layout_for(deltas.dos)) - len(by_hand)


_READER_NOTE = "a note the reader made about its own source"


def test_por_a_reader_warning_reaches_warnings_and_never_losses():
    char = boundarychars._base()
    char.warnings.append(_READER_NOTE)
    _, _, _, rep, _ = _por_readback(char)
    assert _READER_NOTE in rep.warnings
    assert rep.losses == []


@pytest.mark.parametrize("game", laterchars.GAMES)
def test_later_a_reader_warning_reaches_warnings_and_never_losses(game):
    char = doswidths.c64_sourced(laterchars.caster(game))
    char.warnings.append(_READER_NOTE)
    _, rep, _ = _later_readback(char)
    assert _READER_NOTE in rep.warnings
    assert rep.losses == []


def test_por_a_space_stripped_from_a_name_is_a_warning_and_not_a_loss():
    char = boundarychars._base()
    char.set("name", "A B", "boundary")
    _, _, _, rep, _ = _por_readback(char)
    assert rep.losses == []
