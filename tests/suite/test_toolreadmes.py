"""Every `tools/` directory has a README.md with a row for each file in it.

`tools/` is one subdirectory per game or job, and a script nobody can find is
the failure `#181 (Sweep the 95 Python files in scratch for tools nobody can
find)` swept for. This holds the index and the directory READMEs to what the
tree actually contains, so a tool added without a row, or a row left behind
by a tool that was moved or deleted, fails here:

* each subdirectory's `README.md` opens with `# <directory>`, then the
  sentence that is its `__init__.py` docstring, then a table of `file |
  purpose` rows sorted by file name;
* every file in the directory has exactly one row, and every row names a file
  that is there. `__init__.py` and `README.md` are the two exceptions inside a
  subdirectory: the first is what the sentence is taken from and the second is
  the page itself;
* `tools/README.md` lists every subdirectory, linked, in order, with the same
  sentence, and has a row for every file at the top of `tools/` -- there the
  `__init__.py` has a row too, because it does something.

`tests/suite/test_toolpaths.py` reads these pages as it reads every tracked text
file, so a path a row cites is checked there.
"""

from __future__ import annotations

import ast
import pathlib
import re
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"

ROW = re.compile(r"^\| (?:`(?P<a>[^`]+)`|\[(?P<b>[^\]]+)\]\((?P<c>[^)]+)\)) \|")
LINK = re.compile(r"\]\((?P<t>[^)\s]+)\)")

#: Named in a subdirectory README only by being what it is made from.
NO_ROW_IN_A_SUBDIRECTORY = {"__init__.py", "README.md"}


def _tracked(prefix: str) -> list[str]:
    done = subprocess.run(["git", "ls-files", "-z", prefix], cwd=ROOT,
                          capture_output=True, check=True)
    return [p.decode() for p in done.stdout.split(b"\0") if p]


def _subdirectories() -> list[str]:
    return sorted(p.parent.name for p in TOOLS.glob("*/__init__.py"))


DIRECTORIES = _subdirectories()


def _docstring(d: str) -> str:
    tree = ast.parse((TOOLS / d / "__init__.py").read_text(encoding="utf-8"))
    return " ".join((ast.get_docstring(tree) or "").split())


def _rows(text: str) -> list[str]:
    return [m["a"] or m["b"] for line in text.split("\n")
            if (m := ROW.match(line))]


def _files_in(d: str) -> set[str]:
    prefix = f"tools/{d}/" if d else "tools/"
    return {p[len(prefix):] for p in _tracked(prefix) if "/" not in p[len(prefix):]}


def _problems(files: set[str], rows: list[str], exempt: set[str]) -> list[str]:
    """What is wrong between the files a directory holds and its rows."""
    out = []
    for name in sorted(files - exempt - set(rows)):
        out.append(f"{name} has no row")
    for name in sorted(set(rows) - files):
        out.append(f"the row for {name} names no file")
    for name in sorted({r for r in rows if rows.count(r) > 1}):
        out.append(f"{name} has more than one row")
    if rows != sorted(rows):
        out.append("the rows are not sorted by file name")
    return out


def test_there_are_fifteen_directories_and_none_was_forgotten():
    assert DIRECTORIES == sorted(DIRECTORIES) and len(DIRECTORIES) >= 15
    every = {p.split("/")[1] for p in _tracked("tools/") if p.count("/") == 2}
    assert every == set(DIRECTORIES), (
        f"a directory under tools/ has no __init__.py: {sorted(every - set(DIRECTORIES))}")


@pytest.mark.parametrize("d", DIRECTORIES)
def test_a_directory_readme_opens_with_the_docstring_and_has_a_row_per_file(d):
    text = (TOOLS / d / "README.md").read_text(encoding="utf-8")
    lines = text.split("\n")
    assert lines[0] == f"# {d}" and lines[1] == "", lines[:2]
    assert lines[2] == _docstring(d), (
        f"tools/{d}/README.md's sentence is not tools/{d}/__init__.py's docstring")
    assert lines[3] == "" and lines[4] == "| file | purpose |"
    problems = _problems(_files_in(d), _rows(text), NO_ROW_IN_A_SUBDIRECTORY)
    assert not problems, f"tools/{d}/README.md: " + "; ".join(problems)


@pytest.mark.parametrize("d", DIRECTORIES)
def test_a_link_in_a_directory_readme_points_at_something(d):
    page = TOOLS / d / "README.md"
    dead = []
    for target in LINK.findall(page.read_text(encoding="utf-8")):
        if re.match(r"[a-z]+:|#", target):
            continue
        if not (page.parent / target.split("#")[0]).exists():
            dead.append(target)
    assert not dead, f"tools/{d}/README.md links to {dead}, which are not there"


def test_the_index_lists_every_directory_in_order_with_its_sentence():
    text = (TOOLS / "README.md").read_text(encoding="utf-8")
    index = [m.groups() for line in text.split("\n")
             if (m := re.match(r"^\| \[([^\]]+)\]\(([^)]+)\) \| (.*) \|$", line))]
    assert [i[0] for i in index] == DIRECTORIES
    for name, target, sentence in index:
        assert target == f"{name}/README.md"
        assert sentence == _docstring(name)


def test_every_file_at_the_top_of_tools_has_a_row_in_the_index():
    text = (TOOLS / "README.md").read_text(encoding="utf-8")
    top = text.split("## Top level", 1)[1]
    problems = _problems(_files_in(""), _rows(top), {"README.md"})
    assert not problems, "tools/README.md: " + "; ".join(problems)


# ---------------------------------------------------------------------------
# The check has to be able to fail.
# ---------------------------------------------------------------------------

def test_a_tool_with_no_row_fails():
    assert _problems({"a.py", "b.py"}, ["a.py"], set()) == ["b.py has no row"]


def test_a_row_for_a_file_that_is_gone_fails():
    assert _problems({"a.py"}, ["a.py", "z.py"], set()) == [
        "the row for z.py names no file"]


def test_an_unsorted_or_doubled_row_fails():
    assert "the rows are not sorted by file name" in _problems(
        {"a.py", "b.py"}, ["b.py", "a.py"], set())
    assert "a.py has more than one row" in _problems(
        {"a.py"}, ["a.py", "a.py"], set())


def test_the_two_exceptions_need_no_row():
    assert _problems({"__init__.py", "README.md", "a.py"}, ["a.py"],
                     NO_ROW_IN_A_SUBDIRECTORY) == []
