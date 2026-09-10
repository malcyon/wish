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

`ROSTER_MIN_WIDTH` used to be a floor under the whole window as well, because
`_size_roster` handed it to `setMinimumWidth`: whatever the roster's minimum
was became a floor under the header, which does not scroll, and a minimum
taken from font metrics is a floor that follows the UI font -- #41's bug, and
the reason Windows CI once measured 1304 where Linux measured 1036. That stayed
sound only while the constant was smaller than every real party's own columns,
and it is not: an ordinary six-character party measures under 440 at every UI
font up to the base font's own reach, so the window's floor became a text
measurement again for the common case (#474). `_size_roster` no longer sets
the roster's minimum width at all -- it keeps whatever `QTableView` has of its
own, well under any party's columns, and the three rules above still hold from
`sizeHint` and `_share_width` alone.
"""

from __future__ import annotations

from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import QTableView

#: The column that gives. It is the widest of the five -- twenty bytes of name
#: against three digits of hit points -- and the only one whose value a reader
#: can still recognise from its first few characters.
NAME_COLUMN = 0

#: What the roster asks the layout for, in pixels, once its five columns are
#: wider than this, at any font on any platform. Read only by `sizeHint`
#: below -- `_size_roster` no longer hands it to `setMinimumWidth`, so it is
#: not a floor under the window any more. It used to be: see the module
#: docstring for why that stopped holding (`#474`).
#:
#: Why this number and not another. It has to clear the four contents-sized
#: columns at the base UI font, or the roster would ask for less room than
#: they need on a machine nobody has resized anything on: `Race`, `Class`,
#: `AC`, `HP` and the table's own chrome come to 356px here at 9pt, so 440
#: leaves `Name` 84 of its 231 -- `WWWWWWW...` at the widest a name can be, and
#: more of an ordinary one.
#:
#: At a Windows-sized font -- which measures here like six to ten points more
#: than 9pt -- those four columns come to 564 and 694, so this number no
#: longer covers them either; that is the third rule working (module
#: docstring), not a number to raise.
ROSTER_MIN_WIDTH = 440

#: What `Name` keeps when it has given away everything else. Enough for an
#: initial and the ellipsis, and a constant rather than a measurement for the
#: same reason `ROSTER_MIN_WIDTH` used to be one.
#:
#: It is a floor under a floor: `QHeaderView` has a `minimumSectionSize` of its
#: own, that one *is* a font metric, and above the base UI font it is the larger
#: of the two -- 49px at +3, 61 at +6, 75 at +10 here. So this number decides
#: what `Name` keeps at the base font and Qt decides it above that, which is
#: the right way round: the table scrolls either way, and it is only `Name`'s
#: own width that has to be the same on every machine.
NAME_MIN_WIDTH = 40


class RosterView(QTableView):
    """A `QTableView` that reports what it can survive, not what it wants.

    `QAbstractScrollArea.sizeHint` answers 256px whatever is in it, which is
    why `_size_roster` used to pin `minimumWidth == maximumWidth` to get the
    roster its five columns -- and that pin is what put a font metric under the
    window. The hint below is what a `QHBoxLayout` aims for and the maximum is
    the natural width, so the layout gives the roster everything spare up to
    its contents and takes it back again first when the window is squeezed --
    down to the hint, and then further still, to whatever `QTableView` answers
    for its own `minimumSizeHint`, since `_size_roster` stopped giving the
    roster an explicit floor of its own (#474). Nothing else in the header has
    any spare to take: see `ROW_STRETCH` in `window.py`, where the roster is
    the item with the stretch.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        #: All three are zero until `measure` has been called, and every
        #: override below falls back to Qt's own answer while they are. The
        #: form is built long before there is a party to size it from.
        self._natural = 0
        self._name = 0
        self._fixed = 0

    def measure(self, natural: int, name: int) -> None:
        """Record what the columns came to, once they are sized to contents.

        `natural` is the whole table at its contents, chrome included; `name`
        is the `Name` column alone. What is left is the four columns that never
        give any of it back.
        """
        self._natural, self._name, self._fixed = natural, name, natural - name
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
        """Give `Name` whatever the other four columns did not take.

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
        """
        if not self._natural:
            return
        header = self.horizontalHeader()
        want = max(NAME_MIN_WIDTH, min(self._name, self.width() - self._fixed))
        if header.sectionSize(NAME_COLUMN) != want:
            header.resizeSection(NAME_COLUMN, want)
