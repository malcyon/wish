"""`tools/classdiagram.py`: the parts that do not need a real `pyreverse` run.

`#488 (Generate class diagrams from the code with pyreverse, since the
published docs show every class alone and never how they hold each other)`'s
step 1 turned into this tool. Shelling out to a real `pyreverse` takes
minutes and needs a dependency CI does not have, so these tests exercise the
Mermaid parsing, the missing-`pyreverse` message, the empty-diagram skip and
the worktree lifecycle -- the parts that are this tool's own.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools import classdiagram  # noqa: E402

#: A real `classes_titles.mmd`, as `pyreverse` wrote it on 2026-09-10 --
#: two classes, one of them empty, no edges.
TITLES_MMD = """\
classDiagram
  class Title {
    class_bit_names : dict[int, str] | None
    key : str
    title : str
  }
  class UnknownTitleError {
  }
"""

#: A real relation-bearing fragment, from `classes_goldbox.mmd` -- three
#: class blocks and three edges of different kinds.
GOLDBOX_MMD = """\
classDiagram
  class AmigaShape {
    dos : DosDeltas
  }
  class DosDeltas {
  }
  class Game {
  }
  AmigaShape --> DosDeltas : dos
  DaxError --|> DosSaveError
  Game --o SaveGame0 : game
"""

#: What `pyreverse` writes for a module with no classes in it -- the six
#: modules the issue's own run named: `assets`, `classcode`, `derive`,
#: `dos_layout`, `encoding`, `petscii`.
EMPTY_MMD = "classDiagram\n"


def test_measure_mmd_counts_classes_and_edges():
    assert classdiagram.measure_mmd(TITLES_MMD) == (2, 0)
    assert classdiagram.measure_mmd(GOLDBOX_MMD) == (3, 3)


def test_measure_mmd_on_an_empty_diagram_is_zero_classes():
    assert classdiagram.measure_mmd(EMPTY_MMD) == (0, 0)


def test_slug_for_strips_directories_and_extensions():
    assert classdiagram.slug_for(["goldbox/amiga.py"]) == "amiga"
    assert classdiagram.slug_for(["goldbox"]) == "goldbox"
    assert classdiagram.slug_for(["goldbox/amiga.py", "goldbox/dos.py"]) \
        == "amiga+dos"


def test_find_pyreverse_with_none_on_path_names_the_command_to_build_one(
    monkeypatch,
):
    monkeypatch.setattr(classdiagram.shutil, "which", lambda name: None)
    with pytest.raises(classdiagram.ClassDiagramError) as excinfo:
        classdiagram.find_pyreverse(None)
    message = str(excinfo.value)
    assert "pip install pylint" in message
    assert ".venv" in message


def test_find_pyreverse_prefers_an_explicit_path(monkeypatch, tmp_path):
    fake = tmp_path / "pyreverse"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setattr(classdiagram.shutil, "which", lambda name: None)
    assert classdiagram.find_pyreverse(str(fake)) == str(fake)


def test_find_pyreverse_rejects_an_explicit_path_that_does_not_exist(
    monkeypatch,
):
    monkeypatch.setattr(classdiagram.shutil, "which", lambda name: None)
    with pytest.raises(classdiagram.ClassDiagramError):
        classdiagram.find_pyreverse("/no/such/pyreverse")


def test_report_diagram_on_an_empty_file_says_skipped(tmp_path, capsys):
    mmd_path = tmp_path / "classes_assets.mmd"
    mmd_path.write_text(EMPTY_MMD)
    classdiagram.report_diagram(mmd_path, mmdc=None)
    out = capsys.readouterr().out
    assert "skipped" in out
    assert "Mermaid parse error" in out


def test_report_diagram_with_no_mmdc_reports_classes_and_edges_only(
    tmp_path, capsys,
):
    mmd_path = tmp_path / "classes_titles.mmd"
    mmd_path.write_text(TITLES_MMD)
    classdiagram.report_diagram(mmd_path, mmdc=None)
    out = capsys.readouterr().out
    assert "2 classes" in out
    assert "0 edges" in out
    assert "mermaid-cli" in out
    assert "px" not in out


def test_report_diagram_names_modules_for_a_packages_file(tmp_path, capsys):
    mmd_path = tmp_path / "packages_goldbox.mmd"
    mmd_path.write_text(GOLDBOX_MMD)
    classdiagram.report_diagram(mmd_path, mmdc=None)
    out = capsys.readouterr().out
    assert "3 modules" in out


def test_run_pyreverse_refuses_a_target_that_does_not_exist(tmp_path):
    with pytest.raises(classdiagram.ClassDiagramError):
        classdiagram.run_pyreverse(
            "pyreverse-never-called", tmp_path, ["nosuchmodule"],
            tmp_path / "out", [],
        )


def test_pyreverse_argv_pins_the_command_line():
    """The mutation a reviewer tried by hand: change `-o mmd` to `-o png`
    in `pyreverse_argv` and this goes red, where the old suite -- which
    only ever mocked `run_pyreverse` away or exercised the pre-flight check
    that returns before a command line is built -- did not notice at all."""
    out_dir = pathlib.Path("/tmp/classdiagram-does-not-need-to-exist")

    argv = classdiagram.pyreverse_argv("PYREV", ["goldbox"], out_dir, [])
    assert argv == ["PYREV", "-o", "mmd", "-d", str(out_dir), "goldbox"]

    argv = classdiagram.pyreverse_argv(
        "PYREV", ["goldbox/amiga.py"], out_dir,
        ["--no-standalone", "-k"],
    )
    assert argv == ["PYREV", "-o", "mmd", "-d", str(out_dir),
                     "--no-standalone", "-k", "goldbox/amiga.py"]


def test_run_pyreverse_hands_pyreverse_argv_to_subprocess_run_at_root(
    monkeypatch, tmp_path,
):
    """Proves `run_pyreverse` actually uses `pyreverse_argv`'s output, and
    runs it with `cwd` set to whichever root it was given -- the thing
    `--dirty` and the worktree path are supposed to change."""
    (tmp_path / "goldbox").mkdir()
    calls = []
    monkeypatch.setattr(
        classdiagram.subprocess, "run",
        lambda argv, cwd, check: calls.append((argv, cwd, check)),
    )

    out_dir = tmp_path / "out"
    classdiagram.run_pyreverse("PYREV", tmp_path, ["goldbox"], out_dir, [])

    assert len(calls) == 1
    argv, cwd, check = calls[0]
    assert argv == classdiagram.pyreverse_argv(
        "PYREV", ["goldbox"], out_dir, [],
    )
    assert argv[1:3] == ["-o", "mmd"]
    assert cwd == tmp_path
    assert check is True


def test_worktree_is_created_at_head_and_removed_after(tmp_path):
    """Checks this one worktree's path, not the whole registry -- several
    tests here add their own worktree to the same repository, and under
    `pytest`'s parallel workers a snapshot of the whole list races another
    test's add or remove."""
    repo = classdiagram.REPO

    wt = classdiagram.add_worktree(repo)
    try:
        assert wt.is_dir()
        assert (wt / "AGENTS.md").is_file()
        during = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=repo, check=True, capture_output=True, text=True,
        ).stdout
        assert str(wt) in during
    finally:
        classdiagram.remove_worktree(repo, wt)

    assert not wt.exists()
    after = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo, check=True, capture_output=True, text=True,
    ).stdout
    assert str(wt) not in after


