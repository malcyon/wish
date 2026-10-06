"""A Pool of Radiance save with a Training Hall hireling opens in the editor.

The DOS and Amiga roster is built from the C64 record, and the C64 writer
blocks a treasure share with bit 2 set, which every Training Hall hireling
ships with. Opening a save shows and edits the party; it must not depend on
whether the party could be written to a C64.

The synthetic saves are built from the format; the disk-backed test reads the
hireling templates in the player's own `MON3CHA.DAX` and skips without them.
"""
from __future__ import annotations

import pathlib

import pytest
from support.editorwindow import make_root
from support.neutralrecords import _filled

from editor import saveplan
from editor.roster import Party
from goldbox import (
    amiga_savegame,
    c64_codec,
    c64_port,
    dos_codec,
    dos_port,
    dos_savegame,
)
from goldbox.layout import Confidence

POOL = dos_port.POOL_OF_RADIANCE
F83 = dos_port.FIELDS_BY_NAME["field_83_87"].offset
CONTROL_AT, SHARE_AT = F83 + 1, F83 + 2
SHARES = (0xFF, 0x84, 0x04, 0x05, 0x02, 0x03, 0x08)


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _poked(share: int, control: int = 0xB1) -> dos_codec.DosCharacter:
    """A filled Pool character with the companion bit and `share` poked in."""
    game = c64_port.by_key(POOL.key)
    char = _filled(game)
    char.set("name", "HIRELING", "made up", Confidence.CONFIRMED,
             c64_codec.Provenance.RESHAPED)
    record, itm, spc, _report = dos_codec.write(char, deltas=POOL)
    data = bytearray(record)
    data[CONTROL_AT], data[SHARE_AT] = control, share
    return _reread(bytes(data), itm, spc)


def _reread(record: bytes, itm: bytes, spc: bytes) -> dos_codec.DosCharacter:
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = pathlib.Path(d) / "CHRDATA9.SAV"
        path.write_bytes(record)
        path.with_suffix(POOL.item_suffix).write_bytes(itm)
        path.with_suffix(POOL.effect_suffix).write_bytes(spc)
        return dos_codec.read_character(path)


def _folder(tmp_path, share: int, players: int = 1, first=None):
    """A DOS Pool folder: `players` ordinary players, then one hireling.

    `first` is a `(control, share)` poked into HERO1 instead of leaving him an
    ordinary player."""
    game = c64_port.by_key(POOL.key)
    for n in range(1, players + 2):
        char = _filled(game)
        char.set("name", f"HERO{n}", "made up", Confidence.CONFIRMED,
                 c64_codec.Provenance.RESHAPED)
        record, itm, spc, _report = dos_codec.write(char, deltas=POOL)
        data = bytearray(record)
        if n == players + 1:
            data[CONTROL_AT], data[SHARE_AT] = 0xB1, share
        elif n == 1 and first is not None:
            data[CONTROL_AT], data[SHARE_AT] = first
        stem = tmp_path / f"CHRDATA{n}"
        stem.with_suffix(".SAV").write_bytes(bytes(data))
        stem.with_suffix(POOL.item_suffix).write_bytes(itm)
        stem.with_suffix(POOL.effect_suffix).write_bytes(spc)
    container = dos_savegame.container_for(POOL.key)
    (tmp_path / f"SAVGAMA{container.suffix}").write_bytes(bytes(container.size))
    return tmp_path


@pytest.mark.parametrize("share", SHARES)
def test_a_dos_hireling_opens_and_keeps_its_raw_share(tmp_path, share):
    party = Party(str(_folder(tmp_path, share)))
    assert [m.name for m in party.members] == ["HERO1", "HERO2"]
    hireling = party.members[1]
    assert hireling.record.get("treasure_share") == share
    assert hireling.record_original == hireling.record.to_bytes()


@pytest.mark.parametrize("share", SHARES)
def test_an_amiga_hireling_opens_and_keeps_its_raw_share(tmp_path, share):
    hireling = dos_codec.to_neutral(_poked(share))
    savgam = bytearray(amiga_savegame.POR_SAVEGAME_SIZE)
    at = amiga_savegame.POOL_OF_RADIANCE.party_at
    savgam[at:at + 8] = b"CHRDATA1"
    disk = amiga_savegame.make_por_save_disk("A", [hireling], bytes(savgam))
    path = tmp_path / "pool.adf"
    disk.save(str(path))
    party = Party(str(path))
    assert len(party.members) == 1
    assert party.members[0].record.get("treasure_share") == share


def test_the_window_opens_a_hireling_folder_without_a_dialog(
        app, tmp_path, monkeypatch):
    import editor.window as ew
    said = []
    monkeypatch.setattr(ew.QMessageBox, "critical",
                        lambda *a, **k: said.append(a[1:3]))
    binding = ew.EditorBinding(make_root())
    binding.load(str(_folder(tmp_path, 0xFF)))
    assert said == []
    assert len(binding.party.members) == 2


