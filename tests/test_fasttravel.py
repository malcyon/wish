"""The Fast Travel row against a machine that is only momentarily unsafe.

`FastTravel` may only enter `NEWECL` from `DUNGEON`'s key-wait loop, and the
row used to ask that question of the button: one sample of the program counter
every refresh, and about 3% of idle samples land in the KERNAL's interrupt path
-- so the button went grey for a second at a time with the party standing still
(#152). Donald's design is to wait after the click instead, so these tests are
about the two halves of that: the button no longer moves when the PC does, and
a click that arrives at a bad microsecond pauses and then travels.

The wait can never be the reason nothing happens, so the other two are the ways
out of it -- a game that is genuinely busy, and a connection that dies while a
click is waiting on it.

Qt widgets, offscreen: `tests/conftest.py` builds the one `QApplication` the
session shares. `make_root` and `machine` are the small helpers
`tests/test_debugmode.py` carries too, kept local so this file does not reach
into a test module another change owns.
"""

from __future__ import annotations

import time

import pytest

from automap import actionbar, actions
from automap.target import MemoryTarget, NotConnected
from goldbox import games

WORLD, COMBAT = 1, 2                    # $6E11: DUNGEON, COMBAT
IN_THE_LOOP = 0x10C2                    # a PC a fast travel will accept
IN_THE_IRQ = 0xEA34                     # the KERNAL's jiffy-clock update


def make_root():
    from PyQt6.QtWidgets import QMainWindow

    from wish.ui_window import Ui_WishWindow
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    return root


class Machine(MemoryTarget):
    """A `MemoryTarget` with a CPU whose PC the test scripts, look by look.

    `answers` is a queue the test fills immediately before the call it is
    about -- building the row and picking an area both refresh, and under the
    old code a refresh consumed a look, so anything set at construction was
    long gone by the time the interesting call ran. When the queue is empty the
    machine answers `resting`, which is where a 6502 sitting at the game's own
    key prompt spends almost all its time.

    `LOST` in either place raises `NotConnected` instead: the connection given
    up on, which every later call through a `ViceTarget` does (#151).
    """

    LOST = object()

    def __init__(self, memory=None, resting=IN_THE_LOOP):
        super().__init__(memory)
        self.answers: list = []
        self.resting = resting
        self.looks = 0
        self.jumps: list[int] = []

    def pc(self):
        want = self.answers.pop(0) if self.answers else self.resting
        self.looks += 1
        if want is self.LOST:
            raise NotConnected("the connection was given up on")
        return want

    def set_pc(self, address: int) -> None:
        self.jumps.append(address)


def machine(mode: int = WORLD, area: int = 0, disk: int = 3,
            resting=IN_THE_LOOP, indoors: int = 1) -> Machine:
    """A party standing in an area, ready to be travelled out of."""
    return Machine({games.MODE_FLAG_POOL: bytes([mode]),
                    actions.FASTTRAVEL_SLOT: bytes([area]),
                    actions.FASTTRAVEL_DISK: bytes([disk]),
                    actions.FASTTRAVEL_INDOORS: bytes([indoors]),
                    actions.FASTTRAVEL_X: bytes([5, 6, 1])}, resting=resting)


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def row(app, target=None, **kw):
    from automap.actionbar import FastTravelBar
    bar = FastTravelBar(make_root(), **kw)
    if target is not None:
        bar.attach(target)
    return bar


def somewhere_else(bar):
    """Pick an area the party is not already in, so legality gets that far."""
    bar.combo.setCurrentIndex(bar.rows.index(actions.area_by_id(13)))


# --- the button no longer moves when the program counter does ----------------

def test_a_moment_in_the_interrupt_handler_does_not_grey_the_button(app):
    """What Donald sees today: the party is standing still at the game's own
    key prompt, nothing is happening, and once every thirty seconds or so the
    Fast Travel button goes grey and comes back a second later. The refresh
    that greyed it caught the 6502 in the KERNAL's jiffy-clock update, which is
    tens of microseconds long and nothing to do with the game.

    Three refreshes over a machine that would answer `$EA34` to the first of
    them. The button is enabled through all three, and its tooltip stays the
    warning rather than flashing an address nobody can read in time -- and the
    refresh does not ask for the PC at all, which is what makes that true
    however long the interrupt handler runs for.
    """
    target = machine()
    bar = row(app, target)
    somewhere_else(bar)
    target.answers = [IN_THE_IRQ]
    target.looks = 0
    seen = []
    for _ in range(3):
        bar.refresh()
        seen.append((bar.button.isEnabled(), bar.button.toolTip()))
    assert [ok for ok, _tip in seen] == [True, True, True], seen
    assert {tip for _ok, tip in seen} == {actionbar.DANGER}
    assert target.looks == 0, "the button is still deciding on the PC"


