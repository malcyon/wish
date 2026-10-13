"""The repository's pytest configuration removes a passing test's ``tmp_path``.

The Amiga acceptance tests write about 12 MB of floppy images each, and a
retained directory per test fills a shared tmpfs; only a failed test's
directory is kept. The child run reads the policy from the repo's own
``pyproject.toml`` rather than naming it on its command line.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

PROBE = '''
def test_passes(tmp_path):
    (tmp_path / "kept.bin").write_bytes(b"x" * 1024)


def test_fails(tmp_path):
    (tmp_path / "kept.bin").write_bytes(b"x" * 1024)
    assert False, "fails on purpose so its directory is retained"
'''


# Records every path pytest offers for collection, so the test can check the
# run never looked outside its own probe folder.
COLLECT_LOG_PLUGIN = '''
import os

# Created on import so a run that offers no path still leaves an empty log.
open(os.environ["COLLECT_LOG"], "a").close()


def pytest_ignore_collect(collection_path):
    with open(os.environ["COLLECT_LOG"], "a") as log:
        log.write(str(collection_path) + "\\n")
'''


def test_only_a_failed_tests_tmp_path_survives_the_run(tmp_path):
    probe_dir = tmp_path / "probe"
    probe_dir.mkdir()
    probe = probe_dir / "test_probe.py"
    probe.write_text(PROBE)
    base = tmp_path / "base"
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    (plugin_dir / "collectlog.py").write_text(COLLECT_LOG_PLUGIN)
    visited = tmp_path / "visited.txt"
    env = dict(os.environ, COLLECT_LOG=str(visited))
    env["PYTHONPATH"] = os.pathsep.join(
        [str(plugin_dir)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
    )

    result = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            "-c", str(REPO / "pyproject.toml"),
            "--rootdir", str(REPO),
            "-q", "-n0", "-p", "no:cacheprovider",
            "-p", "collectlog",
            f"--basetemp={base}",
            # Starts collection at the probe folder instead of at the
            # filesystem root, so the shared pytest-of-<user> folder is
            # never scanned.
            f"--confcutdir={probe_dir}",
            str(probe),
        ],
        capture_output=True, text=True, timeout=300, env=env,
    )

    assert "1 failed, 1 passed" in result.stdout, result.stdout + result.stderr
    # Collection that starts above the probe folder scans the shared
    # pytest-of-<user> folder, where another run's cleanup can delete an entry
    # mid-scan.
    outside = [
        line for line in visited.read_text().splitlines()
        if Path(line) != probe_dir and probe_dir not in Path(line).parents
    ]
    assert not outside, outside
    # pytest also leaves a `<name>current` symlink per test; only real
    # directories hold a test's files.
    kept = sorted(p.name for p in base.iterdir() if not p.is_symlink())
    assert kept == ["test_fails0"], kept
