"""The party list, and the one widget in the header that gives up width.

Everything else above the tabs is sized to the widest value its bytes can hold
and then pinned there, so a window narrower than the header wants was paid for
by Character: its two form columns were squeezed past their own minimums and
the right one drew on top of the left (#71). The roster is the one thing up
there that can lose width and still say something -- a name elides where a spin
box cannot -- so it is the one thing that does.

Three rules, and they are Donald's:

* above `ROSTER_MIN_WIDTH` the roster is exactly its five columns at their
  contents, as it has always been;
* below it `Name` absorbs the whole shortfall and elides, so `Race`, `Class`,
  `AC` and `HP` stay readable for as long as there is width for them;
* only when `Name` has given everything it has does the table scroll.

The rules say nothing about the case they did not anticipate: an ordinary
party's `natural` -- the five columns at their contents -- is *under*
`ROSTER_MIN_WIDTH`, so the constant forces the roster wider than its own
contents rather than narrower. The pixels that buys have to go somewhere, and
the second rule is what decides where: `Name` is the column that gives, in
both directions, so it is also the column that takes a surplus. It is the same
rule read the other way round, not a fourth one -- see `_share_width`.

`ROSTER_MIN_WIDTH` is a floor under the whole window as well, because
`_size_roster` hands it to `setMinimumWidth`: whatever the roster's minimum
is becomes a floor under the header, which does not scroll, and a minimum
taken from font metrics is a floor that follows the UI font -- #41's bug, and
the reason Windows CI once measured 1304 where Linux measured 1036.

`_size_roster` used to hand it `min(natural, ROSTER_MIN_WIDTH)`, believing
`natural` -- the five columns at their contents -- was always the larger of
the two, so `min` always picked the constant and the floor was
font-independent. That was false for an ordinary party: six characters
measure `natural` at 219 against the constant's 440, so `min` picked the
font-derived number instead, and the window's floor followed the UI font
again for the common case (#474). Letting the roster scroll instead of
setting any minimum fixed the arithmetic and broke the picture -- at the
window's new floor `Class`, `AC` and `HP` sat behind a horizontal scrollbar,
which Donald rejected (#504) -- so `_size_roster` hands the constant to
`setMinimumWidth` with no `min()`: font-independent by construction, and
every column stays visible at any width down to the floor.
"""

from __future__ import annotations

from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import QTableView

#: The column that gives. It is the widest of the five -- twenty bytes of name
#: against three digits of hit points -- and the only one whose value a reader
#: can still recognise from its first few characters.
NAME_COLUMN = 0

#: What the roster may be squeezed to, in pixels, at any font on any platform.
#: `_size_roster` hands it straight to `setMinimumWidth` whenever there are
#: rows, so it is a floor under the whole window.
#:
#: It is not derived by measuring what the four fixed columns need -- an
#: earlier version of this comment claimed `Race`, `Class`, `AC` and `HP` come
#: to 356px at the base font, and that number was never checked against a
#: real party: an ordinary six-character party's whole five columns, `Name`
#: included, measure 219px, nowhere near 356 (#474). 440 is a deliberately
#: round constant instead, wider than any real party's columns need, chosen
#: so it clears them comfortably rather than by a measured margin -- and
#: because it is a constant rather than anything measured from a party's own
#: text, the floor it sets does not move with the UI font.
#:
#: At a Windows-sized font -- which measures here like six to ten points more
#: than 9pt -- the four fixed columns can outgrow even a generous constant,
#: and that is the third rule working (module docstring) rather than a reason
#: to raise this number: raising it to cover the worst font would put the
#: window's floor back over a 1366px-wide screen.
ROSTER_MIN_WIDTH = 440

#: What `Name` keeps when it has given away everything else. Enough for an
#: initial and the ellipsis, and a constant for the same reason
#: `ROSTER_MIN_WIDTH` is one.
#:
#: It is a floor under a floor: `QHeaderView` has a `minimumSectionSize` of its
#: own, that one *is* a font metric, and above the base UI font it is the larger
#: of the two -- 49px at +3, 61 at +6, 75 at +10 here. So this number decides
#: what `Name` keeps at the base font and Qt decides it above that, which is
#: the right way round: the table scrolls either way, and it is only the floor
#: under the *window* that has to be the same on every machine.
NAME_MIN_WIDTH = 40


