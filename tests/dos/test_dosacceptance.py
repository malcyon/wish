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
from tools.dos import dosbox, dospod

W, H = 320, 200
BAR_Y = dosbox.BAR[1]
#: The rest menu's letters as each title's `GAME.OVR` reads them, written out
#: here rather than taken from the driver, so a fake driven with the wrong
#: letters fails: days, hours, minutes, add, subtract, rest.
_POOL_REST = da.RestKeys("y", "h", "m", "i", "d", "r")      # 0x244ED
_LATER_REST = da.RestKeys("d", "h", "m", "a", "s", "r")     # 0x2B4A7, 0x2BD63
# Pools of Darkness: `Rest Days Hours Mins Add Subtract Exit`, `GAME.EXE` 0xBB26.
TITLE_KEYS = {"pool": _POOL_REST, "curse": _LATER_REST, "ssb": _LATER_REST,
              "darkness": _LATER_REST}


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


#: The synthetic question's prompt: six cells of ink left of what is typed.
_PROMPT = bytes((0x11, 0x22, 0x44, 0x88, 0x12, 0x24))


def _journal_frame(typed: int = 0) -> dosbox.Screen:
    """A synthetic stand-in for Pools of Darkness' journal question: `_PROMPT`
    and one lit cell per typed key on the bar row, and sparse ink across
    `dospod.JOURNAL_LINE_RECT`.  The `pod_journal` fixture makes the driver
    know it by this frame's own digests."""
    frame = _screen(_PROMPT + b"\x81" * typed, b"")
    px = bytearray(frame.px)
    x0, y0, w, h = dospod.JOURNAL_LINE_RECT
    for x in range(x0, x0 + w, 3):
        at = ((y0 + x % h) * W + x) * 3
        px[at:at + 3] = b"\x55\xff\x55"
    return dosbox.Screen(W, H, bytes(px))


@pytest.fixture
def pod_journal(monkeypatch):
    frame = _journal_frame()
    monkeypatch.setattr(dospod, "JOURNAL_PROMPT",
                        frame.glyphs(dospod.JOURNAL_PROMPT_RECT))
    monkeypatch.setattr(dospod, "JOURNAL_LINE",
                        frame.glyphs(dospod.JOURNAL_LINE_RECT))


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


@pytest.fixture(autouse=True)
def _pod_map_measured(monkeypatch):
    """The fakes' map bar stands in for the measured `dungeon` one of
    `POD_MAP_BARS`, whose real values the tests at the end check against
    captures."""
    monkeypatch.setattr(da, "POD_MAP_BARS", {
        "dungeon": da.bar_signature(_screen(FakePool.BARS["map"], b""))})


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


@pytest.mark.parametrize("failure", ("", "magic", "display", "five", "back_magic",
                                          "back_camp"))
def test_pool_display_captures_every_member_and_returns_to_camp_before_save(
        tmp_path, monkeypatch, failure):
    class DisplayPool(FakePool):
        BARS = {**FakePool.BARS, "magic": b"\x12\x45\x78",
                "display": b"\x13\x46\x79", "wrong": b"\x14\x47\x7a"}

        def key(self, k, gap=0.0):
            if self.mode == "camp" and k == "m":
                self.keys.append(k)
                self.mode = "wrong" if failure == "magic" else "magic"
            elif self.mode == "magic" and k == "d":
                self.keys.append(k)
                self.mode = "wrong" if failure == "display" else "display"
            elif self.mode == "display" and k == "Return":
                self.keys.append(k)
                self.mode = "wrong" if failure == "back_magic" else "magic"
            elif self.mode == "magic" and k == "e":
                self.keys.append(k)
                self.mode = "wrong" if failure == "back_camp" else "camp"
            else:
                super().key(k, gap)

        def capture(self):
            frame = super().capture()
            if self.mode != "display":
                return frame
            px = bytearray(frame.px)
            for y in (40, 64, 88, 112, 136, 160)[:5 if failure == "five" else 6]:
                at = (y * W + 8) * 3
                px[at:at + 3] = b"\xff\xff\xff"
            return dosbox.Screen(W, H, bytes(px))

    monkeypatch.setattr(da, "POOL_MAGIC_BAR", da.bar_signature(
        _screen(DisplayPool.BARS["magic"], b"")))
    monkeypatch.setattr(da, "POOL_DISPLAY_BAR", da.bar_signature(
        _screen(DisplayPool.BARS["display"], b"")))
    game = DisplayPool(tmp_path)
    d = da.Driver(game, lambda **k: None, "A")
    d.camp()
    if failure:
        with pytest.raises(da.StepFailed):
            d.display()
        assert not game.save_file("D").exists()
        return
    got = d.display()
    assert got["visible_members"] == 6
    assert got["back_in_camp"] and game.mode == "camp"
    assert game.keys[-4:] == ["m", "d", "Return", "e"]
    d.save("D")
    assert game.save_file("D").is_file()


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
    assert da.parse_step("display").kind == "display"
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
        where = "boot"
        #: The labels `journal` and `yes_no` were asked with, before each step.
        asked: list[str] = []
        declined: list[str] = []
        continued: list[str] = []

        def __init__(self, session, note, letter, *rest, **kw):
            self.game = Game()

        def journal(self, label):
            self.asked.append(label)
            return False

        def yes_no(self, label):
            self.declined.append(label)
            return 0

        def press_continue(self, label):
            self.continued.append(label)
            return 0

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
    ("pool", ("load", "camp", "display", "save D", "read")),
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
    ("pool", ("load", "display"), "display needs camp first"),
    ("curse", ("load", "display"), "pool only"),
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


# -- Pools of Darkness: an Amiga slot converted, installed, read and driven -------------


def _pod_node(**fields) -> bytes:
    """One twenty-byte Amiga item node, big-endian, from `amiga_pod`'s own map."""
    from goldbox import amiga_pod
    raw = bytearray(amiga_pod.ITEM_FILE_SIZE)
    for name, value in fields.items():
        f, at = amiga_pod.ITEM_FIELDS[name], amiga_pod.ITEM_FIELD_AT[name]
        raw[at:at + f.size] = value.to_bytes(f.size, "big")
    return bytes(raw)


def _pod_block(name: str, thief: tuple[int, ...], nodes: list[bytes],
               heads: int) -> bytes:
    """A character block of an Amiga saved game: `amiga_pod.PodWriter`'s
    404-byte record, its head-item count, then the nodes after it."""
    import struct

    from goldbox import amiga_pod, amiga_savegame
    record = bytearray(amiga_pod.PodWriter(
        name=name, hit_points_max=30, thief_skills=thief,
        character_class=amiga_pod.CLASSES.index("THIEF"),
        class_levels=(0, 0, 0, 0, 0, 0, 20),
        class_bits=amiga_pod.CLASS_BIT["thief"]).to_bytes()[
            :amiga_savegame.POD_RECORD_BYTES])
    struct.pack_into(">I", record, amiga_savegame.POD_ITEM_COUNT_AT, heads)
    struct.pack_into(">I", record, amiga_savegame.POD_EFFECT_HEAD_AT, 0)
    return bytes(record) + b"".join(nodes)


