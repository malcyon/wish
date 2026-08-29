from __future__ import annotations


def make_root():
    from PyQt6.QtWidgets import QMainWindow

    from wish.ui_window import Ui_WishWindow
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    return root


"""Layout rules that only broke on Windows, asserted here on Linux.

Every test in this file stands for a report from Donald's Windows build that no
Linux run reproduced -- which is exactly why they shipped. The trick each time
is to take the platform difference away from the platform: fake the screen, fake
the window frame, fake a style that draws fat spin-box arrows. What is asserted
is then the *rule*, and the rule holds on both.

Three of them, in the order he found them:

* **The window must never open larger than the available screen**, floor or no
  floor. It did, because the clamp ran before `show()`, when there is no frame
  to measure, and a 1030 px window plus a 39 px title bar does not fit on a
  1080 px screen with a task bar.
* **A field must always show its value.** Widths were tuned to the arrows Fusion
  and Breeze draw; Windows draws wider ones, and the number went.
* **A selected row must read as selected.** The Windows style highlights the
  text of a cell rather than the cell, and draws a focus rectangle around the
  current one, which reads as a stray highlighted space before the text.

No test here opens a modal dialog and none of them changes the application
style: a `QProxyStyle` is set on the one widget under test, because the
`QApplication` is shared by the whole session (`tests/conftest.py`).
"""


import os
import pathlib

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gamedata import disk_dir
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QBrush, QColor, QPixmap, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QProxyStyle,
    QSpinBox,
    QStyle,
    QStyleOptionSpinBox,
    QTableView,
)

from automap.config import (
    UNSHOWN_CHROME,
    Settings,
    clamp_to_screen,
    hold_geometry,
    restore_geometry,
)
from editor.window import TABLE_SELECTION, _spin_width

DISKS = str(disk_dir() or "no-disks-here")
game_disks = pytest.mark.skipif(
    not pathlib.Path(f"{DISKS}/PORSAVE11.D64").exists(),
    reason="needs the save disks")

#: A 1920x1080 desktop with the Windows task bar taken off it. The screen
#: Donald's build opened too big for.
DESKTOP = QRect(0, 0, 1920, 1032)

#: What Windows 11 spends on a title bar and a resize border. Measured off
#: nothing -- it is a stand-in for chrome the offscreen platform never draws --
#: but the rule under test is "whatever the chrome is, the frame fits".
CHROME = (16, 39)


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def framed(window, chrome=CHROME):
    """Give a window a title bar and a border it would not otherwise have.

    The offscreen platform draws no frame at all, so `frameGeometry()` equals
    `geometry()` and every chrome calculation measures zero -- which is the
    same blind spot the real bug lived in, since a window that has never been
    shown has no frame either.
    """
    def frame():
        inner = window.geometry()
        return QRect(inner.x(), inner.y(),
                     inner.width() + chrome[0], inner.height() + chrome[1])

    window.frameGeometry = frame
    return window


# --- the window opens bigger than the screen ---------------------------------

def test_the_first_run_size_is_cut_down_to_a_smaller_screen(app):
    """The bug, in one line: 1875x1030 does not fit on 1920x1032 once a title
    bar is added, and nothing noticed because the clamp ran before `show()`."""
    from wish.window import FIRST_RUN

    win = framed(QMainWindow())
    restore_geometry(win, Settings(), floor=FIRST_RUN, space=DESKTOP)
    frame = win.frameGeometry()
    assert frame.width() <= DESKTOP.width()
    assert frame.height() <= DESKTOP.height(), "the status bar is off the screen"
    assert win.height() < FIRST_RUN[1], "the floor must not beat the display"
    win.close()


def test_the_floor_never_beats_the_display(app):
    """A laptop gets its own size, not the one the first run asks for."""
    from wish.window import FIRST_RUN

    laptop = QRect(0, 0, 1366, 728)
    win = framed(QMainWindow())
    restore_geometry(win, Settings(), floor=FIRST_RUN, space=laptop)
    assert win.frameGeometry().width() <= laptop.width()
    assert win.frameGeometry().height() <= laptop.height()
    win.close()


