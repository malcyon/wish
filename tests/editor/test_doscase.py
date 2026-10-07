"""DOS save files are found by name in any case, on a case-sensitive file system.

The folders are built from synthetic bytes only, so none of this reads game data.
"""

from __future__ import annotations

import pathlib
import struct

import pytest
from PyQt6.QtWidgets import QApplication

from editor import convert, dosimport
from goldbox import (
    amiga_pod,
    amiga_savegame,
    dos_codec,
    dos_port,
    dos_savegame,
)
from goldbox.amiga_adf import AmigaDisk

ITEMS = 3


def _amiga_save() -> bytes:
    out = bytearray(amiga_savegame.POD_VAR_BYTES)
    out[dos_savegame.POD_PARTY_COUNT - 1] = 1
    out += bytes((3, 4, 2, 5, 137, 0))
    out += bytes((dos_savegame.POD_MODE_DUNGEON, dos_savegame.POD_MODE_DUNGEON))
    out += struct.pack(">HHH", 6, 0, 1)
    record = bytearray(amiga_savegame.POD_RECORD_BYTES)
    struct.pack_into(">I", record, amiga_savegame.POD_ITEM_COUNT_AT, 0)
    struct.pack_into(">I", record, amiga_savegame.POD_EFFECT_HEAD_AT, 0)
    record[amiga_savegame.POD_NAME_AT:amiga_savegame.POD_NAME_AT + 4] = b"WHO\x00"
    out += record
    out += b"\xA5" * (amiga_savegame.POD_SAVEGAME_SIZE - len(out))
    return bytes(out)


def _disk_three() -> AmigaDisk:
    disk = AmigaDisk.blank("POD 3")
    disk.make_dir(f"/{amiga_savegame.SAVE_DRAWER}")
    disk.make_dir("/DISK3")
    disk.write_file(f"/{amiga_savegame.SAVE_DRAWER}/spindisk", b"\x01" * 40)
    disk.write_file(f"/{amiga_savegame.SAVE_DRAWER}/WRITE.ME", b"\x02" * 8)
    disk.write_file("/DISK3/GEN.TLB", b"\x03" * 600)
    return disk


def _vault() -> dos_codec.PodVault:
    items = []
    for n in range(ITEMS):
        raw = bytearray(dos_codec.ITEM_SIZE)
        raw[dos_port.ITEM_FIELDS_BY_NAME["type_index"].offset] = 10 + n
        items.append(bytes(raw))
    return dos_codec.PodVault(7, 8, 9, tuple(items))


def _slot(folder: pathlib.Path, rename=lambda name: name) -> None:
    """A DOS Pools of Darkness slot A with a three-item vault, every file
    named through `rename`."""
    state = amiga_savegame.pod_from_amiga(_amiga_save())
    blocks = amiga_savegame.pod_parse(_amiga_save()).blocks
    characters = [amiga_pod.pod_to_neutral(b) for b in blocks]
    dos_codec.new_pod_save_from(state, characters, folder, "A", vault=_vault())
    fields = dos_port.FIELDS_BY_NAME_FOR[dos_port.POOLS_OF_DARKNESS.key]
    record = bytearray((folder / "CHRDATA1.SAV").read_bytes())
    record[fields["char_class"].offset] = 2    # fighter, char_class 2
    record[fields["class_levels"].offset + 2] = 1
    record[fields["class_bits"].offset] = 8
    (folder / "CHRDATA1.SAV").write_bytes(bytes(record))
    for path in sorted(folder.iterdir()):
        path.rename(folder / rename(path.name))


def _convert(folder: pathlib.Path):
    source = convert.Source.detect(folder)
    assert source.port == "dos" and source.slot == "A"
    return convert.PodDosToAmiga().rehearse(
        source, "A", None, disk_three=_disk_three())


def _vault_items(rehearsal) -> int:
    disk = AmigaDisk(rehearsal.disk)
    return len(amiga_savegame.pod_read_vault(disk, "A").items)


def test_an_upper_case_slot_converts_with_its_vault(tmp_path):
    _slot(tmp_path)
    assert _vault_items(_convert(tmp_path)) == ITEMS


