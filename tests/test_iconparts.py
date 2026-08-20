"""The icon editor's option tables, and the set of icons the game can make."""

import pathlib

import pytest

from por.icons import ICON_COUNT, icon_for_slot
from por.savegame import SaveGame0
from por.iconparts import CELLS_PER_POSE, SPACE, IconParts

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def parts() -> IconParts:
    return IconParts((FIXTURES / "SPELLE64.bin").read_bytes(),
                     (FIXTURES / "SPELLN64.bin").read_bytes())


@pytest.fixture(scope="module")
def legal(parts) -> set[bytes]:
    """The whole reachable set. Slow enough to be worth computing once."""
    return parts.legal_shapes()


def test_the_counts_come_from_the_overlay_not_from_here(parts):
    """`$B0DA` holds `1C 0E 23 17` and `$B0DE` the four table addresses.

    Read rather than hardcoded, so a different build would be parsed correctly
    instead of being silently mis-sliced into plausible-looking rubbish.
    """
    assert parts.count("large", "weapon") == 28
    assert parts.count("large", "head") == 14
    assert parts.count("small", "weapon") == 35
    assert parts.count("small", "head") == 23
    assert parts.tables[("small", "weapon")][0] == 0xA800
    assert parts.tables[("small", "head")][0] == 0xA8F0
    assert parts.tables[("large", "weapon")][0] == 0xA9E0
    assert parts.tables[("large", "head")][0] == 0xAAD0


def test_a_composed_icon_is_eighteen_cells(parts):
    shape = parts.compose("small", 0, 1)
    assert len(shape) == CELLS_PER_POSE * 2
    assert shape != bytes([SPACE]) * len(shape)


def test_the_factory_default_is_small_weapon_zero_head_one(parts):
    """The commonest shape in the corpus, and it reconstructs exactly."""
    assert parts.compose("small", 0, 1).hex() == (
        "20a02086878806070820a020898a8b061011")


def test_changing_the_weapon_keeps_the_head(parts):
    """`$B26F`/`$B29B` save cells 0, 1, 9 and 10 and restore them.

    Without it the two menu items would not be independent and the reachable
    set would collapse to roughly the number of weapons.
    """
    one = parts.compose("small", 0, 5)
    two = parts.apply(one, "small", "weapon", 9)
    assert two[1] == one[1] and two[10] == one[10]
    assert two[4] != one[4]              # the body did change


def test_the_reachable_set_is_bigger_than_the_naive_product(parts, legal):
    """35x23 would be 805. Order matters and the two size pairs interact, so
    the real answer is larger -- which is why the editor explores rather than
    enumerating pairs."""
    assert len(parts.legal_shapes(("small",))) == 3138
    assert len(parts.legal_shapes(("large",))) == 1227
    assert len(legal) == 15328
    assert len(legal) > 35 * 23 + 28 * 14


def test_every_icon_we_hold_is_one_the_game_could_have_made(legal):
    """The check that the model is right rather than merely self-consistent.

    Only some of these reconstruct from a single (weapon, head) pair; the rest
    need a sequence, including one that mixes a large body with a small head.
    All of them are reachable.
    """
    shapes = set()
    for name in ("savedgame0.bin", "party6_savedgame0.bin",
                 "pool1_savedgame0.bin", "party6_after_combat.bin"):
        # The fixtures keep their two-byte load address; `from_prg` is what
        # strips it. Reading them raw shifts every icon two cells and makes
        # perfectly legal art look unreachable.
        save0 = SaveGame0.from_prg((FIXTURES / name).read_bytes()).to_bytes()
        for slot in range(ICON_COUNT):
            shape = bytes(icon_for_slot(save0, slot).shape)
            if set(shape) != {SPACE} and any(shape):
                shapes.add(shape)
    assert shapes, "no icons in the fixtures"
    outside = [s.hex() for s in shapes if s not in legal]
    assert not outside, f"not reachable by any menu sequence: {outside}"


def test_an_option_out_of_range_is_refused(parts):
    with pytest.raises(ValueError):
        parts.compose("small", 35, 0)
    with pytest.raises(ValueError):
        parts.compose("large", 0, 14)


def test_the_colour_rule_reproduces_the_icons_we_hold(parts):
    """`colour[cell] = C[class(glyph)] | (8 if bit 7)`.

    103 of the 104 icon slots across every disk we have satisfy it cell for
    cell. The one that does not is SHARA THE GRAY on the shipped POOL1 party,
    which carries colour `$0F` in two cells where the rule allows only 0-7 plus
    the glyph's own bit 3 -- hand-authored art, not something the editor made.
    """
    save0 = SaveGame0.from_prg(
        (FIXTURES / "party6_savedgame0.bin").read_bytes()).to_bytes()
    checked = 0
    for slot in range(ICON_COUNT):
        icon = icon_for_slot(save0, slot)
        shape, colours = bytes(icon.shape), bytes(icon.colours)
        if set(shape) == {SPACE} or not any(shape):
            continue
        per_class = parts.part_colours(colours, shape)
        assert parts.colours_for(shape, per_class, colours) == colours
        checked += 1
    assert checked, "no icons to check"


def test_a_cell_holding_no_part_keeps_the_colour_it_had(parts):
    """The rule governs parts. A space has class $0F and its colour byte is
    residue -- inventing one disagreed with every icon in a save."""
    shape = parts.compose("small", 0, 1)
    existing = bytes([0x0E]) * len(shape)
    out = parts.colours_for(shape, {0: 1, 1: 2}, existing)
    for cell, glyph in enumerate(shape):
        if parts.part_class(glyph) >= 7:
            assert out[cell] == 0x0E


def test_the_editor_offers_only_icons_the_game_can_make(parts, legal, tmp_path):
    """The point of all of it. Whatever the picker is driven to, the result is
    a shape reachable from the game's own menus."""
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QApplication

    from editor.partspicker import PartsPicker
    from por.icons import load_icon_charset

    app = QApplication.instance() or QApplication([])
    charset = bytes(2048)               # shape is what matters, not the art
    shape = parts.compose("small", 0, 1)
    colours = parts.colours_for(shape, {k: 1 for k in range(7)}, bytes(18))
    dialog = PartsPicker(parts, charset, shape, colours)

    for row in (3, 17, 30):
        dialog.weapons.setCurrentRow(row)
        assert dialog.shape in legal
    for row in (2, 11, 22):
        dialog.heads.setCurrentRow(row)
        assert dialog.shape in legal
    dialog.size_box.setCurrentText("large")
    dialog.weapons.setCurrentRow(5)
    assert dialog.shape in legal, "mixing sizes must stay inside the set"
    assert len(dialog.shape) == CELLS_PER_POSE * 2
    app.processEvents()
