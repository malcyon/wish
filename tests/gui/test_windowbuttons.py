"""`tools/gui/windowbuttons.py` lists a window's buttons and presses them for real."""

import os
import pathlib
import sys
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from PyQt6.QtWidgets import QApplication, QInputDialog, QMainWindow

from automap import actions as engine
from automap.actionbar import ActionBar, FastTravelBar
from automap.panel import MessagesPanel, RosterPanel
from automap.target import MemoryTarget
from tools.gui import windowbuttons
from wish.ui_window import Ui_WishWindow


class Plain(engine.Action):
    name, label, description, combat_legal = "heal", "Plain", "d", True

    def legality(self, target):
        return engine.Verdict(True)

    def run(self, target, **kwargs):
        target.write(0x10, b"\x01")
        return engine.Outcome(True, "Plain done.", ((0x10, b"\x01"),))


class Asking(Plain):
    name, label, confirm = "store-spells", "Asking", "Really?"

    def run(self, target, **kwargs):
        target.write(0x20, b"\x02")
        return engine.Outcome(True, "Asked and done.", ((0x20, b"\x02"),))


class Off(Plain):
    name, label = "restore-spells", "Off"

    def legality(self, target):
        return engine.Verdict(False, "not now")


@pytest.fixture
def window():
    QApplication.instance() or QApplication([])
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    messages = MessagesPanel(root)
    bar = ActionBar(root, actions=[Plain(), Asking(), Off()], say=messages.say)
    target = MemoryTarget()
    bar.attach(target)
    return SimpleNamespace(
        root=root, messages=messages, actions_bar=bar, target=target,
        fasttravel_bar=FastTravelBar(root, say=messages.say),
        roster=RosterPanel(root))


def named(rows, name):
    return next(r for r in rows if r["name"] == name)


def test_rows_lists_every_kind_of_button(window):
    rows = windowbuttons.rows(window)
    names = {r["name"] for r in rows}
    assert {"action_heal", "action_store", "action_restore", "ft_button",
            "ft_back_button", "card_0_level_up", "card_7_level_up"} <= names
    heal = named(rows, "action_heal")
    assert (heal["text"], heal["enabled"], heal["visible"]) == ("Plain", True, True)
    off = named(rows, "action_restore")
    assert off["enabled"] is False and off["tooltip"] == "not now"
    assert named(rows, "card_0_level_up")["visible"] is False


def test_a_disabled_button_is_not_clicked(window):
    out = windowbuttons.click(window, "action_restore")
    assert out["error"] == "button is disabled"
    assert window.actions_bar.last is None


def test_a_hidden_button_and_an_unknown_name_are_errors(window):
    assert windowbuttons.click(window, "card_0_level_up")["error"] == "button is hidden"
    assert windowbuttons.click(window, "nope")["error"] == "no such button"


def test_a_plain_click_runs_the_action_and_returns_the_new_lines(window):
    out = windowbuttons.click(window, "action_heal")
    assert out["error"] is None and out["dialog"] is None
    assert window.target.read(0x10, 1) == b"\x01"
    assert [m.split("  ", 1)[1] for m in out["messages"]] == ["Plain done."]
    assert named(out["buttons"], "action_heal")["enabled"]


def test_a_question_answered_no_writes_nothing(window):
    out = windowbuttons.click(window, "action_store", answer="no")
    assert out["dialog"] == {"kind": "question", "text": "Really?", "answer": "no"}
    assert window.target.read(0x20, 1) == b"\x00"
    assert out["messages"] == []


def test_no_answer_defaults_to_no(window):
    out = windowbuttons.click(window, "action_store")
    assert out["dialog"]["answer"] == "no"
    assert window.target.read(0x20, 1) == b"\x00"


def test_a_question_answered_yes_runs_the_action(window):
    out = windowbuttons.click(window, "action_store", answer="yes")
    assert out["dialog"]["answer"] == "yes"
    assert window.target.read(0x20, 1) == b"\x02"
    assert out["messages"][-1].endswith("Asked and done.")


def test_the_spell_dialog_is_answered_with_the_chosen_label(window):
    chosen = []
    card = window.roster.cards[0]
    parent = card.level_up
    while parent is not None and parent is not window.root:
        parent.show()
        parent = parent.parentWidget()
    card.level_up.setEnabled(True)
    card.level_up.clicked.connect(lambda _c=False: chosen.append(
        QInputDialog.getItem(window.root, "wish", "A learns one new spell:",
                             ["Bless", "Sleep"], 0, False)))
    out = windowbuttons.click(window, "card_0_level_up", spell="Sleep")
    assert out["error"] is None, out["error"]
    assert chosen == [("Sleep", True)]
    assert out["dialog"]["items"] == ["Bless", "Sleep"]
    assert out["dialog"]["text"] == "A learns one new spell:"
    # Without a pick the dialog is cancelled.
    out = windowbuttons.click(window, "card_0_level_up")
    assert chosen[-1][1] is False


def test_the_real_window_lists_its_buttons_and_does_not_click_a_greyed_one(
        tmp_path, monkeypatch):
    """`AutomapBinding` has the attributes `rows` and `click` read; an Amiga
    target leaves every Action button disabled."""
    from gamedata import synthetic_geo

    from automap import c64
    from automap.area import RESIDENT_GEO
    from automap.state import Automapper
    from automap.window import AutomapBinding
    from goldbox.geo import Geo

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    class NotAC64(MemoryTarget):
        c64_memory = False

    QApplication.instance() or QApplication([])
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    geo = Geo(synthetic_geo())
    target = NotAC64({0xD011: bytes([0x1B]), 0xD018: bytes([0x15]),
                      0xDD00: bytes([0x17]),
                      c64.DEFAULT.live_position: bytes((4, 5, 0)),
                      RESIDENT_GEO: geo.to_bytes()})
    binding = AutomapBinding(root, Automapper(target, {"GEO00": geo}))
    for _ in range(24):
        binding.tick()
    rows = windowbuttons.rows(binding)
    assert named(rows, "action_heal")["enabled"] is False
    assert windowbuttons.click(binding, "action_heal")["error"] == "button is disabled"
