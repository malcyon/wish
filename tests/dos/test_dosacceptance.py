"""`tools/dos/dosacceptance.py`: the step list, the rest keys and the reading.

The driven half needs DOSBox and the player's archives and is proven by a
run.  What is pinned here: that the rest-menu keys reach the asked time from
any time the camp presets, on a fake that does the rest menu's arithmetic as
`GAME.OVR` 0x244ED and 0x24246 do it; that the camp bar is recognised
whichever word is highlighted; and that the reading names a node that lost
minutes, one that vanished, and one that the expectation accepts.  The one
test that converts the fixture party skips without the archives or the C64
disks.
"""

from __future__ import annotations

import pathlib

import pytest

from tools.dos import dosacceptance as da
from tools.dos import dosbox

W, H = 320, 200
BAR_Y = dosbox.BAR[1]
#: The rest menu's letters as each title's `GAME.OVR` reads them, written out
#: here rather than taken from the driver, so a fake driven with the wrong
#: letters fails: days, hours, minutes, add, subtract, rest.
_POOL_REST = da.RestKeys("y", "h", "m", "i", "d", "r")      # 0x244ED
_LATER_REST = da.RestKeys("d", "h", "m", "a", "s", "r")     # 0x2B4A7, 0x2BD63
TITLE_KEYS = {"pool": _POOL_REST, "curse": _LATER_REST, "ssb": _LATER_REST}


