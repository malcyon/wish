"""`tools/classedges.py`, and the one question it exists to answer.

`#470 (Give the project a neutral title beside its neutral character record,
with one port per platform a title shipped on)` is judged at each stage by
whether `Title` has an edge in a `goldbox/`-scoped class diagram, and
`tools/classdiagram.py` cannot draw one here -- `pylint` is not in `.venv` and
the tool refuses to install it.  So the count is read out of the AST instead,
and this is what says the reading is the same one `pyreverse` would make:
**an annotated attribute counts, a parameter does not.**

The distinction is the whole tool.  `goldbox.titles.race_table` takes a
`'Title | object | str | None'` and `tools/livecheck.py` takes a `title: Title`
in an `__init__` signature; neither is an edge, and a count that included them
would have said `Title` had edges at stage 1.
"""

import pathlib

from conftest import load_tools_module

classedges = load_tools_module("classedges")

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _package(root, files):
    root.mkdir()
    for name, source in files.items():
        (root / f"{name}.py").write_text(source)
    return root


def test_an_annotated_field_is_an_edge_and_a_parameter_is_not(tmp_path):
    root = _package(tmp_path / "pkg", {
        "held": "class Title:\n    pass\n",
        "holder": ("import dataclasses\n\n\n"
                   "@dataclasses.dataclass\n"
                   "class Box:\n"
                   "    rules: Title\n"),
        "passer": ("class Reader:\n"
                   "    def __init__(self, title: Title):\n"
                   "        self.title = title\n"),
        "loose": "TITLES: tuple[Title, ...] = ()\n",
    })
    found = [e for e in classedges.edges([root])
             if classedges._mentions(e[3], "Title")]
    assert [(e[0], e[1], e[2]) for e in found] == [
        ("pkg/holder", "Box", "rules")]


def test_a_union_is_an_edge_and_says_so(tmp_path):
    root = _package(tmp_path / "pkg", {
        "held": "class Title:\n    pass\n",
        "holder": "class Box:\n    rules: Title | None = None\n",
    })
    found = [e for e in classedges.edges([root])
             if classedges._mentions(e[3], "Title")]
    assert len(found) == 1
    assert found[0][3] == "Title | None"
    assert found[0][4] is False          # not a plain name: the weaker claim


def test_a_class_whose_name_merely_starts_the_same_is_not_a_hit(tmp_path):
    root = _package(tmp_path / "pkg", {
        "holder": "class Box:\n    row: TitleRow\n    n: int\n",
    })
    assert [e for e in classedges.edges([root])
            if classedges._mentions(e[3], "Title")] == []


def test_the_title_the_refactor_is_about_has_exactly_one_edge_in_goldbox():
    """Stage 7's answer, pinned so stage 9 notices if it loses the field.

    `goldbox.c64_save.C64Container.rules` is the only annotated `Title`
    anywhere under `goldbox/`; `automap.c64.C64Machine.title` is the other one
    in the tree, and it is what stage 6 put there.
    """
    found = [e for e in classedges.edges([ROOT / "goldbox"])
             if classedges._mentions(e[3], "Title")]
    assert [(e[0], e[1], e[2], e[3]) for e in found] == [
        ("goldbox/c64_save", "C64Container", "rules", "Title")]

    both = sorted(e for e in classedges.edges([ROOT / "goldbox",
                                               ROOT / "automap"])
                  if classedges._mentions(e[3], "Title"))
    assert [(e[0], e[1], e[2]) for e in both] == [
        ("automap/c64", "C64Machine", "title"),
        ("goldbox/c64_save", "C64Container", "rules"),
    ]
