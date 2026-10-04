"""`walk_to_encounter`'s patience for a bar it does not recognise.

`#217 (The DOS walk-to-an-encounter gives up on one mid-redraw frame)`: one
captured frame landing on `blank` -- the bar row caught mid-redraw -- gave up
the whole run, where `PoolOfRadiance.fight()` beside it waits for the bar to
become something it knows.  No emulator is needed: `walk_to_encounter` and
`_await_bar` talk to a `PoolOfRadiance` through `step`, `status`, `turn_right`,
`bar_kind` and `s`, so a stand-in for those is enough.
"""

from __future__ import annotations

import collections
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
        self.pile = dosfightwatch.GOLD_PILE     # which pile the events hit

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
        seg, ofs = dosboxx.seg_off(dosboxx.linear((DS, self.pile)) + byte)
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
        walk=lambda por, steps: {"met": True}, share=0xFF)
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


def test_a_split_that_hits_only_the_silver_pile_is_measured_and_matched():
    ovr = _ovr()
    dbg = _Debugger(ovr, _script(1000, 532), counts=(13, 7))
    dbg.pile = dosfightwatch.PILE_BASE + 4          # silver
    report = dosfightwatch.measure_split(
        _por(dbg), ovr, steps=5, fight_kw={"settled": 0.0},
        walk=lambda por, steps: {"met": True}, share=0xFF)
    base = dosboxx.linear((DS, dosfightwatch.PILE_BASE))
    for i in range(28):
        seg, ofs = dosboxx.seg_off(base + i)
        assert f"BPM {seg:X}:{ofs:X}" in dbg.commands
    assert report["bias"] == BIAS
    assert report["pile"] is None                    # no gold change
    assert report["piles"] == {"silver": {
        "before": 1000, "after": 468, "taken": 532, "expected_cut": 532,
        "expected_after": 468, "matches": True}}
    assert report["matches"] is True
    assert report["piles_at_encounter"]["silver"] == 0


def test_a_nonzero_pile_with_no_split_seen_keeps_matches_false():
    ovr = _ovr()
    # The four bytes of the nonzero gold pile each owe one false first hit,
    # which arming absorbs before the fight's own hits.
    spurious = [(i, 0, (500).to_bytes(4, "little")[i], 0, 2) for i in range(4)]
    dbg = _Debugger(ovr, spurious + _script(1000, 532), counts=(13, 7))
    dbg.pile = dosfightwatch.PILE_BASE + 4          # silver is split
    gold = dosboxx.linear((DS, dosfightwatch.GOLD_PILE))
    dbg.mem[gold:gold + 4] = (500).to_bytes(4, "little")   # gold never is
    report = dosfightwatch.measure_split(
        _por(dbg), ovr, steps=5, fight_kw={"settled": 0.0},
        walk=lambda por, steps: {"met": True}, share=0xFF)
    assert report["piles"]["silver"]["matches"] is True
    assert report["unmeasured_piles"] == ["gold"]
    assert report["gold_split_seen"] is False
    assert report["matches"] is False
    assert "gold" in report["why"]


def test_each_pile_is_reported_on_its_own_when_two_are_split():
    ovr = _ovr()
    dbg = _Debugger(ovr, [], counts=(13, 7))
    gold_hits = _script(1000, 532)
    silver_hits = _script(300, 100)
    piles = {}
    for pile, hits in ((dosfightwatch.GOLD_PILE, gold_hits),
                       (dosfightwatch.PILE_BASE + 4, silver_hits)):
        piles[pile] = hits
    # One pile at a time: each pile's events are replayed against its own address.
    events = []
    for pile, hits in piles.items():
        events += [(pile, h) for h in hits]
    real_run = dbg.run

    def run():
        if dbg.bp is None and dbg.events == [] and events:
            pile, hit = events.pop(0)
            dbg.pile = pile
            dbg.events = [hit]
        real_run()
    dbg.run = run
    report = dosfightwatch.measure_split(
        _por(dbg), ovr, steps=5, fight_kw={"settled": 0.0},
        walk=lambda por, steps: {"met": True}, share=0xFF)
    assert report["piles"]["gold"]["taken"] == 532
    assert report["piles"]["silver"]["before"] == 300
    assert report["piles"]["silver"]["taken"] == 100
    assert report["piles"]["silver"]["matches"] is False   # the rule says 161


def test_a_split_that_takes_less_than_the_rule_says_is_reported():
    ovr = _ovr()
    dbg = _Debugger(ovr, _script(1000, 400), counts=(13, 7))
    report = dosfightwatch.measure_split(
        _por(dbg), ovr, steps=5, fight_kw={"settled": 0.0},
        walk=lambda por, steps: {"met": True}, share=0xFF)
    assert report["taken"] == 400 and report["expected_cut"] == 532
    assert report["matches"] is False


def test_the_verdict_is_the_pile_arithmetic_and_not_the_count_read():
    """The count read gave a = 12, c = 26 in a live fight, which the code cannot
    produce; copper 64 -> 43 is `(64 div 9) * 3` for a `$FB` hireling."""
    ovr = _ovr()
    dbg = _Debugger(ovr, _script(64, 21), counts=(12, 26))
    dbg.pile = dosfightwatch.PILE_BASE
    report = dosfightwatch.measure_split(
        _por(dbg), ovr, steps=5, fight_kw={"settled": 0.0},
        walk=lambda por, steps: {"met": True}, share=0xFB)
    assert (report["counts"]["a"], report["counts"]["c"]) == (12, 26)
    assert report["piles"]["copper"]["expected_cut"] == 21
    assert report["matches"] is True
    assert report["rule"] == {"a": 9, "c": 3}


def test_a_share_with_no_rule_gives_no_verdict():
    ovr = _ovr()
    dbg = _Debugger(ovr, _script(64, 21), counts=(12, 26))
    dbg.pile = dosfightwatch.PILE_BASE
    report = dosfightwatch.measure_split(
        _por(dbg), ovr, steps=5, fight_kw={"settled": 0.0},
        walk=lambda por, steps: {"met": True}, share=0x42)
    assert "matches" not in report and report["rule"] is None


def test_the_rules_by_share():
    assert dosfightwatch.SHARE_RULES[0x03] == dosfightwatch.SHARE_RULES[0xFB] == (9, 3)
    assert dosfightwatch.SHARE_RULES[0xFF] == (13, 7)


def test_the_hireling_share_is_the_one_nonzero_share(tmp_path):
    for n, share in ((1, 0), (7, 0xFB)):
        rec = bytearray(285)
        rec[dosfightwatch.SHARE_OFFSET] = share
        (tmp_path / f"CHRDATD{n}.SAV").write_bytes(bytes(rec))
    assert dosfightwatch.hireling_share(tmp_path, "D") == 0xFB
    assert dosfightwatch.hireling_share(tmp_path, "E") is None


def _records(tmp_path, shares):
    for n, share in enumerate(shares, 1):
        rec = bytearray(285)
        rec[dosfightwatch.SHARE_OFFSET] = share
        (tmp_path / f"CHRDATD{n}.SAV").write_bytes(bytes(rec))


def test_player_characters_at_one_do_not_hide_the_hireling(tmp_path):
    _records(tmp_path, [1] * 6 + [0xFB])
    assert dosfightwatch.hireling_share(tmp_path, "D") == 0xFB


def test_two_records_with_the_same_ruled_share_give_no_verdict(tmp_path):
    _records(tmp_path, [0, 0, 0, 0, 0, 0xFB, 0xFB])
    assert dosfightwatch.hireling_share(tmp_path, "D") is None


def test_at_with_a_numeric_facing_names_the_letters():
    with pytest.raises(ValueError, match="N, E, S or W"):
        dosfightwatch.check_at("7,3,1")
    dosfightwatch.check_at("7,3,e")


class _LockedScreen:
    def glyphs(self, rect=None) -> str:
        return dosfightwatch.LOCKED_BAR


class _LockedSession(_FakeSession):
    """Shows the locked bar until a key is pressed, the world's bar after."""

    def capture(self):
        return _Screen() if self.pressed else _LockedScreen()


class _LockedDoorPoR(_FakePoR):
    """The first step meets a locked door, and EXIT then a turn is what the
    walk must do; the next step is the encounter."""

    def __init__(self):
        super().__init__(["encounter"])
        self.s = _LockedSession()
        self.turns = 0

    def step(self) -> bool:
        return False


def test_a_locked_door_is_answered_exit_and_the_walk_turns():
    por = _LockedDoorPoR()
    result = dosfightwatch.walk_to_encounter(por, steps=5, patience=1.0)
    assert por.s.pressed == ["e"]
    assert result["met"] is True and result["at_step"] == 2
    assert result["blocked"] == 1


def test_a_locked_door_that_does_not_clear_ends_the_walk():
    por = _LockedDoorPoR()
    por.s.wait_until_ink = lambda *a, **k: False
    result = dosfightwatch.walk_to_encounter(por, steps=5, patience=1.0)
    assert result["met"] is False
    assert result["why"] == "locked door did not clear"


def test_pile_mode_will_not_run_without_a_folder():
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
        walk=lambda por, steps: {"met": True}, share=0xFF)
    assert all(h["phase"] for h in report["hits"])
    assert report["pile"] == {"before": 1000, "after": 468}
    assert report["taken"] == 532 and report["matches"] is True


def test_a_ds_that_is_not_the_games_is_blocked_and_the_override_skips_the_check():
    ovr = _ovr()
    dbg = _Debugger(ovr, [], counts=(13, 7))
    base = dosboxx.linear((DS, dosfightwatch.PILE_BASE))
    dbg.mem[base + 8:base + 12] = b"\x00\x00\x05\x00"      # a pile of 327,680
    report = dosfightwatch.measure_split(
        _por(dbg), ovr, steps=5, fight_kw={"settled": 0.0},
        walk=lambda por, steps: {"met": True}, share=0xFF)
    assert "not the game's data segment" in report["why"]
    assert not any(c.startswith("BPM") for c in dbg.commands)
    dbg2 = _Debugger(ovr, [], counts=(13, 7))
    dbg2.mem[base + 8:base + 12] = b"\x00\x00\x05\x00"
    dosfightwatch.measure_split(_por(dbg2), ovr, steps=5, ds=DS,
                                fight_kw={"settled": 0.0},
                                walk=lambda por, steps: {"met": True}, share=0xFF)
    assert any(c.startswith("BPM") for c in dbg2.commands)


