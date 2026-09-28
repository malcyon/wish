"""The repository's pytest configuration removes a passing test's ``tmp_path``.

The Amiga acceptance tests write about 12 MB of floppy images each, and a
retained directory per test fills a shared tmpfs; only a failed test's
directory is worth keeping. The child run reads the policy from the repo's own
``pyproject.toml`` rather than naming it on its command line.
"""

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


def test_only_a_failed_tests_tmp_path_survives_the_run(tmp_path):
    probe_dir = tmp_path / "probe"
    probe_dir.mkdir()
    probe = probe_dir / "test_probe.py"
    probe.write_text(PROBE)
    base = tmp_path / "base"

    result = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            "-c", str(REPO / "pyproject.toml"),
            "--rootdir", str(REPO),
            "-q", "-n0", "-p", "no:cacheprovider",
            f"--basetemp={base}",
            str(probe),
        ],
        capture_output=True, text=True, timeout=300,
    )

    assert "1 failed, 1 passed" in result.stdout, result.stdout + result.stderr
    # pytest also leaves a `<name>current` symlink per test; only real
    # directories hold a test's files.
    kept = sorted(p.name for p in base.iterdir() if not p.is_symlink())
    assert kept == ["test_fails0"], kept
