"""A disk-reading tool with no disks stops with a message instead of scanning
the directory it happens to be run from.

Each tool is imported afresh with no `$POR_DISKS`, no registry and an empty
home, so its module-level disk constant is the one a machine without disks
produces. `tool_disks` looks in `$POR_DISKS` first, then in the search, and
answers `None` when neither finds anything.
"""
from __future__ import annotations

import ast
import importlib
import pathlib
import signal
import sys
import threading
import types

import pytest

from automap import paths

pytestmark = pytest.mark.usefixtures("no_registry")

NO_DISKS = "No game disks found. Set $POR_DISKS."


@pytest.fixture(autouse=True)
def _nowhere(monkeypatch, tmp_path):
    """No variable, no registry, a home with nothing in it, and a working
    directory that `disk_candidates()` will search and find empty."""
    monkeypatch.delenv("POR_DISKS", raising=False)
    monkeypatch.setattr(paths, "_home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def fresh(monkeypatch):
    """Import modules again, so their module-level disk constant is computed
    under the isolation above, and put the originals back afterwards."""

    def load(*dotted):
        for name in dotted:
            pkg, leaf = name.rsplit(".", 1)
            package = importlib.import_module(pkg)
            importlib.import_module(name)
            monkeypatch.setattr(package, leaf, getattr(package, leaf))
            monkeypatch.delitem(sys.modules, name, raising=False)
        return [importlib.import_module(name) for name in dotted]

    return load


# -- the lookup ----------------------------------------------------------------


def test_tool_disks_is_none_when_nothing_answers():
    assert paths.tool_disks() is None


def test_tool_disks_takes_the_variable_at_its_word(monkeypatch, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("POR_DISKS", str(empty))
    assert paths.tool_disks() == pathlib.Path(empty)


def test_tool_disks_ignores_an_empty_variable(monkeypatch):
    monkeypatch.setenv("POR_DISKS", "")
    assert paths.tool_disks() is None


def test_tool_disks_falls_back_to_the_search(monkeypatch, tmp_path):
    found = tmp_path / "PoR"
    found.mkdir()
    (found / "POOL1.D64").write_bytes(b"")
    assert paths.tool_disks() == found


def test_tool_disks_calls_find_disks_by_its_module_name(monkeypatch, tmp_path):
    """A test that patches `paths.find_disks` has to reach it."""
    monkeypatch.setattr(paths, "find_disks", lambda game=None: tmp_path / "x")
    assert paths.tool_disks() == tmp_path / "x"


# -- the guard, for the tools that read the disks ------------------------------


def test_the_constant_is_none_with_no_disks(fresh):
    (walk,) = fresh("tools.areas.eclwalk")
    assert walk.DISKS is None


def test_eclwalk_stops_with_no_disks(fresh, monkeypatch):
    (walk,) = fresh("tools.areas.eclwalk")
    monkeypatch.setattr(sys, "argv", ["eclwalk.py", "list"])
    with pytest.raises(SystemExit) as stopped:
        walk.main()
    assert str(stopped.value) == NO_DISKS


def test_exitroute_stops_with_no_disks(fresh):
    _, route = fresh("tools.areas.eclwalk", "tools.areas.exitroute")
    with pytest.raises(SystemExit) as stopped:
        route.main(["ECL07", "A904"])
    assert str(stopped.value) == NO_DISKS


def test_genexits_stops_with_no_disks(fresh):
    _, gen = fresh("tools.areas.eclwalk", "tools.generate.genexits")
    with pytest.raises(SystemExit) as stopped:
        gen.build()
    assert str(stopped.value) == NO_DISKS


# -- an explicit --disks reaches the staging, and an empty one is no disks -----


def _stub_session(monkeypatch, module, staged):
    """Replace everything in `module` that launches or stages, and record the
    disk folder `stage_disks` is given. `Session.boot` fails, which stops the
    run straight after staging."""
    slot = types.SimpleNamespace(
        n=99, display=99, dir="", teardown=lambda: None, release=lambda: None)

    class Session:
        def __init__(self, *a, **k):
            pass

        def boot(self):
            return False

        def terminate(self):
            pass

    monkeypatch.setattr(module.S, "claim_slot", lambda *a, **k: slot)
    monkeypatch.setattr(module.S, "stage_disks",
                        lambda slot, disks, *a, **k: staged.append(disks))
    monkeypatch.setattr(module.S, "stage_writable", lambda *a, **k: None)
    monkeypatch.setattr(module.S, "Session", Session)
    return slot


def test_wallpins_stages_the_disks_it_was_given(fresh, monkeypatch, tmp_path):
    (pins,) = fresh("tools.areas.wallpins")
    staged = []
    slot = _stub_session(monkeypatch, pins, staged)
    slot.dir = str(tmp_path / "slot")
    (tmp_path / "slot").mkdir()
    given = tmp_path / "disks"
    given.mkdir()
    with pytest.raises(RuntimeError, match="Boot failed"):
        pins.main(["--disks", str(given), "--out", str(tmp_path / "out")])
    assert staged == [given]


def test_wallpins_stops_with_no_disks(fresh, monkeypatch):
    (pins,) = fresh("tools.areas.wallpins")
    _stub_session(monkeypatch, pins, [])  # a missing guard must not claim a pool slot
    with pytest.raises(SystemExit) as stopped:
        pins.main([])
    assert str(stopped.value) == NO_DISKS


def test_fasttravelrun_stops_with_an_empty_disks_argument(fresh, monkeypatch):
    (run,) = fresh("tools.areas.fasttravelrun")
    _stub_session(monkeypatch, run, [])  # a missing guard must not claim a pool slot
    with pytest.raises(SystemExit) as stopped:
        run.main(["--disks", ""])
    assert str(stopped.value) == NO_DISKS


def test_fasttravelrun_stops_with_no_disks(fresh, monkeypatch):
    (run,) = fresh("tools.areas.fasttravelrun")
    _stub_session(monkeypatch, run, [])  # a missing guard must not claim a pool slot
    with pytest.raises(SystemExit) as stopped:
        run.main([])
    assert str(stopped.value) == NO_DISKS


# -- no tool builds a disk folder that can be the current directory ------------

TOOLS_DIR = pathlib.Path(__file__).resolve().parents[2] / "tools"

#: The lookups that answer `None` when there are no disks.
_LOOKUPS = frozenset({"find_disks", "tool_disks"})


def _last_name(func: ast.expr) -> str | None:
    """`f` for `f(...)`, and `f` for `a.b.f(...)`."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _is_lookup(node: ast.expr) -> bool:
    return isinstance(node, ast.Call) and _last_name(node.func) in _LOOKUPS


def _holds_lookup(node: ast.expr) -> bool:
    """The node is a lookup call, or an `or`/`and` chain with one among its
    operands. A lookup nested inside some other call is not counted: what that
    call does with the `None` is its own business."""
    if isinstance(node, ast.BoolOp):
        return any(_holds_lookup(v) for v in node.values)
    return _is_lookup(node)


def _ends_in_empty_string(node: ast.expr) -> bool:
    return (isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or)
            and isinstance(node.values[-1], ast.Constant)
            and node.values[-1].value == "")


def _is_string_or_path_call(node: ast.Call, *, path_only: bool) -> bool:
    """`Path(x)`, `pathlib.Path(x)` or `_p.Path(x)`, and `str(x)` unless
    `path_only`, each with exactly one positional argument."""
    if len(node.args) != 1 or node.keywords:
        return False
    name = _last_name(node.func)
    if name == "Path":
        return True
    return not path_only and name == "str" and isinstance(node.func, ast.Name)


def bad_disk_folders(source: str) -> list[tuple[int, str]]:
    """Line and reason for every expression in `source` that turns "no disks"
    into the current directory or into the text `None`."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.BoolOp) and _ends_in_empty_string(node)
                and any(_is_lookup(v) for v in node.values[:-1])):
            found.append((node.lineno, "a disk lookup `or` an empty string"))
        if isinstance(node, ast.Call):
            if (_is_string_or_path_call(node, path_only=False)
                    and _holds_lookup(node.args[0])):
                found.append((node.lineno, "a disk lookup, which may be "
                              "`None`, turned into a string or a Path"))
            if (_is_string_or_path_call(node, path_only=True)
                    and _ends_in_empty_string(node.args[0])):
                found.append((node.lineno, "a Path built from a value that "
                              "falls back to an empty string"))
    return sorted(set(found))


def scan_tools(root: pathlib.Path) -> tuple[int, list[str]]:
    """How many files under `root` were read, and `file:line: reason` for each
    bad disk folder in them. Nothing is imported or run."""
    files = sorted(root.rglob("*.py"))
    hits = []
    for path in files:
        for line, reason in bad_disk_folders(path.read_text(encoding="utf-8")):
            hits.append(f"{path.relative_to(root).as_posix()}:{line}: {reason}")
    return len(files), hits


def test_no_tool_builds_a_disk_folder_that_can_be_the_current_directory():
    scanned, hits = scan_tools(TOOLS_DIR)
    assert scanned > 100, f"only {scanned} files scanned under {TOOLS_DIR}"
    assert not hits, (
        f"{len(hits)} disk folders that turn no disks into `Path(\"\")`, "
        f"which is the current directory, or into `None` as text; use "
        f"`automap.paths.tool_disks()` and check for `None`:\n"
        + "\n".join(hits))


@pytest.mark.parametrize("source", [
    "root = os.environ.get('POR_DISKS') or find_disks() or ''",
    "root = paths.find_disks() or ''",
    "root = args.disks or tool_disks() or \"\"",
    "root = str(find_disks())",
    "root = str(paths.find_disks())",
    "root = pathlib.Path(find_disks())",
    "root = _p.Path(tool_disks())",
    "root = Path(args.disks or find_disks())",
    "root = str(args.disks or tool_disks() or '')",
    "root = Path(args.disks or '')",
    "root = pathlib.Path(os.environ.get('POR_DISKS') or '')",
    "def f():\n    return Path(args.disks or tool_disks())",
])
def test_the_sweep_reports_each_forbidden_form(source):
    assert bad_disk_folders(source)


@pytest.mark.parametrize("source", [
    "root = tool_disks()",
    "root = args.disks or tool_disks()",
    "root = find_disks()\nif root is None:\n    raise SystemExit('none')\n"
    "root = str(root)",
    "root = str(root)",
    "root = pathlib.Path(args.disks)",
    "root = Path(found)",
    "name = str(os.environ.get('USER') or '')",
    "name = os.environ.get('POR_DISKS') or ''",
    "root = str(resolve(find_disks()))",
    "root = find_disks() or fallback",
    "root = str(find_disks(), 'utf-8')",
])
def test_the_sweep_leaves_the_correct_forms_alone(source):
    assert bad_disk_folders(source) == []


# -- tools that read the disks from an option, a title variable or the registry -

CURSE_DISKS = "no Curse disks; pass --disks"


def _nothing_launches(monkeypatch):
    """Everything that claims a slot, stages disks, starts an emulator or a
    child process raises, so a missing guard shows up as the claim it made."""

    def refuse(what):
        def raiser(*a, **k):
            raise AssertionError(f"{what} was reached with no disks")
        return raiser

    # `ssbrun` subclasses `Session` when it is first imported, so it comes
    # before the stubs replace `Session` with a function.
    importlib.import_module("tools.secret_of_the_silver_blades.ssbrun")
    from tools.c64 import session as por
    from tools.curse_of_the_azure_bonds import curserun

    for owner, names in ((por, ("claim_slot", "stage_disks", "stage_writable",
                                "Session")),
                         (curserun, ("stage", "CurseSession"))):
        for name in names:
            monkeypatch.setattr(owner, name, refuse(f"{owner.__name__}.{name}"))
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", refuse("subprocess.Popen"))


@pytest.fixture
def no_title_disks(monkeypatch):
    for var in ("COAB_DISKS", "SSB_DISKS", "POR_DISKS"):
        monkeypatch.delenv(var, raising=False)
    _nothing_launches(monkeypatch)
    # `c64addprobe.main` installs its own SIGTERM and SIGINT handlers and
    # never puts the old ones back.
    saved = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    yield
    if threading.current_thread() is threading.main_thread():
        for sig, handler in saved.items():
            signal.signal(sig, handler)


@pytest.mark.parametrize("module, argv, message", [
    ("tools.c64.c64addprobe", ["--save", "SAVE.D64"], "no Curse disks found; pass --disks"),
    ("tools.c64.c64addchar", [], NO_DISKS),
    ("tools.c64.c64strength", ["--cha", "X.CHA"], NO_DISKS),
    ("tools.c64.splatload", ["--save", "SAVE.D64"], NO_DISKS),
    ("tools.curse_of_the_azure_bonds.cursepaladin", ["run", "--save", "S.D64"],
     CURSE_DISKS),
    ("tools.curse_of_the_azure_bonds.cursetrain", ["run", "--save", "S.D64"],
     CURSE_DISKS),
    ("tools.secret_of_the_silver_blades.ssbtrain", ["run", "--save", "S.D64"],
     "no Silver Blades disks: set $SSB_DISKS or pass --disks"),
    ("tools.curse_of_the_azure_bonds.curseload", ["--save", "S.D64"], CURSE_DISKS),
    ("tools.curse_of_the_azure_bonds.curseareazero", [], CURSE_DISKS),
    ("tools.c64.dualclassagain", ["c64", "--save", "S.D64"],
     "no disks for curse-of-the-azure-bonds; pass --disks"),
])
def test_a_tool_with_a_title_lookup_stops_with_no_disks(
        no_title_disks, fresh, module, argv, message):
    (tool,) = fresh(module)
    with pytest.raises(SystemExit) as stopped:
        tool.main(argv)
    assert str(stopped.value) == message


@pytest.mark.parametrize("module, argv", [
    ("tools.c64.c64addprobe", ["--save", "SAVE.D64"]),
    ("tools.c64.c64addchar", []),
    ("tools.c64.c64strength", ["--cha", "X.CHA"]),
    ("tools.c64.splatload", ["--save", "SAVE.D64"]),
    ("tools.curse_of_the_azure_bonds.cursepaladin", ["run", "--save", "S.D64"]),
    ("tools.curse_of_the_azure_bonds.cursetrain", ["run", "--save", "S.D64"]),
    ("tools.curse_of_the_azure_bonds.curseload", ["--save", "S.D64"]),
    ("tools.curse_of_the_azure_bonds.curseareazero", []),
    ("tools.c64.dualclassagain", ["c64", "--save", "S.D64"]),
])
def test_a_given_disks_folder_gets_past_the_guard(
        no_title_disks, fresh, monkeypatch, tmp_path, module, argv):
    """With `--disks DIR` the tool goes on to the slot claim, which the stubs
    turn into an error of their own."""
    (tool,) = fresh(module)
    given = tmp_path / "disks"
    given.mkdir()
    with pytest.raises(AssertionError, match="was reached with no disks"):
        tool.main([*argv, "--disks", str(given), "--out", str(tmp_path / "out")])
