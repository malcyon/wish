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

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

pytest.importorskip("tools.curse_of_the_azure_bonds.cursememorize")
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

    after = sorted((e for e in events if e["event"] == "after"),
                   key=lambda e: e["file"])
    assert [e["file"] for e in after] == [
        "CHRDATA1.SAV", "CHRDATA3.SAV", "chrdata2.sav"]
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
        minutes=1.0, out=str(tmp_path / "out"))


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
