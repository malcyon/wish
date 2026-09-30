"""The editor's details pane names a scroll's spells, in every C64 title.

Silver Blades' scrolls sit at ITEMS location 10, beside its wands, so the
type id and not the location has to say which item is a scroll.
"""

from __future__ import annotations

import pytest

from automap import gamedisks
from editor.inventory import ItemTraitsModel
from goldbox import c64_port, items, spells
from goldbox.d64 import D64

POOL = c64_port.POOL_OF_RADIANCE
CURSE = c64_port.CURSE_OF_THE_AZURE_BONDS
SSB = c64_port.SECRET_OF_THE_SILVER_BLADES

#: Per title: its scroll templates, then a location-10 item that is no scroll
#: and its charges.
CASES = {
    POOL: (("MU SCROLL WITH 3 SPELLS",), ("WAND OF MAGIC MISSILES", "20")),
    CURSE: (("MU SCROLL WITH 3 SPELLS", "CLER SCROLL WITH 3 SPELLS"),
            ("NECKLACE OF MISSILES", "7")),
    SSB: (("MAGE SCROLL 3 SPELLS", "CLER SCROLL 3 SPELLS"),
          ("WAND OF FIREBALLS", "8")),
}


def _tables(game):
    root = gamedisks.find(game.key)
    if root is None:
        pytest.skip(f"no {game.key} disks on this machine")
    for path in sorted(root.glob(game.disk_glob)):
        if D64.open(str(path)).find(b"ITEMS") is not None:
            break
    else:
        pytest.skip(f"no {game.key} side carries ITEMS")
    path = str(path)
    names = items.load_item_names(path, game)
    templates = items.load_item_templates(path, names, game=game)
    model = ItemTraitsModel()
    model.set_tables(items.load_item_types(path),
                     spells.load_spell_names(path, game),
                     spells.for_game(game))
    return model, names, templates


def _scroll_cases():
    return [(g, n) for g, (scrolls, _) in CASES.items() for n in scrolls]


@pytest.mark.parametrize("game,scroll", _scroll_cases(),
                         ids=lambda v: getattr(v, "key", v))
def test_a_scroll_shows_its_three_spells(game, scroll):
    model, names, templates = _tables(game)
    raw = templates[scroll]
    model.set_item(items.Item(raw, names))
    rows = dict(model.rows)
    expected = ", ".join(
        spells.describe(n, model.spell_names, model.spells)
        for n in raw[13:16] if n)
    assert rows["Spells"] == expected
    assert "Charges" not in rows


@pytest.mark.parametrize("game", CASES, ids=lambda g: g.key)
def test_a_location_10_item_that_is_no_scroll_keeps_its_charges(game):
    model, names, templates = _tables(game)
    name, charges = CASES[game][1]
    model.set_item(items.Item(templates[name], names))
    rows = dict(model.rows)
    assert rows["Charges"] == charges
    assert "Spells" not in rows
