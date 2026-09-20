"""Checks the key-list expansion and the per-press log of the DOS Curse
`MEMORIZE` page-turn driver, against a fake session.

`#574 (Camp.memorize's page-turn landing is stateful and not proven for page >
0)` needs four values after every keypress, and a run that stops pressing once
the grimoire is no longer showing.  Both are the parts of
`tools/curse_of_the_azure_bonds/cursememorize.py` that hold without an
emulator.
"""

from __future__ import annotations

import pathlib
import shutil
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

pytest.importorskip("tools.curse_of_the_azure_bonds.cursememorize")
from goldbox import dos_savegame as sg  # noqa: E402
from tools.curse_of_the_azure_bonds import cursememorize as cm  # noqa: E402


class FakeScreen:
    """Only what `press_sequence` reads off a capture."""

    def __init__(self, row, bar="bar", digest="dig"):
        self._row, self._bar, self._digest = row, bar, digest

    def highlight_row(self, rect, **kw):
        return self._row

    def glyphs(self, rect=None):
        return self._bar

    def digest(self, rect=None):
        return self._digest


class FakeSession:
    """Records keys, hands out canned screens, writes no file."""

    def __init__(self, screens):
        self.screens = list(screens)
        self.keys: list[str] = []
        self.shots: list[str] = []

    def key(self, *keys, **kw):
        self.keys.extend(keys)

    def settle(self, **kw):
        return self.screens.pop(0) if self.screens else FakeScreen(None)

    def shot(self, name, allow_blank=False):
        self.shots.append(name)
        return pathlib.Path(f"{name}.png")


class RectScreen(FakeScreen):
    """A screen whose rectangles read differently, as a real one's do."""

    def __init__(self, row, bar="bar", digest="dig", counter="count"):
        super().__init__(row, bar, digest)
        self._counter = counter

    def glyphs(self, rect=None):
        return self._counter if rect == cm.COUNTER else self._bar


def test_expand_keys_splits_words_and_repeats():
    assert cm.expand_keys(["n End*3"]) == ["n", "End", "End", "End"]
    assert cm.expand_keys(["End", "n"]) == ["End", "n"]
    assert cm.expand_keys(["~0.5 Return"]) == ["~0.5", "Return"]


def test_shot_name_keeps_no_punctuation_from_a_keysym():
    assert cm.shot_name("t0", 3, "~0.5") == "t0-03-_0_5"
    assert cm.shot_name("t0", 3, "Return") == "t0-03-Return"


def test_press_sequence_logs_four_values_for_every_press():
    s = FakeSession([FakeScreen(10, "barA", "d0"), FakeScreen(1, "barA", "d1")])
    rows: list[dict] = []
    out = cm.press_sequence(s, ["n", "End"], rows.append, tag="t0")
    assert s.keys == ["n", "End"]
    assert [(r["key"], r["row"], r["bar"], r["digest"]) for r in out] == [
        ("n", 10, "barA", "d0"),
        ("End", 1, "barA", "d1"),
    ]
    assert rows == out and s.shots == ["t0-00-n", "t0-01-End"]


def test_press_sequence_stops_after_two_unhighlighted_screens():
    s = FakeSession([FakeScreen(4), FakeScreen(None), FakeScreen(None),
                     FakeScreen(4)])
    rows: list[dict] = []
    out = cm.press_sequence(s, ["End"] * 4, rows.append, tag="t1")
    assert s.keys == ["End"] * 3
    assert [r["row"] for r in out] == [4, None, None]
    assert rows[-1]["key"] == "<stop>"


def test_press_sequence_presses_through_blanks_when_asked():
    s = FakeSession([FakeScreen(None)] * 3)
    out = cm.press_sequence(s, ["e", "m", "m"], lambda r: None, tag="path",
                            blank_stop=0)
    assert [r["key"] for r in out] == ["e", "m", "m"]


def test_a_sleep_token_presses_nothing():
    s = FakeSession([FakeScreen(2)])
    cm.press_sequence(s, ["~0"], lambda r: None, tag="t2")
    assert s.keys == []