def test_a_lower_case_vault_beside_upper_case_saves_keeps_its_items(tmp_path):
    _slot(tmp_path, lambda n: n.lower() if n.startswith("VAULT") else n)
    assert (tmp_path / "vaulta.dat").is_file()
    assert _vault_items(_convert(tmp_path)) == ITEMS


def test_a_mixed_case_vault_keeps_its_items(tmp_path):
    _slot(tmp_path, lambda n: "Vaulta.dat" if n.startswith("VAULT") else n)
    assert _vault_items(_convert(tmp_path)) == ITEMS


def test_an_all_lower_case_slot_converts(tmp_path):
    _slot(tmp_path, str.lower)
    assert convert._dos_slots(tmp_path) == ["A"]
    assert _vault_items(_convert(tmp_path)) == ITEMS


def _case_sensitive(folder: pathlib.Path) -> bool:
    """Whether the file system under folder keeps `a` and `A` as two names."""
    probe = folder / "case_probe"
    probe.mkdir()
    (probe / "a").write_bytes(b"")
    return not (probe / "A").exists()


@pytest.fixture
def two_case_names_possible(tmp_path):
    if not _case_sensitive(tmp_path):
        pytest.skip("The file system cannot hold two names differing only in case")


def test_two_names_differing_only_in_case_stop_the_conversion(
        two_case_names_possible, tmp_path):
    _slot(tmp_path)
    (tmp_path / "vaulta.dat").write_bytes((tmp_path / "VAULTA.DAT").read_bytes())
    with pytest.raises(dos_savegame.DosNameClashError):
        _convert(tmp_path)


def test_two_character_files_differing_only_in_case_stop_the_slot(
        two_case_names_possible, tmp_path):
    _slot(tmp_path)
    (tmp_path / "chrdata1.sav").write_bytes(
        (tmp_path / "CHRDATA1.SAV").read_bytes())
    with pytest.raises(dos_savegame.DosNameClashError):
        convert._dos_slots(tmp_path)


def _with_one_item(folder: pathlib.Path) -> None:
    """Give upper-case character 1 a stored item and its item file."""
    fields = dos_port.FIELDS_BY_NAME_FOR[dos_port.POOLS_OF_DARKNESS.key]
    record = bytearray((folder / "CHRDATA1.SAV").read_bytes())
    record[fields["item_count"].offset] = 1
    (folder / "CHRDATA1.SAV").write_bytes(bytes(record))
    item = bytearray(dos_codec.ITEM_SIZE)
    item[dos_port.ITEM_FIELDS_BY_NAME["type_index"].offset] = 12
    (folder / "CHRDATA1.THG").write_bytes(bytes(item))


@pytest.mark.parametrize("rename", [str, str.lower], ids=["upper", "lower"])
def test_a_lower_case_slot_opens_in_the_editor_with_its_items(
        tmp_path, monkeypatch, rename):
    from editor.roster import Party

    monkeypatch.setenv(convert.POD_CONVERT_ENV, "1")
    _slot(tmp_path)
    _with_one_item(tmp_path)
    for path in sorted(tmp_path.iterdir()):
        path.rename(tmp_path / rename(path.name))
    party = Party(convert.Source.detect(tmp_path))
    assert len(party) == 1
    assert len(party.members[0].native.items) == 1


def test_a_lower_case_curse_slot_is_read_for_the_not_set_out_check(tmp_path):
    curse = dos_port.CURSE_OF_THE_AZURE_BONDS
    size = dos_savegame.container_for(curse.key).size
    (tmp_path / "savgama.dat").write_bytes(bytes(size))
    source = convert.Source(port="dos", title=curse, path=tmp_path, slot="A")
    # A save that has not set out needs no game disk; an unreadable one is
    # answered with True.
    assert convert.amiga_needs_game_disk(curse, source) is False


CLASH_TEXT = (
    "This folder contains both CHRDATD1.SAV and chrdatd1.sav. DOS treats "
    "these names as the same save file.\n\nMove the copy you do not want to "
    "another folder, then try again. No files have been changed.")


