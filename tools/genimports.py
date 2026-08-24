#!/usr/bin/env python3
"""Module-level import edges inside one package, read out of the AST.

The dependency graph in `docs/117-save-conversion.md` is checked with this
rather than drawn by hand, because a hand-drawn one is only ever true on the
day it was drawn -- and the thing it exists to catch, a codec importing
another codec, is exactly the edge somebody adds without noticing.

    python3 tools/genimports.py            # the edge list
    python3 tools/genimports.py --mermaid  # the fenced block docs/117 holds

An import inside a function or a class body is reported separately: it is a
real edge, but a deferred one, usually there to break a cycle or to keep an
optional dependency off the import path. An import under
`if __name__ == "__main__"` is reported separately again -- it binds only when
the module is run as a script.
"""
from __future__ import annotations

import argparse
import ast
import pathlib
import sys

#: Edge kinds, weakest binding last.
TOP, DEFERRED, SCRIPT = "module-level", "deferred", "script-only"


def _parents(tree: ast.AST) -> None:
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            child._parent = parent  # type: ignore[attr-defined]


def _kind(node: ast.AST) -> str:
    """Where in the module this import sits, and so how strongly it binds."""
    at = getattr(node, "_parent", None)
    while at is not None:
        if isinstance(at, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return DEFERRED
        if isinstance(at, ast.If) and ast.dump(at.test).find("__main__") >= 0:
            return SCRIPT
        at = getattr(at, "_parent", None)
    return TOP


def edges(package: pathlib.Path) -> list[tuple[str, str, str]]:
    """`(source, destination, kind)` for every intra-package import."""
    modules = {p.stem for p in package.glob("*.py")}
    found: set[tuple[str, str, str]] = set()
    for path in sorted(package.glob("*.py")):
        tree = ast.parse(path.read_text(), str(path))
        _parents(tree)
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.level == 1:
                if node.module is None:          # from . import a, b
                    targets = [a.name for a in node.names if a.name in modules]
                elif node.module in modules:     # from .a import x
                    targets = [node.module]
            elif isinstance(node, ast.Import):   # import por.a
                targets = [a.name.split(".")[1] for a in node.names
                           if a.name.startswith(package.name + ".")
                           and a.name.split(".")[1] in modules]
            for target in targets:
                found.add((path.stem, target, _kind(node)))
    # One edge per pair, at the strongest binding it was seen with.
    rank = {TOP: 0, DEFERRED: 1, SCRIPT: 2}
    best: dict[tuple[str, str], str] = {}
    for source, destination, kind in found:
        pair = (source, destination)
        if pair not in best or rank[kind] < rank[best[pair]]:
            best[pair] = kind
    return sorted((s, d, k) for (s, d), k in best.items())


def mermaid(found: list[tuple[str, str, str]]) -> str:
    lines = ["```mermaid", "graph LR"]
    for source, destination, kind in found:
        arrow = {TOP: "-->", DEFERRED: "-.->", SCRIPT: "-.->"}[kind]
        label = "" if kind == TOP else f"|{kind}|"
        lines.append(f"  {source} {arrow}{label} {destination}")
    lines.append("```")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("package", nargs="?", default="por",
                    help="package directory (default: por)")
    ap.add_argument("--mermaid", action="store_true",
                    help="print a fenced mermaid graph instead of a list")
    args = ap.parse_args(argv)
    found = edges(pathlib.Path(args.package))
    if args.mermaid:
        print(mermaid(found))
        return 0
    for source, destination, kind in found:
        print(f"{source} -> {destination}"
              + ("" if kind == TOP else f"  ({kind})"))
    return 0


if __name__ == "__main__":  # pragma: no cover - a script
    sys.exit(main())