def test_sample_reads_the_entry_state_without_a_keypress():
    s = FakeSession([FakeScreen(10, "barA", "d0")])
    rows: list[dict] = []
    row = cm.sample(s, rows.append, tag="t0")
    assert s.keys == [] and row["n"] == -1 and row["key"] == ""
    assert (row["row"], row["bar"], row["digest"]) == (10, "barA", "d0")
    assert rows == [row]


def test_a_press_records_the_memorise_counter_apart_from_the_bar():
    """The `CAN MEMORIZE` digits are the one thing that says whether a
    memorisation survived a screen, and the bar's own digest does not carry
    them: `m` moves both, and leaving the list and coming back moves only the
    counter."""
    s = FakeSession([RectScreen(10, "barA", "d0", "2 1"),
                     RectScreen(10, "barB", "d1", "2 0")])
    out = cm.press_sequence(s, ["n", "m"], lambda r: None, tag="t0")
    assert [(r["bar"], r["counter"]) for r in out] == [
        ("barA", "2 1"), ("barB", "2 0")]


def test_the_entry_sample_records_the_counter_too():
    s = FakeSession([RectScreen(10, "barA", "d0", "2 0")])
    assert cm.sample(s, lambda r: None, tag="t0")["counter"] == "2 0"


def test_follow_presses_each_line_under_its_own_tag_and_stops_at_quit(
        tmp_path):
    """One boot, several screens: the keys a screen wants are read off its own
    screenshot, so the file is written while the session is still up."""
    path = tmp_path / "keys"
    path.write_text("n m\n\n# a note\nEnd*2\n!quit\nEscape\n")
    s = FakeSession([FakeScreen(1)] * 10)
    rows: list[dict] = []
    notes: list[dict] = []

    lines = cm.follow(s, path, rows.append, lambda **kw: notes.append(kw),
                      deadline=time.time() + 5)

    assert s.keys == ["n", "m", "End", "End"]
    assert lines == 5 and notes[-1]["event"] == "follow-done"
    assert [r["tag"] for r in rows] == ["f01", "f01", "f04", "f04"]


def test_follow_does_not_press_a_line_the_file_has_not_finished(tmp_path):
    """A line is pressed when its newline arrives, never half written: an
    `Escape` pressed from `Escape Escape` would answer a prompt the other half
    was meant for."""
    path = tmp_path / "keys"
    path.write_text("n\nEnd Esc")
    s = FakeSession([FakeScreen(1)] * 5)
    notes: list[dict] = []

    cm.follow(s, path, lambda r: None, lambda **kw: notes.append(kw),
              deadline=time.time() + 0.3, poll=0.05)

    assert s.keys == ["n"]
    assert notes[-1]["event"] == "follow-timeout"


def test_follow_reports_the_records_when_a_line_asks(tmp_path):
    path = tmp_path / "keys"
    path.write_text("!records\n!quit\n")
    asked: list[bool] = []
    cm.follow(FakeSession([]), path, lambda r: None, lambda **kw: None,
              deadline=time.time() + 5, report=lambda: asked.append(True))
    assert asked == [True]


def test_follow_presses_nothing_once_its_deadline_has_passed(tmp_path):
    path = tmp_path / "keys"
    path.write_text("n\n")
    s = FakeSession([FakeScreen(1)])
    cm.follow(s, path, lambda r: None, lambda **kw: None,
              deadline=time.time() - 1)
    assert s.keys == []


class SaveSession:
    """A slot's save directory, with nothing else a wait needs."""

    def __init__(self, root):
        self.save_dir = root
        root.mkdir(parents=True, exist_ok=True)

    def save_file(self, letter):
        return self.save_dir / f"SAVGAM{letter.upper()}.DAT"


