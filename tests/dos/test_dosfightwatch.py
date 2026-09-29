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


def test_a_split_that_hits_only_the_silver_pile_is_measured_and_matched():
    ovr = _ovr()
    dbg = _Debugger(ovr, _script(1000, 532), counts=(13, 7))
    dbg.pile = dosfightwatch.PILE_BASE + 4          # silver
    report = dosfightwatch.measure_split(
        _por(dbg), ovr, steps=5, fight_kw={"settled": 0.0},
        walk=lambda por, steps: {"met": True})
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
        walk=lambda por, steps: {"met": True})
    assert report["piles"]["gold"]["taken"] == 532
    assert report["piles"]["silver"]["before"] == 300
    assert report["piles"]["silver"]["taken"] == 100
    assert report["piles"]["silver"]["matches"] is False   # the rule says 161


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


POOL_SIZE = dos_savegame.SAVE_POOL_OF_RADIANCE.size


def _donor(*, outdoors=False) -> bytes:
    """A zero Pool save `retarget`ed to the Slums, standing at 14,4 facing east."""
    save = bytearray(POOL_SIZE)
    dos_savegame.retarget(save, area=20, dax=2, geo=20, wallset=(2, 4, 1),
                          script=b"\0\0" + b"\x42" * 100)
    dos_savegame.put_position(save, 14, 4, 1)
    dos_savegame.put_word(save, dos_savegame.INDOORS, 0 if outdoors else 1)
    return bytes(save)


def _stage(tmp_path):
    folder, save = tmp_path / "spec", tmp_path / "SAVE"
    folder.mkdir()
    save.mkdir()
    hall = bytearray(POOL_SIZE)
    dos_savegame.retarget(hall, area=11, dax=3, geo=0, wallset=(0, 0xFFFF, 0xFFFF),
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


def test_placing_refuses_an_outdoor_donor(tmp_path):
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

    def measure(por, ovr, *, steps, ds, evidence, walk):
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