def test_remove_worktree_also_removes_the_wrapping_temp_directory(tmp_path):
    """`git worktree remove` only deregisters `wt` itself; the `mkdtemp`
    directory that wraps it (`add_worktree`'s `parent`) is not git's to
    clean up and is left behind unless `remove_worktree` does it."""
    repo = classdiagram.REPO
    wt = classdiagram.add_worktree(repo)
    parent = wt.parent
    assert parent.is_dir()

    classdiagram.remove_worktree(repo, wt)

    assert not parent.exists()


def test_add_worktree_removes_its_temp_directory_when_git_fails(
    monkeypatch, tmp_path,
):
    """A `git worktree add` failure -- a stale lock, permissions, disk
    pressure -- must not leave the `mkdtemp` wrapper behind either."""
    made = {}
    real_mkdtemp = classdiagram.tempfile.mkdtemp

    def fake_mkdtemp(prefix):
        made["parent"] = pathlib.Path(real_mkdtemp(prefix=prefix, dir=str(tmp_path)))
        return str(made["parent"])

    monkeypatch.setattr(classdiagram.tempfile, "mkdtemp", fake_mkdtemp)

    def fail_run(cmd, cwd, check):
        raise subprocess.CalledProcessError(128, cmd)

    monkeypatch.setattr(classdiagram.subprocess, "run", fail_run)

    with pytest.raises(subprocess.CalledProcessError):
        classdiagram.add_worktree(classdiagram.REPO)

    assert not made["parent"].exists()


