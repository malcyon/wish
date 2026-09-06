"""The Quest Log: the City Council's books, drawn beside the map.

A quest log the game itself only shows one City Hall visit at a time: what has
been asked for, what is finished, and -- the line worth having -- what is
finished and still owed money.

Read-only, and deliberately. Every byte behind this panel is a plot flag, and
writing one would mean claiming to know what the rest of the script expects
afterwards. Displaying them promises nothing.

All the decoding is `goldbox/commissions.py`, which has no Qt in it and is tested
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
they are useful and harmless. See `docs/103-quest-log-panel.md`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from PyQt6.QtCore import QObject, Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from goldbox import areas
from goldbox import commissions as book

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
# `goldbox/commissions.py` is the authority; this is the same thing in words, for
# the tooltip, and it is why a row can be finished and still on the board.
# The addresses each of these rests on are in `goldbox/commissions.py`; they are
# deliberately not here, because a player reads these.
GATE_NOTES = {
    2: "gated on the book bounty, not on the six entries",
    4: "also needs Cadorna's chambers unpaid and Cadorna not yet exposed",
    5: "also needs Sokal Keep paid and the Bishop unfinished",
    6: "also needs Sokal Keep paid",
    12: "also needs Sokal Keep paid",
    13: "also needs the envoy unpaid, and either Cadorna exposed or his "
        "chambers paid",
    14: "also needs Cadorna fully exposed",
    15: "also needs the council meeting unfinished",
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
    it beyond reach, so it is not a commission and gets no row. Nothing on
    the face says so -- a slot no party can be offered is not the player's
    problem; the finding is `docs/103-quest-log-panel.md`.
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
        return _sentence(book.LEDGER[commission.ledger[0]][0] or commission.name)
    return _sentence(commission.name)


#: Place names the clerk's speech spells in lower case, and what a reader
#: expects to see. Only one so far: every other district and building the board
#: mentions -- Sokal Keep, Kuto's Well, Podal Plaza, Kovel Mansion, Valjevo
#: Castle, Stojanow Gate -- is already capitalised in the bytecode.
#:
#: **Sokal, not Sokol.** That is the game's own spelling and it stands; the
#: guides say Sokol and are not the authority on what the board says.
PLACES = {"slums": "Slums"}


def _sentence(text: str) -> str:
    """First letter up, place names capitalised, nothing else touched.

    Both done here rather than in `goldbox/commissions.py`, because the strings
    there are the clerk's own speech as the bytecode carries it and are cited
    as such -- "clear the slums" is what is on the board, and "Clear the Slums"
    is what a quest log should say. `str.capitalize` would lower the rest and
    turn "Norris the Gray" into "Norris the gray".
    """
    for word, name in PLACES.items():
        text = re.sub(rf"\b{word}\b", name, text)
    return text[:1].upper() + text[1:] if text else text


def _note(commission, entries) -> str:
    """The one fact a commission needs on its face, when it has one.

    Two shapes. A commission spanning several ledger entries counts them --
    "3 of 6 books recovered". A single entry that keeps a progress marker says
    what the marker means, which `goldbox.commissions.marker_text` decoded: only
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
    where = f"candidate {commission.order} on the clerk's board"
    if commission.order in on_board:
        return f"{where}: the clerk raises it on the next visit"
    if commission.order in open_gates:
        return f"{where}: its gate is open, but the clerk offers three a visit"
    return f"{where}: its gate is shut"


# A row whose tooltip is one sentence instead of the ledger detail. The Slums'
# 25 is the whole area's encounters, set and wandering together; a PC
# walkthrough quotes 15, which is `$4A80`'s separate cap on wandering fights,
# and the number on the face reads as contradicting it. That is the only thing
# this row's tooltip has to settle, and Donald asked in 2026-08 for exactly
# this sentence and nothing under it -- the ledger address and the board
# candidate are on every other row for whoever wants them.
TOOLTIPS = {
    21: (f"Counts every fight won in the Slums: {book.SLUM_SET} set encounters "
         f"and {book.SLUM_WANDERING} wandering."),
}


def _tip(commission, entries, on_board, open_gates) -> str:
    if len(commission.ledger) == 1 and commission.ledger[0] in TOOLTIPS:
        return TOOLTIPS[commission.ledger[0]]
    lines = [commission.name, _board_line(commission, on_board, open_gates)]
    if commission.order in GATE_NOTES:
        lines.append(f"  {GATE_NOTES[commission.order]}")
    many = len(commission.ledger) > 1
    for index in commission.ledger:
        entry = entries[index]
        line = f"Ledger {index} = {entry.value}"
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
            lines.append("  Counts towards commissions completed")
    if many:
        sources = {entries[i].source for i in commission.ledger}
        if len(sources) == 1 and sources != {None}:
            lines.append(f"written by {sources.pop()}")
        if any(entries[i].major for i in commission.ledger):
            lines.append("Counts towards commissions completed")
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


