"""A Pools of Darkness save shown in the Character Editor window, behind
`WISH_EXPERIMENTAL_POD_CONVERT`.

`test_podparty.py` covers the party and its sheet record. This file covers
what the window does with them: Open reaches the sheet without an error, each
box shows what the record holds at the width this title's bytes have, the
fields the title has no byte for are greyed through the unwritable mechanism
with an empty tooltip, items and spells are named from the title's own DOS or
Amiga files, and opening and flushing a character moves no byte.

**The synthetic tests need no game data.** They write a one-character DOS
save folder from a blank record and stand in for the name readers, so CI runs
them. **The specimen tests read the player's own saves and game files** at run
time -- the saves `test_podparty.py` lists, the DOS game folder under the
registry's `dos-archives` entry and the Amiga disk 1 under its `amiga` entry --
and skip without them.
"""
from __future__ import annotations

import pathlib

import pytest
from support.editorwindow import make_root
from test_podparty import FLAG, OFF, POD, _amiga_sources, _dos_sources, _flag

from editor import convert, enums, podsheet
from goldbox import c64_port, dos_codec, item_names, spell_names, titles
from goldbox.encoding import combat_value
from goldbox.items import Item

#: What the fake name readers return, and so what the window must show.
ITEM_WORD = 7
FAKE_ITEMS = {ITEM_WORD: "Test Mace"}
FAKE_SPELLS = {9: "Test Burning Hands", 10: "Test Charm Person"}


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _window(game_folder=None):
    import editor.window as ew
    folders = {POD.key: str(game_folder)} if game_folder else {}
    return ew.EditorBinding(make_root(), game_folders=folders)


def _no_box(monkeypatch):
    """Fail on any "Cannot open" or other error box, and say which."""
    import editor.window as ew

    def box(*args, **kwargs):
        raise AssertionError(f"an error box opened: {args[1:]}")
    monkeypatch.setattr(ew.QMessageBox, "critical", box)


# ---------------------------------------------------------------------------
# A one-character save, written from a blank record
# ---------------------------------------------------------------------------

#: The classes of the synthetic character: a human who left the ranger for
#: magic-user, so his class mask is 0x81.
FORMER_RANGER = 0x81


def _synthetic_folder(root: pathlib.Path) -> pathlib.Path:
    """`root/SAVE`: slot A with one character holding one item, a spellbook
    with the odd byte of 8 the engine never writes, memorised spells and the
    slots to hold them."""
    folder = root / "SAVE"
    folder.mkdir()
    record = podsheet.PodSheetRecord(bytes(podsheet.SIZE))
    record.set("name", "GRIMNIR")
    record.set("race", 5)
    record.set("class_bits", FORMER_RANGER)
    former = bytearray(record.get_raw("former_class_levels"))
    former[4] = 9                       # the ranger slot
    record.set_raw("former_class_levels", bytes(former))
    record.set("level_magic_user", 9)
    record.set("hp_max", 40)
    record.set("hp_current", 40)
    record.set("strength", 17)
    record.set("experience", 123456)
    record.set("thief_pick_pockets", 200)
    record.set("platinum", 12)
    record.set("age", 30)
    record.set_known_ids([9, 10, 118])
    record.set_raw("spells_known", bytes(
        8 if i == 117 else b for i, b in enumerate(
            record.get_raw("spells_known"))))
    record.set_memorised([9, 9, 10])
    slots = bytearray(record.get_raw("spells_castable"))
    slots[18] = 3                       # magic-user, spell level 1
    record.set_raw("spells_castable", bytes(slots))
    record.set("item_count", 1)
    mace = bytearray(16)
    mace[0], mace[3] = 1, ITEM_WORD
    (folder / "CHRDATA1.SAV").write_bytes(record.to_bytes())
    (folder / "CHRDATA1.THG").write_bytes(dos_codec.item_from_c64(bytes(mace)))
    (folder / "SAVGAMA.PTY").write_bytes(b"")
    return folder


def _synthetic_game_folder(root: pathlib.Path) -> pathlib.Path:
    """A folder `titles.dos_folder_title` takes for this title's DOS game."""
    launcher, config, stem = titles.DOS_FOLDER_FILES[POD.key]
    folder = root / stem
    folder.mkdir()
    for name in (launcher, config):
        (folder / name).write_bytes(b"")
    return folder