def test_a_count_breakpoint_that_never_fires_says_why(monkeypatch):
    ovr = _ovr()
    dbg = _Debugger(ovr, _script(1000, 532), counts=(13, 7))
    monkeypatch.setattr(dosfightwatch, "count_fight", lambda por, brk: None)
    report = dosfightwatch.measure_split(
        _por(dbg), ovr, steps=5, fight_kw={"settled": 0.0},
        walk=lambda por, steps: {"met": True}, share=0xFF)
    assert "count breakpoint" in report["why"]


POOL_SIZE = dos_savegame.SAVE_POOL_OF_RADIANCE.size


def _donor(*, outdoors=False) -> bytes:
    """A zero Pool save moved by `move_to_area` to the Slums, standing at 14,4 facing east."""
    save = bytearray(POOL_SIZE)
    dos_savegame.move_to_area(save, area=20, dax=2, geo=20, wallset=(2, 4, 1),
                          script=b"\0\0" + b"\x42" * 100)
    dos_savegame.put_position(save, 14, 4, 1)
    dos_savegame.put_word(save, dos_savegame.INDOORS, 0 if outdoors else 1)
    return bytes(save)


def _stage(tmp_path):
    folder, save = tmp_path / "spec", tmp_path / "SAVE"
    folder.mkdir()
    save.mkdir()
    hall = bytearray(POOL_SIZE)
    dos_savegame.move_to_area(hall, area=11, dax=3, geo=0, wallset=(0, 0xFFFF, 0xFFFF),
                          script=b"\0\0" + b"\x99" * 300)
    (folder / "SAVGAME.DAT").write_bytes(bytes(hall))
    (folder / "CHRDATE7.SAV").write_bytes(b"\x07" * 285)
    return folder, save


def test_a_folder_placed_like_a_donor_stands_where_the_donor_stands(tmp_path):
    folder, save = _stage(tmp_path)
    donor = _donor()
    script = b"\0\0" + b"\x42" * 100
    letter = dosfightwatch.install_folder(save, folder, place=(donor, script))
    data = (save / f"SAVGAM{letter}.DAT").read_bytes()
    for read in (dos_savegame.current_area, dos_savegame.geo_block,
                 dos_savegame.dax_number, dos_savegame.wall_triple,
                 dos_savegame.position):
        assert read(data) == read(donor), read.__name__
    for address in range(dos_savegame.WALLMAP, dos_savegame.WALLMAP + 3):
        assert dos_savegame.word(data, address) == dos_savegame.word(donor, address)
    assert dos_savegame.position(data) == (14, 4, 1)
    start, end = dos_savegame.ECL_BUFFER
    assert data[start:end] == donor[start:end]
    assert not dos_savegame.outdoors(data)
    assert (save / "CHRDATE7.SAV").read_bytes() == b"\x07" * 285


def test_placing_blocks_an_outdoor_donor(tmp_path):
    folder, save = _stage(tmp_path)
    with pytest.raises(ValueError, match="overland"):
        dosfightwatch.install_folder(save, folder, place=(_donor(outdoors=True), b"\0\0"))


def test_a_changed_character_file_stops_the_run_before_it_boots(tmp_path, monkeypatch):
    folder, save = _stage(tmp_path)
    dosfightwatch.install_folder(save, folder)
    assert dosfightwatch.check_records_unchanged(folder, save, "E")["records_unchanged"]
    (save / "CHRDATE7.SAV").write_bytes(b"\x08" * 285)
    with pytest.raises(ValueError, match="CHRDATE7.SAV"):
        dosfightwatch.check_records_unchanged(folder, save, "E")

    class Claimed:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class Session:
        booted = False

        def __init__(self, claimed, game):
            self.save_dir = save

        def stage(self, fresh):
            pass

        def boot(self, fresh):
            Session.booted = True

        def close(self):
            pass

    def alter(save_dir, folder, at, source, place):
        (save_dir / "CHRDATE7.SAV").write_bytes(b"\x08" * 285)
        return "E"

    monkeypatch.setattr(dosbox, "find_game", lambda *a: tmp_path)
    monkeypatch.setattr(dosboxx, "claim", lambda *a: Claimed())
    monkeypatch.setattr(dosboxx, "XSession", Session)
    monkeypatch.setattr(dosfightwatch, "install_folder", alter)
    with pytest.raises(ValueError, match="CHRDATE7.SAV"):
        dosfightwatch.pile(folder=folder, source=None, at=None, steps=1,
                           out=tmp_path / "out", ds=None)
    assert not Session.booted
    assert "records_unchanged" not in (tmp_path / "out" / "report.json").read_text()


def test_the_evoker_placed_in_the_slums_matches_the_engines_slums_save(tmp_path):
    from gamedata import specimen
    evoker = specimen("por-hireling-evoker-ff")
    slums = specimen("por-amiga-slums-dos-resave")
    from tools.dos import dosbox as db
    try:
        ecl = (db.find_game("POOLRAD") / "ECL2.DAX").read_bytes()
    except (FileNotFoundError, OSError) as e:
        pytest.skip(f"needs the DOS game files: {e}")
    donor = (slums / "SAVGAMD.DAT").read_bytes()
    script = dos_savegame.dax_block(ecl, 20, name="ECL2.DAX")
    dosfightwatch.check_donor_script(donor, script)
    save = tmp_path / "SAVE"
    save.mkdir()
    dosfightwatch.install_folder(save, evoker, place=(donor, script))
    before = (evoker / "SAVGAME.DAT").read_bytes()
    after = (save / "SAVGAME.DAT").read_bytes()
    for read in (dos_savegame.current_area, dos_savegame.geo_block,
                 dos_savegame.dax_number, dos_savegame.wall_triple,
                 dos_savegame.position):
        assert read(after) == read(donor), read.__name__
    assert (dos_savegame.current_area(after), dos_savegame.dax_number(after),
            dos_savegame.wall_triple(after)) == (20, 2, (2, 4, 1))
    assert dos_savegame.position(after) == (14, 4, 1)
    start, end = dos_savegame.ECL_BUFFER
    assert after[start:end] == donor[start:end]
    allowed = set(range(start, end)) | {0}
    for address in (dos_savegame.AREA, dos_savegame.SCRIPT, dos_savegame.DISK,
                    dos_savegame.INDOORS,
                    *range(dos_savegame.WALLSET, dos_savegame.WALLSET + 3),
                    *range(dos_savegame.WALLMAP, dos_savegame.WALLMAP + 3)):
        off = dos_savegame.word_offset(address, dos_savegame.SAVE_POOL_OF_RADIANCE)
        allowed |= {off, off + 1}
    allowed |= {12801, 12802, 12805}
    changed = {i for i in range(len(before)) if before[i] != after[i]}
    assert changed <= allowed, sorted(changed - allowed)
    assert dosfightwatch.check_records_unchanged(evoker, save, "E")["records_unchanged"]


def test_only_the_installed_slots_character_files_are_compared(tmp_path):
    folder, save = _stage(tmp_path)
    (folder / "SAVGAMF.DAT").write_bytes(bytes(POOL_SIZE))
    (folder / "CHRDATF1.SAV").write_bytes(b"\x01" * 285)
    letter = dosfightwatch.install_folder(save, folder, source="E")
    assert not (save / "CHRDATF1.SAV").exists()
    assert dosfightwatch.check_records_unchanged(folder, save, letter)


def test_the_placed_save_reports_what_still_differs_from_the_donor(tmp_path):
    folder, save = _stage(tmp_path)
    data = bytearray((folder / "SAVGAME.DAT").read_bytes())
    data[100] = 9                       # state the hall save holds and the donor does not
    (folder / "SAVGAME.DAT").write_bytes(bytes(data))
    script = b"\0\0" + b"\x42" * 100
    dosfightwatch.install_folder(save, folder, place=(_donor(), script))
    report = dosfightwatch.place_like(save / "SAVGAME.DAT", _donor(), script)
    assert report["differs_from_donor"] == {"count": 1, "ranges": [[100, 100]]}


# -- the screens a run keeps (#743): the fight ended at a bar nobody could see --


class _UnknownBarScreen:
    def glyphs(self, rect=None) -> str:
        return "01364f4c1cd47efa"


class _NoHits:
    def drain(self):
        return []


class _PngSession:
    """Writes a file for every `shot`, the way the pool's session does."""

    def __init__(self, root):
        self.root = root
        self.root.mkdir(exist_ok=True)

    def shot(self, name, allow_blank=False):
        path = self.root / f"{name}.png"
        path.write_bytes(b"\x89PNG " + name.encode())
        return path

    def capture(self):
        return _UnknownBarScreen()

    def key(self, *keys, gap=0.0):
        pass


def test_a_bar_the_fight_does_not_know_is_kept_in_the_run_folder(tmp_path):
    por = _FakePoR([None])
    por.s = _PngSession(tmp_path / "pool")
    por.world_glyphs = "the-world"
    evidence = dosfightwatch.Evidence(tmp_path / "out")
    result = dosfightwatch.fight_watching(
        por, _NoHits(), patience=0.0, evidence=evidence)
    assert result["why"] == "unknown bar 01364f4c1cd47efa"
    assert "unknown_bar_01364f4c1cd47efa.png" in evidence.files
    for name in evidence.files:
        assert (tmp_path / "out" / name).read_bytes().startswith(b"\x89PNG")


def test_the_walk_keeps_a_bar_it_gives_up_on(tmp_path):
    por = _FakePoR([None])
    por.s = _PngSession(tmp_path / "pool")
    evidence = dosfightwatch.Evidence(tmp_path / "out")
    result = dosfightwatch.walk_to_encounter(
        por, steps=5, patience=0.0, evidence=evidence)
    assert result["met"] is False
    assert (tmp_path / "out" / "walk_unknown_bar_01364f4c1cd47efa.png").exists()


def test_each_encounter_is_kept_and_named(tmp_path):
    ovr = _ovr()
    dbg = _Debugger(ovr, _script(1000, 532), counts=(13, 7))
    dbg.shot = _PngSession(tmp_path / "pool").shot
    evidence = dosfightwatch.Evidence(tmp_path / "out")
    dosfightwatch.measure_split(
        _por(dbg), ovr, steps=5, fight_kw={"settled": 0.0},
        walk=lambda por, steps: {"met": True}, evidence=evidence)
    assert evidence.files == ["encounter1.png", "encounter2.png"]
    assert (tmp_path / "out" / "encounter2.png").exists()


