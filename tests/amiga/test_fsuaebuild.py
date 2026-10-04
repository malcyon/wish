"""The FS-UAE fork build applies `tools/amiga/fsuae-*.patch` before it compiles.

Without `fsuae-inputcode-null.patch` the fork's Linux build segfaults on every
state save, state load and reset, because each is queued with a NULL string
that `strdup` is handed. Without `fsuae-restore-redraw.patch` the picture stays
black after a state load until the game draws each line again. The container
build cannot run here, so these tests run the build scripts' own patch step,
cut out of each script, against a tiny tree that holds only the lines the
patches touch: the step must apply every patch, skip them on a second run, and
stop on a tree they do not fit.
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
SCRIPTS = [AMIGA / "fsuaebuildcontainer.sh", AMIGA / "fsuaebuildclang.sh"]

#: Each patch, with the source lines it must remove and add and nothing else.
PATCHES = {
    "fsuae-inputcode-null.patch": (
        ["inputcode_pending[i].s = my_strdup(s);"],
        ["inputcode_pending[i].s = s ? my_strdup(s) : NULL;"]),
    "fsuae-restore-redraw.patch": (
        [],
        ["notice_screen_contents_lost(0);"]),
}

needs_patch = pytest.mark.skipif(
    shutil.which("sh") is None or shutil.which("patch") is None,
    reason="needs sh and patch")


def _printed(name: str) -> str:
    """The patch path as the step prints it: the scripts join with "/" on every OS."""
    return f"{AMIGA}/{name}"


def _target(name: str) -> str:
    """The file a patch changes, below the source tree."""
    return re.search(r"^\+\+\+ b/(\S+)$", (AMIGA / name).read_text(encoding="utf-8"),
                     re.M).group(1)


def _hunk_lines(name: str) -> list[str]:
    """The patch's one hunk, without its header."""
    text = (AMIGA / name).read_text(encoding="utf-8")
    return text.split("\n@@", 1)[1].split("\n", 1)[1].rstrip("\n").split("\n")


def _before(name: str) -> str:
    """The file as the patch expects to find it: context and removed lines."""
    return "\n".join(line[1:] for line in _hunk_lines(name)
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


def _tree(tmp_path: pathlib.Path, bodies: dict[str, str]) -> pathlib.Path:
    for rel, body in bodies.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(body, encoding="utf-8")
    return tmp_path


def _fitting_tree(tmp_path: pathlib.Path) -> pathlib.Path:
    return _tree(tmp_path, {_target(name): _before(name) for name in PATCHES})


def test_every_patch_in_the_directory_is_checked_here():
    assert sorted(p.name for p in AMIGA.glob("fsuae-*.patch")) == sorted(PATCHES)


@pytest.mark.parametrize("name", sorted(PATCHES))
def test_each_patch_changes_only_its_own_lines(name):
    removed, added = PATCHES[name]
    lines = _hunk_lines(name)
    assert [line[1:].strip() for line in lines if line.startswith("-")] == removed
    assert [line[1:].strip() for line in lines if line.startswith("+")] == added


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_each_build_patches_before_it_bootstraps(script):
    step = _patch_step(script)
    assert "fsuae-*.patch" in step
    assert "${FSUAE_PATCHES:-/patches}" in step


@needs_patch
@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_the_step_applies_every_patch_then_skips_them(script, tmp_path):
    tree = _fitting_tree(tmp_path)
    first = _run_step(script, tree)
    assert first.returncode == 0, first.stdout + first.stderr
    patched = {}
    for name, (removed, added) in PATCHES.items():
        assert f"### applied {_printed(name)}" in first.stdout
        body = (tree / _target(name)).read_text(encoding="utf-8")
        assert all(line in body for line in added)
        assert not any(line in body for line in removed)
        patched[name] = body
    second = _run_step(script, tree)
    assert second.returncode == 0, second.stdout + second.stderr
    for name in PATCHES:
        assert f"### already applied {_printed(name)}" in second.stdout
        assert (tree / _target(name)).read_text(encoding="utf-8") == patched[name]


@needs_patch
@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_the_step_stops_on_a_tree_the_patches_do_not_fit(script, tmp_path):
    tree = _tree(tmp_path, {_target(name): "int unrelated;\n" for name in PATCHES})
    done = _run_step(script, tree)
    assert done.returncode != 0
    assert "### applied" not in done.stdout
