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
from editor.files import automatic_dir, back_up, prune
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

class FakeDisk:
    """A disk with bytes in it, so the file handling is tested without one."""

    def __init__(self, data):
        self.data = data

    def to_bytes(self):
        return self.data

    def save(self, path):
        pathlib.Path(path).write_bytes(self.data)


def test_the_message_spells_out_a_backup_that_went_somewhere_else(tmp_path):
    """Beside the disk, `backups/NAME` is enough. Elsewhere it is not.

    A folder the user chose in Preferences is not one they are looking at, so
    the short form would name a `backups/` on a path the message never gives.
    """
    from editor import files

    beside = tmp_path / "PORSAVE11.D64"
    beside.write_bytes(b"old")
    said = files.save_disk(FakeDisk(b"new"), beside,
                           files.automatic_dir(beside))
    assert said.startswith("wrote PORSAVE11.D64, backup backups/")

    elsewhere = tmp_path / "elsewhere"
    other = tmp_path / "PORSAVE12.D64"
    other.write_bytes(b"old")
    said = files.save_disk(FakeDisk(b"new"), other, elsewhere)
    assert str(elsewhere) in said          # the whole path, not just the leaf


def test_no_backup_folder_refuses_the_save_rather_than_writing(tmp_path):
    """The rule the editor's licence to overwrite rests on.

    It writes back over the file you opened, and the only reason that is
    defensible is the copy it takes first. With nowhere to put the copy the
    save does not happen -- there is no hidden directory to fall back to.
    """
    from editor import files

    save = tmp_path / "PORSAVE11.D64"
    save.write_bytes(b"old")
    with pytest.raises(files.NoBackupFolder) as raised:
        files.save_disk(FakeDisk(b"new"), save, "")
    assert save.read_bytes() == b"old"
    assert "Preferences" in str(raised.value)
    # And a save that would write nothing needs no folder: closing a window
    # nobody edited in must not turn into an argument about backups.
    assert files.save_disk(FakeDisk(b"old"), save, "") == "no changes"


def test_a_backup_is_made_and_the_original_is_unchanged(tmp_path):
    f = tmp_path / "x.d64"
    f.write_bytes(b"before")
    copy = back_up(f, automatic_dir(f))
    assert copy.read_bytes() == b"before"
    assert copy.parent.name == "backups"


def test_saving_to_a_new_name_backs_up_nothing(tmp_path):
    assert back_up(tmp_path / "not-there.d64", tmp_path / "backups") is None


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


@game_disks
def test_a_spell_list_is_wide_enough_for_the_longest_name(editor):
    """Donald: "the spells are not visible in the table because it's so
    small". The spellbook opened 70 pixels wide beside a memorised column
    whose drop-down asked for 330, inside a box capped at 520.

    The rule and not the pixel count: whatever the font, each list is at least
    as wide as its longest line plus the frame and the scroll bar. The
    spellbook's tick box makes it wider still, so this is a floor for both.
    """
    from PyQt6.QtWidgets import QStyle

    editor.resize(1875, 1030)
    editor.show()
    editor.ui.roster.selectRow(0)                    # MALCYON, a magic-user
    book, memorised = editor._spell_widgets()
    lists = ((book.list, [book.list.item(i).text()
                          for i in range(book.list.count())]),
             # Any spell can be memorised, so the memorised list is measured
             # against every name the drop-down offers, not against the two
             # in it now.
             (memorised.list, [memorised.choice.itemText(i)
                               for i in range(memorised.choice.count())]))
    for view, texts in lists:
        wanted = max(view.fontMetrics().horizontalAdvance(t) for t in texts)
        furniture = 2 * view.frameWidth() + view.style().pixelMetric(
            QStyle.PixelMetric.PM_ScrollBarExtent, None, view)
        assert wanted > 0
        assert view.minimumWidth() >= wanted + furniture
        # And the sheet gives them the width they ask for.
        assert view.width() >= wanted + furniture


@game_disks
def test_the_memorised_drop_down_shows_a_whole_spell_name(editor):
    """Donald: "the text isn't entirely visible". Sharing a row with Add and
    Remove left it 132 px of edit field for a 303 px name."""
    editor.resize(1875, 1030)
    editor.show()
    editor.ui.roster.selectRow(0)
    _book, memorised = editor._spell_widgets()
    choice = memorised.choice
    wanted = max(choice.fontMetrics().horizontalAdvance(choice.itemText(i))
                 for i in range(choice.count()))
    assert choice.minimumWidth() >= wanted     # plus the frame and the arrow
    assert choice.width() >= wanted


