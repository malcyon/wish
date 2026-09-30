from __future__ import annotations

"""Silver Blades spell 100 is BESTOW CURSE, a magic-user 4 spell.

DOS's spell table and the C64's both give it that class and level, so it is
named with them and it has a spellbook row like every other learnable spell.
The C64 trainer's menu still never offers it, and `levelup.learnable` models
that menu.
"""

import pytest

from goldbox import levelup, spells
from goldbox.record import CharacterRecord

SSB = spells.SECRET_OF_THE_SILVER_BLADES
NAMES = {100: "BESTOW CURSE"}


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_spell_100_is_a_magic_user_4_spell():
    assert spells.spell_group(100, SSB) == ("magic-user", 4)
    assert 100 not in SSB.not_a_spell
    assert SSB.in_spellbook(100)


def test_it_is_named_with_its_class_and_level():
    assert spells.describe(100, NAMES, SSB) == "BESTOW CURSE (magic-user 4)"


def test_the_c64_trainer_menu_never_offers_it():
    rec = CharacterRecord.blank()
    rec.set("level_magic_user", 14)
    rec.set("intelligence", 18)
    assert 100 in SSB.not_granted
    assert 100 not in levelup.learnable(rec, SSB, level=14)


def test_a_scroll_holding_it_shows_its_class_and_level():
    from editor.inventory import ItemTraitsModel
    from goldbox.dos_codec import C64_SCROLL_TYPES
    from goldbox.items import TYPE_LOCATION, Item, ItemType

    kind = bytearray(32)
    scroll = C64_SCROLL_TYPES["secret-of-the-silver-blades"][0]
    kind[TYPE_LOCATION] = 10                       # where its scrolls sit
    raw = bytearray(16)
    raw[0] = scroll
    raw[13] = 100
    m = ItemTraitsModel()
    m.set_tables({scroll: ItemType(scroll, bytes(kind))}, NAMES, SSB)
    m.set_item(Item(bytes(raw), {}))
    assert dict(m.rows)["Spells"] == "BESTOW CURSE (magic-user 4)"


def test_the_spellbook_widget_has_a_checked_row_for_it(app):
    from PyQt6.QtWidgets import QListWidget

    from editor.spellwidget import SpellbookEditor

    widget = SpellbookEditor(QListWidget())
    widget.set_names(NAMES, SSB)
    raw = bytearray(SSB.spellbook_size)
    raw[100 >> 3] |= 1 << (100 & 7)
    widget.set_bytes(bytes(raw))
    row = widget._rows[100]
    assert row.text() == "BESTOW CURSE (magic-user 4)"
    assert row.checkState().value == 2
    assert 100 in widget.known()
    assert widget.to_bytes() == bytes(raw)
