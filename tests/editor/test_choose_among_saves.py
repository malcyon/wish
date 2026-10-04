"""Open and Save As on a source that holds several saved games.

A DOS folder with saved games A and B, and an Amiga Curse disk with slots A
and B, are built from the format (`test_saveplan.py`'s builders), so this
needs no game data. The slot picker is replaced by a stand-in that answers
with a chosen letter or cancels: what is checked is that the letter reaches
the party the editor holds, that Save As publishes that party and not the
first one, and that cancelling changes nothing.
"""
from __future__ import annotations

import pytest
from support.editorwindow import make_root
from test_saveplan import amiga_two_slot_disk, dos_folder

import editor.window as ew
from editor.window import EditorBinding
from goldbox import amiga_savegame, dos_codec
from goldbox.amiga_adf import AmigaDisk

GOLD = 4321


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def picker_answering(monkeypatch, letter):
    """Replace the slot picker; `letter=None` cancels it. Returns the list of
    slot lists it was shown."""
    shown = []

    class Picker:
        def __init__(self, slots, _parent):
            shown.append(list(slots))

        def exec(self):
            from PyQt6.QtWidgets import QDialog
            return (QDialog.DialogCode.Rejected if letter is None
                    else QDialog.DialogCode.Accepted)

        @property
        def slot(self):
            return letter

    monkeypatch.setattr(ew, "SlotPicker", Picker)
    return shown


def two_slot_dos_folder(tmp_path):
    """Saved game A holds two characters, saved game B holds one."""
    folder = dos_folder(tmp_path, slot="A", numbers=(1, 2))
    dos_folder(tmp_path, slot="B", numbers=(1,))
    return folder


def names(binding):
    return [member.name for member in binding.party.members]


def published(binding, monkeypatch, target):
    """Type `target` into the open destination section and click Save As.
    Returns the error boxes shown (an exception raised inside a Qt slot would
    abort the interpreter, so they are recorded rather than raised)."""
    binding._child("destination_path").setText(str(target))
    said = []
    monkeypatch.setattr(ew.QMessageBox, "critical",
                        lambda _parent, title, text: said.append((title, text)))
    binding._child("button_destination_save_as").click()
    return said


# ---------------------------------------------------------------------------
# DOS folder
# ---------------------------------------------------------------------------

def test_open_of_a_dos_folder_with_two_saves_supplies_the_chosen_slot(
        app, tmp_path, monkeypatch):
    folder = two_slot_dos_folder(tmp_path / "save")
    shown = picker_answering(monkeypatch, "B")
    binding = EditorBinding(make_root())

    binding.load(str(folder))

    assert shown == [["A", "B"]]
    assert binding.party.source.slot == "B"
    assert names(binding) == ["HERO1"]


def test_save_as_of_the_chosen_dos_slot_publishes_that_slots_party(
        app, tmp_path, monkeypatch):
    folder = two_slot_dos_folder(tmp_path / "save")
    picker_answering(monkeypatch, "B")
    binding = EditorBinding(make_root())
    binding.load(str(folder))
    binding._widgets["gold"].setValue(GOLD)
    binding._edited()
    out = tmp_path / "copy"

    binding.begin_save_as("dos")
    assert binding._child("label_destination_slot").text() == "B"
    assert published(binding, monkeypatch, out) == []

    written = dos_codec.read_party(out, "B")
    assert [c.name for c in written] == ["HERO1"]
    assert written[0].get("gold") == GOLD
    assert (out / "CHRDATB1.SAV").exists()
    # A native DOS copy is the whole folder, so the other saved game rides
    # along untouched; only the chosen slot's files carry the edit.
    assert (out / "CHRDATA1.SAV").read_bytes() == (
        folder / "CHRDATA1.SAV").read_bytes()
    assert dos_codec.read_party(out, "A")[0].get("gold") != GOLD


def test_cancelling_the_dos_picker_leaves_the_party_and_its_edits(
        app, tmp_path, monkeypatch):
    folder = two_slot_dos_folder(tmp_path / "save")
    other = dos_folder(tmp_path / "other", slot="A", numbers=(1,))
    dos_folder(tmp_path / "other", slot="B", numbers=(1,))
    picker_answering(monkeypatch, "A")
    binding = EditorBinding(make_root())
    binding.load(str(folder))
    binding._widgets["gold"].setValue(GOLD)
    binding._edited()
    party, dirty = binding.party, set(binding.dirty)
    assert dirty

    # "Don't Save" at the unsaved-changes question, then Cancel at the picker.
    monkeypatch.setattr(
        ew.QMessageBox, "exec",
        lambda self: ew.QMessageBox.StandardButton.Discard)
    picker_answering(monkeypatch, None)
    binding.load(str(other))

    assert binding.party is party
    assert binding.dirty == dirty
    assert binding.path == folder
    assert binding._widgets["gold"].value() == GOLD
    assert binding._flush() == []
    assert party.members[0].record.get("gold") == GOLD
    assert names(binding) == ["HERO1", "HERO2"]


# ---------------------------------------------------------------------------
# Amiga disk image
# ---------------------------------------------------------------------------

def test_open_of_an_amiga_disk_with_two_saves_supplies_the_chosen_slot(
        app, tmp_path, monkeypatch):
    path = amiga_two_slot_disk(tmp_path)
    shown = picker_answering(monkeypatch, "B")
    binding = EditorBinding(make_root())

    binding.load(str(path))

    assert shown == [["A", "B"]]
    assert binding.party.source.slot == "B"
    assert names(binding) == ["OMEGA"]


def test_save_as_of_the_chosen_amiga_slot_publishes_that_slots_party(
        app, tmp_path, monkeypatch):
    path = amiga_two_slot_disk(tmp_path)
    picker_answering(monkeypatch, "B")
    binding = EditorBinding(make_root())
    binding.load(str(path))
    binding._widgets["gold"].setValue(GOLD)
    binding._edited()
    out = tmp_path / "copy.adf"

    binding.begin_save_as("amiga")
    assert binding._child("label_destination_slot").text() == "B"
    assert published(binding, monkeypatch, out) == []

    disk = AmigaDisk.open(str(out))
    save = amiga_savegame.read_slot(disk, "B", amiga_savegame.CURSE.key)
    assert [c.name for c in save.characters] == ["OMEGA"]
    assert save.characters[0].money["gold"] == GOLD


def test_cancelling_the_amiga_picker_leaves_the_party_and_its_edits(
        app, tmp_path, monkeypatch):
    path = amiga_two_slot_disk(tmp_path)
    other = amiga_two_slot_disk(tmp_path, name="other.adf")
    picker_answering(monkeypatch, "A")
    binding = EditorBinding(make_root())
    binding.load(str(path))
    binding._widgets["gold"].setValue(GOLD)
    binding._edited()
    party, dirty = binding.party, set(binding.dirty)
    assert dirty

    monkeypatch.setattr(
        ew.QMessageBox, "exec",
        lambda self: ew.QMessageBox.StandardButton.Discard)
    picker_answering(monkeypatch, None)
    binding.load(str(other))

    assert binding.party is party
    assert binding.dirty == dirty
    assert str(binding.path) == str(path)
    assert binding._widgets["gold"].value() == GOLD
    assert binding._flush() == []
    assert party.members[0].record.get("gold") == GOLD
    assert names(binding) == ["ALPHA"]