# --- side quests, #158 (Track the quests the game itself forgets, starting
# --- with Ohlo's potion) -----------------------------------------------------
#
# Every string a side-quest row draws was approved from a screenshot: the six
# on-screen words on 2026-09-04, and the tooltip's third line -- "Ohlo's
# potion collected." and "Ohlo's quest completed." -- on 2026-09-05. That
# approval also reached `book.IN_PROGRESS`, which was already shipping
# lowercase in the Commissions panel and is now "In progress" in both places,
# because the same state word spelled two ways in one window is worse than
# changing a string a player has already seen.
#
# **A side quest is not marked as Wish's own record rather than the game's.**
# The reason is `durable_state`: it back-fills from `$4A81` in every case but
# one -- accepted, potion not yet collected, Wish not attached when it
# happened -- and the next session in the Slums closes even that, because
# `$4A04` is still 250 while the party has not left.  So the row is wrong only
# inside a window that shuts by itself, which is not worth a sentence in front
# of a player.
#
# **There is no separate group on screen.**  Donald, 2026-09-04: *"I don't
# think we need a separate 'Side Quests' section. Just lump them all
# together."*  Then, once this was under way, he narrowed how far that goes:
# *"You can keep track of commissions separately on the backend. Just display
# them together? The player will not care about the difference."*  So the
# merge is display only. `side_quest_rows()` stays its own function, and
# `update_from` appends its rows to the commissions `Group` rather than
# building one of their own. `SIDE_QUEST_HEADING` is gone rather than merely
# unused, because it was the only thing on screen that told the two kinds of
# row apart -- which is exactly what the second instruction gave up. The
# distinction still exists in the code, in this function and this table; it
# only stopped being something a player sees.
#
# **The tooltip's third line is `_side_quest_tip`'s rendering of a
# `QuestFlag.meaning`**, from whichever flag explains the state -- those
# sentences live in `goldbox/commissions.py` beside the flags themselves.
# `_side_quest_flag` can only reach `accept.meaning` when `durable_state` is
# `QUEST_ACCEPTED`, and Ohlo's accept flag is `durable=False`, so that third
# sentence is unreachable from the panel today and survives only for the
# debug log and the tests.
#
# The row was watched appearing and changing live against a running game --
# a party collecting Ohlo's potion at the booth, then delivering it, each
# within one poll -- "The Quest Log's side-quest row, watched arriving" in
# `docs/50-experiments.md`.
#
#: A side-quest state nobody has proposed a word for goes here rather than on
#: the face of the window: it is what a bug report needs and nothing a player
#: asked for. A child of `wish`, so `wish/debuglog.py`'s handler picks it up
#: when the log is on and its level swallows it when the log is off -- and
#: this module still imports nothing from `wish`.
_log = logging.getLogger("wish.automap.questlog").warning

SIDE_QUEST_IN_HAND = book.IN_PROGRESS
SIDE_QUEST_FINISHED = "Finished"

#: `durable_state` -> the row's state word. Deliberately partial: Ohlo's own
#: accept flag is not durable, so `QUEST_ACCEPTED` can never come out of
#: `durable_state` today and no word has been proposed for it. The first
#: quest whose accept flag *is* durable will produce one and needs a word
#: added here before it can be shown -- the code does not otherwise change.
SIDE_QUEST_WORDS = {
    book.QUEST_IN_HAND: SIDE_QUEST_IN_HAND,
    book.QUEST_FINISHED: SIDE_QUEST_FINISHED,
}


def _side_quest_flag(quest, word):
    """Which `QuestFlag` explains this state, for the tooltip's meaning."""
    if word == book.QUEST_FINISHED:
        return quest.finish
    if word == book.QUEST_ACCEPTED:
        return quest.accept
    durable_progress = [p for p in quest.progress if p.durable]
    return durable_progress[0] if durable_progress else quest.finish


def _side_quest_tip(state) -> str:
    """The quest's name, the area, and what the state means -- no address."""
    quest = state.quest
    place = None
    found = areas.area(quest.area)
    if found is not None:
        place = found.name
    flag = _side_quest_flag(quest, state.durable_state)
    return "\n".join([quest.name, place or f"area {quest.area}", flag.meaning])


