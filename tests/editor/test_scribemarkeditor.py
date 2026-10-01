"""A scroll's spell marked as being scribed is named by its real spell.

DOS and Amiga add 128 to the byte while a scribe is pending.  Spell names here
are made up: the test is about which id is looked up, not the game's words.
"""
from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication, QTreeWidget
from support import packoverflow as packs

from editor.inventory import ItemTraitsModel
from editor.leavebehind import LeaveBehindDialog
from goldbox import c64_port, dos_codec
from goldbox.items import LOCATION_USABLE_MAGIC, TYPE_LOCATION, Item
from goldbox.spells import for_game

TITLES = {"Pool": c64_port.POOL_OF_RADIANCE,
          "Curse": c64_port.CURSE_OF_THE_AZURE_BONDS,
          "Silver Blades": c64_port.SECRET_OF_THE_SILVER_BLADES}
NAMES = {n: f"SPELL{n}" for n in range(1, 60)}
SCROLL_LOCATION = 10


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _model(game) -> ItemTraitsModel:
    model = ItemTraitsModel()
    model.set_tables({}, NAMES, for_game(game))
    return model


class _Kind:
    def __init__(self, location):
        self.raw = [0] * (TYPE_LOCATION + 1)
        self.raw[TYPE_LOCATION] = location


@pytest.mark.parametrize("title", TITLES)
def test_a_marked_spell_is_named_as_the_unmarked_one_is(title):
    model = _model(TITLES[title])
    for n in (1, 5, 56):
        assert model._scroll_spell(128 + n) == model._spell(n)


@pytest.mark.parametrize("title", TITLES)
def test_a_byte_past_the_last_spell_keeps_the_item_only_text(title):
    model = _model(TITLES[title])
    last = model.spells.last_spell
    for sid in (128, 128 + last + 1, 246, 255):
        assert model._scroll_spell(sid) == model._spell(sid)
    assert "effect" in model._scroll_spell(255)


def test_a_scroll_row_names_every_marked_spell():
    model = _model(TITLES["Silver Blades"])
    item = Item(packs.scroll(129, 130, 5), NAMES)
    rows = model._power_rows(item, _Kind(SCROLL_LOCATION))
    assert rows == [("Spells", ", ".join(model._spell(n) for n in (1, 2, 5)))]


def test_an_item_that_is_not_a_scroll_reads_its_high_byte_as_before():
    model = _model(TITLES["Silver Blades"])
    raw = bytearray(packs.ordinary(0))
    raw[13:16] = bytes((200, 129, 0))
    rows = model._power_rows(Item(bytes(raw), NAMES),
                             _Kind(LOCATION_USABLE_MAGIC))
    assert rows[0] == ("Charges", "200")
    assert "SPELL1" not in repr(rows)


def test_the_leave_behind_dialog_names_a_marked_spell(app):
    game = TITLES["Silver Blades"]
    party = [packs.member("ALPHA", 15, packs.scroll(128 + 5), packs.scroll(6))]
    dialog = LeaveBehindDialog(dos_codec.pack_overflow(party), {}, NAMES,
                               for_game(game), "Accept")
    texts = []

    def walk(item):
        texts.append(item.text(0))
        for n in range(item.childCount()):
            walk(item.child(n))
    view = dialog.findChild(QTreeWidget)
    for n in range(view.topLevelItemCount()):
        walk(view.topLevelItem(n))
    assert any(t.startswith(_model(game)._spell(5)) for t in texts)
    assert not any("effect" in t for t in texts)


def _morgaine_scroll_rows(name):
    from gamedata import specimen_root
    from support.amigalaterwrite import _verified

    from editor.roster import Party
    root = specimen_root()
    where = None if root is None else root / "ssb-dos" / f"WISH-SPEC-{name}"
    if where is None or not where.is_dir():
        pytest.skip(f"needs specimen ssb-dos/WISH-SPEC-{name}")
    _verified(where)
    party = Party(str(where))
    member = next(m for m in party.members if m.name == "MORGAINE")
    raw = member.record.get_raw("inventory")[:16]
    model = _model(TITLES["Silver Blades"])
    return model._power_rows(Item(bytes(raw), NAMES), _Kind(SCROLL_LOCATION))


def test_a_game_written_mid_scribe_scroll_shows_the_rows_of_the_reloaded_one():
    mid = _morgaine_scroll_rows("dos-ssb-745-mid-scribe")
    after = _morgaine_scroll_rows("dos-ssb-745-after-reload")
    assert mid == after
    assert "effect" not in repr(mid)
