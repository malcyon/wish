"""`tools/suite/datatouch.py`: the first pass records which test files reach the game data.

Every case runs a tiny generated suite as a child `pytest` with its own data
directory, reached through `$POR_DISKS` the way the real suite reaches it, so
nothing here runs the whole suite and nothing reads a game file.
"""

import os
import pathlib
import subprocess
import sys
import textwrap

import pytest

from automap import gamedisks
from tools.suite import datatouch, suiterun

REPO = pathlib.Path(__file__).resolve().parent.parent

HEAD = "import glob, os, pathlib, subprocess, sys\nimport pytest\nDATA = os.environ['POR_DISKS']\n"

# One route into the data per file. `test_arithmetic.py` reaches everything but
# the data and must stay out: a sibling whose name only begins like the data
# directory's, a file under the temp directory, and a lookup of an unset variable.
ROUTES = {
    "test_open.py": """
        def test_it():
            with open(os.path.join(DATA, "one.d64"), "rb") as f:
                f.read()
    """,
    "test_stat_only.py": """
        def test_it():
            assert pathlib.Path(DATA, "one.d64").is_file()
    """,
    "test_module_level.py": """
        HAVE = os.path.isfile(os.path.join(DATA, "one.d64"))

        @pytest.mark.skipif(not HAVE, reason="no data")
        def test_it():
            pass
    """,
    "test_fixture.py": """
        @pytest.fixture
        def image():
            return pathlib.Path(DATA, "one.d64").exists()

        def test_it(image):
            assert image
    """,
    "test_subprocess.py": """
        def test_it():
            subprocess.run([sys.executable, "-c", "pass"], check=True)
    """,
    "test_glob.py": """
        def test_it():
            assert glob.glob(os.path.join(DATA, "*.d64"))
    """,
    "test_path_glob.py": """
        def test_it():
            assert list(pathlib.Path(DATA, "absent").glob("*.d64")) == []
    """,
    "test_listdir.py": """
        def test_it():
            assert os.listdir(DATA)
    """,
    "test_inverted_gate.py": """
        @pytest.mark.skipif("POR_DISKS" in os.environ, reason="only without data")
        def test_it():
            pass
    """,
    "test_arithmetic.py": """
        def test_it(tmp_path):
            assert 1 + 1 == 2
            (tmp_path / "x").write_text("x")
            assert not os.path.exists(DATA + "-elsewhere/one.d64")
            assert os.environ.get("NOT_SET_ANYWHERE") is None
    """,
}
RECORDED = sorted(f"tests/{name}" for name in ROUTES if name != "test_arithmetic.py")


def _suite(root, routes=None):
    """A project under `root` with the data directory beside it."""
    data = root / "data"
    data.mkdir()
    (data / "one.d64").write_bytes(b"x")
    project = root / "project"
    (project / "tests").mkdir(parents=True)
    (project / "pytest.ini").write_text("[pytest]\n")
    for name, body in (routes or ROUTES).items():
        (project / "tests" / name).write_text(HEAD + textwrap.dedent(body))
    return project, data


def _child(project, data, log, *args, plugin=True):
    env = {**os.environ, "POR_DISKS": str(data), "PYTHONPATH": str(REPO),
           "QT_QPA_PLATFORM": "offscreen"}
    env.pop(datatouch.LOG_ENV, None)
    if log is not None:
        env[datatouch.LOG_ENV] = str(log)
    load = ["-p", "tools.suite.datatouch"] if plugin else []
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *load,
         *args, "tests"],
        cwd=project, env=env, capture_output=True, text=True, timeout=240)


MODES = [pytest.param(["-n0"], id="one-process"),
         pytest.param(["-n", "2", "--dist", "loadgroup"], id="two-workers")]


@pytest.mark.parametrize("mode", MODES)
def test_every_route_into_the_data_is_recorded_and_nothing_else_is(tmp_path, mode):
    project, data = _suite(tmp_path)
    log = tmp_path / "log"
    done = _child(project, data, log, *mode)
    assert done.returncode == 0, done.stdout + done.stderr
    assert datatouch.recorded(log, project) == RECORDED
    if mode[0] == "-n":
        assert len(list(log.glob("*.txt"))) >= 2, "each worker writes its own log"


def test_the_log_names_the_route_beside_each_file(tmp_path):
    project, data = _suite(tmp_path)
    log = tmp_path / "log"
    _child(project, data, log, "-n0")
    reasons = dict(line.split("\t") for line in
                   (log / next(log.iterdir()).name).read_text().splitlines())
    assert reasons["tests/test_subprocess.py"] == "subprocess.Popen"
    assert reasons["tests/test_inverted_gate.py"].startswith("setup skipped")
    assert reasons["tests/test_stat_only.py"].startswith("os.stat ")


def test_a_file_that_is_gone_is_not_recorded(tmp_path):
    project, data = _suite(tmp_path)
    log = tmp_path / "log"
    _child(project, data, log, "-n0")
    (project / "tests" / "test_open.py").unlink()
    assert "tests/test_open.py" not in datatouch.recorded(log, project)


def test_nothing_recorded_selects_nothing(tmp_path):
    assert datatouch.recorded(tmp_path / "missing", tmp_path) == []
    (tmp_path / "empty").mkdir()
    assert datatouch.recorded(tmp_path / "empty", tmp_path) == []


def test_an_ordinary_run_records_nothing_and_leaves_os_stat_alone(tmp_path):
    routes = {"test_plain.py": """
        import posix

        def test_it():
            assert os.stat is posix.stat
            assert os.path.isfile(os.path.join(DATA, "one.d64"))
    """}
    project, data = _suite(tmp_path, routes)
    log = tmp_path / "log"
    loaded_without_the_variable = _child(project, data, None, "-n0")
    assert loaded_without_the_variable.returncode == 0, loaded_without_the_variable.stdout
    not_loaded = _child(project, data, log, "-n0", plugin=False)
    assert not_loaded.returncode == 0, not_loaded.stdout
    assert not log.exists()


def test_the_recorder_watches_exactly_what_the_no_data_pass_hides(tmp_path, monkeypatch):
    """Both registry files, and every variable the example names at the path it is
    pointed at, so an entry added to the example is watched with nothing to update."""
    hidden = suiterun.no_data_env(gamedisks.EXAMPLE, tmp_path / "absent")
    expected = {str(gamedisks.REGISTRY), str(gamedisks.EXAMPLE)}
    for number, var in enumerate(hidden):
        monkeypatch.setenv(var, str(tmp_path / f"place-{number}"))
        expected.add(str(tmp_path / f"place-{number}"))
    assert set(datatouch.watched_paths()) == expected
    assert len(hidden) > 5


def test_the_examples_own_paths_are_watched_on_a_machine_with_no_registry(
        tmp_path, monkeypatch):
    """Without `gamedisks.yaml` the loader stops on any entry that has no variable,
    and the recorder must still watch the paths the example lists."""
    monkeypatch.setattr(gamedisks, "REGISTRY", tmp_path / "none.yaml")
    for var in suiterun.no_data_env(gamedisks.EXAMPLE, pathlib.Path("x")):
        monkeypatch.delenv(var, raising=False)
    watched = set(datatouch.watched_paths())
    listed = [path for row in gamedisks._load(gamedisks.EXAMPLE).values()
              for path in gamedisks._as_list(row.get(gamedisks.PATHS))]
    assert len(listed) > 5
    for path in listed:
        assert str(pathlib.Path(path).expanduser()) in watched
