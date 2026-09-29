"""`defeatdrive.leave_after` takes the post-combat menu out to the world.

The mercy heal at `POST.COM $1544` runs after the losing side's menus, so the
driver has to press `EXIT` at `VIEW POOL EXIT`, answer `LEAVE TREASURE`, and
call the run finished only when the mode byte went from 5 to 1 (`#648`).
Nothing here needs an emulator: the session is a script of readings.
"""
from types import SimpleNamespace

from conftest import load_tools_module

defeatdrive = load_tools_module("defeatdrive")
S = defeatdrive.S


class Log:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


class Script:
    """Each reading is `(mode, kind, bar text)`; the last one repeats."""

    def __init__(self, readings):
        self.readings = list(readings)
        self.at = 0
        self.pressed = []

    def _now(self):
        return self.readings[min(self.at, len(self.readings) - 1)]

    def mode(self):
        return self._now()[0]

    def screen(self):
        return None

    def combat_state(self, s):
        _, kind, text = self._now()
        return SimpleNamespace(kind=kind, text=text)

    def combat_bar(self, label, timeout=0.0):
        self.pressed.append(label)
        self.at += 1
        return True

    def press_kernal(self, code):
        self.pressed.append(code)
        self.at += 1

    def await_change(self, was, timeout=0.0):
        return True

    def idle(self, seconds):
        self.at += 1


def test_exit_then_leave_treasure_then_mode_five_to_one_is_success():
    sess = Script([
        (5, S.BAR_EXIT, "VIEW POOL EXIT"),
        (5, S.BAR_LEAVE, "GO BACK LEAVE TREASURE"),
        (5, S.BAR_BLANK, ""),
        (1, S.BAR_BLANK, ""),
    ])
    log = Log()
    assert defeatdrive.leave_after(sess, log, 5.0, 0.0) is True
    assert sess.pressed == ["EXIT", "LEAVE"]
    assert [kw["value"] for k, kw in log.events if k == "mode"] == [5, 1]


def test_mode_one_without_ever_seeing_five_is_not_the_checkpoint():
    sess = Script([(1, S.BAR_BLANK, "")])
    assert defeatdrive.leave_after(sess, Log(), 0.05, 0.0) is False
    assert sess.pressed == []


def test_an_exit_bar_that_is_not_the_pool_menu_is_left_alone():
    sess = Script([(5, S.BAR_EXIT, "GUARD DELAY EXIT")])
    assert defeatdrive.leave_after(sess, Log(), 0.05, 0.0) is False
    assert sess.pressed == []


def test_a_bare_press_bar_is_answered_with_return_and_waited_out():
    sess = Script([
        (5, S.BAR_PRESS, "PRESS RETURN"),
        (5, S.BAR_BLANK, ""),
        (1, S.BAR_BLANK, ""),
    ])
    awaited = []
    sess.await_change = lambda was, timeout=0.0: awaited.append(was) or True
    assert defeatdrive.leave_after(sess, Log(), 5.0, 0.0) is True
    assert sess.pressed == [0x0D]
    assert awaited == ["PRESS RETURN"]


def test_mode_five_seen_but_never_one_is_not_success():
    sess = Script([(5, S.BAR_BLANK, "")])
    assert defeatdrive.leave_after(sess, Log(), 0.05, 0.0) is False


class Says(Log):
    def __init__(self):
        super().__init__()
        self.said = []

    def say(self, *a):
        self.said.append(a)


def test_a_leave_that_never_reached_the_world_has_its_own_exit_status():
    status = defeatdrive.leave_status(Script([(5, S.BAR_BLANK, "")]),
                                      Says(), 0.05, 0.0)
    assert status == defeatdrive.LEAVE_FAILED
    assert status not in (0, 1)


def test_a_leave_that_reached_the_world_exits_zero():
    sess = Script([(5, S.BAR_BLANK, ""), (1, S.BAR_BLANK, "")])
    assert defeatdrive.leave_status(sess, Says(), 5.0, 0.0) == 0


class Counting(Script):
    """A `Script` whose monitor records the checkpoint calls."""

    def __init__(self, readings, hits=6):
        super().__init__(readings)
        self.calls = []
        self.hits = hits

    def mon(self, timeout=5.0):
        return Mon(self)


class Mon:
    def __init__(self, owner):
        self.owner = owner

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def checkpoint_set(self, address, *, exec_=False, stop=True, **kw):
        self.owner.calls.append(("set", address, exec_, stop))
        return 7

    def checkpoint_hits(self, cp):
        self.owner.calls.append(("hits", cp))
        return self.owner.hits

    def checkpoint_delete(self, cp):
        self.owner.calls.append(("delete", cp))


def test_a_heal_counter_is_armed_at_mode_five_read_at_mode_one_and_deleted():
    sess = Counting([(5, S.BAR_BLANK, ""), (1, S.BAR_BLANK, "")])
    log = Log()
    assert defeatdrive.leave_after(sess, log, 5.0, 0.0) is True
    assert sess.calls == [("set", 0x1549, True, False), ("hits", 7), ("delete", 7)]
    assert [kw for k, kw in log.events if k == "mercy_heal"] == [{"hits": 6}]


def test_no_heal_counter_is_armed_before_the_post_combat_mode():
    sess = Counting([(1, S.BAR_BLANK, "")])
    assert defeatdrive.leave_after(sess, Log(), 0.05, 0.0) is False
    assert sess.calls == []
