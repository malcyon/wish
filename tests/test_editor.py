"""Tests for the character editor.

The binding and file handling are pure Python. The window needs Qt but not a
display -- QT_QPA_PLATFORM=offscreen, set in the fixture -- so all of it runs
headless.
"""

import os
import pathlib

import pytest
from gamedata import disk_dir, disk_path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QLabel, QWidget

from editor.binding import (
    binding_for,
    bindings,
    editable_fields,
    shown_fields,
)
from editor.files import back_up, prune
from editor.roster import Party
from por.layout import LAYOUT, Confidence

# Wherever the player keeps them, not wherever one machine did.
DISKS = str(disk_dir() or "no-disks-here")
game_disks = pytest.mark.skipif(not pathlib.Path(f"{DISKS}/PORSAVE11.D64").exists(),
                                reason="needs the save disks")


@pytest.fixture
def save(tmp_path):
    """A throwaway copy. Never test against the player's real disks.

    Skips rather than raising when there are none. A fixture that raises turns
    every test using it into an ERROR on a machine without the game, which is
    what CI is; skipping is the same signal the rest of the suite gives.
    """
    src = disk_path("PORSAVE11")
    if src is None:
        pytest.skip("needs the save disks")
    out = tmp_path / "PORSAVE11.D64"
    out.write_bytes(src.read_bytes())
    return out


# --- read-only rules --------------------------------------------------------

def test_a_field_the_game_recomputes_is_read_only():
    b = bindings(in_save=True)
    assert b["thac0_base"].read_only
    assert "recomputes" in b["thac0_base"].reason


def test_a_field_we_do_not_understand_is_read_only():
    unknown = next(f for f in LAYOUT if f.confidence is Confidence.UNKNOWN)
    assert binding_for(unknown, in_save=True).read_only


def test_the_tail_of_the_record_is_read_only_in_a_save_only():
    """A slot holds 256 bytes of a 580-byte record, so a write past 0x100 is
    silently dropped -- but the same field is real in a .chr export."""
    assert bindings(in_save=True)["hp_current"].read_only
    assert not bindings(in_save=False)["hp_current"].read_only


def test_an_ordinary_field_is_editable():
    assert not bindings(in_save=True)["strength"].read_only
    assert not bindings(in_save=True)["gold"].read_only


def test_no_placeholder_fields_reach_the_form():
    assert not [f for f in editable_fields()
                if f.name.startswith(("region_", "gap_", "unknown"))]


# --- the roster -------------------------------------------------------------

@game_disks
def test_a_save_disk_lists_its_party_with_ac_and_hp(save):
    party = Party(str(save))
    assert party.is_save and len(party) == 6
    roland = next(m for m in party.members if m.name == "ROLAND")
    assert (roland.hp_current, roland.hp_max) == (5, 7)
    assert roland.wounded
    assert roland.armour_class == 4


@game_disks
def test_a_roster_disk_has_no_savedgame_and_still_lists_characters():
    """PORSAVE10.D64 holds eight standalone characters and no SAVEDGAME0 at
    all. An editor that assumes a save disk always has one falls over here."""
    party = Party(f"{DISKS}/PORSAVE10.D64")
    assert not party.is_save
    assert len(party) == 8
    assert {"NYX", "DAX", "ASTRID"} <= {m.name for m in party.members}
    assert all(m.armour_class is None for m in party.members)


# --- backups ----------------------------------------------------------------

def test_a_backup_is_made_and_the_original_is_unchanged(tmp_path):
    f = tmp_path / "x.d64"
    f.write_bytes(b"before")
    copy = back_up(f)
    assert copy.read_bytes() == b"before"
    assert copy.parent.name == "backups"


def test_saving_to_a_new_name_backs_up_nothing(tmp_path):
    assert back_up(tmp_path / "not-there.d64") is None


