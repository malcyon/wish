"""The frozen build: what each platform ships, and its entry scripts.

Nothing here runs PyInstaller. `wish.spec` is a Python script whose `Analysis`,
`EXE`, `PYZ` and `COLLECT` names PyInstaller injects at exec time, so the spec
can be executed against stand-ins and asked what it built -- which is enough to
catch the regression that matters: the Linux tarball quietly losing `wish-cli`,
or the Windows zip quietly gaining it.
"""
from __future__ import annotations

import importlib.util
import io
import pathlib
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPEC = ROOT / "wish.spec"


class _Fake:
    """Whatever PyInstaller would have built, recorded rather than built."""

    def __init__(self, kind, args, kwargs):
        self.kind, self.args, self.kwargs = kind, args, kwargs
        self.name = kwargs.get("name")
        # COLLECT reads these off the EXEs it is given.
        self.contents_directory = "_internal"
        self.dependencies = []
        self.toc = []
        self.append_pkg = True
        # Analysis exposes these; a list is TOC-like enough for the spec.
        self.pure = []
        self.scripts = []
        self.binaries = []
        self.datas = []


def _run_spec(platform: str, pure=()) -> dict[str, list[_Fake]]:
    """Execute wish.spec as PyInstaller would, on the platform named.

    `pure` is what every `Analysis` reports having imported, for the spec's own
    check that the CLI dragged in no Qt.
    """
    built: dict[str, list[_Fake]] = {}

    def maker(kind):
        def make(*args, **kwargs):
            f = _Fake(kind, args, kwargs)
            f.pure = [(name, "somewhere.py", "PYMODULE") for name in pure]
            built.setdefault(kind, []).append(f)
            return f
        return make

    hooks = types.ModuleType("PyInstaller.utils.hooks")
    hooks.collect_submodules = lambda name: [name]
    saved = {k: sys.modules.get(k) for k in
             ("PyInstaller", "PyInstaller.utils", "PyInstaller.utils.hooks")}
    sys.modules.setdefault("PyInstaller", types.ModuleType("PyInstaller"))
    sys.modules.setdefault("PyInstaller.utils", types.ModuleType("PyInstaller.utils"))
    sys.modules["PyInstaller.utils.hooks"] = hooks

    real_platform = sys.platform
    try:
        sys.platform = platform
        env = {name: maker(name)
               for name in ("Analysis", "EXE", "PYZ", "COLLECT", "MERGE")}
        exec(compile(SPEC.read_text(encoding="utf-8"), str(SPEC), "exec"), env)
    finally:
        sys.platform = real_platform
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    return built


def test_linux_ships_the_window_and_the_cli():
    built = _run_spec("linux")
    assert [e.name for e in built["EXE"]] == ["wish", "wish-cli"]


def test_windows_ships_the_window_alone():
    # Donald: "Windows users don't need a cli. They're point and click heroes."
    built = _run_spec("win32")
    assert [e.name for e in built["EXE"]] == ["wish"]
    # And does not pay for analysing one it will not ship.
    assert len(built["Analysis"]) == 1


def test_one_collect_holds_both_executables():
    """Two COLLECTs would mean two copies of Qt, ~150 MB of it."""
    built = _run_spec("linux")
    assert len(built["COLLECT"]) == 1
    collected = [a for a in built["COLLECT"][0].args if isinstance(a, _Fake)]
    assert [e.name for e in collected] == ["wish", "wish-cli"]


def test_the_cli_is_its_own_entry_script():
    cli = _run_spec("linux")["Analysis"][1]
    assert cli.args[0] == ["packaging/wish_cli_main.py"]


def test_a_cli_that_imports_qt_fails_the_build():
    """Asserted, not excluded: an exclude defers the failure to a user's machine."""
    with pytest.raises(SystemExit, match="must not import Qt"):
        _run_spec("linux", pure=["por.d64", "PyQt6.QtWidgets"])
    # And the window, which is all Qt, is not caught by it.
    assert _run_spec("win32", pure=["PyQt6.QtWidgets"])["EXE"]


def test_the_window_is_windowed():
    """console=False is what makes the Windows build silent; it is deliberate."""
    window, cli = _run_spec("linux")["EXE"]
    assert window.kwargs["console"] is False
    assert cli.kwargs["console"] is True


