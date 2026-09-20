"""Every `tools/` path a tracked text file cites is a path that exists.

`tools/` was one flat directory of 370 files and is now one subdirectory per
game or job, so a citation such as `tools/dosbox.py` is stale the day the file
moves and nothing fails: a reader is sent to a path that is not there, and
`git grep` for the old name finds it only if somebody thinks to look. This
walks every tracked text file for anything that looks like a path into `tools/`
and checks each one against the tree.

What counts as a citation is `tools/` followed by path characters, and the
forms it understands are:

* a file, with or without a line number: `tools/dos/dosbox.py`,
  `tools/dos/dosbox.py:123`;
* a module and an attribute, the way prose names a function:
  `tools/dos/dosbox.find_game` -- the module part must be a real file;
* an extensionless module name, `tools/icons/iconproposal`;
* a directory, `tools/dos/` or `tools/dos`;
* a glob, `tools/dos/dos*.py`, which must match at least one file.

Two kinds of text are not citations and are exempt, both by a rule that names
what it lets through rather than by a pattern loose enough to hide drift:

* **A template.** `tools/<name>.py` and `tools/{name}.py` stand for any tool,
  and `git show {sha}~1:tools/{name}` reads a path from a commit that
  predates the move. A citation whose first character after `tools/` is `<`
  or `{` is a template.
* **A made-up example.** `tools/x.py` and `tools/y.py` are invented names in
  `tools/pathleak.py` and in the `senior-analyst` agent. They are two exact
  names, not a family.

Nothing else is exempt, so a citation of a file that has been moved, renamed
or deleted fails here with the file, the line and the text.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"

#: This file's own examples cite paths that do not exist, on purpose.
SKIP_FILES = {"tests/suite/test_toolpaths.py"}
#: Game data and other bytes; nothing in them is prose.
SKIP_PREFIXES = ("tests/fixtures/",)

#: The two invented example names described in the module docstring.
MADE_UP = {"x.py", "y.py"}

#: A suffix that makes a name a file rather than a module with an attribute.
_FILE_SUFFIX = re.compile(r"\.(?:py|sh|ps1|yaml|yml|md|json|toml|uae|txt|cfg)"
                          r"(?:\.|$)")

#: `tools/` at a word start -- after `/` or `:` too, so `<checkout>/tools/x.py`
#: and `sha~1:tools/x.py` are read -- followed by the characters a path uses,
#: with `*` for a glob. A leading `<` or `{` marks a template.
CITATION = re.compile(
    r"(?<![A-Za-z0-9_.-])tools/(?P<path>[<{][^\s`'\"()]*|[A-Za-z0-9_./*?-]*)")


def _tracked_text():
    listing = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                             capture_output=True, check=True)
    for raw in listing.stdout.split(b"\0"):
        if not raw:
            continue
        rel = raw.decode("utf-8")
        if rel in SKIP_FILES or rel.startswith(SKIP_PREFIXES):
            continue
        path = ROOT / rel
        if not path.is_file():
            continue            # a symlink to a directory, or a deleted file
        try:
            yield rel, path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue            # binary


def _resolves(cited: str) -> bool:
    """Does `tools/<cited>` name a file, a directory, a module or a glob hit?"""
    if "*" in cited or "?" in cited:
        return any(TOOLS.glob(cited))
    if cited in MADE_UP:
        return True
    where = TOOLS / cited
    if where.exists():
        return True
    parent, _, last = cited.rpartition("/")
    if not last or _FILE_SUFFIX.search(last):
        return False            # a file name that is not there, or a bare `dir/`
    # `dosbox.find_game`: a module and an attribute, or a bare module name.
    stem = last.split(".")[0]
    return (TOOLS / parent / f"{stem}.py").is_file()


def _citations():
    for rel, text in _tracked_text():
        for number, line in enumerate(text.split("\n"), start=1):
            for m in CITATION.finditer(line):
                cited = m["path"].rstrip(".-")
                if not cited or cited[0] in "<{":
                    continue                       # a template
                yield rel, number, f"tools/{cited}", cited


def test_every_tools_path_cited_in_a_tracked_file_exists():
    dead = [f"{rel}:{number}: {shown}"
            for rel, number, shown, cited in _citations()
            if not _resolves(cited)]
    assert not dead, (
        f"{len(dead)} citations of a `tools/` path that is not there -- "
        f"moved, renamed or deleted, or mistyped:\n" + "\n".join(dead[:60]))


# ---------------------------------------------------------------------------
# The checker has to be able to fail, and to pass for every form it names.
# ---------------------------------------------------------------------------

def _dead(text: str) -> list[str]:
    out = []
    for m in CITATION.finditer(text):
        cited = m["path"].rstrip(".-")
        if cited and cited[0] not in "<{" and not _resolves(cited):
            out.append(f"tools/{cited}")
    return out


@pytest.mark.parametrize("text", [
    "see `tools/wishagent.py` for the bot",
    "at `tools/wishagent.py:12`",
    "the function `tools/wish.subcommand` names a module attribute",
    "`tools/wish`, as a module",
    "everything in `tools/` and in `tools`",
    "the two scripts that stay at the top, `tools/wish*.py`",
    "<checkout>/tools/wishagent.py",
    "`git show {sha}~1:tools/{name}`",
    "a template, `tools/<name>.py` or `tools/{name}.py`",
    "made-up examples, `tools/x.py` and `tools/y.py`",
])
def test_the_forms_that_are_citations_or_exempt_pass(text):
    assert _dead(text) == []


@pytest.mark.parametrize("text, expect", [
    ("`tools/no_such_tool.py`", ["tools/no_such_tool.py"]),
    ("`tools/no_such_tool.py:40`", ["tools/no_such_tool.py"]),
    ("`tools/no_such_tool.attr`", ["tools/no_such_tool.attr"]),
    ("`tools/no_such_dir/`", ["tools/no_such_dir/"]),
    ("`tools/no_such_*.py`", ["tools/no_such_*.py"]),
    # A real module name with a file suffix that does not exist is not rescued
    # by the module reading.
    ("`tools/wish.yaml`", ["tools/wish.yaml"]),
    # The path of a file that used to be at the top of `tools/`.
    ("`tools/wishagent/wishagent.py`", ["tools/wishagent/wishagent.py"]),
])
def test_a_citation_of_a_path_that_is_not_there_fails(text, expect):
    assert _dead(text) == expect
