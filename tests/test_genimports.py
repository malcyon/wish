"""`tools/genimports.py`, and the document it keeps honest.

The tool exists to catch one edge -- a codec reaching into another format's
record table -- so the two things worth testing are that it sees an import
however it is spelled, and that the block in `docs/117-save-conversion.md` is
still the block it prints. A generated document nothing regenerates is a
document that is only mostly true.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))

import genimports  # noqa: E402

DOC = pathlib.Path(__file__).resolve().parent.parent / "docs/117-save-conversion.md"


def _package(root, files):
    root.mkdir()
    for name, source in files.items():
        (root / f"{name}.py").write_text(source)
    return root


def test_a_sibling_is_seen_however_the_import_is_spelled(tmp_path):
    """Four spellings, one edge each. The absolute one was missed once."""
    root = _package(tmp_path / "por", {
        "layout": "",
        "relative": "from .layout import Field\n",
        "bare": "from . import layout\n",
        "absolute": "from por.layout import Field\n",
        "dotted": "import por.layout\n",
    })
    found = {(s, d) for s, d, _ in genimports.edges(root)}
    for source in ("relative", "bare", "absolute", "dotted"):
        assert (source, "layout") in found, source


def test_an_import_outside_the_module_body_binds_more_weakly(tmp_path):
    root = _package(tmp_path / "por", {
        "layout": "",
        "late": "def f():\n    from por.layout import Field\n",
    })
    assert genimports.edges(root) == [("late", "layout", genimports.DEFERRED)]


def test_the_documented_graph_is_the_one_the_tool_prints():
    """docs/117 marks the block generated; this is what makes that true."""
    package = pathlib.Path(__file__).resolve().parent.parent / "por"
    printed = genimports.mermaid(genimports.edges(package))
    assert printed in DOC.read_text(), (
        "docs/117-save-conversion.md is out of step with tools/genimports.py --"
        " re-run `python3 tools/genimports.py --mermaid` and replace the block")
