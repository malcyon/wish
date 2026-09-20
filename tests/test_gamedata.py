from __future__ import annotations

"""`tests/gamedata.py` finds Curse's disks through the registry alone, and a
machine that keeps its own `gamedisks.yaml` fails, rather than skips, when the
registry cannot say where a title's disks are.

CI has no `gamedisks.yaml`: `tests/conftest.py` swaps the example in there, and
the tests that need disks must keep skipping.
"""

import os
import subprocess
import sys

import pytest
import yaml
from gamedata import (
    CURSE_KEY,
    _blank_disk,
    curse_absent,
    curse_dir,
    curse_disks,
    has_own_registry,
    npc_party_disk,
    require_registered,
)
from support import titletables as test_titletables
from support.silverblades import SSB_KEY, ssb_dir, ssb_disks

from automap import gamedisks
from goldbox import c64_port

TITLE_KEYS = [g.key for g in c64_port.GAMES] + ["npc-party-save"]
ENTRY_KEYS = list(gamedisks._example())

POOL_ONLY = """\
pool-of-radiance:
  env: POR_DISKS
  glob: ["POOL*.D64"]
  paths: []
"""


@pytest.fixture(autouse=True)
def _fresh_lookup():
    _clear_caches()
    yield
    _clear_caches()


def _clear_caches():
    curse_dir.cache_clear()
    ssb_dir.cache_clear()
    test_titletables._champions_side_a.cache_clear()
    test_titletables._death_knights_side.cache_clear()


def test_a_registry_with_no_curse_entry_fails_the_lookup(own_registry):
    own_registry(POOL_ONLY)
    with pytest.raises(gamedisks.RegistryError) as stopped:
        curse_dir()
    message = str(stopped.value)
    assert CURSE_KEY in message and "gamedisks.yaml" in message


def test_an_entry_naming_a_directory_that_is_not_there_fails_the_lookup(
        own_registry, tmp_path):
    gone = tmp_path / "no-such-folder"
    own_registry(f"{CURSE_KEY}:\n  env: COAB_DISKS\n"
                 f"  glob: [\"CURSE*.D64\"]\n  paths: [\"{gone.as_posix()}\"]\n")
    with pytest.raises(gamedisks.RegistryError) as stopped:
        curse_dir()
    assert f"add one under `{CURSE_KEY}:`" in str(stopped.value)


def test_curse_disks_fail_the_same_way(own_registry):
    own_registry(POOL_ONLY)
    with pytest.raises(gamedisks.RegistryError):
        curse_disks()


def test_the_home_folder_is_not_searched_for_curse_disks(
        own_registry, tmp_path, monkeypatch):
    """A rip unpacked under `~/c64/All Games` is not found unless the registry
    names it."""
    decoy = tmp_path / "c64" / "All Games" / "Any Name At All"
    decoy.mkdir(parents=True)
    (decoy / "CURSE1.D64").write_bytes(b"")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    own_registry(POOL_ONLY)
    with pytest.raises(gamedisks.RegistryError):
        curse_dir()


def test_the_lookup_finds_a_directory_the_registry_names(own_registry, tmp_path):
    (tmp_path / "curse").mkdir()
    (tmp_path / "curse" / "CURSE1.D64").write_bytes(b"")
    own_registry(f"{CURSE_KEY}:\n  env: COAB_DISKS\n"
                 f"  glob: [\"CURSE*.D64\"]\n"
                 f"  paths: [\"{(tmp_path / 'curse').as_posix()}\"]\n")
    assert curse_dir() == tmp_path / "curse"


def test_a_machine_with_no_registry_gets_none_and_the_tests_skip(no_registry):
    assert curse_dir() is None
    with pytest.raises(pytest.skip.Exception):
        curse_disks()


def test_the_example_replacing_a_missing_registry_gets_none(
        example_registry):
    """What CI has: `tests/conftest.py` points the loader at the example, whose
    paths are not on the machine."""
    assert curse_dir() is None
    with pytest.raises(pytest.skip.Exception):
        curse_disks()


