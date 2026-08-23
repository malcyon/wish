"""The City Council's books, drawn beside the map.

A quest log the game itself only shows one City Hall visit at a time: what has
been asked for, what is finished, and -- the line worth having -- what is
finished and still owed money.

Read-only, and deliberately. Every byte behind this panel is a plot flag, and
writing one would mean claiming to know what the rest of the script expects
afterwards. Displaying them promises nothing.

All the decoding is `por/commissions.py`, which has no Qt in it and is tested
against saves. This module is presentation: `update_from()` takes the same
bytes that module does -- the 224 flags at `$4A20`, a `SaveGame0`, or a whole
`SAVEDGAME0` image -- so it works from a live read and from a save file alike.

**One row per commission, in plot order, with a plain state word.** The board
and the ledger are usually the same byte -- `ECL08` gates "clear the slums" on
`$4AA6+21`, and that byte is also the ledger entry the clerk pays for -- so a
panel with an offers group and a ledger group showed that one byte twice. It
was labelled and tooltipped as one thing in two states; readers still counted
two commissions. So the two are joined here instead: `COMMISSIONS` pairs each
board candidate with the ledger entries its gate settles, adds the six entries
no candidate offers, and each pair draws exactly one row.

The row carries only facts about the party's game -- the commission's name, its
state, and for the books how many of the six are in. Raw marker values, ledger
indices, addresses and the gate's other conditions are in the tooltip, where
they are useful and harmless. See `docs/103-commissions-panel.md`.
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from por import commissions as book

from .panel import CARD, LATTICE, MUTED

PANEL_WIDTH = 248

#: The fourth state word. The other three are the decoder's own.
OFFERED = "offered"

# Six ledger entries have no candidate on the board, so there is no imperative
# to borrow and the clerk's only words for them are his payment speech --
# "graveyard menace ended". Labelling an unfinished job with the speech for
# having finished it is the trap this panel exists to avoid, so they get a
# neutral name here and the speech goes in the tooltip.
UNBOARDED = {
    0: "Norris the Gray, in Kuto's Well",
    2: "the area by the evil temple",
    11: "the graveyard menace",
    24: "Cadorna's treachery",
    25: "Cadorna himself",
}

# What a candidate's gate reads besides its own ledger entries. `_gate` in
# `por/commissions.py` is the authority; this is the same thing in words, for
# the tooltip, and it is why a row can be finished and still on the board.
GATE_NOTES = {
    2: "gated on the book bounty flag $4AC2, not on the six entries",
    4: "also needs $4A97 (Cadorna's chambers) unpaid and $4ABE "
       "(Cadorna exposed) below 254",
    5: "also needs Sokal Keep paid and $4A9B (the Bishop) unfinished",
    6: "also needs Sokal Keep paid",
    12: "also needs Sokal Keep paid",
    13: "also needs $4A98 (the envoy) unpaid, and either $4ABE "
        "(Cadorna exposed) or $4A97 (his chambers) paid",
    14: "also needs $4ABE (Cadorna exposed) at 254 or more",
    15: "also needs $4A9A (the council meeting) unfinished",
}

#: The one commission that settles more than one ledger entry, and its noun.
UNITS = {2: "books recovered"}


@dataclass(frozen=True)
class Commission:
    """One job: the clerk's words for it, and the ledger it settles."""

    name: str
    ledger: tuple[int, ...]
    order: int | None                   # board candidate, where there is one
    unit: str | None = None


def _table() -> tuple[Commission, ...]:
    """Board candidates joined to the entries they settle, then the rest.

    Candidate 9 is dropped: it settles nothing and an unconditional `GOTO` puts
    it beyond reach, so it is not a commission. The panel's footnote says so.
    """
    out, claimed = [], set()
    for offer in book.BOARD:
        if not offer.ledger:
            continue
        out.append(Commission(offer.text, offer.ledger, offer.order,
                              UNITS.get(offer.order)))
        claimed |= set(offer.ledger)
    for index in range(book.LEDGER_COUNT):
        if index not in claimed:
            out.append(Commission(
                UNBOARDED.get(index, book.ledger_name(index)), (index,), None))
    # By first ledger index, which is roughly the plot's own order.
    return tuple(sorted(out, key=lambda c: min(c.ledger)))


COMMISSIONS = _table()