def test_the_mode_flag_still_disables_the_button(app):
    """The gate that was kept. `$6E11` is 2 -- a fight -- and it is stable and
    reliable, so it does what it always did whatever the PC says."""
    bar = row(app, machine(mode=COMBAT))
    somewhere_else(bar)
    assert not bar.button.isEnabled()
    assert "$6E11 is 2" in bar.button.toolTip()


def test_the_mode_flag_is_read_once_per_refresh(app):
    """`ActionBar` reads each address once a refresh through `_OnePoll`; this
    row asked `$6E11` three times -- the dropdown's gate, `Action`'s own and
    `FastTravel`'s. Each read stops the machine and resumes it, handing the
    emulation ~14.3 ms of extra emulated time, so three a second is about 43 ms
    a second of the game running faster than it should (#152)."""
    target = machine()
    bar = row(app, target)
    somewhere_else(bar)
    target.reads.clear()
    bar.refresh()
    assert sum(1 for addr, _n in target.reads
               if addr == games.MODE_FLAG_POOL) == 1, target.reads


# --- and the click waits instead ---------------------------------------------

def test_a_click_in_that_moment_waits_and_then_travels(app):
    """The other half of the same second: the user clicks while the machine is
    in the interrupt handler. Nothing is refused -- the click waits for the PC
    to come back to the key-wait loop, which on a real machine is the next look
    because every look hands the emulation ~14.3 ms, and then travels."""
    target = machine()
    bar = row(app, target)
    somewhere_else(bar)
    target.answers = [IN_THE_IRQ, IN_THE_IRQ]       # back in the loop after
    target.looks = 0
    outcome = bar.run()
    assert outcome is not None and outcome.ok, outcome
    assert target.jumps == [actions.NEWECL_TAIL]
    assert target.looks >= 3, "the click did not wait for the PC"


def test_the_wait_gives_up_rather_than_hanging(app, monkeypatch):
    """A game that is genuinely busy -- loading, or running a script -- never
    comes back to the key prompt, and a button that waited for ever would be a
    frozen window. The wait has a limit, and running out of it is a refusal in
    the messages panel with nothing written.

    `WAIT_SECONDS` is shortened here so the suite does not sit for two seconds:
    what is asserted is the behaviour the limit produces -- that the call ends,
    refuses and writes nothing -- and not the number.
    """
    monkeypatch.setattr(actionbar, "WAIT_SECONDS", 0.1)
    said = []
    target = machine(resting=IN_THE_IRQ)            # never comes back
    bar = row(app, target, say=lambda text, detail="", alarm=False:
              said.append((text, alarm)))
    somewhere_else(bar)
    started = time.monotonic()
    outcome = bar.run()
    took = time.monotonic() - started
    assert outcome is not None and not outcome.ok
    assert outcome.message == actionbar.FastTravelBar.STILL_BUSY
    assert target.jumps == [] and outcome.writes == ()
    assert said and said[-1][1] is True, "a refusal is an alarm in the panel"
    assert took < 5.0, f"the wait did not end: {took:.1f}s"


def test_a_connection_lost_mid_wait_ends_the_wait_rather_than_spinning(app):
    """The hazard the wait was written around. A target that has given up
    raises `NotConnected` from every later call (#151), and the wait is a loop
    of calls, so it is exactly where that lands.

    It ends there and then rather than spinning to the deadline, which is what
    the timing assertion is for: the real `WAIT_SECONDS` is left alone, and a
    loop that swallowed the failure would take all of it.

    Only the CPU is dead here, deliberately. A target whose reads failed as
    well would be refused by the mode flag before the wait ever started, and it
    is the wait's own handling that is in question.
    """
    said = []
    target = machine(resting=Machine.LOST)
    bar = row(app, target, say=lambda text, detail="", alarm=False:
              said.append((text, alarm)))
    somewhere_else(bar)
    target.answers = [IN_THE_IRQ]      # one look, and then it is gone
    started = time.monotonic()
    outcome = bar.run()
    took = time.monotonic() - started
    assert outcome is not None and not outcome.ok
    assert outcome.message == actionbar.FastTravelBar.LOST_WHILE_WAITING
    assert target.jumps == []
    assert said and said[-1][1] is True
    assert took < actionbar.WAIT_SECONDS / 2, (
        f"the wait spun on a dead connection for {took:.2f}s")


def test_a_messages_panel_line_opens_with_a_capital(app):
    """Donald, 2026-08-31: *"I want us to start making sure we capitalize the
    phrases that are going into the Messages panel. It looks more
    professional."*

    Pinned on the composed line rather than on the strings, because the first
    word is the caller's -- `_report("fast travel", ...)` here and
    `action.label.lower()` on the action bar -- so capitalising every message
    string would leave the prefix lowercase and change nothing a user sees.
    """
    said: list[str] = []
    bar = row(app, say=lambda text, detail="", alarm=False: said.append(text))
    bar._report("fast travel",
                actions.Outcome(False, actionbar.FastTravelBar.STILL_BUSY))
    assert said[-1] == ("Fast travel: the game was busy and nothing was "
                        "written; try again in a moment.")
