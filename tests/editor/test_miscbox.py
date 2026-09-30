"""The Misc box shows the character's condition and damage as words.

Condition and Damage are display rows: `value_condition` and `value_damage`
are labels, not bound fields, so a save never writes them and a tail the
editor cannot decode still reaches the file as it was read. Everything is
built from the format, so nothing here needs a game disk.
"""
from __future__ import annotations

import pytest
from gamedata import _disk_with, synthetic_save
from PyQt6.QtWidgets import QLabel, QTabWidget
from support.editorwindow import make_root
from support.neutralrecords import _filled

from editor.roster import Party
from editor.window import CONDITION_WORDS, EditorBinding
from goldbox import c64_codec, c64_port, dos_codec, dos_port, dos_savegame
from goldbox.d64 import D64
from goldbox.layout import Confidence
from goldbox.record import CharacterRecord
from goldbox.savegame import (
    ROSTER_IN_USE,
    ROSTER_TAIL_AT,
    load_save,
    store_save,
    tail_damage,
)

POOL = dos_port.POOL_OF_RADIANCE
TAIL = bytes.fromhex("300100010008000400")
TWO_FORMS_TAIL = bytes.fromhex("300100010108060400")


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _shown(path, slot=None):
    """A window on the Stats tab, actually shown, with the member in save slot
    `slot` selected -- the first row when there is none. A save lists its
    members in reverse slot order."""
    root = make_root()
    w = EditorBinding(root, str(path))
    tabs = root.findChild(QTabWidget, "tabs")
    for i in range(tabs.count()):
        if tabs.widget(i).objectName() == "tab_editor":
            tabs.setCurrentIndex(i)
            break
    root.resize(1875, 1030)
    root.show()
    row = 0 if slot is None else next(
        r for r in range(len(w.party)) if w.party.member(r).index == slot)
    w.roster.selectRow(row)
    return w


def _roster_disk(tmp_path, **field_values):
    record = CharacterRecord.blank()
    record.set("name", "ZERO")
    for field, value in field_values.items():
        record.set(field, value)
    out = tmp_path / "ROSTER.D64"
    out.write_bytes(_disk_with([(b"ZERO", record.to_prg())]))
    return out


def _c64_save(tmp_path, game, byte, tail=TAIL):
    """A synthetic save whose slot 0 roster block holds `byte` and `tail`."""
    path = synthetic_save(tmp_path, game=game)
    disk = D64.open(path)
    game, sg0, sg1 = load_save(disk, game)
    block = sg1.roster(0)
    block._set(ROSTER_IN_USE, byte)
    for i, value in enumerate(tail):
        block._set(ROSTER_TAIL_AT + i, value)
    store_save(disk, sg0, sg1, game)
    disk.save(path)
    return path


def _block_bytes(path, game):
    _game, _sg0, sg1 = load_save(D64.open(path), game)
    raw = sg1.roster(0).raw
    return raw[ROSTER_IN_USE], raw[ROSTER_TAIL_AT:ROSTER_TAIL_AT + len(TAIL)]


def _dos_folder(tmp_path, **neutral_fields):
    game = c64_port.by_key(POOL.key)
    char = _filled(game)
    char.set("name", "HERO1", "made up", Confidence.CONFIRMED,
             c64_codec.Provenance.RESHAPED)
    for field, value in neutral_fields.items():
        char.set(field, value, "made up")
    record, itm, spc, _report = dos_codec.write(char, deltas=POOL)
    stem = tmp_path / "CHRDATA1"
    stem.with_suffix(".SAV").write_bytes(record)
    stem.with_suffix(POOL.item_suffix).write_bytes(itm)
    stem.with_suffix(POOL.effect_suffix).write_bytes(spc)
    container = dos_savegame.container_for(POOL.key)
    (tmp_path / f"SAVGAMA{container.suffix}").write_bytes(
        bytes(container.size))
    return tmp_path


def _condition(w) -> str:
    return w._child("value_condition").text()


def test_the_box_is_called_misc_and_holds_two_labels_not_two_fields(app, tmp_path):
    w = _shown(_roster_disk(tmp_path))
    box = w._child("box_misc")
    assert box.title() == "Misc"
    assert w._child("label_condition").text() == "Condition"
    assert w._child("label_damage").text() == "Damage"
    assert isinstance(w._child("value_condition"), QLabel)
    assert isinstance(w._child("value_damage"), QLabel)
    for gone in ("field_roster_in_use", "field_roster_tail", "box_roster"):
        assert w._child(gone) is None
    assert "roster_in_use" not in w._widgets
    assert "roster_tail" not in w._widgets


@pytest.mark.parametrize("byte, shown", [
    (0x01, "OK"),
    (0x83, "Dead, out of play"),
    (0x04, "Dying"),
    (0x81, "OK, out of play"),
])
def test_a_roster_disk_character_shows_his_condition(app, tmp_path, byte, shown):
    w = _shown(_roster_disk(tmp_path, roster_in_use=byte))
    assert _condition(w) == shown