@pytest.fixture
def fake_names(monkeypatch):
    """Stand in for the two name readers; the list collects `(table, port)`
    for every call, in order."""
    calls = []

    def items(game, platform, where):
        calls.append(("items", platform))
        return dict(FAKE_ITEMS)

    def spells(game, platform, where):
        calls.append(("spells", platform))
        return dict(FAKE_SPELLS)

    monkeypatch.setattr(item_names, "item_names", items)
    monkeypatch.setattr(spell_names, "spell_names", spells)
    return calls


def _open_synthetic(monkeypatch, tmp_path, *, names: bool):
    _flag(monkeypatch, "1")
    _no_box(monkeypatch)
    folder = _synthetic_folder(tmp_path)
    window = _window(_synthetic_game_folder(tmp_path) if names else None)
    window.load(str(folder))
    return window, folder


def test_open_shows_a_synthetic_party_through_the_sheet(
        app, monkeypatch, tmp_path, fake_names):
    window, _folder = _open_synthetic(monkeypatch, tmp_path, names=True)
    assert window.party is not None and window.party.game is POD
    assert len(window.party) == 1
    widgets = window._widgets
    assert widgets["name"].text().strip() == "GRIMNIR"
    assert widgets["strength"].value() == 17
    assert widgets["level_magic_user"].value() == 9
    assert widgets["hp_max"].value() == 40
    assert widgets["experience"].value() == 123456
    assert widgets["age"].value() == 30
    assert widgets["platinum"].value() == 12
    # A thief skill is an unsigned byte here; the C64's box stops at 127.
    assert widgets["thief_pick_pockets"].value() == 200
    assert widgets["thief_pick_pockets"].maximum() == 255
    assert widgets["hp_max"].maximum() == 255
    assert widgets["experience"].maximum() > 0xFFFFFF


def test_the_neutral_class_is_named_from_the_titles_class_names(
        app, monkeypatch, tmp_path, fake_names):
    window, _folder = _open_synthetic(monkeypatch, tmp_path, names=True)
    names = enums.class_bit_names(POD)
    assert names[FORMER_RANGER] == "magic-user/ranger"
    assert window._widgets["class_bits"].currentText() == "Magic-user/ranger"
    assert window.party.member(0).class_name == (
        "magic-user/ranger (was ranger 9)")


def test_the_fields_the_title_has_no_byte_for_are_greyed_without_a_tooltip(
        app, monkeypatch, tmp_path, fake_names):
    window, _folder = _open_synthetic(monkeypatch, tmp_path, names=True)
    assert podsheet.UNWRITABLE
    for name in podsheet.UNWRITABLE:
        widget = window._widgets[name]
        assert not widget.isEnabled(), name
        assert widget.toolTip() == "", name
    for name in ("strength", "level_magic_user", "hp_max", "experience",
                 "platinum", "age"):
        assert window._widgets[name].isEnabled(), name
    # The trait slots have no bytes: nothing is listed, nothing can be added.
    traits = window._widgets["item_effects"]
    assert traits.to_bytes() == b""
    assert not window._child("button_trait_add").isEnabled()


def test_the_icon_box_stays_empty(app, monkeypatch, tmp_path, fake_names):
    window, _folder = _open_synthetic(monkeypatch, tmp_path, names=True)
    icon = window._widgets["icon"]
    assert icon.icon is None
    assert not icon.isEnabled()
    assert window.charset == b""
    assert window.icon_parts is None


def test_items_are_named_from_the_title_s_own_files(
        app, monkeypatch, tmp_path, fake_names):
    window, _folder = _open_synthetic(monkeypatch, tmp_path, names=True)
    assert window.item_names == FAKE_ITEMS
    inventory = window.items
    shown = [inventory.data(inventory.index(row, 1))
             for row in range(inventory.rowCount())]
    assert FAKE_ITEMS[ITEM_WORD] in shown
    assert not [text for text in shown if text.startswith(("word ", "?"))]
    assert window._child("label_inventory").text() == "1 of 16 slots used"
    # Names found: the status line carries no "no game disk" suffix.
    assert "no game disk" not in window.root.statusBar().currentMessage()


