"""An opt-in debug log, so a bug report can carry evidence.

**Only our own process, only on request, only to a local file.** Turned on from
File > Preferences, written where you can read it before you send it, and never
transmitted anywhere. There is no telemetry, no upload and no counting of
anything -- `docs/104-debug-log.md`.

Three things make the claim checkable rather than a promise:

* the handler is attached to the ``wish`` logger and that logger does not
  propagate, so nothing any other library logs can reach the file;
* every line goes through `Scrubbed`, which rewrites absolute paths to their
  last component -- a path carries a username, and tracebacks are full of them;
* nothing is written at all while `is_on()` is false, including the file.

**The file has no preamble.** It opens on the version line, which is the field
a bug report needs; what is and is not recorded is `docs/104-debug-log.md`'s
job, not a comment block the reader has to scroll past every time.

**The log is debug mode.** `start()` turns `wish/debugmode.py` on and `stop()`
turns it off, so a user asked for a log does not also have to be told to export
a variable -- see `docs/118-debug-mode.md` for what that does and does not
reach.
"""

from __future__ import annotations

import contextlib
import datetime
import logging
import logging.handlers
import os
import pathlib
import platform
import re
import sys
import time
import traceback

from automap.paths import config_dir

from . import debugmode

NAME = "wish"

# One file per session, and the last few kept. Enough to compare "it worked
# yesterday" against today; not a diary of everything the program ever did.
KEEP = 5

# **The log has a ceiling, and it is not a matter of trust.** One file per
# session is not a bound: a session left running for weeks with the map polling
# five times a second writes until the disk is full. So each session's file
# rotates once at `MAX_BYTES` and keeps one previous part, and `KEEP` sessions
# survive -- so the whole directory cannot exceed roughly
# `KEEP * MAX_BYTES * (PARTS + 1)`, about 20 MB, whatever anybody does.
MAX_BYTES = 2_000_000
PARTS = 1


def ceiling() -> int:
    """The most the log directory can hold, in bytes. Asserted by a test."""
    return KEEP * MAX_BYTES * (PARTS + 1)

# A read that takes longer than this stalled the emulator: under VICE the
# monitor holds the CPU for the whole round trip, and the poll interval is
# 200 ms, so anything above it is visible as a stutter in the game.
SLOW_MS = 250

_logger = logging.getLogger(NAME)
_logger.propagate = False       # nothing of ours leaks into a root handler
_logger.setLevel(logging.CRITICAL + 1)

_handler: logging.Handler | None = None
_previous_hook = None
_path: pathlib.Path | None = None


# -- scrubbing ---------------------------------------------------------------

# A directory chain plus a last component: "/home/ada/src/wish/session.py" and
# r"C:\Users\Ada\wish\session.py". Only the last component survives, because
# everything before it is the part that names a person.
_POSIX = re.compile(r"/(?:[^/\s'\"<>:,]+/)+([^/\s'\"<>:,]*)")
_WINDOWS = re.compile(r"[A-Za-z]:\\(?:[^\\\s'\"<>:,]+\\)+([^\\\s'\"<>:,]*)")


def scrub(text: str) -> str:
    """Absolute paths down to their basename. Cheap, and applied to every line."""
    text = _POSIX.sub(lambda m: ".../" + m.group(1), text)
    return _WINDOWS.sub(lambda m: "...\\" + m.group(1), text)


class Scrubbed(logging.Formatter):
    """The formatter, and the last gate before anything reaches the file."""

    def format(self, record: logging.LogRecord) -> str:
        return scrub(super().format(record))


# -- where it goes -----------------------------------------------------------

def log_dir() -> pathlib.Path:
    """Beside the settings, in a directory of its own."""
    return config_dir() / "logs"


def path() -> pathlib.Path | None:
    """The file this session is writing, or None while logging is off."""
    return _path


def is_on() -> bool:
    return _handler is not None


def _prune(keep: int = KEEP) -> None:
    try:
        # `*.log*`, not `*.log`: a rotated part is `wish-....log.1`, and a
        # pruner that could not see those would leave them for ever.
        files = sorted(log_dir().glob("wish-*.log*"))
    except OSError:
        return
    for old in files[:-keep] if keep else files:
        with contextlib.suppress(OSError):
            old.unlink()


# -- turning it on and off ---------------------------------------------------

def start() -> pathlib.Path | None:
    """Open this session's file and start writing. Idempotent.

    Returns the file, or None if it could not be opened -- a read-only home is
    not a reason to take the window down.
    """
    global _handler, _path
    if _handler is not None:
        return _path
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = log_dir() / f"wish-{stamp}.log"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")   # and prove it can be written
        handler = logging.handlers.RotatingFileHandler(
            target, maxBytes=MAX_BYTES, backupCount=PARTS,
            encoding="utf-8")
    except OSError:
        return None
    handler.setFormatter(Scrubbed("%(asctime)s %(levelname)s %(message)s",
                                  datefmt="%H:%M:%S"))
    _handler, _path = handler, target
    _logger.setLevel(logging.DEBUG)
    _logger.addHandler(handler)
    debugmode.enable()
    _prune()
    note("logging on: %s", versions())
    return target