#: INA's pick pockets as the Amiga engine wrote it for a level 29 thief
#: (#650), and TRIPEL's under 128, which both readings agree on.
INA_THIEF = (135, 90, 80, 70, 60, 50, 40, 30)
TRIPEL_THIEF = (120, 1, 2, 3, 4, 5, 6, 7)


def _pod_disk(tmp_path: pathlib.Path, slot: str = "C") -> pathlib.Path:
    """A blank Amiga save disk holding one Pools of Darkness saved game,
    built from the documented format: INA with a readied scroll case of two
    scrolls and a sword, and TRIPEL with nothing.  No game file is read."""
    import struct

    from goldbox import amiga_savegame, dos_savegame
    from goldbox.amiga_adf import AmigaDisk
    case = _pod_node(type_index=0x49, quantity=2, readied=1, weight=2)
    mage = _pod_node(type_index=39, charges=5, effect=6, power=7, weight=1, quantity=1)
    cleric = _pod_node(type_index=40, charges=8, effect=9, power=10, weight=1, quantity=1)
    sword = _pod_node(type_index=1, weight=60, quantity=1, readied=1)
    blocks = [_pod_block("INA", INA_THIEF, [case, mage, cleric, sword], 2),
              _pod_block("TRIPEL", TRIPEL_THIEF, [], 0)]
    data = bytearray(amiga_savegame.POD_VAR_BYTES)
    data[dos_savegame.POD_PARTY_COUNT - 1] = len(blocks)
    data += bytes((3, 4, 2, 5, 137, 0))
    data += bytes((dos_savegame.POD_MODE_DUNGEON, dos_savegame.POD_MODE_DUNGEON))
    data += struct.pack(">HHH", 6, 0, len(blocks))
    for block in blocks:
        data += block
    data += bytes(amiga_savegame.POD_SAVEGAME_SIZE - len(data))
    disk = AmigaDisk.blank("PDARKSAVE")
    disk.make_dir(f"/{amiga_savegame.SAVE_DRAWER}")
    disk.write_file(amiga_savegame.pod_slot_path(slot), bytes(data))
    path = tmp_path / "pod-save.adf"
    path.write_bytes(disk.to_bytes())
    return path


@pytest.fixture
def pod_source(tmp_path, monkeypatch):
    """The synthetic disk converted by `build_amiga_source`, with the flag
    unset beforehand so the test sees the driver set it and put it back."""
    import os

    from editor import convert
    monkeypatch.delenv(convert.POD_CONVERT_ENV, raising=False)
    out = tmp_path / "out"
    out.mkdir()
    built = da.build_amiga_source(str(_pod_disk(tmp_path)), "SavGamC.pty", out)
    assert convert.POD_CONVERT_ENV not in os.environ
    return out, built


def test_an_amiga_slot_converts_by_the_convert_route_and_reads_back(pod_source):
    """The product route with the flag set for the conversion only: nothing
    dropped or lost, INA's pick pockets 135 and TRIPEL's 120, and the case
    replaced by its two scrolls with their spell ids, all as `read` reports
    them."""
    out, built = pod_source
    assert "refused" not in built, built.get("refused")
    assert built["direction"] == "PodAmigaToDos"
    assert built["dropped"] == [] and built["losses"] == []
    assert built["amiga_slot"] == "SavGamC.pty" and built["dos_slot"] == "A"
    assert len(built["adf_sha256"]) == 64
    assert built["files"] == ["CHRDATA1.SAV", "CHRDATA1.THG", "CHRDATA2.SAV",
                              "SAVGAMA.PTY", "VAULTA.DAT"]
    slot = da.read_slot(out / "source", "A")
    assert slot == built["read"]["A"]
    who = {c["name"]: c for c in slot["characters"]}
    assert who["INA"]["thief"] == dict(zip(da.THIEF_FIELDS, INA_THIEF))
    assert who["TRIPEL"]["thief"]["thief_pick_pockets"] == 120
    assert who["INA"]["item_count"] == 3
    assert [(i["type_index"], i["spells"]) for i in who["INA"]["items"]] == [
        (39, [5, 6, 7]), (40, [8, 9, 10]), (1, [0, 0, 0])]
    assert slot["vault_bytes"] == 12 and slot["place"]["x"] == 3


def test_a_loss_only_the_debug_log_hears_of_is_listed_among_the_warnings(
        tmp_path, monkeypatch):
    """The DOS writer sends some losses to `wish.goldbox.dos_codec`'s log and
    to neither `dropped` nor `losses` (a spell id past the book, #509), so the
    run's report lists every warning the conversion logged.  The warning is
    raised here by a wrapper, so the test does not rest on which losses the
    writer logs today."""
    from goldbox import dos_codec
    real = dos_codec.new_pod_save_from

    def logging_one(*a, **k):
        dos_codec._log.warning("spells_known: id %s is outside the book", 126)
        return real(*a, **k)

    monkeypatch.setattr(dos_codec, "new_pod_save_from", logging_one)
    out = tmp_path / "out"
    out.mkdir()
    built = da.build_amiga_source(str(_pod_disk(tmp_path)), "C", out)
    assert built["dropped"] == [] and built["losses"] == []
    assert built["warnings"] == [
        "wish.goldbox.dos_codec: spells_known: id 126 is outside the book"]


