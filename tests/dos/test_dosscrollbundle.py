from __future__ import annotations

"""The four extra bytes of a DOS Silver Blades item are a chain, not padding.

`#254 (Two DOS gaps the Amiga port gives a shape to: a 16-bit field in
gap_13c, and a pointer at the end of the Silver Blades item)`. Silver Blades'
item is 67 bytes where the other five DOS engines' is 63, and `0x03F`-`0x042`
is a far pointer to another 67-byte item node. One item type uses it:
`type_index` `0x49`, the bundle the JOIN command makes out of scrolls, whose
`quantity` sub-scrolls hang off it carrying three spell ids each.

The consequence a reader has to know about is that **the chain is written into
the `.STF` file**, inline after its head item, while `item_count` counts head
items only. So a file holding a bundle has more 67-byte records than
`item_count` says, and taking the first `item_count` of them reads the
bundle's spell nodes as items. `walk` is the engine's form and
`slice_naively` is the other one; the tests below pin the disagreement on
composed bytes, because no save on this machine carries a bundle.

The engine tests read the player's own archives through
`tools/dos/dosbox.find_game` and skip cleanly without them; no game bytes are in
this repository.
"""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.dos import dosscrollbundle as sb  # noqa: E402

STRIDE = 67


def _item(type_index: int, quantity: int = 0, spells=(0, 0, 0),
          text: str = "") -> bytes:
    """One synthetic 67-byte item. Composed here, never sliced out of a save."""
    data = bytearray(STRIDE)
    data[0] = len(text)
    data[1:1 + len(text)] = text.encode("ascii")
    data[0x02E] = type_index
    data[0x039] = quantity
    data[0x03C], data[0x03D], data[0x03E] = spells
    return bytes(data)


# --- the walk ----------------------------------------------------------------


def test_a_file_with_no_bundle_is_one_entry_per_record():
    items = _item(0x27, spells=(113, 111, 51)) + _item(0x1E, quantity=30)
    entries = sb.walk(items, STRIDE)
    assert [e["index"] for e in entries] == [0, 1]
    assert all(e["subnodes"] == [] for e in entries)


def test_a_bundle_swallows_the_records_that_follow_it():
    """A bundle of two is three records in the file and one item in the pack."""
    items = (_item(sb.SCROLL_BUNDLE, quantity=2)
             + _item(0x27, spells=(1, 2, 3))
             + _item(0x27, spells=(4, 0, 0))
             + _item(0x08, text="Mace +1"))
    entries = sb.walk(items, STRIDE)
    assert [e["index"] for e in entries] == [0, 3]
    assert entries[0]["subnodes"] == [1, 2]


def test_the_flat_slice_and_the_engine_disagree_about_a_bundle():
    """What a player loses: the pack ends at the bundle's spell nodes.

    `item_count` is 2 -- the bundle and the mace -- so a reader taking the
    first two records hands back the bundle and one of its own spell nodes,
    and the mace is gone.
    """
    items = (_item(sb.SCROLL_BUNDLE, quantity=2)
             + _item(0x27, spells=(1, 2, 3))
             + _item(0x27, spells=(4, 0, 0))
             + _item(0x08, text="Mace +1"))
    heads = [e["index"] for e in sb.walk(items, STRIDE)]
    assert heads == [0, 3]
    assert sb.slice_naively(items, STRIDE, 2) == [0, 1]


def test_a_chain_that_runs_off_the_end_is_an_error_rather_than_a_guess():
    items = _item(sb.SCROLL_BUNDLE, quantity=3) + _item(0x27)
    with pytest.raises(ValueError, match="bundle of 3"):
        sb.walk(items, STRIDE)


def test_a_63_byte_title_has_no_chain_to_walk():
    """The stride is what says whether the field exists at all, so the same
    byte at `0x2E` in a Pool of Radiance item cannot start a chain."""
    items = bytearray(63 * 2)
    items[0x02E] = sb.SCROLL_BUNDLE
    items[0x039] = 1
    assert [e["subnodes"] for e in sb.walk(bytes(items), 63)] == [[], []]


# --- the spells --------------------------------------------------------------


def test_a_plain_scroll_carries_its_own_three_ids():
    items = _item(0x27, spells=(113, 111, 51))
    assert sb.spells_of(items, STRIDE, sb.walk(items, STRIDE)[0]) == \
        [113, 111, 51]


