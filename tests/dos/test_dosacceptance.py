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
            "save": b"\x88", "quit": b"\x99\x0f"}

    def __init__(self, tmp: pathlib.Path, preset: int = 0, swallow: bool = False,
                 dead: str = ""):
        self.mode = "map"
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
            if k in "yhm":
                self.field = {"y": 4, "h": 3, "m": 2}[k]
            elif k == "i":
                self.inc()
            elif k == "d":
                self.dec()
            elif k == "r":
                self.rested.append(self.total)
                self.clock += self.total
                self.total, self.mode = 0, "camp"
            elif k == "e":
                self.mode = "camp"
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


def _camped(tmp_path, **kw) -> tuple[FakePool, da.Driver]:
    game = FakePool(tmp_path, **kw)
    d = da.Driver(game, lambda **k: None, "A")
    d.camp()
    return game, d


@pytest.mark.parametrize("preset", [0, 7, 4 * 60 + 30, 1440 + 65, 3 * 1440])
@pytest.mark.parametrize("asked", [5, 90, 1445])
def test_the_rest_keys_set_the_asked_time_from_any_preset(tmp_path, preset, asked):
    game, d = _camped(tmp_path, preset=preset)
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
    assert da.parse_step("shot rest-screen").name == "rest-screen"
    for bad in ("walk 2", "save", "save K", "rest 7m", "load now"):
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
    save, dest = tmp_path / "save", tmp_path / "SAVE"
    save.mkdir()
    dest.mkdir()
    for name in ("SAVGAMA.DAT", "CHRDATA1.SAV", "CHRDATA1.SPC", "NOTES.TXT"):
        (save / name).write_bytes(name.encode())
    (dest / "SAVGAMJ.DAT").write_bytes(b"someone else's")
    took = da.install(save, dest, "d")
    assert sorted(p.name for p in dest.iterdir()) == [
        "CHRDATD1.SAV", "CHRDATD1.SPC", "SAVGAMD.DAT"]
    assert (dest / "CHRDATD1.SPC").read_bytes() == b"CHRDATA1.SPC"
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
        def __init__(self, session, note, letter):
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
