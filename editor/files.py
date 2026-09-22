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
import logging
import os
import pathlib
import shutil
import stat
import tempfile

_log = logging.getLogger("wish.editor.files")

BACKUP_DIR = "backups"
KEEP_BACKUPS = 20


class NoBackupFolder(RuntimeError):
    """Nowhere to put the copy, so the save does not happen."""


class RecoveryFailed(RuntimeError):
    """Undoing a write itself failed, so something of it is still on disk.

    `backup` is the copy of whatever was there before, when there was one,
    and `left` names every file the undo could not remove. A caller says
    where the player's own bytes are rather than claiming nothing was
    written. `editor.saveplan` re-exports this under the same name, so a
    publication and its rollback raise one class between them.
    """

    def __init__(self, message: str, backup: "pathlib.Path | None" = None,
                 left: "tuple[pathlib.Path, ...] | list[pathlib.Path]" = ()):
        self.backup = backup
        self.left = tuple(left)
        super().__init__(message)


class TargetNotEmpty(RuntimeError):
    """A save folder that already holds files, which a new save will not join.

    One folder holding two parties' files is neither of them, so a
    destination that is not empty is refused rather than mixed into.
    """


def _no_backup_folder(name: str) -> NoBackupFolder:
    """The one refusal for a write that would overwrite with nowhere to put
    the copy."""
    return NoBackupFolder(
        f"No backup folder is set, so {name} was not written. "
        "File > Preferences… to say where backups go.")


def source_folder(target: str | pathlib.Path) -> pathlib.Path:
    """The folder holding a save file, or a save folder itself.

    A DOS save is a directory of files.  Treating it as though it were one
    file puts both the next Open picker and automatic backups beside the save
    folder instead of in it.
    """
    target = pathlib.Path(target)
    return target if target.is_dir() else target.parent


def automatic_dir(target: str | pathlib.Path) -> pathlib.Path:
    """`backups/` beside the save. The answer until somebody chooses another."""
    return source_folder(target) / BACKUP_DIR


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
        return str(source_folder(current))
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
        raise _no_backup_folder(target.name)
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


def save_folder(written: dict[pathlib.Path, bytes | None],
                into: str | pathlib.Path | None) -> str:
    """Replace the changed files in one save folder, with backups.

    Each replacement is prepared and synced before any original moves.  If a
    later replacement fails, every earlier one is put back from its bytes, so
    a character's record, item and effect files do not land half-written.
    """
    changed = {pathlib.Path(path): (None if data is None else bytes(data))
               for path, data in written.items()
               if ((data is None and pathlib.Path(path).exists())
                   or (data is not None and (not pathlib.Path(path).exists()
                                            or pathlib.Path(path).read_bytes()
                                            != bytes(data))))}
    if not changed:
        return "no changes"
    first = next(iter(changed))
    if not into:
        raise _no_backup_folder(first.name)

    originals = {path: path.read_bytes() if path.exists() else None
                 for path in changed}
    temporary: dict[pathlib.Path, pathlib.Path] = {}
    try:
        for path, data in changed.items():
            if data is None:
                continue
            fd, name = tempfile.mkstemp(prefix=f".{path.name}.",
                                        dir=path.parent)
            temporary[path] = pathlib.Path(name)
            with os.fdopen(fd, "wb") as out:
                out.write(data)
                out.flush()
                os.fsync(out.fileno())
        copies = {path: back_up(path, into) for path in changed}
        replaced: list[pathlib.Path] = []
        try:
            for path in changed:
                replacement = temporary.pop(path, None)
                if replacement is None:
                    path.unlink()
                else:
                    os.replace(replacement, path)
                replaced.append(path)
        except BaseException:
            for path in reversed(replaced):
                was = originals[path]
                if was is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(was)
            raise
    finally:
        for path in temporary.values():
            path.unlink(missing_ok=True)
    copy = copies[first]
    if copy is None:
        return f"wrote {first.name}"
    if copy.parent == automatic_dir(first):
        return f"wrote {first.name}, backup {copy.parent.name}/{copy.name}"
    return f"wrote {first.name}, backup {copy}"


# ---------------------------------------------------------------------------
# Publishing a save somewhere else: a whole image, or a whole save folder
# ---------------------------------------------------------------------------

