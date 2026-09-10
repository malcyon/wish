"""Sweep of `tools/*.py` for the read-only-specimen staging bug (#472, #476).

`tools/specimens.py add` makes every specimen read-only on purpose. A bare
`shutil.copy` into a directory a tool reuses across runs -- a pool slot, or a
tool's own `--out`-scoped staging directory -- carries that mode onto the
staged copy, so the game gets a write-protected save disk and every write it
makes is silently refused, and the next run into that same directory dies on
a bare `PermissionError` staging over the leftover.

Two directories are reused this way and both are covered here:

* **A pool slot's own directory**, `slot.dir` -- `#430 (A pool slot with a
  read-only SIDE0.D64 left in it fails every later run with a bare
  Permission denied)`, `#455 (A Silver Blades run staged from a specimen
  gives the game a write-protected save disk)`, `#469 (A second Silver
  Blades run in the same pool slot cannot start, because the staged save
  disk is left read-only)` and `#472 (Eight more tools stage a disk into a
  pool slot with a bare shutil.copy, and session.py's own fix for #430 still
  leaves the game a read-only save disk)` are four rounds of finding this by
  hand, one file at a time.
* **A tool's own `out / "disks"` staging directory**, built under a `--out`
  that defaults to a fixed path under `work/` and so is just as reused as a
  slot unless `--out` is passed each time -- `#476 (Six tools stage a save
  into their own reused work/ output directory with a bare shutil.copy, the
  same shape #472 fixed for pool slots)`.

This is the test meant to make a fifth round unnecessary for either shape.

`tools/session.py`'s `stage_writable` is the one place allowed to call
`shutil.copy` on either kind of destination -- it is the function everything
else is supposed to go through.
"""
from __future__ import annotations

import ast
import pathlib

TOOLS = pathlib.Path(__file__).resolve().parent.parent / "tools"

#: The only file allowed to open `shutil.copy` on one of these destinations
#: directly: it is `stage_writable`'s own implementation.
EXEMPT = {"session.py"}


def _names_a_slot(text: str) -> bool:
    return "slot.dir" in text or "slot_dir" in text


def _names_a_reused_staging_dir(text: str) -> bool:
    """A directory built as `<something> / "disks"`, off a tool's own
    `--out` -- the shape all six #476 tools shared: `staging = out /
    "disks"` or `staging_dir = out / "disks"`, checked by hand in each file.
    `--out` defaults to a fixed path under `work/` unless passed each time,
    so this directory is reused across invocations exactly the way a pool
    slot is, and a bare `shutil.copy` into it carries the same read-only
    mode a specimen brings.
    """
    return '/ "disks"' in text or "/ 'disks'" in text


def _slot_scoped_bare_copies(root: pathlib.Path = TOOLS) -> list[str]:
    """Every `shutil.copy` into a directory a run reuses across processes:
    a pool slot's own directory, or a tool's own `out / "disks"` staging
    directory (`#472`, `#476`).

    Found by walking each file's AST rather than grepping text, so a call
    split across lines, or reached through a variable a few lines above it --
    `staged = pathlib.Path(slot.dir) / "SIDE0.D64"` then `shutil.copy(save,
    staged)`, which is the shape `tools/splatload.py`, `tools/cursewarp.py`
    and `tools/ssbwarp.py`'s old `SAVE_IN.D64` copy all had, and
    `staging = out / "disks"` then `shutil.copy(src, staging / "STAGED.D64")`,
    which is what every one of the six `#476` tools did -- is still caught.
    The variable tracking is file-wide rather than scoped to one function,
    which trades a false positive from an unrelated reuse of a name like
    `staged` for never missing the real shape again; nothing in this tree
    reuses those names for anything else.

    **The destination need not be a bare name.** `staging / "STAGED.D64"` is
    a `BinOp`, not a `Name`, so the check walks every name inside the
    destination expression rather than only asking whether the whole
    expression *is* one -- which is what a `dest` reached through a tracked
    variable but combined with a literal filename, the `#476` shape, needs.

    A destination naming `slot.dir` (however it is spelled -- `run.slot.dir`,
    `self.slot.dir`, an f-string built from it) or built as `<out> /
    "disks"` is what makes a copy land in a directory reused across separate
    runs, which is the property that turns a read-only specimen into a
    poisoned destination.
    """
    found = []
    for path in sorted(root.glob("*.py")):
        if path.name in EXEMPT:
            continue
        # `encoding="utf-8"` and not the platform default: Windows reads as
        # cp1252, and several tools here carry a byte it has no character
        # for -- an em dash, a `▸`, a game string quoted in a docstring. Both
        # Windows CI jobs went red on `UnicodeDecodeError` at position 3972
        # of the first such file while both Linux jobs passed, which is the
        # shape `.claude/rules/commits.md` names: something that is not
        # byte-identical on another machine.
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue
        reused_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                text = ast.get_source_segment(source, node.value) or ""
                if _names_a_slot(text) or _names_a_reused_staging_dir(text):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            reused_names.add(target.id)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "copy"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "shutil"):
                continue
            args = list(node.args)
            dest = args[1] if len(args) > 1 else None
            if dest is None:
                continue
            text = ast.get_source_segment(source, dest) or ""
            is_hit = (
                _names_a_slot(text)
                or _names_a_reused_staging_dir(text)
                or any(isinstance(n, ast.Name) and n.id in reused_names
                       for n in ast.walk(dest)))
            if is_hit:
                found.append(f"{path.name}:{node.lineno}")
    return found


