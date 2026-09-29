"""`walk_to_encounter`'s patience for a bar it does not recognise.

`#217 (The DOS walk-to-an-encounter gives up on one mid-redraw frame)`: one
captured frame landing on `blank` -- the bar row caught mid-redraw -- gave up
the whole run, where `PoolOfRadiance.fight()` beside it waits for the bar to
become something it knows.  No emulator is needed: `walk_to_encounter` and
`_await_bar` talk to a `PoolOfRadiance` through `step`, `status`, `turn_right`,
`bar_kind` and `s`, so a stand-in for those is enough.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.dos import dosbox, dosfightwatch  # noqa: E402


class _Screen:
    def glyphs(self, rect=None) -> str:
        return "blank-digest"


class _FakeSession:
    def __init__(self):
        self.shots: list[str] = []
        self.pressed: list[str] = []

    def capture(self) -> _Screen:
        return _Screen()

    def shot(self, name: str, allow_blank: bool = False):
        self.shots.append(name)
        return None

    def key(self, *keys, gap=0.0) -> None:
        self.pressed.extend(keys)

    def wait_until_ink(self, rect, same, timeout=30.0) -> bool:
        return True


class _FakePoR:
    """A party that never moves: every step is blocked by whatever bar_kind gives."""

    COMBAT_KEYS = dosbox.PoolOfRadiance.COMBAT_KEYS

    def __init__(self, kinds):
        self._kinds = iter(kinds)
        self._last: str | None = None
        self.s = _FakeSession()
        self.world_bar = "world"

    def status(self) -> str:
        return "status"

    def step(self) -> bool:
        return False

    def turn_right(self) -> bool:
        return True

    def bar_kind(self, screen=None) -> str | None:
        try:
            self._last = next(self._kinds)
        except StopIteration:
            pass
        return self._last


def test_a_frame_caught_mid_redraw_is_not_the_end_of_the_walk():
    """The regression: `blank` seen once and gone is a frame, not a defeat."""
    por = _FakePoR(["blank", "encounter"])
    result = dosfightwatch.walk_to_encounter(por, steps=5, patience=5.0)
    assert result["met"] is True
    assert result["bar"] == "encounter"


def test_a_bar_that_never_resolves_gives_up_and_names_its_digest():
    """`blank` for ever is a stuck game, and the shot is what names it later.

    `patience=0.0` puts the deadline in the past before it is first checked,
    so the give-up path runs with no real sleep at all -- the trick
    `tests/dos/test_dosfight.py::test_a_bar_nobody_has_labelled_gives_up_naming_its_digest`
    already uses on `fight()`'s copy of this mechanism.
    """
    por = _FakePoR(["blank"])
    result = dosfightwatch.walk_to_encounter(por, steps=5, patience=0.0)
    assert result["met"] is False
    assert "blank" in result["why"]
    assert por.s.shots == ["walk_unknown_bar_blank-digest"]


def test_a_bar_nobody_has_labelled_at_all_still_gives_up_by_its_digest():
    """`bar_kind` returning `None` is a bar not in `COMBAT_BARS` at all."""
    por = _FakePoR([None])
    result = dosfightwatch.walk_to_encounter(por, steps=5, patience=0.0)
    assert result["met"] is False
    assert result["why"] == "a bar nobody has labelled (None)"


# -- the treasure split (#743): no emulator, a scripted debugger ---------------

import pytest  # noqa: E402

from goldbox import dos_savegame  # noqa: E402
from tools.dos import dosboxx  # noqa: E402

BIAS = 0x30000          # where the fake overlay sits in memory
DS = 0x4000
SS, BP = 0x5000, 0x0100


def _ovr() -> bytes:
    data = bytearray(0x7000)
    for i in range(len(data)):
        data[i] = (i * 7 + 3) & 0xFF
    return bytes(data)


class _Debugger:
    """Just enough of `XSession`: a log, registers, memory and a script."""

    def __init__(self, ovr: bytes, hits, counts):
        self.mem = bytearray(0x100000)
        self.mem[BIAS:BIAS + len(ovr)] = ovr
        self.log = ""
        self.regs_now: dict[str, int] = {"DS": DS, "SS": SS, "BP": BP}
        self.commands: list[str] = []
        self.events = list(hits)
        self.counts = counts
        self.bp: int | None = None
        self.halted_now = False
        self.keys: list[str] = []

    # what the fight loop and the arming code call
    def dbg(self, cmd, expect=None, timeout=5.0, quiet=0.3):
        self.commands.append(cmd)
        return ""

    def log_text(self):
        return self.log

    def attach(self, tries=6, gap=1.0):
        return True

    def capture(self):
        return _Screen()

    def key(self, *keys, gap=0.0):
        self.keys.extend(keys)

    def shot(self, name, allow_blank=False):
        return None

    def regs(self, *names):
        return {n: self.regs_now[n] for n in names}

    def read(self, addr, n):
        lin = dosboxx.linear(addr)
        return bytes(self.mem[lin:lin + n])

    def brk(self, addr):
        self.bp = dosboxx.linear(addr)
        self.commands.append(f"BP {self.bp:X}")

    def clear_breakpoints(self):
        self.bp = None
        self.commands.append("BPDEL *")

    def halted(self, timeout=3.0):
        return self.halted_now

    def run(self):
        self.halted_now = False
        if self.bp is not None:
            cs, ip = dosboxx.seg_off(self.bp)
            self.regs_now.update(CS=cs, IP=ip)
            base = dosboxx.linear((SS, BP - 6))
            self.mem[base:base + 2] = bytes(self.counts)
            self.halted_now = True
            return
        if not self.events:
            return
        byte, old, new, offset, length = self.events.pop(0)
        after = BIAS + offset + length
        cs, ip = dosboxx.seg_off(after)
        self.regs_now.update(CS=cs, IP=ip)
        seg, ofs = dosboxx.seg_off(dosboxx.linear((DS, dosfightwatch.GOLD_PILE)) + byte)
        self.log += (f"DEBUG: Memory breakpoint : {seg:04X}:{ofs:04X} - "
                     f"{old:02X} -> {new:02X}\n")


def _por(dbg):
    por = _FakePoR(["command"])
    por.s = dbg
    por.world_glyphs = "blank-digest"
    return por


def _script(pile_before: int, cut: int):
    """Fill hits for `pile_before`, then split hits down by `cut`."""
    fill, split = dosfightwatch.FILL_OFFSET, dosfightwatch.SPLIT_OFFSET
    hits, state = [], bytearray(4)
    for target, offset, length in ((pile_before, fill, 3),
                                   (pile_before - cut, split, 4)):
        want = target.to_bytes(4, "little")
        for i in range(4):
            if want[i] != state[i]:
                hits.append((i, state[i], want[i], offset, length))
                state[i] = want[i]
    return hits


def test_the_split_formula_is_the_engines_byte_quotient():
    assert dosfightwatch.expected_cut(1000, 7, 13) == 532
    assert dosfightwatch.expected_cut(1000, 3, 9) == 333
    assert dosfightwatch.expected_cut(4000, 7, 13) == 357   # (307 & 255) * 7


def test_a_folder_is_installed_as_it_stands_and_can_be_moved(tmp_path):
    folder, save = tmp_path / "spec", tmp_path / "SAVE"
    folder.mkdir()
    save.mkdir()
    (folder / "SAVGAME.DAT").write_bytes(bytes(13000))
    (folder / "CHRDATE7.SAV").write_bytes(b"\x07" * 285)
    (save / "CHRDATA1.SAV").write_bytes(b"stale")
    letter = dosfightwatch.install_folder(save, folder, at="5,6,E")
    assert letter == "E"
    assert sorted(p.name for p in save.iterdir()) == ["CHRDATE7.SAV", "SAVGAME.DAT"]
    assert (save / "CHRDATE7.SAV").read_bytes() == b"\x07" * 285
    data = (save / "SAVGAME.DAT").read_bytes()
    assert (data[dos_savegame.POS_X], data[dos_savegame.POS_Y]) == (5, 6)


def test_the_pile_is_watched_and_the_split_read_from_scripted_hits():
    ovr = _ovr()
    dbg = _Debugger(ovr, _script(1000, 532), counts=(13, 7))   # A, C
    por = _por(dbg)
    report = dosfightwatch.measure_split(
        por, ovr, steps=5, fight_kw={"settled": 0.0},
        walk=lambda por, steps: {"met": True})
    gold = dosboxx.linear((DS, dosfightwatch.GOLD_PILE))
    for i in range(4):
        seg, ofs = dosboxx.seg_off(gold + i)
        assert f"BPM {seg:X}:{ofs:X}" in dbg.commands
    assert report["bias"] == BIAS
    seg, ofs = dosboxx.seg_off(BIAS + dosfightwatch.COUNT_OFFSET)
    assert report["count_break"] == f"{seg:04X}:{ofs:04X}"
    assert dbg.bp == BIAS + dosfightwatch.COUNT_OFFSET
    assert report["fill_agrees"] is True
    assert report["pile"] == {"before": 1000, "after": 468}
    assert (report["counts"]["c"], report["counts"]["a"]) == (7, 13)
    assert report["expected_cut"] == 532 == report["taken"]
    assert report["matches"] is True


def test_a_split_that_takes_less_than_the_rule_says_is_reported():
    ovr = _ovr()
    dbg = _Debugger(ovr, _script(1000, 400), counts=(13, 7))
    report = dosfightwatch.measure_split(
        _por(dbg), ovr, steps=5, fight_kw={"settled": 0.0},
        walk=lambda por, steps: {"met": True})
    assert report["taken"] == 400 and report["expected_cut"] == 532
    assert report["matches"] is False


def test_pile_mode_refuses_to_run_without_a_folder():
    with pytest.raises(SystemExit):
        dosfightwatch.main(["pile"])


def test_two_bytes_tripped_by_one_word_write_are_both_classified():
    ovr = _ovr()
    script = _script(1000, 532)
    # The fill's two byte hits and the split's two arrive in one halt each.
    dbg = _Debugger(ovr, script, counts=(13, 7))
    real_run = dbg.run

    def run():
        real_run()
        if dbg.bp is None and dbg.events and dbg.events[0][3] == script[0][3]:
            real_run()
        elif dbg.bp is None and dbg.events and dbg.events[0][3] == script[2][3]:
            real_run()
    dbg.run = run
    report = dosfightwatch.measure_split(
        _por(dbg), ovr, steps=5, fight_kw={"settled": 0.0},
        walk=lambda por, steps: {"met": True})
    assert all(h["phase"] for h in report["hits"])
    assert report["pile"] == {"before": 1000, "after": 468}
    assert report["taken"] == 532 and report["matches"] is True


def test_a_ds_that_is_not_the_games_is_refused_and_the_override_skips_the_check():
    ovr = _ovr()
    dbg = _Debugger(ovr, [], counts=(13, 7))
    base = dosboxx.linear((DS, dosfightwatch.PILE_BASE))
    dbg.mem[base + 8:base + 12] = b"\x00\x00\x05\x00"      # a pile of 327,680
    report = dosfightwatch.measure_split(
        _por(dbg), ovr, steps=5, fight_kw={"settled": 0.0},
        walk=lambda por, steps: {"met": True})
    assert "not the game's data segment" in report["why"]
    assert not any(c.startswith("BPM") for c in dbg.commands)
    dbg2 = _Debugger(ovr, [], counts=(13, 7))
    dbg2.mem[base + 8:base + 12] = b"\x00\x00\x05\x00"
    dosfightwatch.measure_split(_por(dbg2), ovr, steps=5, ds=DS,
                                fight_kw={"settled": 0.0},
                                walk=lambda por, steps: {"met": True})
    assert any(c.startswith("BPM") for c in dbg2.commands)


def test_a_count_breakpoint_that_never_fires_says_why(monkeypatch):
    ovr = _ovr()
    dbg = _Debugger(ovr, _script(1000, 532), counts=(13, 7))
    monkeypatch.setattr(dosfightwatch, "count_fight", lambda por, brk: None)
    report = dosfightwatch.measure_split(
        _por(dbg), ovr, steps=5, fight_kw={"settled": 0.0},
        walk=lambda por, steps: {"met": True})
    assert "count breakpoint" in report["why"]