def test_spells_are_named_and_the_capacity_is_the_records_own(
        app, monkeypatch, tmp_path, fake_names):
    window, _folder = _open_synthetic(monkeypatch, tmp_path, names=True)
    assert window.spell_names == FAKE_SPELLS
    book, memorised = window._spell_widgets()
    assert book.known() == [9, 10, 118]
    assert memorised.ids() == [9, 9, 10]
    assert "Test Burning Hands" in memorised.list.item(0).text()
    capacity = window._child("field_spells_memorised_capacity").text()
    assert "magic-user: L1 3/3" in capacity
    assert "cleric" not in capacity


def test_the_game_files_are_tried_in_the_open_saves_port_first(
        app, monkeypatch, tmp_path, fake_names):
    _open_synthetic(monkeypatch, tmp_path, names=True)
    assert fake_names == [("items", "dos"), ("spells", "dos")]


def test_a_folder_with_no_names_keeps_the_existing_lines(
        app, monkeypatch, tmp_path):
    window, _folder = _open_synthetic(monkeypatch, tmp_path, names=False)
    assert window.item_names == {} and window.spell_names == {}
    assert window.root.statusBar().currentMessage().endswith(
        "  -- no game disk, so no item names and no icons")
    label = window._child("label_inventory").text()
    assert label.startswith("1 of 16 slots used. No game disk found")
    # Items show as the name words they hold, as for any title with no names.
    inventory = window.items
    assert inventory.data(inventory.index(0, 1)).startswith("word ")


def test_opening_and_flushing_a_character_moves_no_byte(
        app, monkeypatch, tmp_path, fake_names):
    window, _folder = _open_synthetic(monkeypatch, tmp_path, names=True)
    record = window.party.member(0).record
    original = record.to_bytes()
    assert window._flush(0) == []
    assert record.to_bytes() == original
    assert record.get_raw("spells_known")[117] == 8


def test_the_spellbook_keeps_a_byte_it_does_not_edit_and_writes_one_or_zero(
        app, monkeypatch, tmp_path, fake_names):
    window, _folder = _open_synthetic(monkeypatch, tmp_path, names=True)
    record = window.party.member(0).record
    book, _memorised = window._spell_widgets()
    book.set_ids([10, 11, 118])
    assert window._flush(0) == []
    raw = record.get_raw("spells_known")
    assert raw[8] == 0              # id 9 unticked
    assert raw[9] == 1              # id 10 kept
    assert raw[10] == 1             # id 11 newly ticked
    assert raw[117] == 8            # id 118 kept as it was


def test_the_control_combo_writes_the_first_byte_of_the_control_run(
        app, monkeypatch, tmp_path, fake_names):
    import editor.window as ew
    window, _folder = _open_synthetic(monkeypatch, tmp_path, names=True)
    record = window.party.member(0).record
    assert not record.is_npc
    before = record.get_raw("field_83_87")
    window._child("control_combo").setCurrentText(ew.CONTROL_GAME)
    window._child("morale_spin").setValue(40)
    assert window._flush(0) == []
    assert record.is_npc
    after = record.get_raw("field_83_87")
    assert after[0] == 0x80 | 20 and after[1:] == before[1:]
    window._child("control_combo").setCurrentText(ew.CONTROL_PLAYER)
    assert window._flush(0) == []
    assert not record.is_npc and record.get_raw("field_83_87")[0] == 0


def test_the_backstab_row_reads_this_title_s_rule(
        app, monkeypatch, tmp_path, fake_names):
    window, _folder = _open_synthetic(monkeypatch, tmp_path, names=True)
    record = window.party.member(0).record
    value = window._child("value_thief_backstab")
    assert value.text() == "None"
    record.set("level_thief", 40)
    window._populate()
    assert value.text() == "×5"      # Pools of Darkness clamps at 5