# --- the entry scripts ----------------------------------------------------

def _entry(name: str):
    """Load packaging/<name>.py by path.

    Not by import: `packaging` is also an installed distribution, and this
    directory has no `__init__.py`, so importing it by name is a coin toss.
    """
    path = ROOT / "packaging" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_entry_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_entry_script_resolves():
    from tools.wish import main
    assert _entry("wish_cli_main").main is main


def test_window_entry_script_resolves():
    from wish.__main__ import main
    assert _entry("wish_main").main is main


@pytest.fixture
def entry():
    return _entry("wish_main")


def test_streams_that_exist_are_left_alone(entry, monkeypatch):
    mine = io.StringIO()
    monkeypatch.setattr(sys, "stdout", mine)
    monkeypatch.setattr(sys, "stderr", mine)
    entry._repair_streams()
    assert sys.stdout is mine and sys.stderr is mine


def test_a_none_stream_gets_the_console_when_there_is_one(
        entry, monkeypatch, tmp_path):
    """The Windows path: `wish.exe --version` typed into a terminal.

    Verified on Linux only, with the console stood in for by a file --
    `AttachConsole` and `CONOUT$` exist on no other platform.
    """
    device = tmp_path / "console"
    monkeypatch.setattr(entry, "_CONSOLE_DEVICE", str(device))
    monkeypatch.setattr(entry, "_attach_windows_console", lambda: True)
    monkeypatch.setattr(entry, "_inherited_stream", lambda fd: None)
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    entry._repair_streams()
    # Both streams go to the one console -- there is no CONERR$. A file is a
    # poor stand-in for that (two handles on a file truncate each other), so
    # this checks where each one points and writes down only one of them.
    assert sys.stdout.name == str(device)
    assert sys.stderr.name == str(device)
    print("wish 1.2.3")
    sys.stdout.flush()

    assert "wish 1.2.3" in device.read_text()


def test_without_a_console_a_redirect_still_catches_it(
        entry, monkeypatch, tmp_path):
    """`wish.exe --version > out.txt`, and every CI runner."""
    out = tmp_path / "out.txt"
    with out.open("w") as f:
        monkeypatch.setattr(entry, "_attach_windows_console", lambda: False)
        monkeypatch.setattr(entry, "_inherited_stream", lambda fd: f)
        monkeypatch.setattr(sys, "stdout", None)
        entry._repair_streams()
        print("wish 1.2.3")
        sys.stdout.flush()
    assert "wish 1.2.3" in out.read_text()


def test_a_redirect_beats_the_console(entry, monkeypatch, tmp_path):
    """`wish.exe --version > out.txt` means that file, not the terminal.

    The other order would leave the file empty and print behind the user's
    back -- and CI captures `--version` through exactly this pipe.
    """
    device = tmp_path / "console"
    out = tmp_path / "out.txt"
    monkeypatch.setattr(entry, "_CONSOLE_DEVICE", str(device))
    monkeypatch.setattr(entry, "_attach_windows_console", lambda: True)
    with out.open("w") as f:
        monkeypatch.setattr(entry, "_inherited_stream", lambda fd: f)
        monkeypatch.setattr(sys, "stdout", None)
        entry._repair_streams()
        print("wish 1.2.3")
        sys.stdout.flush()
    assert "wish 1.2.3" in out.read_text()
    assert not device.exists()


def test_with_neither_it_is_silence_and_not_a_crash(entry, monkeypatch):
    """A double-click from Explorer. argparse needs a stream, not an audience."""
    monkeypatch.setattr(entry, "_attach_windows_console", lambda: False)
    monkeypatch.setattr(entry, "_inherited_stream", lambda fd: None)
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    entry._repair_streams()
    print("swallowed")
    print("swallowed", file=sys.stderr)
    assert sys.stdout.write("swallowed") == 9


@pytest.mark.skipif(sys.platform == "win32",
                    reason="on Windows it really does borrow a console, "
                           "which is the whole point of the function")
def test_no_console_is_borrowed_off_windows(entry):
    """The ctypes call is guarded by the platform check and nothing else."""
    assert entry._attach_windows_console() is False