def test_a_window_never_shown_is_clamped_against_an_estimated_frame(app):
    """There is no frame to measure until the window is on screen, so the
    clamp assumes one. It is only ever an over-estimate, and the second clamp
    after `show()` works off the real numbers."""
    win = QMainWindow()                   # not framed: chrome measures zero
    win.resize(DESKTOP.width(), DESKTOP.height())
    clamp_to_screen(win, DESKTOP)
    assert win.width() == DESKTOP.width() - UNSHOWN_CHROME[0]
    assert win.height() == DESKTOP.height() - UNSHOWN_CHROME[1]
    win.close()


def test_a_window_on_screen_is_clamped_against_its_real_frame(app):
    """Once it is up the frame is real, and the estimate gives way to it."""
    win = framed(QMainWindow())
    win.setVisible(True)
    win.resize(DESKTOP.width(), DESKTOP.height())
    clamp_to_screen(win, DESKTOP)
    assert win.height() == DESKTOP.height() - CHROME[1]
    assert win.frameGeometry().height() == DESKTOP.height()
    win.close()


def test_a_window_too_tall_to_shrink_keeps_its_top_on_screen(app):
    """The resize cannot go below the layout's minimum, so some windows still
    do not fit. When one does not, it overflows off the *bottom*: the menu bar
    has to stay reachable. Donald's Windows build aligned its bottom edge to
    the bottom of the screen instead, and the menus went off the top."""
    win = framed(QMainWindow())
    win.setMinimumSize(1170, DESKTOP.height() + 120)
    win.resize(1200, DESKTOP.height() + 120)
    win.move(200, 100)
    clamp_to_screen(win, DESKTOP)
    assert win.frameGeometry().top() == DESKTOP.top()
    assert win.frameGeometry().height() > DESKTOP.height()   # still too tall
    win.close()


def test_a_maximised_window_is_left_alone(app):
    """Donald's own workaround was to maximise it. The clamp must not undo
    that: resizing a maximised window un-maximises it."""
    win = framed(QMainWindow())
    win.resize(900, 700)
    win.showMaximized()
    if not win.isMaximized():             # some platforms will not do it
        pytest.skip("the platform plugin does not maximise")
    was = win.size()
    clamp_to_screen(win, QRect(0, 0, 400, 300))
    assert win.size() == was
    win.close()


@game_disks
def test_the_whole_window_fits_a_1080p_screen_on_a_first_run(app, tmp_path,
                                                             monkeypatch):
    """The same rule against the real window, which is what Donald opened."""
    from wish.session import Session
    from wish.window import FIRST_RUN, WishWindow

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    win = WishWindow(None, maps={}, session=Session(find=lambda pref=None: None))
    framed(win)
    restore_geometry(win, Settings(), floor=FIRST_RUN, space=DESKTOP)
    assert win.frameGeometry().width() <= DESKTOP.width()
    assert win.frameGeometry().height() <= DESKTOP.height()
    win.close()


# --- the compositor has its own idea of the size -----------------------------

def unshown(window):
    """Laid out and sent events like a real window, and on nobody's desktop.

    `WA_DontShowOnScreen` is what keeps this off whichever compositor the suite
    is run on: `show()` still lays the window out and still delivers the resize
    events the rule is about, and no window is created for a compositor to have
    an opinion about.
    """
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    window.show()
    return window


def test_a_size_the_platform_forces_after_show_is_asked_for_again(app):
    """Donald: on Linux the window doesn't remember its size.

    cosmic-comp answers the first `show()` with a size of its own -- 1280x662
    for a bare `QMainWindow` that asked for 1875x1030 -- and Qt takes it, one
    frame after the window appears. Whatever was restored was gone by the time
    anybody looked, and closing then wrote the compositor's size back over the
    remembered one. Asking again after that first configure is honoured.
    """
    win = unshown(QMainWindow())
    win.resize(1400, 900)
    hold_geometry(win, space=DESKTOP)
    win.resize(1280, 662)                 # the compositor, uninvited
    assert (win.width(), win.height()) == (1400, 900)
    win.close()


