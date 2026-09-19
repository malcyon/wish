"""Pytest plugin that records which test files reach the game data.

`tools/suite/suiterun.py` loads it into the first pass with `-p tools.suite.datatouch`
and reads what it wrote to choose the files the no-data pass runs: a file that
never looked at the data cannot behave differently without it. An ordinary
`pytest` never loads it, and loaded without `$WISH_DATA_TOUCH_LOG` it does nothing.

A test file is marked when, while one of its modules is being imported or one of
its tests is being set up, run or torn down, the process

* opens, lists, scans, walks or globs a path under a watched path, or stats one
  (`os.stat`, `os.lstat` and `os.access` are wrapped, because CPython raises no
  audit event for them and `Path.is_file()` reaches the registry that way);
* starts a child process, which inherits the environment and cannot be watched
  from here, so any test that starts one is marked whatever the child does;
* or has a test that did not pass, because a gate that skips with the data
  present and runs without it is the mirror image of the usual one.

The watched paths are everything the no-data pass hides, read from
`automap.gamedisks` when the run starts, so nothing here names a path and the two
cannot drift apart. A recorder that cannot start, a log that cannot be written
(a `<pid>.failed` marker is left beside the logs, best effort) and a log that
cannot be read all leave no selection, and `suiterun.py` falls back to the
source scan.

**This is a known limit, not a guarantee that no file is missed.** Routes that
are not recorded, and can therefore leave a file out of the selection:

* a `spawn` or `forkserver` multiprocessing child, which is a new interpreter
  that never loads this plugin (a `fork` child is not one: `os.fork` marks its
  parent's file);
* a path that reaches the data through a symlink, because the match is on the
  text of the path and its `realpath` at start, not on what the kernel resolves;
* a thread that outlives its test, whose reads land on whichever file runs next
  or on none;
* file loading done in Qt's C++, which raises no audit event.

Each process writes `<$WISH_DATA_TOUCH_LOG>/<pid>.txt`, one `path<TAB>reason`
line per marked file, so xdist workers never interleave a write.
"""

from __future__ import annotations

import functools
import os
import pathlib
import sys

try:
    import pytest
except ImportError:
    # `suiterun.py` imports this module for `LOG_ENV` and `recorded` and may run
    # under an interpreter with no pytest; only the plugin hooks need it.
    pytest = None

LOG_ENV = "WISH_DATA_TOUCH_LOG"

# `open` covers `io.open`, `os.open` and every reader built on them.
_PATH_EVENTS = frozenset({
    "open", "os.listdir", "os.scandir", "os.walk", "glob.glob",
    "pathlib.Path.glob", "pathlib.Path.rglob",
})
_CHILD_EVENTS = frozenset({
    "subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn",
    "os.fork", "os.forkpty",
})
_WRAPPED = ("stat", "lstat", "access")
_SUPPORT_TABLES = ("supports_dir_fd", "supports_follow_symlinks",
                   "supports_effective_ids")

# Module state, not a class, because the audit hook and the `os` wrappers run on
# every event in the process and read `_current` first.
_current: str | None = None
_marks: dict[str, str] = {}
_log_dir: pathlib.Path | None = None
_exact: frozenset[str] = frozenset()
_prefixes: tuple[str, ...] = ()
_hook_added = False
_originals: dict[str, object] = {}
_wrappers: dict[str, object] = {}


def watched_paths() -> list[str]:
    """Every path the no-data pass hides: both registry files and every
    candidate location of every entry in either of them."""
    import yaml

    from automap import gamedisks

    names: dict[str, None] = {}
    for source in (gamedisks.REGISTRY, gamedisks.EXAMPLE):
        if source.is_file():
            loaded = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
            names.update(dict.fromkeys(loaded))
    paths: dict[str, None] = {str(gamedisks.REGISTRY): None,
                              str(gamedisks.EXAMPLE): None}
    for name in names:
        try:
            found = gamedisks.candidates(name)
        except gamedisks.RegistryError:
            # No registry and no variable for this entry: the lookup itself
            # would stop, so the example's own paths are the ones to watch.
            row = (yaml.safe_load(gamedisks.EXAMPLE.read_text(encoding="utf-8"))
                   or {}).get(name) or {}
            raw = row.get(gamedisks.PATHS) or []
            found = [pathlib.Path(p).expanduser()
                     for p in ([raw] if isinstance(raw, str) else raw)]
        paths.update(dict.fromkeys(str(path) for path in found))
    return list(paths)


def recorded(log_dir: pathlib.Path, worktree: pathlib.Path) -> list[str]:
    """The test files the logs in `log_dir` name, as posix paths under `tests/`
    that exist in `worktree`, sorted; `[]` when there is nothing to read.

    Any process that failed to write its log, or any log that cannot be read or
    decoded, makes the whole selection `[]`: a partial selection would run fewer
    files than the run needs."""
    found: set[str] = set()
    try:
        directory = pathlib.Path(log_dir)
        if any(directory.glob("*.failed")):
            return []
        for log in directory.glob("*.txt"):
            for line in log.read_text(encoding="utf-8").splitlines():
                path = line.partition("\t")[0]
                if path.startswith("tests/") and (worktree / path).is_file():
                    found.add(path)
    except (OSError, ValueError):
        return []
    return sorted(found)