@game_disks
def test_the_window_opens_inside_a_small_desktop(app, save):
    """Donald's compositor hands out 1280x662 of a 1920x1080 desktop, and the
    sheet asks for 1875x1030. The sheet scrolls; the window has to fit."""
    from PyQt6.QtCore import QRect

    from editor.__main__ import WANTED, fit_on_screen
    from editor.window import EditorWindow
    space = QRect(0, 0, 1280, 662)
    w = EditorWindow(str(save))
    w.resize(*WANTED)
    fit_on_screen(w, space)
    w.show()
    fit_on_screen(w, space)
    assert w.frameGeometry().width() <= space.width()
    assert w.frameGeometry().height() <= space.height()


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


# --- the sheet is three tabs under the roster -------------------------------

BOXES = ("box_identity", "box_abilities", "box_saves", "box_levels",
         "box_thief_skills", "box_money", "box_appearance", "box_inventory",
         "box_spells", "box_traits", "box_effects")

#: Donald's grouping, and the whole of it: every box is on exactly one tab
#: except the icon, which is above them with the roster. `box_levels` --
#: Experience and levels -- was not in the grouping he wrote and is here
#: because it is a stats box; it is the one placement to check with him.
TABS = {
    "Stats": ("box_identity", "box_abilities", "box_money", "box_saves",
              "box_thief_skills", "box_effects", "box_levels"),
    "Inventory": ("box_inventory", "box_traits"),
    "Spells": ("box_spells",),
}


@game_disks
def test_the_sheet_is_three_tabs_and_every_box_is_on_one_of_them(app, save):
    """Four columns side by side asked for 2001px of width and got a scroll
    bar instead. Grouped by what you are doing, the widest tab asks for 912."""
    from PyQt6.QtWidgets import QGroupBox, QTabWidget

    from editor.window import EditorWindow
    w = EditorWindow(str(save))
    tabs = w.findChild(QTabWidget, "sheet_tabs")
    assert [tabs.tabText(i) for i in range(tabs.count())] == list(TABS)
    for name in BOXES:
        assert isinstance(w.findChild(QGroupBox, name), QGroupBox), name
    for i, boxes in enumerate(TABS.values()):
        page = tabs.widget(i)
        for name in boxes:
            assert page.isAncestorOf(w._child(name)), name
    # The roster and the icon are above the tabs, on every one of them.
    for i in range(tabs.count()):
        assert not tabs.widget(i).isAncestorOf(w.ui.roster)
        assert not tabs.widget(i).isAncestorOf(w._child("box_appearance"))


#: A 1280x800 laptop with a task bar taken off it, which is the screen
#: `tests/test_mapscale.py` holds the whole window to. The editor has to fit
#: inside it with room to spare, or it becomes the floor instead of the map.
SMALL_LAPTOP = (1280, 760)


@game_disks
def test_the_sheet_is_not_a_floor_under_the_window(app, save):
    """The measurement issue #43 asked for, and the reason for the tabs.

    Four columns in one scroll area asked for 2001x1127 and collapsed to
    421x141, so the sheet was unreadable at any window anybody would open.
    Three tabs ask for 912x837 at most -- the Stats tab -- and the window's
    minimum is 681x380 here. The width it gained is the roster, which is above
    the tabs now and so outside the scroll area that used to let it collapse.

    The floor is not zero because Character is 395x672 of spin boxes and
    cannot shrink: pinned to their pages with no scroll area the tabs want
    891x1078, which is taller than the laptop in `SMALL_LAPTOP`. That is why
    the scroll area survives the tabs and merely moved inside them.

    Both assertions are relations rather than the numbers above, because a
    number measured on Linux says nothing about Windows -- three points of UI
    font take the minimum to 778x403 and Character to 504x792.
    """
    from editor.window import EditorWindow
    w = EditorWindow(str(save))
    w.show()
    floor = w.minimumSizeHint()
    assert floor.width() <= SMALL_LAPTOP[0]
    assert floor.height() <= SMALL_LAPTOP[1]
    # The tallest box on the sheet is taller than the whole window's minimum.
    assert floor.height() < w._child("box_identity").minimumSizeHint().height()


@game_disks
def test_every_field_still_binds_after_the_conversion(app, save):
    """The count is the point: a field left behind in a deleted tab is silent."""
    from editor.window import EditorWindow
    w = EditorWindow(str(save))
    assert len(w._widgets) == len(expected_sheet_fields()) + 1
    assert w._widgets["thief_open_locks"].parent().objectName() == "box_thief_skills"


@game_disks
def test_a_fighter_is_shown_no_spellbook_and_no_thief_skills(app, save):
    """Greyed, never hidden: the box stays where it is and says why it is off.

    Eight thief-skill zeros still must not invite somebody to type in them.
    """
    from editor.window import EditorWindow
    w = EditorWindow(str(save))
    thief, spells = w._child("box_thief_skills"), w._child("box_spells")
    # isHidden, not isVisible: nothing is visible until the window is shown.
    w.ui.roster.selectRow(5)                         # BRUTUS, a fighter
    assert not thief.isHidden() and not spells.isHidden()
    assert not thief.isEnabled() and not spells.isEnabled()
    assert "not one" in thief.toolTip()
    assert "casts no spells" in spells.toolTip()
    w.ui.roster.selectRow(1)                         # LADY KATHERINE, mu/thief
    assert thief.isEnabled() and spells.isEnabled()
    assert thief.toolTip() == "" and spells.toolTip() == ""
    w.ui.roster.selectRow(2)                         # ROLAND, a cleric
    assert not thief.isEnabled()
    assert spells.isEnabled()


