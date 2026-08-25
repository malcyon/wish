"""Tests for the character editor.

The binding and file handling are pure Python. The window needs Qt but not a
display -- QT_QPA_PLATFORM=offscreen, set in the fixture -- so all of it runs
headless.
"""

import os
import pathlib

import pytest
from gamedata import disk_dir, disk_path, synthetic_save

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


@pytest.fixture
def party(tmp_path):
    """A save disk built from the format rather than copied off one.

    Six characters at the widest the record and the title's tables allow, so
    the width tests that used to skip everywhere run in CI -- #70. The
    disk-backed twin of each is what proves it representative.
    """
    return synthetic_save(tmp_path)


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
    # The widget holds the whole mask, both declared fields of it, because how
    # far into it a title reaches is the title's business.
    assert book.to_bytes() == editor._spellbook_raw(record)
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
    a monster. Not evidence of tampering.

    Named `MONSTER` and not annotated since 2026-08-24: the note it used to
    carry was wider than the longest real race, and `Race` is what sets the
    Character box's width -- and so the header's, which is a floor under the
    whole window (#41, #43).
    """
    from editor.enums import RACE
    assert RACE[0] == "MONSTER" and RACE[8] == "MONSTER"


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

BOXES = ("box_identity", "box_combat", "box_roster", "box_abilities",
         "box_saves", "box_levels", "box_thief_skills", "box_money",
         "box_appearance", "box_inventory", "box_spells", "box_traits",
         "box_effects")

#: Above the tabs, on every one of them: the roster and Character. Character
#: is up there because 23 fields stacked in a column were 672px tall and the
#: tab could not hold them; eleven of them are up there in two columns.
#:
#: One box, since round eight. The combat icon spent round five on the Stats
#: tab, came back in round six and has gone down again: it is 166px of header
#: at every font size on every platform -- `IconEditor` is `FRAME_WIDE * ZOOM`,
#: 48 squares at 3 pixels -- and pure floor, because nothing in it can read a
#: wider window. Taking it off the header took 172px off the whole window's
#: minimum, which is what brought the widest party a save can hold inside a
#: 1280 screen at Donald's own font. Character Traits was tried here too and
#: Donald turned it down: it made the header far too tall.
HEADER_BOXES = ("box_identity",)

#: Donald's grouping, and the whole of it. `box_levels` -- Experience and
#: levels -- was not in the grouping he wrote and is here because it is a
#: stats box; it is the one placement to check with him.
#:
#: Round seven dissolved `box_record` -- Miscellaneous -- which was thirteen
#: unrelated fields and a title that admitted it. `box_combat` took the six
#: that decide a fight, including the Armour class pair the header used to
#: carry; `box_roster` took the six read-only housekeeping fields nobody
#: edits.
#:
#: Round eight brought the combat icon down here, beside `Combat`: Donald's
#: own proposal, on the grounds that the two belong together and that the
#: header shrinks. Both are true -- see `HEADER_BOXES` above.
TABS = {
    "Stats": ("box_combat", "box_roster", "box_abilities", "box_money",
              "box_saves", "box_thief_skills", "box_effects", "box_levels",
              "box_appearance"),
    "Inventory": ("box_inventory", "box_traits"),
    "Spells": ("box_spells",),
}

#: Left to right across the Stats tab. Donald asked for Abilities and Saving
#: throws on the left of the window. That is a fact about order and not about
#: grouping, so it is pinned separately: a repack that put the housekeeping
#: fields back on the left would still satisfy `TABS`.
#:
#: Character Traits is last and alone, which is round seven's answer to the
#: hole Donald drew a box round: it is the only box on the tab that can use
#: spare width, so it gets a column to itself and all of the stretch, and the
#: four columns of fields hug their own contents. Packed so no column is
#: taller than Experience and levels over Thief skills, which is what decides
#: whether the tab scrolls on his screen.
#:
#: The combat icon goes under Roster and so directly right of Combat, which is
#: the only place on the tab that is both beside Combat and free: Roster is
#: 298px wide against the icon's 166, and the column had 320px of nothing
#: under it. Every other slot costs the tab 172px of width -- a column of its
#: own -- or puts the icon under Combat rather than beside it. Measured at
#: 1330x940 with a save open, the tab asks for the same 1241px it did in
#: round seven -- the icon costs no width at all -- and the empty part of
#: column four goes from 298x323 to an L a fifth smaller.
#: Column three's second item is a *row*, `row_combat`, holding `Combat` and
#: the combat icon side by side and top-aligned -- Donald asked for the icon's
#: top to meet Combat's top line, and matching two boxes of different heights
#: with a spacer would come apart the first time either gained a field.
STATS_COLUMNS = (("box_abilities", "box_saves"),
                 ("box_levels", "box_thief_skills"),
                 ("box_money", ("box_combat", "box_appearance")),
                 ("box_roster",),
                 ("box_effects",))


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
    # The roster and Character are above the tabs, on every one of them.
    for i in range(tabs.count()):
        assert not tabs.widget(i).isAncestorOf(w.ui.roster)
        for name in HEADER_BOXES:
            assert not tabs.widget(i).isAncestorOf(w._child(name)), name


@game_disks
def test_the_stats_columns_are_in_the_order_donald_asked_for(app, save):
    """Abilities and Saving throws on the left of the window, Character Traits
    alone on the right.

    Left to right and not merely present, because the five columns pack eight
    boxes and the tallest of them decides how much of the tab scrolls. A
    repack that balanced better and ignored the order would pass
    `test_the_sheet_is_three_tabs_and_every_box_is_on_one_of_them`, and a
    repack that put a narrow box in the stretching column would put the hole
    back.

    No column heights are quoted here on purpose. Three measurements of them
    during round four disagreed by up to 30px, because a box's minimum depends
    on whether a save is open, whether the widget has been shown, and the UI
    font -- so a number written down here is true of one run and misleading in
    the next. The order is what this test is about, and the order is stable.
    """
    from PyQt6.QtWidgets import QGroupBox

    from editor.window import EditorWindow
    w = EditorWindow(str(save))
    columns = w.ui.sheet_columns
    got = []
    for i in range(columns.count()):
        column = columns.itemAt(i).layout()
        if column is None:
            continue
        entries = []
        for j in range(column.count()):
            widget = column.itemAt(j).widget()
            if isinstance(widget, QGroupBox):
                entries.append(widget.objectName())
                continue
            row = column.itemAt(j).layout()
            if row is not None:
                inner = tuple(row.itemAt(k).widget().objectName()
                              for k in range(row.count())
                              if isinstance(row.itemAt(k).widget(), QGroupBox))
                if inner:
                    entries.append(inner)
        got.append(tuple(entries))
    assert got == list(STATS_COLUMNS)


@game_disks
def test_the_combat_icon_sits_beside_combat(app, save):
    """Donald's own proposal, and round eight's whole change: the icon and the
    `Combat` box belong together by meaning, and the header shrinks by 172px
    when the icon leaves it -- which is what takes the widest party a save can
    hold from 1265px of window to 1093 at the default UI font, and from 1442 to
    1270 at three points more, against a 1280 screen.

    `STATS_COLUMNS` pins which column it is in. This pins that it is *beside*
    `Combat` and not merely on the same tab: the next column to the right, and
    overlapping it vertically, which is the difference between the icon being
    where he asked for it and the icon being under `Roster` by coincidence.

    Geometry rather than layout indices, because the two are only side by side
    if the boxes above them leave them level -- `Money` is 232px tall and
    `Roster` 203, so the icon starts 29px above `Combat` and ends inside it.
    """
    from editor.window import EditorWindow
    w = EditorWindow(str(save))
    w.show()
    w.resize(1330, 940)
    app.processEvents()
    page = w._child("page_stats")
    combat = w._child("box_combat")
    icon = w._child("box_appearance")
    left = combat.mapTo(page, combat.rect().topLeft())
    right = icon.mapTo(page, icon.rect().topLeft())
    assert right.x() >= left.x() + combat.width(), "the icon is not to the right"
    assert right.x() - (left.x() + combat.width()) < 30, "and not far to the right"
    top, bottom = right.y(), right.y() + icon.height()
    assert top < left.y() + combat.height() and bottom > left.y(), (
        "the icon and Combat do not overlap vertically")


@game_disks
def test_the_stats_spare_width_goes_to_the_one_box_that_can_use_it(app, save):
    """The hole Donald drew a box round, and why it was there.

    Character Traits is the only box on this tab that can use spare width.
    Round six shared the stretch equally between four columns, which turned
    one 490x230 hole beside Money into a gap beside every column; round seven
    gives Traits a column of its own and all of the stretch, and the columns
    of fields are sized to their own contents with nothing between them.

    The assertion is that exactly one column stretches and it is the one
    holding Traits -- not five particular numbers.
    """
    from PyQt6.QtWidgets import QGroupBox

    from editor.window import EditorWindow
    w = EditorWindow(str(save))
    columns = w.ui.sheet_columns
    stretches = [columns.stretch(i) for i in range(columns.count())]
    assert len(stretches) == len(STATS_COLUMNS)
    stretched = [i for i, s in enumerate(stretches) if s]
    assert len(stretched) == 1, stretches
    column = columns.itemAt(stretched[0]).layout()
    boxes = [column.itemAt(j).widget().objectName()
             for j in range(column.count())
             if isinstance(column.itemAt(j).widget(), QGroupBox)]
    assert boxes == ["box_effects"], boxes


@game_disks
def test_the_header_s_spare_width_goes_to_a_spacer(app, save):
    """Nothing in the header grows into a wider window except the gap.

    Every field in Character is sized to the widest value its bytes can hold,
    so it cannot read a wider window. The roster could, and that was the fault:
    a `Stretch` section takes the whole viewport, so `Name` drew several times
    the longest name the game can hold. Capping it did nothing --
    `QHeaderView` ignores `maximumSectionSize` for a stretching section (#90).

    So the slack leaves the table. `header_slack` is the only item in the row
    with any stretch, the roster is pinned to exactly its five columns, and a
    wider window widens the gap between the two boxes and nothing else.

    Round six's history is why this is asserted rather than left to the
    layout: the slack was given to Character and shared 1:1 between its two
    form columns, which each took half and huddled at their own left edge --
    the gutter down the middle of Character and the gap beside it, both of
    which Donald marked. Handing it to the fields instead only moved it: a
    drop-down 890px wide with `2  ELF` in it.
    """
    from editor.window import EditorWindow
    w = EditorWindow(str(save))
    row = w.ui.header_row
    stretched = [i for i in range(row.count()) if row.stretch(i)]
    assert len(stretched) == 1, "one thing takes the slack, not none and not two"
    assert row.itemAt(stretched[0]).spacerItem() is not None, (
        "the slack belongs to the spacer, not to a box that would grow into it")
    columns = w.ui.form_identity
    assert not any(columns.stretch(i) for i in range(columns.count()))

    view = w.ui.roster
    header = view.horizontalHeader()
    from editor.window import NAME_COLUMN
    assert header.sectionResizeMode(NAME_COLUMN) != header.ResizeMode.Stretch
    assert view.maximumWidth() == view.minimumWidth(), (
        "the roster is its columns, whatever the window is doing")
    # And the column really is a name's width rather than a window's.
    from por.layout import NAME_SIZE
    widest = view.fontMetrics().horizontalAdvance("W" * NAME_SIZE)
    assert header.sectionSize(NAME_COLUMN) <= widest * 2


#: The screen `tests/test_mapscale.py` holds the whole window to, and the one
#: Donald asked for in round five: a 1280x720 laptop, forty pixels shorter than
#: the 1280x760 the earlier rounds allowed themselves. The editor has to fit
#: inside it with room to spare, or it becomes the floor instead of the map.
SMALL_LAPTOP = (1280, 720)


@game_disks
def test_the_sheet_is_not_a_floor_under_the_window(app, save):
    """The measurement issue #43 asked for, and the reason for the tabs.

    Four columns in one scroll area asked for 2001x1127 and collapsed to
    421x141, so the sheet was unreadable at any window anybody would open. The
    editor's minimum is 853x400 with a save open, and the widest tab -- Stats
    -- scrolls when it cannot have the room it asks for.

    The width is the header. The header does not scroll, so the window can
    never be narrower than what stands in it side by side: 683 with nothing
    but the roster, 1883 with all 23 of Character's fields down one row, 992
    with the five it kept in round four, 892 once the combat icon left and
    Character was given ten fields in two columns, 957 in round six with
    Character held to a constant 520, 1025 in round seven, and 853 now -- the
    combat icon has gone to the Stats tab and taken 172px of header with it.
    The rest is the roster, which is sized from the names in the party.

    See `test_the_header_fits_its_width_budget` below, which is the
    arithmetic, and `test_character_is_two_columns_the_way_donald_drew_it`,
    which is the shape.

    What is left tracking the font is the roster, which is sized from the
    names it holds: 349px at the default UI font, 446 at three points more and
    669 at ten. That is #70's half of the problem, it is the whole of the
    difference between the numbers above, and it is not measured by CI,
    because every test that opens a save skips without the disks.

    The floor is not zero because a box of spin boxes cannot shrink, which is
    why the scroll area survived the tabs and merely moved inside them.

    The assertions are relations wherever they can be, because a number
    measured on Linux says nothing about Windows -- but the size is pinned to
    a real screen, because a window bigger than the desktop is the failure
    this round exists to prevent.
    """
    from PyQt6.QtWidgets import QGroupBox

    from editor.window import EditorWindow
    w = EditorWindow(str(save))
    w.show()
    floor = w.minimumSizeHint()
    assert floor.width() <= SMALL_LAPTOP[0]
    assert floor.height() <= SMALL_LAPTOP[1]
    # The tallest tab page wants more height than the whole window's floor
    # gives it, so the scroll areas are still doing the work. Measured against
    # the page and not against the tallest single box since round seven:
    # Miscellaneous was 397px of one box and dissolving it left nothing on the
    # sheet taller than the header, which is 202 of the floor's 400.
    pages = ("page_stats", "page_inventory", "page_spells")
    tallest = max(w._child(name).minimumSizeHint().height() for name in pages)
    assert floor.height() < tallest
    # Every box is still on the form -- a split that dropped one would be
    # silent, since a field with no widget is simply not shown.
    assert {b.objectName() for b in w.findChildren(QGroupBox)} >= set(BOXES)


#: Donald's arrangement, left column beside right. Pinned as a shape rather
#: than as a height: the header does not scroll, so a Character reflowed back
#: into one column of eleven would be twice as tall for no measurement to
#: catch.
#:
#: The Armour class pair left for `Combat` in round seven, which is what made
#: the header cheaper; `Sex`, `Age` and `Size` came up from Miscellaneous,
#: which is what it cost. Both moves are measured in
#: `test_the_header_fits_its_width_budget`.
IDENTITY_COLUMNS = (("name", "race", "char_class", "class_bits", "alignment"),
                    ("hp_max", "hp_rolled", "hp_current",
                     "sex", "age", "size_small"))

#: The six that decide a fight, and the six nobody edits. What used to be
#: `Miscellaneous`, which was neither.
COMBAT_FIELDS = ("thac0_base", "thac0", "armour_class_base", "armour_class",
                 "movement", "infravision")
ROSTER_FIELDS = ("roster_in_use", "party_order", "roster_movement",
                 "roster_tail", "turn_class", "flags_0b8")


def _form_fields(form) -> tuple[str, ...]:
    from PyQt6.QtWidgets import QFormLayout

    from editor.binding import field_name
    return tuple(
        field_name(form.itemAt(r, QFormLayout.ItemRole.FieldRole)
                   .widget().objectName())
        for r in range(form.rowCount()))


@game_disks
def test_character_is_two_columns_the_way_donald_drew_it(app, save):
    """Every derived field is beside its source -- `Hp current` under `Hp max`
    -- which is the rule the round-two repack broke when it packed for width
    alone.

    The two columns are inside a container of their own since round seven,
    so that a header too narrow for them clips instead of drawing one column
    over the other -- #71, and `EditorWindow._pin_identity_columns`.
    """
    from PyQt6.QtWidgets import QFormLayout, QHBoxLayout

    from editor.window import EditorWindow
    w = EditorWindow(str(save))
    box = w._child("box_identity")
    columns = w._child("columns_identity")
    assert box.isAncestorOf(columns), "the columns are not inside Character"
    assert isinstance(columns.layout(), QHBoxLayout), "one column, not two"
    got = []
    for i in range(columns.layout().count()):
        form = columns.layout().itemAt(i).layout()
        assert isinstance(form, QFormLayout)
        got.append(_form_fields(form))
    assert tuple(got) == IDENTITY_COLUMNS


@game_disks
def test_miscellaneous_is_gone_and_its_fields_are_grouped(app, save):
    """`Miscellaneous` was thirteen unrelated fields and a title that said so.

    Every one of them is still on the sheet, in a box named for what it holds:
    the Armour class pair came down out of the header to sit with Thac0, and
    `Sex`, `Age` and `Size` went up to Character because they are identity.
    """
    from PyQt6.QtWidgets import QGroupBox

    from editor.window import EditorWindow
    w = EditorWindow(str(save))
    assert w.findChild(QGroupBox, "box_record") is None
    assert _form_fields(w.ui.form_combat) == COMBAT_FIELDS
    assert _form_fields(w.ui.form_roster) == ROSTER_FIELDS


@game_disks
def test_no_two_widgets_in_character_overlap_at_its_floor(app, save):
    """#71, and the test the issue asked for.

    The header is capped so the window's floor stops following the UI font,
    and at a Windows-sized font Character wants nearly twice the cap. Round
    six let the layout squeeze both form columns below their own minimums:
    the left column's labels lost all their width and vanished, and the right
    column's labels were drawn over the left column's fields -- `Hp max` on
    top of the name box, `Armour class` reading `Armour c`.

    It clips at the box's edge instead now. What is off the edge is not
    readable either, and that is still #71's remaining half -- the header
    costs 880px at ten points of extra font against a 1280 screen -- but a
    field that is off the edge is a window that is too narrow, and a field
    with another field drawn on top of it is a broken program.

    At +0 and at +10, which is roughly where Windows' base UI font measures.
    """
    from PyQt6.QtGui import QFont
    from PyQt6.QtWidgets import QComboBox, QLabel, QLineEdit, QSpinBox

    from editor.window import EditorWindow
    base = app.font()
    try:
        for extra in (0, 10):
            bigger = QFont(base)
            bigger.setPointSizeF(base.pointSizeF() + extra)
            app.setFont(bigger)
            w = EditorWindow(str(save))
            w.show()
            columns = w._child("columns_identity")
            w.resize(w.minimumSizeHint())
            app.processEvents()
            # Direct children only: a spin box's own line edit is a child of
            # the spin box and its geometry is in the spin box's coordinates.
            kinds = (QLabel, QLineEdit, QSpinBox, QComboBox)
            boxes = [(c.objectName(), c.geometry())
                     for c in columns.children()
                     if isinstance(c, kinds) and c.objectName()]
            for i, (name, one) in enumerate(boxes):
                for other_name, other in boxes[i + 1:]:
                    assert not one.intersects(other), (
                        f"+{extra}pt: {name} and {other_name} overlap")
    finally:
        app.setFont(base)


#: What the boxes in the header may cost between them, at three points of
#: extra UI font, before the whole window stops fitting `SMALL_LAPTOP`. The
#: roster is 446 of it at that font, the header's spacings and the window's
#: own margins 26, which leaves this.
#:
#: Derived from a real party's roster, which is why it is a budget and not the
#: guarantee: against the *widest* party a save can hold the roster is 764 at
#: that font, and what settles whether the window fits 1280 is
#: `tests/test_mapscale.py::test_the_window_still_fits_the_laptop_with_a_save_open`,
#: which measures the whole window against the whole screen.
#:
#: Round four derived the same budget from the automapper's 836 and got 422.
#: That 836 is measured with nothing open (#63): with a save loaded the
#: automapper is not the floor and the editor is, so the screen is the ceiling
#: that governs and the screen is what this is taken from.
IDENTITY_BUDGET = SMALL_LAPTOP[0] - 446 - 26


def _floor_width(box) -> int:
    """What a layout will not squeeze a box below.

    `qSmartMinSize` takes an explicit `minimumSize` in preference to
    `minimumSizeHint`, which is how Character Traits is allowed to be narrower
    than its own title.
    """
    return box.minimumWidth() or box.minimumSizeHint().width()


def _header_cost(app, save, extra: int = 3) -> int:
    """What the header's boxes will not be squeezed below, at a given font."""
    from PyQt6.QtGui import QFont

    from editor.window import EditorWindow
    base = app.font()
    try:
        bigger = QFont(base)
        bigger.setPointSizeF(base.pointSizeF() + extra)
        app.setFont(bigger)
        w = EditorWindow(str(save))
        w.show()
        return sum(_floor_width(w._child(name)) for name in HEADER_BOXES)
    finally:
        app.setFont(base)


def test_the_header_fits_its_width_budget(app, party):
    """The header does not scroll, so every pixel in it is a floor under the
    whole window -- and every widget in it is sized from font metrics, which
    is the mechanism #41 was opened to remove.

    Measured at three points of extra UI font. Round four: the five fields
    Character kept cost 392, and Donald's two-column arrangement cost 672
    against a 422 budget -- impossible by 250. Round five moved the combat
    icon out of the header, which was 310px of it at every font size, and
    trimmed the `Name` box by 30% -- it was 318 wide because twenty bytes of
    name is twenty capital Ws.

    Round six is the first one where the budget is *enforced* rather than
    checked: what is measured here is the explicit minimum each box is held
    to. That was 480 for Character and 166 for the combat icon, 646 against a
    budget of 808 at any font at all; round eight sent the icon to the Stats
    tab and it is 480. Round five's 648 was a measurement, it was true on
    Linux, and on Windows the same box measured 876 -- see
    `test_the_header_boxes_do_not_widen_with_the_ui_font`. A budget checked
    against one platform's font metrics is not a budget.

    What the budget does not say is what Character *wants*, which is the
    other half of #71 and is not fixed. Round seven moved the Armour class
    pair down to `Combat` and brought `Sex`, `Age` and `Size` up from
    Miscellaneous, and Character went from 939 to 880 at ten points of extra
    font and from 1207 to 1120 at sixteen. Against a 1280 screen with the
    roster's 669 beside it, both still overrun; what is capped clips rather
    than overlapping -- `test_no_two_widgets_in_character_overlap_at_its_floor`
    -- and the roster is the next thing that would have to give.

    Every box in the header and not Character by name, because the budget is
    what the header costs. A second one added without a floor of its own would
    pass a test that measured only the first -- which is how the combat icon's
    166px went unbudgeted through round five.

    The party is synthetic and the test no longer skips: this and
    `tests/test_mapscale.py::test_the_window_still_fits_the_laptop_with_a_save_open`
    are the two that hold the 1280x720 line, and both used to skip on every CI
    job there is (#70). What is measured here is a pair of explicit minimums,
    so the answer does not depend on which party is open -- which is exactly
    why the disks-only twin below is an equality rather than a bound.
    """
    assert _header_cost(app, party) <= IDENTITY_BUDGET


@game_disks
def test_the_header_fits_its_width_budget_on_a_real_save(app, save, party):
    """The disk-backed twin, and what proves the synthetic party representative.

    An explicit minimum is a constant, so the two must agree exactly. If they
    ever do not, something in the header has started following the party's own
    strings again -- and that is a fault in the header, not in this test.
    """
    assert _header_cost(app, save) == _header_cost(app, party)


@game_disks
def test_the_header_boxes_do_not_widen_with_the_ui_font(app, save):
    """Every box in the header is sized from font metrics, and the header does
    not scroll, so left alone each of them is a floor under the whole window
    that follows the font -- the mechanism #41 was opened to remove.

    Character is 521px wide at the default UI font here, 648 at three points
    more and 874 at eight. It is given an explicit minimum instead, which
    `qSmartMinSize` takes in preference to the hint, and the floor stops
    moving.

    The combat icon used to be held the same way and is not in the header any
    more. It was the cheap box -- `IconEditor` is 144px of fixed pixels at
    every font -- and it was still 166px of floor that nothing could ever read,
    which is why round eight moved it out rather than capping it again.

    Pinned as a relation between font sizes rather than as a number, because
    every number here is a Linux number. Eight points and not three: Windows'
    base UI font measures like eight to ten points more than this one, which
    is why round five passed here and failed there.
    """
    from PyQt6.QtGui import QFont

    from editor.window import EditorWindow
    base = app.font()
    got = {name: [] for name in HEADER_BOXES}
    try:
        for extra in (0, 8):
            bigger = QFont(base)
            bigger.setPointSizeF(base.pointSizeF() + extra)
            app.setFont(bigger)
            w = EditorWindow(str(save))
            w.show()
            for name in HEADER_BOXES:
                box = w._child(name)
                got[name].append(_floor_width(box))
                # Explicitly set, not merely hinted: it is the explicit one
                # that `qSmartMinSize` takes, and a box left to its hint is
                # exactly what failed on Windows.
                assert box.minimumWidth() > 0, f"{name} has no floor of its own"
    finally:
        app.setFont(base)
    for name, widths in got.items():
        assert widths[0] == widths[1], f"{name} widened with the font"


def test_the_editors_own_floor_does_not_follow_the_ui_font(app):
    """The Linux-runnable half of `tests/test_mapscale.py`'s #41 guarantee,
    and the test that would have caught round five.

    That one measures the whole window, where the automapper's own floor is
    usually the larger of the two and hides what the editor is doing. This
    one measures the editor alone, with nothing open -- which is the state CI
    can reach without the disks -- and at eight points of extra font, which is
    roughly where Windows' base UI font measures.

    Round five put ten fields and their labels in a header that does not
    scroll, and on Windows CI the whole window's floor went from 1036 to 1304
    with three points of font: #41's guarantee broken, and 1304 over the
    1280 screen as well. Here the same box goes from 521 to 874 and the
    editor's floor does not move, because the header and the button row above
    it are both held to constants.

    No save, so no `@game_disks`: this has to run on a machine without the
    game, because that machine is CI and CI is where round five got through.
    """
    from PyQt6.QtGui import QFont

    from editor.window import EditorWindow
    base = app.font()
    got = []
    try:
        for extra in (0, 8):
            bigger = QFont(base)
            bigger.setPointSizeF(base.pointSizeF() + extra)
            app.setFont(bigger)
            got.append(EditorWindow(None).minimumSizeHint().width())
    finally:
        app.setFont(base)
    assert got[0] == got[1], f"the editor's floor followed the font: {got}"


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
    # Donald's words, and the only new string round five put on the sheet.
    assert w.findChild(QGroupBox, "box_abilities").title() == "Ability Scores"


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


# --- the later titles' spells -----------------------------------------------
# Issues #80 and #81. The editor read Pool of Radiance's `SPELLN00` whatever
# save was open and Pool of Radiance's seven-byte mask whatever title it
# belonged to, so on Curse and Silver Blades the Spells tab showed numbers, and
# on Silver Blades it showed two thirds of the numbers there were.
#
# The disks are the player's own, found the way the rest of the suite finds
# them, and every test here skips when they are absent.

def _copy_disks(source, pattern, into):
    import shutil
    for disk in sorted(source.glob(pattern)):
        shutil.copy(disk, into / disk.name)


def _title_save(where, pattern, game, into):
    """A throwaway copy of a whole save disk of one title, or skip.

    Copied because a test must never write to the player's disks, and the
    editor is a program that writes.
    """
    from por.d64 import D64
    if where is None:
        pytest.skip(f"needs the {game.title} disks")
    _copy_disks(where, pattern, into)
    for path in sorted(into.glob(pattern)):
        try:
            disk = D64.open(path)
            entry = disk.find(game.save_file)
            if entry is not None and game.matches_payload(disk.read_file(entry)):
                return path
        except Exception:
            continue
    pytest.skip(f"no {game.title} disk here carries a whole save")


def _curse_window(app, tmp_path):
    from gamedata import curse_dir

    from editor.window import EditorWindow
    from por import games
    save = _title_save(curse_dir(), "CURSE*.[dD]64",
                       games.CURSE_OF_THE_AZURE_BONDS, tmp_path)
    return EditorWindow(str(save))


def _silver_blades_window(app, tmp_path):
    from editor.window import EditorWindow
    from por import games
    ssb_dir = pytest.importorskip("tests.test_silverblades").ssb_dir
    save = _title_save(ssb_dir(), "SILVER*.[dD]64",
                       games.SECRET_OF_THE_SILVER_BLADES, tmp_path)
    return EditorWindow(str(save))


def _rows(book):
    """Every tick box in a spellbook widget, by spell id."""
    return {sid: row.text() for sid, row in book._rows.items()}


def test_a_curse_spellbook_names_its_spells_rather_than_numbering_them(
        app, tmp_path):
    """#80. `SHOCKING GRASP` is id 20 in both titles, so the number is the same
    and only the table it is looked up in differs.

    Curse ships no `SPELLN00`; its names are in `COMBAT2` at `$E000`. Asking
    for the wrong file raised, the exception was logged and swallowed, and an
    empty name table looks exactly like a missing game disk.
    """
    from por import games
    window = _curse_window(app, tmp_path)
    assert window.party.game is games.CURSE_OF_THE_AZURE_BONDS
    assert window.spell_names, "no spell names off a Curse disk"

    book, _ = window._spell_widgets()
    rows = _rows(book)
    assert rows[20].startswith("SHOCKING GRASP")
    assert not [t for t in rows.values() if t.startswith("spell ")], (
        [t for t in rows.values() if t.startswith("spell ")][:5])


def test_a_silver_blades_spellbook_names_its_spells_too(app, tmp_path):
    """#80, third title. Silver Blades moves two of the fifty-six -- 36 is
    `HEAL` where Pool of Radiance has `ANIMATE DEAD` -- so a spellbook read
    against the wrong table would be wrong even where it was not blank."""
    from por import games
    window = _silver_blades_window(app, tmp_path)
    assert window.party.game is games.SECRET_OF_THE_SILVER_BLADES
    rows = _rows(window._spell_widgets()[0])
    assert rows[20].startswith("SHOCKING GRASP")
    assert rows[36].startswith("HEAL")
    assert not [t for t in rows.values() if t.startswith("spell ")]


def test_the_editor_and_the_automapper_name_the_same_spells(app, tmp_path):
    """The disagreement was the clearest evidence of #80 and is the test.

    `automap/window.py::_names_for_spells` calls
    `por.spells.load_spell_names(path, game)` -- with the title. The editor
    called it without, so the two windows named the same character's spells
    differently: the map said `STINKING CLOUD` and the sheet said `spell 34`.
    """
    from por.spells import load_spell_names
    for build in (_curse_window, _silver_blades_window):
        window = build(app, tmp_path)
        disk = window._find_game_disk()
        automapper = load_spell_names(disk, window.party.game)
        assert automapper, "the automapper's own call found no names"
        assert window.spell_names == automapper
        # And what the missing title cost, in the same breath: neither title
        # ships `SPELLN00`, so the untitled call raises, the window logged the
        # exception and carried on, and the panel numbered every spell.
        with pytest.raises(Exception, match="SPELLN00"):
            load_spell_names(disk)


def test_a_silver_blades_casters_spellbook_reaches_past_spell_fifty_five(
        app, tmp_path):
    """#81. MORGAINE knows twenty-nine spells and the sheet showed twenty-four.

    Seven bytes is 56 bits, which is Pool of Radiance's spell count and nothing
    else's. Silver Blades' mask is sixteen bytes -- `GEN $41DC` clears exactly
    that many -- so `CONFUSION`, `FIRE SHIELD`, `MINOR GLOBE OF INVULNERABLITY`
    and `HOLD MONSTERS`, ids 82, 85, 88 and 94, had no tick box to appear in.
    """
    from por.spells import SECRET_OF_THE_SILVER_BLADES as TABLE
    from por.spells import spells_known

    window = _silver_blades_window(app, tmp_path)
    row = next(r for r in range(window.model.rowCount())
               if window.party.member(r).record.name.strip() == "MORGAINE")
    window.ui.roster.selectRow(row)
    record = window.party.member(row).record

    book, _ = window._spell_widgets()
    assert book.known() == spells_known(record.to_bytes(), TABLE)
    assert len(book.known()) == 29
    assert 94 in book.known()
    assert _rows(book)[94].startswith("HOLD MONSTERS")


def test_a_silver_blades_spellbook_survives_an_edit_of_its_low_bits(
        app, tmp_path):
    """Ticking a first-level spell must not clear the fourth-level ones.

    The mask spans two declared fields now, and this is the failure that would
    follow from writing only one of them.
    """
    window = _silver_blades_window(app, tmp_path)
    row = next(r for r in range(window.model.rowCount())
               if window.party.member(r).record.name.strip() == "MORGAINE")
    window.ui.roster.selectRow(row)
    record = window.party.member(row).record
    before = window._spellbook_raw(record)

    book, _ = window._spell_widgets()
    book.set_ids(sorted(set(book.known()) | {13}))
    window._flush()
    after = window._spellbook_raw(record)
    assert after[10:] == before[10:], "the high bytes moved"
    assert after[1] == before[1] | (1 << 5)


# --- Castable per level was on screen all along, and unreadable --------------

def test_the_castable_box_shows_its_bytes_whole(app, party):
    """#42: "Castable per level" read `00 00 00 00 00` for every character.

    Not a wrong read and not a wrong field: the box was 85px for the 98px of
    `01 00 00 00 00 00` it had to draw. `widest_text` answers "the longest
    string a field can display", and for six raw bytes every string is the
    same length, so it picked `ff ff ff ff ff ff` -- barely half the width in
    the proportional UI font. `setText` leaves the cursor at the end and
    QLineEdit scrolls to the cursor, so what was on screen was the tail: five
    groups of `00`, identical for a caster with slots and a fighter without.

    Two assertions, because either alone can pass while the field is wrong.
    The text is what the record holds; the leftmost character drawn is the
    first one, which is what says the box is not scrolled.
    """
    from PyQt6.QtCore import QPoint

    from editor.window import EditorWindow

    window = EditorWindow(str(party))
    try:
        box = window._child("field_spells_castable")
        for row in range(len(window.party)):
            window.ui.roster.selectRow(row)
            record = window.party.member(row).record
            raw = record.get_raw("spells_castable")
            assert box.text() == raw.hex(" "), record.name
            box.grab()          # the scroll offset only moves when it paints
            assert box.cursorPositionAt(QPoint(1, box.height() // 2)) == 0, (
                f"{record.name}: {box.text()!r} is scrolled off its left edge")
            assert (box.fontMetrics().horizontalAdvance(box.text())
                    <= box.width()), record.name
    finally:
        window.close()


@game_disks
def test_a_casters_slots_are_not_a_fighters(app, save):
    """The other half of #42: zero is a real answer for three of the six.

    A test that only asserted "the box matches the bytes" would pass on a
    field that was always empty, so one caster and one fighter off the same
    disk are named here. MALCYON is a magic-user 1 with one first-level slot;
    ROLAND is a cleric 1, whose slots sit in the high nibbles; SILAS is a
    fighter and reads all zeros correctly.
    """
    from editor.window import EditorWindow

    window = EditorWindow(str(save))
    try:
        box = window._child("field_spells_castable")
        shown = {}
        for row in range(len(window.party)):
            window.ui.roster.selectRow(row)
            shown[window.party.member(row).record.name.strip()] = box.text()
        assert shown["MALCYON"] == "01 00 00 00 00 00"
        assert shown["ROLAND"] == "30 00 00 00 00 00"
        assert shown["SILAS"] == "00 00 00 00 00 00"
    finally:
        window.close()
