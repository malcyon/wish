from __future__ import annotations

"""`automap/gamedisks.py`, the one registry #212 asked for.

Two layers, and the point of the module is their precedence: `$<env>` wins
outright and is taken whole, and `gamedisks.yaml` -- gitignored, one machine's
own, the only file the loader reads -- is the search list. `gamedisks.yaml.example`
is committed and is the whole registry. Every test here points `REGISTRY` at a
file under `tmp_path`, so nothing depends on this machine's `gamedisks.yaml`
except the tests that read the example.
"""


import ast
import json
import pathlib
import sys

import pytest
import yaml

import automap
from automap import gamedisks, paths
from goldbox import c64_port

REPO = pathlib.Path(__file__).resolve().parent.parent


def _write(path: pathlib.Path, text: str) -> pathlib.Path:
    path.write_text(text)
    return path


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """An isolated `gamedisks.yaml`."""
    registry_file = _write(tmp_path / "gamedisks.yaml", """
a-game:
  env: A_GAME_DISKS
  glob: ["A*.d64"]
  paths:
    - committed-one
    - committed-two
no-default:
  env: NO_DEFAULT_DISKS
""")
    monkeypatch.setattr(gamedisks, "REGISTRY", registry_file)
    monkeypatch.delenv("A_GAME_DISKS", raising=False)
    monkeypatch.delenv("NO_DEFAULT_DISKS", raising=False)
    # A row the machine's file lacks comes from the example, whose env name
    # is `POR_DISKS`; a shell that exports it would win over the paths.
    monkeypatch.delenv("POR_DISKS", raising=False)
    # The entries above use relative names, the way a real rip's directory
    # name is relative to wherever it was found -- `is_dir()` checks them
    # against the process's own working directory, so tests that create one
    # of those directories need to be standing here when they check it.
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_names_lists_every_entry(registry):
    assert gamedisks.names() == ["a-game", "no-default"]


def test_with_nothing_set_the_paths_are_tried_in_order(registry):
    assert gamedisks.candidates("a-game") == [
        pathlib.Path("committed-one"), pathlib.Path("committed-two")]


def test_an_entry_with_no_paths_has_no_candidates(registry):
    assert gamedisks.candidates("no-default") == []


def test_an_unknown_entry_has_no_candidates(registry):
    assert gamedisks.candidates("nothing-registered-under-this-name") == []


def test_the_environment_variable_wins_outright_and_is_taken_whole(
        registry, monkeypatch):
    monkeypatch.setenv("A_GAME_DISKS", "/wherever/the/player/put/it")
    assert gamedisks.candidates("a-game") == [
        pathlib.Path("/wherever/the/player/put/it")]


def test_a_path_named_twice_appears_once(registry):
    _write(registry / "gamedisks.yaml", """
a-game:
  paths: [one, two, one]
""")
    assert gamedisks.candidates("a-game") == [
        pathlib.Path("one"), pathlib.Path("two")]


def test_home_expands_in_every_candidate(registry):
    _write(registry / "gamedisks.yaml", """
a-game:
  env: A_GAME_DISKS
  paths: ["~/somewhere"]
""")
    assert gamedisks.candidates("a-game") == [
        pathlib.Path.home() / "somewhere"]


def test_a_missing_registry_stops_with_one_line_naming_the_example(
        tmp_path, monkeypatch):
    """Copying the example is the whole setup, so that is what the message
    says. A `SystemExit`, so a tool stops with the line and no traceback."""
    monkeypatch.setattr(gamedisks, "REGISTRY", tmp_path / "gamedisks.yaml")
    monkeypatch.delenv("POR_DISKS", raising=False)
    with pytest.raises(gamedisks.RegistryMissing) as raised:
        gamedisks.find("pool-of-radiance")
    message = str(raised.value)
    assert "\n" not in message
    assert "gamedisks.yaml.example" in message


def test_an_empty_registry_has_no_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(gamedisks, "REGISTRY",
                        _write(tmp_path / "gamedisks.yaml", "# nothing yet\n"))
    assert gamedisks.names() == []


def test_the_environment_variable_works_with_no_registry_at_all(
        tmp_path, monkeypatch):
    """`POR_DISKS=/where tools/generate/genitems.py` on a checkout that has not copied
    the example yet: the variable's name comes from the example, and the run
    goes ahead rather than stopping at the missing file."""
    (tmp_path / "POOL1.D64").write_bytes(b"")
    monkeypatch.setattr(gamedisks, "REGISTRY", tmp_path / "gamedisks.yaml")
    monkeypatch.setenv("POR_DISKS", str(tmp_path))
    assert gamedisks.find("pool-of-radiance") == tmp_path