def test_no_tool_stages_a_disk_into_a_reused_directory_with_a_bare_shutil_copy():
    """#472, #476: name the file and line rather than just say something
    failed."""
    offenders = _slot_scoped_bare_copies()
    assert offenders == [], (
        "these call sites copy into a directory a run reuses across "
        "processes -- a pool slot, or a tool's own out/disks staging "
        "directory -- with a bare shutil.copy, which carries a read-only "
        "specimen's mode onto the staged file and leaves it there for the "
        "next run to trip over -- route them through "
        "tools.session.stage_writable instead:\n  "
        + "\n  ".join(offenders))


def test_the_sweep_catches_the_shape_it_exists_to_prevent(tmp_path):
    """Prove the scanner is not vacuous by feeding it the bug it looks for.

    A test that only ever asserts `== []` against the real tree cannot be
    told apart from one whose matching logic never matches anything -- this
    is what tells them apart.
    """
    (tmp_path / "toolstub.py").write_text(
        "import shutil\n"
        "import pathlib\n"
        "\n"
        "def stage(slot, save):\n"
        "    shutil.copy(save, pathlib.Path(slot.dir) / 'SIDE0.D64')\n")

    offenders = _slot_scoped_bare_copies(tmp_path)

    assert offenders == ["toolstub.py:5"]


def test_the_sweep_catches_a_copy_reached_through_a_variable(tmp_path):
    """The shape `tools/splatload.py`, `tools/cursewarp.py` and the old
    `tools/ssbwarp.py` `SAVE_IN.D64` copy all had: the slot path is built a
    few lines above the call, not written inline at the call site."""
    (tmp_path / "toolstub.py").write_text(
        "import shutil\n"
        "import pathlib\n"
        "\n"
        "def stage(slot, save):\n"
        "    staged = pathlib.Path(slot.dir) / 'SIDE0.D64'\n"
        "    shutil.copy(save, staged)\n")

    assert _slot_scoped_bare_copies(tmp_path) == ["toolstub.py:6"]


def test_the_sweep_catches_a_copy_into_a_reused_out_disks_directory(tmp_path):
    """#476: the shape all six named tools shared -- `staging = out /
    "disks"` a few lines above a bare `shutil.copy(src, staging /
    "STAGED.D64")`, where the destination is a `BinOp` built from the
    tracked variable and a literal filename, not the variable alone."""
    (tmp_path / "toolstub.py").write_text(
        "import shutil\n"
        "import pathlib\n"
        "\n"
        "def stage(out, src):\n"
        "    staging = out / 'disks'\n"
        "    staging.mkdir(parents=True, exist_ok=True)\n"
        "    shutil.copy(src, staging / 'STAGED.D64')\n")

    assert _slot_scoped_bare_copies(tmp_path) == ["toolstub.py:7"]


def test_the_sweep_leaves_a_wrapped_copy_alone(tmp_path):
    """`stage_writable` itself, or a call routed through it, is not a hit."""
    (tmp_path / "toolstub.py").write_text(
        "import pathlib\n"
        "from tools import session as S\n"
        "\n"
        "def stage(slot, save):\n"
        "    S.stage_writable(save, pathlib.Path(slot.dir) / 'SIDE0.D64')\n")

    assert _slot_scoped_bare_copies(tmp_path) == []
