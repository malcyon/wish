"""The record an acceptance driver leaves when it stops on a screen it does not recognise.

A driver writes one folder per stop holding the saved machine, its disks and
`resume.json`; a later run reads it back and checks its own inputs against it
before touching an emulator. Any mapping in the record with a `file` key names
a file relative to the folder, and `write` fills in that file's `sha256` and
`bytes`. The record is written last and atomically, so a missing `resume.json`
means there is nothing to resume. The `manifest` and `screen` hashes are
compared by the driver, not by `read`. A C64 record passes a constant `command`,
since that driver has no subcommand.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import tempfile

FORMAT = "wish-acceptance-resume"
VERSION = 1

#: Exit status a driver returns when it stopped with a record that can be resumed.
RESUME_EXIT = 3

RECORD_NAME = "resume.json"

#: Fields every record carries, whichever driver wrote it.
REQUIRED = ("driver", "argv", "command", "title", "step", "sent", "machine", "disks", "options")


class ResumeRecordError(Exception):
    """The record is missing, damaged, for another driver, or its files changed."""


def sha256_file(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_entries(node):
    if isinstance(node, dict):
        if "file" in node:
            yield node
        for value in node.values():
            yield from _file_entries(value)
    elif isinstance(node, list):
        for value in node:
            yield from _file_entries(value)


def _resolve(folder: pathlib.Path, name: str) -> pathlib.Path:
    if not isinstance(name, str) or not name:
        raise ResumeRecordError(f"file {name!r} is not a file name")
    # Both flavours are checked: a record written on one platform is read on another.
    for flavour in (pathlib.PurePosixPath, pathlib.PureWindowsPath):
        path = flavour(name)
        if path.is_absolute() or path.drive or path.root or ".." in path.parts:
            raise ResumeRecordError(f"file {name!r} is not inside the record folder")
    return folder / pathlib.PurePosixPath(name)


def _require(record: dict, where) -> None:
    missing = [key for key in REQUIRED if key not in record]
    if missing:
        raise ResumeRecordError(f"{where} lacks {', '.join(missing)}")


def write(folder, record: dict) -> pathlib.Path:
    """Hash every file the record lists, then write `resume.json` atomically."""
    folder = pathlib.Path(folder)
    record = json.loads(json.dumps(record))
    _require(record, "the record")
    record["format"] = FORMAT
    record["version"] = VERSION
    for entry in _file_entries(record):
        path = _resolve(folder, entry["file"])
        if not path.is_file():
            raise ResumeRecordError(f"{entry['file']} is not in {folder}")
        entry["sha256"] = sha256_file(path)
        entry["bytes"] = path.stat().st_size
    target = folder / RECORD_NAME
    fd, temp = tempfile.mkstemp(dir=folder, prefix=RECORD_NAME + ".", suffix=".part")
    try:
        try:
            handle = os.fdopen(fd, "w", encoding="utf-8")
        except BaseException:
            os.close(fd)
            raise
        with handle:
            json.dump(record, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    except BaseException:
        if os.path.exists(temp):
            os.unlink(temp)
        raise
    return target


def read(path, driver: str) -> dict:
    """Load a record and check its format, version, driver, required fields and every file's size and hash."""
    path = pathlib.Path(path)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ResumeRecordError(f"{path} does not exist") from None
    except (OSError, ValueError) as exc:
        raise ResumeRecordError(f"{path} cannot be read: {exc}") from None
    if not isinstance(record, dict) or record.get("format") != FORMAT:
        raise ResumeRecordError(f"{path} is not a {FORMAT} record")
    if record.get("version") != VERSION:
        raise ResumeRecordError(f"{path} is version {record.get('version')}, not {VERSION}")
    if record.get("driver") != driver:
        raise ResumeRecordError(f"{path} was written by the {record.get('driver')} driver, not {driver}")
    _require(record, path)
    for entry in _file_entries(record):
        target = _resolve(path.parent, entry["file"])
        if not target.is_file():
            raise ResumeRecordError(f"{entry['file']} is missing from {path.parent}")
        if entry.get("bytes") != target.stat().st_size:
            raise ResumeRecordError(f"{entry['file']} does not match its recorded size")
        if sha256_file(target) != entry.get("sha256"):
            raise ResumeRecordError(f"{entry['file']} does not match its recorded SHA-256")
    return record


def first_difference(recorded, current):
    """The 1-based index of the first unequal entry, or None when the lists are equal.

    A list that is a prefix of the other differs at the first entry past the
    shorter one.
    """
    recorded, current = list(recorded), list(current)
    for index, (a, b) in enumerate(zip(recorded, current), start=1):
        if a != b:
            return index
    if len(recorded) != len(current):
        return min(len(recorded), len(current)) + 1
    return None


def check_options(record: dict, current: dict):
    """The name of the first option whose value differs from the record's, or None.

    Options are compared in sorted order; an option present on one side only
    differs.
    """
    recorded = record.get("options", {})
    for name in sorted(set(recorded) | set(current)):
        if recorded.get(name, object()) != current.get(name, object()):
            return name
    return None
