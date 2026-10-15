"""A zombie Curse member who got away converts to the C64 with his living movement.

The C64 sheet prints roster `+0x1B` as cached and only a fight rebuilds it
(`LIBRARY $3918`), so the byte Wish writes is what the player reads until then.
The specimen is the game-written Amiga Curse slot F in which BRUTUS, a zombie
player character, ran from the Tilverton brawl; it was written by the game from
a staged slot D (its provenance.toml says which bytes), and its record holds
the living 12.
"""

from __future__ import annotations

import pytest
from gamedata import specimen
from PyQt6.QtWidgets import QApplication

from automap import gamedisks
from goldbox.d64 import D64
from goldbox.savegame import load_save
from tools.convert import convertamigatoc64

CURSE = "curse-of-the-azure-bonds"
NAME = "wish303-i6-curse-brutus-got-away-slot-f"


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_brutus_arrives_on_the_c64_at_movement_twelve_not_the_zombies_six(
        app, tmp_path):
    disks = gamedisks.find(CURSE)
    if disks is None:
        pytest.skip("needs Curse's own C64 disks, found through "
                    "automap/gamedisks.py")
    disk = specimen(NAME, "amiga") / "fetched-save.adf"
    convertamigatoc64.main([
        "--tree", ".", "--specimen", str(disk), "--disks", str(disks),
        "--source-slot", "F", "--out-dir", str(tmp_path / "out"),
        "--summary", str(tmp_path / "summary.json")])
    d64 = next((tmp_path / "out").glob("wish-*/WISHSAVE.D64"))
    _game, _sg0, sg1 = load_save(D64.open(str(d64)))
    moves = [b.movement for b in sg1.roster_blocks if b.roster_in_use]
    # BRUTUS is the first member; the other four were 9 before and stay 9.
    assert moves[0] == 12
    assert moves[1:] == [9, 9, 9, 9]