@pytest.mark.parametrize("share", (0xFF, 0x84, 0x02, 0x03, 0x08))
def test_a_hireling_saves_back_with_its_engine_share(tmp_path, share):
    folder = _folder(tmp_path, share)
    on_disk = (folder / "CHRDATA2.SAV").read_bytes()
    party = Party(str(folder))
    assert saveplan.dos_files(party)["CHRDATA2.SAV"] == on_disk
    party.members[1].record.set("gold", 9)
    edited = saveplan.dos_files(party)["CHRDATA2.SAV"]
    assert edited[SHARE_AT] == share
    assert edited != on_disk


@pytest.mark.parametrize("block", (0x6D, 0x6E, 0x6F, 0x70, 0x7A))
def test_the_shipped_hireling_templates_open(tmp_path, block):
    from tools.dos import dosxpaward as xp
    try:
        game = xp.find_game("POOLRAD")
        data = (game / "MON3CHA.DAX").read_bytes()
    except (FileNotFoundError, OSError):
        pytest.skip("needs the DOS POOLRAD archive; set FR_ARCHIVES")
    template = dos_savegame.dax_block(data, block, "MON3CHA.DAX")
    _folder(tmp_path, 0)
    (tmp_path / "CHRDATA2.SAV").write_bytes(template)
    party = Party(str(tmp_path))
    assert len(party.members) == 2
    assert party.members[1].record.get("treasure_share") == template[SHARE_AT]


# -- the Misc box's treasure share row (WISH-13) ------------------------------


def _window(folder, row: int):
    """A shown Character Editor on `folder` with member `row` selected."""
    from PyQt6.QtWidgets import QTabWidget

    import editor.window as ew
    root = make_root()
    w = ew.EditorBinding(root, str(folder))
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
    """`(label, value, tooltip)` of the treasure share row, None when hidden."""
    label = w._child("label_treasure_share")
    value = w._child("value_treasure_share")
    assert label.isVisible() == value.isVisible()
    if not value.isVisible():
        return None
    assert label.toolTip() == value.toolTip()
    return label.text(), value.text(), value.toolTip()


def _shown_share(percent: int):
    import editor.window as ew
    return ew.TREASURE_SHARE_LABEL, ew.TREASURE_SHARE_VALUE.format(percent=percent)


def test_a_dos_hireling_shows_his_share_and_a_player_shows_none(app, tmp_path):
    import editor.window as ew
    w = _window(_folder(tmp_path, 0xFF), row=1)
    label, value, tip = _line(w)
    assert (label, value) == _shown_share(88)
    assert tip == ew.TREASURE_SHARE_TOOLTIP.format(parts=7, denominator=8)
    w.roster.selectRow(0)
    assert _line(w) is None


def test_flipping_the_hireling_to_a_player_hides_the_share_and_back_shows_it(
        app, tmp_path):
    import editor.window as ew
    w = _window(_folder(tmp_path, 0xFF), row=1)
    control = w._child("control_combo")
    control.setCurrentText(ew.CONTROL_PLAYER)
    app.processEvents()
    assert _line(w) is None
    control.setCurrentText(ew.CONTROL_GAME)
    app.processEvents()
    assert _line(w)[:2] == _shown_share(88)


@pytest.mark.parametrize("share,percent", [(0x84, 80), (0x05, 63), (0x03, 75)])
def test_the_shown_share_is_the_low_three_bits_over_the_party_count(
        app, tmp_path, share, percent):
    """Five parts among three players is 62.5, which rounds half up to 63."""
    players = 3 if share == 0x05 else 1
    w = _window(_folder(tmp_path, share, players=players), row=players)
    assert _line(w)[:2] == _shown_share(percent)


@pytest.mark.parametrize("share", (0x08, 0x00))
def test_a_hireling_whose_share_is_zero_shows_no_line(app, tmp_path, share):
    """0x08 has no bit in the low three: the engine takes nothing."""
    w = _window(_folder(tmp_path, share), row=1)
    assert _line(w) is None


def test_a_hireling_who_is_not_ok_shows_no_line(app, tmp_path):
    w = _window(_folder(tmp_path, 0xFF), row=1)
    w.party.member(1).condition = ("dead", True)
    w._populate()
    assert _line(w) is None


def test_a_member_taken_over_by_charm_hides_the_line_for_the_whole_party(
        app, tmp_path):
    folder = _folder(tmp_path, 0xFF, first=(c64_codec.DOS_PC_TAKEN_OVER, 1))
    w = _window(folder, row=1)
    assert _line(w) is None


def test_an_amiga_hireling_alone_takes_all_of_the_split(app, tmp_path):
    hireling = dos_codec.to_neutral(_poked(0xFF))
    savgam = bytearray(amiga_savegame.POR_SAVEGAME_SIZE)
    at = amiga_savegame.POOL_OF_RADIANCE.party_at
    savgam[at:at + 8] = b"CHRDATA1"
    disk = amiga_savegame.make_por_save_disk("A", [hireling], bytes(savgam))
    path = tmp_path / "pool.adf"
    disk.save(str(path))
    w = _window(path, row=0)
    assert _line(w)[:2] == _shown_share(100)


def test_no_treasure_share_tooltip_shows_a_memory_address_or_a_byte(app, tmp_path):
    import re
    w = _window(_folder(tmp_path, 0xFF), row=1)
    tip = _line(w)[2]
    assert not re.search(r"\$|0x|[0-9A-Fa-f]{4}", tip)