def test_a_slot_that_was_written_is_reported_as_changed(tmp_path, monkeypatch):
    monkeypatch.setattr(cm.dosbox, "settle_files", lambda folder, **kw: True)
    session = SaveSession(tmp_path / "SAVE")
    session.save_file("B").write_bytes(b"new")
    notes: list[dict] = []
    assert cm.wait_for_save(session, "B", None, lambda **kw: notes.append(kw))
    assert notes[-1] == {"event": "saved", "slot": "B", "changed": True}


def test_a_slot_the_game_never_wrote_is_reported_unchanged(
        tmp_path, monkeypatch):
    """The keys that should have saved may have gone to a screen that ignored
    them, and a run that called that a save would report the staged records as
    the game's own writing."""
    monkeypatch.setattr(cm.dosbox, "settle_files", lambda folder, **kw: True)
    session = SaveSession(tmp_path / "SAVE")
    session.save_file("B").write_bytes(b"old")
    notes: list[dict] = []
    assert not cm.wait_for_save(session, "B", b"old",
                                lambda **kw: notes.append(kw), timeout=0.2)
    assert notes[-1]["changed"] is False


class FakeSlotSession:
    """A slot directory with the files a run leaves in it."""

    def __init__(self, root, shots, saves):
        self.dir = root / "slot"
        self.save_dir = self.dir / "SAVE"
        (self.dir / "shots").mkdir(parents=True)
        self.save_dir.mkdir()
        for name in shots:
            (self.dir / "shots" / name).write_bytes(b"png")
        for name in saves:
            (self.save_dir / name).write_bytes(b"rec")


def test_keeping_a_run_leaves_nothing_a_longer_earlier_run_wrote(
        tmp_path, monkeypatch):
    """`--out` defaults to one fixed path.  A first run that pressed many keys
    and saved two characters, then a second that pressed one and saved one,
    must leave `out` holding the second's files only -- otherwise the
    `after` events describe a character the second run never touched."""
    monkeypatch.setattr(cm, "describe", lambda path: {"file": path.name})
    out = tmp_path / "out"

    first = FakeSlotSession(tmp_path / "a", ["t0-00-n.png", "t0-01-End.png"],
                            ["CHRDATA1.SAV", "CHRDATA2.SAV", "SAVGAMA.DAT"])
    cm.keep_run_files(first, out, lambda **kw: None)

    events: list[dict] = []
    second = FakeSlotSession(tmp_path / "b", ["t0-00-n.png"],
                             ["CHRDATA1.SAV", "SAVGAMA.DAT", "OTHER.TXT"])
    cm.keep_run_files(second, out, lambda **kw: events.append(kw))

    assert sorted(p.name for p in (out / "shots").iterdir()) == ["t0-00-n.png"]
    assert sorted(p.name for p in (out / "saves").iterdir()) == [
        "CHRDATA1.SAV", "SAVGAMA.DAT"]
    assert [e["file"] for e in events if e["event"] == "after"] == [
        "CHRDATA1.SAV"]
    assert events[-1]["event"] == "kept"


def test_keeping_a_run_leaves_a_file_this_tool_does_not_write(
        tmp_path, monkeypatch):
    """`--out` is a directory somebody may keep notes in.  Only the shots and
    the records this tool copies are replaced; a lower-case record from an
    earlier run goes too, because the copy filter matches by upper case."""
    monkeypatch.setattr(cm, "describe", lambda path: {"file": path.name})
    out = tmp_path / "out"
    (out / "shots").mkdir(parents=True)
    (out / "saves").mkdir()
    (out / "shots" / "old.PNG").write_bytes(b"x")
    (out / "shots" / "notes.txt").write_bytes(b"mine")
    (out / "saves" / "chrdata9.sav").write_bytes(b"x")
    (out / "saves" / "savgamb.dat").write_bytes(b"x")
    (out / "saves" / "notes.txt").write_bytes(b"mine")
    (out / "run.jsonl").write_bytes(b"kept")

    slot = FakeSlotSession(tmp_path / "a", ["t0-00-n.png"], ["CHRDATA1.SAV"])
    cm.keep_run_files(slot, out, lambda **kw: None)

    assert sorted(p.name for p in (out / "shots").iterdir()) == [
        "notes.txt", "t0-00-n.png"]
    assert sorted(p.name for p in (out / "saves").iterdir()) == [
        "CHRDATA1.SAV", "notes.txt"]
    assert (out / "run.jsonl").read_bytes() == b"kept"


