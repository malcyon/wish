"""The Effect row and tooltip read item byte +14 with the open title's rule."""

import pytest

from goldbox import spells
from goldbox.items import Item, load_item_names, load_item_templates
from goldbox.spells import describe, load_spell_names

CURSE = "curse-of-the-azure-bonds"
SSB = "secret-of-the-silver-blades"


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _title(key):
    from automap import gamedisks
    where = gamedisks.find(key)
    first = None if where is None else next(iter(sorted(
        where.glob("*.[dD]64"))), None)
    if first is None:
        pytest.skip(f"needs the {key} disks")
    from goldbox import c64_port
    table = spells.BY_KEY[key]
    game = c64_port.by_key(key)
    return (table, load_spell_names(str(first), table),
            load_item_templates(str(first), game=game),
            load_item_names(str(first), game))


def _rows(app, key, name):
    from editor.inventory import ItemTraitsModel
    table, names, tpl, item_names = _title(key)
    m = ItemTraitsModel()
    m.set_tables({}, names, table)
    m.set_item(Item(tpl[name], item_names))
    return dict(m.rows), names, table


@pytest.mark.parametrize("key, name, sid", [
    (SSB, "WAND OF ICE STORM", 87),
    (SSB, "EYES OF CHARMING", 10),
    (CURSE, "WAND OF FIREBALLS", 47),
])
def test_a_wand_names_its_own_spell(app, key, name, sid):
    rows, names, table = _rows(app, key, name)
    assert rows["Effect"] == describe(sid, names, table)
    assert "CAUSE SERIOUS WOUNDS" not in rows["Effect"]


@pytest.mark.parametrize("name, sid", [("POTION OF SPEED", 57),
                                       ("POTION EXTRA HEALING", 99)])
def test_a_curse_potion_shows_the_item_only_line(app, name, sid):
    rows, _names, _table = _rows(app, CURSE, name)
    assert rows["Effect"].startswith(f"effect {sid} ")
    assert "argument to the power" not in rows["Effect"]


def test_the_items_tooltip_uses_the_title_rule(app):
    from editor.inventory import InventoryModel
    table, _names, tpl, _ = _title(SSB)
    model = InventoryModel()
    model.set_spells(table)
    tip = model._tooltip(0, Item(tpl["WAND OF ICE STORM"]))
    assert "effect: spell 87" in tip
    default = InventoryModel()._tooltip(0, Item(tpl["WAND OF ICE STORM"]))
    assert "effect: spell 64" in default      # Pool's rule, 87 - 23
