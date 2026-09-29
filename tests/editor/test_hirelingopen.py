"""A Pool of Radiance save with a Training Hall hireling opens in the editor.

The DOS and Amiga roster is built from the C64 record, and the C64 writer
refuses a treasure share with bit 2 set, which every Training Hall hireling
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
SHARES = (0xFF, 0x84, 0x04, 0x05)


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


def _folder(tmp_path, share: int):
    """A DOS Pool folder: HERO1 an ordinary player, HERO2 a hireling."""
    game = c64_port.by_key(POOL.key)
    for n in (1, 2):
        char = _filled(game)
        char.set("name", f"HERO{n}", "made up", Confidence.CONFIRMED,
                 c64_codec.Provenance.RESHAPED)
        record, itm, spc, _report = dos_codec.write(char, deltas=POOL)
        data = bytearray(record)
        if n == 2:
            data[CONTROL_AT], data[SHARE_AT] = 0xB1, share
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


@pytest.mark.parametrize("share", (0xFF, 0x84))
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