def test_a_bundle_carries_three_ids_per_sub_node_and_none_of_its_own():
    items = (_item(sb.SCROLL_BUNDLE, quantity=2)
             + _item(0x27, spells=(1, 2, 3))
             + _item(0x28, spells=(4, 5, 0)))
    assert sb.spells_of(items, STRIDE, sb.walk(items, STRIDE)[0]) == \
        [1, 2, 3, 4, 5]


def test_the_top_bit_of_a_spell_id_is_a_flag_and_not_part_of_the_id():
    items = _item(0x27, spells=(0x80 | 51, 0, 0))
    assert sb.spells_of(items, STRIDE, sb.walk(items, STRIDE)[0]) == [51]


def test_three_bytes_of_a_weapon_are_charges_effect_and_power():
    """The negative control: the same three bytes in a non-scroll are not
    spells, and reading them as spells is how a wand acquires a spellbook."""
    items = _item(0x34, spells=(4, 87, 0), text="Wand of Ice Storm")
    assert sb.spells_of(items, STRIDE, sb.walk(items, STRIDE)[0]) == []


# --- the engines themselves --------------------------------------------------


def _overlay(stem: str) -> bytes:
    from tools.dos import dosxpaward
    try:
        path = dosxpaward.find_game(stem) / "GAME.OVR"
    except FileNotFoundError:
        pytest.skip(f"needs the DOS {stem} archive; set FR_ARCHIVES")
    if not path.is_file():
        pytest.skip(f"no GAME.OVR beside DOS {stem}")
    return path.read_bytes()


def _far_loads(ovr: bytes, displacement: int) -> int:
    from tools.dos import dosfieldrefs
    return sum(1 for r in dosfieldrefs.references(ovr, displacement,
                                                  prefixes=(0x26,))
               if r["mnem"].startswith(("les", "lds")))


def test_silver_blades_loads_a_far_pointer_from_the_end_of_an_item():
    assert _far_loads(_overlay("SECRET"), 0x03F) >= 20


@pytest.mark.parametrize(
    "stem", ["POOLRAD", "CURSE", "GATEWAY", "DARKNESS", "TREASURE"])
def test_no_63_byte_title_loads_one(stem):
    """The control. Their items end at `0x03E`, and none of the five reaches
    past it for a pointer -- so the 41 in Silver Blades are not a pattern that
    matches everywhere."""
    assert _far_loads(_overlay(stem), 0x03F) == 0


def test_only_silver_blades_ever_writes_the_bundle_type_into_an_item():
    """`mov byte ptr es:[di+0x2e], 0x49`, once, in the JOIN routine.

    A type nothing writes is a type no save can hold, which is why the other
    five compare against `0x49` -- they read scrolls -- and never store it.
    """
    store = b"\x26\xc6\x45\x2e" + bytes([sb.SCROLL_BUNDLE])
    assert _overlay("SECRET").count(store) == 1
    for stem in ("POOLRAD", "CURSE", "GATEWAY", "DARKNESS", "TREASURE"):
        assert _overlay(stem).count(store) == 0, stem


# --- stage: a slot whose members carry the joined scrolls asked for ----------

#: Seven spell ids are enough to tell 42 staged scrolls apart.
IDS = [9, 10, 11, 12, 13, 14, 15]
#: Made-up templates of the four kinds, as `item_templates` returns them.
ITEMS = {
    "scroll": bytes((0x27, 1, 2, 3, 0, 0, 4, 0, 10, 0, 0, 0xB8, 0x0B, 1, 2, 3)),
    "staff": bytes((0x0F, 0, 0, 0x0F, 0, 0, 0, 0, 50, 0, 0, 10, 0, 0, 0, 0)),
    "darts": bytes((0x05, 0, 0, 0x05, 0, 0, 0, 0, 5, 0, 4, 0, 0, 0, 0, 0)),
    "arrows": bytes((0x1E, 0, 0, 0x1E, 0, 0, 0, 0, 3, 0, 10, 0, 0, 0, 0, 0)),
}