def test_the_marker_skips_only_where_there_is_no_registry_to_blame(
        own_registry, example_registry):
    """With the example in place of the registry the marker skips; with a registry of the
    machine's own that lacks the title it does not, so the test runs and reaches
    the failure."""
    assert curse_absent() is True
    curse_dir.cache_clear()
    own_registry(POOL_ONLY)
    assert curse_absent() is False


def _run_pytest(tmp_path, registry_text, *args):
    """Run pytest in a child whose registry is `registry_text` and whose
    `$..._DISKS` variables are unset, so nothing on this machine answers for an
    entry the text leaves out."""
    registry = tmp_path / "gamedisks.yaml"
    registry.write_text(registry_text, encoding="utf-8")
    driver = (
        "import pathlib, sys\n"
        "from automap import gamedisks\n"
        "gamedisks.REGISTRY = pathlib.Path(sys.argv[1])\n"
        "import pytest\n"
        "sys.exit(pytest.main(['-q', '-n0', '-p', 'no:cacheprovider']\n"
        "                     + sys.argv[2:]))\n")
    variables = {row.get(gamedisks.ENV)
                 for row in gamedisks._example().values()}
    env = {k: v for k, v in os.environ.items() if k not in variables}
    return subprocess.run([sys.executable, "-c", driver, str(registry), *args],
                          cwd=gamedisks.REPO, env=env, capture_output=True,
                          text=True, timeout=240)


def test_collecting_every_test_survives_a_registry_that_finds_nothing(tmp_path):
    """`RegistryError` is a `SystemExit`, so one raised while a test module is
    imported aborts collection for the whole run with `INTERNALERROR` and no test
    executes. The lookup has to happen when a test runs, where the error fails
    that test alone -- for every title, so the whole tree is collected."""
    done = _run_pytest(tmp_path, POOL_ONLY, "--collect-only", "tests")
    assert done.returncode == 0 and "INTERNALERROR" not in done.stdout, (
        done.stdout[-1500:] + done.stderr[-1500:])


@pytest.mark.parametrize("key", ENTRY_KEYS)
def test_the_registry_says_where_each_entrys_disks_are(key):
    """On a machine with its own `gamedisks.yaml`, an entry that leads nowhere
    fails here, naming the entry, rather than turning every test that reads it
    into a skip. Every entry of the example is checked, the ones that are not
    titles included."""
    if not has_own_registry():
        pytest.skip("this machine keeps no gamedisks.yaml of its own")
    require_registered(key)


def test_the_guard_covers_every_entry_of_the_example():
    """The guard's parameters are read from the example when the module is
    collected; this reads the file again, so an entry added to it and somehow
    left out of the guard is a failure."""
    with gamedisks.EXAMPLE.open(encoding="utf-8") as f:
        listed = list(yaml.safe_load(f))
    assert listed, "the example lists no entries"
    marks = [m for m in
             test_the_registry_says_where_each_entrys_disks_are.pytestmark
             if m.name == "parametrize"]
    assert [list(m.args[1]) for m in marks] == [listed]
    assert set(TITLE_KEYS) <= set(listed)


@pytest.mark.parametrize("key", TITLE_KEYS)
def test_the_guard_names_a_missing_entry_for_every_title(own_registry, key):
    own_registry(POOL_ONLY)
    with pytest.raises(gamedisks.RegistryError) as stopped:
        require_registered(key)
    assert key in str(stopped.value)


@pytest.mark.parametrize("registry", ["example_registry", "no_registry"])
@pytest.mark.parametrize("key", TITLE_KEYS)
def test_the_guard_stays_quiet_where_there_is_no_registry_of_the_machines_own(
        request, registry, key):
    request.getfixturevalue(registry)
    assert not has_own_registry()
    require_registered(key)