def stop() -> None:
    """Stop writing at once, and close the file. Idempotent."""
    global _handler, _path
    if _handler is None:
        return
    note("logging off")
    debugmode.disable()
    _logger.removeHandler(_handler)
    _logger.setLevel(logging.CRITICAL + 1)
    with contextlib.suppress(Exception):
        _handler.close()
    _handler, _path = None, None


# -- writing -----------------------------------------------------------------

def note(message: str, *args) -> None:
    if _handler is not None:
        _logger.info(message, *args)


def warn(message: str, *args) -> None:
    if _handler is not None:
        _logger.warning(message, *args)


def exception(message: str, *args) -> None:
    """A message and the traceback of the exception being handled.

    The one thing this feature exists for: `Session.poll` swallows anything a
    read throws to keep the window alive, and until now the traceback died with
    it.
    """
    if _handler is not None:
        _logger.error(message, *args, exc_info=True)


def crash(kind, value, tb) -> None:
    """An exception nothing caught. Always to stderr, and to the log if it is on.

    Installed as `sys.excepthook` by `install_excepthook`, which is what makes
    this reachable at all: PyQt6 aborts the process on an exception raised
    inside a slot -- `Aborted (core dumped)`, with the traceback on stderr and
    nothing anywhere else. A Windows user running the windowed build has no
    stderr to read, so the one report that mattered was the one nobody could
    send. With a hook installed Qt calls it instead of aborting, so the window
    also survives what would have killed it.
    """
    text = "".join(traceback.format_exception(kind, value, tb))
    sys.stderr.write(text)
    if _handler is not None:
        _logger.error("unhandled exception\n%s", text)


def install_excepthook() -> None:
    """Route every uncaught exception through `crash`. Idempotent.

    Called by each entry point before the window is built, and not gated on the
    log being on: keeping the application alive is worth doing either way, and
    `crash` writes to the file only when there is one.
    """
    global _previous_hook
    if _previous_hook is not None:
        return
    _previous_hook = sys.excepthook
    sys.excepthook = crash


@contextlib.contextmanager
def timed(what: str, slow_ms: int = SLOW_MS):
    """Time a block, and say so only when it was slow enough to be felt."""
    if _handler is None:
        yield
        return
    start_at = time.perf_counter()
    try:
        yield
    finally:
        ms = (time.perf_counter() - start_at) * 1000
        if ms >= slow_ms:
            warn("%s took %.0f ms (over %d ms: the emulator stalled)",
                 what, ms, slow_ms)


# -- the things worth saying -------------------------------------------------

def versions() -> str:
    """Us, Python, Qt, and the platform. No environment, no hostname."""
    try:
        # `wish.__version__`, not a metadata lookup by distribution name: the
        # distribution was once called "por-tools" and renaming it left this
        # reading "wish unknown" in every debug log, which is the one field the
        # log exists to carry. This spelling cannot go stale that way, and it
        # works in a frozen build, where there is no metadata to look up.
        from . import __version__ as ours
    except Exception:                       # pragma: no cover - defensive
        ours = "unknown"
    try:
        from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR
        qt = f"PyQt {PYQT_VERSION_STR} / Qt {QT_VERSION_STR}"
    except Exception:                       # pragma: no cover - GUI-less run
        qt = "PyQt absent"
    return (f"wish {ours}, Python {platform.python_version()}, {qt}, "
            f"{platform.system()} {platform.release()} {platform.machine()}")


def save_shape(party, file: str | os.PathLike | None = None) -> str:
    """The shape of an open save file: never a byte of its contents.

    Size, blocks, how many characters and which area -- enough to tell a save
    disk from a roster disk and to reproduce a load, and nothing that says who
    the characters are.
    """
    bits = [pathlib.Path(file).name] if file else []
    try:
        bits.append(f"{len(party.disk.to_bytes())} bytes")
        bits.append(f"{sum(e.block_count for e in party.disk.directory())} blocks")
    except Exception:
        pass
    try:
        bits.append("save disk" if party.is_save else "roster disk")
        bits.append(f"{len(party)} characters")
    except Exception:
        pass
    save0 = getattr(party, "save0", None)
    if save0 is not None:
        with contextlib.suppress(Exception):
            bits.append(f"area {save0.area_file}")
    return ", ".join(bits) or "unreadable"


def area_shape(state) -> str:
    """What the map thinks it is drawing, and how sure it is."""
    area = state.area or "unidentified"
    candidates = state.candidates
    if candidates is None:
        return area
    names = getattr(candidates, "names", []) or []
    return (f"{area} (from {candidates.source}, "
            f"{'certain' if candidates.certain else f'{len(names)} candidates'})")