def _slot(tmp_path: pathlib.Path, members: int = 3) -> pathlib.Path:
    """A Silver Blades slot A of composed records with empty packs: each
    record is this project's own writer's, from a filled neutral character."""
    from support.neutralrecords import _filled

    from goldbox import c64_port, dos_codec, dos_port
    record, _itm, _spc, _rep = dos_codec.write(
        _filled(c64_port.SECRET_OF_THE_SILVER_BLADES),
        deltas=dos_port.SECRET_OF_THE_SILVER_BLADES)
    save = tmp_path / "save"
    save.mkdir()
    (save / "SAVGAMA.DAT").write_bytes(bytes(5469))
    count = dos_port.FIELDS_BY_NAME_FOR[
        dos_port.SECRET_OF_THE_SILVER_BLADES.key]["item_count"].offset
    for n in range(1, members + 1):
        out = bytearray(record)
        out[count] = 0          # an empty pack, as the archives' slot A holds
        out[0x0B0] = n          # a byte the stage must not touch
        (save / f"CHRDATA{n}.SAV").write_bytes(bytes(out))
    return save


def _staged(tmp_path):
    save = _slot(tmp_path)
    packs = {2: sb.parse_pack("j10*2,s*2,staff"), 1: sb.parse_pack("s*3")}
    out = tmp_path / "out"
    report = sb.stage(save, "A", packs, out, IDS, ITEMS)
    return save, out, report


def test_the_staged_file_walks_back_as_the_bundles_asked_for(tmp_path):
    _save, out, _report = _staged(tmp_path)
    items = (out / "CHRDATA2.STF").read_bytes()
    entries = sb.walk(items, STRIDE)
    assert [e["type"] for e in entries] == [sb.SCROLL_BUNDLE] * 2 + [0x27] * 2 + [0x0F]
    assert [len(e["subnodes"]) for e in entries] == [10, 10, 0, 0, 0]
    assert sb.item_count((out / "CHRDATA2.SAV").read_bytes()) == 5
    assert sb.item_count((out / "CHRDATA1.SAV").read_bytes()) == 3
    assert [e["subnodes"] for e in sb.walk((out / "CHRDATA1.STF").read_bytes(),
                                           STRIDE)] == [[], [], []]


def test_every_staged_scroll_in_the_party_carries_its_own_three_spells(tmp_path):
    _save, out, report = _staged(tmp_path)
    seen = []
    for n in (1, 2):
        items = (out / f"CHRDATA{n}.STF").read_bytes()
        for entry in sb.walk(items, STRIDE):
            for index in entry["subnodes"] or [entry["index"]]:
                node = items[index * STRIDE:(index + 1) * STRIDE]
                if node[0x2E] == 0x27:
                    seen.append(tuple(node[0x3C:0x3F]))
    assert len(seen) == 3 + 22 == len(set(seen))
    assert all(set(s) <= set(IDS) for s in seen)
    assert report["lines"][1]["first_scroll"] == 0
    assert report["lines"][2]["first_scroll"] == 3


def test_the_head_is_the_one_join_makes(tmp_path):
    """Type 0x49, names 0x27, the count and 0x4D, weight and quantity the
    count, value the scrolls' sum, and no spells of its own."""
    _save, out, _report = _staged(tmp_path)
    head = (out / "CHRDATA2.STF").read_bytes()[:STRIDE]
    assert head[0x2E:0x32] == bytes((0x49, 0x27, 10, 0x4D))
    assert int.from_bytes(head[0x37:0x39], "little") == 10 and head[0x39] == 10
    assert int.from_bytes(head[0x3A:0x3C], "little") == 10 * 3000
    assert head[0x3C:0x3F] == bytes(3)