def test_a_run_that_died_before_staging_keeps_the_last_runs_evidence(tmp_path):
    out = tmp_path / "out"
    (out / "shots").mkdir(parents=True)
    (out / "saves").mkdir()
    (out / "shots" / "t0-00-n.png").write_bytes(b"png")
    (out / "saves" / "CHRDATA1.SAV").write_bytes(b"rec")

    empty = FakeSlotSession(tmp_path / "a", [], [])
    events: list[dict] = []
    cm.keep_run_files(empty, out, lambda **kw: events.append(kw))

    assert events == []
    assert (out / "shots" / "t0-00-n.png").read_bytes() == b"png"
    assert (out / "saves" / "CHRDATA1.SAV").read_bytes() == b"rec"


def test_a_record_that_will_not_read_does_not_hide_the_others(
        tmp_path, monkeypatch):
    def describe(path):
        if path.name.upper() == "CHRDATA1.SAV":
            raise ValueError("short record")
        return {"file": path.name}

    monkeypatch.setattr(cm, "describe", describe)
    slot = FakeSlotSession(tmp_path / "a", ["t0-00-n.png"],
                           ["CHRDATA1.SAV", "chrdata2.sav", "CHRDATA3.SAV"])
    events: list[dict] = []
    cm.keep_run_files(slot, tmp_path / "out", lambda **kw: events.append(kw))

    after = [e for e in events if e["event"] == "after"]
    # Records come back in name order ignoring case, and compare ignoring
    # case: a case-insensitive filesystem may report either spelling.
    assert [e["file"].upper() for e in after] == [
        "CHRDATA1.SAV", "CHRDATA2.SAV", "CHRDATA3.SAV"]
    assert "short record" in after[0]["error"]
    assert "error" not in after[1] and "error" not in after[2]


class RunScreen(FakeScreen):
    def ink(self, rect=None):
        return "ink"


class RunSession:
    """Just enough of `dosbox.Session` for `run` to go from stage to close."""

    def __init__(self, root):
        self.dir = root / "slot"
        self.save_dir = self.dir / "SAVE"
        (self.dir / "shots").mkdir(parents=True)
        self.save_dir.mkdir()

    def stage(self, fresh=False):
        pass

    def save_file(self, letter):
        return self.save_dir / f"SAVGAM{letter.upper()}.DAT"

    def boot(self, fresh=False):
        pass

    def marching_first(self, slot, who):
        return type("Game", (), {"world_bar": "bar"})()

    def capture(self):
        return FakeScreen(1)

    def settle(self, **kw):
        return RunScreen(1)

    def key(self, *keys, **kw):
        pass

    def shot(self, name, allow_blank=False):
        path = self.dir / "shots" / f"{name}.png"
        path.write_bytes(b"png")
        return path

    def close(self):
        pass


class FakeSlot:
    def release(self):
        pass


def _run_args(tmp_path, specimen):
    return cm.argparse.Namespace(
        specimen=str(specimen), game="CURSE", slot="A", who=5, begin="",
        path="", reenter="", trial=["n"], after=None, save_to=None,
        follow=None, follow_minutes=1.0, minutes=1.0,
        out=str(tmp_path / "out"), relocate=None)


def _curse_save(*, area=1, geo=1, x=4, y=4, facing=0):
    save = bytearray(sg.SAVE_CURSE_OF_THE_AZURE_BONDS.size)
    save[0] = 2
    sg.put_word(save, sg.AREA, geo)
    sg.put_word(save, sg.SCRIPT, area)
    sg.put_word(save, sg.DISK, 2)
    sg.put_word(save, sg.INDOORS, 1)
    sg.put_position(save, x, y, facing)
    sg.put_wall_block(save, (1, 2, 3))
    return save