def test_an_entry_the_machines_file_lacks_takes_the_examples_row(registry):
    """A `gamedisks.yaml` copied before an entry was added keeps working."""
    assert gamedisks.candidates("pool-of-radiance") == [
        pathlib.Path("/data/agent-disks/pool-of-radiance")]


def test_where_is_never_none_and_never_an_index_error(registry):
    assert gamedisks.where("no-default") == pathlib.Path(
        "/data/agent-disks/no-default")
    assert gamedisks.where("a-game") == pathlib.Path("committed-one")


def test_a_hand_edited_string_is_one_path_not_a_list_of_letters(registry):
    _write(registry / "gamedisks.yaml", """
a-game:
  glob: "A*.d64"
  paths: /one/path
""")
    assert gamedisks.candidates("a-game") == [pathlib.Path("/one/path")]
    assert gamedisks._globs("a-game") == ["A*.d64"]


def test_a_registry_that_is_not_a_mapping_stops_with_one_line(registry):
    _write(registry / "gamedisks.yaml", "- just\n- a list\n")
    with pytest.raises(gamedisks.RegistryError) as raised:
        gamedisks.names()
    assert "\n" not in str(raised.value)


# -- find(), and both directions it has to prove ------------------------------

def test_find_returns_the_first_candidate_that_actually_matches(registry):
    disks = registry / "committed-two"
    disks.mkdir()
    (disks / "A1.d64").write_bytes(b"")
    assert gamedisks.find("a-game") == pathlib.Path("committed-two")


def test_find_is_none_when_no_candidate_exists(registry):
    assert gamedisks.find("a-game") is None


def test_pointed_at_an_empty_directory_find_is_still_none(registry,
                                                          monkeypatch):
    """The registry's other half of #211's proof: a directory that exists but
    holds nothing does not count as found."""
    empty = registry / "empty"
    empty.mkdir()
    monkeypatch.setenv("A_GAME_DISKS", str(empty))
    assert gamedisks.find("a-game") is None


def _no_glob_entry(registry):
    _write(registry / "gamedisks.yaml", """
a-game:
  paths: ["a-directory"]
""")
    directory = registry / "a-directory"
    directory.mkdir()
    return directory


def test_an_entry_with_no_glob_needs_a_directory_with_something_in_it(registry):
    """`dos-archives` names a directory, not a file, so any content will do."""
    directory = _no_glob_entry(registry)
    (directory / "anything.txt").write_bytes(b"")
    assert gamedisks.find("a-game") == pathlib.Path("a-directory")


def test_an_empty_directory_is_not_found_when_the_entry_has_no_glob(registry):
    """16 empty entry directories sat under /data/agent-disks, `dos-archives`
    matched one, and its tests stopped with `SystemExit` instead of skipping."""
    _no_glob_entry(registry)
    assert gamedisks.find("a-game") is None
    assert gamedisks.report()[0][-1] is False


def test_an_empty_directory_is_not_found_when_the_entry_has_a_glob(registry):
    (registry / "committed-one").mkdir()
    assert gamedisks.find("a-game") is None


def test_a_directory_with_a_matching_file_is_found(registry):
    disks = registry / "committed-one"
    disks.mkdir()
    (disks / "A1.d64").write_bytes(b"")
    assert gamedisks.find("a-game") == pathlib.Path("committed-one")


def test_a_directory_with_only_non_matching_files_is_not_found(registry):
    disks = registry / "committed-one"
    disks.mkdir()
    (disks / "B1.d64").write_bytes(b"")
    (disks / "A1.txt").write_bytes(b"")
    assert gamedisks.find("a-game") is None


# -- report() ------------------------------------------------------------------

def test_report_names_the_environment_variable_as_the_layer(registry,
                                                             monkeypatch):
    (registry / "A1.d64").write_bytes(b"")
    monkeypatch.setenv("A_GAME_DISKS", str(registry))
    rows = {name: row for name, *row in gamedisks.report()}
    assert rows["a-game"][1] == "$A_GAME_DISKS"
    assert rows["a-game"][3] is True


def test_report_says_none_when_nothing_resolves(registry):
    rows = {name: row for name, *row in gamedisks.report()}
    assert rows["no-default"][1] == "none"
    assert rows["no-default"][3] is False


