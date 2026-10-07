"""A Pools of Darkness acceptance run can snapshot and restore at a screen
reached by key presses: the boot survives DOSBox-X's start-up text screen,
the title is left by its own `PLAY` key rather than by Escape, and a
`snapshot` may follow a `press` once the screen holds still."""

import pytest

from tests.dos.test_dosacceptance import _fake_run, _run_args, _Session, _Slot
from tools.dos import acceptance as da
from tools.dos import dospod


class _Clock:
    """`time.monotonic` and `time.sleep` on one fake clock."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(da.time, "monotonic", c)
    monkeypatch.setattr(da.time, "sleep", c.sleep)
    return c


class _Frame:
    def __init__(self, name):
        self.name, self.px = name, name.encode()

    def digest(self, rect=None):
        return self.name


def _steps(*texts):
    return [da.parse_step(t) for t in texts]


# -- 1. the boot waits out the start-up text screen ---------------------------


class _TextFirst:
    """`XSession.boot` whose closing settle grabbed the DOS text screen, which
    then gives way to the game's line-doubled screen after `text` grabs."""

    def __init__(self, text):
        self.text, self.calls = text, []

    def boot(self, fresh=True):
        self.calls.append("boot")
        raise da.dosboxx.NotLineDoubled("block at (0,2) is not one pixel")

    def capture(self):
        self.calls.append("capture")
        if self.text:
            self.text -= 1
            raise da.dosboxx.NotLineDoubled("block at (0,2) is not one pixel")
        return _Frame("title")

    def settle(self, *a, **k):
        self.calls.append("settle")


def test_the_boot_waits_out_a_start_up_text_screen(clock):
    s = _TextFirst(3)
    da.boot_session(s)
    assert s.calls == ["boot"] + ["capture"] * 4 + ["settle"]


def test_a_text_screen_that_never_goes_still_stops_the_boot(clock):
    s = _TextFirst(10 ** 6)
    with pytest.raises(da.dosboxx.NotLineDoubled, match="still no line-doubled"):
        da.boot_session(s, timeout=30.0)
    assert clock.t >= 30.0


def test_a_darkness_snapshot_run_gets_past_a_text_screen_at_boot(monkeypatch, tmp_path,
                                                                 clock):
    """The run then fails at the faked menu, not at the boot."""
    import json
    _fake_run(monkeypatch, tmp_path, menu_error=TimeoutError("past the boot"))
    monkeypatch.setattr(da.dospod, "find_game", lambda stem: tmp_path / "game")
    log: list[str] = []

    class Booting(_Session):
        def boot(self, fresh=False):
            raise da.dosboxx.NotLineDoubled("block at (0,2) is not one pixel")

        def capture(self):
            return _Frame("title")

        def settle(self, *a, **k):
            pass

    monkeypatch.setattr(da.dosboxx, "claim", lambda note="": _Slot(log))
    monkeypatch.setattr(da.dossnapshot, "SnapshotSession",
                        lambda slot, game, **kw: Booting(tmp_path, log))
    args = _run_args(tmp_path, ["load", "press Down", "snapshot a", "press Return",
                                "restore a"])
    args.title = "darkness"
    assert da.run(args) == 1
    lost = json.loads((tmp_path / "out" / "summary.json").read_text())["lost"]
    assert "past the boot" in lost and "NotLineDoubled" not in lost


# -- 2. the PLAY DEMO bar gets PLAY, never Escape -----------------------------


class _Title:
    """Pools of Darkness from boot: the SSI logo, which ignores keys and goes
    by itself after `logo` looks, a credits screen that Escape advances, the
    credits with the `PLAY DEMO` bar, then the party menu, where Escape and a
    digit change nothing and Return would pick `Create New Character`."""

    def __init__(self, logo=4):
        self.looks, self.logo = 0, logo
        self.name, self.keys, self.escaped_title, self.created = "credits", [], False, False

    def screen(self):
        if self.looks < self.logo:
            return dospod.LOGO_SCREEN
        return dospod.PLAY_DEMO_SCREEN if self.name == "play" else self.name

    def key(self, k):
        self.keys.append(k)
        if self.looks < self.logo:
            return
        if self.name == "credits" and k == "Escape":
            self.name = "play"
        elif self.name == "play" and k in ("Escape", dospod.TITLE_PLAY):
            self.escaped_title = k == "Escape"
            self.name = "menu"
        elif self.name == "menu" and k == "Return":
            self.created = True

    def settle(self, quiet=0.5, timeout=8.0):
        self.looks += 1
        return _Frame(self.screen())

    def wait_for(self, pred, timeout=30.0):
        self.looks += 1
        return bool(pred(_Frame(self.screen())))


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(dospod.time, "sleep", lambda s: None)