def test_pile_keeps_the_loaded_screen_and_the_report_names_the_shots(
        tmp_path, monkeypatch):
    folder, save = _stage(tmp_path)

    class Claimed:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class Session(_PngSession):
        def __init__(self, claimed, game):
            super().__init__(tmp_path / "pool")
            self.save_dir = save

        def stage(self, fresh):
            pass

        def boot(self, fresh):
            pass

        def close(self):
            pass

    class Por:
        def __init__(self, s):
            self.s = s

        def to_main_menu(self):
            pass

        def load_game(self, letter):
            pass

        def status(self):
            return "status"

    def measure(por, ovr, *, steps, ds, evidence, walk, share):
        evidence.take(por.s, "encounter1")
        return {"walk": {"met": True}}

    monkeypatch.setattr(dosbox, "find_game", lambda *a: tmp_path)
    monkeypatch.setattr(dosboxx, "claim", lambda *a: Claimed())
    monkeypatch.setattr(dosboxx, "XSession", Session)
    monkeypatch.setattr(dosbox, "PoolOfRadiance", Por)
    monkeypatch.setattr(dosfightwatch, "find_ovr", lambda game: b"")
    monkeypatch.setattr(dosfightwatch, "measure_split", measure)
    out = tmp_path / "out"
    report = dosfightwatch.pile(folder=folder, source=None, at=None, steps=1,
                                out=out, ds=None)
    assert report["screenshots"] == ["loaded.png", "encounter1.png"]
    assert (out / "loaded.png").exists()
    assert "loaded.png" in (out / "report.json").read_text()


def test_a_shot_that_fails_does_not_stop_the_fight_and_is_reported(tmp_path):
    import subprocess

    class Failing(_PngSession):
        def shot(self, name, allow_blank=False):
            raise subprocess.CalledProcessError(1, "import")

    por = _FakePoR([None])
    por.s = Failing(tmp_path / "pool")
    por.world_glyphs = "the-world"
    evidence = dosfightwatch.Evidence(tmp_path / "out")
    result = dosfightwatch.fight_watching(
        por, _NoHits(), patience=0.0, evidence=evidence)
    assert result["why"] == "unknown bar 01364f4c1cd47efa"
    assert evidence.files == []
    assert len(evidence.errors) == 2


def test_a_blank_frame_is_not_kept_as_an_unknown_bar(tmp_path):
    por = _FakePoR(["blank"])
    por.s = _PngSession(tmp_path / "pool")
    por.world_glyphs = "the-world"
    evidence = dosfightwatch.Evidence(tmp_path / "out")
    dosfightwatch.fight_watching(por, _NoHits(), patience=0.0, evidence=evidence)
    assert not any(f.startswith("unknown_bar_") for f in evidence.files)


def test_a_known_bar_with_no_key_is_not_kept_as_an_unknown_bar(tmp_path):
    por = _FakePoR(["move_attack"])
    por.s = _PngSession(tmp_path / "pool")
    por.world_glyphs = "the-world"
    evidence = dosfightwatch.Evidence(tmp_path / "out")
    result = dosfightwatch.fight_watching(
        por, _NoHits(), patience=0.0, evidence=evidence)
    assert not any(f.startswith("unknown_bar_") for f in evidence.files)
    assert result["why"].startswith("unknown bar")   # bounded, not endless


# -- a torn frame is skipped, not fatal (#743) --


class _TornThenWorld:
    """Raises `NotLineDoubled` on the first `torn` captures, then shows the world bar."""

    def __init__(self, torn):
        self.torn = torn
        self.calls = 0
        self.shots: list[str] = []

    def capture(self):
        self.calls += 1
        if self.calls <= self.torn:
            raise dosboxx.NotLineDoubled("block at (0,314) is not one pixel")
        return _WorldScreen()

    def key(self, *keys, gap=0.0):
        pass

    def shot(self, name, allow_blank=False):
        self.shots.append(name)
        return None


class _WorldScreen:
    def glyphs(self, rect=None) -> str:
        return "the-world"


def test_a_torn_frame_mid_fight_does_not_end_the_fight():
    por = _FakePoR([None])
    por.s = _TornThenWorld(3)
    por.world_glyphs = "the-world"
    result = dosfightwatch.fight_watching(por, _NoHits(), settled=0.0)
    assert result["result"] is True
    assert por.s.calls == 4


def test_a_torn_frame_at_a_hit_is_recorded_with_an_unknown_bar():
    class OneHit:
        def __init__(self):
            self.rows = []
            self.hits = []

        def drain(self):
            fresh, self.rows = self.rows, []
            return fresh

        def note(self, hit, **kw):
            self.hits.append(kw)
            return dict(kw)

    class Session(_TornThenWorld):
        def regs(self, *names):
            return {}

        def run(self):
            pass

    w = OneHit()
    w.rows = [object()]
    por = _FakePoR([None])
    por.s = Session(1)
    por.world_glyphs = "the-world"
    result = dosfightwatch.fight_watching(por, w, settled=0.0)
    assert result["result"] is True
    assert w.hits[0]["bar"] == "?"


def test_a_torn_frame_while_waiting_for_the_bar_is_retried():
    por = _FakePoR(["encounter"])
    por.s = _TornThenWorld(2)
    kind, resolved = dosfightwatch._await_bar(por, patience=5.0)
    assert (kind, resolved) == ("encounter", True)
    assert por.s.calls == 3


def test_a_torn_hit_frame_keeps_the_previous_bar_and_asks_for_one_try():
    tries = []

    class Session(_TornThenWorld):
        def __init__(self):
            super().__init__(0)
            self.mode = ["ok", "torn", "world"]

        def capture(self):
            tries.append(self.CAPTURE_TRIES if "CAPTURE_TRIES" in self.__dict__ else None)
            m = self.mode.pop(0)
            if m == "torn":
                raise dosboxx.NotLineDoubled("torn")
            return _WorldScreen() if m == "world" else _Screen()

        def regs(self, *names):
            return {}

        def run(self):
            pass

    class Hits:
        def __init__(self):
            self.queue = [[object()], [object()], []]
            self.seen = []
            self.hits = []

        def drain(self):
            return self.queue.pop(0) if self.queue else []

        def note(self, hit, **kw):
            self.seen.append(kw["bar"])
            return dict(kw)

    por = _FakePoR(["command"])
    por.s = Session()
    por.world_glyphs = "the-world"
    w = Hits()
    result = dosfightwatch.fight_watching(por, w, settled=0.0)
    assert w.seen == ["command", "command"]
    assert result["last_bar"] == "command"
    assert tries[:2] == [1, 1]
    assert "CAPTURE_TRIES" not in por.s.__dict__


def test_a_screen_that_stays_torn_gives_up_as_unreadable(tmp_path):
    por = _FakePoR([None])
    por.s = _TornThenWorld(10 ** 9)
    por.world_glyphs = "the-world"
    result = dosfightwatch.fight_watching(por, _NoHits(), patience=0.0)
    assert result["result"] is False
    assert result["why"] == "unreadable screen"


def test_a_walk_on_a_screen_that_stays_torn_reports_it_and_takes_the_shot():
    por = _FakePoR([None])
    por.s = _TornThenWorld(10 ** 9)
    result = dosfightwatch.walk_to_encounter(por, steps=5, patience=0.0)
    assert result["met"] is False
    assert result["why"] == "unreadable screen"
    assert por.s.shots == ["walk_unreadable_screen"]


# -- PrayerWatch, on a debugger that is a dictionary of bytes -----------------

P = dosfightwatch.PRAYER_LAYOUTS["pool"]
DS = 0x149E
STUB = 0x0863
LOAD = 0x2C33
ASTUB = STUB - P.prayer_unit + P.attack_unit
ATT_L = 0x33AE
ATT_L2 = 0x34C0
SS = 0x5000
PARTY_SEG = 0x4000
OVR_SIZE = 0x40000
CODE = {name: bytes((0x10 * (i + 1) + j) & 0xFF for j in range(8))
        for i, name in enumerate(P.routines)}
DESCRIPTOR = bytes(range(0xA0, 0xAC))
CD3F = bytes.fromhex("cd3fb21200")


def _le(value: int) -> bytes:
    return value.to_bytes(2, "little")


class FakeDebugger:
    """A halted emulator: memory by linear address, and a script of halts.

    `pending` holds one callable per halt, each setting the registers and any
    memory the game would have changed; `halted()` applies the next while the
    emulator is running, as a breakpoint firing would.
    """

    def __init__(self):
        self.mem: dict[int, int] = {}
        self.pending: list = []
        self.registers: dict[str, int] = {"DS": DS}
        self.is_halted = True
        self.armed: list[tuple[int, int]] = []
        self.cleared = 0
        self.runs = 0

    def put(self, seg: int, off: int, data: bytes) -> None:
        for i, b in enumerate(data):
            self.mem[(seg << 4) + off + i] = b

    def read(self, addr, n) -> bytes:
        seg, off = addr
        return bytes(self.mem.get((seg << 4) + off + i, 0) for i in range(n))

    def regs(self, *names) -> dict[str, int]:
        return {n: self.registers.get(n, 0) for n in names}

    def brk(self, addr) -> None:
        self.armed.append(addr)

    def clear_breakpoints(self) -> None:
        self.armed.clear()
        self.cleared += 1

    def breakpoints(self) -> str:
        return " ".join(f"{s:04X}:{o:04X}" for s, o in self.armed)

    def run(self) -> None:
        self.is_halted = False
        self.runs += 1

    def halted(self, timeout: float = 3.0) -> bool:
        if not self.is_halted and self.pending:
            self.pending.pop(0)()
            self.is_halted = True
        return self.is_halted

    def attach(self, tries: int = 6, gap: float = 1.0) -> bool:
        self.is_halted = True
        return True