def _state(commission, entries, on_board) -> str | None:
    """The one word, or `None` for a commission the party has not met."""
    values = [entries[i].value for i in commission.ledger]
    if all(v == book.PAID_VALUE for v in values):
        return book.PAID
    if any(v == book.DONE for v in values):
        return book.REWARD_WAITING
    if any(values):                     # a marker, or some but not all paid
        return book.IN_PROGRESS
    if commission.order in on_board:
        return OFFERED
    return None


def _name(commission, word) -> str:
    """The clerk's own words, whichever of his two sets is the true one.

    Before it is done, the board's imperative -- "clear the slums". Once it is
    done, his payment speech -- "slums cleared" -- which is the better name and
    is only ever shown over a job that really is finished. Putting the speech on
    an unfinished row is the label that started this redesign, and the many-entry
    commission keeps the board's text because it has six speeches, not one.
    """
    if word in (book.PAID, book.REWARD_WAITING) and len(commission.ledger) == 1:
        return book.LEDGER[commission.ledger[0]][0] or commission.name
    return commission.name


def _note(commission, entries) -> str:
    """The one fact a commission needs on its face, when it has one.

    Two shapes. A commission spanning several ledger entries counts them --
    "3 of 6 books recovered". A single entry that keeps a progress marker says
    what the marker means, which `por.commissions.marker_text` decoded: only
    four entries have one, and only the slums' counts anything.
    """
    if commission.unit:
        total = len(commission.ledger)
        done = sum(entries[i].value >= book.DONE for i in commission.ledger)
        return f"{done} of {total} {commission.unit}" if 0 < done < total else ""
    if len(commission.ledger) == 1:
        entry = entries.get(commission.ledger[0])
        if entry is not None and entry.detail:
            return entry.detail
    return ""


def _board_line(commission, on_board, open_gates) -> str:
    if commission.order is None:
        return "no candidate on the clerk's board offers this one"
    where = f"candidate {commission.order} on ECL08's board at $A84D"
    if commission.order in on_board:
        return f"{where}: the clerk raises it on the next visit"
    if commission.order in open_gates:
        return f"{where}: its gate is open, but the clerk offers three a visit"
    return f"{where}: its gate is shut"


def _tip(commission, entries, on_board, open_gates) -> str:
    lines = [commission.name, _board_line(commission, on_board, open_gates)]
    if commission.order in GATE_NOTES:
        lines.append(f"  {GATE_NOTES[commission.order]}")
    many = len(commission.ledger) > 1
    for index in commission.ledger:
        entry = entries[index]
        line = f"ledger {index} at ${entry.address:04X} = {entry.value}"
        speech = book.LEDGER[index][0]
        if many:
            lines.append(f"{line} ({entry.state})"
                         + (f' - "{speech}"' if speech else ""))
            continue
        lines.append(line)
        if speech:
            lines.append(f'  the clerk pays for it as "{speech}"')
        if entry.source:
            lines.append(f"  written by {entry.source}")
        if entry.major:
            lines.append("  counts towards commissions completed")
    if many:
        sources = {entries[i].source for i in commission.ledger}
        if len(sources) == 1 and sources != {None}:
            lines.append(f"written by {sources.pop()}")
        if any(entries[i].major for i in commission.ledger):
            lines.append("counts towards commissions completed")
    return "\n".join(lines)


def _label(text="", *, bold=False, muted=False, size=0) -> QLabel:
    lab = QLabel(text)
    font = lab.font()
    if bold:
        font.setBold(True)
    if size:
        font.setPointSize(size)
    lab.setFont(font)
    if muted:
        lab.setStyleSheet(f"color: {MUTED.name()}")
    lab.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
    return lab


class Row(QWidget):
    """One commission: its name, where it stands, and a note if it needs one."""

    def __init__(self, parent=None):
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        self.what = _label(size=8)
        self.what.setWordWrap(True)
        self.what.setSizePolicy(QSizePolicy.Policy.Expanding,
                                QSizePolicy.Policy.Preferred)
        self.state = _label(size=8, muted=True)
        top.addWidget(self.what, 1)
        top.addWidget(self.state, 0, Qt.AlignmentFlag.AlignTop)
        box.addLayout(top)

        self.note = _label(size=7, muted=True)
        self.note.setWordWrap(True)
        box.addWidget(self.note)

    def show_row(self, what: str, state: str = "", tip: str = "",
                 note: str = "", dim: bool = False) -> None:
        self.what.setText(what)
        self.what.setStyleSheet(f"color: {MUTED.name()}" if dim else "")
        self.state.setText(state)
        self.note.setText(note)
        self.note.setVisible(bool(note))
        self.setToolTip(tip)
        self.show()