def _clash_folder(folder: pathlib.Path, *names: str) -> None:
    """Just real enough for Source.detect to find a slot D record."""
    folder.mkdir(exist_ok=True)
    (folder / "SAVGAMD.DAT").write_bytes(b"\x00")
    for name in names:
        (folder / name).write_bytes(
            b"\x00" * dos_port.POOL_OF_RADIANCE.record_size)


def _convert_modals(monkeypatch):
    critical = []
    monkeypatch.setattr(convert.QMessageBox, "critical",
                        lambda self_, t, x: critical.append((t, x)))
    return critical


def test_the_convert_dialog_names_both_files_of_a_case_clash(
        two_case_names_possible, tmp_path, monkeypatch):
    _ = QApplication.instance() or QApplication([])
    _clash_folder(tmp_path / "slot", "CHRDATD1.SAV", "chrdatd1.sav")
    before = sorted((p.name, p.read_bytes()) for p in (tmp_path / "slot").iterdir())
    critical = _convert_modals(monkeypatch)
    dialog = convert.ConvertDialog(
        str(tmp_path / "slot" / "SAVGAMD.DAT"), None, lambda game: None)
    try:
        dialog.replan()
        assert dialog._blocked == (convert.DIALOG_TITLE, CLASH_TEXT)
    finally:
        dialog.close()
    assert critical == [(convert.DIALOG_TITLE, CLASH_TEXT)]
    assert sorted((p.name, p.read_bytes()) for p in (tmp_path / "slot").iterdir()) == before


def test_a_clash_among_three_names_shows_the_generic_sentence(
        two_case_names_possible, tmp_path, monkeypatch):
    _ = QApplication.instance() or QApplication([])
    _clash_folder(tmp_path / "slot", "CHRDATD1.SAV", "chrdatd1.sav", "Chrdatd1.sav")
    critical = _convert_modals(monkeypatch)
    dialog = convert.ConvertDialog(
        str(tmp_path / "slot" / "SAVGAMD.DAT"), None, lambda game: None)
    try:
        dialog.replan()
    finally:
        dialog.close()
    assert critical == [(convert.DIALOG_TITLE, convert.CANNOT_CONVERT)]


def test_a_single_lower_case_character_file_converts_in_the_dialog(
        tmp_path, monkeypatch):
    _ = QApplication.instance() or QApplication([])
    _clash_folder(tmp_path / "slot", "chrdatd1.sav")
    critical = _convert_modals(monkeypatch)
    dialog = convert.ConvertDialog(
        str(tmp_path / "slot" / "SAVGAMD.DAT"), None, lambda game: None)
    try:
        dialog.replan()
        assert dialog.source is not None and dialog.source.slot == "D"
    finally:
        dialog.close()
    assert critical == []


def test_a_clash_found_only_in_the_rehearsal_names_both_item_files(
        two_case_names_possible, tmp_path, monkeypatch):
    """The slot detects and its character file is unique; the item file beside
    it is read only when the conversion is rehearsed."""
    _ = QApplication.instance() or QApplication([])
    slot = tmp_path / "slot"
    _clash_folder(slot, "CHRDATD1.SAV")
    for name in ("CHRDATD1.ITM", "chrdatd1.itm"):
        (slot / name).write_bytes(b"\x00" * dos_codec.ITEM_SIZE)
    out = tmp_path / "out"
    out.mkdir()
    before = sorted((p.name, p.read_bytes()) for p in slot.iterdir())
    critical = _convert_modals(monkeypatch)
    game_files = dosimport.GameFiles(icon=b"", animate=b"")
    dialog = convert.ConvertDialog(
        str(slot / "SAVGAMD.DAT"), None, lambda game: game_files,
        destination="c64", folder=str(out))
    text = (
        "This folder contains both CHRDATD1.ITM and chrdatd1.itm. DOS treats "
        "these names as the same save file.\n\nMove the copy you do not want "
        "to another folder, then try again. No files have been changed.")
    try:
        dialog.replan()
        assert dialog.source is not None and dialog.source.slot == "D"
        assert dialog.rehearsal is None
        assert dialog._blocked == (convert.DIALOG_TITLE, text)
    finally:
        dialog.close()
    assert critical == [(convert.DIALOG_TITLE, text)]
    assert sorted((p.name, p.read_bytes()) for p in slot.iterdir()) == before
    assert list(out.iterdir()) == []