def _world(dbg: FakeDebugger, *, side_of_attacker: int = 0,
           party: tuple[str, ...] = ("MALCYON", "ROXY"), node_id: int = 49,
           minutes: int = 8) -> None:
    """Prayer's table and stubs, a party carrying `node_id`, and the frames
    of a party attack under the dispatcher."""
    dbg.put(DS, P.handler_table + 49 * 4, _le(0xED) + _le(STUB))
    dbg.put(DS, P.handler_table + 35 * 4, _le(0xB6) + _le(STUB))
    dbg.put(STUB, 0, DESCRIPTOR)
    dbg.put(STUB, 0xED, CD3F)
    dbg.put(STUB, 0xB6, CD3F)
    dbg.put(ASTUB, P.stub_attack, CD3F)
    # The party list: records at PARTY_SEG:0x1000 * i, each with one node.
    dbg.put(DS, P.party_list, _le(0) + _le(PARTY_SEG))
    for i, name in enumerate(party):
        rec = 0x1000 * i
        dbg.put(PARTY_SEG, rec, bytes((len(name),)) + name.encode())
        dbg.put(PARTY_SEG, rec + P.side, b"\x00")
        if i + 1 < len(party):
            dbg.put(PARTY_SEG, rec + P.next_record,
                    _le(0x1000 * (i + 1)) + _le(PARTY_SEG))
        node = 0x800 + rec
        dbg.put(PARTY_SEG, rec + P.node_list, _le(node) + _le(PARTY_SEG))
        dbg.put(PARTY_SEG, node, bytes((node_id,)) + _le(minutes) + b"\x03\x00")
    # The attacker's record, on `side_of_attacker`.
    dbg.put(PARTY_SEG, 0, bytes((7,)) + b"MALCYON")
    dbg.put(PARTY_SEG, P.side, bytes((side_of_attacker,)))
    # Four frames: dispatcher (id at +10h), query, walker (list at +0Ah,
    # returning to the attack roll's list-10 call) and the attack roll.
    rets = [(0x1111, 0x2222), (0x1111, 0x3333), (0x33AE, 0x0CF8), (0x1111, 0x4444)]
    for k, (seg, off) in enumerate(rets):
        frame = bytearray(0x14)
        frame[0:2] = _le(0x200 + 0x40 * (k + 1))
        frame[2:4] = _le(off)
        frame[4:6] = _le(seg)
        if k == 0:
            frame[0x10] = 49
        if k == 2:
            frame[0x0A] = dosfightwatch.ATTACK_LIST
        if k == 3:
            frame[0x0C:0x0E] = _le(0)
            frame[0x0E:0x10] = _le(PARTY_SEG)
        dbg.put(SS, 0x200 + 0x40 * k, bytes(frame))
    # The stack at an entry: node far pointer at SP+6, combatant at SP+0Ah.
    stack = bytearray(16)
    stack[6:8], stack[8:10] = _le(0x800), _le(PARTY_SEG)
    stack[10:12], stack[12:14] = _le(0), _le(PARTY_SEG)
    dbg.put(SS, 0x100, bytes(stack))
    dbg.put(PARTY_SEG, 0x800, bytes((node_id,)) + _le(minutes) + b"\x03\x00")


def _at(dbg, cs, ip, who=PARTY_SEG, **more):
    """A halt at `cs:ip` for the combatant whose record is at `who:0`."""
    def go():
        stack = bytearray(dbg.read((SS, 0x100), 16))
        stack[10:12], stack[12:14] = _le(0), _le(who)
        dbg.put(SS, 0x100, bytes(stack))
        dbg.registers.update({"CS": cs, "IP": ip, "SS": SS, "SP": 0x100,
                              "BP": 0x200, "ES": who, "DI": 0, "AX": 0,
                              "ZF": 1, **more})
    return go


def _overlay(dbg, ovr: bytearray) -> None:
    for name, at in P.routines.items():
        ovr[at:at + 8] = CODE[name]
        dbg.put(LOAD, at - P.prayer_unit_file, CODE[name])
    for name, off in P.attack_points.items():
        at = P.attack_unit_file + off
        code = bytes((0x70 + 0x10 * off + j) & 0xFF for j in range(8))
        ovr[at:at + 8] = code
        for seg in (ATT_L, ATT_L2):
            dbg.put(seg, off, code)


def _watch(dbg, notes):
    image = bytearray(0x1000)
    at = P.prayer_unit * 16
    image[at:at + 12] = DESCRIPTOR
    ovr = bytearray(OVR_SIZE)
    return dosfightwatch.PrayerWatch(dbg, bytes(ovr), bytes(image),
                                     note=lambda **kw: notes.append(kw),
                                     title="pool"), ovr


def _ready(*, side_of_attacker: int = 0, node_id: int = 49):
    """A watch that has attached, read the party and armed the stubs, with
    the overlay's code in memory and the handlers' frame inside the handler."""
    dbg, notes = FakeDebugger(), []
    _world(dbg, side_of_attacker=side_of_attacker, node_id=node_id)
    watch, _ = _watch(dbg, notes)
    watch.ovr = bytearray(OVR_SIZE)
    _overlay(dbg, watch.ovr)
    watch.attach()
    at_menu = watch.party()
    watch.arm()
    inner = bytearray(0x10)
    inner[8:10], inner[10:12] = _le(0x800), _le(PARTY_SEG)
    inner[12:14], inner[14:16] = _le(0), _le(PARTY_SEG)
    dbg.put(SS, 0x200 + 0x40 * 3, bytes(inner))
    return dbg, watch, notes, at_menu


def _load(dbg):
    dbg.put(STUB, 0xED, bytes.fromhex("ea") + _le(0x12B2) + _le(LOAD))


def _unload(dbg):
    dbg.put(STUB, 0xED, CD3F)


def _both(dbg, first, second):
    def go():
        first()
        second()
    return go


def _attack_load(dbg, seg):
    dbg.put(ASTUB, P.stub_attack, b"\xea" + _le(0x0CB7) + _le(seg))


def _aroll(dbg, who=PARTY_SEG, load=ATT_L, roll=12):
    """The attack roll's stub halt, with the attack unit loaded at `load`."""
    def go():
        _attack_load(dbg, load)
        dbg.put(SS, 0x100 + 4, bytes((roll,)))
        _at(dbg, ASTUB, P.stub_attack, who)()
    return go


def _pt(dbg, off, who=PARTY_SEG, seg=ATT_L):
    """A halt at the roll's list-10 call (0CF5) or its return (0CF8); the
    attacker is at BP+0Ch and the defender at BP+8."""
    base = _at(dbg, seg, off, who, BP=0x2C0)

    def go():
        dbg.put(SS, 0x2C0 + 8, _le(0) + _le(0x4900) + _le(0) + _le(who))
        base()
    return go


def _pair(dbg, *inside, who=PARTY_SEG):
    """A party attack's halts: the roll's stub, the list-10 call, `inside`, the return."""
    return [_aroll(dbg, who), _pt(dbg, 0x0CF5, who), *inside, _pt(dbg, 0x0CF8, who)]


def _one_attack(dbg, who=PARTY_SEG):
    return _pair(dbg, _at(dbg, STUB, 0xED, who), _at(dbg, LOAD, 0x12B2, who),
                 _at(dbg, LOAD, 0x12D5, who), _at(dbg, LOAD, 0x0C06, who), who=who)


def _first_call_then(dbg, second_call):
    """The first call, which loads the overlay under the stub, then `second_call`."""
    return [*_pair(dbg, _at(dbg, STUB, 0xED),
                   _both(dbg, lambda: _load(dbg), _at(dbg, STUB, 0xED)),
                   _at(dbg, LOAD, 0x12B2), _at(dbg, LOAD, 0x12D5),
                   _at(dbg, LOAD, 0x0C06)), *second_call]


def test_the_overlay_segment_is_read_from_the_stub_and_the_four_routines_armed():
    dbg, watch, notes, at_menu = _ready()
    assert watch.stub == STUB and watch.stub_load() is None
    assert [m["name"] for m in at_menu] == ["MALCYON", "ROXY"]
    assert watch.holders(at_menu, 49) == ["MALCYON", "ROXY"]
    assert dbg.armed == [(STUB, 0xED), (STUB, 0xB6), (ASTUB, 0x3E)]
    dbg.pending = _first_call_then(dbg, _one_attack(dbg))

    stop = watch.run_fight(600, idle=lambda: False)

    assert stop == "one attack round"
    kinds = [h["kind"] for h in watch.halts]
    call, ret = "attack_call", "attack_return"
    assert kinds == ["attack_stub", call, "stub49", "stub49", "handler", "bonus",
                     "helper", ret, "attack_stub", call, "stub49", "handler",
                     "bonus", "helper"]
    watch.halts = [h for h in watch.halts if h["kind"] not in
                   ("attack_stub", call, ret)]
    assert [h["kind"] for h in watch.halts] == [
        "stub49", "stub49", "handler", "bonus", "helper",
        "stub49", "handler", "bonus", "helper"]
    want = {(LOAD, P.routines[n] - P.prayer_unit_file)
            for n in P.routines}
    assert want <= set(dbg.armed) and (STUB, 0xED) in dbg.armed
    first, second, counted = watch.halts[0], watch.halts[1], watch.halts[5]
    assert first["id"] == 49 and first["list"] == 10 and first["party_attack"]
    assert first["load_now"] is None and second["load_now"] == f"{LOAD:04X}"
    assert first["routines_armed"] is False and counted["routines_armed"] is True
    assert counted["attacker_nodes"][0]["id"] == 49
    assert first["attacker"]["name"] == "MALCYON" and first["attacker"]["side"] == 0
    assert first["node"]["bytes"] == "3108000300"
    assert first["combatant"]["name"] == "MALCYON"
    assert len(first["chain"]) == 4 and len(first["stack"]) == 32
    assert set(first["ds_6816_6822"]) == {"6816", "6822"}
    bonus = watch.halts[3]
    assert bonus["zf"] == 1 and bonus["es_di_combatant"]["name"] == "MALCYON"
    assert all(h["code_matches"] for h in watch.halts if "code_matches" in h)
    logged = [n for n in notes if n["event"] == "prayer-halt"]
    assert len(logged) == 14 and logged[4]["cs_ip"] == f"{LOAD:04X}:12B2"
    assert watch.summary(49, at_menu, at_menu)["conclusive"] is True


def test_the_first_call_alone_does_not_complete_a_round():
    dbg, watch, _, at_menu = _ready()
    dbg.pending = _first_call_then(dbg, [])
    assert watch.run_fight(600, idle=lambda: True) == "fight over"
    result = watch.summary(49, at_menu, at_menu)
    assert result["round_completed"] is False and result["conclusive"] is False
    assert "later attack" in result["why"][0]


def test_a_run_with_no_halts_is_not_conclusive():
    dbg, watch, _, at_menu = _ready()
    assert watch.run_fight(600, idle=lambda: True) == "fight over"
    result = watch.summary(49, at_menu, at_menu)
    assert watch.halts == [] and result["conclusive"] is False
    assert result["halts"] == 0


def test_a_monsters_attack_is_not_a_party_attack_and_the_run_is_not_conclusive():
    dbg, watch, _, at_menu = _ready(side_of_attacker=1)
    dbg.pending = [_at(dbg, STUB, 0xED)]
    assert watch.run_fight(600, idle=lambda: True) == "fight over"
    assert watch.halts[0]["attacker"]["side"] == 1
    assert "party_attack" not in watch.halts[0] and watch.party_attack is False
    result = watch.summary(49, at_menu, at_menu)
    assert result["conclusive"] is False and result["round_completed"] is False


