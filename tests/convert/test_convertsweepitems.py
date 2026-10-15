"""The sweep tools hand the writer the item-type table for Pool and Curse.

Without it `c64_codec.write` takes the strength-only THAC0 branch, so the
`convertdrops` and `convertbytes` sweeps would never exercise the readied-weapon
rule.
"""

from __future__ import annotations

import gamedata

from goldbox import c64_codec, c64_port
from tools.convert import convertbytes, convertdrops

pytestmark = gamedata.needs_curse_disks


def test_convertdrops_game_files_carry_the_curse_item_table():
    convertdrops._GAME_FILES.clear()
    files = convertdrops.game_files(
        c64_port.by_key("curse-of-the-azure-bonds"))
    assert files is not None and files.item_types
    assert {0x1C, 0x49} <= set(files.item_types)


def test_convertbytes_loads_the_item_table_for_every_weapon_rule_title():
    mod = convertbytes._load(None)
    for key in c64_codec.WEAPON_RULE_TITLES:
        game = c64_port.by_key(key)
        where = mod["gamedisks"].find(key)
        if where is None:
            continue
        assert convertbytes.item_types_for(mod, game, where), key
    silver = c64_port.by_key("secret-of-the-silver-blades")
    assert convertbytes.item_types_for(mod, silver, ".") is None
