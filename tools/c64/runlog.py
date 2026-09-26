"""The log and signal handling a driven run shares: a `.jsonl` beside the terminal, and a signal that unwinds the run."""
from __future__ import annotations

import json
import pathlib
import signal
import time


class Terminated(Exception):
    """SIGTERM or SIGINT arrived -- an outer `timeout` wrapper, usually."""


def _terminated(signum, frame):
    raise Terminated(f"signal {signum}")


def catch_signals() -> None:
    """Make a signal unwind the run instead of killing it where it stands.

    A `timeout 200 tools/c64/savecheck.py ...` sends SIGTERM, Python has no
    handler for it, and the process dies mid-statement: no `"failed"` entry,
    no traceback, and -- worse -- no `finally`, so VICE is left running on a
    slot the kernel has already unleased, where the next run finds it.  (The
    lease itself is an `fcntl.flock` and goes when the process does, however
    it goes -- `tools/registry/instance.py` says so; what outlives the process is the
    emulator it started.)  Raising instead means the run stops
    through its own `except`, writes what went wrong, and tears its slot
    down.  `#380` is the ticket where a lost traceback cost a repeat run.

    Best effort: `signal.signal` only works on the main thread, and a caller
    that is not on one gets the old behaviour rather than an error.
    """
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _terminated)
        except (ValueError, OSError):        # not the main thread
            pass


def keep_old_log(out: pathlib.Path) -> pathlib.Path | None:
    """Move an existing log out of the way, and say where it went.

    **A second run on the same disk used to truncate the first one's log.**
    `--out` defaults to `<disk stem>.jsonl` in the `savecheck` scratch directory, which does not
    have `--tag` in it, so two runs of the same `.d64` share one path however
    differently they are tagged.  On 2026-09-07 a failure worth diagnosing was
    photographed, logged, and then erased by the immediate retry that was
    trying to reproduce it -- the retry opens its log before it boots, so the
    evidence went minutes before the second run reached the same point
    (`#380`).  The old file is stamped with its own last-written time, so the
    name says which run it was.

    **Preserving the old log must never cost the new one.**  The file can
    vanish between the check and the stat, and the directory can be
    unwritable, and either raised from here takes the whole run down before a
    single entry is written -- which is worse than the truncation this
    exists to prevent.  So an `OSError` here gives up on keeping the old
    file and lets the caller open the path in place.
    """
    if not out.exists():
        return None
    try:
        when = time.strftime("%Y%m%d-%H%M%S",
                             time.localtime(out.stat().st_mtime))
        kept = out.with_name(f"{out.stem}-{when}{out.suffix}")
        n = 1
        while kept.exists():
            kept = out.with_name(f"{out.stem}-{when}-{n}{out.suffix}")
            n += 1
        out.rename(kept)
    except OSError:
        return None
    return kept


class Log:
    """Everything the run saw, to the terminal and to a `.jsonl` beside it.

    Nine other driven-run tools -- `tools/pool_of_radiance/fightrun.py`, `tools/pool_of_radiance/outdoorstep.py`,
    `tools/c64/c64restinterrupt.py`, `tools/pool_of_radiance/defeatdrive.py`, `tools/c64/statusdrive.py`,
    `tools/c64/hallmenu.py`, `tools/c64/turndrive.py`, `tools/c64/traitsave.py` and
    `tools/c64/traitdrive.py` -- had their own copy of this class, none of them
    hardened the way `#380 (The session driver sometimes fails BEGIN
    ADVENTURING within 0.2s of the picker loading, well inside its own 30s
    wait)` hardened this one. `#442 (Nine driven-run tools lose their log when
    the console goes, and two truncate the previous run's)` moved them onto
    this class -- either directly, or as the base of a small subclass that
    adds a `quiet` flag or a `self.dir`-relative filename of its own -- rather
    than leaving nine near-identical copies for a tenth tool to diverge from.
    """

    def __init__(self, out: pathlib.Path, append: bool = False):
        out.parent.mkdir(parents=True, exist_ok=True)
        self.dir = out.parent
        #: False once the terminal has gone, so nothing tries to talk to it
        #: again -- see `say`.
        self.talking = True
        if append:
            # `tools/c64/traitsave.py` runs `write` and then `boot` as two
            # separate invocations that deliberately share one growing
            # `traitsave.jsonl`, and `tools/c64/hallmenu.py` opens its log the
            # same way. `keep_old_log` exists to stop a second run from
            # *destroying* the first run's record -- it would be wrong here
            # too, since it would rename the shared history away on every
            # invocation instead of letting it grow.  There was never a "w"
            # here for these two to truncate.
            self.file = open(out, "a")
            return
        kept = keep_old_log(out)
        self.file = open(out, "w")
        if kept is not None:
            self.say(f"the last log at this path was kept as {kept.name}")

    def emit(self, kind: str, **kw) -> None:
        kw["kind"] = kind
        kw["t"] = round(time.time(), 3)
        self.file.write(json.dumps(kw, default=str) + "\n")
        self.file.flush()

    def say(self, *a) -> None:
        """The terminal half, and it must never be able to stop the run.

        A driven run is usually started as `... | head -40` or through a
        harness that stops reading, and `print` to a pipe nobody is reading
        any more raises `BrokenPipeError`.  Raised out of the failure handler
        it takes the rest of the handler with it, which leaves behind exactly
        what `#380` left behind: the screenshot, the `"failure_screen"` entry
        that comes before the first `say`, and no `"failed"` entry at all.
        The `.jsonl` is the record; the console is a convenience, and a
        convenience that has gone away is not a reason to lose the record.
        """
        if self.talking:
            try:
                print(*a, flush=True)
            except OSError:
                self.talking = False
                try:
                    self.emit("console_closed")
                except OSError:
                    # The record itself has gone -- a full disk, a closed
                    # descriptor.  Nothing here can report that, and raising
                    # it out of a failure handler is what lost the traceback
                    # this whole change exists to keep.
                    pass

    def close(self) -> None:
        self.file.close()