def side_quest_rows(flags) -> list[tuple]:
    """One tuple per side quest the durable bytes say something about.

    `(name, state word, tooltip, sub-line, draw the name muted)`, the same
    shape `commission_rows` draws. Takes the same `Flags` object
    `update_from` already built from `flags()` -- not the raw source, and
    never `scratch()` -- so the byte the game itself forgets never reaches
    this row. A quest whose `durable_state` is `QUEST_UNSEEN` gets no row:
    Donald's decision of 2026-09-04 is that the log shows nothing between
    accepting an errand and holding what it asked for.

    `update_from` appends these after `commission_rows`' own, into the same
    `Group` -- the merge is display only (#158). The two stay separate here
    and separate in `goldbox/commissions.py`; only where the rows land moved.
    """
    rows = []
    for state in book.side_quests(flags):
        word = state.durable_state
        if word == book.QUEST_UNSEEN:
            continue
        said = SIDE_QUEST_WORDS.get(word)
        if said is None:
            # A state nobody has proposed a word for draws **no row**, and
            # takes nothing else down with it.  A bare `SIDE_QUEST_WORDS[word]`
            # raised `KeyError` here, and `tick()`'s broad handler turned that
            # into `trouble reading the emulator: 'accepted'` in the alarm
            # line -- a raw internal word, blamed on the emulator.  Worse,
            # `update_from` caches the flag bytes before calling this, so the
            # whole log, commissions and summonses included, stopped redrawing
            # from then on.  Skipping is not silent: the debug log says so.
            _log("no approved word for the side-quest state %r", word)
            continue
        rows.append((
            _sentence(state.quest.name),
            said,
            _side_quest_tip(state),
            "",
            word == book.QUEST_FINISHED,
        ))
    return rows


class QuestLogPanel(QObject):
    """The whole log: one row per commission, and the summonses under it.

    One entry point -- `update_from(source)`. Nothing here writes.
    """

    def __init__(self, root: QWidget, parent: QObject | None = None):
        super().__init__(parent)
        self.root = root
        self.heading = root.findChild(QLabel, "questlog_heading")
        self.scroll = root.findChild(QScrollArea, "questlog_scroll")
        if self.scroll is not None:
            self.scroll.setStyleSheet(f"QScrollArea {{ border: 1px solid "
                                      f"{LATTICE.name()}; border-radius: 4px; }}")
            if self.scroll.widget() is not None:
                self.scroll.widget().setStyleSheet(f"background: {CARD.name()};")

        self.completed = root.findChild(QLabel, "questlog_completed")
        if self.completed is not None:
            self.completed.setStyleSheet(f"color: {MUTED.name()}")
            self.completed.setToolTip(
                "Bumped by the clerk for the ten commissions that count "
                "as major")

        self.column = root.findChild(QVBoxLayout, "questlog_column")
        if self.column is None and self.scroll is not None and self.scroll.widget() is not None:
            self.column = self.scroll.widget().layout()

        # One group for commissions and side quests together (#158): Donald,
        # 2026-09-04, does not want a separate section, so there is no
        # `self.groups["side_quests"]` to gate -- `update_from` decides
        # whether `side_quest_rows()` contributes to this same group's rows.
        self.groups = {"commissions": Group()}
        self.groups["summons"] = Group("Summoned to")
        if self.column is not None:
            for group in self.groups.values():
                self.column.addWidget(group)
            self.column.addStretch(1)

        self._flags = None
        self.set_message("waiting for a game")

    def set_message(self, text: str) -> None:
        """No bytes to show, and why."""
        if self.heading is not None:
            self.heading.setText(f"Quest Log - {text}" if text
                                 else "Quest Log")

    def update_from(self, source) -> None:
        """Redraw from the flag block. Same input as `goldbox.commissions.read`."""
        flags = book.flags(source)
        if self._flags is not None and flags.to_bytes() == self._flags:
            return                      # plot flags move rarely; skip the churn
        self._flags = flags.to_bytes()
        state = book.read(flags)
        self.set_message("")
        if self.completed is not None:
            self.completed.setText(f"Quests completed: {state.completed}")

        rows = commission_rows(flags) + side_quest_rows(flags)
        self.groups["commissions"].show_rows(
            rows or [("The clerk has nothing on the books for this party", "", "")])
        self.groups["summons"].show_rows(
            [(_sentence(a.name), a.state, "")
             for a in state.outstanding])

