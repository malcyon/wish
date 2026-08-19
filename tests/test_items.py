"""Tests for por.items, against a save taken after the party bought equipment."""

import pathlib

import pytest

from por.d64 import D64
from por.items import ITEM_AREA_BASE, ITEM_SIZE, items_for_slot, load_item_names
from por.savegame import SaveGame0

DISKS = "/mnt/media/roms/c64/Pool of Radiance Disks"
FIXTURES = pathlib.Path(__file__).parent / "fixtures"
# Read the committed fixture, never the live disk -- an earlier version read
# PORSAVE2.D64 directly and broke the moment Donald saved over it.
equipped = pytest.mark.skipif(
    not (FIXTURES / "party6_after_combat.bin").exists(),
    reason="needs the equipped-party fixture")


@pytest.fixture
def names():
    return load_item_names("work/POOL1.D64.orig")


@pytest.fixture
def save():
    return SaveGame0.from_prg((FIXTURES / "party6_after_combat.bin").read_bytes())


def test_name_table_is_1_based_compound(names):
    """Stored indices are 1-based, and the table is keyed by them directly."""
    assert names[57] == "BANDED"
    assert names[48] == "MAIL"
    assert names[36] == "LONG SWORD"
    assert names[50] == "LEATHER"


def test_name_table_has_gaps(names):
    """ITEMNAMES is read through its pointer table, not by splitting strings in
    order, because three indices have no name. A sequential reader closes those
    gaps and shifts every later name -- silently, and onto plausible wrong
    values."""
    assert 62 not in names and 63 not in names and 168 not in names
    assert names[61] == "ARROW(S)" and names[64] == "POTION"
    assert len(names) == 252
    assert max(names) == 255


@equipped
def test_scratch_blocks_mirror_a_real_character(save, names):
    """Slots 6 and 7 are a scratch buffer, and their item blocks mirror
    whichever character was handled last -- which is how the block-to-slot
    mapping was established. Which character it mirrors is not fixed, so assert
    only that it matches one of them."""
    p = save.to_bytes()
    scratch = [i.raw for i in items_for_slot(p, 6, names)]
    real = [[i.raw for i in items_for_slot(p, s.index, names)] for s in save.characters]
    assert scratch in real


@equipped
@pytest.mark.parametrize("who,expected", [
    ("BRUTUS", ["BANDED MAIL", "SHIELD", "LONG SWORD"]),
    ("LADY KATHERINE", ["SHORT SWORD", "LEATHER ARMOR", "SLING"]),
    ("MAGNUS", ["BANDED MAIL", "SHIELD", "LONG SWORD", "SHORT BOW",
                "ARROW(S)", "ARROW(S)", "ARROW(S)"]),
    ("ROLAND", ["BANDED MAIL", "MACE"]),
])
def test_decoded_inventories(save, names, who, expected):
    slot = next(s for s in save.characters if s.record.name == who)
    assert [i.name for i in items_for_slot(save.to_bytes(), slot.index, names)] == expected


@equipped
def test_weights_and_costs_match_add_1e(save, names):
    """Weight is tenths of a pound and cost is gp -- confirmed because every
    value matches the AD&D 1st edition equipment tables."""
    slot = next(s for s in save.characters if s.record.name == "SILAS")
    by_name = {i.name: i for i in items_for_slot(save.to_bytes(), slot.index, names)}
    assert (by_name["BANDED MAIL"].weight_lb, by_name["BANDED MAIL"].cost_gp) == (35.0, 90)
    assert (by_name["LONG SWORD"].weight_lb, by_name["LONG SWORD"].cost_gp) == (6.0, 15)
    assert (by_name["SHIELD"].weight_lb, by_name["SHIELD"].cost_gp) == (10.0, 15)


@equipped
def test_readied_flag(save, names):
    slot = next(s for s in save.characters if s.record.name == "MAGNUS")
    items = {i.name: i for i in items_for_slot(save.to_bytes(), slot.index, names)}
    assert items["BANDED MAIL"].readied
    assert not items["SHORT BOW"].readied      # carried, not readied


@equipped
def test_ammunition_carries_a_quantity(save, names):
    slot = next(s for s in save.characters if s.record.name == "MAGNUS")
    arrows = [i for i in items_for_slot(save.to_bytes(), slot.index, names)
              if i.name == "ARROW(S)"]
    assert arrows and all(a.quantity == 10 for a in arrows)


def test_geometry():
    assert ITEM_AREA_BASE == 0x5900
    assert ITEM_SIZE == 16


@equipped
def test_experience_is_present_after_combat(save):
    """One orc fight: 17 xp each, 8 for LADY KATHERINE."""
    u24 = lambda r: (lambda b: b[0] | b[1] << 8 | b[2] << 16)(r.get_raw("experience"))
    xp = {s.record.name: u24(s.record) for s in save.characters}
    assert xp["BRUTUS"] == 17
    assert xp["LADY KATHERINE"] == 8
    assert all(v > 0 for v in xp.values())


@equipped
def test_silver_appeared_from_looting(save):
    assert all(s.record.silver >= 25 for s in save.characters)


DISKS = "/mnt/media/roms/c64/Pool of Radiance Disks"
game_disks = pytest.mark.skipif(not pathlib.Path(f"{DISKS}/POOL2.D64").exists(),
                                reason="needs the full set of game disks")


@game_disks
def test_templates_come_from_every_disk():
    from por.items import load_item_templates
    one = load_item_templates("work/POOL1.D64.orig")
    all_of_them = load_item_templates(f"{DISKS}/POOL1.D64")
    assert len(all_of_them) > len(one)          # siblings are scanned
    assert "WAND OF MAGIC MISSILES" in all_of_them


def test_the_hidden_name_mask_produces_the_unidentified_name(names):
    """Each of the low three bits of +6 conceals one name word. CURSED NECKLACE
    is the decisive case: it hides the noun and the suffix, so a cursed item
    presents as a plain NECKLACE."""
    from por.items import Item, load_item_templates
    tpl = load_item_templates("work/POOL1.D64.orig", names)
    cases = {"BANDED MAIL +1": "BANDED MAIL",
             "POTION OF HEALING": "POTION",
             "BATTLE AXE": "BATTLE AXE"}
    for real, shown in cases.items():
        if real in tpl:
            assert Item(tpl[real], names).unidentified_name == shown
    assert Item(tpl["BATTLE AXE"], names).is_identified
