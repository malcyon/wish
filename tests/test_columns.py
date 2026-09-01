"""The automapper's three columns are dragged by the user, and remembered.

The roster, the map and the Quest Log / Notes / Messages column used to be
three cells of a grid, two of them capped at a width chosen once for one
screen. `#162 (Let the user resize the Quest Log and roster columns)` made the
two dividers draggable and the widths remembered, and Donald settled both of
the questions it was opened on: *"a dragged width on a column should be
remembered when Wish opens again"*, and *"Sure, let the user drag it down to
nothing. As long as they can drag it back out when they do that."*

**The second sentence is what this file is mostly about.** A column dragged
shut has no width left to grab, so what the user aims at afterwards is the
divider; if that went with the column the panel would be gone for good and the
only way back would be editing the settings file by hand. The case that
matters is therefore not the drag but the *next start*: a zero read out of the
settings file, and a divider still in the window to pull it back out with.

**No assertion here is a pixel count.** Every one is a bound -- is this column
shut, is it wider than it was, is there a divider with a width at all -- or a
comparison between two measurements taken in the same run on the same machine.
Windows draws a wider font than this desk and a column's floor is made of
widgets, so a number measured here would be a claim about this desk and
nothing else.
"""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest

from automap.config import FILE, Settings
from automap.panel import ColumnSplitter
from automap.paths import config_dir

#: Which handle to drag, which column it opens and shuts, and which way to
#: drag it to shut that column. The map is between the two, so shutting the
#: roster is a drag to the left and shutting the reading column is a drag to
#: the right.
SIDES = {
    "the roster": (1, ColumnSplitter.ROSTER_AT, -1),
    "the Quest Log, Notes and Messages column": (2, ColumnSplitter.SIDE_AT, 1),
}


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _window(app, settings=None):
    """A shown window on the automapper tab, wide enough for its own columns.

    The width is asked of the window rather than typed in: its floor already
    holds every column's own minimum, so the floor plus the two side columns'
    default widths is room to spare on any machine, and a machine with a wider
    font gets a wider window rather than a squeezed one.
    """
    from wish.session import Session
    from wish.window import MAP_TAB, WishWindow

    win = WishWindow(None, maps={}, tab=MAP_TAB, settings=settings,
                     session=Session(find=lambda pref=None: None))
    win.show()
    floor = win.minimumSizeHint()
    win.resize(floor.width() + ColumnSplitter.ROSTER + ColumnSplitter.SIDE,
               floor.height())
    app.processEvents()
    return win


def _close(win):
    """Shut the window the way the program does, so the settings are written."""
    win.session.close()
    win.close()


def _drag(app, splitter, index: int, dx: int) -> None:
    """Drag divider `index` by `dx` pixels, the way a mouse does.

    `QSplitterHandle.moveSplitter` is protected and unreachable from Python,
    which is the good news: what is exercised here is the press, the move and
    the release, so a divider that is drawn but does not answer the mouse
    fails these tests.
    """
    handle = splitter.handle(index)
    middle = handle.rect().center()
    QTest.mousePress(handle, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, middle)
    QTest.mouseMove(handle, middle + QPoint(dx, 0))
    QTest.mouseRelease(handle, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier, middle + QPoint(dx, 0))
    app.processEvents()


def _write_settings(**values) -> None:
    """A settings file with these keys in it, as a hand-editing user's would be.

    `tests/conftest.py` points all four config variables at `tmp_path`, so
    this writes to a throwaway directory on every platform.
    """
    folder = config_dir()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / FILE).write_text(json.dumps(values, indent=1) + "\n",
                               encoding="utf-8")


# --- the defaults did not move ----------------------------------------------

def test_the_columns_open_at_the_widths_they_always_had(app):
    """Donald's ruling on `#168 (A character ready to level loses the Level up
    button, even with nothing running)`: *"This is a corner case. Leave it the
    way it is and let users resize it."*

    So the roster still opens at a card's width and the reading column still
    opens at its own, and what is new is that either can be dragged. Both are
    constants this code sets, not numbers measured off a font, which is why
    they can be asserted exactly.
    """
    win = _window(app)
    try:
        widths = win.map.columns.widths()
        assert widths[ColumnSplitter.ROSTER_AT] == ColumnSplitter.ROSTER
        assert widths[ColumnSplitter.SIDE_AT] == ColumnSplitter.SIDE
        assert widths[ColumnSplitter.MAP_AT] > 0
    finally:
        _close(win)


