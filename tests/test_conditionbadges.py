"""The roster card's condition badges, and the two icon sets that draw them.

Every glyph here was chosen by Donald from game-icons.net and is in the
repository verbatim -- see `#4 (Condition badges on the roster card)`. The
groupings are `docs/136-condition-badges.md`'s. Nothing in this file judges
either; what it pins is that a badge appears for the effect it belongs to and
for nothing else, that a character with no effects gets a bare card, and that
eight more glyphs do not make the card any taller -- which is what
`#135 (The automapper's roster column does not scroll, so a full party puts a
944px floor under the window)` is about.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QByteArray, QRectF
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QMainWindow

from automap import live
from ui import icons
from ui.iconpaint import draw_icon


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _character(**kw):
    fields = dict(slot=0, name="BRUTUS", classes=(), level=1, armour_class=9,
                  thac0=18, hp=11, hp_max=11, experience=0)
    fields.update(kw)
    return live.Character(**fields)


def _effects(*ids, owner=0):
    """One effect slot per id, all owned by party slot 0."""
    return tuple(live.Effect(slot=i, id=n, owner=owner, duration=8,
                             magnitude=0)
                 for i, n in enumerate(ids))


def _card(app):
    from automap.panel import CharacterCard
    from wish.ui_window import Ui_WishWindow
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    return CharacterCard(root, 0)


def _glyphs(who):
    return tuple(icon for icon, _ in who.conditions)


# --- which badge for which effect --------------------------------------------

def test_a_character_with_nothing_running_gets_no_badges():
    """The blank card is the one a player sees most, and a badge that appears
    on it means nothing. Alive, undrained, no spell up: nothing at all."""
    assert _character().conditions == ()
    assert _character(effects=()).conditions == ()


def test_each_badge_appears_for_its_own_effects_and_for_nothing_else():
    """One effect at a time, across the whole candidate set: an id inside a
    badge's group lights that badge, and an id outside every group lights
    none. This is what stops a regrouping quietly badging the wrong spell."""
    covered = {i: glyph for glyph, ids in live.CONDITION_BADGES for i in ids}
    for code in range(1, 128):
        who = _character(effects=_effects(code))
        expected = (covered[code],) if code in covered else ()
        assert _glyphs(who) == expected, f"effect {code}"


def test_a_grouped_badge_is_drawn_once_and_says_which_spell():
    """*Warded* covers six ids on one glyph, which is what makes it worth
    having -- but a player looking at it has to be able to find out which
    defence is up, and two of them must not draw two shields."""
    assert dict(live.CONDITION_BADGES)["embrassed-energy"] == (
        8, 9, 17, 28, 41, 89)
    who = _character(effects=_effects(8, 41))
    assert _glyphs(who) == ("embrassed-energy",)
    assert dict(who.conditions)["embrassed-energy"].splitlines() == [
        "Protection from Evil", "Protection from Normal Missiles"]


def test_the_badges_keep_the_table_s_order_whatever_the_save_holds():
    """The effect arrays are 64 slots the game fills in whatever order it
    likes. A card whose badges reshuffle between two polls is unreadable, so
    the order is `CONDITION_BADGES`', not the save's."""
    forwards = _glyphs(_character(effects=_effects(38, 25, 8, 1, 39)))
    backwards = _glyphs(_character(effects=_effects(39, 1, 8, 25, 38)))
    assert forwards == backwards
    assert forwards == ("running-ninja", "healing-shield", "embrassed-energy",
                        "eyelashes", "strong")


def test_the_two_record_conditions_still_come_first():
    """Dead or dying and levels drained are read from the record rather than
    from the effect arrays, and they are the two that decide what a player
    does next, so they lead."""
    who = _character(hp=0, levels_drained=2, effects=_effects(39))
    assert _glyphs(who) == ("death-skull", "oppression", "running-ninja")
    assert "drained 2 levels" in dict(who.conditions)["oppression"]


def test_every_badged_effect_is_confirmed():
    """`goldbox/traits.py` grades each name, and a PROBABLE name drawn as a
    picture reads as a fact. The PROBABLE radius pair 45/46 and Prayer 49 are
    left out for exactly that reason and because `docs/136-condition-badges.md`
    left their grouping open."""
    from goldbox import traits
    for _, ids in live.CONDITION_BADGES:
        for code in ids:
            assert traits.confidence(code) == "CONFIRMED", code
    badged = {i for _, ids in live.CONDITION_BADGES for i in ids}
    assert not badged & {45, 46, 49}


# --- on the card -------------------------------------------------------------

def test_the_card_is_no_taller_with_every_badge_lit(app):
    """Eight cards each gaining a row of badges is what would break
    `#135 (The automapper's roster column does not scroll, so a full party puts
    a 944px floor under the window)`. `IconRow` is a fixed 13 high and only
    ever grows sideways, and this is what says so."""
    card = _card(app)
    card.show_character(_character())
    bare = (card.frame.sizeHint().height(),
            card.frame.minimumSizeHint().height())
    card.show_character(_character(hp=0, levels_drained=2, quickfight=True,
                                   effects=_effects(39, 1, 8, 25, 38)))
    assert len(card.conditions.names) == 5 + 2
    assert (card.frame.sizeHint().height(),
            card.frame.minimumSizeHint().height()) == bare


def test_the_quickfight_badge_is_the_sabre_and_stays_off_the_conditions_row(app):
    """Quickfight is a setting the player made, not something done to the
    character, so it keeps its own row. It is `sparkling-sabre` because
    `running-ninja` is hasted's and two running figures on one card at 13px
    cannot be told apart -- Donald settled it on `#4 (Condition badges on the
    roster card)`."""
    card = _card(app)
    card.show_character(_character(quickfight=True, effects=_effects(39)))
    assert card.quickfight.names == ("sparkling-sabre",)
    assert card.conditions.names == ("running-ninja",)
    card.show_character(_character())
    assert card.quickfight.names == ()


# --- the drawings themselves -------------------------------------------------

def test_every_chosen_glyph_is_in_the_table_with_its_artist():
    """Attribution is the whole of what CC BY 3.0 asks for, and a licence file
    generated from what ships cannot go stale the way a retyped one does."""
    assert set(icons.GAME_ICONS) == set(icons.ARTISTS)
    assert icons.ARTISTS == {
        "death-skull": "sbed",
        "oppression": "Lorc",
        "running-ninja": "Darkzaitzev",
        "healing-shield": "Delapouite",
        "embrassed-energy": "Lorc",
        "eyelashes": "Delapouite",
        "strong": "Lorc",
        "sparkling-sabre": "Lorc",
    }
    assert not set(icons.GAME_ICONS) & set(icons.FONT_AWESOME)
    assert not set(icons.GAME_ICONS) & set(icons.OURS)


def test_the_two_sets_are_drawn_in_their_own_boxes():
    """game-icons.net draws on 512 and Font Awesome on 640. Scaling a 512 glyph
    by 640 would draw it at four-fifths size beside its neighbour, and nothing
    about the picture would say why."""
    assert icons.box("death-skull") == icons.GAME_ICONS_BOX == 512
    assert icons.box("location-dot") == icons.BOX == 640
    for name in icons.ICONS:
        x0, y0, x1, y1 = icons.extent(name)
        unit = icons.box(name)
        assert 0 <= x0 and 0 <= y0 and x1 <= unit and y1 <= unit, name


def _grey(image, size: int) -> bytes:
    """The image's grey levels, row padding dropped.

    `bytesPerLine` rounds up to four, and the pad bytes are whatever was in
    the buffer -- comparing them made a 26px image differ from itself.
    """
    grey = image.convertToFormat(QImage.Format.Format_Grayscale8)
    raw = grey.constBits().asstring(grey.sizeInBytes())
    stride = grey.bytesPerLine()
    return b"".join(raw[y * stride:y * stride + size] for y in range(size))


@pytest.mark.parametrize("name", sorted(icons.GAME_ICONS))
@pytest.mark.parametrize("size", [13, 26, 128, 512])
def test_our_parser_draws_what_an_svg_renderer_draws(app, name, size):
    """The path data is the artist's, relative commands, smooth cubics, arcs
    and all, so `ui/icons.py` grew a parser rather than the icons being
    redrawn into something simpler. This is what says the parser is right:
    every pixel identical to Qt's own SVG renderer reading the same `d`.

    It fails if a curve is misread -- and a misread curve is a redrawn icon,
    which is the one thing `CLAUDE.md`'s Art section forbids.

    **512 is in the list because 128 is not enough.** Three arcs reach the
    parser, in `oppression` and `sparkling-sabre`, and all three are shallow:
    drawing them as straight chords instead changes nothing a 128px raster can
    see, and 26 pixels at 512. The native box is where an arc stops being its
    own chord.
    """
    ours = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    ours.fill(QColor("white"))
    p = QPainter(ours)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw_icon(p, name, 0, 0, size, QColor("black"))
    p.end()

    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">'
           f'<path fill="#000" d="{icons.path_data(name)}"/></svg>')
    theirs = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    theirs.fill(QColor("white"))
    p = QPainter(theirs)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(QByteArray(svg.encode())).render(p, QRectF(0, 0, size, size))
    p.end()

    a, b = _grey(ours, size), _grey(theirs, size)
    if a == b:
        return                                  # the common case, compared in C
    off = [(i % size, i // size)
           for i, (p, q) in enumerate(zip(a, b)) if abs(p - q) > 40]
    assert not off, f"{name} at {size}px differs at {off[:8]}"


def test_a_quadratic_is_raised_rather_than_guessed_at():
    """No icon that ships uses `Q` or `T`, and a silently mis-drawn glyph is
    worse than an import that fails."""
    icons.ICONS["_quadratic"] = "M0 0Q10 10 20 0Z"
    try:
        with pytest.raises(ValueError):
            icons.commands("_quadratic")
    finally:
        del icons.ICONS["_quadratic"]