def test_report_names_the_registry_file_as_the_layer(registry):
    disks = registry / "committed-two"
    disks.mkdir()
    (disks / "A1.d64").write_bytes(b"")
    rows = {name: row for name, *row in gamedisks.report()}
    assert rows["a-game"][1] == "gamedisks.yaml"
    assert rows["a-game"][3] is True


# -- the example this project actually ships -----------------------------------

def _example() -> dict:
    return yaml.safe_load(gamedisks.EXAMPLE.read_text(encoding="utf-8"))


def test_the_example_is_the_whole_registry():
    """Every entry has its variable, and an example path under
    `/data/agent-disks/<entry>` where `<entry>` is the entry's own name, so the
    file and the directory describe each other."""
    example = _example()
    assert example, "gamedisks.yaml.example has no entries"
    wrong = [name for name, row in example.items()
             if not row.get(gamedisks.ENV)
             or f"/data/agent-disks/{name}" not in (row.get(gamedisks.PATHS)
                                                    or [])]
    assert wrong == []


def test_the_example_says_what_every_entry_is():
    """The comment above each entry's keys is the documentation: a machine
    filling this in reads it to know what to put there."""
    lines = gamedisks.EXAMPLE.read_text(encoding="utf-8").splitlines()
    bare = []
    for n, line in enumerate(lines):
        if line and not line.startswith((" ", "#")) and line.endswith(":"):
            block = lines[n + 1:n + 2]
            if not (block and block[0].lstrip().startswith("#")):
                bare.append(line.rstrip(":"))
    # The three C64 title entries carry their comment too; none may be bare.
    assert bare == []


def test_this_machines_registry_only_names_entries_the_example_has():
    """`gamedisks.yaml` is gitignored, so this is the one place a stale copy
    (an entry renamed in the example) is caught. Skips where there is none:
    CI, and any checkout that has not copied the example yet."""
    if not gamedisks.REGISTRY.is_file():
        pytest.skip("no gamedisks.yaml on this machine; copy the example")
    unknown = set(gamedisks.names()) - set(_example())
    assert unknown == set()