def test_a_wider_window_spends_the_extra_on_the_map(app):
    """The behaviour the two width caps used to give, kept by the stretch
    factors. Without it a wider window is blank paper beside a short note.

    Two measurements of the same window, so there is no constant here."""
    win = _window(app)
    try:
        before = win.map.columns.widths()
        win.resize(win.width() + 400, win.height())
        app.processEvents()
        after = win.map.columns.widths()
        assert after[ColumnSplitter.MAP_AT] > before[ColumnSplitter.MAP_AT]
        assert after[ColumnSplitter.ROSTER_AT] == before[ColumnSplitter.ROSTER_AT]
        assert after[ColumnSplitter.SIDE_AT] == before[ColumnSplitter.SIDE_AT]
    finally:
        _close(win)


# --- dragging ---------------------------------------------------------------

@pytest.mark.parametrize("what", sorted(SIDES))
def test_a_column_can_be_dragged_wider(app, what):
    """`#168`'s magic-user / fighter / cleric at levels 9, 8 and 7 draws
    `MU/F/C  L9/L8/L7  [Level up]` and, on Windows, no name at all. This is
    the fix Donald asked for: widen the column and the name comes back.
    """
    handle, column, _shut = SIDES[what]
    win = _window(app)
    try:
        splitter = win.map.columns.splitter
        before = splitter.sizes()[column]
        _drag(app, splitter, handle,
              -120 if column == ColumnSplitter.SIDE_AT else 120)
        assert splitter.sizes()[column] > before, f"{what} would not widen"
    finally:
        _close(win)


@pytest.mark.parametrize("what", sorted(SIDES))
def test_a_column_dragged_shut_can_be_dragged_back_out(app, what):
    """Donald: *"let the user drag it down to nothing. As long as they can
    drag it back out when they do that."* Both halves, in one window."""
    handle, column, shut = SIDES[what]
    win = _window(app)
    try:
        splitter = win.map.columns.splitter
        _drag(app, splitter, handle, shut * win.width())
        assert splitter.sizes()[column] == 0, f"{what} would not shut"
        _drag(app, splitter, handle, -shut * win.width())
        assert splitter.sizes()[column] > 0, f"{what} would not come back"
    finally:
        _close(win)


def test_the_map_cannot_be_dragged_shut(app):
    """Neither divider may leave the automapper tab with no map on it. The
    map gives way to its own floor and stops there."""
    win = _window(app)
    try:
        splitter = win.map.columns.splitter
        for handle, direction in ((1, 1), (2, -1)):
            _drag(app, splitter, handle, direction * win.width())
            assert splitter.sizes()[ColumnSplitter.MAP_AT] > 0
    finally:
        _close(win)


# --- and remembered ---------------------------------------------------------

def test_a_dragged_width_is_the_width_the_next_start_opens_at(app):
    """*"a dragged width on a column should be remembered when Wish opens
    again."*

    Two windows in one run, the second built from the settings file the first
    wrote. The assertion compares them with each other, so nothing here is a
    measurement of this machine.
    """
    win = _window(app, Settings.load())
    try:
        splitter = win.map.columns.splitter
        was = splitter.sizes()
        _drag(app, splitter, 1, 120)
        dragged = splitter.sizes()
        assert dragged != was, "the drag changed nothing, so nothing is proven"
    finally:
        _close(win)

    again = Settings.load()
    assert again.automap_columns == dragged, "the file did not keep the drag"
    second = _window(app, again)
    try:
        assert second.map.columns.widths() == dragged
    finally:
        _close(second)


def test_a_window_resize_does_not_overwrite_a_dragged_width(app):
    """A column squeezed by a window that is briefly too narrow is not a width
    anybody chose, and writing it back is how a preference goes missing with
    nobody having touched it. Only a drag is recorded.
    """
    win = _window(app, Settings.load())
    try:
        splitter = win.map.columns.splitter
        _drag(app, splitter, 2, -120)
        dragged = splitter.sizes()
        win.resize(win.minimumSizeHint().width(), win.height())
        app.processEvents()
        assert splitter.sizes() != dragged, "the window was not squeezed at all"
    finally:
        _close(win)
    assert Settings.load().automap_columns == dragged


