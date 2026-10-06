"""The Misc box's treasure share row, per title and port.

The synthetic cases open a synthetic C64 save and put the port, the companion
and every member's condition in memory, so they run everywhere. The specimen
cases open saves the engines wrote and skip where the specimen tree is absent.
"""
from __future__ import annotations

import gamedata
import pytest
from gamedata import synthetic_save
from PyQt6.QtWidgets import QTabWidget
from support.editorwindow import make_root

import editor.window as ew
from editor.window import EditorBinding
from goldbox import c64_port

POOL = c64_port.POOL_OF_RADIANCE
CURSE = c64_port.CURSE_OF_THE_AZURE_BONDS
SILVER = c64_port.SECRET_OF_THE_SILVER_BLADES


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _shown(path, row=0):
    root = make_root()
    w = EditorBinding(root, str(path))
    tabs = root.findChild(QTabWidget, "tabs")
    for i in range(tabs.count()):
        if tabs.widget(i).objectName() == "tab_editor":
            tabs.setCurrentIndex(i)
            break
    root.resize(1875, 1030)
    root.show()
    w.roster.selectRow(row)
    return w


def _line(w):
    """`(label, value, tooltip)` of the row, None when it is hidden."""
    label = w._child("label_treasure_share")
    value = w._child("value_treasure_share")
    assert label.isVisible() == value.isVisible()
    if not value.isVisible():
        return None
    assert label.toolTip() == value.toolTip()
    return label.text(), value.text(), value.toolTip()


def _party(tmp_path, game, port, share=0xFF):
    """A six-member synthetic party on `port`, member 0 a companion."""
    w = _shown(synthetic_save(tmp_path, game=game))
    w.party.port = port
    for m in w.party.members:
        m.condition = ("okay", True)
    member = w.party.member(0)
    member.record.set("flags_0b8", 0x9E)
    member.record.set("treasure_share", share)
    w._populate()
    return w


@pytest.mark.parametrize("game", [POOL, CURSE, SILVER],
                         ids=["pool", "curse", "silver"])
def test_a_dos_companion_shows_seven_parts_of_twelve(app, tmp_path, game):
    w = _party(tmp_path, game, "dos")
    label, value, tip = _line(w)
    assert (label, value) == (ew.TREASURE_SHARE_LABEL,
                              ew.TREASURE_SHARE_VALUE.format(percent=58))
    assert tip == ew.TREASURE_SHARE_TOOLTIP.format(parts=7, denominator=12)


def test_an_amiga_pool_companion_shows_the_dos_figure(app, tmp_path):
    w = _party(tmp_path, POOL, "amiga")
    assert _line(w)[1] == ew.TREASURE_SHARE_VALUE.format(percent=58)


@pytest.mark.parametrize("game", [POOL, CURSE], ids=["pool", "curse"])
def test_a_c64_companion_shows_the_combined_chance_per_monster(
        app, tmp_path, game):
    """Three parts against six occupied slots: 3 of 10."""
    w = _party(tmp_path, game, "c64")
    label, value, tip = _line(w)
    assert (label, value) == (ew.TREASURE_CHANCE_LABEL,
                              ew.TREASURE_CHANCE_VALUE.format(percent=30))
    assert tip == ew.TREASURE_CHANCE_TOOLTIP.format(percent=30)


@pytest.mark.parametrize("game,port", [(SILVER, "c64"), (CURSE, "amiga"),
                                       (SILVER, "amiga")])
def test_a_title_and_port_whose_split_was_not_read_shows_no_line(
        app, tmp_path, game, port):
    assert _line(_party(tmp_path, game, port)) is None


@pytest.mark.parametrize("port", ["dos", "amiga", "c64"])
def test_a_companion_holding_a_share_of_zero_shows_no_line(app, tmp_path, port):
    assert _line(_party(tmp_path, POOL, port, share=0)) is None


@pytest.mark.parametrize("port", ["dos", "c64"])
def test_a_player_character_shows_no_line(app, tmp_path, port):
    w = _party(tmp_path, POOL, port)
    w.roster.selectRow(1)
    assert _line(w) is None


def test_a_member_whose_condition_was_not_read_hides_the_line(app, tmp_path):
    w = _party(tmp_path, POOL, "dos")
    w.party.member(3).condition = None
    w._populate()
    assert _line(w) is None


def test_a_curse_player_who_pressed_keep_and_is_made_game_controlled_takes_one_part(
        app, tmp_path):
    """The share byte holds 1 as the KEEP flag and the game would count it:
    one part among four players and the two companions' one part, 1 of 5."""
    w = _party(tmp_path, CURSE, "dos", share=0)
    w.party.member(1).record.set("treasure_share", 1)
    w.roster.selectRow(1)
    assert _line(w) is None
    w._child("control_combo").setCurrentText(ew.CONTROL_GAME)
    app.processEvents()
    assert _line(w)[1] == ew.TREASURE_SHARE_VALUE.format(percent=20)


def test_a_roster_disk_companion_shows_no_line(app, tmp_path):
    from gamedata import _disk_with

    from goldbox.record import CharacterRecord
    record = CharacterRecord.blank()
    record.set("name", "ZERO")
    record.set("treasure_share", 0xFF)
    record.set("flags_0b8", 0x9E)
    record.set("roster_in_use", 1)
    path = tmp_path / "ROSTER.D64"
    path.write_bytes(_disk_with([(b"ZERO", record.to_prg())]))
    w = _shown(path)
    assert w.party.member(0).is_npc and not w.party.is_save
    assert _line(w) is None


# The two companions below are the Training Hall evoker, in saves the engines
# wrote; their figures were measured in play.


def test_the_dos_pool_evoker_specimen_shows_54_percent(app):
    path = gamedata.specimen("por-hireling-evoker-ff")
    w = _shown(path, row=6)
    assert w.party.member(6).name == "EVOKER"
    assert _line(w)[:2] == (ew.TREASURE_SHARE_LABEL,
                            ew.TREASURE_SHARE_VALUE.format(percent=54))
    w.roster.selectRow(0)
    assert _line(w) is None


def test_the_c64_pool_evoker_specimen_shows_27_percent_per_monster(app):
    path = gamedata.specimen_root()
    found = None if path is None else sorted(path.glob(
        "por-c64/WISH-SPEC-por-743-c64-hireling-fight-resave.[dD]64"))
    if not found:
        pytest.skip("needs the C64 specimen WISH-SPEC-por-743-c64-hireling-fight-resave")
    w = _shown(found[0], row=6)
    assert w.party.member(6).name == "EVOKER"
    assert _line(w)[:2] == (ew.TREASURE_CHANCE_LABEL,
                            ew.TREASURE_CHANCE_VALUE.format(percent=27))


def test_dirten_in_the_dos_pool_specimen_shows_no_line(app):
    w = _shown(gamedata.specimen("dos-pool-745-mid-scribe"), row=6)
    assert w.party.member(6).name == "DIRTEN"
    assert _line(w) is None