def test_pruning_drops_the_oldest_not_the_newest(tmp_path):
    target = tmp_path / "x.d64"
    into = tmp_path / "backups"
    into.mkdir()
    for i in range(25):
        (into / f"x.d64.{i:03d}").write_bytes(b"")
    dropped = prune(target, into, keep=20)
    assert len(dropped) == 5
    left = sorted(p.name for p in into.glob("x.d64.*"))
    assert left[0] == "x.d64.005" and left[-1] == "x.d64.024"


# --- the window -------------------------------------------------------------

@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def expected_sheet_fields():
    """The fields `editor/character.ui` is expected to carry a widget for.

    The exclusions live in `editor/binding.NOT_ON_THE_SHEET`, beside the code
    that acts on them, so the sheet and the test cannot drift apart.
    """
    return shown_fields(editable_fields())


@game_disks
def test_the_window_binds_every_field_widget(app, save):
    from editor.window import EditorWindow
    w = EditorWindow(str(save))
    assert w.model.rowCount() == 6
    # every non-placeholder field has a widget, plus the promoted icon
    assert len(w._widgets) == len(expected_sheet_fields()) + 1


@game_disks
def test_selecting_a_character_fills_the_sheet(app, save):
    from editor.window import EditorWindow
    w = EditorWindow(str(save))
    w.ui.roster.selectRow(2)
    assert w._widgets["name"].text() == "ROLAND"
    w.ui.roster.selectRow(0)
    assert w._widgets["name"].text() == "MALCYON"


@game_disks
def test_an_edit_survives_switching_character_and_back(app, save):
    """The flush-before-switch bug: an edit made and not tabbed out of must not
    vanish when another character is clicked."""
    from editor.window import EditorWindow
    w = EditorWindow(str(save))
    w.ui.roster.selectRow(0)
    w._widgets["gold"].setValue(4242)
    w.ui.roster.selectRow(3)
    w.ui.roster.selectRow(0)
    assert w._widgets["gold"].value() == 4242


@game_disks
def test_read_only_widgets_are_disabled_on_a_save(app, save):
    from editor.window import EditorWindow
    w = EditorWindow(str(save))
    assert not w._widgets["hp_current"].isEnabled()
    assert not w._widgets["thac0_base"].isEnabled()
    assert w._widgets["strength"].isEnabled()


@game_disks
def test_a_no_op_save_writes_nothing_at_all(app, save):
    """The bar the CLI holds, and it matters more here because Save overwrites
    the file you opened. Visiting every character must not perturb a byte."""
    from editor.window import EditorWindow
    before = save.read_bytes()
    w = EditorWindow(str(save))
    for row in range(6):
        w.ui.roster.selectRow(row)
    assert w.save(interactive=False) == "no changes"
    assert save.read_bytes() == before
    assert not (save.parent / "backups").exists()


