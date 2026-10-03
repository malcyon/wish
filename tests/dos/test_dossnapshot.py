"""DOS machine snapshots: the config they need and the file handling around them.

Nothing here boots DOSBox-X.  A fake `key()` stands in for the emulator: the
save key writes a state file and the log line DOSBox-X writes, the load key
records which state file was in the slot.  The live control, which boots Pool
of Radiance, walks a square and restores, is `tools/dos/dossnapshot.py control`.
"""

from __future__ import annotations

import pathlib
import sys
import zipfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.dos import dosbox, dosboxx, dossnapshot  # noqa: E402


def _sections(conf: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    current = ""
    for line in conf.splitlines():
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            out[current] = []
        elif current:
            out[current].append(line)
    return out


def _conf(tmp_path) -> str:
    return dosboxx.CONFIG.format(dir=tmp_path, stem="POOLRAD", exe="START.EXE",
                                 cycles=30000, title=dosboxx.TITLE)


def test_the_config_turns_off_the_remark_dialog_inside_the_dosbox_section(tmp_path):
    conf = dossnapshot.add_config(_conf(tmp_path))
    dosbox_section = _sections(conf)["dosbox"]
    assert "saveremark=false" in dosbox_section
    assert "forceloadstate=true" in dosbox_section
    assert "saveremark=false" not in _sections(_conf(tmp_path)).get("dosbox", [])


def test_adding_the_config_twice_adds_each_line_once(tmp_path):
    once = dossnapshot.add_config(_conf(tmp_path))
    assert dossnapshot.add_config(once) == once
    assert once.count("saveremark=false") == 1


def test_a_config_with_no_dosbox_section_is_refused():
    with pytest.raises(ValueError):
        dossnapshot.add_config("[sdl]\nfullscreen=false\n")


def test_changed_files_names_added_removed_and_rewritten():
    before = {"SAVGAMA.DAT": "1", "SAVGAMB.DAT": "2", "OLD.DAT": "3"}
    after = {"SAVGAMA.DAT": "1", "SAVGAMB.DAT": "9", "SAVGAMC.DAT": "4"}
    assert dossnapshot.changed_files(before, after) == [
        "OLD.DAT", "SAVGAMB.DAT", "SAVGAMC.DAT"]


class FakeEmulator:
    """What DOSBox-X does with the two keys, as far as the files can tell."""

    def __init__(self, session, save_line="[11:07:01]: Saved. (Slot 1)",
                 load_line="[11:08:36]: Loaded. (Slot 1)", write_zip=True):
        self.s = session
        self.save_line = save_line
        self.load_line = load_line
        self.write_zip = write_zip
        self.loaded: list[bytes] = []
        self.pressed: list[str] = []

    def _log(self, line: str) -> None:
        with self.s.log.open("a") as f:
            f.write(line + "\n")

    def key(self, *keys: str, gap: float = 0.35) -> None:
        for k in keys:
            self.pressed.append(k)
            if k == dossnapshot.SAVE_KEY:
                self.s.state_file.parent.mkdir(parents=True, exist_ok=True)
                if self.write_zip:
                    with zipfile.ZipFile(self.s.state_file, "w") as z:
                        z.writestr("Memory", f"state {len(self.pressed)}")
                else:
                    self.s.state_file.write_bytes(b"half a state")
                self._log("Saving state to slot: 1")
                if self.save_line:
                    self._log(self.save_line)
            elif k == dossnapshot.LOAD_KEY:
                self.loaded.append(self.s.state_file.read_bytes())
                self._log("Loading state from slot: 1")
                if self.load_line:
                    self._log(self.load_line)


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setattr(dosboxx, "require_debugger", lambda: None)
    monkeypatch.setattr(dosbox, "require_tools", lambda tools=(): None)
    monkeypatch.setattr(dosbox, "WORK", tmp_path)
    game = tmp_path / "archive" / "POOLRAD"
    (game / "SAVE").mkdir(parents=True)
    (game / "START.EXE").write_bytes(b"MZ")
    (game / "SAVE" / "SAVGAMA.DAT").write_bytes(b"a")
    slot_dir = tmp_path / "inst" / "0"
    slot_dir.mkdir(parents=True)
    slot = dosboxx.Slot(n=0, dir=slot_dir, _fd=-1, _display_num=90)
    s = dossnapshot.SnapshotSession(slot, game, snapshot_dir=tmp_path / "snaps")
    s.stage()
    s.STATE_TIMEOUT = 2.0
    return s


def test_staging_writes_the_snapshot_lines_into_the_config_dosbox_x_reads(session):
    conf = (session.dir / "dosbox.conf").read_text()
    assert "saveremark=false" in _sections(conf)["dosbox"]
    assert "forceloadstate=true" in _sections(conf)["dosbox"]


def test_a_snapshot_moves_the_slot_file_to_its_name(session, monkeypatch):
    emu = FakeEmulator(session)
    monkeypatch.setattr(session, "key", emu.key)
    path = session.snapshot("leg1")
    assert path == session.snapshot_dir / "leg1.sav"
    assert zipfile.is_zipfile(path)
    assert not session.state_file.exists()
    assert emu.pressed == [dossnapshot.SAVE_KEY]


def test_a_restore_loads_that_snapshot_and_not_a_later_one(session, monkeypatch):
    emu = FakeEmulator(session)
    monkeypatch.setattr(session, "key", emu.key)
    first = session.snapshot("first").read_bytes()
    session.snapshot("second")
    assert session.restore("first") == []
    assert emu.loaded == [first]
    assert emu.pressed[-1] == dossnapshot.LOAD_KEY


def test_a_restore_names_the_game_saves_written_since_the_snapshot(session, monkeypatch):
    emu = FakeEmulator(session)
    monkeypatch.setattr(session, "key", emu.key)
    session.snapshot("leg")
    (session.save_dir / "SAVGAMC.DAT").write_bytes(b"c")
    (session.save_dir / "SAVGAMA.DAT").write_bytes(b"rewritten")
    assert session.restore("leg") == ["SAVGAMA.DAT", "SAVGAMC.DAT"]
    # The restore leaves the folder as the game left it.
    assert (session.save_dir / "SAVGAMC.DAT").read_bytes() == b"c"


def test_restoring_a_name_never_saved_raises(session, monkeypatch):
    emu = FakeEmulator(session)
    monkeypatch.setattr(session, "key", emu.key)
    with pytest.raises(FileNotFoundError):
        session.restore("never")
    assert emu.pressed == []


def test_a_load_dosbox_x_aborts_raises_with_its_reason(session, monkeypatch):
    emu = FakeEmulator(session, load_line="Aborted. Check your memory size: 16 MB")
    monkeypatch.setattr(session, "key", emu.key)
    session.snapshot("leg")
    with pytest.raises(dossnapshot.SnapshotFailed, match="memory size"):
        session.restore("leg")


def test_a_save_with_no_log_line_times_out(session, monkeypatch):
    emu = FakeEmulator(session, save_line="")
    monkeypatch.setattr(session, "key", emu.key)
    session.STATE_TIMEOUT = 0.3
    with pytest.raises(dossnapshot.SnapshotFailed, match="no log line"):
        session.snapshot("leg")


def test_a_state_file_that_is_not_a_complete_zip_raises(session, monkeypatch):
    emu = FakeEmulator(session, write_zip=False)
    monkeypatch.setattr(session, "key", emu.key)
    session.ZIP_WAIT = 0.3
    with pytest.raises(dossnapshot.SnapshotFailed, match="not a complete state"):
        session.snapshot("leg")


def test_a_state_file_completed_after_the_log_line_is_waited_for(session, monkeypatch):
    """The log line can come before the file is flushed; the wait sees it finish."""
    emu = FakeEmulator(session, write_zip=False)
    monkeypatch.setattr(session, "key", emu.key)
    slept = []

    def sleep(seconds):
        # The flush lands during the first pause after the log line.
        if dossnapshot.SAVE_KEY in emu.pressed and not slept:
            with zipfile.ZipFile(session.state_file, "w") as z:
                z.writestr("Memory", "flushed")
        slept.append(seconds)

    monkeypatch.setattr(dossnapshot.time, "sleep", sleep)
    path = session.snapshot("leg")
    assert zipfile.is_zipfile(path)
    assert slept


@pytest.mark.parametrize("record", [None, "not json", "[1, 2]"])
def test_a_missing_or_corrupt_saves_record_raises_before_loading(session, monkeypatch,
                                                                  record):
    emu = FakeEmulator(session)
    monkeypatch.setattr(session, "key", emu.key)
    session.snapshot("leg")
    sidecar = session.snapshot_dir / "leg.saves.json"
    if record is None:
        sidecar.unlink()
    else:
        sidecar.write_text(record)
    with pytest.raises(dossnapshot.SnapshotFailed, match="leg.saves.json"):
        session.restore("leg")
    assert emu.loaded == []


def test_discard_removes_the_state_and_its_record(session, monkeypatch):
    emu = FakeEmulator(session)
    monkeypatch.setattr(session, "key", emu.key)
    session.snapshot("leg")
    session.discard_snapshot("leg")
    assert list(session.snapshot_dir.iterdir()) == []
    session.discard_snapshot("leg")  # twice is harmless


@pytest.mark.parametrize("name", ["", "../x", "a b", "a/b"])
def test_a_name_that_could_leave_the_folder_is_refused(session, name):
    with pytest.raises(ValueError):
        session.snapshot_path(name)


def test_the_default_folder_is_under_the_cache_and_names_the_slot(session):
    s = dossnapshot.SnapshotSession(session.slot, session.source)
    assert s.snapshot_dir.parts[-4:] == ("wish", "dos", "snapshots", "x0")
    assert ".cache" in s.snapshot_dir.parts