def test_main_reports_a_failed_worktree_as_one_line_not_a_traceback(
    monkeypatch, capsys,
):
    """Every other failure this tool can hit -- no pyreverse, a bad target,
    a failed pyreverse run -- is caught in `main()` and printed as one
    line. A `git worktree add` failure used to bypass that and raise
    `CalledProcessError` straight out of `main()`."""
    monkeypatch.setattr(classdiagram, "find_pyreverse",
                         lambda explicit: "pyreverse-stub")
    monkeypatch.setattr(classdiagram.shutil, "which", lambda name: None)

    def fail_add_worktree(repo):
        raise subprocess.CalledProcessError(
            128, ["git", "worktree", "add"], stderr="fatal: a lock file")

    monkeypatch.setattr(classdiagram, "add_worktree", fail_add_worktree)

    rc = classdiagram.main(["goldbox"])

    assert rc == 1
    err = capsys.readouterr().err
    assert "worktree" in err
    assert "Traceback" not in err


def test_worktree_is_removed_even_when_the_run_inside_it_fails(tmp_path):
    """The shape `main()` relies on: `add_worktree` then a failing step,
    inside `try`/`finally`, still leaves no worktree behind."""
    repo = classdiagram.REPO
    wt = classdiagram.add_worktree(repo)
    try:
        with pytest.raises(classdiagram.ClassDiagramError):
            try:
                raise classdiagram.ClassDiagramError("pretend pyreverse failed")
            finally:
                classdiagram.remove_worktree(repo, wt)
    finally:
        pass
    assert not wt.exists()


def test_main_reports_pyreverse_missing_without_touching_git(monkeypatch):
    """`main()` must fail before ever adding a worktree when there is no
    pyreverse to run -- otherwise every invocation with none installed
    pays for a worktree it cannot use."""
    calls = []
    monkeypatch.setattr(classdiagram, "add_worktree",
                         lambda repo: calls.append("add") or pathlib.Path("/nope"))
    monkeypatch.setattr(classdiagram.shutil, "which", lambda name: None)

    rc = classdiagram.main(["goldbox"])

    assert rc == 2
    assert calls == []


def test_main_runs_pyreverse_reports_and_cleans_up(
    monkeypatch, tmp_path, capsys,
):
    """Wires `main()` end to end with a stand-in for `run_pyreverse` that
    writes a real `.mmd` file, so the worktree add/remove and the report
    line are proven together without a real pyreverse."""
    monkeypatch.setattr(classdiagram, "find_pyreverse",
                         lambda explicit: "pyreverse-stub")
    monkeypatch.setattr(classdiagram.shutil, "which", lambda name: None)

    seen_worktrees = []

    def fake_add_worktree(repo):
        wt = tmp_path / "wt"
        wt.mkdir()
        seen_worktrees.append(wt)
        return wt

    removed = []
    monkeypatch.setattr(classdiagram, "add_worktree", fake_add_worktree)
    monkeypatch.setattr(classdiagram, "remove_worktree",
                         lambda repo, wt: removed.append(wt))

    def fake_run_pyreverse(pyreverse, root, targets, out_dir, extra_args):
        assert pyreverse == "pyreverse-stub"
        assert root == seen_worktrees[0]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "classes_titles.mmd").write_text(TITLES_MMD)

    monkeypatch.setattr(classdiagram, "run_pyreverse", fake_run_pyreverse)

    out_dir = tmp_path / "out"
    rc = classdiagram.main(["goldbox/titles.py", "--out", str(out_dir)])

    assert rc == 0
    assert removed == seen_worktrees
    out = capsys.readouterr().out
    assert "2 classes" in out


def test_main_dirty_never_touches_a_worktree(monkeypatch, tmp_path):
    monkeypatch.setattr(classdiagram, "find_pyreverse",
                         lambda explicit: "pyreverse-stub")
    monkeypatch.setattr(classdiagram.shutil, "which", lambda name: None)

    def fail_add_worktree(repo):
        raise AssertionError("must not build a worktree when --dirty")

    monkeypatch.setattr(classdiagram, "add_worktree", fail_add_worktree)

    def fake_run_pyreverse(pyreverse, root, targets, out_dir, extra_args):
        assert root == classdiagram.REPO
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "classes_titles.mmd").write_text(TITLES_MMD)

    monkeypatch.setattr(classdiagram, "run_pyreverse", fake_run_pyreverse)

    out_dir = tmp_path / "out"
    rc = classdiagram.main(
        ["goldbox/titles.py", "--dirty", "--out", str(out_dir)],
    )
    assert rc == 0
