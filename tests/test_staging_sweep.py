"""Sweep of `tools/*.py` for the read-only-specimen staging bug (#472).

`tools/specimens.py add` makes every specimen read-only on purpose. A bare
`shutil.copy` into a pool slot's own directory carries that mode onto the
staged copy, so the game gets a write-protected save disk and every write it
makes is silently refused -- and the next run into that same slot dies on a
bare `PermissionError` staging over the leftover. `#430 (A pool slot with a
read-only SIDE0.D64 left in it fails every later run with a bare Permission
denied)`, `#455 (A Silver Blades run staged from a specimen gives the game a
write-protected save disk)`, `#469 (A second Silver Blades run in the same
pool slot cannot start, because the staged save disk is left read-only)` and
`#472 (Eight more tools stage a disk into a pool slot with a bare
shutil.copy, and session.py's own fix for #430 still leaves the game a
read-only save disk)` are four rounds of finding this by hand, one file at a
time. This is the test meant to make a fifth round unnecessary.

`tools/session.py`'s `stage_writable` is the one place allowed to call
`shutil.copy` on a destination built from a slot's own directory -- it is the
function everything else is supposed to go through.
"""
from __future__ import annotations

import ast
import pathlib

TOOLS = pathlib.Path(__file__).resolve().parent.parent / "tools"

#: The only file allowed to open `shutil.copy` on a slot-scoped destination
#: directly: it is `stage_writable`'s own implementation.
EXEMPT = {"session.py"}


def _names_a_slot(text: str) -> bool:
    return "slot.dir" in text or "slot_dir" in text


def _slot_scoped_bare_copies(root: pathlib.Path = TOOLS) -> list[str]:
    """Every `shutil.copy(src, <dest built from a slot's own directory>)`.

    Found by walking each file's AST rather than grepping text, so a call
    split across lines, or reached through a variable a few lines above it --
    `staged = pathlib.Path(slot.dir) / "SIDE0.D64"` then `shutil.copy(save,
    staged)`, which is the shape `tools/splatload.py`, `tools/cursewarp.py`
    and `tools/ssbwarp.py`'s old `SAVE_IN.D64` copy all had -- is still
    caught. The variable tracking is file-wide rather than scoped to one
    function, which trades a false positive from an unrelated reuse of a name
    like `staged` for never missing the real shape again; nothing in this
    tree reuses those names for anything else.

    A destination naming `slot.dir` (however it is spelled -- `run.slot.dir`,
    `self.slot.dir`, an f-string built from it) is what makes a copy land in
    a directory a pool reuses across separate processes, which is the
    property that turns a read-only specimen into a poisoned slot.
    """
    found = []
    for path in sorted(root.glob("*.py")):
        if path.name in EXEMPT:
            continue
        source = path.read_text()
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue
        slot_scoped_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                text = ast.get_source_segment(source, node.value) or ""
                if _names_a_slot(text):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            slot_scoped_names.add(target.id)
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
            is_hit = _names_a_slot(text) or (
                isinstance(dest, ast.Name) and dest.id in slot_scoped_names)
            if is_hit:
                found.append(f"{path.name}:{node.lineno}")
    return found


def test_no_tool_stages_a_disk_into_a_slot_with_a_bare_shutil_copy():
    """#472: name the file and line rather than just say something failed."""
    offenders = _slot_scoped_bare_copies()
    assert offenders == [], (
        "these call sites copy into a pool slot's own directory with a bare "
        "shutil.copy, which carries a read-only specimen's mode onto the "
        "staged file and leaves it there for the next run to trip over -- "
        "route them through tools.session.stage_writable instead:\n  "
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


def test_the_sweep_leaves_a_wrapped_copy_alone(tmp_path):
    """`stage_writable` itself, or a call routed through it, is not a hit."""
    (tmp_path / "toolstub.py").write_text(
        "import pathlib\n"
        "from tools import session as S\n"
        "\n"
        "def stage(slot, save):\n"
        "    S.stage_writable(save, pathlib.Path(slot.dir) / 'SIDE0.D64')\n")

    assert _slot_scoped_bare_copies(tmp_path) == []