def test_relocation_changes_only_the_copied_slot_a_save(
        tmp_path, monkeypatch):
    source = tmp_path / "specimen" / "SAVGAMA.DAT"
    source.parent.mkdir()
    seed = _curse_save()
    script_start, script_end = sg.SAVE_CURSE_OF_THE_AZURE_BONDS.script_buffer
    seed[script_start:script_end] = bytes([0xA5]) * (script_end - script_start)
    original = bytes(seed)
    source.write_bytes(original)
    staged = tmp_path / "slot" / "SAVE" / source.name
    staged.parent.mkdir(parents=True)
    shutil.copyfile(source, staged)
    game = tmp_path / "game"
    game.mkdir()
    (game / "ECL2.DAX").write_bytes(b"synthetic index")
    block = b"\x88\x13target area script"
    monkeypatch.setattr(cm.dos_savegame, "dax_block",
                        lambda data, area, name: block)

    moved = cm.relocate_staged_save(
        staged, game, area=2, x=8, y=0, facing=1)

    result = staged.read_bytes()
    shape = sg.SAVE_CURSE_OF_THE_AZURE_BONDS
    start, end = shape.script_buffer
    assert source.read_bytes() == original
    assert sg.current_area(result) == moved["area"] == 2
    assert sg.geo_block(result) == moved["geo"] == 1
    assert sg.position(result) == tuple(moved["position"]) == (8, 0, 1)
    assert result[0] == sg.word(result, sg.DISK) == moved["dax"] == 2
    assert result[start:start + len(block) - sg.ECL_HEADER] == \
        block[sg.ECL_HEADER:]
    assert not any(result[start + len(block) - sg.ECL_HEADER:end])
    assert sg.wall_block(result)[0] == (1, 2, 3)


def test_relocation_refuses_an_unregistered_or_different_map_before_writing(
        tmp_path):
    staged = tmp_path / "SAVGAMA.DAT"
    original = bytes(_curse_save())
    staged.write_bytes(original)

    with pytest.raises(ValueError, match="not a registered Curse area"):
        cm.relocate_staged_save(staged, tmp_path, area=0x7F,
                                x=8, y=0, facing=1)
    with pytest.raises(ValueError, match="resident GEO01"):
        cm.relocate_staged_save(staged, tmp_path, area=3,
                                x=8, y=0, facing=1)

    assert staged.read_bytes() == original


def test_the_existing_path_stages_the_original_location(
        tmp_path, monkeypatch, capsys):
    specimen = _specimen(tmp_path)
    original = bytes(_curse_save(area=1, geo=1, x=4, y=4, facing=0))
    (specimen / "SAVGAMA.DAT").write_bytes(original)
    _stub_run(monkeypatch, tmp_path,
              lambda slot, game: RunSession(tmp_path / "slot"))
    args = _run_args(tmp_path, specimen)

    assert cm.run(args) == 0
    capsys.readouterr()

    assert (tmp_path / "out" / "saves" / "SAVGAMA.DAT").read_bytes() == \
        original


def test_the_driver_relocates_the_copy_before_boot(
        tmp_path, monkeypatch, capsys):
    specimen = _specimen(tmp_path)
    original = bytes(_curse_save())
    (specimen / "SAVGAMA.DAT").write_bytes(original)
    (tmp_path / "ECL2.DAX").write_bytes(b"synthetic index")
    block = b"\x88\x13target area script"
    monkeypatch.setattr(cm.dos_savegame, "dax_block",
                        lambda data, area, name: block)

    class RelocatedSession(RunSession):
        def boot(self, fresh=False):
            assert sg.current_area(self.save_file("A").read_bytes()) == 2

    _stub_run(monkeypatch, tmp_path,
              lambda slot, game: RelocatedSession(tmp_path / "slot"))
    args = _run_args(tmp_path, specimen)
    args.relocate = (2, 8, 0, 1)

    assert cm.run(args) == 0
    capsys.readouterr()

    staged = (tmp_path / "out" / "saves" / "SAVGAMA.DAT").read_bytes()
    assert specimen.joinpath("SAVGAMA.DAT").read_bytes() == original
    assert sg.current_area(staged) == 2
    assert sg.position(staged) == (8, 0, 1)