def test_a_slot_the_disk_does_not_hold_is_refused_before_anything_is_written(
        tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    built = da.build_amiga_source(str(_pod_disk(tmp_path)), "D", out)
    assert "slot D" in built["refused"]
    assert not (out / "source").exists()


def test_a_pools_of_darkness_slot_installs_its_container_vault_and_records(
        pod_source, tmp_path):
    """`SAVGAMA.PTY`, `VAULTA.DAT` and every `CHRDATA*`, which is what
    `new_pod_save_from` writes.  Before this title, `source_slot` refused the
    folder: it holds 0 SAVGAM?.DAT files."""
    out, _ = pod_source
    dest = tmp_path / "play"
    dest.mkdir()
    (dest / "SAVGAMB.PTY").write_bytes(b"the archives' own")
    took = da.install(out / "source", dest, "A", same_letter=True)
    assert sorted(took["files"]) == sorted(p.name for p in dest.iterdir()) == [
        "CHRDATA1.SAV", "CHRDATA1.THG", "CHRDATA2.SAV", "SAVGAMA.PTY", "VAULTA.DAT"]
    with pytest.raises(ValueError, match="install A as A"):
        da.install(out / "source", dest, "D", same_letter=da.TITLES["darkness"].same_letter)


def test_the_read_step_sets_each_members_skills_and_items_side_by_side(
        pod_source, tmp_path):
    import shutil
    out, _ = pod_source
    shutil.copytree(out / "source", out / "installed")
    result = da.read_step(out / "source", out, "A", ["A"], [], [])
    rows = {r["name"]: r for r in result["slots"]["A"]["members"]}
    assert rows["INA"]["changed"] == [] and rows["TRIPEL"]["present"]
    assert rows["INA"]["thief"]["after"]["thief_pick_pockets"] == 135
    lines = da.describe(result)
    assert any(line.startswith("  INA: pick pockets 135, 3 items (3 read)")
               for line in lines)


def test_the_title_reads_the_archives_own_container_and_records():
    """A control on a container the engine wrote: the archives' shipped slot
    A, read in place and never written.  Its provenance is unknown
    (`.claude/rules/testing.md`), so only the reading's own invariants are
    asserted: six characters, eight thief skills each, and an item count
    that matches the items read."""
    try:
        save = dospod.find_game() / "SAVE"
    except FileNotFoundError:
        pytest.skip("needs the DOS Pools of Darkness archives ($FR_ARCHIVES)")
    slot = da.read_slot(save, "A")
    assert len(slot["characters"]) == 6
    for c in slot["characters"]:
        assert len(c["thief"]) == 8
        assert c["item_count"] == len(c["items"])


@pytest.mark.parametrize("steps", [
    ("load", "begin", "camp", "sheet 4", "items 4", "sheet 6", "save D", "read"),
    ("load", "begin", "walk 1", "shot walked", "camp", "save D", "read"),
    ("load", "save B", "begin", "camp", "rest 5m", "save D", "read"),
])
def test_orders_pools_of_darkness_allows(steps):
    da.validate_steps(_steps(*steps), "darkness")


@pytest.mark.parametrize("title,steps,why", [
    ("darkness", ("load", "train 1"), "curse only"),
    ("darkness", ("load", "camp"), "needs begin first"),
    ("darkness", ("load", "begin", "walk MI"), "walk 1"),
    ("darkness", ("load", "begin", "sheet 1"), "sheet needs camp first"),
    ("darkness", ("load", "items 1"), "items needs camp first"),
    ("darkness", ("load", "begin", "camp", "display"), "pool only"),
    ("pool", ("load", "walk 1"), "walk MI"),
    ("pool", ("load", "camp", "sheet 1"), "darkness only"),
    ("curse", ("load", "begin", "camp", "items 2"), "darkness only"),
])
def test_orders_pools_of_darkness_does_not_allow(title, steps, why):
    with pytest.raises(ValueError, match=why):
        da.validate_steps(_steps(*steps), title)


def test_the_new_steps_parse_and_bad_ones_are_refused():
    assert da.parse_step("sheet 4").line == 4
    assert (da.parse_step("items 8").kind, da.parse_step("items 8").line) == ("items", 8)
    assert da.parse_step("walk 1").key == "1"
    for bad in ("sheet", "sheet 9", "items 0", "walk 3"):
        with pytest.raises(ValueError):
            da.parse_step(bad)
    assert [da.parse_amiga_slot(s) for s in ("SavGamA.pty", "savgamh.PTY", "c")] \
        == ["A", "H", "C"]
    for bad in ("SavGamK.pty", "savgam.dat", "AB"):
        with pytest.raises(ValueError):
            da.parse_amiga_slot(bad)


@pytest.mark.parametrize("argv,why", [
    (["--title", "darkness", "--fixture-row", "3F=01:00:2F:01"], "no C64 port"),
    (["--title", "curse", "--amiga-slot", "A", "--amiga-disk", "x.adf"],
     "--title darkness"),
    (["--title", "darkness", "--amiga-slot", "A"], "needs --amiga-disk"),
    (["--title", "darkness", "--amiga-slot", "K", "--amiga-disk", "x.adf"],
     "not an Amiga"),
])
def test_the_command_line_refuses_a_bad_source_before_any_boot(argv, why, capsys):
    with pytest.raises(SystemExit):
        da.main(argv)
    assert why in capsys.readouterr().err


class FakePod(FakePool):
    """DOS Pools of Darkness from its title screens to camp, as `GAME.EXE`'s
    strings and its load routine (`GAME.OVR` 0x12887) describe it: an
    optional copy-protection question that echoes a typed key and takes
    `Return`; Silver Blades' party-menu rows (`Down` moves, `Return` picks;
    row 0 is `Create New Character` before a load, row 2 `Load Saved Game`);
    `LOAD FROM WHERE? POOLS SECRET EXIT`, where only `P` leads on and a slot
    letter does nothing; `LOAD WHICH GAME:` listing only the letters whose
    `SAVGAM<L>.PTY` exists; after a load row 6 saves and row 7 begins, or 8
    and 9 when the save's byte 0x2F adds `Train` and `Human Change`; the
    roster highlight moved by `End`; the sheet's `ITEMS` with `Next`."""

    BARS = {**FakePool.BARS, "title": b"\x21", "question": b"\x22", "menu": b"\x23\x24",
            "which": b"\x25", "party": b"\x26\x27", "create": b"\x28",
            "sheet": b"\x29\x2a", "items": b"\x2b\x2c", "psave": b"\x2d",
            "from": b"\x2e\x2f", "secret": b"\x30", "tour": b"\x31\x32",
            "story": b"\x34", "cont": b"\x35\x36", "overland": b"\x37\x38",
            "town": b"\x3a\x3b\x3c"}

    def __init__(self, tmp, question=True, pages=3, size=6, journal=False,
                 swallow_p=False, tours=0, after_tour="map", dead_n=False,
                 continues=0, dead_return=False, late_return=False,
                 late_n=False, after_town="map"):
        super().__init__(tmp, keys=TITLE_KEYS["darkness"])
        self.mode = "title"
        #: `YES NO` bars the arrival asks, one after another, after `Begin`
        #: and the journal question; each draws its own text, takes `N`
        #: (`into_tour` has every key typed at one) unless `dead_n`, and the
        #: last leads to `after_tour`.
        self.tours, self.after_tour, self.dead_n = tours, after_tour, dead_n
        self.into_tour: list[str] = []
        #: Story dialogs after the last bar, each drawing its own text, taking
        #: `Return` (`into_cont` has every key typed at one) unless
        #: `dead_return`; the last leads to the map.
        self.continues, self.dead_return, self.into_cont = continues, dead_return, []
        #: The first `Return` takes effect only after one more capture, as a
        #: redraw that lands after the driver's wait has run out.
        self.late_return, self.late_wait = late_return, 0
        #: The first `N` takes effect only after one more capture.
        self.late_n, self.late_n_wait = late_n, False
        #: A town services screen: every key typed at it (`into_town`), and
        #: where `M` leads.
        self.after_town, self.into_town = after_town, []
        #: Keys typed at the map, where a stray `Return` or `N` would land.
        self.into_map: list[str] = []
        #: `Begin` leads to the journal question, which draws every key
        #: typed into it (`into_journal`) and leaves for the map on `Return`
        #: after something was typed (`GAME.OVR` 0x3603).
        self.journal, self.into_journal, self.journal_typed = journal, [], 0
        #: `LOAD FROM WHERE?` drops the first `p`.
        self.swallow_p = swallow_p
        self.titles, self.question, self.typed = 2, question, 0
        self.row, self.line, self.size = 0, 1, size
        self.page, self.pages = 1, pages
        self.loaded = False
        self.train = False
        #: The archives' stub is 1,364 bytes with byte 0x2F zero.
        (self.save_dir / "SAVGAMA.PTY").write_bytes(bytes(1364))

    def key(self, k, gap=0.0):
        self.keys.append(k)
        m = self.mode
        if m == "tour":
            self.into_tour.append(k)
            if k == "n" and self.late_n:
                self.late_n, self.late_n_wait = False, True
            elif k == "n" and not self.dead_n:
                self._decline()
        elif m == "town":
            self.into_town.append(k)
            if k == "m":
                self.mode = self.after_town
        elif m == "cont":
            self.into_cont.append(k)
            if k == "Return" and self.late_return:
                self.late_return, self.late_wait = False, 1
            elif k == "Return" and not self.dead_return:
                self._next_cont()
        elif m == "map" and k in ("Return", "n"):
            self.into_map.append(k)
        elif m == "overland" and k == da.ENCAMP:
            self.mode = "camp"
        elif m == "journal":
            self.into_journal.append(k)
            if k == "Return" and self.journal_typed:
                self.mode, self.journal_typed = self.arrival(), 0
            elif len(k) == 1:
                self.journal_typed += 1
        elif m == "from" and k == "p" and self.swallow_p:
            self.swallow_p = False
        elif m == "title":
            if k == "Escape":
                self.titles -= 1
                if self.titles == 0:
                    self.mode = "question" if self.question else "menu"
        elif m == "question" and k == "Return" and self.typed:
            self.mode, self.question = "menu", False
        elif m == "question" and k not in ("Escape", "Return"):
            self.typed += 1
        elif m in ("menu", "party") and k == "Down":
            self.row = (self.row + 1) % 11
        elif m in ("menu", "party") and k == "Return":
            shift = 2 * self.train
            begin = "journal" if self.journal else self.arrival()
            picked = {("menu", 0): "create", ("menu", 2): "from",
                      ("party", 6 + shift): "psave", ("party", 7 + shift): begin}
            self.mode = picked.get((m, self.row), m)
        elif m == "from" and k.upper() in "PSE":
            self.mode = {"P": "which", "S": "secret", "E": "menu"}[k.upper()]
        elif m == "which" and (self.save_dir / f"SAVGAM{k.upper()}.PTY").is_file():
            got = (self.save_dir / f"SAVGAM{k.upper()}.PTY").read_bytes()
            self.train = len(got) > 0x2F and got[0x2F] != 0
            self.mode, self.row, self.loaded = "party", 0, True
        elif m == "psave" and k.upper() in "ABCDEFGHIJ":
            (self.save_dir / f"SAVGAM{k.upper()}.PTY").write_bytes(b"p")
            self.mode = "party"
        elif m == "camp" and k == "End":
            self.line = self.line % self.size + 1
        elif m == "camp" and k == "v":
            self.mode = "sheet"
        elif m == "sheet" and k == "i":
            self.mode, self.page = "items", 1
        elif m == "sheet" and k == "e":
            self.mode = "camp"
        elif m == "items" and k == "n" and self.page < self.pages:
            self.page += 1
        elif m == "items" and k == "e":
            self.mode = "sheet"
        elif m == "save" and k.upper() in "ABCDEFGHIJ":
            (self.save_dir / f"SAVGAM{k.upper()}.PTY").write_bytes(b"c")
            self.mode = "quit"
        elif m in FakePool.BARS:
            self.keys.pop()     # `FakePool.key` records it again
            super().key(k, gap)

    def _decline(self) -> None:
        self.tours -= 1
        self.mode = "tour" if self.tours else self.after_tour
        if self.mode == "map" and self.continues:
            self.mode = "cont"

    def _next_cont(self) -> None:
        self.continues -= 1
        self.mode = "cont" if self.continues else "map"

    def arrival(self) -> str:
        """Where the party is once the journal question is behind it."""
        return "tour" if self.tours else "cont" if self.continues else "map"

    def capture(self):
        if self.late_n_wait and self.mode == "tour":
            # This capture still shows the old dialog; the next shows the new.
            self.late_n_wait = False
            shown = _screen(self.BARS["tour"], bytes((self.tours + 1,)))
            self._decline()
            return shown
        if self.late_wait and self.mode == "cont":
            # This capture still shows the old screen; the next shows the new.
            self.late_wait = 0
            shown = _screen(self.BARS["cont"], bytes((self.continues + 1,)))
            self._next_cont()
            return shown
        if self.mode == "journal":
            return _journal_frame(self.journal_typed)
        if self.mode in FakePool.BARS and self.mode not in ("camp",):
            return super().capture()
        text = {"title": (self.titles,), "question": (1, self.typed),
                "menu": (self.row,), "party": (self.row,),
                "camp": (self.line,), "sheet": (self.line,),
                "items": (self.line, self.page),
                "tour": (self.tours,), "cont": (self.continues,)}.get(self.mode, ())
        bar = FakePool.BARS["camp"] if self.mode == "camp" else self.BARS[self.mode]
        return _screen(bar, bytes(t + 1 for t in text))

    def walk_highlight(self, rect, want, key="End", timeout=20.0):
        assert rect == da.POD_MENU_RECT
        for _ in range(11):
            if self.row == want:
                return want
            self.key(key)
        return None

    def press_until_change(self, key, tries=5, gap=0.8):
        before = self.capture().digest()
        for _ in range(tries):
            self.key(key)
            if self.capture().digest() != before:
                return True
        return False


def _pod_driver(tmp_path, **kw):
    game = FakePod(tmp_path, **kw)
    d = da.Driver(game, lambda **k: None, "A", "darkness", party_size=game.size)
    return game, d


@pytest.mark.parametrize("question", [True, False])
def test_pools_of_darkness_loads_through_its_party_menu(tmp_path, question):
    """The question, when there is one, gets the probe key and `Return`; the
    party menu gets the probe key and no `Return` at `Create New Character`;
    then row 2, `Return`, `P` for POOLS at LOAD FROM WHERE?, and the slot
    letter once."""
    game, d = _pod_driver(tmp_path, question=question)
    got = d.load()
    assert game.mode == "party" and game.loaded and d.where == "party"
    assert got["questions_answered"] == int(question)
    assert got["menu_rows"] == {"view": 3, "save": 6, "begin": 7}
    assert [k for k in game.keys if k != "Escape"] == (
        ["1", "Return"] if question else []) + ["1", "Down", "Down", "Return",
                                                 "p", "a"]


def test_a_slot_letter_at_load_from_where_loads_nothing(tmp_path):
    """Run 0's stop: the letter pressed at `LOAD FROM WHERE?` changes nothing."""
    game, d = _pod_driver(tmp_path, question=False)
    game.mode = "menu"
    d.pod_menu(da.POD_LOAD_ROW, "load")
    assert game.mode == "from"
    assert not d.press_screen_changes("a", tries=1, wait=0.1)
    assert d.press_screen_changes(da.POD_LOAD_FROM, tries=1, wait=0.1)
    assert game.mode == "which"


def test_a_slot_that_is_not_installed_is_not_listed_and_stops_the_run(tmp_path):
    game = FakePod(tmp_path, question=False)
    d = da.Driver(game, lambda **k: None, "C", "darkness", party_size=game.size)
    with pytest.raises(da.StepFailed, match="slot C never loaded"):
        d.load()
    assert game.mode == "which" and not game.loaded


@pytest.mark.parametrize("savgam,rows", [
    (bytes(1364), (3, 6, 7)),
    (bytes(0x2F) + b"\x01" + bytes(1364 - 0x30), (5, 8, 9)),
    (bytes(0x2F) + b"\x80", (5, 8, 9)),
    (bytes(0x2F), (3, 6, 7)),
    (None, (3, 6, 7)),
], ids=["stub", "set", "high-bit", "short", "missing"])
def test_the_party_menu_rows_move_two_lower_when_the_training_byte_is_set(savgam, rows):
    got = da.pod_menu_after(savgam)
    assert (got["view"], got["save"], got["begin"]) == rows


def test_a_save_with_the_training_byte_begins_and_saves_two_rows_lower(tmp_path):
    """`Train Character` and `Human Change Classes` sit above `View`, so a save
    with byte 0x2F set moves `Save` to row 8 and `Begin` to row 9."""
    game, d = _pod_driver(tmp_path, question=False)
    staged = bytearray(game.save_dir.joinpath("SAVGAMA.PTY").read_bytes())
    staged[da.POD_TRAIN_BYTE] = 1
    game.save_dir.joinpath("SAVGAMA.PTY").write_bytes(bytes(staged))
    assert d.load()["menu_rows"] == {"view": 5, "save": 8, "begin": 9}
    assert game.train
    d.save("B")
    assert game.keys[-10:] == ["Down"] * 8 + ["Return", "b"] and game.mode == "party"
    game.row = 0
    d.begin()
    assert game.keys[-10:] == ["Down"] * 9 + ["Return"] and game.mode == "map"


def test_pools_of_darkness_begins_camps_views_and_saves(tmp_path):
    game, d = _pod_driver(tmp_path, question=False, pages=3)
    d.load()
    d.begin()
    assert game.mode == "map" and d.where == "map"
    assert game.keys[-8:] == ["Down"] * 7 + ["Return"]
    d.camp()
    game.keys.clear()
    sheet = d.sheet(4)
    assert game.keys == ["End"] * 3 + ["v", "e"] and game.mode == "camp"
    assert sheet["line"] == 4 and game.line == 4
    game.keys.clear()
    items = d.items(4)
    assert game.keys == ["v", "i", "n", "n", "n", "e", "e"]
    assert len(items["pages"]) == 3 and game.mode == "camp"
    game.keys.clear()
    d.sheet(2)
    assert game.keys.count("End") == 4
    saved = d.save("D")
    assert saved["file"] == "SAVGAMD.PTY" and (game.save_dir / "SAVGAMD.PTY").is_file()
    assert game.mode == "camp"


def test_exit_is_never_pressed_on_the_camp_bar_itself(tmp_path):
    """`Exit` on the camp bar breaks camp: leaving a sheet looks first."""
    game, d = _pod_driver(tmp_path, question=False)
    d.load()
    d.begin()
    d.camp()
    game.keys.clear()
    d.back_to_camp("x")
    assert game.keys == [] and game.mode == "camp"


def test_an_items_list_that_never_ends_stops_the_run(tmp_path):
    game, d = _pod_driver(tmp_path, question=False, pages=da.ITEMS_PAGES + 2)
    d.load()
    d.begin()
    d.camp()
    with pytest.raises(da.StepFailed, match="Next still turns"):
        d.items(1)


def test_the_party_menu_save_writes_the_pty(tmp_path):
    game, d = _pod_driver(tmp_path, question=False)
    d.load()
    got = d.save("B")
    assert got["file"] == "SAVGAMB.PTY" and game.mode == "party"
    assert game.keys[-8:] == ["Down"] * 6 + ["Return", "b"]


@pytest.mark.parametrize("walls", [0, 2])
def test_pools_of_darkness_walks_one_square_turning_past_walls(tmp_path, walls):
    game = FakePool(tmp_path)
    d = da.Driver(game, lambda **k: None, "A", "darkness")
    d.where = "map"
    d.world_ink = game.capture().ink(dosbox.BAR)

    class Movement:
        def __init__(self):
            self.facing, self.x, self.keys, self.walls = 0, 0, [], walls

        def status(self):
            return f"{self.x},{self.facing}"

        def turn_right(self):
            self.keys.append("Right")
            self.facing = (self.facing + 1) % 4
            return True

        def step(self):
            self.keys.append("Up")
            if self.walls:
                self.walls -= 1
            else:
                self.x += 1
            return True

    d.game = Movement()
    got = d.walk("1")
    assert d.game.keys == ["Up", "Right"] * walls + ["Up"]
    assert got["turns"] == walls and got["status_after"] == f"1,{walls}"


def test_pools_of_darkness_stops_when_every_facing_is_a_wall(tmp_path):
    game = FakePool(tmp_path)
    d = da.Driver(game, lambda **k: None, "A", "darkness")
    d.where = "map"
    d.world_ink = game.capture().ink(dosbox.BAR)

    class Walls:
        facing = 0

        def status(self):
            return f"0,{self.facing}"

        def turn_right(self):
            self.facing = (self.facing + 1) % 4
            return True

        def step(self):
            return True

    d.game = Walls()
    with pytest.raises(da.StepFailed, match="no facing"):
        d.walk("1")


def test_the_run_boots_start_bat_from_the_title_own_directory(monkeypatch, pod_source):
    """`dospod.find_game`, not the `START.EXE` search, and `START.BAT` as
    the launcher; a container of the wrong title is refused before a claim."""
    out, _ = pod_source
    tmp_path = out.parent
    log = _fake_run(monkeypatch, tmp_path, menu_error=TimeoutError("stopped here"))
    booted = {}

    def session(slot, game, exe="START.EXE"):
        booted.update(game=game, exe=exe)
        return _Session(tmp_path, log)

    monkeypatch.setattr(dosbox, "Session", session)
    monkeypatch.setattr(dospod, "find_game", lambda stem="DARKNESS": tmp_path / stem)
    args = _run_args(tmp_path, ["load"])
    args.title, args.save = "darkness", str(out / "source")
    da.run(args)
    assert booted == {"game": tmp_path / "DARKNESS", "exe": "START.BAT"}
    args.title = "pool"
    log.clear()
    with pytest.raises(ValueError, match="SAVGAMA.PTY, not the SAVGAMA.DAT pool"):
        da.run(args)
    assert "claim" not in log


# -- Pools of Darkness' journal question -------------------------------------------


def test_the_journal_question_after_begin_is_answered_and_the_steps_after_it_work(
        tmp_path, pod_journal):
    """Run 0's stop: `Begin` led to the question, and the driver took it for
    the map and typed `camp`'s and `sheet`'s keys into it.  Now the question
    gets `x` and `Return` and nothing else, and camp, a sheet, its items and
    the camp save run as they would without it."""
    game, d = _pod_driver(tmp_path, question=False, journal=True, pages=2)
    d.load()
    d.begin()
    assert game.mode == "map" and d.where == "map"
    assert game.into_journal == [dospod.JOURNAL_ANSWER, "Return"]
    assert [e["kind"] for e in d.events] == ["journal"]
    d.camp()
    assert game.mode == "camp"
    d.sheet(1)
    items = d.items(1)
    assert len(items["pages"]) == 2 and game.mode == "camp"
    assert d.save("D")["file"] == "SAVGAMD.PTY"
    assert game.into_journal == [dospod.JOURNAL_ANSWER, "Return"]


def test_the_question_is_answered_before_a_step_finds_it(tmp_path, pod_journal):
    """Wherever a step starts, the question showing is answered first, so the
    step's own keys land on the map rather than in the answer box."""
    game, d = _pod_driver(tmp_path, question=False)
    d.load()
    d.begin()
    game.mode = "journal"
    assert d.journal("camp")
    assert game.mode == "map"
    assert not d.journal("camp")
    d.camp()
    assert game.into_journal == [dospod.JOURNAL_ANSWER, "Return"]


def test_exit_is_never_typed_into_the_question(tmp_path, pod_journal):
    """Leaving a sheet presses `Exit` until the camp bar is back; on the
    question that key would be an answer, so it is answered and the run stops."""
    game, d = _pod_driver(tmp_path, question=False)
    d.load()
    d.begin()
    d.camp()
    game.mode = "journal"
    with pytest.raises(da.StepFailed, match="journal question interrupted"):
        d.back_to_camp("sheet-1-back")
    assert game.into_journal == [dospod.JOURNAL_ANSWER, "Return"]
    assert da.LEAVE not in game.into_journal


def test_other_titles_never_look_for_the_question(tmp_path, pod_journal):
    game = FakePool(tmp_path)
    d = da.Driver(game, lambda **k: None, "A", "curse")
    game.capture = lambda: pytest.fail("the question was looked for")
    assert not d.journal("camp")


def test_the_answer_is_no_key_the_driver_presses_on_the_map_camp_or_sheet():
    """Should a frame ever be misread as the question, `x` is none of the map
    bar's, the camp bar's or the sheet bar's commands."""
    driven = {da.ENCAMP, da.CAMP_SAVE, da.CAMP_REST, da.VIEW, da.SHEET_ITEMS,
              da.LEAVE, da.ITEMS_NEXT, *da.LATER_REST.__dict__.values()}
    assert dospod.JOURNAL_ANSWER not in driven


def test_the_run_looks_for_the_question_before_every_step(monkeypatch, tmp_path):
    _fake_run(monkeypatch, tmp_path, menu_error=TimeoutError("stopped"))
    da.run(_run_args(tmp_path, ["load"]))
    assert da.Driver.asked == ["load"]
    assert da.Driver.declined == ["load"]
    assert da.Driver.continued == ["load"]


def test_pools_at_load_from_where_is_pressed_once(tmp_path):
    """A `p` the screen drops is not pressed again: the run stops at
    `lost-load-from` rather than send a key the next screen might take."""
    game, d = _pod_driver(tmp_path, question=False, swallow_p=True)
    with pytest.raises(da.StepFailed, match="POOLS at LOAD FROM WHERE"):
        d.load()
    assert game.keys.count(da.POD_LOAD_FROM) == 1 and game.mode == "from"


# -- Pools of Darkness' YES NO bars after Begin -----------------------------------


@pytest.fixture
def pod_yes_no(monkeypatch):
    """The driver knows the fake's `YES NO` bar by its own signature, as it
    knows the real one by `POD_YES_NO_BAR`."""
    monkeypatch.setattr(da, "POD_YES_NO_BAR",
                        da.bar_signature(_screen(FakePod.BARS["tour"], b"")))


def test_the_arrival_question_after_begin_is_declined_and_the_steps_after_it_work(
        tmp_path, pod_journal, pod_yes_no):
    """Run 0's stop at 75e0c741: `Begin` led through the journal question to a
    `YES NO` bar, the driver took the bar for the map, and `camp`'s `E` changed
    nothing.  Now the bar gets `N` and nothing else, and camp, a sheet, its
    items and the camp save run behind it."""
    game, d = _pod_driver(tmp_path, question=False, journal=True, tours=1, pages=2)
    d.load()
    d.begin()
    assert game.mode == "map" and d.where == "map"
    assert game.into_tour == [da.POD_DECLINE]
    assert [e["kind"] for e in d.events] == ["journal", "yes_no"]
    assert d.events[1]["answered"] == "N" and d.events[1]["step"] == "begin"
    d.camp()
    d.sheet(1)
    assert len(d.items(1)["pages"]) == 2 and game.mode == "camp"
    assert d.save("D")["file"] == "SAVGAMD.PTY"
    assert game.into_tour == [da.POD_DECLINE]
    assert "y" not in game.keys and "Y" not in game.keys


def test_the_decline_key_is_the_first_letter_of_no():
    """The menu routine keys a word by its first capital (`GAME.OVR` 0x3A220)
    and puts the key pressed through `UpCase` (0x3A90F)."""
    assert da.POD_DECLINE.upper() == "NO"[0] != "YES"[0]


def test_without_a_measured_map_bar_begin_stops_at_the_screen_it_reached(
        tmp_path, monkeypatch, pod_yes_no):
    """With no measured bar, whatever follows the answer, the map included,
    stops `begin` with a shot; `camp` never runs."""
    monkeypatch.setattr(da, "POD_MAP_BARS", {})
    game, d = _pod_driver(tmp_path, question=False, tours=1)
    d.load()
    with pytest.raises(da.StepFailed, match="no Pools of Darkness map bar.*"
                       "lost-begin-screen"):
        d.begin()
    assert game.mode == "map" and d.where == "party"
    assert game.keys[-1] == da.POD_DECLINE and da.ENCAMP not in game.keys


def test_the_yes_no_bar_is_never_taken_for_the_map(tmp_path, pod_yes_no):
    """A bar `N` does not change is pressed twice and stops the run, rather
    than being recorded as the map and given `camp`'s key."""
    game, d = _pod_driver(tmp_path, question=False, tours=1, dead_n=True)
    d.load()
    with pytest.raises(da.StepFailed, match="NO changed nothing"):
        d.begin()
    assert game.into_tour == [da.POD_DECLINE] * 2 and game.mode == "tour"


def test_a_screen_after_the_answer_that_is_not_the_map_stops_begin(tmp_path,
                                                                  pod_yes_no):
    """A story screen after the answer is shot, and nothing is typed into it."""
    game, d = _pod_driver(tmp_path, question=False, tours=1, after_tour="story")
    d.load()
    with pytest.raises(da.StepFailed, match="not a measured map bar"):
        d.begin()
    assert game.mode == "story" and game.keys[-1] == da.POD_DECLINE


@pytest.mark.parametrize("tours", [2, da.POD_YES_NO_ROUNDS])
def test_bars_one_after_another_are_each_declined_and_shot(tmp_path, pod_yes_no,
                                                           tours):
    game, d = _pod_driver(tmp_path, question=False, tours=tours)
    d.load()
    d.begin()
    assert game.mode == "map"
    assert game.into_tour == [da.POD_DECLINE] * tours
    assert [e["kind"] for e in d.events] == ["yes_no"] * tours
    assert len({e["shot"] for e in d.events}) == tours


def test_bars_that_keep_coming_stop_the_run(tmp_path, pod_yes_no):
    game, d = _pod_driver(tmp_path, question=False, tours=da.POD_YES_NO_ROUNDS + 1)
    d.load()
    with pytest.raises(da.StepFailed, match=f"after {da.POD_YES_NO_ROUNDS} were"):
        d.begin()
    assert game.into_tour == [da.POD_DECLINE] * da.POD_YES_NO_ROUNDS


def test_a_yes_no_bar_found_before_a_step_is_declined_first(tmp_path, pod_yes_no):
    game, d = _pod_driver(tmp_path, question=False)
    d.load()
    d.begin()
    game.mode, game.tours = "tour", 1
    assert d.yes_no("camp") == 1
    assert game.mode == "map"
    assert d.yes_no("camp") == 0
    d.camp()
    assert game.mode == "camp" and game.into_tour == [da.POD_DECLINE]


def test_other_titles_never_look_for_a_yes_no_bar(tmp_path, pod_yes_no):
    game = FakePool(tmp_path)
    d = da.Driver(game, lambda **k: None, "A", "curse")
    game.capture = lambda: pytest.fail("the bar was looked for")
    assert d.yes_no("camp") == 0



# -- Pools of Darkness' story dialogs that say to press a button or Enter -------


def test_a_late_first_n_is_not_followed_by_a_blind_second(tmp_path, pod_yes_no):
    """The screen changed just after the wait ran out: the second `N` would
    land on the map as a command key."""
    game, d = _pod_driver(tmp_path, question=False, tours=1, late_n=True)
    d.load()
    d.begin()
    assert game.into_tour == ["n"] and game.into_map == [] and game.mode == "map"


def test_a_late_n_onto_another_yes_no_bar_is_declined_by_the_loop(tmp_path,
                                                                 pod_yes_no):
    """The second dialog is shot and declined once, visibly, and counted."""
    game, d = _pod_driver(tmp_path, question=False, tours=2, late_n=True)
    d.load()
    d.begin()
    assert game.into_tour == ["n"] * 2 and game.mode == "map"
    assert [e["kind"] for e in d.events] == ["yes_no"] * 2
    assert len({e["shot"] for e in d.events}) == 2


@pytest.fixture
def pod_continue(monkeypatch, pod_yes_no):
    """The driver knows the fake's continue bar by its own signature."""
    monkeypatch.setattr(da, "POD_CONTINUE_BAR",
                        da.bar_signature(_screen(FakePod.BARS["cont"], b"")))


def test_the_continue_bar_is_not_another_known_bar():
    assert da.POD_CONTINUE_BAR != da.POD_YES_NO_BAR
    assert da.POD_CONTINUE == "Return" and da.POD_CONTINUE_ROUNDS == 5


@pytest.mark.parametrize("continues", [1, da.POD_CONTINUE_ROUNDS])
def test_continue_screens_after_the_answer_get_return_and_nothing_else(
        tmp_path, pod_continue, continues):
    game, d = _pod_driver(tmp_path, question=False, tours=1, continues=continues)
    d.load()
    d.begin()
    assert game.mode == "map" and d.where == "map"
    assert game.into_cont == ["Return"] * continues
    assert [e["kind"] for e in d.events] == ["yes_no"] + ["press_continue"] * continues
    assert len({e["shot"] for e in d.events}) == continues + 1
    assert "y" not in game.keys and "Y" not in game.keys


def test_a_sixth_continue_screen_stops_the_run(tmp_path, pod_continue):
    game, d = _pod_driver(tmp_path, question=False,
                          continues=da.POD_CONTINUE_ROUNDS + 1)
    d.load()
    with pytest.raises(da.StepFailed, match="after 5 were answered.*lost-continue-begin"):
        d.begin()
    assert game.into_cont == ["Return"] * da.POD_CONTINUE_ROUNDS


def test_a_return_that_changes_nothing_stops_the_run(tmp_path, pod_continue):
    game, d = _pod_driver(tmp_path, question=False, continues=1, dead_return=True)
    d.load()
    with pytest.raises(da.StepFailed, match="Return changed nothing"):
        d.begin()
    assert game.into_cont == ["Return"] * 2


def test_with_no_measured_map_the_screen_after_the_last_continue_stops_begin(
        tmp_path, monkeypatch, pod_continue):
    monkeypatch.setattr(da, "POD_MAP_BARS", {})
    game, d = _pod_driver(tmp_path, question=False, tours=1, continues=2)
    d.load()
    with pytest.raises(da.StepFailed, match="lost-begin-screen"):
        d.begin()
    assert game.keys[-1] == "Return" and da.ENCAMP not in game.keys


def test_begin_gives_up_after_too_many_interstitials(tmp_path, monkeypatch,
                                                     pod_continue):
    """The bound is on screens: with 2 allowed, a third is not answered."""
    monkeypatch.setattr(da, "POD_INTERSTITIALS", 2)
    game, d = _pod_driver(tmp_path, question=False, continues=4)
    d.load()
    with pytest.raises(da.StepFailed, match="lost-begin-interstitials"):
        d.begin()
    assert game.into_cont == ["Return"] * 2


def test_the_bound_counts_screens_across_the_helpers_not_passes(
        tmp_path, monkeypatch, pod_continue):
    """A pass can answer a bar, then continues; 4 screens in one pass must not
    get past a bound of 3."""
    monkeypatch.setattr(da, "POD_INTERSTITIALS", 3)
    game, d = _pod_driver(tmp_path, question=False, tours=2, continues=3)
    d.load()
    with pytest.raises(da.StepFailed, match="lost-begin-interstitials"):
        d.begin()
    assert game.into_tour == [da.POD_DECLINE] * 2 and game.into_cont == ["Return"]


def test_a_full_allowance_is_still_enough(tmp_path, monkeypatch, pod_continue):
    monkeypatch.setattr(da, "POD_INTERSTITIALS", 4)
    game, d = _pod_driver(tmp_path, question=False, tours=2, continues=2)
    d.load()
    d.begin()
    assert game.mode == "map" and len(d.events) == 4


def test_a_late_first_return_is_not_followed_by_a_blind_second(tmp_path,
                                                               pod_continue):
    """The screen changed just after the wait ran out: the second `Return`
    would dismiss the next screen unseen."""
    game, d = _pod_driver(tmp_path, question=False, continues=1, late_return=True)
    d.load()
    d.begin()
    assert game.into_cont == ["Return"] and game.mode == "map"
    assert game.into_map == []


def test_a_late_return_onto_another_continue_screen_is_answered_by_the_loop(
        tmp_path, pod_continue):
    game, d = _pod_driver(tmp_path, question=False, continues=2, late_return=True)
    d.load()
    d.begin()
    assert game.into_cont == ["Return"] * 2 and game.mode == "map"
    assert [e["kind"] for e in d.events] == ["press_continue"] * 2


def test_a_continue_screen_found_before_a_step_is_answered_first(tmp_path,
                                                                 pod_continue):
    game, d = _pod_driver(tmp_path, question=False)
    d.load()
    d.begin()
    game.mode, game.continues = "cont", 1
    assert d.press_continue("camp") == 1 and game.mode == "map"
    assert d.press_continue("camp") == 0


def test_other_titles_never_look_for_a_continue_screen(tmp_path, pod_continue):
    game = FakePool(tmp_path)
    d = da.Driver(game, lambda **k: None, "A", "curse")
    game.capture = lambda: pytest.fail("the bar was looked for")
    assert d.press_continue("camp") == 0


@pytest.fixture
def two_map_bars(monkeypatch, pod_yes_no):
    """The fakes' dungeon map and overland bars stand in for the two
    measured ones."""
    monkeypatch.setattr(da, "POD_MAP_BARS", {
        "dungeon": da.bar_signature(_screen(FakePool.BARS["map"], b"")),
        "overland": da.bar_signature(_screen(FakePod.BARS["overland"], b""))})


@pytest.mark.parametrize("kind, after", [("dungeon", "map"), ("overland", "overland")])
def test_begin_takes_each_measured_map_bar_and_says_which(tmp_path, two_map_bars,
                                                          kind, after):
    notes = []
    game = FakePod(tmp_path, question=False, tours=1, after_tour=after)
    d = da.Driver(game, lambda **k: notes.append(k), "A", "darkness",
                  party_size=game.size)
    d.load()
    got = d.begin()
    assert got["map_kind"] == kind and d.where == "map"
    assert [n["map"] for n in notes if n.get("event") == "map_bar"] == [kind]


def test_camp_works_from_the_overland_bar(tmp_path, two_map_bars):
    game, d = _pod_driver(tmp_path, question=False, tours=1, after_tour="overland")
    d.load()
    d.begin()
    d.camp()
    assert game.mode == "camp" and d.where == "camp"


def test_an_unmeasured_bar_still_stops_begin(tmp_path, two_map_bars):
    game, d = _pod_driver(tmp_path, question=False, tours=1, after_tour="story")
    d.load()
    with pytest.raises(da.StepFailed, match="not a measured map bar"):
        d.begin()
    assert da.ENCAMP not in game.keys


def test_the_measured_pod_map_bars_are_sixteen_hex_digits(monkeypatch):
    monkeypatch.undo()
    assert set(da.POD_MAP_BARS) == {"dungeon", "overland"}
    assert len(set(da.POD_MAP_BARS.values())) == 2
    for bar in da.POD_MAP_BARS.values():
        assert len(bar) == 16
        int(bar, 16)


def test_the_measured_pod_map_bar_matches_the_captured_map(monkeypatch):
    """The value was read off a live run's map screen; that capture is in the
    player's cache, not the repository, so this skips without it."""
    import shutil
    import subprocess

    from tools.registry.scratch import cache_dir
    shot = cache_dir("acceptance", "650", "e38a1bb514-run0-control", "shots",
                     "009-lost-begin-screen.png")
    if not shot.exists() or shutil.which("convert") is None:
        pytest.skip("the captured Pools of Darkness map is not on this machine")
    monkeypatch.undo()
    ppm = subprocess.run(["convert", str(shot), "-depth", "8", "ppm:-"],
                         check=True, capture_output=True).stdout
    assert da.bar_signature(dosbox.Screen.from_ppm(ppm)) == da.POD_MAP_BARS["dungeon"]


def test_the_measured_overland_bar_matches_the_captured_screen(monkeypatch):
    """Read off the Amiga cleric run's screen; that capture is in the player's
    cache, so this skips without it."""
    import shutil
    import subprocess

    from tools.registry.scratch import cache_dir
    shot = cache_dir("acceptance", "650", "840311866e-run1-cleric", "shots",
                     "006-lost-begin-screen.png")
    if not shot.exists() or shutil.which("convert") is None:
        pytest.skip("the captured overland screen is not on this machine")
    monkeypatch.undo()
    ppm = subprocess.run(["convert", str(shot), "-depth", "8", "ppm:-"],
                         check=True, capture_output=True).stdout
    assert da.bar_signature(dosbox.Screen.from_ppm(ppm)) == da.POD_MAP_BARS["overland"]


# -- the town services screen ---------------------------------------------------


@pytest.fixture
def pod_town(monkeypatch, pod_yes_no):
    """The driver knows the fake's town bar by its own signature."""
    monkeypatch.setattr(da, "POD_TOWN_BAR",
                        da.bar_signature(_screen(FakePod.BARS["town"], b"")))


def test_the_measured_town_bar_is_sixteen_hex_digits_and_not_a_map():
    assert len(da.POD_TOWN_BAR) == 16 and int(da.POD_TOWN_BAR, 16) >= 0
    assert da.POD_TOWN_BAR not in da.POD_MAP_BARS.values()
    assert not hasattr(da, "POD_TOWN_LEAVE")


def test_a_town_bar_stops_begin_with_a_shot_and_presses_nothing(tmp_path,
                                                               pod_town):
    game, d = _pod_driver(tmp_path, question=False, tours=1, after_tour="town")
    d.load()
    with pytest.raises(da.StepFailed, match="town services screen.*lost-begin-screen"):
        d.begin()
    assert game.into_town == [] and d.where == "party"


def test_a_town_screen_after_the_journal_question_is_a_town_stop(tmp_path,
                                                                pod_town,
                                                                pod_journal):
    game, d = _pod_driver(tmp_path, question=False, journal=True, tours=1,
                          after_tour="town")
    d.load()
    with pytest.raises(da.StepFailed, match="town services screen.*lost-begin-screen"):
        d.begin()
    assert [e["kind"] for e in d.events] == ["journal", "yes_no"]
    assert game.into_town == []


def test_an_unknown_bar_is_not_taken_for_the_town(tmp_path, pod_yes_no):
    """Without a measured town bar the fake's town screen stops `begin` with
    nothing pressed on it."""
    game, d = _pod_driver(tmp_path, question=False, tours=1, after_tour="town")
    d.load()
    with pytest.raises(da.StepFailed, match="lost-begin-screen"):
        d.begin()
    assert game.into_town == []
