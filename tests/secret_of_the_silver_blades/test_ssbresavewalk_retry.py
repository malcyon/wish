"""The Silver Blades resave walk takes its step from a snapshot and retries."""
import pathlib

import pytest

from tools.secret_of_the_silver_blades import ssbresavewalk


class FakeSession:
    """Meets a fight on the first `fights` attempts, then walks."""

    save_disk = "/slot/SIDE0.D64"

    def __init__(self, fights: int, retries: int = 3):
        self.fights = fights
        self.retries = retries
        self.attempts = 0
        self.restores = 0
        self.attached = []
        self.walk_retries = 0
        self.walk_refused = None
        self.pos = 5
        self.events = []
        self.in_combat = False

    def square(self):
        return self.pos

    def attach(self, path):
        self.attached.append(path)
        self.events.append("attach")

    def walk_with_retry(self, moves, retries=3, force_restores=0):
        self.walk_retries = 0
        self.asked_forced = force_restores
        self.fights = max(self.fights, force_restores)
        self.events.append("walk")
        if self.in_combat:
            self.walk_refused = "the game is already in combat"
            return False
        for attempt in range(retries + 1):
            self.attempts += 1
            if self.attempts > self.fights:
                self.pos += 1
                return True
            self.restores += 1
            self.walk_retries = attempt + 1
        self.walk_refused = f"an encounter began on each attempt at {moves!r}"
        return False


def test_a_lost_fight_restores_and_the_retry_walks():
    sess = FakeSession(fights=1)
    moved, restores = ssbresavewalk.walk_square(sess, "I")
    assert (moved, restores) == (True, 1)
    assert sess.attached == [sess.save_disk]


def test_a_walk_with_no_fight_restores_nothing_and_attaches_nothing():
    sess = FakeSession(fights=0)
    assert ssbresavewalk.walk_square(sess, "I") == (True, 0)
    assert sess.attached == []


def test_a_walk_that_fails_every_retry_stops_with_the_reason():
    sess = FakeSession(fights=99)
    with pytest.raises(RuntimeError, match="walk I stopped: an encounter began on each attempt"):
        ssbresavewalk.walk_square(sess, "I")
    assert sess.attached == []


def test_the_disk_is_attached_once_and_only_after_the_walk_that_restored():
    sess = FakeSession(fights=2)
    ssbresavewalk.walk_square(sess, "I")
    assert sess.events == ["walk", "attach"]


def test_a_walk_begun_in_combat_reports_that_and_attaches_nothing():
    sess = FakeSession(fights=0)
    sess.in_combat = True
    with pytest.raises(RuntimeError, match="already in combat") as e:
        ssbresavewalk.walk_square(sess, "I")
    assert "every time" not in str(e.value)
    assert sess.attached == []


def test_a_forced_restore_restores_once_and_walks_the_leg_again():
    sess = FakeSession(fights=0)
    moved, restores = ssbresavewalk.walk_square(sess, "I", force_restore=True)
    assert (moved, restores) == (True, 1)
    assert sess.asked_forced == 1
    assert sess.attached == [sess.save_disk]


def test_the_force_restore_option_is_off_by_default():
    sess = FakeSession(fights=0)
    ssbresavewalk.walk_square(sess, "I")
    assert sess.restores == 0
    assert not getattr(sess, "asked_forced", 0)


class _Kbd:
    def __init__(self):
        self.shots = []

    def screenshot(self, path, **kw):
        self.shots.append(pathlib.Path(path).name)
        return True


class _RunSession:
    """Enough of `SSBSession` for `main` to run past the walk to the resave."""

    save_disk = "/slot/SIDE0.D64"
    game = None

    def __init__(self, resaved):
        self.resaved = resaved
        self.kbd = _Kbd()

    def boot(self):
        return True

    def settle(self, seconds=6.0):
        pass

    def status(self):
        return None

    def square(self):
        return (3, 3)

    def save_game(self):
        return self.resaved

    def close(self):
        pass