def test_the_user_dragging_an_edge_is_never_fought(app):
    """One shot, and only the first. The configure comes in the same breath as
    the window appearing; everything after it is somebody resizing on purpose,
    and a window that snapped back from that would be unusable."""
    win = unshown(QMainWindow())
    win.resize(1400, 900)
    hold_geometry(win, space=DESKTOP)
    win.resize(1280, 662)                 # the compositor
    win.resize(1000, 700)                 # and then the user
    assert (win.width(), win.height()) == (1000, 700)
    win.close()


def test_asking_again_is_still_clamped_to_the_screen(app):
    """A platform that shrank the window because it genuinely does not fit
    still wins: the re-assertion goes through the same clamp as everything
    else, or the Windows bug comes back through this door."""
    win = unshown(framed(QMainWindow()))
    win.resize(1900, 1200)
    hold_geometry(win, space=DESKTOP)
    win.resize(800, 600)
    assert win.frameGeometry().width() <= DESKTOP.width()
    assert win.frameGeometry().height() <= DESKTOP.height()
    win.close()


# --- the spin boxes are too small to show their values -----------------------

class FatArrows(QProxyStyle):
    """A style whose spin-box and combo buttons eat 60 px, standing in for
    Windows, which draws both wider than Fusion and Breeze do.

    The measurement is what is being tested, not the number: a width computed
    from the style is right on any style, and a width computed from a constant
    is right on the one it was measured on.
    """

    BUTTONS = 60
    EATS = {QStyle.ComplexControl.CC_SpinBox:
            QStyle.SubControl.SC_SpinBoxEditField,
            QStyle.ComplexControl.CC_ComboBox:
            QStyle.SubControl.SC_ComboBoxEditField}

    def subControlRect(self, control, option, subcontrol, widget=None):
        rect = super().subControlRect(control, option, subcontrol, widget)
        if self.EATS.get(control) == subcontrol:
            rect.setWidth(max(rect.width() - self.BUTTONS, 0))
        return rect


def room_for_the_value(box: QSpinBox) -> int:
    """How many pixels this style leaves for the number, at the box's width."""
    option = QStyleOptionSpinBox()
    option.initFrom(box)
    option.subControls = (QStyle.SubControl.SC_SpinBoxUp
                          | QStyle.SubControl.SC_SpinBoxDown
                          | QStyle.SubControl.SC_SpinBoxFrame
                          | QStyle.SubControl.SC_SpinBoxEditField)
    option.buttonSymbols = box.buttonSymbols()
    option.frame = box.hasFrame()
    option.rect = QRect(0, 0, box.width(), box.height())
    return box.style().subControlRect(
        QStyle.ComplexControl.CC_SpinBox, option,
        QStyle.SubControl.SC_SpinBoxEditField, box).width()


def test_a_spin_box_shows_its_value_however_wide_the_arrows_are(app):
    """Donald: I can only see up/down arrows, which crowd out the value."""
    from editor.window import SPINBOX_CHROME

    style = FatArrows()
    box = QSpinBox()
    box.setStyle(style)                   # this widget only; never the app
    box.setRange(0, 255)
    box.ensurePolished()
    wanted = box.fontMetrics().horizontalAdvance("255")

    box.resize(_spin_width(box, "255"), box.sizeHint().height())
    assert room_for_the_value(box) >= wanted

    # And the constant this replaced would not have been enough, which is the
    # whole report: it was measured on a style with narrower arrows.
    box.resize(wanted + SPINBOX_CHROME, box.sizeHint().height())
    assert room_for_the_value(box) < wanted
    del style