class Group(QFrame):
    """Rows, under a heading where there is one. Hidden when it has none."""

    def __init__(self, heading: str = "", parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)
        self.heading = _label(heading, bold=True, size=8)
        self.heading.setVisible(bool(heading))
        box.addWidget(self.heading)
        self._box = box
        self._rows: list[Row] = []

    def _row(self, index: int) -> Row:
        # Rows are made once and reused. A panel that rebuilt its widgets on
        # every poll would drop the scroll position each second.
        while len(self._rows) <= index:
            row = Row()
            self._box.addWidget(row)
            self._rows.append(row)
        return self._rows[index]

    def show_rows(self, rows) -> None:
        """`rows` is (text, state, tooltip) triples, or five-tuples with the
        sub-line and whether to draw the name muted."""
        for i, row in enumerate(rows):
            self._row(i).show_row(*row)
        for row in self._rows[len(rows):]:
            row.hide()
        self.setVisible(bool(rows))

    def visible_rows(self) -> list[Row]:
        return [r for r in self._rows if r.isVisibleTo(self)]


def commission_rows(flags) -> list[tuple]:
    """One tuple per commission the party has met, in plot order.

    `(name, state word, tooltip, sub-line, draw the name muted)`. A commission
    with an untouched ledger that the clerk is not raising is left out.
    """
    state = book.read(flags)
    entries = {e.index: e for e in state.ledger}
    on_board = {o.order for o in state.offers}
    open_gates = {o.order for o in book.offered(flags, limit=16)}
    rows = []
    for commission in COMMISSIONS:
        word = _state(commission, entries, on_board)
        if word is None:
            continue
        rows.append((_name(commission, word), word,
                     _tip(commission, entries, on_board, open_gates),
                     _note(commission, entries), word == book.PAID))
    return rows


class CommissionsPanel(QWidget):
    """The whole log: one row per commission, and the summonses under it.

    One entry point -- `update_from(source)`. Nothing here writes.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(PANEL_WIDTH + 22)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        self.heading = _label("Commissions", bold=True)
        outer.addWidget(self.heading)

        inner = QWidget()
        inner.setStyleSheet(f"background: {CARD.name()};")
        column = QVBoxLayout(inner)
        column.setContentsMargins(8, 6, 8, 6)
        column.setSpacing(8)

        self.completed = _label("", muted=True, size=8)
        self.completed.setToolTip(
            f"${book.COMPLETED:04X}, bumped by the clerk for the ten "
            "commissions that count as major")
        column.addWidget(self.completed)

        self.groups = {
            "commissions": Group(),
            "summons": Group("Summoned to"),
        }
        for group in self.groups.values():
            column.addWidget(group)

        self.footnote = _label(
            "One board slot is withdrawn: the clerk never reaches it and it "
            "settles nothing.", muted=True, size=7)
        self.footnote.setWordWrap(True)
        self.footnote.setToolTip(
            "ECL08 $A84D, candidate 9: an unconditional GOTO $A890 jumps past "
            "its own body, so no party can be offered it.")
        column.addWidget(self.footnote)
        column.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.StyledPanel)
        scroll.setStyleSheet(f"QScrollArea {{ border: 1px solid "
                             f"{LATTICE.name()}; border-radius: 4px; }}")
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll, 1)

        self._flags = None
        self.set_message("waiting for a game")

    def set_message(self, text: str) -> None:
        """No bytes to show, and why."""
        self.heading.setText(f"Commissions - {text}" if text
                             else "Commissions")

    def update_from(self, source) -> None:
        """Redraw from the flag block. Same input as `por.commissions.read`."""
        flags = book.flags(source)
        if self._flags is not None and flags.to_bytes() == self._flags:
            return                      # plot flags move rarely; skip the churn
        self._flags = flags.to_bytes()
        state = book.read(flags)
        self.set_message("")
        self.completed.setText(f"Commissions completed: {state.completed}")

        self.groups["commissions"].show_rows(
            commission_rows(flags)
            or [("the clerk has nothing on the books for this party", "", "")])
        self.groups["summons"].show_rows(
            [(a.name, a.state, f"${a.address:04X} = {a.value}")
             for a in state.outstanding])