# ---------------------------------------------------------------------------
# The flag off: Open is as it was
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", OFF)
def test_without_the_flag_open_still_shows_the_cannot_open_box(
        app, monkeypatch, tmp_path, value):
    import editor.window as ew
    _flag(monkeypatch, value)
    said = []
    monkeypatch.setattr(ew.QMessageBox, "critical",
                        lambda *a, **k: said.append((a[1], a[2])))
    window = _window()
    window.load(str(_synthetic_folder(tmp_path)))
    assert said == [("Cannot open", convert.POOLS_OF_DARKNESS_UNSUPPORTED)]
    assert window.party is None


def test_no_other_title_names_the_former_ranger_mask():
    """The mask is named for this title alone."""
    for game in c64_port.GAMES:
        assert FORMER_RANGER not in enums.class_bit_names(game), game.key


def test_the_flag_is_the_one_the_open_tests_set():
    assert FLAG == convert.POD_CONVERT_ENV


# ---------------------------------------------------------------------------
# The saves and game files we have
# ---------------------------------------------------------------------------

def _dos_game_folder():
    from automap import gamedisks

    root = gamedisks.find("dos-archives")
    folders = spell_names.find_dos_folders(root, POD.key) if root else []
    if not folders:
        pytest.skip("needs the DOS Pools of Darkness game folder under the "
                    "registry's dos-archives entry")
    return folders[0]


def _amiga_disk_one(tmp_path) -> pathlib.Path:
    """A folder holding the first Amiga disk of this title, read from the
    registry's `amiga` entry."""
    from goldbox.amiga_adf import AmigaDisk
    from tools.amiga import amigasaves

    for _label, data in amigasaves.images():
        try:
            spell_names.amiga_program([AmigaDisk(bytearray(data))], POD.key)
        except Exception:
            continue
        folder = tmp_path / "disk1"
        folder.mkdir()
        (folder / "disk1.adf").write_bytes(data)
        return folder
    pytest.skip("needs the Amiga Pools of Darkness disk 1 under the "
                "registry's amiga entry")


def _check_window(label, window) -> int:
    """Every character of the open party: the boxes read the record at its
    own width, every item is named, and a flush moves no byte. Returns how
    many characters were checked."""
    from PyQt6.QtWidgets import QSpinBox

    roster = window._child("roster")
    for row in range(len(window.party)):
        roster.selectRow(row)
        member = window.party.member(row)
        record = member.record
        where = f"{label} {member.name!r}"
        assert window._widgets["name"].text().strip() == member.name.strip()
        for name, widget in window._widgets.items():
            if (isinstance(widget, QSpinBox) and widget.isEnabled()
                    and name not in {"combat_figure"}):
                want = record.get(name)
                if name == "armour_class":
                    want = combat_value(want)
                assert widget.value() == want, f"{where} {name}"
        inventory = window.items
        for slot in range(inventory.rowCount()):
            text = inventory.data(inventory.index(slot, 1))
            assert not text.startswith(("word ", "?")), f"{where} {text}"
        original = record.to_bytes()
        assert window._flush(row) == [], where
        assert record.to_bytes() == original, where
    return len(window.party)


def test_every_dos_slot_opens_with_named_items_and_flushes_clean(
        app, monkeypatch):
    import editor.window as ew
    _flag(monkeypatch, "1")
    _no_box(monkeypatch)
    folder = _dos_game_folder()
    expected = item_names.load_dos_item_names(folder)
    checked = 0
    for source in _dos_sources():
        window = _window(folder)
        window._adopt(ew.Party(source), str(source.path))
        assert window.item_names == expected
        assert window.spell_names == spell_names.load_dos_spell_names(
            folder, POD)
        assert not window._widgets["icon"].isEnabled()
        checked += _check_window(str(source.path), window)
    assert checked


def test_every_amiga_slot_opens_with_named_items_and_flushes_clean(
        app, monkeypatch, tmp_path):
    import editor.window as ew
    _flag(monkeypatch, "1")
    _no_box(monkeypatch)
    disk_one = _amiga_disk_one(tmp_path)
    expected = item_names.load_amiga_item_names(disk_one, POD)
    checked = 0
    for label, source in _amiga_sources(tmp_path):
        window = _window(disk_one)
        window._adopt(ew.Party(source), str(source.path))
        assert window.item_names == expected
        assert window.spell_names == spell_names.load_amiga_spell_names(
            disk_one, POD)
        checked += _check_window(label, window)
    assert checked