class _Slot:
    n, display = 9, ":99"

    def release(self):
        pass


def _run_main(monkeypatch, tmp_path, *, resaved, moved=True, restores=1,
              force=True):
    sess = _RunSession(resaved)
    w = ssbresavewalk
    # `main` sets these for the emulator; monkeypatch puts them back after.
    for name in ("QT_QPA_PLATFORM", "GDK_BACKEND", "POR_HEADLESS"):
        monkeypatch.setenv(name, "x")
    for name in ("WAYLAND_DISPLAY", "XDG_SESSION_TYPE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(w.S, "claim_slot", lambda *a, **k: _Slot())
    monkeypatch.setattr(w.S, "copy_closed_disk", lambda *a, **k: None)
    monkeypatch.setattr(w.ssbsession, "stage", lambda *a, **k: "boot.d64")
    monkeypatch.setattr(w.ssbsession, "SSBSession", lambda *a, **k: sess)
    monkeypatch.setattr(w.ssbsession, "load_party", lambda s: True)
    monkeypatch.setattr(w.ssbsession, "Addresses", lambda *a: None)
    monkeypatch.setattr(w, "arrive", lambda *a, **k: "world")
    monkeypatch.setattr(w, "panel", lambda s: ([], []))
    monkeypatch.setattr(w, "sheet_workaround", lambda *a: ["sheet"])
    monkeypatch.setattr(w, "walk_square",
                        lambda s, move, force_restore=False: (moved, restores))
    monkeypatch.setattr(w, "walk_step_routed", lambda *a: "world")
    out = tmp_path / "out"
    argv = ["--disks", str(tmp_path), "--produced", str(tmp_path / "p.D64"),
            "--out", str(out)] + (["--force-restore"] if force else [])
    code = w.main(argv)
    _run_main.shots = sess.kbd.shots
    return code, out


def test_a_resave_that_wrote_nothing_fails_the_run_and_says_so(
        monkeypatch, tmp_path, capsys):
    code, out = _run_main(monkeypatch, tmp_path, resaved=False)
    printed = capsys.readouterr().out
    assert code == 1
    assert "FAILED: ENCAMP > SAVE did not write the party back." in printed
    assert "SUCCESS" not in printed
    assert '"resave_ok": false' in (out / "summary.json").read_text()
    assert _run_main.shots[-1] == "failure.png"


def test_a_failure_screenshot_that_cannot_be_taken_is_logged(
        monkeypatch, tmp_path, capsys):
    def broken(self, path, **kw):
        if path.endswith("failure.png"):
            raise OSError("import: no display")
        return True

    monkeypatch.setattr(_Kbd, "screenshot", broken)
    code, _ = _run_main(monkeypatch, tmp_path, resaved=False)
    assert code == 1
    assert "no failure.png: import: no display" in capsys.readouterr().out


def test_a_walk_that_did_not_move_the_party_fails_the_run(
        monkeypatch, tmp_path, capsys):
    code, _ = _run_main(monkeypatch, tmp_path, resaved=True, moved=False)
    assert code == 1
    assert "FAILED: the walk did not move the party." in capsys.readouterr().out


def test_a_forced_run_with_no_restore_fails_the_run(
        monkeypatch, tmp_path, capsys):
    code, _ = _run_main(monkeypatch, tmp_path, resaved=True, restores=0)
    assert code == 1
    assert "not rolled back though --force-restore" in capsys.readouterr().out


def test_a_run_that_walked_restored_and_resaved_succeeds(
        monkeypatch, tmp_path, capsys):
    code, _ = _run_main(monkeypatch, tmp_path, resaved=True)
    assert code == 0
    assert "SUCCESS" in capsys.readouterr().out
    assert "failure.png" not in _run_main.shots


def test_an_unforced_run_needs_no_restore(monkeypatch, tmp_path):
    code, _ = _run_main(monkeypatch, tmp_path, resaved=True, restores=0,
                        force=False)
    assert code == 0