@game_disks
def test_a_real_edit_is_written_and_backed_up(app, save):
    from editor.window import EditorWindow
    before = save.read_bytes()
    w = EditorWindow(str(save))
    w.ui.roster.selectRow(0)
    w._widgets["gold"].setValue(1234)
    w._edited()
    assert "wrote" in w.save(interactive=False)
    assert save.read_bytes() != before
    backups = list((save.parent / "backups").glob("*"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == before

    again = EditorWindow(str(save))
    again.ui.roster.selectRow(0)
    assert again._widgets["gold"].value() == 1234


# --- the inventory ----------------------------------------------------------

GAME_DISK = f"{DISKS}/POOL1.D64"


@pytest.fixture
def editor(app, save):
    """A window with a game disk, so items have names and templates exist."""
    from editor.window import EditorWindow
    return EditorWindow(str(save), GAME_DISK)


@game_disks
def test_items_are_shown_by_name_not_by_number(editor):
    editor.ui.roster.selectRow(2)                    # ROLAND
    names = [editor.items.data(editor.items.index(r, 1)) for r in range(16)]
    assert names[:2] == ["BANDED MAIL", "MACE"]
    assert names[2] == "—"                           # a free slot, shown as one


@game_disks
def test_without_a_game_disk_the_tab_says_why_items_are_numbers(app, save):
    from editor.window import EditorWindow
    w = EditorWindow(str(save))                      # no game disk beside it
    w.ui.roster.selectRow(2)
    assert "word 57/48" == w.items.data(w.items.index(0, 1))
    assert "No game disk" in w.findChild(QLabel, "label_inventory").text()
    assert not w.findChild(QWidget, "button_item_add").isEnabled()


@game_disks
def test_editing_quantity_and_readied_reaches_the_disk(editor, save):
    from PyQt6.QtCore import Qt

    from editor.window import EditorWindow
    editor.ui.roster.selectRow(0)                    # MALCYON, six darts
    model = editor.items
    assert model.setData(model.index(1, 2), 9)                       # quantity
    assert model.setData(model.index(1, 3), Qt.CheckState.Checked.value,
                         Qt.ItemDataRole.CheckStateRole)             # readied
    assert model.setData(model.index(1, 5), -2)                      # bonus
    assert "wrote" in editor.save(interactive=False)

    again = EditorWindow(str(save), GAME_DISK)
    again.ui.roster.selectRow(0)
    item = again.items.inventory.item(1)
    assert (item.quantity, item.readied, item.bonus) == (9, True, -2)


@game_disks
def test_an_added_item_is_a_copy_of_the_games_own_record(editor, save):
    from editor.window import EditorWindow
    from por.items import load_item_templates
    editor.ui.roster.selectRow(2)                    # ROLAND, two items
    assert "slot 2" in editor.add_item("POTION OF HEALING")
    editor.save(interactive=False)

    again = EditorWindow(str(save), GAME_DISK)
    again.ui.roster.selectRow(2)
    raw = again.items.inventory.raws[2]
    assert raw == load_item_templates(GAME_DISK)["POTION OF HEALING"]


@game_disks
def test_deleting_closes_the_gap(editor):
    editor.ui.roster.selectRow(2)                    # BANDED MAIL, MACE
    assert "slot 0" in editor.delete_item(0)
    assert editor.items.inventory.item(0).name == "MACE"
    assert editor.items.inventory.is_empty(1)


@game_disks
def test_an_identified_item_cannot_be_un_identified(editor):
    """Which name words to hide is not recoverable once they are shown -- the
    CLI refuses the same edit."""
    from PyQt6.QtCore import Qt
    editor.ui.roster.selectRow(2)
    flags = editor.items.flags(editor.items.index(0, 4))
    assert not flags & Qt.ItemFlag.ItemIsUserCheckable


@game_disks
def test_a_no_op_save_writes_nothing_with_a_game_disk_open(editor, save):
    """The item blocks are read and written by a different path from the
    records, so they need their own round-trip proof."""
    before = save.read_bytes()
    for row in range(6):
        editor.ui.roster.selectRow(row)
    assert editor.save(interactive=False) == "no changes"
    assert save.read_bytes() == before


# --- spells -----------------------------------------------------------------

@game_disks
def test_spells_are_shown_by_name(editor):
    editor.ui.roster.selectRow(2)                    # ROLAND, a cleric
    book, memorised = editor._spell_widgets()
    assert book.known() == [1, 2, 3, 4, 5, 6, 7, 8]
    assert memorised.list.item(0).text() == "CURE LIGHT WOUNDS (cleric 1)"


@game_disks
def test_the_capacity_is_shown_beside_the_memorised_list(editor):
    editor.ui.roster.selectRow(2)
    _book, memorised = editor._spell_widgets()
    assert "cleric: L1 3/3" in memorised.capacity.text()


@game_disks
def test_editing_the_spellbook_reaches_the_disk(editor, save):
    from editor.window import EditorWindow
    editor.ui.roster.selectRow(0)                    # MALCYON, a magic-user
    book, _memorised = editor._spell_widgets()
    assert book.known() == [11, 18, 19, 21]
    book.set_ids([11, 18, 19, 21, 9])                # BURNING HANDS
    editor._edited()
    assert "wrote" in editor.save(interactive=False)

    again = EditorWindow(str(save), GAME_DISK)
    again.ui.roster.selectRow(0)
    assert again._spell_widgets()[0].known() == [9, 11, 18, 19, 21]


@game_disks
def test_a_memorised_spell_the_character_does_not_know_is_allowed(editor, save):
    """Shown, never refused: the CLI reports the same inconsistency and writes
    it anyway, because trying what the game has not been shown is the point."""
    from editor.window import EditorWindow
    editor.ui.roster.selectRow(0)
    _book, memorised = editor._spell_widgets()
    assert memorised.add_spell(36)                   # a cleric 3 spell
    assert "not in the spellbook" in memorised.capacity.text()
    assert "wrote" in editor.save(interactive=False)

    again = EditorWindow(str(save), GAME_DISK)
    again.ui.roster.selectRow(0)
    assert again._spell_widgets()[1].ids() == [36]


@game_disks
def test_an_untouched_spell_field_is_written_back_byte_for_byte(editor):
    """The bitmask has bits belonging to no spell and the memorised list has a
    tail we cannot account for. Neither may be normalised on the way through."""
    editor.ui.roster.selectRow(2)
    book, memorised = editor._spell_widgets()
    record = editor.party.member(2).record
    assert book.to_bytes() == record.get_raw("spells_known")
    assert memorised.to_bytes() == record.get_raw("spells_memorised")


# --- the combat icon --------------------------------------------------------

@game_disks
def test_the_icon_picker_offers_the_game_s_own_two_lists(app, editor):
    """Not 253 glyphs a cell. `SPELLE64` says 35 weapons and 23 heads at this
    size, and those are the only two choices the ICON menu has."""
    from editor.partspicker import PartsPicker
    parts = editor.icon_parts
    assert parts is not None, "no disk carrying SPELLE64 was found"
    shape = parts.compose("small", 0, 1)
    colours = parts.colours_for(shape, {k: 1 for k in range(7)}, bytes(18))
    picker = PartsPicker(parts, editor.charset, shape, colours)
    assert picker.weapons.count() == 28
    assert picker.heads.count() == 14


@game_disks
def test_changing_a_cell_glyph_reaches_the_disk(editor, save):
    from editor.window import EditorWindow
    editor.ui.roster.selectRow(4)                    # MAGNUS
    icon = editor._widgets["icon"]
    assert icon.icon.shape[0] != 200
    icon.set_cell_glyph(0, 200)
    editor._edited()
    assert "wrote" in editor.save(interactive=False)

    again = EditorWindow(str(save), GAME_DISK)
    again.ui.roster.selectRow(4)
    assert again._widgets["icon"].icon.shape[0] == 200


@game_disks
def test_changing_a_cell_colour_reaches_the_disk(editor, save):
    """The colour half was editable before this batch and was never written
    back -- the icon table is patched separately from the character slots."""
    from editor.window import EditorWindow
    editor.ui.roster.selectRow(4)
    icon = editor._widgets["icon"]
    icon.set_cell_colour(0, 7)
    editor._edited()
    editor.save(interactive=False)

    again = EditorWindow(str(save), GAME_DISK)
    again.ui.roster.selectRow(4)
    assert again._widgets["icon"].icon.colours[0] == 7


# --- dropdowns --------------------------------------------------------------

@game_disks
def test_race_class_alignment_and_sex_are_named(editor):
    editor.ui.roster.selectRow(1)                    # LADY KATHERINE
    shown = {n: editor._widgets[n].currentText()
             for n in ("race", "char_class", "class_bits", "alignment", "sex")}
    assert shown["race"] == "4  HALF-ELF"
    assert shown["class_bits"] == "5  magic-user/thief"
    assert shown["alignment"] == "5  NEUTRAL EVIL"
    assert shown["sex"] == "1  female"


def test_race_zero_is_named_rather_than_left_blank():
    """The commonest race in the game, and the reason PRINCESS FATIMA reads as
    a monster. Not evidence of tampering."""
    from editor.enums import RACE
    assert "MONSTER" in RACE[0] and "none" in RACE[0]


@game_disks
def test_a_code_the_game_has_no_name_for_is_still_shown(app, editor):
    from editor.window import _select
    combo = editor._widgets["race"]
    _select(combo, 200)
    assert combo.currentData() == 200
    assert "not in the game's table" in combo.currentText()


@game_disks
def test_the_two_class_fields_are_allowed_to_disagree(editor, save):
    """0x073 and 0x0EB say the same thing two ways. Forcing them into
    agreement is where a losslessness bug came from."""
    from editor.window import EditorWindow
    editor.ui.roster.selectRow(1)
    before = editor.party.member(1).record.get("class_bits")
    editor._widgets["char_class"].setCurrentIndex(
        editor._widgets["char_class"].findData(2))          # FIGHTER
    editor._edited()
    editor.save(interactive=False)

    again = EditorWindow(str(save), GAME_DISK)
    again.ui.roster.selectRow(1)
    assert again._widgets["char_class"].currentData() == 2
    assert again.party.member(1).record.get("class_bits") == before


@game_disks
def test_choosing_an_alignment_reaches_the_disk(editor, save):
    from editor.window import EditorWindow
    editor.ui.roster.selectRow(0)
    combo = editor._widgets["alignment"]
    combo.setCurrentIndex(combo.findData(0))                # LAWFUL GOOD
    editor._edited()
    assert "wrote" in editor.save(interactive=False)

    again = EditorWindow(str(save), GAME_DISK)
    again.ui.roster.selectRow(0)
    assert again._widgets["alignment"].currentData() == 0


# --- preview ----------------------------------------------------------------

@game_disks
def test_preview_of_an_untouched_save_reports_no_changes(editor):
    for row in range(6):
        editor.ui.roster.selectRow(row)
    assert editor.preview_text().endswith("no changes")


@game_disks
def test_preview_lists_fields_items_and_the_icon(editor):
    editor.ui.roster.selectRow(0)
    editor._widgets["gold"].setValue(999)
    editor.items.setData(editor.items.index(1, 2), 9)
    editor.add_item("POTION OF HEALING")
    editor._widgets["icon"].set_cell_colour(0, 7)
    text = editor.preview_text()
    assert "slot 0 MALCYON: gold 2 -> 999" in text
    assert "slot 0 MALCYON: item 1 DART quantity 4 -> 9" in text
    assert "item 7 added: POTION OF HEALING" in text
    assert "combat icon: 1 of 36 bytes changed" in text
    assert "4 change(s) (nothing written yet)" in text


@game_disks
def test_preview_writes_nothing(editor, save):
    before = save.read_bytes()
    editor.ui.roster.selectRow(0)
    editor._widgets["gold"].setValue(999)
    editor.preview()
    assert save.read_bytes() == before


@game_disks
def test_the_preview_window_does_not_block(editor):
    """Save must not become modal, and neither may the report it renders."""
    editor.preview()
    assert editor._preview.isVisible() and not editor._preview.isModal()


@game_disks
def test_a_roster_disk_still_opens_and_has_no_items(app, tmp_path):
    """PORSAVE10.D64 has no SAVEDGAME0, so no items and no icons -- the tabs
    must say so rather than crash."""
    from editor.window import EditorWindow
    copy = tmp_path / "PORSAVE10.D64"
    copy.write_bytes(pathlib.Path(f"{DISKS}/PORSAVE10.D64").read_bytes())
    w = EditorWindow(str(copy), GAME_DISK)
    for row in range(8):
        w.ui.roster.selectRow(row)
    assert w.items.rowCount() == 0
    assert "roster disk" in w.findChild(QLabel, "label_inventory").text()
    assert w.add_item("POTION OF HEALING") == "no inventory here"
    assert w.preview_text().endswith("no changes")


# --- the sheet is boxes, not tabs -------------------------------------------

BOXES = ("box_identity", "box_abilities", "box_saves", "box_levels",
         "box_thief_skills", "box_money", "box_appearance", "box_inventory",
         "box_spells", "box_traits", "box_effects")


@game_disks
def test_the_sheet_is_one_scrolling_page_of_group_boxes(app, save):
    """Nine tabs answered "is this the wounded one" in nine clicks. One page
    with titled borders answers it in none."""
    from PyQt6.QtWidgets import QGroupBox, QScrollArea, QTabWidget

    from editor.window import EditorWindow
    w = EditorWindow(str(save))
    assert w.findChild(QTabWidget) is None
    assert isinstance(w.findChild(QScrollArea, "sheet_scroll"), QScrollArea)
    for name in BOXES:
        assert isinstance(w.findChild(QGroupBox, name), QGroupBox), name


@game_disks
def test_every_field_still_binds_after_the_conversion(app, save):
    """The count is the point: a field left behind in a deleted tab is silent."""
    from editor.window import EditorWindow
    w = EditorWindow(str(save))
    assert len(w._widgets) == len(expected_sheet_fields()) + 1
    assert w._widgets["thief_open_locks"].parent().objectName() == "box_thief_skills"


@game_disks
def test_a_fighter_is_shown_no_spellbook_and_no_thief_skills(app, save):
    """Eight thief-skill zeros invite somebody to type in them."""
    from editor.window import EditorWindow
    w = EditorWindow(str(save))
    # isHidden, not isVisible: nothing is visible until the window is shown.
    w.ui.roster.selectRow(5)                         # BRUTUS, a fighter
    assert w._child("box_thief_skills").isHidden()
    assert w._child("box_spells").isHidden()
    w.ui.roster.selectRow(1)                         # LADY KATHERINE, mu/thief
    assert not w._child("box_thief_skills").isHidden()
    assert not w._child("box_spells").isHidden()
    w.ui.roster.selectRow(2)                         # ROLAND, a cleric
    assert w._child("box_thief_skills").isHidden()
    assert not w._child("box_spells").isHidden()


@game_disks
def test_a_hidden_box_is_still_written_back_untouched(app, save):
    """Hiding is a display decision. The bytes behind it are not ours to lose."""
    from editor.window import EditorWindow
    before = save.read_bytes()
    w = EditorWindow(str(save))
    for row in range(6):
        w.ui.roster.selectRow(row)
    assert w.save(interactive=False) == "no changes"
    assert save.read_bytes() == before


def test_moving_a_box_in_designer_needs_no_code_change(app, tmp_path):
    """The promise the .ui exists for. A box is moved to the other column and
    every field must still be found -- `findChild` does not care who the
    parent is."""
    import pathlib as _p
    import xml.etree.ElementTree as ET

    from PyQt6 import uic
    from PyQt6.QtWidgets import QMainWindow, QWidget

    from editor.binding import field_name

    tree = ET.parse(_p.Path("editor/character.ui"))
    # Any two columns: naming them would make this test fail whenever the
    # sheet is rearranged, which is the very thing it exists to permit.
    columns = [w for w in tree.iter("layout")
               if (w.get("name") or "").startswith("column_")]
    source = next(c for c in columns
                  if any(i.find("widget") is not None
                         and i.find("widget").get("name") == "box_thief_skills"
                         for i in c))
    target = next(c for c in columns if c is not source)
    item = next(i for i in source
                if i.find("widget") is not None
                and i.find("widget").get("name") == "box_thief_skills")
    source.remove(item)
    target.insert(0, item)
    out = tmp_path / "rearranged.ui"
    tree.write(out, encoding="unicode")

    form = uic.loadUi(str(out), QMainWindow())
    found = {field_name(w.objectName()) for w in form.findChildren(QWidget)
             if field_name(w.objectName())}
    assert "thief_open_locks" in found
    assert len(found) == len(expected_sheet_fields()) + 1


@game_disks
def test_experience_is_editable_and_reaches_the_disk(app, save):
    """It used to be a RAW field in a QLineEdit, and `_flush` writes back only
    `name`, so typing an experience total silently did nothing. It is a 24-bit
    integer field now."""
    from editor.window import EditorWindow
    w = EditorWindow(str(save))
    w.ui.roster.selectRow(0)
    assert w._widgets["experience"].value() == 86
    w._widgets["experience"].setValue(31337)
    w._edited()
    assert "wrote" in w.save(interactive=False)

    again = EditorWindow(str(save))
    again.ui.roster.selectRow(0)
    assert again._widgets["experience"].value() == 31337


@game_disks
def test_nothing_looks_editable_that_cannot_be_written(app, save):
    """A widget the flush cannot handle must be disabled, not silently ignored.
    RAW fields are shown as hex for information only."""
    from PyQt6.QtWidgets import QLineEdit

    from editor.window import EditorWindow
    w = EditorWindow(str(save))
    w.ui.roster.selectRow(0)
    lying = [n for n, widget in w._widgets.items()
             if isinstance(widget, QLineEdit) and n != "name" and widget.isEnabled()]
    assert not lying, f"enabled but unwritable: {lying}"


# --- the roster carries race and class, and is no taller than its rows -------

@game_disks
def test_the_roster_names_the_race_and_class(app, save):
    """"The dwarf fighter" is how you pick who to edit."""
    from editor.window import EditorWindow, RosterModel
    w = EditorWindow(str(save))
    assert RosterModel.HEADERS == ("Name", "Race", "Class", "AC", "HP")
    row = [w.model.data(w.model.index(0, c)) for c in range(5)]
    assert row == ["MALCYON", "elf", "magic-user", "6", "4 / 4"]
    assert w.model.data(w.model.index(4, 1)) == "dwarf"


@game_disks
def test_the_roster_is_sized_to_its_rows_not_to_the_window(app, save):
    """Six characters used to fill a quarter of the window."""
    from editor.window import EditorWindow, _content_height
    w = EditorWindow(str(save))
    w.resize(1200, 900)
    w.show()                       # heights are wrong until the table is shown
    # No splitter: the roster, the icon and the sheet are one scrolling page.
    # The table is capped at its own rows and never stretches to the window.
    assert w.ui.roster.maximumHeight() <= _content_height(w.ui.roster) + 8
    assert _content_height(w.ui.roster) < 300


def test_the_whole_sheet_scrolls_as_one_page(app, save):
    """A fixed top over a scrolling bottom squeezed the fields into a sixty
    pixel strip on any window short of enormous. Everything scrolls together."""
    from PyQt6.QtWidgets import QScrollArea, QSplitter

    from editor.window import EditorWindow
    w = EditorWindow(str(save))
    w.resize(1200, 700)
    w.show()
    assert w.findChild(QSplitter) is None, "the splitter is what caused this"
    scroll = w.findChild(QScrollArea, "sheet_scroll")
    assert scroll is not None
    # The roster is inside the scrolled page, not above it.
    assert w.ui.roster.isVisibleTo(scroll)


# --- field widths come from the layout --------------------------------------

def test_the_widest_value_comes_from_the_kind_and_the_byte_width():
    from editor.binding import value_range, widest_text
    from por.layout import FIELDS_BY_NAME
    assert widest_text(FIELDS_BY_NAME["strength"]) == "255"
    assert widest_text(FIELDS_BY_NAME["gold"]) == "65535"
    assert widest_text(FIELDS_BY_NAME["name"]) == "W" * 20
    assert widest_text(FIELDS_BY_NAME["thief_open_locks"]) == "-128"
    assert value_range(FIELDS_BY_NAME["experience"]) == (0, 0xFFFFFF)


@game_disks
def test_a_name_box_is_wider_than_an_ability_box(app, save):
    """Every box was the same generous width whatever could go in it."""
    from editor.window import EditorWindow
    w = EditorWindow(str(save))
    name = w._widgets["name"].maximumWidth()
    strength = w._widgets["strength"].maximumWidth()
    gold = w._widgets["gold"].maximumWidth()
    assert strength < gold < name
    assert (w._widgets["strength"].minimum(),
            w._widgets["strength"].maximum()) == (0, 255)
    assert w._widgets["thief_open_locks"].minimum() == -128


@game_disks
def test_the_identity_box_is_called_character(app, save):
    from PyQt6.QtWidgets import QGroupBox

    from editor.window import EditorWindow
    w = EditorWindow(str(save))
    assert w.findChild(QGroupBox, "box_identity").title() == "Character"


# --- the item column, and the two new tables --------------------------------

@game_disks
def test_the_item_column_fits_the_longest_name_the_disks_hold(editor):
    """163 items, and the widest is TWO-HANDED SWORD +1 +3 VS UNDEAD."""
    from editor import inventory
    table = editor._child("inventory")
    wanted = table.fontMetrics().horizontalAdvance(inventory.LONGEST_ITEM_NAME)
    assert inventory.LONGEST_ITEM_NAME in editor.templates
    assert wanted <= table.columnWidth(inventory.NAME) <= wanted + 40


@game_disks
def test_the_traits_of_the_selected_item_are_shown(editor):
    editor.ui.roster.selectRow(2)                     # ROLAND
    editor._child("inventory").selectRow(0)           # BANDED MAIL
    assert editor._show_traits() == "BANDED MAIL"
    traits = dict(editor.traits.rows)
    assert traits["Protection"] == "AC 4"
    assert traits["Usable by"] == "cleric, fighter"
    editor._child("inventory").selectRow(1)           # MACE
    assert dict(editor.traits.rows)["Damage vs medium"] == "1d6+1"


@game_disks
def test_a_free_slot_has_no_traits(editor):
    editor.ui.roster.selectRow(2)
    editor._child("inventory").selectRow(15)
    assert editor._show_traits() == "Select an item"
    assert editor.traits.rowCount() == 0


@game_disks
def test_a_scroll_shows_its_spells_and_a_wand_its_charges(editor):
    from editor.inventory import ItemTraitsModel
    from por.items import Item
    m = ItemTraitsModel()
    m.set_tables(editor.item_types, editor.spell_names)
    m.set_item(Item(editor.templates["MU SCROLL WITH 1 SPELL"], editor.item_names))
    assert dict(m.rows)["Spells"] == "MAGIC MISSILE (magic-user 1)"
    m.set_item(Item(editor.templates["WAND OF MAGIC MISSILES"], editor.item_names))
    rows = dict(m.rows)
    assert rows["Charges"] == "20"
    # 88 - 23 = 65, past RESTORATION, so it is not named from the spell table.
    assert rows["Effect"].startswith("effect 65")
    m.set_item(Item(editor.templates["CURSED NECKLACE"], editor.item_names))
    rows = dict(m.rows)
    assert rows["Saving throws"] == "-5" and rows["Cursed"].startswith("yes")
    m.set_item(Item(editor.templates["GAUNTLETS OF OGRE POWER"], editor.item_names))
    assert "passive" in dict(m.rows)["Power"]


@game_disks
def test_the_effect_list_shows_an_elfs_racial_resistance(editor):
    """107 in the first slot is what GEN seeds an elf with, and the editor
    showed no sign of it before."""
    from editor import effects
    view = editor._widgets["item_effects"]
    editor.ui.roster.selectRow(0)                     # MALCYON, an elf
    assert view.codes()[0] == 107
    assert view.model_.data(view.model_.index(0, 2)) == \
        "elf: 90% resistance to sleep and charm"
    assert view.model_.rowCount() == effects.SLOTS
    editor.ui.roster.selectRow(2)                     # ROLAND, a human
    assert not any(view.codes())
    assert view.model_.data(view.model_.index(0, 2)) == effects.EMPTY


def test_a_code_nobody_has_named_is_shown_as_a_number():
    """Silently dropping it would read as "this character has nothing".

    The DOS guide's effect table named most of these, so the code picked here
    is one it does not reach -- and the point of the test is the fallback, not
    which code happens to be unnamed today.
    """
    from editor.effects import EffectsModel
    from por.traits import describe
    assert describe(107) == "elf: 90% resistance to sleep and charm"
    assert describe(200) == "trait 200"
    m = EffectsModel(bytes([200]))
    assert m.data(m.index(0, 1)) == "200"
    assert m.data(m.index(0, 2)) == "trait 200"
