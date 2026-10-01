"""A paladin's sheet that never opened is a failed step, not a `False` answer.

`#699`: two live runs of `curedrive.py run --who MARK --script "read;sheet"`
failed to open MARK's individual sheet (a stale `bank_ids` cache made the
underlying screen unreadable, `tests/c64/test_screenbank.py`'s
`test_a_transport_failure_asking_for_the_banks_is_not_remembered`), yet both
runs still logged `{"event": "sheet", "cure_offered": false}` and exited 0.
`Run.open_sheet` already refuses a screen that is not the sheet and returns
`None` -- what was missing is that `Run.sheet` and `Run.cure` took that `None`
as a negative answer instead of a failure.  Nothing here needs an emulator.
"""

import io

from conftest import load_tools_module

CD = load_tools_module("curedrive")


def _bare_run(who: str = "MARK") -> "CD.Run":
    run = CD.Run.__new__(CD.Run)
    run.log_file = io.StringIO()
    run.who = who
    run.n = 0
    run.out = None
    return run


def _events(run: "CD.Run") -> list[dict]:
    import json
    return [json.loads(line) for line in run.log_file.getvalue().splitlines()]


def test_a_sheet_that_never_opened_raises_and_logs_no_cure_offered():
    run = _bare_run()
    run.open_sheet = lambda: None
    run.shot = lambda tag: tag
    run.close_sheet = lambda: None
    run.row24 = lambda: ""

    try:
        run.sheet()
        raised = False
    except RuntimeError:
        raised = True
    assert raised

    events = _events(run)
    assert all("cure_offered" not in e for e in events)
    assert any(e["event"] == "sheet-not-opened" for e in events)


def test_cure_on_a_sheet_that_never_opened_raises_and_logs_no_verdict():
    run = _bare_run()
    run.open_sheet = lambda: None
    run.shot = lambda tag: tag
    run.close_sheet = lambda: None
    run.row24 = lambda: ""

    try:
        run.cure()
        raised = False
    except RuntimeError:
        raised = True
    assert raised

    events = _events(run)
    assert not any(e["event"] == "cure-not-offered" for e in events)
    assert any(e["event"] == "sheet-not-opened" for e in events)


def test_cure_on_a_genuinely_opened_sheet_without_cure_still_logs_not_offered():
    run = _bare_run()
    run.open_sheet = lambda: "VIEW:ITEMS EXIT"
    run.shot = lambda tag: tag
    run.close_sheet = lambda: None
    run.row24 = lambda: ""

    result = run.cure()

    assert result == {"cured": False, "bar": "VIEW:ITEMS EXIT"}
    events = _events(run)
    assert any(e["event"] == "cure-not-offered" for e in events)
    assert not any(e["event"] == "sheet-not-opened" for e in events)


class _Screen:
    def __init__(self, rows: dict[int, str]):
        self._rows = rows

    def row(self, n: int) -> str:
        return self._rows.get(n, "")


class _Session:
    """Confirms the sheet once, then goes on to press `VIEW`."""

    def __init__(self, confirmed: _Screen):
        self._confirmed = confirmed

    def press_bar(self, word: str) -> bool:
        return True

    def screen(self) -> _Screen:
        return self._confirmed


def test_open_sheet_survives_a_glitched_second_read_after_confirming_exit():
    """The first read already confirmed EXIT and the paladin's name; a
    transient failure on the follow-up read alone must not turn that into
    a claim the sheet never opened (#699 code-review follow-up)."""
    who = "MARK"
    run = _bare_run(who)
    confirmed = _Screen({1: who, 24: "VIEW:ITEMS EXIT"})
    run.sess = _Session(confirmed)
    run.camp = lambda: True
    run.pick_paladin = lambda: True
    # The independent follow-up read glitches and comes back empty, the
    # way a transient screen-bank failure does.
    run.row24 = lambda: ""

    bar = run.open_sheet()

    assert bar == "VIEW:ITEMS EXIT"