def test_a_rerun_into_the_same_out_replaces_the_log_and_the_table(
        tmp_path, monkeypatch, capsys):
    specimen = tmp_path / "specimen"
    specimen.mkdir()
    (specimen / "CHRDATA1.SAV").write_bytes(b"rec")
    monkeypatch.setattr(cm, "describe", lambda path: {"file": path.name})
    monkeypatch.setattr(cm.dosbox, "find_game", lambda stem: tmp_path)
    monkeypatch.setattr(cm.dosbox, "claim", lambda note="": FakeSlot())
    monkeypatch.setattr(cm.dosbox, "Session",
                        lambda slot, game: RunSession(tmp_path / "slot"))
    args = _run_args(tmp_path, specimen)

    assert cm.run(args) == 0
    first_log = (tmp_path / "out" / "run.jsonl").read_text().splitlines()
    first_tsv = (tmp_path / "out" / "keys.tsv").read_text().splitlines()
    shutil.rmtree(tmp_path / "slot")
    assert cm.run(args) == 0
    capsys.readouterr()

    log = (tmp_path / "out" / "run.jsonl").read_text().splitlines()
    tsv = (tmp_path / "out" / "keys.tsv").read_text().splitlines()
    assert len(log) == len(first_log) and len(tsv) == len(first_tsv)
    assert sum(line.startswith("tag\t") for line in tsv) == 1


@pytest.mark.parametrize("what", ["specimen", "game"])
def test_a_missing_specimen_or_game_fails_before_a_slot_is_claimed(
        tmp_path, monkeypatch, capsys, what):
    specimen = tmp_path / "specimen"
    if what == "game":
        specimen.mkdir()

        def no_game(stem):
            raise FileNotFoundError("no archives at nowhere")

        monkeypatch.setattr(cm.dosbox, "find_game", no_game)
    else:
        monkeypatch.setattr(cm.dosbox, "find_game", lambda stem: tmp_path)

    def claim(note=""):
        raise AssertionError("a slot was claimed")

    monkeypatch.setattr(cm.dosbox, "claim", claim)
    assert cm.run(_run_args(tmp_path, specimen)) == 2
    assert not (tmp_path / "out").exists()
    assert what in capsys.readouterr().err


def _stub_run(monkeypatch, tmp_path, session_factory):
    monkeypatch.setattr(cm, "describe", lambda path: {"file": path.name})
    monkeypatch.setattr(cm.dosbox, "find_game", lambda stem: tmp_path)
    monkeypatch.setattr(cm.dosbox, "claim", lambda note="": FakeSlot())
    monkeypatch.setattr(cm.dosbox, "Session", session_factory)


def _specimen(tmp_path):
    specimen = tmp_path / "specimen"
    specimen.mkdir()
    (specimen / "CHRDATA1.SAV").write_bytes(b"rec")
    return specimen


def test_a_shot_an_earlier_tenant_of_the_slot_left_is_not_kept(
        tmp_path, monkeypatch, capsys):
    """`stage(fresh=True)` empties `game/` and not `shots/`, so the slot may
    still hold the last tenant's PNGs when this run starts."""
    def factory(slot, game):
        session = RunSession(tmp_path / "slot")
        (session.dir / "shots" / "t0-19-End.png").write_bytes(b"stale")
        return session

    _stub_run(monkeypatch, tmp_path, factory)
    out = tmp_path / "out"
    (out / "shots").mkdir(parents=True)
    (out / "shots" / "t0-19-End.png").write_bytes(b"previous run")

    assert cm.run(_run_args(tmp_path, _specimen(tmp_path))) == 0
    capsys.readouterr()

    kept = sorted(p.name for p in (out / "shots").iterdir())
    assert "t0-19-End.png" not in kept and kept
    assert all(p.read_bytes() == b"png" for p in (out / "shots").iterdir())


