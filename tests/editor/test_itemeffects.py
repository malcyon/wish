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


def test_a_curse_potion_of_speed_is_named(app):
    rows, _names, _table = _rows(app, CURSE, "POTION OF SPEED")
    assert rows["Effect"] == "Potion of Speed"


def test_another_unmapped_curse_effect_keeps_the_item_only_line(app):
    rows, _names, _table = _rows(app, CURSE, "POTION EXTRA HEALING")
    assert rows["Effect"].startswith("effect 99 ")
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


# --- the window hands the title's table to the Items list --------------------

def _binding(tmp_path, key, glob, only_the_save=False):
    """An editor window on a copy of the title's own save disk, or a skip."""
    import shutil

    from automap import gamedisks
    from goldbox import c64_port
    from goldbox.d64 import D64
    game = c64_port.by_key(key)
    where = gamedisks.find(key)
    if where is None:
        pytest.skip(f"needs the {key} disks")
    save = None
    for disk in sorted(where.glob(glob)):
        try:
            d = D64.open(disk)
            entry = d.find(game.save_file)
            if entry is not None and game.matches_payload(d.read_file(entry)):
                save = disk
                break
        except Exception:
            continue
    if save is None:
        pytest.skip(f"no {key} disk carries a whole save")
    if only_the_save:
        shutil.copy(save, tmp_path / save.name)
    else:
        for disk in sorted(where.glob(glob)):
            shutil.copy(disk, tmp_path / disk.name)
    from support.editorwindow import make_root

    from editor.window import EditorBinding
    return EditorBinding(make_root(), str(tmp_path / save.name))


@pytest.mark.parametrize("key, glob", [(CURSE, "CURSE*.[dD]64"),
                                       (SSB, "SILVER*.[dD]64")])
def test_the_window_gives_the_items_list_its_titles_table(app, tmp_path,
                                                          key, glob):
    window = _binding(tmp_path, key, glob)
    assert window.game_disk_found is not None
    assert window.items.spells.key == key


@pytest.mark.parametrize("key, glob", [(CURSE, "CURSE*.[dD]64"),
                                       (SSB, "SILVER*.[dD]64")])
def test_the_items_list_has_its_titles_table_with_no_game_disk(
        app, tmp_path, monkeypatch, key, glob):
    """The save disk carries its own charset, so the no-disk branch is reached
    by making the search find nothing and reloading."""
    window = _binding(tmp_path, key, glob)
    window.items.set_spells(spells.POOL_OF_RADIANCE)
    monkeypatch.setattr(window, "_find_game_disk", lambda: None)
    window._load_game_disk()
    assert window.game_disk_found is None
    assert window.items.spells.key == key


# --- Pool of Radiance keeps its rule -----------------------------------------

def test_pool_of_radiance_potion_of_speed_stays_57(app):
    from automap import gamedisks
    from editor.inventory import InventoryModel, ItemTraitsModel
    from goldbox import c64_port
    where = gamedisks.find("pool-of-radiance")
    first = None if where is None else next(iter(sorted(
        where.glob("POOL*.[dD]64"))), None)
    if first is None:
        pytest.skip("needs the Pool of Radiance disks")
    table = spells.POOL_OF_RADIANCE
    game = c64_port.by_key(table.key)
    item = Item(load_item_templates(str(first), game=game)["POTION OF SPEED"],
                load_item_names(str(first), game))
    traits = ItemTraitsModel()
    traits.set_tables({}, load_spell_names(str(first), game), table)
    traits.set_item(item)
    assert dict(traits.rows)["Effect"] == \
        "effect 57 — the item-only range past RESTORATION"
    assert "effect: spell 57" in InventoryModel()._tooltip(0, item)


# --- "Potion of Speed" is scoped to a Curse potion (no disks needed) ---------

def _synthetic(key, type_index, *, effect=57, charges=0, types=None):
    from editor.inventory import ItemTraitsModel
    raw = bytearray(16)
    raw[0] = type_index
    raw[13], raw[14] = charges, effect
    m = ItemTraitsModel()
    m.set_tables(types or {}, {}, spells.BY_KEY[key])
    m.set_item(Item(bytes(raw)))
    return dict(m.rows)


def test_a_synthetic_curse_potion_of_speed_is_named(app):
    from editor.inventory import CURSE_POTION_TYPE
    assert _synthetic(CURSE, CURSE_POTION_TYPE)["Effect"] == "Potion of Speed"


def test_silver_blades_effect_57_keeps_the_item_only_line(app):
    from editor.inventory import CURSE_POTION_TYPE
    row = _synthetic(SSB, CURSE_POTION_TYPE)["Effect"]
    assert row.startswith("effect 57 ")


def test_a_curse_non_potion_with_57_keeps_the_item_only_line(app):
    from editor.inventory import CURSE_POTION_TYPE
    row = _synthetic(CURSE, CURSE_POTION_TYPE + 8)["Effect"]
    assert row.startswith("effect 57 ")


def test_a_curse_scroll_spell_byte_57_keeps_its_text(app):
    from goldbox.items import ItemType
    scroll = 0x3D
    types = {scroll: ItemType(scroll, bytes(16))}
    row = _synthetic(CURSE, scroll, effect=57, types=types)["Spells"]
    assert row.startswith("effect 57 ")
    assert "Potion of Speed" not in row