def _screen(bar: bytes, text: bytes, block: tuple[int, int] | None = None) -> dosbox.Screen:
    """A frame whose bar row carries `bar` as lit cells and whose text window
    carries `text`, a byte per pixel of row 136.  `block` is a range of bar
    cells drawn knocked out of a filled block, the way the game highlights a
    word."""
    px = bytearray(W * H * 3)
    for x, v in enumerate(text[:W]):
        at = (136 * W + x) * 3
        px[at:at + 3] = bytes((v, v, v))
    for cell, pattern in enumerate(bar[:W // da.CELL]):
        inside = block is not None and block[0] <= cell < block[1]
        for dy in range(dosbox.BAR[3]):
            for dx in range(da.CELL):
                lit = bool(pattern >> ((dx + dy) % 8) & 1)
                at = ((BAR_Y + dy) * W + cell * da.CELL + dx) * 3
                if inside:
                    px[at:at + 3] = b"\x00\x00\x00" if lit else b"\xaa\x00\xaa"
                else:
                    px[at:at + 3] = b"\x55\xff\x55" if lit else b"\x00\x00\x00"
    return dosbox.Screen(W, H, bytes(px))


# -- the bar, blind to its highlight -------------------------------------------


def test_the_bar_signature_ignores_which_word_is_highlighted():
    # Fewer lit pixels than paper in every cell, as a letter is.
    words = bytes((0x18, 0x24, 0, 0x81, 0x07, 0, 0x03))
    plain = _screen(words, b"")
    for block in ((0, 2), (3, 5), (6, 7)):
        lit = _screen(words, b"", block)
        # The whole-bar digest `glyphs` is fooled by the block, and the
        # signature is not.
        assert lit.glyphs(dosbox.BAR) != plain.glyphs(dosbox.BAR)
        assert da.bar_signature(lit) == da.bar_signature(plain)
    assert da.bar_signature(_screen(bytes((0x18, 0x24, 0, 0x81, 0x05)), b"")) \
        != da.bar_signature(plain)


# -- a fake DOS Pool of Radiance camp ------------------------------------------


class FakePool:
    """Camp, the rest menu and the camp save, as the overlay does them.

    The rest time is the game's digits: minute units, minute tens, hours,
    days.  `Inc` on minutes adds five to the units and carries; `Dec` takes
    five, borrowing from a higher field, and zeroes the whole time when
    nothing above has anything to borrow (`GAME.OVR` 0x24246).  `R` rests the
    time off and adds it to the clock.
    """

    BARS = {"map": b"\x11\x22", "camp": b"\x33\x44\x55", "rest": b"\x66\x77",
            "save": b"\x88", "quit": b"\x99\x0f",
            "watch": b"\xaa\x0f\x33", "fight": b"\x5a\xa5"}

    def __init__(self, tmp: pathlib.Path, preset: int = 0, swallow: bool = False,
                 dead: str = "", watches: int = 0, fight: bool = False,
                 keys: da.RestKeys | None = None):
        self.fight = fight
        #: The rest menu's letters: Pool's by default, `da.LATER_REST` for
        #: Curse and Silver Blades.
        self.rk = keys or TITLE_KEYS["pool"]
        self.mode = "map"
        #: Random events the next rest ends in, one after another.
        self.watches = watches
        self.answers: list[str] = []
        self.preset = preset
        self.total = 0
        self.field = 2
        self.clock = 0
        self.rested: list[int] = []
        self.swallow = swallow
        self.armed = False
        self.dead = dead
        self.save_dir = tmp / "SAVE"
        self.save_dir.mkdir()
        self.keys: list[str] = []

    # -- the game's arithmetic ------------------------------------------

    def digits(self) -> tuple[int, int, int, int]:
        days, rest = divmod(self.total, 1440)
        hours, mins = divmod(rest, 60)
        return mins % 10, mins // 10, hours, days

    def inc(self) -> None:
        self.total += {2: 5, 3: 60, 4: 1440}[self.field]
        self.total = min(self.total, 99 * 1440 + 1439)

    def dec(self) -> None:
        units, tens, hours, days = self.digits()
        idx = {2: 1, 3: 3, 4: 4}[self.field]
        amount, unit = {2: (5, 1), 3: (1, 60), 4: (1, 1440)}[self.field]
        have = {1: units, 3: hours, 4: days}[idx]
        higher = {1: (tens, hours, days), 3: (days,), 4: ()}[idx]
        if self.total == 0:
            return
        if amount <= have or any(higher):
            self.total -= amount * unit
        else:
            self.total = 0

    # -- the session's surface -------------------------------------------

    def key(self, k: str, gap: float = 0.0) -> None:
        self.keys.append(k)
        if self.armed:
            self.armed = False
            return
        before = self.mode
        if k == self.dead:
            return
        if self.mode == "map" and k == "e":
            self.mode = "camp"
        elif self.mode == "camp" and k == "r":
            self.mode, self.total, self.field = "rest", self.preset, 2
        elif self.mode == "camp" and k == "s":
            self.mode = "save"
        elif self.mode == "rest":
            rk = self.rk
            if k in (rk.days, rk.hours, rk.mins):
                self.field = {rk.days: 4, rk.hours: 3, rk.mins: 2}[k]
            elif k == rk.inc:
                self.inc()
            elif k == rk.dec:
                self.dec()
            elif k == rk.go:
                self.rested.append(self.total)
                self.clock += self.total
                self.total, self.mode = 0, "camp"
                if self.watches:
                    self.mode = "watch"
                if self.fight:
                    self.mode = "fight"
            elif k == "e":
                self.mode = "camp"
        elif self.mode == "watch" and k in "gs":
            self.answers.append(k)
            self.watches -= 1
            self.mode = "fight" if k == "s" else "watch" if self.watches else "map"
        elif self.mode == "save" and k.upper() in "ABCDEFGHIJ":
            (self.save_dir / f"SAVGAM{k.upper()}.DAT").write_bytes(
                bytes((self.clock % 256,)))
            self.mode = "quit"
        elif self.mode == "quit" and k == "n":
            self.mode = "camp"
        if self.mode != before and self.swallow:
            self.armed = True

    def capture(self) -> dosbox.Screen:
        text = b""
        if self.mode == "rest":
            text = bytes((1 + self.field, *(d + 1 for d in self.digits())))
        return _screen(self.BARS[self.mode], text)

    def settle(self, quiet: float = 0.6, timeout: float = 30.0) -> dosbox.Screen:
        return self.capture()

    def wait_for(self, pred, timeout: float = 30.0) -> bool:
        return bool(pred(self.capture()))

    def wait_while_ink(self, rect, same, timeout: float = 30.0) -> bool:
        return self.capture().ink(rect) != same

    def shot(self, name: str, allow_blank: bool = False) -> pathlib.Path:
        return self.save_dir.parent / f"{name}.png"

    def save_file(self, letter: str) -> pathlib.Path:
        return self.save_dir / f"SAVGAM{letter.upper()}.DAT"


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    monkeypatch.setattr(da.time, "sleep", lambda s: None)
    monkeypatch.setattr(dosbox, "settle_files", lambda *a, **k: True)


def _camped(tmp_path, title="pool", **kw) -> tuple[FakePool, da.Driver]:
    game = FakePool(tmp_path, keys=TITLE_KEYS[title], **kw)
    d = da.Driver(game, lambda **k: None, "A", title)
    d.logged = []
    d.note = lambda **k: d.logged.append(k)
    d.camp()
    return game, d


@pytest.mark.parametrize("title", sorted(da.TITLES))
@pytest.mark.parametrize("preset", [0, 7, 4 * 60 + 30, 1440 + 65, 3 * 1440])
@pytest.mark.parametrize("asked", [5, 90, 1445])
def test_the_rest_keys_set_the_asked_time_from_any_preset(tmp_path, title, preset,
                                                          asked):
    game, d = _camped(tmp_path, title, preset=preset)
    got = d.rest(asked)
    assert game.rested == [asked]
    assert got["asked"] == asked
    assert game.mode == "camp"


def test_a_swallowed_key_after_each_redraw_is_pressed_again(tmp_path):
    game, d = _camped(tmp_path, preset=4 * 60 + 30, swallow=True)
    d.rest(5)
    assert game.rested == [5]


def test_nothing_is_pressed_while_the_party_rests(tmp_path):
    # Any key during a rest asks `Stop Resting?`: the last key before camp
    # returns is the rest key itself.
    game, d = _camped(tmp_path)
    d.rest(5)
    assert game.keys[-1] == da.REST_GO


def test_a_key_that_changes_nothing_stops_the_run(tmp_path):
    game, d = _camped(tmp_path, dead=da.REST_INC)
    with pytest.raises(da.StepFailed, match="Inc on minutes"):
        d.rest(5)
    assert game.rested == []


def test_rest_and_save_refuse_before_camp(tmp_path):
    d = da.Driver(FakePool(tmp_path), lambda **k: None, "A")
    with pytest.raises(da.StepFailed, match="camp first"):
        d.rest(5)
    with pytest.raises(da.StepFailed, match="camp first"):
        d.save("D")


def test_the_camp_save_is_believed_by_the_file_and_declines_the_quit(tmp_path):
    game, d = _camped(tmp_path)
    got = d.save("D")
    assert (game.save_dir / "SAVGAMD.DAT").is_file()
    assert got["back_in_camp"] and game.mode == "camp"
    assert game.keys[-2:] == ["d", da.QUIT_NO]


# -- a random event ends the rest ------------------------------------------------


@pytest.fixture
def _watch_and_clock(monkeypatch):
    """The fake's watch bar stands in for the real one, and time moves per call."""
    monkeypatch.setattr(da, "WATCH_BAR", da.bar_signature(
        _screen(FakePool.BARS["watch"], b"")))
    now = [0.0]

    def tick():
        now[0] += 1.0
        return now[0]

    monkeypatch.setattr(da, "time", type("T", (), {"time": staticmethod(tick),
                                                   "sleep": staticmethod(lambda s: None)}))


def test_the_watch_bar_is_answered_go_and_logged(tmp_path, _watch_and_clock):
    game, d = _camped(tmp_path, watches=1)
    got = d.rest(5)
    assert game.answers == ["g"] and game.mode == "map"
    assert got["left_camp"] is True
    assert [e["kind"] for e in d.events] == ["go_stay"]
    assert [k["event"] for k in d.logged if k["event"] == "random"] == ["random"]


def test_a_second_watch_is_answered_too(tmp_path, _watch_and_clock):
    game, d = _camped(tmp_path, watches=2)
    d.rest(5)
    assert game.answers == ["g", "g"] and len(d.events) == 2


def test_a_third_watch_stops_the_run_without_pressing(tmp_path, _watch_and_clock):
    game, d = _camped(tmp_path, watches=3)
    with pytest.raises(da.StepFailed, match="lost-rest-events"):
        d.rest(5)
    assert game.answers == ["g", "g"]


def test_stay_is_never_pressed(tmp_path, _watch_and_clock):
    game, d = _camped(tmp_path, watches=2)
    d.rest(5)
    assert "s" not in game.keys[game.keys.index("g"):]


def test_a_fight_after_the_rest_stops_the_run(tmp_path, _watch_and_clock):
    game, d = _camped(tmp_path, fight=True)
    with pytest.raises(da.StepFailed, match="lost-rest-end"):
        d.rest(5)
    assert game.answers == []


def test_save_camps_again_after_the_party_was_moved_along(tmp_path, _watch_and_clock):
    game, d = _camped(tmp_path, watches=1)
    d.rest(5)
    got = d.save("D")
    assert got["back_in_camp"] and game.keys[-2:] == ["d", da.QUIT_NO]
    assert game.keys.count("e") == 2
    assert (game.save_dir / "SAVGAMD.DAT").is_file()


# -- the step list and its arguments --------------------------------------------


@pytest.mark.parametrize("text,minutes", [("5m", 5), ("8h", 480), ("2d", 2880),
                                          ("1h30m", 90), ("1d0h5m", 1445)])
def test_durations(text, minutes):
    assert da.parse_duration(text) == minutes


@pytest.mark.parametrize("text", ["", "5", "m", "5s", "h5"])
def test_a_duration_that_is_not_one_is_refused(text):
    with pytest.raises(ValueError):
        da.parse_duration(text)


def test_rest_presses_split_the_time_the_way_the_menu_holds_it():
    assert da.rest_presses(5) == (0, 0, 1)
    assert da.rest_presses(90) == (0, 1, 6)
    assert da.rest_presses(1445) == (1, 0, 1)
    for bad in (0, 7, 100 * 1440):
        with pytest.raises(ValueError):
            da.rest_presses(bad)


def test_steps_parse_and_a_bad_one_is_refused():
    assert da.parse_step("save d").letter == "D"
    assert da.parse_step("rest 5m").minutes == 5
    assert da.parse_step("rest 8d").minutes == 8 * 1440
    assert da.parse_step("train 3").line == 3
    assert da.parse_step("shot rest-screen").name == "rest-screen"
    assert da.parse_step("press Return").key == "Return"
    assert da.parse_step("walk MI").key == "MI"
    for bad in ("walk 2", "walk N", "save", "save K", "rest 7m", "load now", "train",
                "train 9", "begin now", "press", "press a;b"):
        with pytest.raises(ValueError):
            da.parse_step(bad)


def test_the_command_line_refuses_a_bad_step_before_any_boot():
    with pytest.raises(SystemExit):
        da.main(["--save", ".", "--steps", "load", "rest 3m"])


def test_rows_and_expectations_parse():
    assert da.parse_row("3F=01:00:2F:01") == (63, 1, 0, 0x2F, 1)
    assert da.parse_expect("brutus:1:42:1") == da.Expect("BRUTUS", 1, 42, 1)
    assert da.parse_expect("BRUTUS:1:0x2A") == da.Expect("BRUTUS", 1, 42, None)
    for bad in ("40=01:00:2F:01", "3F=01:00:2F", "3F=100:00:2F:01"):
        with pytest.raises(ValueError):
            da.parse_row(bad)


# -- staging and reading ---------------------------------------------------------


def test_install_keeps_only_the_one_slot_and_renames_it(tmp_path):
    # Distinct names: "save" and "SAVE" are one directory on Windows.
    save, dest = tmp_path / "staged", tmp_path / "play"
    save.mkdir()
    dest.mkdir()
    # Lower-case archive names must count as the same slot as upper-case ones.
    for name in ("savgama.dat", "CHRDATA1.SAV", "chrdata1.spc", "NOTES.TXT"):
        (save / name).write_bytes(name.encode())
    (dest / "SAVGAMJ.DAT").write_bytes(b"someone else's")
    took = da.install(save, dest, "d")
    assert sorted(p.name for p in dest.iterdir()) == [
        "CHRDATD1.SAV", "CHRDATD1.SPC", "SAVGAMD.DAT"]
    assert (dest / "CHRDATD1.SPC").read_bytes() == b"chrdata1.spc"
    assert took["from_slot"] == "A" and took["as_slot"] == "D"


def test_the_clock_difference_crosses_midnight():
    before = (0, 7, 5, 23, 3, 1)       # 23:57, day 3
    after = (0, 2, 0, 0, 4, 1)         # 00:02, day 4
    assert da.clock_total(after) - da.clock_total(before) == 5


def _slot(*chars):
    return {"characters": [{"name": n, "nodes": [
        {"id": i, "minutes": m, "data": dt} for i, m, dt in nodes]}
        for n, nodes in chars]}


def test_compare_names_a_node_that_aged_one_that_vanished_and_a_new_one():
    before = _slot(("BRUTUS", [(1, 47, 1), (17, 2, 0x0B)]), ("GUY", [(5, 10, 3)]))
    after = _slot(("BRUTUS", [(1, 42, 1)]), ("GUY", [(5, 10, 3), (9, 3, 0)]))
    rows = {(r["name"], r["id"]): r for r in da.compare_nodes(before, after)}
    assert rows[("BRUTUS", 1)]["lost"] == 5
    assert rows[("BRUTUS", 17)]["after"] is None
    assert rows[("GUY", 5)]["lost"] == 0
    assert rows[("GUY", 9)]["before"] is None


def test_judge_accepts_only_the_named_node_at_the_named_minutes():
    after = _slot(("BRUTUS", [(1, 42, 1)]))
    assert da.judge(da.Expect("BRUTUS", 1, 42, 1), after)["verdict"] == "accepts"
    unchanged = da.judge(da.Expect("BRUTUS", 1, 42, 1), _slot(("BRUTUS", [(1, 47, 1)])))
    assert unchanged["verdict"] == "refutes" and "47 minutes" in unchanged["why"]
    assert da.judge(da.Expect("BRUTUS", 1, 42), _slot(("BRUTUS", [])))["verdict"] \
        == "refutes"
    assert da.judge(da.Expect("BRUTUS", 1, 42), _slot())["verdict"] == "refutes"


def test_the_evidence_goes_under_the_acceptance_cache():
    out = da.default_out("661", "bless", "0123456789abcdef")
    assert out.parts[-4:] == ("wish", "acceptance", "661", "0123456789-bless")


def test_the_fixture_party_converts_with_its_bless_and_reads_back(tmp_path):
    """Save As DOS of the fixture party with a 47-minute Bless on slot 0:
    nothing dropped, `01 2F 00 01 00` in BRUTUS's `.SPC`, and the reading
    the run's `read` step makes of it accepts BRUTUS at 47."""
    from editor import saveplan
    try:
        built = da.build_source([(63, 1, 0, 0x2F, 1)], tmp_path)
    except FileNotFoundError:
        pytest.skip("needs the DOS Pool of Radiance archives ($FR_ARCHIVES)")
    except saveplan.MissingAssets:
        pytest.skip("needs Pool of Radiance's own C64 disks")
    assert built["dropped"] == [] and built["losses"] == []
    assert [n["raw"] for n in built["nodes"]["CHRDATA1.SPC"]] == ["012f000100"]
    slot = da.read_slot(tmp_path / "source", "A")
    assert da.judge(da.Expect("BRUTUS", 1, 47, 1), slot)["verdict"] == "accepts"


class _Slot:
    def __init__(self, log):
        self.log = log

    def release(self):
        self.log.append("release")


class _Session:
    """Stands in for dosbox.Session; `fail_on` names the method that raises."""

    def __init__(self, tmp_path, log, fail_on=None):
        self.dir = tmp_path / "session"
        self.save_dir = self.dir / "SAVE"
        self.log, self.fail_on = log, fail_on

    def stage(self, fresh=True):
        self.save_dir.mkdir(parents=True, exist_ok=True)

    def boot(self, fresh=False):
        pass

    def close(self):
        self.log.append("close")
        if self.fail_on == "close":
            raise RuntimeError("close broke")


def _run_args(tmp_path, steps):
    import argparse
    return argparse.Namespace(
        title="pool", slot="A", steps=steps, expect=[], fixture_row=[], save=None,
        out=str(tmp_path / "out"), issue="661", run="t", note="t")


def _fake_run(monkeypatch, tmp_path, *, find_game=None, session_fail=None,
              menu_error=None):
    log: list[str] = []
    monkeypatch.setattr(da, "git_state", lambda: {"sha": "0" * 40, "dirty": False})
    monkeypatch.setattr(da, "install", lambda *a: {})

    def find(stem):
        if find_game:
            raise find_game
        return tmp_path / "game"

    def claim(note=""):
        log.append("claim")
        return _Slot(log)

    monkeypatch.setattr(dosbox, "find_game", find)
    monkeypatch.setattr(dosbox, "claim", claim)
    monkeypatch.setattr(dosbox, "Session",
                        lambda slot, game: _Session(tmp_path, log, session_fail))

    class Game:
        def to_main_menu(self):
            raise menu_error

    class D:
        def __init__(self, session, note, letter, *rest, **kw):
            self.game = Game()

        def shot(self, name):
            (tmp_path / "session" / "shots").mkdir(parents=True, exist_ok=True)
            (tmp_path / "session" / "shots" / f"{name}.png").write_bytes(b"x")
            return name

        def fail(self, label, why):
            return da.StepFailed(f"{why}; see {self.shot('lost-' + label)}.png")

        def load(self):
            self.game.to_main_menu()

    monkeypatch.setattr(da, "Driver", D)
    return log


def test_a_missing_game_is_found_before_a_slot_is_claimed(monkeypatch, tmp_path):
    log = _fake_run(monkeypatch, tmp_path, find_game=FileNotFoundError("no game"))
    with pytest.raises(FileNotFoundError):
        da.run(_run_args(tmp_path, ["load"]))
    assert "claim" not in log


def test_a_timeout_before_the_load_writes_the_lost_shot_and_reason(monkeypatch, tmp_path):
    import json
    _fake_run(monkeypatch, tmp_path, menu_error=TimeoutError("no menu"))
    assert da.run(_run_args(tmp_path, ["load"])) == 1
    out = tmp_path / "out"
    assert (out / "shots" / "lost-timeout.png").is_file()
    assert "no menu" in json.loads((out / "summary.json").read_text())["lost"]


def test_a_failed_close_still_releases_the_slot_and_the_log(monkeypatch, tmp_path):
    log = _fake_run(monkeypatch, tmp_path, session_fail="close",
                    menu_error=TimeoutError("x"))
    with pytest.raises(RuntimeError, match="close broke"):
        da.run(_run_args(tmp_path, ["load"]))
    assert log == ["claim", "close", "release"]
    assert (tmp_path / "out" / "summary.json").is_file()


def test_a_bad_step_order_is_refused_before_a_slot_is_claimed(monkeypatch, tmp_path, capsys):
    log = _fake_run(monkeypatch, tmp_path)
    with pytest.raises(SystemExit):
        da.main(["--save", str(tmp_path), "--steps", "load", "rest 5m"])
    assert log == []
    assert "needs camp first" in capsys.readouterr().err


# -- the later titles: keys, order, staging ----------------------------------------


def test_the_later_titles_rest_on_their_own_letters():
    """`Rest Days Hours Mins Add Subtract Exit` (Curse `GAME.OVR` 0x2B4A7,
    Silver Blades 0x2BD63): Pool's `Y`, `I` and `D` are not its keys, and
    `D` selects the days field there rather than subtracting."""
    for title in ("curse", "ssb"):
        keys = da.TITLES[title].rest_keys()
        assert (keys.days, keys.inc, keys.dec) == ("d", "a", "s")
    assert TITLE_KEYS["pool"] == da.RestKeys("y", "h", "m", "i", "d", "r")


def test_pool_keys_do_not_rest_a_later_title(tmp_path):
    # The Curse menu driven with Pool's letters: `y` selects nothing, so the
    # first key of the zeroing changes nothing and the run stops there.
    game = FakePool(tmp_path, keys=TITLE_KEYS["curse"], preset=90)
    d = da.Driver(game, lambda **k: None, "A", "pool")
    d.camp()
    with pytest.raises(da.StepFailed, match="days field"):
        d.rest(5)
    assert game.rested == []


def test_a_rest_that_ends_on_a_still_screen_stops_the_run(tmp_path, _watch_and_clock,
                                                           monkeypatch):
    # Eight days is 2,304 passes, so the bar's own deadline is over an hour
    # away; a screen that has stopped changing ends the run long before it.
    monkeypatch.setattr(da, "REST_STALL", 20.0)
    game, d = _camped(tmp_path, "curse", fight=True)
    calls = []
    real = game.capture
    game.capture = lambda: calls.append(1) or real()
    with pytest.raises(da.StepFailed, match="nothing under the viewport"):
        d.rest(8 * 1440)
    assert game.rested == [8 * 1440]
    assert len(calls) < 100


def _steps(*texts):
    return [da.parse_step(t) for t in texts]


@pytest.mark.parametrize("title,steps", [
    ("pool", ("load", "walk MI", "camp", "rest 5m", "save D", "read")),
    ("curse", ("load", "save B", "train 1", "save C", "read")),
    ("curse", ("load", "begin", "camp", "rest 8d")),
    ("ssb", ("load", "begin", "camp", "rest 5m", "save D", "read")),
    ("ssb", ("load", "shot party", "begin", "camp", "save B", "read")),
    ("ssb", ("load", "press Down", "press Return", "shot menu", "press t", "read")),
])
def test_orders_the_game_allows(title, steps):
    da.validate_steps(_steps(*steps), title)


def test_pool_walk_mi_turns_twice_then_steps_and_records_each_map_state(tmp_path):
    game = FakePool(tmp_path)
    d = da.Driver(game, lambda **k: None, "A")
    d.where = "map"
    d.world_ink = game.capture().ink(dosbox.BAR)
    d.world_sig = da.bar_signature(game.capture())

    class Movement:
        world_bar = d.world_ink

        def __init__(self):
            self.facing = 3
            self.x = 0
            self.keys = []

        def status(self):
            return f"{self.x},{self.facing}"

        def turn_right(self):
            self.keys.append("Right")
            self.facing = (self.facing + 1) % 4
            return True

        def step(self):
            self.keys.append("Up")
            self.x += 1
            return True

    move = Movement()
    d.game = move
    got = d.walk("MI")
    assert move.keys == ["Right", "Right", "Up"]
    assert got["status_before"] == "0,3"
    assert got["status_after"] == "1,1"
    assert len(got["screens"]) == 4
    assert d.where == "map"


def test_pool_walk_mi_stops_before_camp_when_step_enters_combat(tmp_path):
    game = FakePool(tmp_path)
    d = da.Driver(game, lambda **k: None, "A")
    d.where = "map"
    d.world_ink = game.capture().ink(dosbox.BAR)

    class Movement:
        def __init__(self):
            self.keys = []

        def status(self):
            return "map-status"

        def turn_right(self):
            self.keys.append("Right")
            return True

        def step(self):
            self.keys.append("Up")
            game.mode = "fight"
            return True

    move = Movement()
    d.game = move
    with pytest.raises(da.StepFailed, match="map bar did not return"):
        d.walk("MI")
    assert move.keys == ["Right", "Right", "Up"]
    assert d.where == "map"


def test_pool_walk_mi_stops_before_camp_when_step_hits_a_wall(tmp_path):
    game = FakePool(tmp_path)
    d = da.Driver(game, lambda **k: None, "A")
    d.where = "map"
    d.world_ink = game.capture().ink(dosbox.BAR)

    class Movement:
        def __init__(self):
            self.facing = 3
            self.keys = []

        def status(self):
            return f"0,{self.facing}"

        def turn_right(self):
            self.keys.append("Right")
            self.facing = (self.facing + 1) % 4
            return True

        def step(self):
            self.keys.append("Up")
            return True

    move = Movement()
    d.game = move
    with pytest.raises(da.StepFailed, match="status did not change"):
        d.walk("MI")
    assert move.keys == ["Right", "Right", "Up"]
    assert d.where == "map"


@pytest.mark.parametrize("title,steps,why", [
    ("pool", ("load", "rest 5m"), "needs camp first"),
    ("pool", ("load", "begin"), "puts the party on the map"),
    ("pool", ("load", "save D"), "needs camp first"),
    ("pool", ("load", "camp", "walk MI"), "walk needs the map"),
    ("curse", ("load", "begin", "walk MI"), "pool only"),
    ("curse", ("load", "camp"), "needs begin first"),
    ("curse", ("load", "begin", "train 1"), "party menu"),
    ("curse", ("camp",), "needs load first"),
    ("curse", ("load", "begin", "camp", "camp"), "already camped"),
    ("ssb", ("load", "train 1"), "curse only"),
    ("ssb", ("load", "load"), "the first"),
    ("ssb", ("press Return",), "needs load first"),
    ("curse", ("load", "press Return", "begin"), "only press, shot and read"),
])
def test_orders_the_game_does_not_allow(title, steps, why):
    with pytest.raises(ValueError, match=why):
        da.validate_steps(_steps(*steps), title)


def test_silver_blades_is_installed_under_its_own_letter(tmp_path):
    save, dest = tmp_path / "staged", tmp_path / "play"
    save.mkdir()
    dest.mkdir()
    for name in ("SAVGAMA.DAT", "CHRDATA1.SAV"):
        (save / name).write_bytes(b"x")
    with pytest.raises(ValueError, match="install A as A"):
        da.install(save, dest, "D", same_letter=True)
    assert list(dest.iterdir()) == []
    assert da.install(save, dest, "a", same_letter=True)["as_slot"] == "A"


def test_a_folder_of_two_slots_needs_the_one_named(tmp_path):
    for name in ("SAVGAMA.DAT", "savgamb.dat", "CHRDATA1.SAV", "CHRDATB1.SAV"):
        (tmp_path / name).write_bytes(name.encode())
    with pytest.raises(FileNotFoundError, match="--from-slot"):
        da.source_slot(tmp_path)
    assert da.source_slot(tmp_path, "b") == "B"
    with pytest.raises(FileNotFoundError, match="holds no SAVGAMC"):
        da.source_slot(tmp_path, "C")
    dest = tmp_path / "play"
    dest.mkdir()
    took = da.install(tmp_path, dest, "J", "B")
    assert sorted(p.name for p in dest.iterdir()) == ["CHRDATJ1.SAV", "SAVGAMJ.DAT"]
    assert (dest / "CHRDATJ1.SAV").read_bytes() == b"CHRDATB1.SAV"
    assert took["from_slot"] == "B"


def _curse_record(name: bytes = b"MATHEW") -> bytes:
    from goldbox import dos_port
    size = dos_port.deltas_for("curse-of-the-azure-bonds").record_size
    data = bytearray(size)
    data[0] = len(name)
    data[1:1 + len(name)] = name
    return bytes(data)


def test_the_stages_write_what_they_log(tmp_path):
    from goldbox import dos_codec
    (tmp_path / "SAVGAMJ.DAT").write_bytes(bytes(0xE00))
    (tmp_path / "CHRDATJ1.SAV").write_bytes(_curse_record())
    (tmp_path / "CHRDATJ1.FX").write_bytes(bytes.fromhex("080000ff00") + bytes(4))
    hall = da.stage_hall(tmp_path, "j")
    assert (tmp_path / "SAVGAMJ.DAT").read_bytes()[0xD51:0xD53] == b"\xff\x00"
    assert (hall["before"], hall["after"]) == ("0000", "ff00")
    xp = da.stage_xp(tmp_path, "J", 1, 5000)
    assert dos_codec.read_character(tmp_path / "CHRDATJ1.SAV").get("experience") == 5000
    assert xp["name"] == "MATHEW"
    line, node = da.parse_node("1=141:10080:1:1")
    got = da.stage_node(tmp_path, "J", line, node)
    fx = (tmp_path / "CHRDATJ1.FX").read_bytes()
    assert len(fx) == 18 and fx[9:14] == bytes((141, 0x60, 0x27, 1, 1))
    assert got["file"] == "CHRDATJ1.FX" and got["node"]["minutes"] == 10080
    assert [n.hex()[:10] for n in dos_codec.read_character(
        tmp_path / "CHRDATJ1.SAV").effects] == ["080000ff00", "8d60270101"]


@pytest.mark.parametrize("bad", ["0=1:2:3:4", "1=1:2:3", "1=256:0:0:0",
                                 "1=1:65536:0:0", "x"])
def test_a_bad_node_is_refused(bad):
    with pytest.raises(ValueError):
        da.parse_node(bad)


def test_experience_is_compared_by_name():
    before = {"characters": [{"name": "GUY", "experience": 200000},
                             {"name": "PAINE", "experience": None}]}
    after = {"characters": [{"name": "GUY", "experience": 202750}]}
    rows = {r["name"]: r for r in da.compare_experience(before, after)}
    assert rows["GUY"]["gained"] == 2750
    assert rows["PAINE"]["gained"] is None


# -- Curse's party menu: load, save, train -------------------------------------------


class FakeCurseMenu(FakePool):
    """Curse from the title menu to the party menu, its save and its training.

    `trainable` names the roster lines the school takes; `learns` is how many
    `LEARN` screens a training leaves; `asks_quit` puts a `QUIT TO DOS`
    question after a party-menu save.
    """

    BARS = {**FakePool.BARS, "title": b"\x01", "which": b"\x02\x03",
            "party": b"\x04\x05\x06", "offer": b"\x07", "learn": b"\x08\x09",
            "psave": b"\x0a", "pquit": b"\x0b\x0c"}

    def __init__(self, tmp, trainable=(1,), learns=1, asks_quit=False, size=6):
        super().__init__(tmp, keys=TITLE_KEYS["curse"])
        self.mode, self.line, self.size = "title", 1, size
        self.trainable, self.learns, self.asks_quit = set(trainable), learns, asks_quit
        self.trained: list[int] = []
        self.left = 0

    def key(self, k, gap=0.0):
        self.keys.append(k)
        m = self.mode
        if m == "title" and k == "l":
            self.mode = "which"
        elif m == "which" and k.upper() in "ABCDEFGHIJ":
            self.mode = "party"
        elif m == "party" and k == "End":
            self.line = self.line % self.size + 1
        elif m == "party" and k == "t" and self.line in self.trainable:
            self.mode = "offer"
        elif m == "offer" and k == "y":
            self.trained.append(self.line)
            self.left = self.learns
            self.mode = "learn" if self.left else "party"
        elif m == "learn" and k == "l":
            self.left -= 1
            self.mode = "learn" if self.left else "party"
        elif m == "party" and k == "s":
            self.mode = "psave"
        elif m == "psave" and k.upper() in "ABCDEFGHIJ":
            (self.save_dir / f"SAVGAM{k.upper()}.DAT").write_bytes(
                bytes((len(self.trained),)))
            self.mode = "pquit" if self.asks_quit else "party"
        elif m == "pquit" and k == "n":
            self.mode = "party"
        elif m == "party" and k == "b":
            self.mode = "map"
        else:
            super().key(k, gap)

    def capture(self):
        if self.mode in FakePool.BARS:
            return super().capture()
        text = bytes((self.line,)) if self.mode == "party" else b""
        return _screen(self.BARS[self.mode], text)

    def press_until_change(self, key, tries=5, gap=0.8):
        before = self.capture().digest()
        for _ in range(tries):
            self.key(key)
            if self.capture().digest() != before:
                return True
        return False


def _curse_loaded(tmp_path, **kw):
    game = FakeCurseMenu(tmp_path, **kw)
    d = da.Driver(game, lambda **k: None, "J", "curse", party_size=game.size)
    d.game.to_main_menu = lambda timeout=120.0: None
    got = d.load()
    assert game.mode == "party" and d.where == "party" and got["slot"] == "J"
    return game, d


def test_curse_loads_to_the_party_menu_pressing_the_letter_once(tmp_path):
    game, d = _curse_loaded(tmp_path)
    assert game.keys == ["l", "j"]


def test_curse_trains_the_line_asked_for_and_learns_its_spell(tmp_path):
    game, d = _curse_loaded(tmp_path, trainable=(3,), learns=2)
    got = d.train(3)
    assert game.trained == [3] and game.mode == "party"
    assert game.keys.count("End") == 2 and got["after"] == ["l", "l"]
    # The highlight stays where the last command left it, and End wraps.
    game.trainable = {2}
    d.train(2)
    assert game.trained == [3, 2] and game.keys.count("End") == 2 + 5


def test_a_school_that_refuses_stops_the_run(tmp_path):
    game, d = _curse_loaded(tmp_path, trainable=())
    with pytest.raises(da.StepFailed, match="train-refused"):
        d.train(1)
    assert game.trained == []


@pytest.mark.parametrize("asks_quit", [False, True])
def test_the_party_menu_save_is_believed_by_the_file(tmp_path, asks_quit):
    game, d = _curse_loaded(tmp_path, asks_quit=asks_quit)
    got = d.save("B")
    assert (game.save_dir / "SAVGAMB.DAT").is_file() and game.mode == "party"
    assert got["at"] == "party menu"
    assert (da.QUIT_NO in game.keys) is asks_quit


def test_curse_begins_and_camps(tmp_path):
    game, d = _curse_loaded(tmp_path)
    d.begin()
    assert game.mode == "map" and d.where == "map"
    d.camp()
    assert game.mode == "camp"
    d.rest(5)
    assert game.rested == [5]


# -- the later titles' conversion, off the player's disks ---------------------------


@pytest.mark.parametrize("title,name,effect_file", [
    ("curse", "PHILIPPE", "CHRDATA6.FX"),
    ("ssb", "MORGAINE", "CHRDATA6.SFX"),
])
def test_a_later_title_party_converts_with_its_bless_and_reads_back(
        tmp_path, title, name, effect_file):
    """Save As DOS of the title's engine-written C64 specimen with a Bless
    row for party slot 0 whose duration byte leaves 47 minutes at the
    save's own clock: nothing dropped, `01 2F 00 05 00` in the first
    character's effect file, and the reading the run's `read` step makes of
    it accepts him at 47."""
    from editor import saveplan
    base = da.c64_base(title)
    if not base.is_file():
        pytest.skip(f"needs {base.name} in $WISH_SPECIMENS/por-c64")
    try:
        built = da.build_source([(63, 1, 0, 0x2F, 5)], tmp_path, title)
    except FileNotFoundError:
        pytest.skip("needs the DOS archives ($FR_ARCHIVES)")
    except saveplan.MissingAssets:
        pytest.skip("needs the title's own C64 disks")
    assert built["dropped"] == [] and built["losses"] == []
    assert built["minutes_left"] == [47]
    assert [n["raw"] for n in built["nodes"][effect_file]] == ["012f000500"]
    slot = built["read"]["A"]
    assert da.judge(da.Expect(name, 1, 47, 5), slot)["verdict"] == "accepts"
    assert slot["place"]["set_out"] is True


def test_encamp_is_never_pressed_at_the_party_menu(tmp_path):
    # `E` is exit to DOS at Curse's party menu: a BEGIN that did not take
    # leaves the run stopped there, not pressing on into camp.
    game, d = _curse_loaded(tmp_path)
    game.key = lambda k, gap=0.0: game.keys.append(k)
    with pytest.raises(da.StepFailed):
        d.begin()
    with pytest.raises(da.StepFailed, match="lost-camp"):
        d.camp()
    assert "e" not in game.keys


# -- review findings: refusals before a slot is claimed, and the log handle -----------


def test_hall_is_refused_for_a_title_whose_hall_word_is_not_documented(capsys):
    with pytest.raises(SystemExit):
        da.main(["--title", "ssb", "--save", ".", "--hall", "--steps", "load"])
    assert "--hall" in capsys.readouterr().err


def test_hall_refuses_a_save_too_short_to_hold_the_word(tmp_path):
    (tmp_path / "SAVGAMA.DAT").write_bytes(bytes(0x100))
    with pytest.raises(ValueError, match="too short"):
        da.stage_hall(tmp_path, "A")
    assert (tmp_path / "SAVGAMA.DAT").stat().st_size == 0x100


def _staged_run(monkeypatch, tmp_path, **extra):
    log = _fake_run(monkeypatch, tmp_path)
    saves = tmp_path / "saves"
    saves.mkdir()
    (saves / "SAVGAMA.DAT").write_bytes(bytes(0xE00))
    (saves / "CHRDATA1.SAV").write_bytes(b"x")
    args = _run_args(tmp_path, ["load"])
    args.save = str(saves)
    for k, v in extra.items():
        setattr(args, k, v)
    return log, args


@pytest.mark.parametrize("extra", [{"xp": ["3=100"]}, {"add_node": ["3=1:2:3:4"]}])
def test_a_line_with_no_record_is_refused_before_a_slot_is_claimed(
        monkeypatch, tmp_path, extra):
    log, args = _staged_run(monkeypatch, tmp_path, **extra)
    with pytest.raises(ValueError, match="CHRDATA3.SAV"):
        da.run(args)
    assert "claim" not in log


def test_a_short_save_is_refused_for_hall_before_a_slot_is_claimed(monkeypatch, tmp_path):
    log, args = _staged_run(monkeypatch, tmp_path, hall=True)
    (tmp_path / "saves" / "SAVGAMA.DAT").write_bytes(bytes(0x100))
    with pytest.raises(ValueError, match="too short"):
        da.run(args)
    assert "claim" not in log


@pytest.mark.parametrize("key", ["e", "E", "Escape", "escape"])
def test_press_refuses_exit_to_dos_and_escape(key):
    with pytest.raises(ValueError):
        da.parse_step(f"press {key}")


def test_the_log_is_closed_when_the_save_has_no_such_slot(monkeypatch, tmp_path):
    _fake_run(monkeypatch, tmp_path)
    opened = []
    real = pathlib.Path.open

    def spy(self, *a, **k):
        h = real(self, *a, **k)
        opened.append(h)
        return h

    monkeypatch.setattr(pathlib.Path, "open", spy)
    empty = tmp_path / "empty"
    empty.mkdir()
    args = _run_args(tmp_path, ["load"])
    args.save = str(empty)
    with pytest.raises(FileNotFoundError):
        da.run(args)
    assert opened and all(h.closed for h in opened)


def test_begin_presses_b_once_so_a_slow_boot_cannot_press_it_on_the_map(tmp_path):
    game, d = _curse_loaded(tmp_path)
    seen = []
    real = d.press_screen_changes
    d.press_screen_changes = lambda key, **kw: (seen.append((key, kw)), real(key, **kw))[1]
    d.begin()
    assert seen == [(da.PARTY_BEGIN, {"tries": 1, "wait": 30.0})]