def replace_file(target: str | pathlib.Path, data: bytes,
                 into: str | pathlib.Path | None) -> pathlib.Path | None:
    """Put `data` at `target` through a temporary sibling, backing up first.

    The same two guarantees `save_disk` gives the file the editor opened, for
    a file it is writing for the first time: the replacement is written and
    fsynced beside the target and renamed over it, so an interrupted write
    leaves the original whole, and an existing target is copied into `into`
    before anything moves.

    Returns that copy, or `None` for a target that did not exist -- a new
    output has nothing to lose, so it needs no backup and an unset `into` is
    not an error for it. Overwriting with nowhere to put the copy raises
    `NoBackupFolder`, exactly as `save_disk` does.

    **A replaced file keeps the permissions it had.** `tempfile.mkstemp`
    makes its file 0600 and the rename carries that over, so replacing a
    save disk the player shares with a group would quietly make it theirs
    alone.
    """
    target = pathlib.Path(target)
    data = bytes(data)
    target.parent.mkdir(parents=True, exist_ok=True)
    copy = None
    mode = None
    if target.exists():
        if not into:
            raise _no_backup_folder(target.name)
        mode = target.stat().st_mode
        copy = back_up(target, into)
    fd, name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = pathlib.Path(name)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        if mode is not None:
            os.chmod(temporary, stat.S_IMODE(mode))
        os.replace(temporary, target)
    except BaseException:
        _log.exception("writing %s failed; %s is what it held and the "
                       "half-written copy is gone", target,
                       copy or "nothing was there")
        temporary.unlink(missing_ok=True)
        raise
    return copy


def missing_parents(target: str | pathlib.Path) -> list[pathlib.Path]:
    """The folders above `target` that do not exist yet, deepest first.

    What a write is about to create on its way to the target, so an undo can
    take exactly those away again and leave a folder that was already there.
    """
    out: list[pathlib.Path] = []
    parent = pathlib.Path(target).parent
    while not parent.exists() and parent != parent.parent:
        out.append(parent)
        parent = parent.parent
    return out


def remove_if_empty(folders: "tuple[pathlib.Path, ...] | list[pathlib.Path]"
                    ) -> list[pathlib.Path]:
    """Remove each folder that is empty, deepest first. Returns what went."""
    gone = []
    for folder in sorted(folders, key=lambda p: len(p.parts), reverse=True):
        try:
            folder.rmdir()
        except OSError:
            continue
        gone.append(folder)
    return gone


def publish_folder(target: str | pathlib.Path,
                   contents: dict[str, bytes]) -> list[pathlib.Path]:
    """Write a complete set of files into a new or empty folder.

    Every file is written and fsynced into a temporary sibling first, so a
    conversion that fails partway through producing them never reaches the
    target at all. A target that does not exist is then one rename; an empty
    one that does takes the files one at a time, which is a sequence of
    replacements rather than a transaction -- a failure part way through it
    removes the files already moved in.

    Raises `TargetNotEmpty` for a folder that already holds anything,
    `ValueError` for a name that is not a simple file name, and
    `RecoveryFailed` naming what is left when the removal after a failed move
    itself fails -- the original failure is chained to it, and a bare `OSError`
    would otherwise report the second failure and lose the first.
    """
    target = pathlib.Path(target)
    for name in contents:
        if pathlib.Path(name).name != name:
            raise ValueError(f"{name} is not a file name")
    if target.exists():
        if not target.is_dir():
            raise TargetNotEmpty(f"{target} is not a folder")
        if any(target.iterdir()):
            raise TargetNotEmpty(f"{target} already holds files")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = pathlib.Path(tempfile.mkdtemp(prefix=f".{target.name}.",
                                            dir=target.parent))
    try:
        for name, data in contents.items():
            with open(staging / name, "wb") as out:
                out.write(bytes(data))
                out.flush()
                os.fsync(out.fileno())
        if not target.exists():
            os.replace(staging, target)
            return sorted(target / name for name in contents)
        moved: list[pathlib.Path] = []
        try:
            for name in contents:
                os.replace(staging / name, target / name)
                moved.append(target / name)
        except BaseException as exc:
            _log.exception("publishing %s failed after %d file(s) moved in",
                           target, len(moved))
            left = []
            for path in moved:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    left.append(path)
            if left:
                _log.error("could not remove %s",
                           ", ".join(str(p) for p in left))
                raise RecoveryFailed(
                    f"{target} was partly written and "
                    + ", ".join(str(p) for p in left)
                    + f" could not be removed after: {exc}",
                    left=left) from exc
            raise
        return sorted(moved)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def restore_file(target: str | pathlib.Path,
                 backup: str | pathlib.Path) -> None:
    """Put a backed-up file back where it came from, through a sibling.

    The same guarantee every other write here gives: the bytes are written
    and fsynced beside the target and renamed over it, so a restore that is
    interrupted leaves the file it is repairing whole rather than half of
    each. A copy straight over the live destination is the one write in a
    publication that could destroy both the old and the new bytes at once.

    The mode and the times are copied on to the **temporary**, before the
    rename rather than after it. A `copystat` that failed afterwards would
    raise out of a restore whose bytes were already back, and the caller
    reports that as a rollback that did not happen.
    """
    target = pathlib.Path(target)
    data = pathlib.Path(backup).read_bytes()
    fd, name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = pathlib.Path(name)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        shutil.copystat(pathlib.Path(backup), temporary)
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