def test_a_run_that_dies_before_staging_keeps_evidence_despite_a_stale_shot(
        tmp_path, monkeypatch, capsys):
    class NoStage(RunSession):
        def stage(self, fresh=False):
            raise RuntimeError("no game tree")

    def factory(slot, game):
        session = NoStage(tmp_path / "slot")
        (session.dir / "shots" / "t0-19-End.png").write_bytes(b"stale")
        return session

    _stub_run(monkeypatch, tmp_path, factory)
    out = tmp_path / "out"
    (out / "shots").mkdir(parents=True)
    (out / "shots" / "t0-00-n.png").write_bytes(b"previous run")

    with pytest.raises(RuntimeError, match="no game tree"):
        cm.run(_run_args(tmp_path, _specimen(tmp_path)))
    capsys.readouterr()

    assert [p.name for p in (out / "shots").iterdir()] == ["t0-00-n.png"]
    assert (out / "shots" / "t0-00-n.png").read_bytes() == b"previous run"


def test_a_full_pool_leaves_the_earlier_runs_log_and_table(
        tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    (out / "run.jsonl").write_text("earlier log\n")
    (out / "keys.tsv").write_text("earlier table\n")

    def claim(note=""):
        raise RuntimeError("pool full")

    monkeypatch.setattr(cm.dosbox, "find_game", lambda stem: tmp_path)
    monkeypatch.setattr(cm.dosbox, "claim", claim)
    with pytest.raises(RuntimeError, match="pool full"):
        cm.run(_run_args(tmp_path, _specimen(tmp_path)))

    assert (out / "run.jsonl").read_text() == "earlier log\n"
    assert (out / "keys.tsv").read_text() == "earlier table\n"


def test_a_session_that_will_not_build_leaves_the_log_and_releases_the_slot(
        tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    (out / "run.jsonl").write_text("earlier log\n")
    released: list[bool] = []

    class Slot:
        def release(self):
            released.append(True)

    def factory(slot, game):
        raise RuntimeError("xdotool is missing")

    monkeypatch.setattr(cm.dosbox, "find_game", lambda stem: tmp_path)
    monkeypatch.setattr(cm.dosbox, "claim", lambda note="": Slot())
    monkeypatch.setattr(cm.dosbox, "Session", factory)
    with pytest.raises(RuntimeError, match="xdotool"):
        cm.run(_run_args(tmp_path, _specimen(tmp_path)))

    assert (out / "run.jsonl").read_text() == "earlier log\n"
    assert released == [True]


def test_a_directory_named_like_a_shot_or_a_record_does_not_stop_the_copy(
        tmp_path, monkeypatch):
    monkeypatch.setattr(cm, "describe", lambda path: {"file": path.name})
    out = tmp_path / "out"
    (out / "shots" / "x.png").mkdir(parents=True)
    (out / "saves" / "CHRDATDIR").mkdir(parents=True)
    slot = FakeSlotSession(tmp_path / "a", ["t0-00-n.png"], ["CHRDATA1.SAV"])
    (slot.dir / "shots" / "y.png").mkdir()
    (slot.save_dir / "SAVGAMDIR").mkdir()

    cm.keep_run_files(slot, out, lambda **kw: None)

    assert (out / "shots" / "t0-00-n.png").is_file()
    assert (out / "saves" / "CHRDATA1.SAV").is_file()
    assert not (out / "shots" / "y.png").exists()
    assert (out / "shots" / "x.png").is_dir()
    assert (out / "saves" / "CHRDATDIR").is_dir()


def test_a_run_whose_files_could_not_be_kept_exits_nonzero(
        tmp_path, monkeypatch, capsys):
    _stub_run(monkeypatch, tmp_path, lambda slot, game: RunSession(
        tmp_path / "slot"))

    def keep(session, out, note):
        raise OSError("disk full")

    monkeypatch.setattr(cm, "keep_run_files", keep)

    assert cm.run(_run_args(tmp_path, _specimen(tmp_path))) == 1
    assert "keeping-failed" in capsys.readouterr().out
