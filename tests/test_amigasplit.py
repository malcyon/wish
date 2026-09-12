"""The Amiga codec is one file per title.

`#470 (Give the project a neutral title beside its neutral character record,
with one port per platform a title shipped on)`'s stage 10 split
`goldbox/amiga_codec.py` into `goldbox/amiga_pod.py`, `goldbox/amiga_por.py`,
`goldbox/amiga_later.py` and `goldbox/amiga_shared.py`.  Donald asked for it in
those terms on 2026-09-09: *"Why is Pool of Radiance data so intermingled with
Pools of Darkness data? We should have clear separation between platforms and
titles."*  Stage 9 deleted the two shims, `goldbox/amiga_codec.py` and
`goldbox/amiga.py`, that carried the four modules' names during the move.

Nothing in the suite would notice the split coming undone.  A later edit that
put one title's constant back in another title's file would import, run and
pass everything.  That is what this file pins.
"""

import ast
import importlib
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Each title's module, and which of the others it may name at module level.
#: Every allowance is a measured exception rather than a convenience, and the
#: reason for each is in the importing module's own docstring.
TITLE_MODULES = {
    "amiga_pod": frozenset(),
    "amiga_por": frozenset(),
    # Three names -- `PorWriteReport` and the pair that re-cuts a ten-byte
    # effect node -- which are Amiga-wide facts wearing Pool of Radiance's
    # spelling because it is the title they were decoded on.
    "amiga_later": frozenset({"amiga_por"}),
}

ALL_FOUR = ("amiga_shared", "amiga_pod", "amiga_por", "amiga_later")

#: The five names stage 10 removed rather than moved.  Each was the Pools of
#: Darkness writer's and read as the whole Amiga port's, and one of them had
#: already put that title's count in front of a reader as Pool of Radiance's.
REMOVED = {
    "DROPPED": "POD_WRITE_DROPPED",
    "DIRECT": "POD_WRITE_DIRECT",
    "TRANSFORMED": "POD_WRITE_TRANSFORMED",
    "field_disposition": "pod_write_field_disposition",
    "write": "write_pod",
}


def _top_level_imports(name: str) -> set[str]:
    """Sibling `goldbox` modules this one imports at module level.

    Read out of the AST rather than from `sys.modules`, because an import
    inside a function is exactly what the split uses to keep two titles apart
    and must not be counted.
    """
    tree = ast.parse((ROOT / "goldbox" / f"{name}.py").read_text())
    found: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            if node.module:
                found.add(node.module.split(".")[0])
            else:
                found.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            found.update(a.name.split(".")[-1] for a in node.names)
    return found


def test_no_title_module_reaches_another_at_import_time_except_the_one_that_may():
    """The separation the ticket asked for, stated where a later edit trips it."""
    for name, allowed in TITLE_MODULES.items():
        siblings = _top_level_imports(name) & set(TITLE_MODULES) - {name}
        assert siblings <= allowed, (
            f"goldbox/{name}.py imports {sorted(siblings - allowed)} at module "
            f"level; a title's module holds that title's facts, and a name two "
            f"of them need belongs in goldbox/amiga_shared.py")


def test_the_shared_module_is_underneath_all_three():
    """`amiga_shared` imports no title at the top, so nothing can cycle.

    It reaches `amiga_por` for Pool of Radiance's record length inside
    `amiga_shape_for`, which is why that reach is deferred rather than absent.
    """
    assert not _top_level_imports("amiga_shared") & set(TITLE_MODULES)
    shared = importlib.import_module("goldbox.amiga_shared")
    dos_port = importlib.import_module("goldbox.dos_port")
    assert shared.amiga_shape_for(288) is dos_port.POOL_OF_RADIANCE


def test_each_module_imports_on_its_own_in_a_fresh_interpreter():
    """A split that only works when one module is imported first is a trap
    that surfaces at random.  Each of the four, alone."""
    for name in ALL_FOUR:
        done = subprocess.run(
            [sys.executable, "-c", f"import goldbox.{name}"],
            cwd=ROOT, capture_output=True, text=True)
        assert done.returncode == 0, (name, done.stderr[-2000:])


def test_the_por_reader_takes_a_later_record_with_only_its_own_module_imported():
    """`to_neutral` dispatches a Curse or Silver Blades record to
    `amiga_later`, on a deferred import.  Cold, in a fresh interpreter, so the
    deferral is what is being tested rather than whatever the suite loaded."""
    code = (
        "from goldbox import amiga_por\n"
        "import sys\n"
        "assert 'goldbox.amiga_later' not in sys.modules\n"
        "from goldbox import amiga_later\n"                # build one record
        "d = amiga_later.CURSE_DELTAS\n"
        "c = amiga_later.AmigaCharacter.from_bytes(bytes(d.record_size), d)\n"
        "del sys.modules['goldbox.amiga_later']\n"
        "out = amiga_por.to_neutral(c)\n"
        "assert out.port == 'Amiga'\n")
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-2000:]


def test_the_unprefixed_pools_of_darkness_names_are_gone():
    """The name was the defect, so no alias is left for any of the five.

    Stage 9 deleted the two shims this test used to check; the claim it pins
    is about `amiga_pod.py` itself, which never carried the unprefixed
    spelling in the first place, so it is checked there directly.
    """
    pod = importlib.import_module("goldbox.amiga_pod")
    for old, new in REMOVED.items():
        assert not hasattr(pod, old), (
            f"amiga_pod.{old} is back; it named the Pools of Darkness "
            f"writer's own table as though it were the Amiga's")
        assert hasattr(pod, new)
