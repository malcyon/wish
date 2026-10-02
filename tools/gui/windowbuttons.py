#!/usr/bin/env python3
"""List and click the Action buttons of a running Wish window, in-process.

A driver that holds an `AutomapBinding` imports this: `rows(window)` is every
button the player can press, and `click(window, name)` presses one the way the
player would, so the dialog it raises really appears and is really answered.
The window's own `ask` and `_chosen_spell` are not replaced.

The buttons are the Action bar's, the Fast Travel row's two and each roster
card's Level up. A button is addressed by its Qt object name, which is the
`name` in a row.
"""

from __future__ import annotations

import time

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QInputDialog, QMessageBox

#: How often the armed timer looks for a modal dialog, in milliseconds.
POLL_MS = 10

#: How long a click may stay inside its dialogs before they are rejected.
DEADLINE_SECONDS = 10.0


def _buttons(window) -> list:
    found = list(window.actions_bar.buttons.values())
    for button in (window.fasttravel_bar.button,
                   window.fasttravel_bar.back_button):
        if button is not None:
            found.append(button)
    found += [card.level_up for card in window.roster.cards
              if card.level_up is not None]
    return found


def _row(window, button) -> dict:
    return {"name": button.objectName(), "text": button.text(),
            "enabled": button.isEnabled(), "tooltip": button.toolTip(),
            # `isVisibleTo` and not `isVisible`: an offscreen window that was
            # never shown reports every button hidden.
            "visible": button.isVisibleTo(window.root)}


def rows(window) -> list[dict]:
    """Every button, with its object name, text, enabled state, tooltip and visibility."""
    return [_row(window, b) for b in _buttons(window)]


def _messages(window) -> list:
    panel = window.messages.list
    return [] if panel is None else [panel.item(i) for i in range(panel.count())]


def _new_lines(window, before) -> list[str]:
    panel = window.messages.list
    if panel is None:
        return []
    start = 0
    if before:
        # Lines are only appended, and the panel drops its oldest past a limit,
        # so the last line seen before is the anchor if it survived.
        at = panel.row(before[-1])
        start = at + 1 if at >= 0 else 0
    return [panel.item(i).text() for i in range(start, panel.count())]


class _Answerer:
    """Answers every modal dialog the click raises, and gives up at a deadline."""

    def __init__(self, answer, spell, seconds: float):
        self.answer, self.spell = answer, spell
        self.dialogs: list[dict] = []
        self.error: str | None = None
        self.deadline = time.monotonic() + seconds
        # Held, not compared by id: a freed dialog's id can come back.
        self._seen: list = []
        self.timer = QTimer()
        self.timer.setInterval(POLL_MS)
        self.timer.timeout.connect(self.look)

    def look(self) -> None:
        # An exception out of a slot would be swallowed by Qt and leave the
        # click blocked on its dialog for ever.
        try:
            modal = QApplication.activeModalWidget()
            if modal is None:
                return
            if time.monotonic() > self.deadline:
                self.error = self.error or "a dialog was still open at the deadline"
                modal.reject()
                return
            if any(modal is seen for seen in self._seen):
                return
            self._seen.append(modal)
            self.dialogs.append(self._answer(modal))
        except Exception as exc:
            self.error = self.error or f"could not answer a dialog: {exc!r}"
            modal = QApplication.activeModalWidget()
            if modal is not None:
                modal.reject()

    def _answer(self, modal) -> dict:
        if isinstance(modal, QMessageBox):
            yes_button = modal.button(QMessageBox.StandardButton.Yes)
            no_button = modal.button(QMessageBox.StandardButton.No)
            if yes_button is None or no_button is None:
                # Nothing to say yes or no to: close it as the player would.
                ok = modal.button(QMessageBox.StandardButton.Ok)
                (ok.click() if ok is not None else modal.reject())
                return {"kind": "message", "text": modal.text()}
            yes = str(self.answer).lower() == "yes"
            (yes_button if yes else no_button).click()
            return {"kind": "question", "text": modal.text(),
                    "answer": "yes" if yes else "no"}
        if isinstance(modal, QInputDialog):
            dialog = {"kind": "choice", "text": modal.labelText(),
                      "items": list(modal.comboBoxItems()), "picked": self.spell}
            if self.spell is None:
                modal.reject()
            else:
                modal.setTextValue(self.spell)
                modal.accept()
            return dialog
        modal.reject()
        return {"kind": type(modal).__name__, "text": ""}


def click(window, name: str, answer: str | None = None,
          spell: str | None = None, deadline: float = DEADLINE_SECONDS) -> dict:
    """Press the button called `name`, answering any dialog it raises.

    A missing, disabled or hidden button is not pressed and the result carries
    an `error`. `answer` is "yes" for a question; anything else, including
    None, answers No. `spell` is the label to pick in a choice dialog; None
    cancels it. The result also holds the dialog that appeared (None if none
    did; `dialogs` has all of them), the Messages panel's new lines, and the button rows afterwards.
    """
    target = next((b for b in _buttons(window) if b.objectName() == name), None)
    result: dict = {"name": name, "error": None, "dialog": None, "messages": []}
    if target is None:
        result["error"] = "no such button"
    elif not target.isEnabled():
        result["error"] = "button is disabled"
    elif not target.isVisibleTo(window.root):
        result["error"] = "button is hidden"
    if result["error"]:
        result["buttons"] = rows(window)
        return result
    before = _messages(window)
    answerer = _Answerer(answer, spell, deadline)
    answerer.timer.start()
    try:
        target.click()
    finally:
        answerer.timer.stop()
    result["dialogs"] = answerer.dialogs
    result["dialog"] = answerer.dialogs[0] if answerer.dialogs else None
    result["error"] = answerer.error
    result["messages"] = _new_lines(window, before)
    result["buttons"] = rows(window)
    return result