def test_only_the_pack_count_and_weight_change_in_the_record(tmp_path):
    from goldbox import dos_port
    fields = dos_port.FIELDS_BY_NAME_FOR[dos_port.SECRET_OF_THE_SILVER_BLADES.key]
    save, out, _report = _staged(tmp_path)
    allowed = set()
    for name in ("item_count", "encumbrance"):
        f = fields[name]
        allowed |= set(range(f.offset, f.offset + f.size))
    for n in (1, 2, 3):
        before = (save / f"CHRDATA{n}.SAV").read_bytes()
        after = (out / f"CHRDATA{n}.SAV").read_bytes()
        assert len(after) == len(before)
        assert {i for i in range(len(before)) if before[i] != after[i]} <= allowed
    enc = fields["encumbrance"]
    staff = sb.stage(save, "A", {2: sb.parse_pack("staff")}, tmp_path / "staff",
                     IDS, ITEMS)
    assert staff["lines"][2]["joined"] == []

    def weight(folder):
        rec = (folder / "CHRDATA2.SAV").read_bytes()
        return int.from_bytes(rec[enc.offset:enc.offset + enc.size], "little")
    # The same money either way, so the difference is the pack: each joined
    # scroll's head weighs 10 x quantity 10, the loose scrolls 10 each.
    assert weight(out) - weight(tmp_path / "staff") == 2 * 10 * 10 + 2 * 10
    assert (out / "SAVGAMA.DAT").read_bytes() == (save / "SAVGAMA.DAT").read_bytes()
    assert not (out / "CHRDATA3.STF").exists()
    assert sorted(p.name for p in save.iterdir()) == [
        "CHRDATA1.SAV", "CHRDATA2.SAV", "CHRDATA3.SAV", "SAVGAMA.DAT"]


@pytest.mark.parametrize("spec,why", [
    ("j11", "2 to 10"), ("j1", "2 to 10"), ("s*17", "at most 16"),
    ("j10*12,s*4,staff", "at most 16"), ("wand", "no item called"),
    ("s*0", "repeats nothing"), ("x!", "not a pack item"),
])
def test_a_pack_the_game_never_holds_is_blocked(spec, why):
    with pytest.raises(ValueError, match=why):
        sb.parse_pack(spec)


def test_a_line_outside_the_party_and_a_used_folder_are_blocked(tmp_path):
    save = _slot(tmp_path)
    with pytest.raises(ValueError, match="line 4 is not in a party of 3"):
        sb.stage(save, "A", {4: [("scroll", 1)]}, tmp_path / "a", IDS, ITEMS)
    used = tmp_path / "used"
    used.mkdir()
    (used / "x").write_bytes(b"")
    with pytest.raises(ValueError, match="not empty"):
        sb.stage(save, "A", {1: [("scroll", 1)]}, used, IDS, ITEMS)


def test_the_staged_scrolls_take_only_levelled_magic_user_ids():
    from tools.dos import dosbox
    try:
        game = dosbox.find_game("SECRET")
    except FileNotFoundError:
        pytest.skip("needs the DOS Silver Blades archive")
    ids = sb.mage_spell_ids(game)
    # Two of the game's own mage scroll templates carry 112, 115, 91 and 82, 83, 88.
    assert len(ids) == 53 and {82, 83, 88, 91, 112, 115} <= set(ids)
    assert 109 not in ids and 1 not in ids


def test_every_staged_scroll_has_three_different_ids_and_its_own_three():
    n = len(IDS)
    triples = [sb.scroll_spells(k, IDS) for k in range(n * (n - 1))]
    assert all(len(set(t)) == 3 for t in triples)
    assert len(set(triples)) == len(triples)
    with pytest.raises(ValueError, match="at most 42"):
        sb.scroll_spells(n * (n - 1), IDS)


def test_only_a_scrolls_spells_differ_from_its_template(tmp_path):
    _save, out, _report = _staged(tmp_path)
    items = (out / "CHRDATA1.STF").read_bytes()
    from goldbox import dos_codec
    for i in range(3):
        got = dos_codec.item_to_c64(items[i * STRIDE:i * STRIDE + 0x3F] + bytes(4))
        assert got[:13] == ITEMS["scroll"][:13]


def test_a_bad_stage_is_one_line_and_exit_two(tmp_path, capsys):
    assert sb.main(["stage", "--out", str(tmp_path / "o"), "--pack", "1=j11"]) == 2
    err = capsys.readouterr().err
    assert err == "stage: a joined scroll holds 2 to 10 scrolls, not 11\n"
    assert not (tmp_path / "o").exists()


def test_the_templates_come_from_the_titles_own_item_files():
    from tools.dos import dosbox
    try:
        game = dosbox.find_game("SECRET")
    except FileNotFoundError:
        pytest.skip("needs the DOS Silver Blades archive")
    got = sb.item_templates(game)
    assert {k: v[0] for k, v in got.items()} == sb.ITEM_TYPES
    assert all(got["scroll"][13:16]) and got["scroll"][6] & 0x07 == 4
    assert all(got[k][4] == 0 for k in sb.ORDINARY)