def test_a_monsters_helper_halt_does_not_end_the_party_attack_round():
    dbg, watch, _, at_menu = _ready()
    _load(dbg)
    watch.load = LOAD
    watch.arm()
    dbg.put(0x4900, 0, bytes((3,)) + b"ORC")
    dbg.put(0x4900, P.side, b"\x01")
    dbg.pending = [_aroll(dbg), _pt(dbg, 0x0CF5), _at(dbg, STUB, 0xED),
                   _at(dbg, LOAD, 0x0C06, 0x4900), _at(dbg, LOAD, 0x0C06)]
    seen = []

    def idle():
        seen.append(len(watch.halts))
        return True
    # The second helper halt is the attacker's own, and the only one that ends it.
    assert watch.run_fight(600, idle=idle) == "one attack round"
    assert [h["combatant"]["name"] for h in watch.halts[3:]] == ["ORC", "MALCYON"]
    assert watch.summary(49, at_menu, at_menu)["conclusive"] is True


def test_another_stub_halt_drops_the_round_before_its_helper_runs():
    dbg, watch, _, _ = _ready()
    _load(dbg)
    watch.load = LOAD
    watch.arm()
    dbg.put(0x4900, 0, bytes((3,)) + b"ORC")
    dbg.put(0x4900, P.side, b"\x01")

    def monster_asks():
        # The attack roll's frame now names the ORC as the attacker.
        dbg.put(SS, 0x200 + 0x40 * 3 + 0xE, _le(0x4900))
        _at(dbg, STUB, 0xB6)()
    dbg.pending = [_aroll(dbg), _pt(dbg, 0x0CF5), _at(dbg, STUB, 0xED),
                   monster_asks, _at(dbg, LOAD, 0x0C06)]
    assert watch.run_fight(600, idle=lambda: True) == "fight over"
    assert watch.completed is None


def test_a_stub_that_reads_int_3f_again_takes_the_routine_breakpoints_off():
    dbg, watch, _, _ = _ready()
    _load(dbg)
    watch.load = LOAD
    watch.arm()
    assert len(dbg.armed) == 7 and watch.armed_at == LOAD
    _unload(dbg)
    dbg.pending = [_at(dbg, STUB, 0xED)]
    watch.run_fight(600, idle=lambda: True)
    assert dbg.armed == [(STUB, 0xED), (STUB, 0xB6), (ASTUB, 0x3E)]
    assert watch.load is None and watch.armed_at is None
    assert watch.halts[0]["load_now"] is None


def test_a_halt_whose_code_does_not_match_is_not_a_hit_and_spoils_the_run():
    dbg, watch, _, at_menu = _ready()
    _load(dbg)
    watch.load = LOAD
    watch.arm()
    dbg.put(LOAD, 0x0C06, b"\xff" * 8)          # what is there now is not the helper
    dbg.pending = [_aroll(dbg), _pt(dbg, 0x0CF5), _at(dbg, STUB, 0xED),
                   _at(dbg, LOAD, 0x0C06)]
    assert watch.run_fight(600, idle=lambda: True) == "fight over"
    bad = watch.halts[3]
    assert bad["kind"] == "other" and bad["code_matches"] is False
    assert watch.completed is None and "helper" in watch.mismatched
    result = watch.summary(49, at_menu, at_menu)
    assert result["conclusive"] is False
    assert any("did not match" in w for w in result["why"])


def test_a_node_that_expired_before_the_fight_makes_the_run_inconclusive():
    dbg, watch, _, at_menu = _ready()
    gone = [{**m, "nodes": []} for m in at_menu]
    result = watch.summary(49, gone, gone)
    assert result["conclusive"] is False
    assert "id 49" in result["why"][0]
    # The id under test must be the one the party carries.
    assert watch.summary(35, at_menu, at_menu)["conclusive"] is False
    # Present at the menu and gone at the stop is just as unfinished.
    assert watch.summary(49, at_menu, gone)["conclusive"] is False


def test_a_party_that_was_not_read_at_the_stop_is_not_conclusive():
    dbg, watch, _, at_menu = _ready()
    dbg.pending = _first_call_then(dbg, _one_attack(dbg))
    watch.run_fight(600, idle=lambda: False)
    assert watch.summary(49, at_menu, at_menu)["conclusive"] is True
    result = watch.summary(49, at_menu, None)
    assert result["conclusive"] is False and "not read at the stop" in result["why"][0]


def test_an_attacker_without_the_tested_node_at_its_stub_halt_is_not_conclusive():
    dbg, watch, _, at_menu = _ready()
    dbg.pending = _first_call_then(dbg, [_aroll(dbg), _pt(dbg, 0x0CF5),
                                         _at(dbg, STUB, 0xED)])
    # The attacker's node list is emptied between the menu and its attack.
    dbg.put(PARTY_SEG, P.node_list, _le(0) + _le(0))
    dbg.pending += [_at(dbg, LOAD, 0x0C06)]
    watch.run_fight(600, idle=lambda: False)
    result = watch.summary(49, at_menu, at_menu)
    assert result["round_completed"] is True and result["conclusive"] is False
    assert "not on the attacker" in result["why"][0]


def test_the_breakpoints_come_off_and_the_game_runs_when_a_halt_cannot_be_read():
    dbg, watch, notes, _ = _ready()
    dbg.pending = [_at(dbg, STUB, 0xED)]
    runs = dbg.runs

    def broken():
        raise RuntimeError("EV answered nothing")
    watch.handle = broken
    with pytest.raises(RuntimeError):
        try:
            watch.run_fight(600, idle=lambda: False)
        finally:
            got = watch.finish()
    assert dbg.armed == [] and dbg.runs > runs and not dbg.is_halted
    assert isinstance(got, list)


def test_finish_attempts_each_release_step_on_its_own():
    dbg, watch, notes, _ = _ready()

    def block():
        raise dosfightwatch.dosboxx.NotHalted("running")
    dbg.clear_breakpoints = block
    runs = dbg.runs
    assert watch.finish() is not None
    assert dbg.runs == runs + 1
    assert [n["step"] for n in notes if n["event"] == "prayer-finish-error"] == ["clear"]


def test_a_table_that_is_not_prayers_is_blocked(monkeypatch):
    monkeypatch.setattr(dosfightwatch.time, "sleep", lambda s: None)
    dbg = FakeDebugger()
    _world(dbg)
    dbg.put(DS, P.handler_table + 49 * 4, _le(0x00ED) + _le(0x0999))
    watch, _ = _watch(dbg, [])
    with pytest.raises(dosfightwatch.PrayerWatchError, match="handler table"):
        watch.attach(tries=2)


def test_a_stub_that_is_neither_int_3f_nor_a_far_jump_is_blocked():
    dbg = FakeDebugger()
    _world(dbg)
    dbg.put(STUB, 0xED, bytes.fromhex("9090909090"))
    watch, _ = _watch(dbg, [])
    watch.attach()
    with pytest.raises(dosfightwatch.PrayerWatchError, match="neither INT 3Fh"):
        watch.stub_load()


def test_code_that_does_not_match_game_ovr_at_the_resolved_segment_is_not_armed():
    dbg = FakeDebugger()
    _world(dbg)
    watch, _ = _watch(dbg, [])
    watch.attach()
    watch.load = LOAD                       # nothing there matches the zeroed GAME.OVR
    dbg.put(LOAD, 0x12B2, b"\xff" * 8)
    armed = watch.arm()
    assert "handler" in armed["mismatched"]
    assert (LOAD, 0x12B2) not in dbg.armed
    assert watch.summary(49, watch.party(), None)["conclusive"] is False


def test_a_mismatch_from_a_superseded_arm_does_not_spoil_the_run_once_a_rearm_matches():
    dbg, watch, _, at_menu = _ready()
    _load(dbg)
    watch.load = LOAD
    dbg.put(LOAD, 0x12B2, b"\xff" * 8)
    assert "handler" in watch.arm()["mismatched"]
    _overlay(dbg, watch.ovr)                # the overlay is now loaded intact
    assert watch.arm()["mismatched"] == [] and watch.mismatched == []
    assert (LOAD, 0x12B2) in dbg.armed
    dbg.pending = [_aroll(dbg), _pt(dbg, 0x0CF5), _at(dbg, STUB, 0xED)]
    watch.run_fight(600, idle=lambda: True)
    assert all(h.get("code_matches", True) for h in watch.halts)
    assert not any("did not match" in w
                   for w in watch.summary(49, at_menu, at_menu)["why"])


def test_a_halt_time_mismatch_survives_a_clean_rearm_at_a_later_stub_halt():
    dbg, watch, _, at_menu = _ready()
    _load(dbg)
    watch.load = LOAD
    watch.arm()
    dbg.put(LOAD, 0x0C06, b"\xff" * 8)          # not the helper
    dbg.pending = [_aroll(dbg), _pt(dbg, 0x0CF5), _at(dbg, STUB, 0xED),
                   _at(dbg, LOAD, 0x0C06),
                   _both(dbg, lambda: _unload(dbg), _at(dbg, STUB, 0xED))]
    watch.run_fight(600, idle=lambda: True)
    assert watch.halts[3]["code_matches"] is False
    assert watch.arm_mismatched == [] and "helper" in watch.halt_mismatched
    result = watch.summary(49, at_menu, at_menu)
    assert result["conclusive"] is False
    assert any("did not match" in w for w in result["why"])


def test_a_mismatch_on_the_arm_in_force_still_spoils_the_run():
    dbg, watch, _, at_menu = _ready()
    _load(dbg)
    watch.load = LOAD
    _overlay(dbg, watch.ovr)
    assert watch.arm()["mismatched"] == []
    dbg.put(LOAD, 0x12B2, b"\xff" * 8)
    assert "handler" in watch.arm()["mismatched"]
    assert any("did not match" in w
               for w in watch.summary(49, at_menu, at_menu)["why"])


# -- the attack roll's own stub, and the pair it brackets ------------------------

def _attack_armed(dbg, seg):
    return {(seg, 0x0CF5), (seg, 0x0CF8)} <= set(dbg.armed)


def test_the_attack_stub_is_armed_and_the_unit_segment_is_read_at_its_halt():
    dbg, watch, _, _ = _ready()
    assert (ASTUB, 0x3E) in dbg.armed and ASTUB == 0x08D2
    assert not any(cs == ATT_L for cs, _ in dbg.armed)
    dbg.pending = [_aroll(dbg)]
    watch.run_fight(600, idle=lambda: True)
    h = watch.halts[0]
    assert h["kind"] == "attack_stub" and h["attack_load_now"] == f"{ATT_L:04X}"
    assert h["attacker"]["name"] == "MALCYON" and h["roll"] == 12 and "defender" in h
    assert watch.attack_armed_at == ATT_L and _attack_armed(dbg, ATT_L)
    assert (ASTUB, 0x3E) in dbg.armed and watch.mismatched == []