@pytest.mark.parametrize("what", sorted(SIDES))
def test_a_column_left_shut_still_has_a_divider_on_a_fresh_start(app, what):
    """**The case where a user loses a panel for good**, and the reason
    `#162` needed more than a bare `QSplitter`.

    A width of zero in the settings file is legitimate -- Donald allowed the
    column to be dragged shut -- so the window opens with nothing of that
    column to grab. What has to be there instead is the divider, on the first
    frame, before the user has done anything. If it is not, the panel is gone
    and the way back is editing JSON by hand.

    Three things are asked of it, and each is a different way of losing it:

    * it is **shown**. A shut column restored by hiding the pane takes its
      divider with it -- measured, `isVisible()` goes false and the handle
      keeps a stale position;
    * it is **inside the window**. Qt gives a handle a two-pixel grab margin
      either side, so a divider narrower than that margin sits partly outside
      the splitter at a shut edge column -- at the style's own width it draws
      at `x = -2` and half of it is off the window;
    * it **answers the mouse**, which is the only one that settles the
      question, and is a press, a move and a release rather than a call to
      anything private.

    Written the long way round, through a real drag and a real close, so what
    is read back is a file the program itself wrote.
    """
    handle_at, column, shut = SIDES[what]
    win = _window(app, Settings.load())
    try:
        splitter = win.map.columns.splitter
        _drag(app, splitter, handle_at, shut * win.width())
        assert splitter.sizes()[column] == 0
    finally:
        _close(win)

    remembered = Settings.load()
    assert remembered.automap_columns[column] == 0, (
        f"{what} was dragged shut and not remembered as shut")

    fresh = _window(app, remembered)
    try:
        splitter = fresh.map.columns.splitter
        assert splitter.sizes()[column] == 0
        handle = splitter.handle(handle_at)
        assert handle.isVisible(), f"no divider left on {what}"
        assert splitter.rect().contains(handle.geometry()), (
            f"the divider on {what} is drawn partly outside the window: "
            f"{handle.geometry()} in {splitter.rect()}")
        _drag(app, splitter, handle_at, -shut * fresh.width())
        assert splitter.sizes()[column] > 0, (
            f"{what} was left shut and could not be dragged back out")
    finally:
        _close(fresh)


# --- a settings file somebody has edited ------------------------------------

#: Every shape of nonsense a hand-edited file can hold, and the shape a future
#: layout change would leave behind. `None` is the ordinary first run.
NONSENSE = {
    "nothing remembered": None,
    "a negative width": [-1, 900, 460],
    "a width past Qt's ceiling": [220, 900, 16777216],
    "a width that is not a number": [220, "wide", 460],
    "a fractional width": [220.5, 900, 460],
    "true and false": [True, False, True],
    "a row from another layout": [220, 900],
    "not a row at all": {"roster": 220},
    "a string": "220 900 460",
}


@pytest.mark.parametrize("what", sorted(NONSENSE))
def test_a_settings_file_nobody_can_use_reads_as_no_choice_at_all(what):
    """The whole row is refused rather than mended: a mended row is three
    widths of which one is somebody's and two are ours, and a window laid out
    from that is harder to explain than one at its defaults."""
    settings = Settings(automap_columns=NONSENSE[what])
    assert settings.column_widths(ColumnSplitter.COLUMNS) is None


@pytest.mark.parametrize("what", sorted(NONSENSE))
def test_a_settings_file_nobody_can_use_still_opens_a_usable_window(app, what):
    """And the outcome a user cares about, rather than the return value: the
    columns are the ones they would have got on a first run, and both dividers
    still answer the mouse."""
    _write_settings(automap_columns=NONSENSE[what])
    win = _window(app, Settings.load())
    try:
        widths = win.map.columns.widths()
        assert widths[ColumnSplitter.ROSTER_AT] == ColumnSplitter.ROSTER
        assert widths[ColumnSplitter.SIDE_AT] == ColumnSplitter.SIDE
        assert widths[ColumnSplitter.MAP_AT] > 0
        splitter = win.map.columns.splitter
        for handle in (1, 2):
            assert splitter.handle(handle).width() > 0
    finally:
        _close(win)


def test_a_settings_file_that_will_not_parse_at_all_opens_a_usable_window(app):
    """`automap/config.py` already treats an unreadable or half-written file
    as "no settings yet" rather than as an error, which is the behaviour this
    wants. Asserted here because the column widths are the first setting whose
    absence would show up as a window shape rather than as a checkbox.
    """
    folder = config_dir()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / FILE).write_text('{"automap_columns": [220, 900,',
                               encoding="utf-8")
    win = _window(app, Settings.load())
    try:
        widths = win.map.columns.widths()
        assert widths[ColumnSplitter.ROSTER_AT] == ColumnSplitter.ROSTER
        assert widths[ColumnSplitter.SIDE_AT] == ColumnSplitter.SIDE
    finally:
        _close(win)