def _leave_failure_marker(directory: pathlib.Path) -> None:
    """Best effort: without a marker, a process that recorded nothing looks like
    one with nothing to record."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{os.getpid()}.failed").write_text("", encoding="utf-8")
    except Exception:
        pass


def _watched_text(arg: object) -> str | None:
    """`arg` as an absolute path when it is under a watched path, else None."""
    if not isinstance(arg, (str, bytes, os.PathLike)):
        return None
    text = os.fsdecode(arg)
    if not text:
        return None
    if not os.path.isabs(text):
        text = os.path.abspath(text)
    if ".." in text:
        text = os.path.normpath(text)
    if text in _exact or text.startswith(_prefixes):
        return text
    return None


def _mark(file: str, reason: str) -> None:
    if file not in _marks:
        _marks[file] = " ".join(reason.split())


def _consider(event: str, args: tuple) -> None:
    file = _current
    if file is None:
        return
    try:
        for arg in args:
            text = _watched_text(arg)
            if text is not None:
                _mark(file, f"{event} {text}")
                return
    except Exception:
        # Raising from an audit hook or a wrapped `os` function would change
        # what the test under observation does.
        pass


def _audit(event: str, args: tuple) -> None:
    if _current is None:
        return
    if event in _CHILD_EVENTS:
        _mark(_current, event)
    elif event in _PATH_EVENTS:
        _consider(event, args)


def _watching(real, event: str):
    @functools.wraps(real)
    def wrapper(path, *args, **kwargs):
        if _current is not None:
            _consider(f"os.{event}", (path,))
        return real(path, *args, **kwargs)
    return wrapper


def _install(watched: list[str]) -> None:
    global _exact, _prefixes, _hook_added
    every = set(watched)
    for path in watched:
        every.add(os.path.realpath(path))
    _exact = frozenset(every)
    _prefixes = tuple(path.rstrip(os.sep) + os.sep for path in every)
    for name in _WRAPPED:
        real = getattr(os, name)
        wrapper = _watching(real, name)
        _originals[name], _wrappers[name] = real, wrapper
        # `shutil` and `os.makedirs` ask these sets whether a function may be
        # given a file descriptor or `follow_symlinks`, by identity.
        for table in _SUPPORT_TABLES:
            if real in getattr(os, table):
                getattr(os, table).add(wrapper)
        setattr(os, name, wrapper)
    if not _hook_added:
        sys.addaudithook(_audit)
        _hook_added = True


def _uninstall() -> None:
    for name, real in _originals.items():
        wrapper = _wrappers[name]
        if getattr(os, name) is wrapper:
            setattr(os, name, real)
        for table in _SUPPORT_TABLES:
            getattr(os, table).discard(wrapper)
    _originals.clear()
    _wrappers.clear()


def pytest_configure(config) -> None:
    global _log_dir
    raw = os.environ.get(LOG_ENV)
    if not raw:
        return
    try:
        _install(watched_paths())
        _log_dir = pathlib.Path(raw)
    except Exception:
        # A recorder that cannot start records nothing, and the marker keeps the
        # other workers' logs from standing for the whole run.
        _uninstall()
        _log_dir = None
        _leave_failure_marker(pathlib.Path(raw))


def pytest_unconfigure(config) -> None:
    global _log_dir
    _uninstall()
    _log_dir = None


def _hookwrapper(function):
    return pytest.hookimpl(hookwrapper=True)(function) if pytest else function


@_hookwrapper
def pytest_make_collect_report(collector):
    """Importing a test module is where a module-level `skipif` asks the registry."""
    global _current
    if _log_dir is None or not isinstance(collector, pytest.Module):
        yield
        return
    previous, _current = _current, collector.nodeid
    try:
        yield
    finally:
        _current = previous


@_hookwrapper
def pytest_runtest_protocol(item, nextitem):
    """Setup, call and teardown, so a fixture's reads land on the test that wanted it."""
    global _current
    if _log_dir is None:
        yield
        return
    _current = item.nodeid.split("::")[0]
    try:
        yield
    finally:
        _current = None


def _mark_unless_passed(report) -> None:
    if _log_dir is not None and report.outcome != "passed":
        _mark(report.nodeid.split("::")[0],
              f"{getattr(report, 'when', 'collect')} {report.outcome}")


def pytest_runtest_logreport(report) -> None:
    _mark_unless_passed(report)


def pytest_collectreport(report) -> None:
    _mark_unless_passed(report)


def pytest_sessionfinish(session) -> None:
    global _current
    _current = None
    if _log_dir is None:
        return
    try:
        _log_dir.mkdir(parents=True, exist_ok=True)
        lines = [f"{file}\t{reason}" for file, reason in sorted(_marks.items())]
        (_log_dir / f"{os.getpid()}.txt").write_text(
            "".join(line + "\n" for line in lines), encoding="utf-8")
    except Exception:
        _leave_failure_marker(_log_dir)