def test_the_shipped_loader_imports_nothing_from_tools():
    """`automap` ships and `tools/` does not, so the loader `automap.paths`
    reaches for cannot depend on anything under `tools/`. Checked by AST: a
    root module name is not enough, since the import that matters is
    `from tools.registry import x`."""
    tree = ast.parse((REPO / "automap" / "gamedisks.py").read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append("." * node.level + (node.module or ""))
    assert [m for m in imported if m == "tools" or m.startswith("tools.")] == []


def test_the_loader_has_no_candidates_and_does_not_raise_with_no_files_at_all(
        tmp_path, monkeypatch):
    """An installed copy has neither `gamedisks.yaml` nor the example."""
    monkeypatch.setattr(gamedisks, "REGISTRY", tmp_path / "gamedisks.yaml")
    monkeypatch.setattr(gamedisks, "EXAMPLE", tmp_path / "gamedisks.yaml.example")
    monkeypatch.delenv("POR_DISKS", raising=False)
    assert gamedisks.names() == []
    assert gamedisks.candidates("pool-of-radiance") == []
    assert gamedisks.find("pool-of-radiance") is None


# -- `automap.paths.disk_candidates` ------------------------------------------

def _guesses(game, home, cwd) -> list[pathlib.Path]:
    """The home-folder guesses `disk_candidates` made before it read the
    registry, spelt out again so a change to them shows up here."""
    roots = [cwd, home, home / "Documents", home / "Games",
             home / "c64", home / "roms", home / "Downloads"]
    out = [r / n for r in roots for n in paths._dir_names(game)]
    return out + [cwd, home]


@pytest.fixture
def searching(tmp_path, monkeypatch):
    """A home folder and working directory of their own, no `$POR_DISKS`, and
    no registry file or example."""
    home = tmp_path / "home"
    home.mkdir()
    work = tmp_path / "startdir"
    work.mkdir()
    monkeypatch.setattr(paths, "_home", lambda: home)
    monkeypatch.chdir(work)
    monkeypatch.delenv("POR_DISKS", raising=False)
    monkeypatch.delenv("COAB_DISKS", raising=False)
    monkeypatch.setattr(gamedisks, "REGISTRY", tmp_path / "gamedisks.yaml")
    monkeypatch.setattr(gamedisks, "EXAMPLE", tmp_path / "gamedisks.yaml.example")
    return home, work.resolve(), tmp_path


def _flow(*where: pathlib.Path) -> str:
    """A YAML flow list of paths. JSON quoting doubles a Windows backslash, so
    `C:\\Users\\...` is not read as an escape sequence."""
    return json.dumps([str(p) for p in where])


def _register(tmp_path, monkeypatch, text: str) -> None:
    monkeypatch.setattr(gamedisks, "REGISTRY", _write(tmp_path / "reg.yaml", text))


def test_the_registrys_directories_come_before_the_home_folder_guesses(
        searching, monkeypatch):
    home, work, tmp = searching
    _register(tmp, monkeypatch, f"""
pool-of-radiance:
  env: POR_DISKS
  paths: {_flow(tmp / 'one', tmp / 'two')}
curse-of-the-azure-bonds:
  env: COAB_DISKS
  paths: {_flow(tmp / 'curse')}
""")
    got = paths.disk_candidates()
    assert got[:2] == [tmp / "one", tmp / "two"]
    assert got[2:] == _guesses(None, home, work)
    curse = paths.disk_candidates(c64_port.CURSE_OF_THE_AZURE_BONDS)
    assert curse[0] == tmp / "curse"
    assert tmp / "one" not in curse


def test_with_no_registry_the_guesses_are_unchanged(searching):
    home, work, _ = searching
    assert paths.disk_candidates() == _guesses(None, home, work)
    game = c64_port.CURSE_OF_THE_AZURE_BONDS
    assert paths.disk_candidates(game) == _guesses(game, home, work)


def test_por_disks_still_wins_over_the_registry(searching, monkeypatch):
    _, _, tmp = searching
    _register(tmp, monkeypatch, f"""
pool-of-radiance:
  env: POR_DISKS
  paths: {_flow(tmp / 'one')}
""")
    monkeypatch.setenv("POR_DISKS", str(tmp / "mine"))
    assert paths.disk_candidates() == [tmp / "mine"]


def test_a_registry_that_lacks_the_title_gives_the_guesses(searching, monkeypatch):
    home, work, tmp = searching
    _register(tmp, monkeypatch, """
some-other-game:
  paths: ["/nowhere"]
""")
    assert paths.disk_candidates() == _guesses(None, home, work)


@pytest.mark.parametrize("body", [
    "pool-of-radiance: [not, a, mapping]\n",
    "pool-of-radiance:\n  paths: 5\n",
    "pool-of-radiance: just text\n",
    "[not, a, mapping]\n",
    "pool-of-radiance: {paths: [: :\n",
], ids=["list", "paths-an-int", "string", "top-level-list", "not-yaml"])
def test_a_malformed_registry_gives_the_guesses(searching, monkeypatch, body):
    home, work, tmp = searching
    _register(tmp, monkeypatch, body)
    assert paths.disk_candidates() == _guesses(None, home, work)


def test_a_missing_registry_file_with_the_example_present_gives_the_guesses(
        searching, monkeypatch):
    """The loader's own stop for a missing `gamedisks.yaml` is a `SystemExit`,
    which `except Exception` would let through to the player."""
    home, work, tmp = searching
    _write(tmp / "gamedisks.yaml.example",
           "pool-of-radiance:\n  paths: [/from/the/example]\n")
    assert not gamedisks.REGISTRY.exists()
    assert paths.disk_candidates() == _guesses(None, home, work)


def test_a_machine_without_the_yaml_module_gives_the_guesses(
        searching, monkeypatch):
    home, work, tmp = searching
    _register(tmp, monkeypatch, f"""
pool-of-radiance:
  paths: {_flow(tmp / 'one')}
""")
    monkeypatch.delitem(sys.modules, "automap.gamedisks")
    monkeypatch.delattr(automap, "gamedisks")
    monkeypatch.setitem(sys.modules, "yaml", None)
    assert paths.disk_candidates() == _guesses(None, home, work)


def test_no_example_path_points_into_the_repository():
    """A default inside the checkout is scratch or a gitignored copy, and stops
    resolving the day somebody clears it -- which is how
    `tests/test_silverblades.py`'s old in-tree entry went missing."""
    offenders = [(name, raw)
                 for name, row in _example().items()
                 for raw in row.get(gamedisks.PATHS) or []
                 if REPO in [pathlib.Path(raw).expanduser(),
                             *pathlib.Path(raw).expanduser().parents]]
    assert offenders == []