def test_the_play_demo_bar_gets_play_and_no_escape(no_sleep):
    boot = _Title()
    assert dospod.to_party_menu(boot) == []
    assert boot.name == "menu" and not boot.escaped_title and not boot.created
    assert dospod.TITLE_PLAY in boot.keys and "Return" not in boot.keys


def test_escapes_the_logo_ignores_are_not_read_as_the_menu(no_sleep):
    """Three still frames on the logo would end the Escapes there, and the
    logo moving on would then read as a question being answered."""
    boot = _Title(logo=8)
    assert dospod.to_party_menu(boot) == []
    assert boot.name == "menu" and not boot.created and "Return" not in boot.keys


# -- 3. a snapshot may follow a press, once the screen holds still -----------


@pytest.mark.parametrize("steps", [
    ("load", "press Down", "press Down", "snapshot arena", "press Return",
     "restore arena", "press Return"),
    ("load", "press Down", "snapshot a", "restore a", "snapshot b"),
    # A restore puts back where its snapshot was, here the party menu.
    ("load", "snapshot menu", "press Down", "restore menu", "begin"),
])
def test_a_snapshot_or_restore_may_follow_a_press(steps):
    da.validate_steps(_steps(*steps), "darkness")


@pytest.mark.parametrize("steps, why", [
    (("load", "press Down", "snapshot a", "begin"), "may come after a press"),
    (("load", "prayer-watch 49", "snapshot a"), "no snapshot or restore after "
                                                "prayer-watch"),
])
def test_what_still_may_not_follow_a_press(steps, why):
    with pytest.raises(ValueError, match=why):
        da.validate_steps(_steps(*steps), "pool")


class _Screens:
    """A snapshot session whose captures run through `frames`, the last one
    repeating, each capture taking `step` seconds on the fake clock."""

    def __init__(self, tmp_path, clock, frames, restored="still", step=0.2):
        self.dir = tmp_path / "session"
        self.clock, self.frames, self.restored, self.step = clock, list(frames), restored, step
        self.log: list[str] = []
        self.taken = None

    def capture(self):
        self.clock.t += self.step
        name = self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]
        return _Frame(name)

    def snapshot(self, name):
        self.log.append(f"snapshot {name}")
        return self.dir / f"{name}.sav"

    def restore(self, name):
        self.log.append(f"restore {name}")
        self.frames = [self.restored]
        return []

    def settle(self, *a, **k):
        self.log.append("settle")

    def shot(self, *a, **k):
        return self.dir / "x.png"


def _pressed_driver(session):
    d = da.Driver(session, lambda **kw: None, "D", "darkness")
    d.where = "pressed"
    d.shot = lambda name: name
    return d


def test_a_snapshot_after_a_press_waits_for_the_screen_to_hold_still(tmp_path, clock):
    s = _Screens(tmp_path, clock, ["drawing1", "drawing2", "drawing3", "still"])
    d = _pressed_driver(s)
    got = d.snapshot("arena")
    assert got["screen"] == "still" and s.log == ["snapshot arena"]
    assert d.restore("arena")["screen"] == "still"


def test_a_screen_that_never_holds_still_is_not_snapshotted(tmp_path, clock):
    s = _Screens(tmp_path, clock, [f"frame{i}" for i in range(1000)])
    d = _pressed_driver(s)
    with pytest.raises(da.StepFailed, match="still changing"):
        d.snapshot("arena")
    assert s.log == []


def test_a_restore_that_brings_back_another_screen_fails(tmp_path, clock):
    s = _Screens(tmp_path, clock, ["still"], restored="elsewhere")
    d = _pressed_driver(s)
    d.snapshot("arena")
    with pytest.raises(da.StepFailed, match="not the one snapshot arena held"):
        d.restore("arena")
