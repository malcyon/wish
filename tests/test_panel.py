"""What a roster card can hold in the width the roster column gives it.

The card's top row used to carry six things -- the name, the condition badges,
the classes, the level, the quickfight badge and the Level up button -- inside
a column capped at 220px, 206 of it once the scrollbar is out. Whatever was
rightmost fell off the end, with no ellipsis and nothing to say the row went
on: a three-class character with four spells running read `MU/C`
(`#161 (A roster card loses a character's classes and its Level up button once
four condition badges are lit)`), and a character who had earned a level got
`Lev`, 32 of the button's 80 pixels, before a single badge was lit
(`#168 (A character ready to level loses the Level up button, even with
nothing running)`).

Donald settled both. The badges and the quickfight badge moved down to the
readied line, right-aligned, where the words give way and the badges do not;
the name became the one thing on the top row that shortens, because the Level
up button is gone the moment it is pressed and half a name for a minute beats
half a control.

**Nothing here asserts a pixel count.** Every measurement is either taken
twice in the same run and compared, or is the question a player would ask --
is the whole of this drawn? -- put to `QWidget.visibleRegion()`, which is what
the column's edge actually cuts.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtGui import QFont

from automap import live, paths

#: Three classes, all of them over the next threshold, so
#: `CharacterCard.ready_to_level` answers with all three and the Level up
#: button is on the card. The synthetic party had nobody who could level,
#: which is how #168 stayed unseen; see `tests/gamedata.WIDEST_EXPERIENCE`.
READY = tuple(live.ClassProgress(name, 8, 100_000, 0.5, 90_000)
              for name in ("magic-user", "cleric", "thief"))
#: The same three, none of them ready.
NOT_READY = tuple(live.ClassProgress(name, 8, 100_000, 0.5, 200_000)
                  for name in ("magic-user", "cleric", "thief"))

#: The widest realistic readied list, from `#41 (The window's minimum width is
#: the sum of the widest strings its panels hold)`.
READIED = ("BANDED MAIL +1", "SHIELD +2", "LONG SWORD +3")

#: Every badge a card can show at once: dead, drained, and the five spell
#: groups a living character can have running.
ALL_EFFECTS = (39, 1, 8, 25, 38)


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _character(**kw):
    fields = dict(slot=0, name="LADY KATHERINE", classes=READY, level=8,
                  armour_class=-3, thac0=5, hp=41, hp_max=99,
                  experience=100_000)
    fields.update(kw)
    return live.Character(**fields)


def _effects(*ids):
    return tuple(live.Effect(slot=i, id=n, owner=0, duration=8, magnitude=0)
                 for i, n in enumerate(ids))


def _window(app, tmp_path, monkeypatch, party, extra=0.0):
    """A real window with `party` on the cards, laid out at the real width.

    The roster is fed from the emulator, so a window opened on a save leaves
    every card hidden -- `show_snapshot` is the call the poll makes and the
    one that tells the column how much width to ask for. The walk up the
    parents afterwards is the Qt trap `tests/test_mapscale.py` documents: a
    card is `visible=false` in the form, and showing it does not tell the
    layouts above that their cached sizes are stale.
    """
    from wish.session import Session
    from wish.window import MAP_TAB, WishWindow

    empty = tmp_path / "empty-home"
    empty.mkdir(exist_ok=True)
    monkeypatch.setattr(paths, "_home", lambda: empty)
    monkeypatch.chdir(empty)

    base = app.font()
    if extra:
        bigger = QFont(base)
        bigger.setPointSizeF(base.pointSizeF() + extra)
        app.setFont(bigger)
    win = WishWindow(None, maps={}, tab=MAP_TAB,
                     session=Session(find=lambda pref=None: None))
    win.show()
    app.processEvents()
    win.map.roster.show_snapshot(live.Snapshot(
        characters=tuple(party), effects=(), x=1, y=1, facing=0,
        clock_text="10:15", area_file="GEO04"))
    widget = win.map.roster.cards[0].frame
    while widget is not None:
        widget.updateGeometry()
        widget = widget.parentWidget()
    for _ in range(3):
        app.processEvents()
    return win, base


def _close(app, win, base):
    win.session.close()
    win.close()
    app.setFont(base)


def _drawn(widget) -> int:
    """How many pixels of this widget's width reach the screen.

    `visibleRegion()` is the clip the roster column's viewport applies, so
    this is the same question a player asks of the card: is the whole of it
    there? A widget cut off by the column answers with less than its width --
    the Level up button answered 32 of 80 -- and one that is not shown at all
    answers 0.
    """
    return widget.visibleRegion().boundingRect().width()


def _whole(widget) -> bool:
    return widget.isVisible() and _drawn(widget) == widget.width()


# --- #161: the badges no longer push anything off the row --------------------

def test_a_card_keeps_its_classes_its_level_and_its_button_with_every_badge(
        app, tmp_path, monkeypatch):
    """The bug, as a player meets it.

    You have buffed the party before a fight, so LADY KATHERINE -- magic-user,
    cleric and thief -- is blessed, hasted, warded and given extra strength.
    Her card read `MU/C`: her thief class gone, her level gone, the quickfight
    badge gone and the Level up button gone with them, and nothing on the card
    to say the row continued.

    Everything on the row is asserted whole, and so is every badge, because
    the badges moving somewhere they are cut off instead would pass a test
    that only looked at the classes.
    """
    who = _character(hp=0, levels_drained=2, quickfight=True,
                     readied=READIED, effects=_effects(*ALL_EFFECTS))
    win, base = _window(app, tmp_path, monkeypatch, [who])
    try:
        card = win.map.roster.cards[0]
        assert len(card.conditions.names) == len(ALL_EFFECTS) + 2
        assert card.klass.text() == "MU/C/T  L8"
        for widget, what in ((card.klass, "the classes and the level"),
                             (card.level_up, "the Level up button"),
                             (card.conditions, "the condition badges"),
                             (card.quickfight, "the quickfight badge")):
            assert _whole(widget), (
                f"{what}: {_drawn(widget)} of {widget.width()}px drawn "
                f"inside a {win.ui.automap_roster_scroll.viewport().width()}px "
                f"column")
    finally:
        _close(app, win, base)


def test_the_readied_line_gives_way_to_the_badges_and_not_the_other_way(
        app, tmp_path, monkeypatch):
    """Donald's ruling on which loses when the two collide: *"I would rather
    see active effects than readied items. That is a fine trade-off as far as
    space goes."*

    A full hand and every badge lit. The badges are drawn whole; the readied
    line takes the remainder, shortens with an ellipsis if the remainder is
    not enough, and the whole list stays in the card's tooltip either way.
    """
    who = _character(hp=0, levels_drained=2, quickfight=True,
                     readied=READIED, effects=_effects(*ALL_EFFECTS))
    win, base = _window(app, tmp_path, monkeypatch, [who])
    try:
        card = win.map.roster.cards[0]
        assert _whole(card.conditions) and _whole(card.quickfight)
        drawn = card.readied.elided_text()
        assert drawn == card.readied.text() or drawn.endswith("…"), drawn
        metrics = card.readied.fontMetrics()
        assert (metrics.horizontalAdvance(drawn)
                <= card.readied.contentsRect().width())
        for item in READIED:
            assert item in card.frame.toolTip()
    finally:
        _close(app, win, base)


def test_the_badges_on_the_readied_line_cost_the_card_no_height(
        app, tmp_path, monkeypatch):
    """Eight cards in a column, each a row of badges taller, is the shape of
    `#135 (The automapper's roster column does not scroll, so a full party
    puts a 944px floor under the window)`. The badges moved down a line; they
    did not add one, and they must not put one under the window either.

    Two things, and the second is the one that would go wrong. Lighting every
    badge does not make the card taller -- but the row they now share is the
    readied line, whose whole point is that it asks the layout for no height
    at all (`ReadiedLabel.SHORT`), and a badge row that insisted on its own
    13px would hand that back eight times over. So the control is the same
    card with the badge rows hidden: the card's floor has to be the same
    number either way.

    Every number here is measured twice in this run and compared, so none of
    them is this machine's.
    """
    bare = _character(readied=READIED)
    lit = _character(hp=0, levels_drained=2, quickfight=True, readied=READIED,
                     effects=_effects(*ALL_EFFECTS))
    win, base = _window(app, tmp_path, monkeypatch, [bare])
    try:
        card = win.map.roster.cards[0]
        before = (card.frame.sizeHint().height(),
                  card.frame.minimumSizeHint().height())
        card.show_character(lit)
        app.processEvents()
        assert (card.frame.sizeHint().height(),
                card.frame.minimumSizeHint().height()) == before, (
            "lighting every badge made the card taller")

        lit_floor = card.frame.minimumSizeHint().height()
        for row in (card.conditions, card.quickfight):
            row.setVisible(False)
        card.frame.updateGeometry()
        app.processEvents()
        assert card.frame.minimumSizeHint().height() == lit_floor, (
            f"the badge rows put {lit_floor - card.frame.minimumSizeHint().height()}"
            f"px under every card, which a party of eight multiplies by eight")
    finally:
        _close(app, win, base)


# --- #168: the Level up button is drawn whole --------------------------------

def test_a_character_ready_to_level_gets_the_whole_button(
        app, tmp_path, monkeypatch):
    """The bug on its own, with no badges anywhere near it: one of your party
    has earned a level, and where the button should be the card said `Lev`.

    Nothing is running and nothing is readied -- the plainest card there is.
    Checked at four font sizes, because the row this button sits on is wider
    at every one of them and a machine's base font is not this desk's.
    """
    for extra in (0, 3, 6, 10):
        win, base = _window(app, tmp_path, monkeypatch, [_character()],
                            extra=extra)
        try:
            card = win.map.roster.cards[0]
            assert card.ready == ("magic-user", "cleric", "thief")
            assert _whole(card.level_up), (
                f"+{extra}pt: {_drawn(card.level_up)} of "
                f"{card.level_up.width()}px of the Level up button drawn")
            assert _whole(card.klass), f"+{extra}pt: the classes were cut"
        finally:
            _close(app, win, base)


def test_the_name_is_what_gives_way_to_the_button(app, tmp_path, monkeypatch):
    """Donald's reasoning, which is what makes this the cheap side of the
    trade: *"The level up button will never be there for very long. It will be
    clicked as soon as it appears. So, cutting off the name for a little while
    is fine."*

    The same fifteen-letter name twice, in the same window: once on a
    character who has earned a level and once on one who has not. Both numbers
    come out of this run, so neither is this machine's.

    **The name pays first, up to everything it has** -- not "the name pays all
    of it". CI found the difference on Windows, where the button is 102px and
    the name had only 91 to give: it went to nothing and the classes covered
    the rest, which is the order `CardClassLabel` exists to enforce. Asserting
    the name alone covers the button is asserting that this desk's fonts leave
    it enough room to.
    """
    win, base = _window(app, tmp_path, monkeypatch, [_character()])
    try:
        card = win.map.roster.cards[0]
        with_button = card.name.width()
        assert _whole(card.level_up) and _whole(card.klass)
        drawn = card.name.elided_text()
        assert drawn == card.name.text() or drawn.endswith("…") or drawn == "", (
            f"the name drew {drawn!r}, which is neither whole, shortened, nor "
            f"given up entirely")

        card.show_character(_character(classes=NOT_READY))
        app.processEvents()
        assert not card.level_up.isVisible()
        gave = card.name.width() - with_button
        assert gave >= card.level_up.width() or with_button == 0, (
            f"the name label was {with_button}px wide beside the button and "
            f"{card.name.width()}px without it, against a button of "
            f"{card.level_up.width()}px -- it gave up {gave}px and still had "
            f"room to spare, so something other than the name gave way first")
    finally:
        _close(app, win, base)


def test_a_short_name_is_not_shortened_to_make_room(app, tmp_path,
                                                    monkeypatch):
    """The name gives way only when it has to. A three-letter name beside a
    Level up button is drawn as it was typed.

    If this fails, the top row has no room even for that, and the card needs
    more than a shortening -- which is worth seeing rather than asserting
    around.

    **A short name survives where a long one would not, and that is all this
    can claim.** A review of this file predicted the trap and CI then sprang
    it: on Windows the classes and the button leave less than `BOB`'s own
    width in a 206px row, so `BOB` *was* shortened and asserting otherwise was
    asserting this desk's font metrics. `#77` records that CI's Linux fonts
    run smaller than this desk's, which is why nobody expected the opposite.

    What is true everywhere is the ordering: the button is whole, and a
    three-letter name gives up no more than a fifteen-letter one would. Both
    numbers come out of this run.
    """
    for extra in (0, 3, 6, 10):
        win, base = _window(app, tmp_path, monkeypatch,
                            [_character(name="BOB")], extra=extra)
        try:
            card = win.map.roster.cards[0]
            assert _whole(card.level_up), (
                f"+{extra}pt: the Level up button is drawn "
                f"{_drawn(card.level_up)} of {card.level_up.width()}px")
            drawn = card.name.elided_text()
            room = card.name.contentsRect().width()
            wants = card.name.fontMetrics().horizontalAdvance("BOB")
            assert drawn == "BOB" or room < wants, (
                f"+{extra}pt: BOB drew as {drawn!r} in {room}px, and it only "
                f"needed {wants}px -- the name was shortened when there was "
                f"room for it")
        finally:
            _close(app, win, base)


def test_the_whole_row_survives_a_larger_ui_font(app, tmp_path, monkeypatch):
    """A machine whose UI font is bigger than this one -- Windows', or a user
    who raised it -- must not be back where the row was cut.

    The classes, the level and the button are asserted whole at each font
    rather than measured, because what a user cares about is whether the
    control is there, and a pixel count at +6pt is this desk's number.
    """
    for extra in (0, 3, 6, 10):
        who = _character(hp=0, levels_drained=2, quickfight=True,
                         readied=READIED, effects=_effects(*ALL_EFFECTS))
        win, base = _window(app, tmp_path, monkeypatch, [who], extra=extra)
        try:
            card = win.map.roster.cards[0]
            for widget, what in ((card.klass, "the classes and the level"),
                                 (card.level_up, "the Level up button"),
                                 (card.conditions, "the condition badges"),
                                 (card.quickfight, "the quickfight badge")):
                assert _whole(widget), (
                    f"+{extra}pt: {what} drawn {_drawn(widget)} of "
                    f"{widget.width()}px")
        finally:
            _close(app, win, base)


# --- the test party itself ---------------------------------------------------

def test_the_synthetic_party_has_characters_who_can_level():
    """The reason #168 went unseen, turned into a test.

    Every card-width measurement this project took was made with the widest
    thing on the card's top row absent, because `gamedata.synthetic_party`'s
    characters sit at level 1 with no experience and so can never train. A
    test party in which nobody can level cannot catch a fault in the control
    that levels them.
    """
    import gamedata

    from goldbox.d64 import D64
    from goldbox.levelup import ready_classes
    from goldbox.savegame import load_save

    _, save, _ = load_save(D64.from_bytes(gamedata.synthetic_party()))
    ready = [ready_classes(slot.record) for slot in save.characters]
    assert ready and all(ready), (
        f"nobody in the synthetic party can level: {ready}")


def test_the_classes_give_way_before_the_button_does(app, tmp_path,
                                                     monkeypatch):
    """CI found this on Windows, where every fix so far had been measured on
    one Linux desk: `the Level up button: 99 of 102px drawn inside a 220px
    column`, with the name already down to `LAD...`.

    The name yielding everything is enough here and was not enough there,
    because **the classes and the button alone are wider than the column** on
    a machine whose base font is wider. A plain `QLabel` cannot give way, so
    the button was what got cut -- which is `#168` again, on a platform the
    fix was never run on.

    Reproduced by widening the two the way a wider font does: a
    six-class character and a button asked for more room. The button must be
    whole and the classes must be the thing that shortened.

    No pixel count is asserted. The button being whole is the player's
    question, and the widths here are this machine's business.
    """
    win, base = _window(app, tmp_path, monkeypatch, [_character()])
    try:
        card = win.map.roster.cards[0]
        card.level_up.setMinimumWidth(card.level_up.width() + 40)
        card.klass.setText("MU/C/T/R/P/B  L18")
        for _ in range(3):
            app.processEvents()
        assert _whole(card.level_up), (
            f"the Level up button drawn {_drawn(card.level_up)} of "
            f"{card.level_up.width()}px -- the classes did not give way")
        assert card.klass.elided_text().endswith("…"), (
            "the classes were not shortened, so nothing gave way and the "
            "button must have been cut instead")
    finally:
        _close(app, win, base)
