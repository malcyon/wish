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

**And the folder is named, never guessed.** `save_disk` is told where the copy
goes and refuses to write when nothing was named -- there is no hidden
directory to fall back to, because the guarantee above is worth more than the
save that would have gone through without it.
"""

from __future__ import annotations

import datetime as _dt
import pathlib
import shutil

BACKUP_DIR = "backups"
KEEP_BACKUPS = 20


class NoBackupFolder(RuntimeError):
    """Nowhere to put the copy, so the save does not happen."""


def automatic_dir(target: str | pathlib.Path) -> pathlib.Path:
    """`backups/` beside the save. The answer until somebody chooses another."""
    return pathlib.Path(target).parent / BACKUP_DIR


def open_start_dir(remembered: str, current: str | pathlib.Path | None,
                    preference: str = "") -> str:
    """Where `File > Open` should start (#66).

    `preference` wins first, if the player has chosen one and it still
    exists -- a deliberate choice, so it beats even the folder beside a save
    that is already open, the same way the game disks preference in
    `automap.paths.resolve_disks` beats searching beside the open save.

    Below that, beside the currently open save if there is one -- unchanged
    from before this remembered anything. Otherwise `remembered`, the folder
    a save was last opened from, but only if it still exists: a remembered
    path always eventually hits a folder that has since been moved, renamed
    or deleted, and the fallback is to let the dialog decide for itself
    rather than open on a path that is not there. `""` is that fallback --
    what this returned for every user before there was anything to
    remember, and still what it returns with no preference set either.
    """
    preference = (preference or "").strip()
    if preference and pathlib.Path(preference).is_dir():
        return preference
    if current:
        return str(pathlib.Path(current).parent)
    remembered = (remembered or "").strip()
    if remembered and pathlib.Path(remembered).is_dir():
        return remembered
    return ""


def back_up(target: str | pathlib.Path,
            into: str | pathlib.Path) -> pathlib.Path | None:
    """Copy `target` into `into`, timestamped. None if there is nothing to copy."""
    target = pathlib.Path(target)
    if not target.exists():
        return None                      # Save As to a new name loses nothing
    stamp = _dt.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    into = pathlib.Path(into)
    into.mkdir(parents=True, exist_ok=True)
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


def save_disk(disk, target: str | pathlib.Path,
              into: str | pathlib.Path | None) -> str:
    """Write `disk` to `target`, backing up into `into` first.

    Returns what to tell the user, and raises `NoBackupFolder` rather than
    overwrite a save with nowhere to put the copy. This module's whole licence
    to write over the file you opened is that guarantee, so an unset folder
    stops the save instead of quietly costing it.

    A save that changes nothing writes nothing -- not the disk, and not a
    backup. That keeps every backup on disk corresponding to a real edit rather
    than to somebody pressing Ctrl+S out of habit, and it is why a window with
    no backup folder can still be closed without an argument.
    """
    target = pathlib.Path(target)
    new = disk.to_bytes()
    if target.exists() and target.read_bytes() == new:
        return "no changes"
    if not into:
        raise NoBackupFolder(
            f"No backup folder is set, so {target.name} was not written. "
            "File > Preferences… to say where backups go.")
    copy = back_up(target, into)
    disk.save(target)
    if copy is None:
        return f"wrote {target.name}"
    # Beside the disk, `backups/NAME` is enough -- it is the folder the user
    # was already looking at. A folder somewhere else is one they chose, and
    # naming it in full is how the message stays checkable.
    if copy.parent == automatic_dir(target):
        return f"wrote {target.name}, backup {copy.parent.name}/{copy.name}"
    return f"wrote {target.name}, backup {copy}"