def test_the_attack_unit_moving_between_halts_rearms_the_points():
    dbg, watch, _, _ = _ready()
    dbg.pending = [_aroll(dbg), _aroll(dbg, load=ATT_L2)]
    watch.run_fight(600, idle=lambda: True)
    assert watch.attack_armed_at == ATT_L2
    assert _attack_armed(dbg, ATT_L2) and not any(cs == ATT_L for cs, _ in dbg.armed)
    assert watch.halts[1]["rearmed"]["armed"][-2:] == [
        f"{ATT_L2:04X}:0CF5 attack_call", f"{ATT_L2:04X}:0CF8 attack_return"]


def test_attack_code_that_does_not_match_game_ovr_is_not_armed_and_spoils_the_run():
    dbg, watch, _, at_menu = _ready()
    dbg.put(ATT_L, 0x0CF5, b"\xff" * 3)
    dbg.pending = [_aroll(dbg)]
    watch.run_fight(600, idle=lambda: True)
    assert (ATT_L, 0x0CF5) not in dbg.armed and (ATT_L, 0x0CF8) in dbg.armed
    assert watch.mismatched == ["attack_call"]
    assert watch.summary(49, at_menu, at_menu)["conclusive"] is False


def test_an_id_35_run_with_three_pairs_and_no_prayer_stub_halt_is_conclusive():
    dbg, watch, _, at_menu = _ready(node_id=35)
    watch.node_id = 35
    for _ in range(4):
        dbg.pending += _pair(dbg)
    stop = watch.run_fight(600, idle=lambda: True)
    assert stop == "quiet pairs" and len(dbg.pending) == 3
    assert [h["kind"] for h in watch.halts].count("attack_call") == 3
    result = watch.summary(35, at_menu, at_menu)
    assert result["conclusive"] is True and result["why"] == []
    assert result["pairs"] == 3 and result["quiet_pairs"] == 3
    assert result["round_completed"] is False and result["party_attack"] is True
    assert result["attack_load_segment"] == f"{ATT_L:04X}"


def test_quiet_pairs_do_not_stop_or_complete_an_id_49_run():
    dbg, watch, _, at_menu = _ready()
    watch.node_id = 49
    for _ in range(3):
        dbg.pending += _pair(dbg)
    assert watch.run_fight(600, idle=lambda: True) == "fight over"
    result = watch.summary(49, at_menu, at_menu)
    assert result["pairs"] == 3 and result["conclusive"] is False


def test_a_pair_with_a_prayer_stub_halt_inside_it_is_not_quiet():
    dbg, watch, _, at_menu = _ready(node_id=35)
    watch.node_id = 35
    dbg.pending = _pair(dbg, _at(dbg, STUB, 0xB6))
    watch.run_fight(600, idle=lambda: True)
    assert watch.pairs[0]["prayer_stubs"] == 1 and watch.quiet_pairs == []
    assert watch.summary(35, at_menu, at_menu)["conclusive"] is False


def test_a_roll_of_1_reaches_the_stub_and_is_not_a_pair():
    dbg, watch, _, at_menu = _ready(node_id=35)
    watch.node_id = 35
    dbg.pending = [_aroll(dbg, roll=1)]
    watch.run_fight(600, idle=lambda: True)
    assert watch.halts[0]["roll"] == 1
    assert watch.pairs == [] and watch.party_attack is False and watch.pair is None
    assert watch.summary(35, at_menu, at_menu)["conclusive"] is False


def test_a_pair_cut_off_by_a_roll_of_1_is_not_counted_when_the_return_comes():
    dbg, watch, _, _ = _ready(node_id=35)
    dbg.pending = [_aroll(dbg), _pt(dbg, 0x0CF5), _aroll(dbg, roll=1),
                   _pt(dbg, 0x0CF8)]
    watch.run_fight(600, idle=lambda: True)
    assert watch.pairs == [] and watch.quiet_pairs == []


def test_a_monsters_list_10_call_opens_no_pair():
    dbg, watch, _, _ = _ready(node_id=35)
    dbg.put(0x4900, 0, bytes((3,)) + b"ORC")
    dbg.put(0x4900, P.side, b"\x01")
    dbg.pending = _pair(dbg, who=0x4900)
    watch.run_fight(600, idle=lambda: True)
    assert watch.pairs == [] and watch.party_attack is False


def test_id_49_needs_its_helper_inside_the_pair_not_after_it():
    dbg, watch, _, at_menu = _ready()
    _load(dbg)
    watch.load = LOAD
    watch.arm()
    dbg.pending = [*_pair(dbg, _at(dbg, STUB, 0xED)), _at(dbg, LOAD, 0x0C06)]
    assert watch.run_fight(600, idle=lambda: True) == "fight over"
    assert watch.completed is None and len(watch.pairs) == 1
    result = watch.summary(49, at_menu, at_menu)
    assert result["conclusive"] is False and result["round_completed"] is False


def test_an_attack_stub_that_is_neither_int_3f_nor_a_far_jump_is_blocked():
    dbg = FakeDebugger()
    _world(dbg)
    dbg.put(ASTUB, P.stub_attack, bytes.fromhex("9090909090"))
    watch, _ = _watch(dbg, [])
    watch.attach()
    with pytest.raises(dosfightwatch.PrayerWatchError, match="attack stub"):
        watch.arm()


def test_an_attack_unit_descriptor_that_is_not_start_exes_is_blocked():
    dbg = FakeDebugger()
    _world(dbg)
    dbg.put(ASTUB, 0, b"\x01" * 12)
    watch, _ = _watch(dbg, [])
    with pytest.raises(dosfightwatch.PrayerWatchError, match="attack unit"):
        watch.attach(tries=1)


def test_pairs_after_the_party_lost_node_35_are_not_conclusive():
    dbg, watch, _, at_menu = _ready(node_id=35)
    watch.node_id = 35
    for m in range(len(at_menu)):
        dbg.put(PARTY_SEG, 0x1000 * m + P.node_list, _le(0) + _le(0))
    for _ in range(3):
        dbg.pending += _pair(dbg)
    assert watch.run_fight(600, idle=lambda: True) == "quiet pairs"
    result = watch.summary(35, at_menu, at_menu)
    assert len(watch.quiet_pairs) == 3 and result["quiet_pairs"] == 0
    assert result["conclusive"] is False


def test_a_return_for_another_attacker_does_not_close_the_pair():
    dbg, watch, _, _ = _ready(node_id=35)
    dbg.put(0x4900, 0, bytes((3,)) + b"ORC")
    dbg.put(0x4900, P.side, b"\x01")
    dbg.pending = [_aroll(dbg), _pt(dbg, 0x0CF5), _pt(dbg, 0x0CF8, who=0x4900)]
    watch.run_fight(600, idle=lambda: True)
    assert watch.pairs == [] and watch.quiet_pairs == []


def test_one_quiet_pair_is_not_a_conclusive_id_35_run():
    dbg, watch, _, at_menu = _ready(node_id=35)
    watch.node_id = 35
    dbg.pending = _pair(dbg)
    assert watch.run_fight(600, idle=lambda: True) == "fight over"
    result = watch.summary(35, at_menu, at_menu)
    assert result["pairs"] == 1 and result["conclusive"] is False


def test_a_prayer_stub_whose_walker_is_not_list_10_does_not_count_the_round():
    dbg, watch, _, _ = _ready()
    _load(dbg)
    watch.load = LOAD
    watch.arm()
    dbg.put(SS, 0x200 + 0x40 * 2 + 0x0A, b"\x0c")
    dbg.pending = _pair(dbg, _at(dbg, STUB, 0xED), _at(dbg, LOAD, 0x0C06))
    assert watch.run_fight(600, idle=lambda: True) == "fight over"
    assert watch.round is None and watch.completed is None


# -- Curse and Silver Blades: the same watch on each title's own addresses -------

#: The titles `prayer-watch` drives, as `PRAYER_LAYOUTS` keys them, and the
#: names `dosaffectreads` finds their games by.
PRAYER_GAMES = {"pool": "pool", "curse": "curse", "ssb": "silver-blades"}
MONSTER_SEG = 0x4900
#: The attack roll's frame, fourth in the chain from the dispatcher's.
ROLL_BP = 0x200 + 0x40 * 3
#: The handler's own frame at the bonus test and the penalty.
INNER_BP = 0x180


def test_pools_addresses_are_the_ones_measured_in_the_live_fight():
    assert (P.handler_table, P.party_list, P.next_record, P.node_list, P.side) == (
        0x6828, 0x5D96, 0x104, 0x7F, 0x10E)
    assert (P.save_roll, P.attack_roll) == (0x6816, 0x6822)
    assert (P.prayer_unit, P.stub_49, P.stub_35, P.prayer_unit_file) == (
        0x41, 0xED, 0xB6, 0xEC5B)
    assert P.routines == {"handler": 0xFF0D, "bonus": 0xFF30,
                          "penalty": 0xFF48, "helper": 0xF861}
    assert (P.attack_unit, P.stub_attack, P.attack_unit_file) == (0xB0, 0x3E, 0x2AEEA)
    assert P.attack_points == {"attack_call": 0x0CF5, "attack_return": 0x0CF8}
    assert P.indirect is False


def _engine(title):
    from tools.dos import dosaffectreads as reads
    name = PRAYER_GAMES[title]
    try:
        game = dosbox.find_game(reads.TITLES[name])
    except FileNotFoundError:
        pytest.skip(f"needs DOS {reads.TITLES[name]} in the archives")
    return reads, reads.load(game, name)