def test_a_c64_save_shows_the_condition_from_its_roster_block(app, tmp_path):
    w = _shown(_c64_save(tmp_path, c64_port.POOL_OF_RADIANCE, 0x83), slot=0)
    assert _condition(w) == "Dead, out of play"


def test_a_pool_zombie_shows_animated(app, tmp_path):
    w = _shown(_c64_save(tmp_path, c64_port.POOL_OF_RADIANCE, 0x03), slot=0)
    assert _condition(w) == "Animated"


def test_a_c64_save_with_no_roster_block_shows_no_condition(
        app, tmp_path, monkeypatch):
    import editor.roster as roster
    real = roster.load_save
    monkeypatch.setattr(roster, "load_save",
                        lambda disk, game: (lambda g, s0, s1: (g, s0, None))(
                            *real(disk, game)))
    w = _shown(synthetic_save(tmp_path))
    assert _condition(w) == ""
    assert not w._child("value_damage").isVisible()


def test_a_dos_member_shows_the_status_the_port_holds(app, tmp_path):
    w = _shown(_dos_folder(tmp_path, status="dying", active=True))
    assert _condition(w) == "Dying"


def test_a_dos_member_out_of_play_shows_it(app, tmp_path):
    w = _shown(_dos_folder(tmp_path, status="okay", active=False))
    assert _condition(w) == "OK, out of play"


def test_a_dos_animated_member_shows_animated(app, tmp_path):
    w = _shown(_dos_folder(tmp_path, status="animated", active=True))
    assert _condition(w) == "Animated"


def test_every_neutral_status_the_readers_name_has_a_word():
    assert set(c64_codec.STATUS_BITS) | {"animated", "temporarily gone"} \
        == set(CONDITION_WORDS)


def test_a_pool_member_shows_the_damage_his_tail_rolls(app, tmp_path):
    w = _shown(_c64_save(tmp_path, c64_port.POOL_OF_RADIANCE, 0x01), slot=0)
    assert w._child("label_damage").isVisible()
    assert w._child("value_damage").isVisible()
    assert w._child("value_damage").text() == "1d8+4" == tail_damage(TAIL)[0]


def test_a_second_attack_form_follows_a_slash(app, tmp_path):
    w = _shown(_c64_save(tmp_path, c64_port.POOL_OF_RADIANCE, 0x01,
                         tail=TWO_FORMS_TAIL), slot=0)
    assert w._child("value_damage").text() == "1d8+4 / 1d6"


def test_a_roster_disk_character_shows_damage(app, tmp_path):
    w = _shown(_roster_disk(tmp_path, roster_in_use=1, roster_tail=TAIL))
    assert w._child("value_damage").text() == "1d8+4"


@pytest.mark.parametrize("game", [c64_port.CURSE_OF_THE_AZURE_BONDS,
                                  c64_port.SECRET_OF_THE_SILVER_BLADES])
def test_a_later_title_hides_the_damage_row(app, tmp_path, game):
    w = _shown(_c64_save(tmp_path, game, 0x01), slot=0)
    assert not w._child("label_damage").isVisible()
    assert not w._child("value_damage").isVisible()
    assert w._child("value_condition").isVisible()
    assert _condition(w) == "OK"


def test_the_row_comes_back_on_a_member_who_can_show_it(app, tmp_path):
    """Hiding is per member, not per window: a Pool party never loses the row
    for good because one member had no tail to read."""
    w = _shown(_c64_save(tmp_path, c64_port.POOL_OF_RADIANCE, 0x01), slot=0)
    member = w.party.member(w.current_row)
    tail = member.roster_tail
    member.roster_tail = None
    w._populate()
    assert not w._child("value_damage").isVisible()
    member.roster_tail = tail
    w._populate()
    assert w._child("value_damage").isVisible()


def test_saving_a_roster_disk_leaves_the_condition_and_tail(app, tmp_path):
    path = _roster_disk(tmp_path, roster_in_use=0x83, roster_tail=TAIL)
    w = _shown(path)
    w._widgets["strength"].setValue(w._widgets["strength"].value() % 17 + 1)
    w._edited()
    assert "wrote" in w.save(interactive=False)
    member = Party(str(path)).members[0]
    assert member.roster_tail == TAIL
    assert member.condition == ("dead", False)


def test_saving_a_c64_save_leaves_the_roster_block_condition_and_tail(
        app, tmp_path):
    path = _c64_save(tmp_path, c64_port.POOL_OF_RADIANCE, 0x83)
    w = _shown(path, slot=0)
    w._widgets["strength"].setValue(w._widgets["strength"].value() % 17 + 1)
    w._edited()
    assert "wrote" in w.save(interactive=False)
    assert _block_bytes(path, c64_port.POOL_OF_RADIANCE) == (0x83, TAIL)


# A DOS Pool of Radiance save is not checked byte for byte: `dos_codec.write`
# rebuilds the armour bonus and attack forms (tail bytes 0 and 3-8) by design.