def test_the_guard_test_fails_rather_than_aborting_the_run(tmp_path):
    done = _run_pytest(
        tmp_path, POOL_ONLY, "tests/test_gamedata.py", "-k",
        "test_the_registry_says_where_each_entrys_disks_are")
    out = done.stdout
    assert done.returncode == 1 and "INTERNALERROR" not in out, (
        out[-1500:] + done.stderr[-1500:])
    for key in TITLE_KEYS:
        assert f"a directory holding {key}'s disks" in out, key


def test_an_entry_whose_paths_do_not_exist_fails_with_the_one_sentence(
        own_registry, tmp_path):
    gone = tmp_path / "no-such-folder"
    own_registry(f"{CURSE_KEY}:\n  env: COAB_DISKS\n"
                 f"  glob: [\"CURSE*.D64\"]\n  paths: [\"{gone.as_posix()}\"]\n")
    with pytest.raises(gamedisks.RegistryError) as stopped:
        require_registered(CURSE_KEY)
    assert str(stopped.value) == (
        f"gamedisks.yaml does not list a directory holding {CURSE_KEY}'s "
        f"disks: add one under `{CURSE_KEY}:`.")


def test_a_byte_for_byte_copy_of_the_example_is_a_registry(own_registry):
    """Path identity is the whole test: the copy's entries are present and a
    path in it that is not on the machine fails as a missing path, with no
    special case for an unedited file."""
    own_registry(gamedisks.EXAMPLE.read_text(encoding="utf-8"))
    assert has_own_registry()
    assert gamedisks.names() == ENTRY_KEYS
    missing = [k for k in ENTRY_KEYS if gamedisks.find(k) is None]
    for key in missing:
        with pytest.raises(gamedisks.RegistryError, match="add one under"):
            require_registered(key)


def _registry_error_from(lookup):
    """The `RegistryError` a lookup raises. A skip counts as a failure here,
    because the lookup must raise."""
    try:
        lookup()
    except pytest.skip.Exception:
        pytest.fail(f"{lookup.__name__} skipped instead of naming the entry")
    except gamedisks.RegistryError as stopped:
        return str(stopped)
    pytest.fail(f"{lookup.__name__} raised nothing")


def test_a_registry_with_no_npc_party_entry_fails_the_lookup(own_registry):
    own_registry(POOL_ONLY)
    assert "npc-party-save" in _registry_error_from(npc_party_disk)


def test_a_machine_with_no_registry_gets_no_npc_party_disk(no_registry):
    assert npc_party_disk() is None


def test_a_registry_with_no_silver_blades_entry_fails_every_lookup(own_registry):
    own_registry(POOL_ONLY)
    for lookup in (ssb_dir, ssb_disks, test_titletables.silver_blades_disk):
        assert SSB_KEY in _registry_error_from(lookup)


@pytest.mark.parametrize("finder, key", [
    (test_titletables.champions_disk, "champions-of-krynn"),
    (test_titletables.death_knights_disk, "death-knights-of-krynn"),
])
def test_a_registry_with_no_krynn_entry_fails_the_finder(own_registry, finder,
                                                         key):
    own_registry(POOL_ONLY)
    assert key in _registry_error_from(finder)


def test_a_krynn_folder_with_no_itemnames_side_still_skips(own_registry,
                                                           tmp_path):
    """The entry leads somewhere, so the registry is not to blame: the rip
    lacks the side the tests read."""
    (tmp_path / "krynn").mkdir()
    (tmp_path / "krynn" / "SIDE.d64").write_bytes(_blank_disk())
    where = (tmp_path / "krynn").as_posix()
    own_registry(
        "champions-of-krynn:\n  env: COK_DISKS\n  glob: [\"*.d64\"]\n"
        f"  paths: [\"{where}\"]\n"
        "death-knights-of-krynn:\n  env: DKK_DISKS\n  glob: [\"*.d64\"]\n"
        f"  paths: [\"{where}\"]\n")
    for finder in (test_titletables.champions_disk,
                   test_titletables.death_knights_disk):
        with pytest.raises(pytest.skip.Exception):
            finder()