@pytest.mark.parametrize("title", sorted(PRAYER_GAMES))
def test_each_titles_layout_is_what_its_own_game_holds(title):
    """Every address in the table, found again in the player's `GAME.OVR` and
    `START.EXE` by what the code does rather than where it is."""
    reads, eng = _engine(title)
    from tools.dos import dosovrmap
    lay = dosfightwatch.PRAYER_LAYOUTS[title]
    ovr = eng.ovr
    assert eng.table == lay.handler_table
    where, handler = eng.handlers[49]
    assert (where, handler) == ("GAME.OVR", lay.routines["handler"])
    unit = dosovrmap.unit_of(eng.units, handler)
    assert (unit["seg"], unit["fileoff"]) == (lay.prayer_unit, lay.prayer_unit_file)
    assert (lay.stub_49, handler - unit["fileoff"]) in unit["ents"]
    if lay.stub_35 is not None:
        assert (lay.stub_35, lay.routines["helper"] - unit["fileoff"]) in unit["ents"]
    body = reads.body(ovr, handler)
    text = [f"{i.mnemonic} {i.op_str}" for i in body]
    side = next(i for i in body if i.op_str.endswith(f"es:[di + {lay.side:#x}]"))
    jne = body[body.index(side) + 2]
    assert (jne.mnemonic, jne.address) == ("jne", lay.routines["bonus"])
    assert int(jne.op_str, 0) == lay.routines["penalty"]
    assert f"dec byte ptr [{lay.attack_roll:#x}]" in text
    assert f"dec byte ptr [{lay.save_roll:#x}]" in text
    call = next(i for i in body if i.mnemonic == "call")
    assert int(call.op_str, 0) == lay.routines["helper"]
    assert unit["fileoff"] <= lay.routines["helper"] < unit["fileoff"] + unit["code"]
    helper = [f"{i.mnemonic} {i.op_str}" for i in reads.body(ovr, lay.routines["helper"])]
    assert f"inc byte ptr [{lay.attack_roll:#x}]" in helper
    assert f"inc byte ptr [{lay.save_roll:#x}]" in helper
    # Silver Blades reads the side through the pointer it is handed.
    assert ("les di, ptr es:[di]" in text) == lay.indirect
    # The attack roll: the one list-10 walk, its d20 kept in the attack roll byte.
    walker = reads.apply_walk(eng)["walker"]
    sites = [(site, start) for site, start in reads.routine_callers(eng, walker)
             if any(i.op_str == "al, 0xa"
                    for i in dosovrmap.window(ovr, site, 40)[-7:])]
    assert len(sites) == 1
    site, roll = sites[0]
    aunit = dosovrmap.unit_of(eng.units, roll)
    assert (aunit["seg"], aunit["fileoff"]) == (lay.attack_unit, lay.attack_unit_file)
    assert (lay.stub_attack, roll - aunit["fileoff"]) in aunit["ents"]
    assert site - aunit["fileoff"] == lay.attack_call
    assert site + 3 - aunit["fileoff"] == lay.attack_return
    assert any(f"mov byte ptr [{lay.attack_roll:#x}], al" == f"{i.mnemonic} {i.op_str}"
               for i in reads.body(ovr, roll, 0x3000) if i.address < site)
    assert f"byte ptr [{lay.save_roll:#x}], al" in [
        i.op_str for i in reads.body(ovr, reads.saving_throw(eng)["routine"], 0x3000)]
    # The query the walker asks with starts from the combatants' list head.
    walk = reads.body(ovr, walker, 0x3000)
    ask = collections.Counter(i.op_str for i in walk if i.mnemonic == "call")
    query = reads.body(ovr, int(ask.most_common(1)[0][0], 0), 0x3000)
    assert f"ptr [{lay.party_list:#x}]" in query[4].op_str
    assert eng.chain == lay.node_list


def _later(title, *, party=("GUY DE VALOIS", "MORGAINE"), node_id=49):
    """A watch on `title`'s addresses: the table's id-49 entry, the party list
    with a node on each member, an ORC on side 1 after them, and the
    attack roll's frames under the dispatcher's."""
    lay = dosfightwatch.PRAYER_LAYOUTS[title]
    dbg, notes = FakeDebugger(), []
    astub = STUB - lay.prayer_unit + lay.attack_unit
    dbg.put(DS, lay.handler_table + 49 * 4, _le(lay.stub_49) + _le(STUB))
    dbg.put(STUB, 0, DESCRIPTOR)
    dbg.put(STUB, lay.stub_49, CD3F)
    dbg.put(astub, lay.stub_attack, CD3F)
    dbg.put(DS, lay.party_list, _le(0) + _le(PARTY_SEG))
    for i, name in enumerate(party):
        rec = 0x1000 * i
        dbg.put(PARTY_SEG, rec, bytes((len(name),)) + name.encode())
        dbg.put(PARTY_SEG, rec + lay.side, b"\x00")
        nxt = (0x1000 * (i + 1), PARTY_SEG) if i + 1 < len(party) else (0, MONSTER_SEG)
        dbg.put(PARTY_SEG, rec + lay.next_record, _le(nxt[0]) + _le(nxt[1]))
        node = 0x800 + rec
        dbg.put(PARTY_SEG, rec + lay.node_list, _le(node) + _le(PARTY_SEG))
        dbg.put(PARTY_SEG, node, bytes((node_id,)) + _le(58) + b"\x03\x00")
    dbg.put(MONSTER_SEG, 0, bytes((3,)) + b"ORC")
    dbg.put(MONSTER_SEG, lay.side, b"\x01")
    for k in range(4):
        frame = bytearray(0x14)
        frame[0:2] = _le(0x200 + 0x40 * (k + 1))
        frame[2:6] = _le(0x1111) + _le(0x1111)
        if k == 0:
            frame[0x10] = 49
        if k == 2:
            frame[0x0A] = dosfightwatch.ATTACK_LIST
            frame[2:6] = _le(lay.attack_return) + _le(ATT_L)
        dbg.put(SS, 0x200 + 0x40 * k, bytes(frame))
    image = bytearray(0x2000)
    image[lay.prayer_unit * 16:lay.prayer_unit * 16 + 12] = DESCRIPTOR
    ovr = bytearray(OVR_SIZE)
    for name, at in lay.routines.items():
        ovr[at:at + 8] = CODE[name]
        dbg.put(LOAD, at - lay.prayer_unit_file, CODE[name])
    for name, off in lay.attack_points.items():
        code = bytes((0x70 + 0x10 * off + j) & 0xFF for j in range(8))
        ovr[lay.attack_unit_file + off:lay.attack_unit_file + off + 8] = code
        dbg.put(ATT_L, off, code)
    watch = dosfightwatch.PrayerWatch(dbg, bytes(ovr), bytes(image),
                                      note=lambda **kw: notes.append(kw),
                                      node_id=node_id, title=title,
                                      until_penalty=True)
    watch.attach()
    at_menu = watch.party()
    watch.arm()
    return dbg, watch, lay, astub, at_menu


#: Silver Blades' handler reads `les di, [bp+0Ch]` / `les di, es:[di]`: it
#: is handed the attack roll's own argument slot, not the record.
THROUGH_A_POINTER = {"ssb"}


def _asked(dbg, lay, who):
    """The combatant argument a handler, helper or query is handed: the record
    itself, or in Silver Blades the attack roll's own slot holding it."""
    dbg.put(SS, ROLL_BP + 0x0C, _le(0) + _le(who))
    title = next(k for k, v in dosfightwatch.PRAYER_LAYOUTS.items() if v is lay)
    if title in THROUGH_A_POINTER:
        return ROLL_BP + 0x0C, SS
    return 0, who


def _halt(dbg, lay, cs, ip, who, *, node=(0x800, PARTY_SEG), inner=False):
    """A halt at `cs:ip` asking about `who` and `node`: at an entry the
    arguments are on the stack, at the bonus test and the penalty in the
    handler's frame with `ES:DI` the record."""
    def go():
        off, seg = _asked(dbg, lay, who)
        args = _le(node[0]) + _le(node[1]) + _le(off) + _le(seg)
        stack = bytearray(16)
        stack[6:14] = args
        dbg.put(SS, 0x100, bytes(stack))
        bp = 0x200
        if inner:
            bp = INNER_BP
            dbg.put(SS, INNER_BP, _le(0x200) + bytes(6) + args)
            dbg.put(SS, INNER_BP - 1, b"\x00")
        dbg.registers.update({"CS": cs, "IP": ip, "SS": SS, "SP": 0x100, "BP": bp,
                              "ES": who, "DI": 0, "AX": 0, "ZF": 1})
    return go


def _roll_halts(dbg, lay, astub, who):
    """The attack roll's stub halt (unit loaded) and its list-10 call."""
    def stub():
        dbg.put(astub, lay.stub_attack, b"\xea" + _le(0x0100) + _le(ATT_L))
        stack = bytearray(16)
        stack[4] = 12
        stack[6:14] = _le(0) + _le(MONSTER_SEG if who != MONSTER_SEG else PARTY_SEG) \
            + _le(0) + _le(who)
        dbg.put(SS, 0x100, bytes(stack))
        dbg.registers.update({"CS": astub, "IP": lay.stub_attack, "SS": SS,
                              "SP": 0x100, "BP": 0x200, "ES": 0, "DI": 0,
                              "AX": 0, "ZF": 0})

    def call(off):
        def go():
            dbg.put(SS, ROLL_BP + 8, _le(0) + _le(PARTY_SEG if who == MONSTER_SEG
                                                  else MONSTER_SEG))
            dbg.put(SS, ROLL_BP + 0x0C, _le(0) + _le(who))
            dbg.registers.update({"CS": ATT_L, "IP": off, "SS": SS, "SP": 0x100,
                                  "BP": ROLL_BP, "ES": 0, "DI": 0, "AX": 0, "ZF": 0})
        return go
    return stub, call(lay.attack_call), call(lay.attack_return)


def _attack(dbg, lay, astub, who, prayer):
    """One attack by `who`: the roll, its list-10 call, the Prayer halts
    `prayer` names (`stub49`, `handler`, `bonus`, `helper`, `penalty`), and the
    walker's return."""
    stub, call, ret = _roll_halts(dbg, lay, astub, who)
    unit = lay.prayer_unit_file
    at = {"stub49": (STUB, lay.stub_49, False),
          "handler": (LOAD, lay.routines["handler"] - unit, False),
          "bonus": (LOAD, lay.routines["bonus"] - unit, True),
          "penalty": (LOAD, lay.routines["penalty"] - unit, True),
          "helper": (LOAD, lay.routines["helper"] - unit, False)}
    return [stub, call, *(_halt(dbg, lay, *at[k][:2], who, inner=at[k][2])
                          for k in prayer), ret]


LATER = ("curse", "ssb")


@pytest.mark.parametrize("title", LATER)
def test_a_later_title_arms_only_its_id_49_stub_and_the_attack_stub(title):
    dbg, watch, lay, astub, at_menu = _later(title)
    assert lay.stub_35 is None
    assert dbg.armed == [(STUB, lay.stub_49), (astub, lay.stub_attack)]
    assert watch.stub == STUB and watch.attack_stub == astub
    assert watch.holders(at_menu, 49) == ["GUY DE VALOIS", "MORGAINE"]
    assert [m["side"] for m in at_menu] == [0, 0, 1]


