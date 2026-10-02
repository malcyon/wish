"""`fsuaegdb.py wish` lists and presses the Wish window's buttons and picks a drop-down entry."""

import os
import pathlib
import sys
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from PyQt6.QtWidgets import QApplication, QMainWindow

from automap import actions as engine
from automap.actionbar import ActionBar, FastTravelBar
from automap.panel import MessagesPanel, RosterPanel
from automap.target import MemoryTarget
from tests.amiga.test_fsuaegdb import (  # noqa: F401 -- `wished` is a fixture
    FakeApp,
    by_event,
    run_wish,
    wished,
)
from tools.amiga import fsuaegdb
from tools.gui import windowbuttons
from wish.ui_window import Ui_WishWindow


class Plain(engine.Action):
    name, label, description, combat_legal = "heal", "Plain", "d", True

    def legality(self, target):
        return engine.Verdict(True)

    def run(self, target, **kwargs):
        target.write(0x10, b"\x01")
        return engine.Outcome(True, "Plain done.", ((0x10, b"\x01"),))


@pytest.fixture
def window():
    QApplication.instance() or QApplication([])
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    messages = MessagesPanel(root)
    bar = ActionBar(root, actions=[Plain()], say=messages.say)
    bar.attach(MemoryTarget())
    travel = FastTravelBar(root, say=messages.say)
    # With no machine attached the row greys its drop-down; a game is running
    # when the verb is used.
    travel.combo.setEnabled(True)
    return SimpleNamespace(
        root=root, messages=messages, actions_bar=bar, fasttravel_bar=travel,
        roster=RosterPanel(root), close=lambda: True)


@pytest.fixture
def real(wished, window, monkeypatch):                  # noqa: F811
    """`wish` over a real button window instead of the observe-only fake."""
    monkeypatch.setattr(fsuaegdb, "open_wish", lambda out: (FakeApp(), window))
    return window


def items(window):
    combo = window.fasttravel_bar.combo
    return [combo.itemText(i) for i in range(combo.count())]


def test_select_picks_the_entry_by_its_text(window, monkeypatch):
    names = items(window)
    assert len(names) > 1
    refreshed = []
    monkeypatch.setattr(window.fasttravel_bar, "refresh", lambda *a: refreshed.append(a))
    result = windowbuttons.select(window, "ft_combo", names[1])
    assert refreshed, "the window's own handler for a changed pick did not run"
    assert result["error"] is None
    assert result["current"] == names[1]
    assert window.fasttravel_bar.combo.currentIndex() == 1
    assert result["items"] == names


@pytest.mark.parametrize("name, item, error", [
    ("nope", "x", "no such combo"), ("ft_combo", "No such place", "no such item")])
def test_select_reports_what_it_cannot_pick_and_changes_nothing(
        window, name, item, error):
    before = window.fasttravel_bar.combo.currentIndex()
    assert windowbuttons.select(window, name, item)["error"] == error
    assert window.fasttravel_bar.combo.currentIndex() == before


def test_select_leaves_a_disabled_combo_alone(window):
    window.fasttravel_bar.combo.setEnabled(False)
    result = windowbuttons.select(window, "ft_combo", items(window)[1])
    assert result["error"] == "combo is disabled"
    assert window.fasttravel_bar.combo.currentIndex() == 0


def test_select_leaves_a_hidden_combo_alone(window, monkeypatch):
    refreshed = []
    monkeypatch.setattr(window.fasttravel_bar, "refresh", lambda *a: refreshed.append(a))
    window.fasttravel_bar.combo.hide()
    result = windowbuttons.select(window, "ft_combo", items(window)[1])
    assert result["error"] == "combo is hidden"
    assert window.fasttravel_bar.combo.currentIndex() == 0
    assert refreshed == []


def test_wish_buttons_logs_every_button_row(real, tmp_path):
    row = by_event(run_wish(tmp_path, ["buttons"]), "buttons")[0]
    names = {b["name"] for b in row["buttons"]}
    assert {"action_heal", "ft_button", "card_0_level_up"} <= names


def test_wish_click_presses_the_button_and_logs_the_result(real, tmp_path):
    row = by_event(run_wish(tmp_path, ["click action_heal"]), "click")[0]
    assert (row["name"], row["error"], row["dialog"]) == ("action_heal", None, None)
    assert "Plain done." in " ".join(row["messages"])


def test_wish_click_passes_the_answer_and_the_spell_with_spaces(
        real, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(windowbuttons, "click", lambda w, name, answer, spell:
                        seen.append((name, answer, spell)) or
                        {"name": name, "error": None})
    run_wish(tmp_path, ["click a yes Cure Light Wounds", "click b", "click c no"])
    assert seen == [("a", "yes", "Cure Light Wounds"), ("b", None, None),
                    ("c", "no", None)]


def test_wish_click_reports_a_disabled_button_and_a_bad_answer(real, tmp_path):
    real.actions_bar.buttons["heal"].setEnabled(False)
    rows = run_wish(tmp_path, ["click action_heal", "click action_heal maybe"])
    first, second = by_event(rows, "click")
    assert first["error"] == "button is disabled"
    assert "ValueError" in second["error"]


def test_wish_select_picks_a_destination_with_spaces_in_its_name(
        real, tmp_path, monkeypatch):
    real.fasttravel_bar.combo.addItem("Two Words")
    rows = run_wish(tmp_path, ["select ft_combo Two Words"])
    row = by_event(rows, "select")[0]
    assert (row["error"], row["current"]) == (None, "Two Words")


def test_wish_select_wants_a_combo_and_an_item(real, tmp_path):
    row = by_event(run_wish(tmp_path, ["select ft_combo"]), "select")[0]
    assert "ValueError" in row["error"]


@pytest.mark.parametrize("line", ["buttons", "click action_heal",
                                  "select ft_combo x"])
def test_the_verbs_report_a_closed_window(wished, tmp_path, line):   # noqa: F811
    rows = run_wish(tmp_path, ["close", line])
    row = by_event(rows, line.split()[0])[0]
    assert "no window is open" in row["error"]