def test_open_sheet_prefers_the_settled_second_read_when_it_succeeds():
    who = "MARK"
    run = _bare_run(who)
    confirmed = _Screen({1: who, 24: "VIEW:ITEMS EXIT"})
    run.sess = _Session(confirmed)
    run.camp = lambda: True
    run.pick_paladin = lambda: True
    run.row24 = lambda: "VIEW:ITEMS CURE EXIT"

    bar = run.open_sheet()

    assert bar == "VIEW:ITEMS CURE EXIT"


def test_heal_on_a_sheet_that_never_opened_raises_and_logs_no_verdict():
    run = _bare_run()
    run.open_sheet = lambda: None
    run.shot = lambda tag: tag
    run.close_sheet = lambda: None
    run.row24 = lambda: ""

    try:
        run.heal()
        raised = False
    except RuntimeError:
        raised = True
    assert raised

    events = _events(run)
    assert not any(e["event"] == "heal-not-offered" for e in events)
    assert any(e["event"] == "sheet-not-opened" for e in events)


def test_heal_on_a_genuinely_opened_sheet_without_heal_still_logs_not_offered():
    run = _bare_run()
    run.open_sheet = lambda: "VIEW:ITEMS CURE EXIT"
    run.shot = lambda tag: tag
    run.close_sheet = lambda: None
    run.row24 = lambda: ""

    result = run.heal()

    assert result == {"healed": False, "bar": "VIEW:ITEMS CURE EXIT"}
    events = _events(run)
    assert any(e["event"] == "heal-not-offered" for e in events)
    assert not any(e["event"] == "sheet-not-opened" for e in events)


def test_sheet_logs_heal_offered_next_to_cure_offered():
    run = _bare_run()
    run.open_sheet = lambda: "VIEW:ITEMS CURE HEAL EXIT"
    run.shot = lambda tag: tag
    run.close_sheet = lambda: None
    run.row24 = lambda: ""

    run.sheet()

    events = _events(run)
    sheet_events = [e for e in events if e["event"] == "sheet"]
    assert sheet_events and sheet_events[0]["cure_offered"] is True
    assert sheet_events[0]["heal_offered"] is True


def test_sheet_logs_heal_offered_false_when_only_cure_is_up():
    run = _bare_run()
    run.open_sheet = lambda: "VIEW:ITEMS CURE EXIT"
    run.shot = lambda tag: tag
    run.close_sheet = lambda: None
    run.row24 = lambda: ""

    run.sheet()

    events = _events(run)
    sheet_events = [e for e in events if e["event"] == "sheet"]
    assert sheet_events and sheet_events[0]["cure_offered"] is True
    assert sheet_events[0]["heal_offered"] is False


def test_rest_to_expiry_defaults_to_the_cure_row():
    run = _bare_run()
    run.conf = CD.TITLES["curse-of-the-azure-bonds"]
    run.read = lambda tag: {"rows": [
        {"mine": True, "id": 141, "minutes_left": 100},
        {"mine": True, "id": 140, "minutes_left": 40}]}
    calls = []
    run.rest = lambda d, h, m: calls.append((d, h, m))

    run.rest_to_expiry()

    events = _events(run)
    plan = [e for e in events if e["event"] == "expiry-plan"][0]
    assert plan["which"] == "cure"
    assert plan["minutes_left"] == 100


def test_rest_to_expiry_heal_selects_the_lay_on_hands_row():
    run = _bare_run()
    run.conf = CD.TITLES["curse-of-the-azure-bonds"]
    run.read = lambda tag: {"rows": [
        {"mine": True, "id": 141, "minutes_left": 100},
        {"mine": True, "id": 140, "minutes_left": 40}]}
    calls = []
    run.rest = lambda d, h, m: calls.append((d, h, m))

    run.rest_to_expiry("heal")

    events = _events(run)
    plan = [e for e in events if e["event"] == "expiry-plan"][0]
    assert plan["which"] == "heal"
    assert plan["minutes_left"] == 40


def test_play_routes_the_heal_verb_and_expire_heal_argument():
    run = _bare_run()
    calls = []
    run.heal = lambda: calls.append("heal")
    run.rest_to_expiry = lambda which="cure": calls.append(("expire", which))

    run.play("heal;expire heal;expire")

    assert calls == ["heal", ("expire", "heal"), ("expire", "cure")]