@pytest.mark.parametrize("title", LATER)
def test_a_later_title_counts_the_party_helper_and_a_monsters_penalty(title):
    dbg, watch, lay, astub, at_menu = _later(title)
    dbg.put(STUB, lay.stub_49, b"\xea" + _le(0x0100) + _le(LOAD))
    dbg.pending = [
        *_attack(dbg, lay, astub, PARTY_SEG, ["stub49"]),       # loads the unit
        *_attack(dbg, lay, astub, PARTY_SEG,
                 ["stub49", "handler", "bonus", "helper"]),
        *_attack(dbg, lay, astub, MONSTER_SEG, ["stub49", "handler", "penalty"])]
    stop = watch.run_fight(600, idle=lambda: not dbg.pending)
    assert stop == "attack round and penalty"
    assert len(dbg.pending) == 1              # the monster's return is never reached
    kinds = [h["kind"] for h in watch.halts]
    assert kinds.count("helper") == 1 and kinds.count("penalty") == 1
    helper = next(h for h in watch.halts if h["kind"] == "helper")
    assert helper["combatant"]["name"] == "GUY DE VALOIS"
    penalty = next(h for h in watch.halts if h["kind"] == "penalty")
    assert penalty["combatant"] == {"at": f"{MONSTER_SEG:04X}:0000", "name": "ORC",
                                    "side": 1}
    assert penalty["es_di_combatant"]["name"] == "ORC"
    rolls = f"ds_{lay.save_roll:04x}_{lay.attack_roll:04x}"
    assert set(helper[rolls]) == {f"{lay.save_roll:04x}", f"{lay.attack_roll:04x}"}
    result = watch.summary(49, at_menu, watch.party())
    assert result["conclusive"] is True and result["why"] == []
    assert result["monster_penalties"] == 1 and result["helper_hits"] == 1


def _ally_then_member(dbg, lay):
    """The party's first record, at `PARTY_SEG`, holds no node; a second, at
    `MEMBER_SEG`, holds the id-49 node."""
    dbg.put(PARTY_SEG, lay.node_list, _le(0) + _le(0))
    dbg.put(PARTY_SEG, lay.next_record, _le(0) + _le(MEMBER_SEG))
    dbg.put(MEMBER_SEG, 0, bytes((6,)) + b"MEMBER")
    dbg.put(MEMBER_SEG, lay.side, b"\x00")
    dbg.put(MEMBER_SEG, lay.next_record, _le(0) + _le(MONSTER_SEG))
    dbg.put(MEMBER_SEG, lay.node_list, _le(0x800) + _le(MEMBER_SEG))
    dbg.put(MEMBER_SEG, 0x800, bytes((49,)) + _le(58) + b"\x03\x00")


MEMBER_SEG = 0x4A00


@pytest.mark.parametrize("title", LATER)
def test_an_allys_round_without_the_node_does_not_keep_a_members_from_counting(title):
    dbg, watch, lay, astub, _ = _later(title, party=("ALLY",))
    _ally_then_member(dbg, lay)
    at_menu = watch.party()
    dbg.put(STUB, lay.stub_49, b"\xea" + _le(0x0100) + _le(LOAD))
    dbg.pending = [
        *_attack(dbg, lay, astub, PARTY_SEG, ["stub49"]),       # loads the unit
        *_attack(dbg, lay, astub, PARTY_SEG, ["stub49", "handler", "bonus", "helper"]),
        *_attack(dbg, lay, astub, MEMBER_SEG, ["stub49", "handler", "bonus", "helper"]),
        *_attack(dbg, lay, astub, MONSTER_SEG, ["stub49", "handler", "penalty"])]
    stop = watch.run_fight(600, idle=lambda: not dbg.pending)
    assert stop == "attack round and penalty"
    result = watch.summary(49, at_menu, watch.party())
    assert result["conclusive"] is True and result["why"] == []


@pytest.mark.parametrize("title", LATER)
def test_an_allys_round_alone_never_passes_an_id_49_run(title):
    dbg, watch, lay, astub, _ = _later(title, party=("ALLY",))
    _ally_then_member(dbg, lay)
    at_menu = watch.party()
    dbg.put(STUB, lay.stub_49, b"\xea" + _le(0x0100) + _le(LOAD))
    dbg.pending = [
        *_attack(dbg, lay, astub, PARTY_SEG, ["stub49"]),
        *_attack(dbg, lay, astub, PARTY_SEG, ["stub49", "handler", "bonus", "helper"]),
        *_attack(dbg, lay, astub, MONSTER_SEG, ["stub49", "handler", "penalty"])]
    watch.run_fight(600, idle=lambda: not dbg.pending)
    result = watch.summary(49, at_menu, watch.party())
    assert result["conclusive"] is False
    assert any("not on the attacker" in w for w in result["why"])


@pytest.mark.parametrize("title", LATER)
def test_a_monsters_penalty_before_a_members_round_does_not_stop_the_run(title):
    dbg, watch, lay, astub, _ = _later(title, party=("ALLY",))
    _ally_then_member(dbg, lay)
    at_menu = watch.party()
    dbg.put(STUB, lay.stub_49, b"\xea" + _le(0x0100) + _le(LOAD))
    dbg.pending = [
        *_attack(dbg, lay, astub, PARTY_SEG, ["stub49"]),
        *_attack(dbg, lay, astub, PARTY_SEG, ["stub49", "handler", "bonus", "helper"]),
        *_attack(dbg, lay, astub, MONSTER_SEG, ["stub49", "handler", "penalty"]),
        *_attack(dbg, lay, astub, MEMBER_SEG, ["stub49", "handler", "bonus", "helper"])]
    stop = watch.run_fight(600, idle=lambda: not dbg.pending)
    assert stop == "attack round and penalty"
    assert len(dbg.pending) == 1              # the member's return is never reached
    assert watch.completed["attacker"] == f"{MEMBER_SEG:04X}:0000"
    assert watch.round_ok(watch.completed)
    result = watch.summary(49, at_menu, watch.party())
    assert result["conclusive"] is True and result["why"] == []


@pytest.mark.parametrize("title", LATER)
def test_a_watch_with_no_tested_node_counts_any_round(title):
    _, watch, _, _, _ = _later(title)
    watch.node_id = None
    assert watch.round_ok({"attacker_nodes": None, "party": []})
    assert watch.round_ok({"attacker_nodes": [], "party": []}, None)


@pytest.mark.parametrize("title", LATER)
def test_without_until_penalty_only_a_round_the_node_passes_returns(title):
    dbg, watch, lay, astub, _ = _later(title, party=("ALLY",))
    _ally_then_member(dbg, lay)
    watch.until_penalty = False
    dbg.put(STUB, lay.stub_49, b"\xea" + _le(0x0100) + _le(LOAD))
    dbg.pending = [
        *_attack(dbg, lay, astub, PARTY_SEG, ["stub49"]),
        *_attack(dbg, lay, astub, PARTY_SEG, ["stub49", "handler", "bonus", "helper"]),
        *_attack(dbg, lay, astub, MEMBER_SEG, ["stub49", "handler", "bonus", "helper"])]
    stop = watch.run_fight(600, idle=lambda: not dbg.pending)
    assert stop == "one attack round"
    assert len(dbg.pending) == 1              # past the ally's round, at the member's
    assert watch.completed["attacker"] == f"{MEMBER_SEG:04X}:0000"


@pytest.mark.parametrize("title", LATER)
def test_a_penalty_halt_with_a_short_chain_logs_the_error(title):
    dbg, watch, lay, astub, _ = _later(title)
    dbg.put(STUB, lay.stub_49, b"\xea" + _le(0x0100) + _le(LOAD))
    penalty = _halt(dbg, lay, LOAD, lay.routines["penalty"] - lay.prayer_unit_file,
                    MONSTER_SEG, inner=True)

    def short():
        penalty()
        dbg.put(SS, 0x200 + 0x40, _le(0))     # the chain ends after two frames
    dbg.pending = [
        *_attack(dbg, lay, astub, PARTY_SEG, ["stub49"]),
        *_attack(dbg, lay, astub, PARTY_SEG,
                 ["stub49", "handler", "bonus", "helper"])[:-1], short]
    watch.run_fight(600, idle=lambda: not dbg.pending)
    halt = next(h for h in watch.halts if h["kind"] == "penalty")
    assert halt["list"] is None
    assert "IndexError" in halt["chain_error"]
    assert watch.penalties == []


@pytest.mark.parametrize("title", LATER)
def test_a_saving_throws_penalty_halt_is_not_a_monsters_attack(title):
    dbg, watch, lay, astub, at_menu = _later(title)
    dbg.put(STUB, lay.stub_49, b"\xea" + _le(0x0100) + _le(LOAD))
    penalty = _halt(dbg, lay, LOAD, lay.routines["penalty"] - lay.prayer_unit_file,
                    MONSTER_SEG, inner=True)

    def list_12():
        penalty()
        dbg.put(SS, 0x200 + 0x40 * 2 + 0x0A, bytes((12,)))
    dbg.pending = [
        *_attack(dbg, lay, astub, PARTY_SEG, ["stub49"]),
        *_attack(dbg, lay, astub, PARTY_SEG,
                 ["stub49", "handler", "bonus", "helper"])[:-1], list_12]
    watch.run_fight(600, idle=lambda: not dbg.pending)
    halt = next(h for h in watch.halts if h["kind"] == "penalty")
    assert halt["list"] == 12 and halt["combatant"]["side"] == 1
    assert watch.penalties == []


@pytest.mark.parametrize("title", LATER)
def test_a_later_title_party_round_alone_does_not_stop_or_conclude_the_run(title):
    dbg, watch, lay, astub, at_menu = _later(title)
    dbg.put(STUB, lay.stub_49, b"\xea" + _le(0x0100) + _le(LOAD))
    dbg.pending = [
        *_attack(dbg, lay, astub, PARTY_SEG, ["stub49"]),
        *_attack(dbg, lay, astub, PARTY_SEG, ["stub49", "handler", "bonus", "helper"])]
    assert watch.run_fight(600, idle=lambda: True) == "fight over"
    result = watch.summary(49, at_menu, watch.party())
    assert result["round_completed"] is True and result["conclusive"] is False
    assert any("penalty" in w for w in result["why"])


@pytest.mark.parametrize("title", LATER)
def test_a_later_title_whose_table_names_another_stub_is_blocked(title, monkeypatch):
    monkeypatch.setattr(dosfightwatch.time, "sleep", lambda s: None)
    dbg, watch, lay, _, _ = _later(title)
    dbg.put(DS, lay.handler_table + 49 * 4, _le(lay.stub_49 + 5) + _le(STUB))
    watch.ds = None
    with pytest.raises(dosfightwatch.PrayerWatchError, match="handler table"):
        watch.attach(tries=2)


def test_only_silver_blades_hands_the_combatant_over_through_a_pointer():
    assert [t for t, lay in dosfightwatch.PRAYER_LAYOUTS.items() if lay.indirect] == ["ssb"]