def test_the_open_saves_port_comes_first_when_both_kinds_of_files_are_set(
        app, monkeypatch, tmp_path):
    """An Amiga disk 3 is named from the Amiga disks and a DOS folder from
    the DOS game, whichever of them Preferences names first."""
    import editor.window as ew
    _flag(monkeypatch, "1")
    dos = _dos_game_folder()
    amiga = _amiga_disk_one(tmp_path)
    dos_expected = item_names.load_dos_item_names(dos)
    amiga_expected = item_names.load_amiga_item_names(amiga, POD)
    assert dos_expected != amiga_expected
    cases = [(_dos_sources()[0], dos_expected),
             (_amiga_sources(tmp_path)[0][1], amiga_expected)]
    for source, expected in cases:
        window = _window(amiga)
        window.set_disks(str(dos))
        window._adopt(ew.Party(source), str(source.path))
        assert window.item_names == expected, source.path


def test_a_member_s_first_item_is_the_name_the_reader_gives(
        app, monkeypatch):
    import editor.window as ew
    _flag(monkeypatch, "1")
    folder = _dos_game_folder()
    names = item_names.load_dos_item_names(folder)
    source = _dos_sources()[0]
    window = _window(folder)
    window._adopt(ew.Party(source), str(source.path))
    member = window.party.member(0)
    window._child("roster").selectRow(0)
    raws = [raw for raw in member.inventory.raws if any(raw)]
    assert raws
    inventory = window.items
    shown = {inventory.data(inventory.index(row, 1))
             for row in range(inventory.rowCount())}
    assert Item(raws[0], names).name in shown


def test_a_dual_class_character_counts_each_class_row_by_its_own_spells(
        app, monkeypatch, tmp_path, fake_names):
    """One memorised spell of each class at level 1 reads 1/n on every row,
    not the three-spell total on each."""
    window, _folder = _open_synthetic(monkeypatch, tmp_path, names=True)
    record = window.party.member(0).record
    slots = bytearray(record.get_raw("spells_castable"))
    slots[0], slots[9] = 2, 1           # cleric 1, druid 1
    record.set_raw("spells_castable", bytes(slots))
    record.set_memorised([9, 77, 1])    # magic-user 1, druid 1, cleric 1
    window._populate()
    capacity = window._child("field_spells_memorised_capacity").text()
    assert "cleric: L1 1/2" in capacity
    assert "druid: L1 1/1" in capacity
    assert "magic-user: L1 1/3" in capacity


def test_a_stored_experience_above_the_box_ceiling_survives_a_flush(
        app, monkeypatch, tmp_path, fake_names):
    window, _folder = _open_synthetic(monkeypatch, tmp_path, names=True)
    record = window.party.member(0).record
    record.set("experience", 3_000_000_000)
    window._populate()
    assert window._widgets["experience"].value() == window._widgets[
        "experience"].maximum() < 3_000_000_000
    assert window._flush(0) == []
    assert record.get("experience") == 3_000_000_000
    window._widgets["experience"].setValue(5)
    assert window._flush(0) == []
    assert record.get("experience") == 5


def test_an_amiga_character_s_items_and_levels_are_editable_like_dos(
        app, monkeypatch, tmp_path, fake_names):
    """The Amiga's writer takes back the items and a level in any class, so
    the window greys no more for the Amiga than for DOS."""
    from PyQt6.QtCore import Qt

    from editor import inventory as inventory_columns
    window, _folder = _open_synthetic(monkeypatch, tmp_path, names=True)
    levels = [n for n in podsheet.LEVEL_SLOTS if n in window._widgets]
    assert "level_fighter" in levels
    window.party.port = "amiga"
    window._apply_read_only()
    window._populate()
    assert window.items.read_only is False
    assert all(window._widgets[n].isEnabled() for n in levels)
    # Add also needs the game's item records, which this window has none of.
    assert window._child("button_item_delete").isEnabled()
    assert window.add_item("anything") != "items are read-only here"
    first = window.items.index(0, inventory_columns.QTY)
    assert window.items.flags(first) & Qt.ItemFlag.ItemIsEditable
