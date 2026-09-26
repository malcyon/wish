"""`tools.dos.dosbox.judge_step` and `run_walked`: telling a walk from a wall
from a driver that pressed nothing (#341 (A DOS run reports a party that
walked into another area as never having walked)).

Every case here is decided from recorded readings -- digests, areas and
squares handed in as plain values -- so none of it starts an emulator.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.dos import dosbox  # noqa: E402


def describe(area: int, x: int, y: int, facing: int) -> dict:
    """A `describe()`/`describe_dos()`-shaped dict, with only what
    `run_walked` reads."""
    return {"area": area, "square": [x, y, facing]}


# -- judge_step ---------------------------------------------------------

def test_a_step_within_an_area_is_a_walk():
    # The status digest differs; no area readings are available (as in the
    # per-step loop, which has only a screen digest to compare).
    kind, reason = dosbox.judge_step(True, True)
    assert kind == "walked"
    assert reason is None


def test_an_area_change_is_a_walk_even_when_the_digest_did_not_move():
    # This is the case #341 is about: the status line lagged the redraw, so
    # the digest read before and after a step that crossed into another area
    # compare equal (`changed=False`) -- and the area itself, read from a
    # save file rather than the screen, says otherwise.
    kind, reason = dosbox.judge_step(True, False, area_before=0, area_after=20)
    assert kind == "walked"
    assert reason is None


def test_an_area_change_reported_as_a_walk_fails_without_reading_the_area():
    # Proves the assertion above is not vacuous: with only the (lagged)
    # digest to go on, the same step reads as blocked.  This is the bug.
    kind, _ = dosbox.judge_step(True, False)
    assert kind == "blocked"


def test_no_movement_is_blocked():
    kind, reason = dosbox.judge_step(True, False, area_before=0, area_after=0)
    assert kind == "blocked"
    assert reason is None


def test_the_driver_pressing_nothing_is_a_driver_error_not_a_wall():
    # Even handed an area change and a changed digest, a step the driver
    # never sent a key for is never a wall -- #360 (The session driver will
    # not walk a Curse or Silver Blades party in a dungeon, because it reads
    # Pool of Radiance's indoors flag)'s `Session.walk_refused` distinction,
    # carried into this harness's own vocabulary.
    kind, reason = dosbox.judge_step(False, True, area_before=0, area_after=20)
    assert kind == "refused"
    assert reason == "the driver pressed nothing"


# -- run_walked -----------------------------------------------------------

def test_run_walked_true_for_a_step_within_the_area():
    built = describe(0, 5, 13, 1)
    resaved = describe(0, 7, 13, 1)
    assert dosbox.run_walked(built, resaved) is True


def test_run_walked_true_for_a_crossed_area_even_with_the_same_square():
    # The reported bug: New Phlan (0,4) facing west to the Slums (0,4)
    # facing west would read as no movement by square alone -- the area is
    # what proves it, and it must be checked before the square is.
    built = describe(0, 0, 4, 3)
    resaved = describe(20, 0, 4, 3)
    assert dosbox.run_walked(built, resaved) is True


def test_run_walked_false_when_nothing_moved():
    built = describe(0, 5, 13, 1)
    resaved = describe(0, 5, 13, 1)
    assert dosbox.run_walked(built, resaved) is False


def test_run_walked_ignores_a_facing_only_change():
    # The loop turns the party in place to recover from a wall; a facing
    # change alone is not a walk.
    built = describe(0, 5, 13, 1)
    resaved = describe(0, 5, 13, 3)
    assert dosbox.run_walked(built, resaved) is False


# -- dossheetread.walk's engine save ---------------------------------------------

class _SaveSession:
    """Just what `dossheetread.walk` asks of a session when it is given no
    steps to walk: a screen, a shot and the slot's file."""

    def __init__(self, tmp_path):
        self.save_dir = tmp_path
        self.screen = dosbox.Screen(8, 8, bytes(8 * 8 * 3))

    def key(self, *keys, gap=0.0):
        pass

    def settle(self, quiet=0.6, timeout=30.0):
        return self.screen

    def capture(self):
        return self.screen

    def shot(self, name, allow_blank=False):
        return self.save_dir / f"{name}.png"

    def save_file(self, letter):
        return self.save_dir / f"SAVGAM{letter.upper()}.DAT"


class _Por:
    """`PoolOfRadiance` as `walk` uses it; `save_game` is what a test sets."""

    world_bar = "bar"

    def __init__(self, session, save_game):
        self.s = session
        self._save_game = save_game

    def record_map(self, screen):
        pass

    def status(self):
        return "status"

    def bar(self):
        return "bar"

    def save_game(self, letter):
        self._save_game(self.s, letter)


def _engine_save(monkeypatch, tmp_path, save_game):
    from tools.dos import dossheetread
    session = _SaveSession(tmp_path)
    monkeypatch.setattr(dosbox, "PoolOfRadiance", lambda s: _Por(s, save_game))
    notes = []
    got = dossheetread.walk(session, 0, lambda **kw: notes.append(kw),
                            engine_save="D")
    return got, notes


def test_an_engine_save_that_times_out_before_the_file_changed_is_not_saved(
        monkeypatch, tmp_path):
    (tmp_path / "SAVGAMD.DAT").write_bytes(b"old")

    def save_game(session, letter):
        raise TimeoutError("SAVGAMD.DAT never changed")

    got, notes = _engine_save(monkeypatch, tmp_path, save_game)
    assert "engine_saved_to" not in got
    assert got["engine_save_failed"] == "SAVGAMD.DAT never changed"
    assert [n["event"] for n in notes] == ["engine_save_failed"]


def test_an_engine_save_that_returns_with_the_file_unchanged_is_not_saved(
        monkeypatch, tmp_path):
    (tmp_path / "SAVGAMD.DAT").write_bytes(b"old")
    got, _ = _engine_save(monkeypatch, tmp_path, lambda session, letter: None)
    assert "engine_saved_to" not in got
    assert "did not change" in got["engine_save_failed"]


def test_an_engine_save_that_wrote_the_file_is_saved_even_if_camp_is_not_left(
        monkeypatch, tmp_path):
    def save_game(session, letter):
        session.save_file(letter).write_bytes(b"new")
        raise TimeoutError("the map bar never came back")

    got, notes = _engine_save(monkeypatch, tmp_path, save_game)
    assert got["engine_saved_to"] == "D"
    assert got["left_in_camp"] == "the map bar never came back"
    assert "engine_save_failed" not in got


def test_an_engine_save_that_wrote_the_file_and_left_camp_is_saved(monkeypatch, tmp_path):
    (tmp_path / "SAVGAMD.DAT").write_bytes(b"old")

    def save_game(session, letter):
        session.save_file(letter).write_bytes(b"new")

    got, _ = _engine_save(monkeypatch, tmp_path, save_game)
    assert got["engine_saved_to"] == "D"
    assert "left_in_camp" not in got