def test_open_sheet_returns_none_when_the_first_read_never_shows_exit(monkeypatch):
    who = "MARK"
    run = _bare_run(who)
    run.sess = _Session(_Screen({1: who, 24: "some other menu"}))
    run.camp = lambda: True
    run.pick_paladin = lambda: True
    run.row24 = lambda: "unreachable"
    # `open_sheet` polls for 30s; fast-forward the clock instead of
    # actually waiting.
    clock = [0.0]

    def fake_time():
        clock[0] += 1
        return clock[0]

    monkeypatch.setattr(CD.time, "time", fake_time)
    monkeypatch.setattr(CD.time, "sleep", lambda s: None)

    assert run.open_sheet() is None


class _TreasureSess:
    """A Silver Blades session standing at a treasure bar, recording every
    key; `opening_scene` is what `enter_world` read off the save."""

    game = None

    def __init__(self, bar: str, opening: bool):
        self.bar, self.opening_scene = bar, opening
        self.pressed: list = []
        outer = self

        class Kbd:
            def key(self, name, *a):
                outer.pressed.append(("key", name))

            def screenshot(self, path):
                return True

        self.kbd = Kbd()

    def screen(self):
        bar = self.bar

        class S:
            def text(self):
                return bar

            def row(self, n):
                return bar if n == 24 else ""
        return S()

    def handle_prompt(self, s=None):
        return False

    def select_bar(self, label, **kw):
        self.pressed.append(("bar", label))
        return False

    press_bar = select_bar

    def press_kernal(self, code):
        self.pressed.append(("kernal", code))

    def to_world_bar(self, **kw):
        self.pressed.append(("to_world_bar",))
        return False

    def log(self, *a):
        pass


def _silver_run(monkeypatch, tmp_path, sess):
    from tools.secret_of_the_silver_blades import ssbsession
    monkeypatch.setattr(ssbsession, "load_party", lambda s, **kw: True)
    monkeypatch.setattr(ssbsession, "Addresses", lambda game, disks: None)
    monkeypatch.setattr(ssbsession, "enter_world", lambda s, a, **kw: True)
    monkeypatch.setattr(CD.time, "sleep", lambda s: None)
    run = _bare_run()
    run.out = tmp_path
    run.sess, run.disks = sess, "disks"
    return run


def test_a_fights_treasure_bar_on_arrival_is_not_left_behind(
        monkeypatch, tmp_path):
    """A won fight's `VIEW TAKE POOL SHARE EXIT` on arrival: leaving it would
    discard the treasure, so no key is pressed and the arrival fails saying
    why (#801)."""
    sess = _TreasureSess("VIEW TAKE POOL SHARE EXIT", opening=False)
    run = _silver_run(monkeypatch, tmp_path, sess)
    assert run._enter_silver(wait=10.0) is False
    assert sess.pressed == []
    stuck = [e for e in _events(run)
             if e["event"] == "never-reached-the-world-bar"]
    assert stuck and "discard" in stuck[0]["why"]


def test_a_leave_question_on_arrival_keeps_the_treasure(monkeypatch,
                                                        tmp_path):
    sess = _TreasureSess("GO BACK LEAVE TREASURE", opening=False)
    run = _silver_run(monkeypatch, tmp_path, sess)
    assert run._enter_silver(wait=10.0) is False
    assert ("bar", "LEAVE TREASURE") not in sess.pressed


def test_the_world_bar_after_clear_messages_is_arrival(monkeypatch, tmp_path):
    from tools.secret_of_the_silver_blades import ssbsession
    sess = _TreasureSess("MOVE VIEW CAST AREA ENCAMP SEARCH LOOK", False)
    run = _silver_run(monkeypatch, tmp_path, sess)
    monkeypatch.setattr(ssbsession, "clear_messages",
                        lambda s, **kw: "MOVE VIEW CAST AREA ENCAMP SEARCH LOOK")
    assert run._enter_silver(wait=10.0) is True
    assert sess.pressed == []
