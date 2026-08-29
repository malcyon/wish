from __future__ import annotations

"""The frozen build: what each platform ships, and its entry script.

Nothing here runs PyInstaller. `wish.spec` is a Python script whose `Analysis`,
`EXE`, `PYZ` and `COLLECT` names PyInstaller injects at exec time, so the spec
can be executed against stand-ins and asked what it built -- which is enough to
catch the regression that matters, now that docs/129-one-binary.md has made it
one executable: a second one creeping back, on either platform, or the
subcommands' module falling out of the bundle.
"""

import importlib.util
import io
import pathlib
import re
import sys
import tomllib
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


def _run_spec(platform: str) -> dict[str, list[_Fake]]:
    """Execute wish.spec as PyInstaller would, on the platform named."""
    built: dict[str, list[_Fake]] = {}

    def maker(kind):
        def make(*args, **kwargs):
            built.setdefault(kind, []).append(_Fake(kind, args, kwargs))
            return built[kind][-1]
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


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_there_is_exactly_one_executable(platform):
    """One binary, and the same one on both platforms -- docs/129.

    This is the assertion the old platform split used to make in two halves:
    the Linux tarball quietly losing `wish-cli`, or the Windows zip quietly
    gaining it. There is nothing to lose or gain now, so what is left to catch
    is a second `EXE` coming back.
    """
    built = _run_spec(platform)
    assert [e.name for e in built["EXE"]] == ["wish"]
    assert len(built["Analysis"]) == 1


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_one_collect_holds_it(platform):
    """Two COLLECTs would mean two copies of Qt, ~150 MB of it."""
    built = _run_spec(platform)
    assert len(built["COLLECT"]) == 1
    collected = [a for a in built["COLLECT"][0].args if isinstance(a, _Fake)]
    assert [e.name for e in collected] == ["wish"]


def test_the_subcommands_module_is_bundled():
    """`wish export` reaches `tools.wish` through an import inside `main()`.

    PyInstaller's scan cannot see it, so it is a hidden import; without it the
    frozen `wish export` dies in `ModuleNotFoundError: tools` on a user's
    machine and the window is none the wiser.
    """
    analysis = _run_spec("linux")["Analysis"][0]
    assert "tools.wish" in analysis.kwargs["hiddenimports"]


def test_it_is_the_window_entry_script():
    assert _run_spec("linux")["Analysis"][0].args[0] == ["packaging/wish_main.py"]


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_the_window_is_windowed(platform):
    """console=False is what keeps Windows from opening one; it is deliberate.

    It costs the subcommands a terminal on Windows, which is the trade
    docs/129 makes explicitly: nobody is expected to use them there.
    """
    exe, = _run_spec(platform)["EXE"]
    assert exe.kwargs["console"] is False


# --- the one command surface ----------------------------------------------
#
# `wish --help` not mentioning `export` is half of why docs/129 merged the two
# programs at all: somebody looking for the save editor looks in the obvious
# place. These are the assertions that the obvious place keeps answering.

def test_the_two_subcommands_are_the_two_subcommands():
    from wish.__main__ import SUBCOMMANDS
    assert SUBCOMMANDS == ("export", "import")


def test_the_top_level_help_mentions_them(capsys):
    from wish.__main__ import main
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    assert "wish export" in out and "wish import" in out


def test_export_wants_a_save_disk(capsys):
    from wish.__main__ import main
    with pytest.raises(SystemExit) as exc:
        main(["export"])
    assert exc.value.code == 2
    assert "usage: wish export" in capsys.readouterr().err


def test_export_says_so_when_the_disk_is_not_there(tmp_path, capsys):
    from wish.__main__ import main
    assert main(["export", str(tmp_path / "nope.d64")]) == 2
    assert "no such save disk" in capsys.readouterr().err


def test_import_wants_somewhere_to_write(capsys):
    """`--dry-run` is the other way to satisfy it, and says nothing is written."""
    from wish.__main__ import main
    with pytest.raises(SystemExit) as exc:
        main(["import", "party.yaml"])
    assert exc.value.code == 2
    assert "-o/--output" in capsys.readouterr().err


def test_a_save_disk_called_export_is_still_openable(tmp_path, monkeypatch):
    """The whole of the resolution rule: exact match, or it is a file.

    `./export` is how docs/129 says to reach one, and it has to actually work
    -- a prefix match or a `startswith` here would swallow it.
    """
    import tools.genui
    import wish.window
    from wish.__main__ import main

    opened = []
    monkeypatch.setattr(tools.genui, "ensure_current", lambda: False)
    monkeypatch.setattr(wish.window, "run",
                        lambda save, *a, **k: (opened.append(save), 0)[1])
    (tmp_path / "export").write_bytes(b"")
    monkeypatch.chdir(tmp_path)

    assert main(["./export", "--disks", str(tmp_path)]) == 0
    assert opened == ["./export"]


# --- the distribution name ------------------------------------------------

def test_the_metadata_lookup_uses_the_distribution_name():
    """`wish` is the command; `wish-goldbox` is the distribution on PyPI.

    This has been wrong twice -- once as a leftover `por-tools`, which made
    every debug log open `wish unknown`. A pip install has only the metadata to
    ask, so a stale name here is a version of "0.0.0+unknown" for every user
    who did not get a frozen build.
    """
    with (ROOT / "pyproject.toml").open("rb") as f:
        name = tomllib.load(f)["project"]["name"]
    source = (ROOT / "wish" / "__init__.py").read_text(encoding="utf-8")
    asked = re.findall(r'\bversion\("([^"]+)"\)', source)
    assert asked == [name]


def test_the_command_is_still_wish():
    """Renaming the distribution must not rename what a user types.

    And there is exactly one name: `wish-cli`, `wish-editor` and `wish-automap`
    were dropped in docs/129, so an entry point reappearing here is a merge
    that only half happened.
    """
    with (ROOT / "pyproject.toml").open("rb") as f:
        scripts = tomllib.load(f)["project"]["scripts"]
    assert scripts == {"wish": "wish.__main__:main"}


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
