"""Opening and saving, and not losing anybody's save disk.

The editor writes back over the file you opened -- no forced new filename. That
is the opposite of the CLI, which refuses to overwrite its input, and it is only
defensible because of the two guarantees here.

**Atomic.** `D64.save` writes a temporary beside the target, fsyncs it and
renames over, so an interrupted save leaves the original untouched.

**Backed up, every time.** Before each overwrite the current file is copied to a
timestamped backup. Not one `.bak` overwritten each save: a bad edit is often
not noticed until the game is booted, by which point a one-deep backup would
already hold the damage.
"""

from __future__ import annotations

import datetime as _dt
import pathlib
import shutil

BACKUP_DIR = "backups"
KEEP_BACKUPS = 20
FALLBACK = pathlib.Path.home() / ".local/share/wish/backups"


def backup_dir_for(target: pathlib.Path) -> pathlib.Path:
    """Beside the save if we may write there, else under the user's data dir."""
    beside = target.parent / BACKUP_DIR
    try:
        beside.mkdir(parents=True, exist_ok=True)
        probe = beside / ".writable"
        probe.touch()
        probe.unlink()
        return beside
    except OSError:
        FALLBACK.mkdir(parents=True, exist_ok=True)
        return FALLBACK


def back_up(target: str | pathlib.Path) -> pathlib.Path | None:
    """Copy `target` aside, timestamped. None if there is nothing to copy."""
    target = pathlib.Path(target)
    if not target.exists():
        return None                      # Save As to a new name loses nothing
    stamp = _dt.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    into = backup_dir_for(target)
    copy = into / f"{target.name}.{stamp}"
    n = 1
    while copy.exists():                 # two saves inside one second
        copy = into / f"{target.name}.{stamp}.{n}"
        n += 1
    shutil.copy2(target, copy)
    prune(target, into)
    return copy


def prune(target: pathlib.Path, into: pathlib.Path,
          keep: int = KEEP_BACKUPS) -> list[pathlib.Path]:
    """Drop the oldest backups of one file, keeping the newest `keep`."""
    ours = sorted(into.glob(f"{target.name}.*"))
    dropped = ours[:-keep] if len(ours) > keep else []
    for old in dropped:
        old.unlink(missing_ok=True)
    return dropped


def save_disk(disk, target: str | pathlib.Path) -> str:
    """Write `disk` to `target`, backing up first. Returns what to tell the user.

    A save that changes nothing writes nothing -- not the disk, and not a
    backup. That keeps every backup on disk corresponding to a real edit rather
    than to somebody pressing Ctrl+S out of habit.
    """
    target = pathlib.Path(target)
    new = disk.to_bytes()
    if target.exists() and target.read_bytes() == new:
        return "no changes"
    copy = back_up(target)
    disk.save(target)
    if copy is None:
        return f"wrote {target.name}"
    return f"wrote {target.name}, backup {copy.parent.name}/{copy.name}"