def test_a_combo_shows_its_longest_name_however_wide_the_arrow_is(app):
    """The same rule for the dropdowns: `magic-user/thief` came out as
    `magic-user` once already, on a style whose arrow was wider than assumed."""
    from PyQt6.QtWidgets import QComboBox, QStyleOptionComboBox

    from editor.window import _size_combo

    style = FatArrows()
    combo = QComboBox()
    combo.setStyle(style)
    combo.addItem("magic-user/thief")
    combo.ensurePolished()
    _size_combo(combo)
    combo.resize(combo.minimumWidth(), combo.sizeHint().height())

    option = QStyleOptionComboBox()
    option.initFrom(combo)
    option.frame = combo.hasFrame()
    option.rect = QRect(0, 0, combo.width(), combo.height())
    field = combo.style().subControlRect(
        QStyle.ComplexControl.CC_ComboBox, option,
        QStyle.SubControl.SC_ComboBoxEditField, combo)
    assert field.width() >= combo.fontMetrics().horizontalAdvance(
        "magic-user/thief")
    del style


@game_disks
def test_every_field_on_the_sheet_can_show_its_widest_value(app, tmp_path):
    """Not one field, all sixty-two, against what `goldbox/layout.py` says each
    can hold. A form sized field by field grows a field that was missed.

    `editor.window.TRIMMED` is the one exception and is read from there rather
    than named here: Donald asked for 30% off the `Name` box in round five of
    #43, because twenty bytes of name is twenty capital Ws, that is 318px at
    three points of extra UI font, and the box sits in the header, which does
    not scroll and is therefore a floor under the whole window. A name that
    long still fits and still edits; it scrolls inside the box. Every other
    field on the sheet still has to show its widest value whole, and a second
    entry appearing in `TRIMMED` has to be a decision somebody made here.
    """
    from PyQt6.QtWidgets import QLineEdit

    from editor.binding import widest_text
    from editor.window import TRIMMED, EditorBinding
    from goldbox.layout import FIELDS_BY_NAME

    assert set(TRIMMED) == {"name"}

    src = pathlib.Path(DISKS) / "PORSAVE11.D64"
    disk = tmp_path / "PORSAVE11.D64"
    disk.write_bytes(src.read_bytes())
    w = EditorBinding(make_root(), str(disk))
    try:
        checked = 0
        for name, widget in w._widgets.items():
            field = FIELDS_BY_NAME.get(name)
            if field is None or not isinstance(widget, (QSpinBox, QLineEdit)):
                continue
            text = widest_text(field)
            wanted = widget.fontMetrics().horizontalAdvance(text)
            wanted = round(wanted * TRIMMED.get(name, 1.0))
            assert widget.minimumWidth() >= wanted, f"{name} cannot show {text}"
            assert widget.minimumWidth() == widget.maximumWidth()
            if isinstance(widget, QSpinBox):
                widget.resize(widget.minimumWidth(), widget.sizeHint().height())
                assert room_for_the_value(widget) >= wanted, name
            checked += 1
        assert checked > 40, "the sheet is not being walked"
    finally:
        w.close()


# --- the selected roster row -------------------------------------------------

def painted(view: QTableView) -> list[str]:
    """The colours across the middle of each row, in row order."""
    view.resize(300, 40 + 30 * view.model().rowCount())
    pixmap = QPixmap(view.size())
    view.render(pixmap)
    image = pixmap.toImage()
    out = []
    top = view.horizontalHeader().height()
    for row in range(view.model().rowCount()):
        middle = top + view.rowHeight(row) // 2
        top += view.rowHeight(row)
        out.append([image.pixelColor(x, middle).name()
                    for x in range(2, view.columnWidth(0) + view.columnWidth(1))])
    return out


def a_table(style=None) -> QTableView:
    model = QStandardItemModel(2, 2)
    for row in range(2):
        for column in range(2):
            cell = QStandardItem("ABC")
            if row == 1:                  # a wounded character, in red
                cell.setData(QBrush(QColor("#b03a2e")), Qt.ItemDataRole.ForegroundRole)
            model.setItem(row, column, cell)
    view = QTableView()
    if style is not None:
        view.setStyle(style)
    view.setModel(model)
    view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
    view.setStyleSheet(TABLE_SELECTION)
    view.selectRow(0)
    return view


