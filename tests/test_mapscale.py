"""The area map scales to the room it is given, so the window can be small.

Donald's Windows build opened taller than his screen and would not shrink: 16
squares at `render.CELL` plus the margins is 596px, and that was a hard floor
under the map, under the automap tab, and so under the whole window. The map
draws at `CELL` where there is room and shrinks to `render.CELL_MIN` where
there is not; the floor is what the window's minimum now rests on.

Everything the canvas answers -- what a click hits, what a tooltip describes,
where a note popover hangs -- is derived from the same cell the paint used, so
the tests that matter here are the ones that scale the canvas and then ask.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QRect
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

from automap import paths
from automap.render import CELL, CELL_MIN, MARGIN
from automap.state import AutomapState
from automap.window import MapCanvas
from goldbox.geo import GRID

#: The screen the whole window has to fit: a 1280x720 laptop, which is what
#: Donald asked for in round five of #43. It was 1280x760 -- a 1280x800 panel
#: with a task bar taken off it -- and forty pixels of that were slack.
SMALL = QRect(0, 0, 1280, 720)


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def canvas(app, side: int) -> MapCanvas:
    """A canvas of a given square size, with nothing to draw."""
    c = MapCanvas(AutomapState())
    c.setMinimumSize(1, 1)              # the layout's floor is not the test's
    c.resize(side, side)
    return c


def square(side: int) -> int:
    """The size a canvas has to be for one cell of `side`."""
    return GRID * side + MARGIN * 2


# --- the cell follows the room ----------------------------------------------

def test_a_full_size_canvas_still_draws_the_full_size_cell(app):
    """Nothing changes where there is room: 34 is what everything else was
    tuned against."""
    assert canvas(app, square(CELL)).cell == CELL


def test_the_cell_shrinks_and_grows_back_with_the_canvas(app):
    c = canvas(app, square(CELL))
    assert c.cell == CELL
    c.resize(square(24), square(24))
    assert c.cell == 24
    c.resize(square(CELL_MIN), square(CELL_MIN))
    assert c.cell == CELL_MIN
    c.resize(square(CELL), square(CELL))
    assert c.cell == CELL, "a canvas given its room back draws at full size"


def test_the_cell_stops_at_the_floor_and_at_the_full_size(app):
    """The floor is the whole point of the exercise; the ceiling is so a
    window nobody will ever open does not get a 60px cell."""
    assert canvas(app, 60).cell == CELL_MIN
    assert canvas(app, 4000).cell == CELL


def test_the_grid_is_square_and_centred_in_whatever_room_there_is(app):
    """A canvas wider than it is tall spends the difference on paper. The
    cell comes off the short side, or the map runs off the bottom."""
    c = canvas(app, square(CELL))
    c.resize(square(CELL) + 200, square(24))
    assert c.cell == 24
    ox, oy = c.origin
    assert ox == (c.width() - GRID * 24) // 2
    assert oy == MARGIN
    assert ox > oy


# --- and everything the canvas answers follows the cell ----------------------

@pytest.mark.parametrize("cell", [CELL, 27, CELL_MIN])
def test_a_click_lands_on_the_right_square_at_any_cell_size(app, cell):
    """The one that would go wrong silently. `square_at` used the module's
    fixed `CELL`, so at any other size a click landed on a square the player
    was not pointing at -- and so did the tooltip and the note popover."""
    c = canvas(app, square(cell))
    assert c.cell == cell
    ox, oy = c.origin
    for x, y in [(0, 0), (3, 4), (GRID - 1, GRID - 1)]:
        middle = (ox + x * cell + cell / 2, oy + y * cell + cell / 2)
        assert c.square_at(*middle) == (x, y)
        # Just inside the square's own top-left corner, and just outside it.
        assert c.square_at(ox + x * cell + 1, oy + y * cell + 1) == (x, y)
    assert c.square_at(ox - 1, oy + 1) is None
    assert c.square_at(ox + GRID * cell + 1, oy + 1) is None


def test_the_note_popover_hangs_off_the_square_it_is_editing(app):
    """`edit_note` puts the popover at the square's bottom-left corner, which
    is not `MARGIN + y * CELL` once the cell is not `CELL`."""
    c = canvas(app, square(CELL_MIN))
    ox, oy = c.origin
    corner = c.corner_of(3, 4)
    assert (corner.x(), corner.y()) == (ox + 3 * CELL_MIN, oy + 5 * CELL_MIN)


def test_the_note_marker_keeps_its_share_of_the_square():
    """A fixed 22px marker in a 20px cell is not a corner marker, it is the
    square -- and it would hide the wall the map is drawn for."""
    from automap.notes import Note
    from automap.render import NOTE_INSET, NOTE_SIZE, Glyph, note_primitives

    def marker(cell):
        (glyph,) = [p for p in note_primitives({(2, 3): [Note("x", "danger")]},
                                               cell, MARGIN)
                    if isinstance(p, Glyph)]
        return glyph

    assert marker(CELL).size == NOTE_SIZE       # unchanged at full size
    small = marker(CELL_MIN)
    assert small.size < CELL_MIN - NOTE_INSET
    assert small.size == pytest.approx(NOTE_SIZE * CELL_MIN / CELL)


def test_a_fight_does_not_put_the_floor_back(app):
    """The two canvases share a stack, and a stack is as tall as its tallest
    page whichever page is showing. A combat canvas whose minimum was the cell
    the fight asked for put a 600px floor back under the window the moment one
    started."""
    from gamedata import synthetic_arena

    from automap import combat
    from automap.target import MemoryTarget
    from automap.window import CombatCanvas

    c = CombatCanvas()
    c.show_battle(combat.read_battle(MemoryTarget(synthetic_arena())))
    _, _, w, h = c.box
    assert c.minimumHeight() == h * combat.CELL_MIN + combat.MARGIN * 2
    assert c.minimumHeight() < square(CELL_MIN)
    c.resize(c.sizeHint())
    assert c.drawn_cell == c.cell, "the room it asked for is the cell it wants"
    c.resize(c.minimumSize())
    assert c.drawn_cell == combat.CELL_MIN


# --- and the window it was all for -------------------------------------------

def _floor(tmp_path, monkeypatch, save=None):
    """The whole window's minimum, built somewhere with no settings file.

    `save` is the path to a saved game, or None for a window with nothing
    open. The two are not the same measurement and #63 is the record of why:
    `EditorWindow._adopt` runs only when a save is opened, and `_size_roster`
    with it, so a window built with None has never seen the roster's real
    column widths or the character sheet's real field widths.

    The save may be `gamedata.synthetic_party`'s, which is why the loaded case
    runs where there are no disks (#70).

    **Two Qt traps live here, and both make a working change look broken.**
    Each cost a prototype run during #71 before it was understood:

    * `EditorWindow.showEvent` calls `_size_roster` once, *after* the window
      is shown. Anything set on the roster before `show()` is overwritten, so
      a change applied to the live widget does nothing at all and reads as the
      idea being wrong rather than the timing.
    * `QLayout.activate()` pins a top-level window's `minimumSize` from the
      layout and does not un-pin it. After shrinking a child's minimum,
      `minimumSizeHint()` keeps answering the old, larger number until the
      window is told `setMinimumSize(0, 0)` and the layout is re-activated --
      so the measurement says the fix failed while the fix is working.
    """
    from wish.session import Session
    from wish.window import WishWindow

    empty = tmp_path / "empty-home"
    empty.mkdir(exist_ok=True)
    monkeypatch.setattr(paths, "_home", lambda: empty)
    monkeypatch.chdir(empty)

    win = WishWindow(save, maps={}, session=Session(find=lambda pref=None: None))
    floor = win.minimumSizeHint()
    win.close()
    return floor


def _floors(app, tmp_path, monkeypatch, save=None, fonts=(0, 3)):
    """`_floor` at each of several UI font sizes, base font restored after."""
    base = app.font()
    try:
        out = []
        for extra in fonts:
            bigger = QFont(base)
            bigger.setPointSizeF(base.pointSizeF() + extra)
            app.setFont(bigger)
            out.append(_floor(tmp_path, monkeypatch, save))
        return out
    finally:
        app.setFont(base)


def test_the_window_can_be_made_short_enough_for_a_small_laptop(app, tmp_path,
                                                               monkeypatch):
    """The bug, at the top: the window could not be made small enough for the
    screen it was on, whatever the positioning did about it. Kept under its
    old name, which is the one issue #41 asks for.

    The height went first, and the width followed: Windows CI answered
    `QSize(1546, 618)` where Linux answered `(1071, 662)`, because every
    column that was sized by its text grew with Windows' wider UI font. A
    1546px floor still fits Donald's 1920px desktop, which is why it is not
    what he reported, but it does not fit a 1366x768 laptop -- and `SMALL` is
    narrower than one of those, so passing here passes there (#41).
    """
    floor = _floor(tmp_path, monkeypatch)
    assert floor.height() <= SMALL.height()
    assert floor.width() <= SMALL.width()


def test_the_windows_minimum_does_not_follow_the_ui_font(app, tmp_path,
                                                         monkeypatch):
    """And the real test, because a number measured on Linux says nothing
    about Windows: the floor has to stop tracking the font.

    Three points of extra font used to buy 144px of minimum width, which is
    the mechanism that made Windows 475px worse than Linux. What is left is
    the map's own floor, the roster's fixed cards and the panels' caps, and
    none of those is text.
    """
    base = app.font()
    try:
        widths = []
        for extra in (0, 3):
            bigger = QFont(base)
            bigger.setPointSizeF(base.pointSizeF() + extra)
            app.setFont(bigger)
            widths.append(_floor(tmp_path, monkeypatch).width())
    finally:
        app.setFont(base)
    assert widths[1] == widths[0], "the minimum width grew with the font"


#: What the two states actually measure here, so the numbers below are numbers
#: rather than an opinion. `gamedata.synthetic_party` is the loaded one: six
#: characters of the widest shape the record and Pool of Radiance's own tables
#: allow.
#:
#: | UI font | empty | loaded, before #71 | loaded, now | the roster in it |
#: |---|---|---|---|---|
#: | base   | 836 x 662 | 1093 x 662 | **948 x 662** | 440 |
#: | +3pt   | 836 x 702 | 1270 x 702 | **948 x 702** | 440 |
#: | +6pt   | 836 x 749 | 1449 x 749 | **948 x 749** | 440 |
#: | +10pt  | 836 x 805 | 1672 x 805 | **948 x 805** | 440 |
#:
#: The roster was the whole of the slope: 587, 764, 941 and 1164 at those four
#: fonts, because its minimum was `header.length()` -- the width of the names,
#: races and classes it happened to be holding. It is a constant now
#: (`editor/rosterview.py`), and 948 is that constant plus Character's own cap
#: of 480 plus 24 of layout margins and spacing plus 4 of window frame, none of
#: which is measured from a string.
#:
#: The height still follows the font through the window's own chrome, which is
#: the two tests below and is not this.


def _heights(app, tmp_path, monkeypatch, fonts=(0, 3, 6, 10)):
    """The window's floor, the automapper page's floor and the chrome's, at
    each of several UI font sizes. Base font restored afterwards.

    The three are one measurement because they are one sum: the window's
    minimum height is the taller of its two pages plus the menu bar, the tab
    bar and the status bar around them. Splitting the answer is what says
    which half of it a font moved.
    """
    from wish.session import Session
    from wish.window import WishWindow

    empty = tmp_path / "empty-home"
    empty.mkdir(exist_ok=True)
    monkeypatch.setattr(paths, "_home", lambda: empty)
    monkeypatch.chdir(empty)

    base = app.font()
    try:
        out = []
        for extra in fonts:
            bigger = QFont(base)
            bigger.setPointSizeF(base.pointSizeF() + extra)
            app.setFont(bigger)
            win = WishWindow(None, maps={},
                             session=Session(find=lambda pref=None: None))
            chrome = sum(w.minimumSizeHint().height()
                         for w in (win.menuBar(), win.tabs.tabBar(),
                                   win.statusBar()))
            out.append((win.minimumSizeHint().height(),
                        win.map.minimumSizeHint().height(), chrome))
            win.close()
        return out
    finally:
        app.setFont(base)


def test_the_automapper_pages_floor_does_not_follow_the_ui_font(
        app, tmp_path, monkeypatch):
    """#77, and the height twin of the width test above.

    The window's minimum *height* was 662 at the base font and 805 at ten
    points more, so a user who raised the UI font three points -- an ordinary
    accessibility choice -- could not fit the window on a 1366x768 panel. Of
    the 143px, 90 were the automapper page: the map canvas's own floor is
    `CELL_MIN` arithmetic and does not move, but the action bar under it, the
    Fast Travel row under that and the bottom strip were each as tall as their
    own font metrics, in a layout that does not scroll.

    Each of those three now caps its `minimumSizeHint` height at a constant
    (`ActionBar.SHORT`, `WarpBar.SHORT`, `BottomStrip.SHORT`), the way #41
    capped the widths, so the page's floor is 580 at every UI font this
    machine can be made to draw -- 580, 605, 635 and 670 before.

    **What is asserted is that the floor stops growing, not that it is the
    same at every font.** Those are the same statement only on a machine whose
    base font is already large enough to reach the caps, and this one's is:
    580 at +0 here, where CI's Linux measures 561 and Windows 551 and both
    climb to their cap a few points later. The first version of this test
    asserted equality across all four fonts, passed here, and went red on both
    CI platforms -- the caps are constants, so a smaller base font sits under
    them and rises until it meets them. The cap is doing its job in all three
    cases; only the machine it was written on could not see the climb.

    So: non-decreasing, and flat by +6pt. Without the caps this machine's
    floor runs 580, 605, 635, 670 and the last two differ, which is what makes
    this bite.

    The roster panel and the notes/commissions/messages column are not capped.
    They do follow the font -- 89 to 132 and 281 to 410 between +0 and +24 --
    and neither comes near the map column's 514, so neither is in this
    number. If one ever overtakes it this test goes red, which is the right
    way round.
    """
    fonts = (0, 3, 6, 10)
    pages = [page for _win, page, _chrome
             in _heights(app, tmp_path, monkeypatch, fonts)]
    seen = dict(zip(fonts, pages))
    assert pages == sorted(pages), (
        f"the automapper page's floor moved about with the font: {seen}")
    assert pages[-1] == pages[-2], (
        f"the automapper page's floor was still following the font at the "
        f"largest sizes, so the caps are not holding it: {seen}")


def test_what_is_left_following_the_font_is_the_windows_own_chrome(
        app, tmp_path, monkeypatch):
    """And the whole window, which still grows -- by exactly its chrome.

    A menu bar, a tab bar and a status bar are three rows of text, and a user
    who asks for a larger UI font is asking for those to be larger too;
    capping them would clip `File`. So the window's floor is not a constant
    the way its width is, and this is the assertion that says what the
    remainder is made of: every pixel the floor moves is one of those three.

    Measured here, empty window: 662, 677, 694, 707 and 715 at +0, +3, +6, +8
    and +10, where before #77 it was 662, 702, 749, 782 and 805. The 720-high
    screen is cleared to about ten points of extra font instead of failing at
    six.

    **The numbers are this machine's and so was the first version of this
    assertion**, which required the remainder to be identical at every font
    and went red on both CI platforms for the reason its sibling above
    explains: a smaller base font sits under the caps and climbs to meet them,
    so the remainder grows until it settles. What is true wherever it runs is
    that it *does* settle -- once the caps hold the page, every further pixel
    the window's floor gains is one its chrome gained too.

    Above roughly +13 the *editor* page overtakes the automapper page and
    starts setting the height itself (378 to 630 between +0 and +16). That is
    a different page and a different issue; the fonts here stop below it.
    """
    fonts = (0, 3, 6, 10)
    parts = _heights(app, tmp_path, monkeypatch, fonts)
    slack = [window - chrome for window, _page, chrome in parts]
    seen = dict(zip(fonts, parts))
    assert slack == sorted(slack), (
        "the window's floor moved about against its menu bar, tab bar and "
        f"status bar: {seen}")
    assert slack[-1] == slack[-2], (
        "the window's floor was still growing by more than its menu bar, tab "
        f"bar and status bar at the largest sizes: {seen}")


def test_the_window_still_fits_the_laptop_with_a_save_open(app, tmp_path,
                                                           monkeypatch):
    """And with a character on screen, which is the case `_floor(None)` above
    has never measured -- #63.

    Opening a save is what runs `EditorWindow._adopt`, and `_size_roster` with
    it: the roster's five columns get their real widths, and none of them were
    in the 836 the empty window answers.

    The party is synthetic, so this runs on a machine with no game (#70) --
    and it is the *widest* party rather than a plausible one, because a floor
    measured from six-letter names is true of nothing.

    **An expected failure twice over before #71 closed it.** Round eight of
    #43 turned it into a real assertion on a local measurement of 1270 against
    1280 -- ten pixels -- and CI answered 1308 on Linux and 1447 on Windows at
    the *base* font, so it went back to being expected to fail. Ten pixels was
    never a margin; it was the width of a different renderer's idea of the same
    string, and no measurement taken on this machine could have told anyone
    that.

    What makes it an assertion again is that the number it measures is no
    longer a font metric. The roster gives up width instead of demanding it,
    and its floor is a constant, so the whole window's floor is 948 at every UI
    font this machine can be made to draw -- 332px of margin under the screen
    rather than ten. The sibling below is the test that says so directly.

    Both axes are checked at all four fonts. The height used to be checked at
    two, because 720 did not hold this window above +3pt -- that was #77, and
    #77 has since capped the automapper page's floor, so +6pt and +10pt now
    fit and are asserted here rather than described in a comment. That is the
    guarantee #77 was opened for; without these rows nothing in CI compares
    the window against the screen at a raised font, and a change to the menu,
    tab or status bar could put it back over 720 with everything green.

    The width at +6pt and +10pt is what the roster change touched, it was 1449
    and 1672 before, and without those two rows this test cannot go red on a
    Linux machine at all -- which is how it came to be an expected failure
    that CI disagreed with.
    """
    from gamedata import synthetic_save

    save = str(synthetic_save(tmp_path))
    fonts = (0, 3, 6, 10)
    floors = _floors(app, tmp_path, monkeypatch, save, fonts=fonts)
    for extra, floor in zip(fonts, floors):
        assert floor.width() <= SMALL.width(), f"+{extra}pt"
    for extra, floor in zip(fonts, floors):
        assert floor.height() <= SMALL.height(), f"+{extra}pt"


def test_the_windows_minimum_does_not_follow_the_ui_font_with_a_save_open(
        app, tmp_path, monkeypatch):
    """#41's guarantee, re-asserted against the state that governs a session.

    `test_the_windows_minimum_does_not_follow_the_ui_font` above is true of
    the window it measures and never covered this one -- the roster is empty
    there, and the roster was the thing that followed the font. #63 is the
    record of why the empty window was never enough.

    Ten points of extra UI font and not three, because Windows' base font
    measures here like six to ten points more than 9pt, and three points was
    where the old numbers still looked survivable: 1093, 1270, 1449 and 1672 at
    +0, +3, +6 and +10 before this, and 948 at all four now.

    An equality and not a tolerance. Every widget left in the header is held to
    an explicit constant, so there is nothing in the answer that a font could
    move by a pixel; if these two ever differ at all, something in the header
    has gone back to measuring a string.
    """
    from gamedata import synthetic_save

    save = str(synthetic_save(tmp_path))
    fonts = (0, 3, 6, 10)
    widths = [f.width()
              for f in _floors(app, tmp_path, monkeypatch, save, fonts=fonts)]
    assert widths == [widths[0]] * len(fonts), (
        f"the minimum width grew with the font: {dict(zip(fonts, widths))}")


def test_the_players_own_party_is_no_wider_than_the_synthetic_one(app, tmp_path,
                                                                  monkeypatch):
    """The disk-backed half, and what makes the synthetic party evidence.

    The synthetic one is built to be the widest the format allows, so a real
    party must come in under it at every font. If the two ever disagree it is
    the synthetic party that has stopped being representative, and it is the
    one to fix -- not this assertion.

    Kept on the disks on purpose: it is the corroborator, not the guarantee.
    The guarantee is the two expected failures above, and those run in CI.
    """
    from gamedata import disk_path, synthetic_save

    src = disk_path("PORSAVE11")
    if src is None:
        pytest.skip("needs the save disks")
    real = tmp_path / "PORSAVE11.D64"
    real.write_bytes(src.read_bytes())

    theirs = _floors(app, tmp_path, monkeypatch, str(real))
    ours = _floors(app, tmp_path, monkeypatch, str(synthetic_save(tmp_path)))
    for extra, mine, yours in zip((0, 3), ours, theirs):
        assert yours.width() <= mine.width(), (
            f"+{extra}pt: a real party is wider than the synthetic one, "
            f"{yours.width()} against {mine.width()}")
        assert yours.height() <= mine.height(), f"+{extra}pt"
    # And the line #43 round five drew, on the party a player really has:
    # 1027x662 and 1124x702 here.
    for extra, floor in zip((0, 3), theirs):
        assert floor.width() <= SMALL.width(), f"+{extra}pt"
        assert floor.height() <= SMALL.height(), f"+{extra}pt"
