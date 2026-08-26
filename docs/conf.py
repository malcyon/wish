"""Sphinx configuration for the API reference.

`docs/` is the hand-written knowledge base and `docs/README.md` is its index.
Sphinx wants an index of its own, so its root document is `docs/api/index.rst`
and everything it generates stays under `docs/api/`; nothing in the knowledge
base is renamed or moved to suit it.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# autodoc imports what it documents, and the packages are not installed on a
# Read the Docs builder -- only docs/requirements.txt is.
sys.path.insert(0, str(REPO))


def _release() -> str:
    """The version, from the git tag, the way hatch-vcs derives it.

    `git describe` is asked first because it is the truth of the checkout being
    built; installed metadata can be stale, and on a shallow clone with no tag
    in reach describe fails and the metadata is all there is.
    """
    try:
        described = subprocess.run(
            ["git", "describe", "--tags", "--long", "--match", "v[0-9]*"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        described = ""
    if described:
        tag, distance, commit = described.rsplit("-", 2)
        if distance == "0":
            return tag.lstrip("v")
        return f"{tag.lstrip('v')}+{distance}.{commit}"
    try:
        from importlib.metadata import version

        return version("wish-goldbox")
    except Exception:
        return "0.0.0"


def _description() -> str:
    """The one-line description, read from `pyproject.toml`.

    One source of truth: the landing page says what the packaging says, so
    changing it in one place changes it in both.
    """
    import tomllib

    try:
        with (REPO / "pyproject.toml").open("rb") as f:
            return tomllib.load(f)["project"]["description"]
    except Exception:
        return ""


project = "wish"
author = "Donald Morton"
copyright = "2026, Donald Morton"
release = _release()
version = release.split("+")[0]
rst_prolog = f".. |description| replace:: {_description()}\n"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
    "sphinx.ext.viewcode",
    "myst_parser",
]

# The knowledge base is Markdown; the generated pages are reStructuredText.
source_suffix = {".rst": "restructuredtext", ".md": "markdown"}
# `docs/index.rst` and not `docs/api/index.rst`: Read the Docs serves the root
# URL from `index.html` at the top of the output and fails the build without
# one, whatever Sphinx thinks its root document is. `docs/README.md` stays the
# knowledge base's own index for anyone browsing the repository; this is the
# published landing page, and the two have different jobs.
root_doc = "index"
# **The API reference only.** The knowledge base under `docs/` is written for
# somebody reading the repository, is full of relative links into the source,
# and is not what a published reference is for. Excluding it here rather than
# just dropping it from a toctree is what stops Sphinx building 65 orphan
# pages and warning about every one of them.
exclude_patterns = [
    "_build",
    "Thumbs.db",
    ".DS_Store",
    "*.md",
    "README.md",
]

# Cheaper than putting PyQt6 on the builder: the docstrings are what is being
# published, and none of them need Qt to be resolvable. See issue #44.
autodoc_mock_imports = ["PyQt6"]
autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
}
# Qt is mocked, and a mocked base class costs a subclass its constructor
# signature -- every window would read `(*args, **kwargs)`. Documenting
# `__init__` as a member of its own gets the real one back.
autodoc_class_signature = "separated"
autodoc_typehints = "description"
autodoc_preserve_defaults = True
# Two classes are called `Party`; unqualified annotations cannot say which.
autodoc_typehints_format = "fully-qualified"
autosummary_generate = True

napoleon_google_docstring = True
napoleon_numpy_docstring = False
# Without this a dataclass's `Attributes:` block and its annotations are both
# documented, and every field warns about a duplicate description.
napoleon_use_ivar = True

# The docstrings in this project are Markdown, and autodoc hands them to a
# reStructuredText parser. Making the default role `literal` is what makes
# `single backticks` come out as code rather than as an italic title.
default_role = "literal"

# The knowledge base links to files that are not documents (LICENSE, source
# under goldbox/, GitHub URLs); myst resolves what it can and the rest are plain
# links.
myst_heading_anchors = 3
suppress_warnings = ["myst.header", "myst.xref_missing", "autosummary"]

intersphinx_mapping = {"python": ("https://docs.python.org/3", None)}

html_theme = "furo"
html_title = f"wish {version}"
html_static_path = []


# ---------------------------------------------------------------------------
# The docstrings in this project are Markdown -- backticks, ``**bold**``, and
# GFM pipe tables -- because they are read in an editor far more often than in
# a browser. autodoc hands them to a reStructuredText parser, which reads a
# pipe table as a line block and the ``|---|---|`` rule as an undefined
# substitution. Rewriting the tables on the way past is what keeps the source
# in the form its readers want and still gets a table out of Sphinx.
#
# Nothing else about the Markdown needs translating: emphasis is spelt the same
# way in both, and ``default_role`` above covers the backticks.

_TABLE_RULE = re.compile(r"^\|[\s:|-]+\|$")


def _pipe_row(line: str) -> list[str] | None:
    line = line.strip()
    if not (line.startswith("|") and line.endswith("|") and len(line) > 1):
        return None
    return [cell.strip() for cell in line[1:-1].split("|")]


def _as_list_table(rows: list[list[str]], indent: str) -> list[str]:
    width = max(len(row) for row in rows)
    out = [f"{indent}.. list-table::", f"{indent}   :header-rows: 1", ""]
    for row in rows:
        row = row + [""] * (width - len(row))
        for n, cell in enumerate(row):
            bullet = "*" if n == 0 else " "
            out.append(f"{indent}   {bullet} - {cell}" if cell else
                       f"{indent}   {bullet} -")
        out.append("")
    return out


def _convert_tables(lines: list[str]) -> list[str]:
    out: list[str] = []
    n = 0
    while n < len(lines):
        rows: list[list[str]] = []
        start = n
        while n < len(lines) and (row := _pipe_row(lines[n])) is not None:
            if not _TABLE_RULE.match(lines[n].strip()):
                rows.append(row)
            n += 1
        # Two rows and a rule is the smallest thing worth calling a table.
        if len(rows) >= 2 and n - start > len(rows):
            indent = lines[start][: len(lines[start]) - len(lines[start].lstrip())]
            out.extend(_as_list_table(rows, indent))
        else:
            out.extend(lines[start:n])
            if n == start:
                out.append(lines[n])
                n += 1
    return out


def _process_docstring(app, what, name, obj, options, lines):
    converted = _convert_tables(lines)
    if converted != lines:
        lines[:] = converted


def setup(app):
    app.connect("autodoc-process-docstring", _process_docstring)
