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
bundle's spell nodes as items. `walk` is the engine's shape and
`slice_naively` is the other one; the tests below pin the disagreement on
composed bytes, because no save on this machine carries a bundle.

The engine tests read the player's own archives through
`tools/dosbox.find_game` and skip cleanly without them; no game bytes are in
this repository.
"""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import dosscrollbundle as sb  # noqa: E402

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
    from tools import dosxpaward
    try:
        path = dosxpaward.find_game(stem) / "GAME.OVR"
    except FileNotFoundError:
        pytest.skip(f"needs the DOS {stem} archive; set FR_ARCHIVES")
    if not path.is_file():
        pytest.skip(f"no GAME.OVR beside DOS {stem}")
    return path.read_bytes()


def _far_loads(ovr: bytes, displacement: int) -> int:
    from tools import dosfieldrefs
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