@game_disks
def test_a_non_caster_s_spells_box_says_why_it_is_empty(app, editor):
    """A disabled box with nothing in it and nothing to read is a broken box."""
    editor.ui.roster.selectRow(5)                    # BRUTUS, a fighter
    book, memorised = editor._spell_widgets()
    assert book.known() == []
    assert memorised.ids() == []
    assert memorised.capacity.text() == "This character casts no spells."


@game_disks
def test_a_disabled_box_is_still_written_back_untouched(app, save):
    """Greying is a display decision. The bytes behind it are not ours to lose."""
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
    # No splitter: the roster and the icon are a row above the tabs.
    # The table is capped at its own rows and never stretches to the window.
    assert w.ui.roster.maximumHeight() <= _content_height(w.ui.roster) + 8
    assert _content_height(w.ui.roster) < 300


@game_disks
def test_the_roster_is_wide_enough_for_all_five_columns(app, save):
    """Beside the icon rather than under Character, the table gets the 256px
    `QTableView` hints and not the 331px its columns came to -- so HP fell off
    the right, a horizontal scroll bar appeared, and it ate a row."""
    from editor.window import EditorWindow
    w = EditorWindow(str(save))
    w.resize(1200, 900)
    w.show()
    view = w.ui.roster
    assert view.viewport().width() >= view.horizontalHeader().length()


def test_each_tab_scrolls_inside_itself(app, save):
    """A fixed top over a scrolling bottom squeezed the fields into a sixty
    pixel strip on any window short of enormous, and one scroll area over the
    lot took the tab bar off screen with it. Each tab scrolls on its own, so
    the roster, the icon and the tab bar are always where they were."""
    from PyQt6.QtWidgets import QScrollArea, QSplitter, QTabWidget

    from editor.window import EditorWindow
    w = EditorWindow(str(save))
    w.resize(1200, 700)
    w.show()
    assert w.findChild(QSplitter) is None, "the splitter is what caused this"
    tabs = w.findChild(QTabWidget, "sheet_tabs")
    for name in ("scroll_stats", "scroll_inventory", "scroll_spells"):
        scroll = w.findChild(QScrollArea, name)
        assert scroll is not None, name
        assert scroll.widgetResizable(), name
        assert tabs.isAncestorOf(scroll), name
    assert not tabs.isAncestorOf(w.ui.roster)


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
    assert view.model_.data(view.model_.index(0, 1)) == \
        "elf: 90% resistance to sleep and charm"
    assert view.model_.rowCount() == effects.SLOTS
    editor.ui.roster.selectRow(2)                     # ROLAND, a human
    assert not any(view.codes())
    assert view.model_.data(view.model_.index(0, 1)) == effects.EMPTY


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
    assert m.data(m.index(0, 1)) == "trait 200"
    # No code column: the sheet names the effect, and the number survives only
    # where nobody has named it.
    assert "Code" not in m.HEADERS


# --- the layout does not move ------------------------------------------------

@game_disks
def test_the_sheet_keeps_its_shape_across_the_roster(editor):
    """Donald: "The layout of the form should not change when we navigate the
    roster. It should stay the same, so people know where to look for things at
    all times."

    PORSAVE11 has a magic-user, a magic-user/thief and three fighters, so it
    covers every combination the two class-conditional boxes ever had. No box
    may come or go, and no tab may change the size it asks for.

    `isHidden`, not `isVisible`: a box on a tab that is not showing is not
    visible and never was hidden, and greying it out -- which is what the two
    class-conditional boxes do -- is not hiding it either.
    """
    from PyQt6.QtWidgets import QGroupBox

    editor.resize(1875, 1030)
    editor.show()
    pages = ("page_stats", "page_inventory", "page_spells")
    shapes = []
    for row in range(len(editor.party)):
        editor.ui.roster.selectRow(row)
        boxes = {b.objectName() for b in editor.findChildren(QGroupBox)
                 if not b.isHidden()}
        shapes.append((boxes, tuple(editor._child(n).sizeHint()
                                    for n in pages)))
    first = shapes[0]
    assert all(s == first for s in shapes), [
        (editor.party.member(i).name, sorted(s[0]), s[1])
        for i, s in enumerate(shapes) if s != first]
    assert "box_spells" in first[0]
    assert "box_thief_skills" in first[0]