class RosterView(QTableView):
    """A `QTableView` that reports what it can survive, not what it wants.

    `QAbstractScrollArea.sizeHint` answers 256px whatever is in it, which is
    why `_size_roster` pins `minimumWidth` to `ROSTER_MIN_WIDTH` to get the
    roster its five columns -- and that pin is what puts the floor under the
    window rather than a font metric. The hint is the floor here and the
    maximum is the natural width, so a `QHBoxLayout` gives the roster
    everything spare up to its contents and takes it back again first when the
    window is squeezed. Nothing else in the header has any spare to take: see
    `ROW_STRETCH` in `window.py`, where the roster is the item with the
    stretch.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        #: Both are zero until `measure` has been called, and every override
        #: below falls back to Qt's own answer while they are. The form is
        #: built long before there is a party to size it from.
        self._natural = 0
        self._name = 0

    def measure(self, natural: int, name: int) -> None:
        """Record what the columns came to, once they are sized to contents.

        `natural` is the whole table at its contents, chrome included; `name`
        is the `Name` column alone. Kept for `sizeHint` -- `_share_width`
        below measures the other four columns live instead, because they stay
        in `ResizeToContents` and can drift a pixel or two after this runs.
        """
        self._natural, self._name = natural, name
        self._share_width()

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        if not self._natural:
            return hint
        return QSize(min(self._natural, ROSTER_MIN_WIDTH), hint.height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._share_width()

    def _share_width(self) -> None:
        """Give `Name` whatever the other four columns did not take -- all of
        it, whichever way the difference runs.

        This runs from `resizeEvent` and from `measure`, so it answers the
        window changing size and nothing else. **A user dragging the `Name`
        divider with the mouse is out of scope and is left alone** until the
        next real resize corrects it: the section is `Interactive` because
        `resizeSection` is ignored under `Stretch` and `ResizeToContents`, and
        being draggable is what `Interactive` means. Nothing about #71's floor
        depends on it -- `minimumWidth` and `maximumWidth` are what the
        window's own minimum is built from and a drag does not touch either --
        so a dragged column is a column the user chose, not a broken
        invariant (#93).

        `want` used to be capped at `self._name`, so a widget forced wider
        than its own contents -- `ROSTER_MIN_WIDTH` conflicting with
        `setMaximumWidth(natural)` when an ordinary party's `natural` is under
        the constant -- left the surplus unclaimed by any column: a white gap
        between `HP` and the roster's own border (#474, rejected a second
        time on 2026-09-10). Dropping the cap means `Name` takes the surplus
        the same way it gives up a shortfall.

        It is measured live rather than from `self._fixed` and `self.width()`,
        which are both a snapshot taken once, before the roster is shown:
        `Race`, `Class`, `AC` and `HP` stay in `ResizeToContents` forever (only
        `Name` becomes `Interactive`), so Qt is free to nudge them by a pixel
        or two once real font metrics are in play, and `self._fixed` -- a
        constant from that first measurement -- does not follow. `self.width()`
        has the same defect the other way: it is the whole widget, and the
        frame, the row-number gutter and a scrollbar (real, when
        `MAX_ROSTER_ROWS` is exceeded) are Qt's to decide, not a value to
        recompute by hand. `viewport().width()` and the four sections' own
        current sizes are what Qt already believes both of those to be *now*,
        so filling from them leaves no remainder either way.
        """
        if not self._natural:
            return
        header = self.horizontalHeader()
        fixed = sum(header.sectionSize(column)
                    for column in range(header.count())
                    if column != NAME_COLUMN)
        want = max(NAME_MIN_WIDTH, self.viewport().width() - fixed)
        if header.sectionSize(NAME_COLUMN) != want:
            header.resizeSection(NAME_COLUMN, want)
