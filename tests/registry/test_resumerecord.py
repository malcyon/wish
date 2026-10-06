"""The shared resume record: written last, read back with every hash checked."""
import json

import pytest

from tools.registry import resumerecord as R


def _record():
    return {
        "driver": "amiga", "argv": ["measure", "--title", "darkness"], "command": "measure",
        "title": "darkness", "holder": "wish2-a2",
        "step": {"n": 13, "key": "S", "state": "camp_save_picker", "kind": "key"},
        "sent": [["P", "key"], ["S", "key"]],
        "machine": {"file": "state.uss", "count_snapshot": 7, "exe": "abc"},
        "start": {"config": "C:\\Amiga\\configs\\goldbox-a500.uae", "config_sha256": "ff", "settings": ["a=b"]},
        "disks": {"df0": {"remote": "C:/Amiga/Disks/x-df0.adf", "file": "df0.adf", "settled": True},
                  "df1": {"remote": "C:/Amiga/Disks/x-df1.adf", "file": "df1.adf", "settled": True}},
        "options": {"no_encounters": True, "encounters_on_at_miss": True, "walk_retry": 0},
        "resumable": True, "why_not": None,
    }


@pytest.fixture
def folder(tmp_path):
    (tmp_path / "state.uss").write_bytes(b"ASF state")
    (tmp_path / "df0.adf").write_bytes(b"disk zero")
    (tmp_path / "df1.adf").write_bytes(b"disk one")
    return tmp_path


def test_write_then_read_round_trips(folder):
    path = R.write(folder, _record())
    assert path == folder / "resume.json"
    got = R.read(path, "amiga")
    want = _record()
    assert got["format"] == R.FORMAT and got["version"] == R.VERSION
    for key in ("argv", "step", "sent", "options", "start", "holder", "resumable"):
        assert got[key] == want[key]
    assert got["machine"]["count_snapshot"] == 7


def test_record_holds_the_required_fields_and_disk_hashes(folder):
    got = R.read(R.write(folder, _record()), "amiga")
    assert got["options"]["no_encounters"] is True
    assert got["options"]["encounters_on_at_miss"] is True
    assert [k for k, _ in got["sent"]] == ["P", "S"]
    assert got["step"]["n"] == 13
    assert got["start"]["config_sha256"] == "ff"
    assert got["disks"]["df0"]["sha256"] == R.sha256_file(folder / "df0.adf")
    assert got["machine"]["sha256"] == R.sha256_file(folder / "state.uss")
    assert got["machine"]["bytes"] == len(b"ASF state")


def test_missing_required_field_is_not_written(folder):
    record = _record()
    del record["options"]
    with pytest.raises(R.ResumeRecordError, match="options"):
        R.write(folder, record)
    assert not (folder / "resume.json").exists()


def test_changed_file_fails_the_read(folder):
    path = R.write(folder, _record())
    (folder / "df1.adf").write_bytes(b"disk one, written to")
    with pytest.raises(R.ResumeRecordError, match="df1.adf"):
        R.read(path, "amiga")


def test_missing_file_fails_the_read(folder):
    path = R.write(folder, _record())
    (folder / "state.uss").unlink()
    with pytest.raises(R.ResumeRecordError, match="state.uss"):
        R.read(path, "amiga")


def test_listed_file_must_exist_to_write(folder):
    (folder / "df0.adf").unlink()
    with pytest.raises(R.ResumeRecordError, match="df0.adf"):
        R.write(folder, _record())


def test_file_outside_the_folder_is_rejected(folder):
    record = _record()
    record["machine"]["file"] = "../state.uss"
    with pytest.raises(R.ResumeRecordError, match="not inside"):
        R.write(folder, record)


@pytest.mark.parametrize("field,value", [("format", "other"), ("version", 2), ("driver", "c64")])
def test_wrong_format_version_or_driver_fails_the_read(folder, field, value):
    path = R.write(folder, _record())
    data = json.loads(path.read_text())
    data[field] = value
    path.write_text(json.dumps(data))
    with pytest.raises(R.ResumeRecordError):
        R.read(path, "amiga")


def test_asking_for_the_other_driver_fails_the_read(folder):
    path = R.write(folder, _record())
    with pytest.raises(R.ResumeRecordError, match="amiga driver"):
        R.read(path, "c64")


def test_absent_or_unparsable_record_fails_the_read(folder):
    with pytest.raises(R.ResumeRecordError, match="does not exist"):
        R.read(folder / "resume.json", "amiga")
    (folder / "resume.json").write_text("{partial")
    with pytest.raises(R.ResumeRecordError, match="cannot be read"):
        R.read(folder / "resume.json", "amiga")


def test_first_difference():
    a = [["P", "key"], ["S", "key"], ["x", "insert"]]
    assert R.first_difference(a, [list(e) for e in a]) is None
    assert R.first_difference(a, [["P", "key"], ["Q", "key"], ["x", "insert"]]) == 2
    assert R.first_difference(a, a[:2]) == 3
    assert R.first_difference(a[:1], a) == 2
    assert R.first_difference([], []) is None


def test_check_options_names_the_first_difference():
    record = _record()
    same = dict(record["options"])
    assert R.check_options(record, same) is None
    assert R.check_options(record, {**same, "walk_retry": 2}) == "walk_retry"
    assert R.check_options(record, {**same, "no_encounters": False, "walk_retry": 2}) == "no_encounters"
    assert R.check_options(record, {**same, "preserve_specimen": True}) == "preserve_specimen"
    assert R.check_options(record, {"no_encounters": True, "encounters_on_at_miss": True}) == "walk_retry"


def test_failed_write_leaves_no_record(folder, monkeypatch):
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(R.os, "replace", boom)
    with pytest.raises(OSError):
        R.write(folder, _record())
    assert not (folder / "resume.json").exists()
    assert [p.name for p in folder.glob("resume.json*")] == []


def test_resume_exit_is_three():
    assert R.RESUME_EXIT == 3
