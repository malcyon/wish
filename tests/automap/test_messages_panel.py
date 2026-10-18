"""`MessagesPanel` following the newest line, and when it must not.

`#349 (The Messages window does not follow the newest line during a fight, so
the log has to be dragged to be read)`. Donald's ruling settled the design:
*"Scroll when it's already at the bottom."* -- so the panel follows only while
the reader has not scrolled away, and a reader who scrolled up on purpose is
left where they put themselves.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from automap.panel import MessagesPanel


def make_root():
    from PyQt6.QtWidgets import QMainWindow

    from wish.ui_window import Ui_WishWindow
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    return root


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _panel_with_room(app) -> MessagesPanel:
    """A `MessagesPanel` whose list has a real, on-screen size.

    Built against a root that has never been shown, the list's viewport
    reports no size at all, so its scrollbar never has a maximum above zero --
    which would make every one of the three cases below pass whether or not
    following worked, because "at the bottom" and "empty" look the same. Only
    `root.show()` with a real size gives the list a viewport small enough that
    the lines it holds actually overflow it.
    """
    root = make_root()
    root.resize(900, 700)
    root.show()
    app.processEvents()
    panel = MessagesPanel(root)
    assert panel.list is not None
    return panel


def _fill(panel: MessagesPanel, app, n: int = 60) -> None:
    """More lines than the list's own window holds."""
    for i in range(n):
        panel.say(f"line {i}", dedup=False)
    app.processEvents()


def _at_bottom(panel: MessagesPanel) -> bool:
    bar = panel.list.verticalScrollBar()
    return bar.value() >= bar.maximum()


def test_the_view_at_the_bottom_stays_there_as_lines_arrive(app):
    panel = _panel_with_room(app)
    _fill(panel, app)
    bar = panel.list.verticalScrollBar()
    assert bar.maximum() > 0, "the list did not overflow -- the test proves nothing"
    assert _at_bottom(panel)

    panel.say("one more line", dedup=False)
    app.processEvents()

    assert _at_bottom(panel)


def test_a_reader_scrolled_up_is_not_yanked_back_by_the_next_line(app):
    """The behaviour a naive `scrollToBottom()`-on-every-line fix breaks."""
    panel = _panel_with_room(app)
    _fill(panel, app)
    bar = panel.list.verticalScrollBar()
    bar.setValue(0)
    app.processEvents()
    assert bar.value() == 0 and not _at_bottom(panel)

    panel.say("a line that arrives while scrolled up", dedup=False)
    app.processEvents()

    assert bar.value() == 0, "the view moved even though the reader scrolled away"


def test_scrolling_back_to_the_bottom_by_hand_resumes_following(app):
    panel = _panel_with_room(app)
    _fill(panel, app)
    bar = panel.list.verticalScrollBar()
    bar.setValue(0)
    app.processEvents()

    bar.setValue(bar.maximum())
    app.processEvents()
    assert _at_bottom(panel)

    panel.say("following resumes", dedup=False)
    app.processEvents()

    assert _at_bottom(panel)


def test_a_withdrawn_line_leaves_the_panel_and_can_be_said_again(app):
    panel = _panel_with_room(app)
    row = panel.say("Waiting to connect...")
    panel.withdraw(row)
    assert panel.lines() == []
    panel.say("Waiting to connect...")
    assert len(panel.lines()) == 1


def test_a_line_that_is_no_longer_newest_is_not_withdrawn(app):
    panel = _panel_with_room(app)
    first = panel.say("Line A")
    panel.say("Line B")
    panel.withdraw(first)
    assert [line.split("  ", 1)[1] for line in panel.lines()] == [
        "Line A", "Line B"]


def test_a_repeated_action_result_is_its_own_row(app):
    from automap import actions as engine
    from automap.actionbar import ActionBar
    from automap.target import MemoryTarget

    class Repeat(engine.Action):
        name, label, description, combat_legal = "heal", "Repeat", "d", True

        def legality(self, target):
            return engine.Verdict(True)

        def run(self, target, **kwargs):
            return engine.Outcome(True, "Removed quickfight from 1 character.", ())

    panel = _panel_with_room(app)
    bar = ActionBar(make_root(), actions=[Repeat()], say=panel.say)
    bar.attach(MemoryTarget())
    action = bar.actions[0]
    bar.run(action)
    bar.run(action)
    lines = panel.lines()
    assert len(lines) == 2
    assert all("Removed quickfight from 1 character." in t for t in lines)


def test_the_connections_repeated_status_line_is_still_shown_once(app):
    panel = _panel_with_room(app)
    panel.say("Waiting to connect...")
    panel.say("Waiting to connect...")
    assert len(panel.lines()) == 1
