#!/usr/bin/env python3
"""Which classes hold which, read out of the AST the way `pyreverse` does.

`tools/classdiagram.py` draws the picture and needs `pylint`, which is not a
dependency of `wish` and must not become one of `.venv`. This answers the one
question that gets asked of the picture without drawing it: **for a named
class, which annotated attributes anywhere in a package are of that type?**
Those annotations are what `pyreverse` turns into an aggregation edge, so a
class with none is drawn alone whatever else refers to it.

    tools/classedges.py Title goldbox
    tools/classedges.py Title goldbox automap        # more than one package
    tools/classedges.py --all goldbox                # every class-to-class edge

`#470 (Give the project a neutral title beside its neutral character record,
with one port per platform a title shipped on)` asks it at every stage: the
whole refactor is meant to put the relationships between a title, its ports
and its containers into the types, and until an annotation names `Title` a
`goldbox/`-scoped diagram draws `Title` with no edges at all. Stages 1 to 6
each answered "still none"; stage 7 is where `goldbox.c64_save.C64Container`
gained `rules: Title`.

## What counts as an edge, and what this deliberately misses

An **annotated class-body attribute** (a dataclass field, or a bare
`x: Title`) and an annotated assignment inside a method. That is `pyreverse`'s
own rule, so the count here is the count there.

Not counted, and each is a real relationship the picture does not draw
either: a duck-typed parameter (`goldbox.titles.race_table` takes
`'Title | object | str | None'` and is a function rather than a class), a
module-level binding (`TITLES: tuple[Title, ...]`), a dict of them, and an
attribute assigned with no annotation. A union is counted, and reported with
the annotation as written, so `Title | None` is visible as the weaker claim
it is.

**A bare class name is matched, not resolved.** `tools/livecheck.py` defines
its own `Title` dataclass, so a run over `tools/` finds a different class with
the same name. Read the file column before believing a hit.
"""
from __future__ import annotations

import argparse
import ast
import pathlib

#: One hit: the module, the class it is a field of, the field, the annotation
#: exactly as it is written, and whether the annotation is a plain name.
Edge = tuple[str, str, str, str, bool]


def _annotation(node: ast.AST) -> str:
    return ast.unparse(node)


def _mentions(annotation: str, name: str) -> bool:
    """Does this annotation name that class, as a name rather than a string?

    Matched on the dotted tail so `c64_save.Container` and `Container` both
    hit, and on whole words so `Title` does not match `TitleRow`.
    """
    for part in annotation.replace("|", " ").replace("[", " ").replace(
            "]", " ").replace(",", " ").replace("'", " ").replace(
                '"', " ").split():
        if part.split(".")[-1] == name:
            return True
    return False


def edges_in(path: pathlib.Path) -> list[Edge]:
    """Every annotated attribute of every class in one module."""
    tree = ast.parse(path.read_text(), filename=str(path))
    out: list[Edge] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in ast.walk(node):
            if not isinstance(stmt, ast.AnnAssign):
                continue
            if not isinstance(stmt.target, ast.Name):
                continue
            written = _annotation(stmt.annotation)
            out.append((path.stem, node.name, stmt.target.id, written,
                        isinstance(stmt.annotation, (ast.Name, ast.Attribute))))
    return out


def edges(roots: list[pathlib.Path]) -> list[Edge]:
    found: list[Edge] = []
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            found.extend((f"{root.name}/{module}", *rest)
                         for module, *rest in edges_in(path))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("name", nargs="?",
                        help="the class to look for, by its bare name")
    parser.add_argument("packages", nargs="+", type=pathlib.Path)
    parser.add_argument("--all", action="store_true",
                        help="every annotated attribute, not one class's")
    args = parser.parse_args(argv)

    found = edges(args.packages)
    if not args.all:
        if args.name is None:
            parser.error("give a class name, or --all")
        found = [e for e in found if _mentions(e[3], args.name)]

    for module, owner, field, written, plain in sorted(found):
        mark = "" if plain else "   (union or subscript)"
        print(f"{module}.{owner}.{field}: {written}{mark}")
    what = args.name if not args.all else "annotated attribute"
    where = ", ".join(str(p) for p in args.packages)
    print(f"\n{len(found)} {what} edge(s) in {where}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
