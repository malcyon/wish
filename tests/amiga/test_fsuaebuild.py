"""The FS-UAE fork build applies `tools/amiga/fsuae-*.patch` before it compiles.

Without `fsuae-inputcode-null.patch` the fork's Linux build segfaults on every
state save, state load and reset, because each is queued with a NULL string
that `strdup` is handed. The container build cannot run here, so these tests
run the build scripts' own patch step, cut out of each script, against a tiny
tree that holds only the lines the patch touches: the step must apply the
patch, skip it on a second run, and stop on a tree it does not fit.
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
AMIGA = ROOT / "tools" / "amiga"
PATCH = AMIGA / "fsuae-inputcode-null.patch"
SCRIPTS = [AMIGA / "fsuaebuildcontainer.sh", AMIGA / "fsuaebuildclang.sh"]
GUARD = "inputcode_pending[i].s = s ? my_strdup(s) : NULL;"
UNGUARDED = "inputcode_pending[i].s = my_strdup(s);"

needs_patch = pytest.mark.skipif(
    shutil.which("sh") is None or shutil.which("patch") is None,
    reason="needs sh and patch")


def _hunk_lines() -> list[str]:
    """The patch's one hunk, without its header."""
    text = PATCH.read_text(encoding="utf-8")
    return text.split("\n@@", 1)[1].split("\n", 1)[1].rstrip("\n").split("\n")


def _before() -> str:
    """The file as the patch expects to find it: context and removed lines."""
    return "\n".join(line[1:] for line in _hunk_lines()
                     if line[:1] in (" ", "-")) + "\n"


def _patch_step(script: pathlib.Path) -> str:
    """The lines a build script runs between `cd /src` and `./bootstrap`."""
    text = script.read_text(encoding="utf-8")
    match = re.search(r"^cd /src\n(.*?)^(?:make distclean|echo \"### bootstrap)",
                      text, re.M | re.S)
    assert match, f"{script.name} has no step between cd /src and bootstrap"
    return match.group(1)


def _run_step(script: pathlib.Path, tree: pathlib.Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, FSUAE_PATCHES=str(AMIGA))
    return subprocess.run(["sh", "-eu", "-c", _patch_step(script)], cwd=tree,
                          env=env, capture_output=True, text=True, check=False)


def _tree(tmp_path: pathlib.Path, body: str) -> pathlib.Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "inputdevice.cpp").write_text(body, encoding="utf-8")
    return tmp_path


def test_the_patch_guards_the_strdup_and_nothing_else():
    lines = _hunk_lines()
    assert [line[1:].strip() for line in lines if line.startswith("-")] == [UNGUARDED]
    assert [line[1:].strip() for line in lines if line.startswith("+")] == [GUARD]
    assert "+++ b/src/inputdevice.cpp" in PATCH.read_text(encoding="utf-8")


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_each_build_patches_before_it_bootstraps(script):
    step = _patch_step(script)
    assert "fsuae-*.patch" in step
    assert "${FSUAE_PATCHES:-/patches}" in step


@needs_patch
@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_the_step_applies_the_guard_then_skips_it(script, tmp_path):
    tree = _tree(tmp_path, _before())
    first = _run_step(script, tree)
    assert first.returncode == 0, first.stdout + first.stderr
    assert f"### applied {PATCH}" in first.stdout
    patched = (tree / "src" / "inputdevice.cpp").read_text(encoding="utf-8")
    assert GUARD in patched and UNGUARDED not in patched
    second = _run_step(script, tree)
    assert second.returncode == 0, second.stdout + second.stderr
    assert f"### already applied {PATCH}" in second.stdout
    assert (tree / "src" / "inputdevice.cpp").read_text(encoding="utf-8") == patched


@needs_patch
@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_the_step_stops_on_a_tree_the_patch_does_not_fit(script, tmp_path):
    tree = _tree(tmp_path, "int unrelated;\n")
    done = _run_step(script, tree)
    assert done.returncode != 0
    assert "### applied" not in done.stdout