def test_the_selected_row_is_filled_edge_to_edge_and_the_others_are_not(app):
    """A whole row of one colour, not a highlighted space before each cell."""
    view = a_table()
    rows = painted(view)
    assert rows[0].count("#cddff5") > len(rows[0]) * 0.6
    assert "#cddff5" not in rows[1]
    view.close()


def test_the_selection_survives_the_table_losing_the_focus(app):
    """`:!active` -- otherwise the row it is editing goes pale the moment you
    click anywhere else, and which character is open stops being obvious."""
    view = a_table()
    view.clearFocus()
    assert "#cddff5" in painted(view)[0]
    view.close()


def test_a_colour_the_model_asks_for_survives_the_selection_rule(app):
    """The stylesheet must not take the wounded red or the NPC ochre with it."""
    view = a_table()
    red = [c for c in painted(view)[1]
           if QColor(c).red() > QColor(c).blue() + 40]
    assert red, "the model's own foreground colour was painted over"
    view.close()


def test_the_roster_carries_the_selection_rule(app):
    """The rule is on the table Donald was looking at, not only in a constant."""
    from editor.window import EditorBinding

    w = EditorBinding(make_root(), )
    try:
        assert "item:selected" in w.roster.styleSheet()
        assert "outline: none" in w.roster.styleSheet()
    finally:
        w.close()


# --- the name, capitalised ---------------------------------------------------

def test_the_title_bar_and_the_about_box_say_wish(app):
    """The product name, capitalised. The command stays `wish`."""
    from editor.window import EditorBinding
    from wish import about

    w = EditorBinding(make_root(), )
    try:
        assert w.root.windowTitle() == "Wish"          # from the .ui, nothing open
        w.path = pathlib.Path("PORSAVE14.D64")
        w._retitle()
        assert w.root.windowTitle() == "Wish - PORSAVE14.D64"
    finally:
        w.close()
    assert about.TEXT.startswith("<h3>Wish ")


# --- the preferences dialog --------------------------------------------------

def test_the_debug_log_has_no_paragraph_under_it_and_no_popup(app, tmp_path,
                                                              monkeypatch):
    """Two of Donald's, together: remove the descriptive text, and remove the
    popup that appears when the user checks it."""
    from wish.preferences import PreferencesDialog
    from wish.session import Session
    from wish.window import WishWindow

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    win = WishWindow(None, maps={}, session=Session(find=lambda pref=None: None))
    said = []
    win.announce = lambda title, text: said.append(title)
    try:
        dialog = PreferencesDialog(win)
        box = dialog.logging.parentWidget()
        assert box.title() == "Diagnostics"
        assert [q.text() for q in box.findChildren(QLabel)] == []
        dialog.logging.setChecked(True)
        assert said == [], "turning the log on put a box on the screen"
    finally:
        win.debug_action.setChecked(False)
        win.close()


def test_a_backend_status_is_a_badge_beside_the_label_not_part_of_it(app,
                                                                     tmp_path,
                                                                     monkeypatch):
    """Donald: the statuses need to look different from the label."""
    from wish.preferences import PreferencesDialog
    from wish.session import Session
    from wish.window import WishWindow

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    win = WishWindow(None, maps={}, session=Session(find=lambda pref=None: None))
    try:
        dialog = PreferencesDialog(win)
        for name in ("VICE", "Ultimate"):
            assert dialog.radios[name].text() == name
            assert dialog.badges[name].text() in ("answering", "not answering")
            # A frame and a ground of its own, so it cannot read as more label.
            assert "border" in dialog.badges[name].styleSheet()
            assert "background" in dialog.badges[name].styleSheet()
        assert dialog.unverified["Ultimate"].isVisibleTo(dialog)
    finally:
        win.close()
