#!/usr/bin/env python3
"""Generate a Mermaid class diagram for a package or module with `pyreverse`.

`#488 (Generate class diagrams from the code with pyreverse, since the
published docs show every class alone and never how they hold each other)`'s
step 1 was run by hand on 2026-09-10; this is that run turned into a tool, so
the next session can reproduce a picture instead of reading a report about
one. The findings from that run -- the whole-package diagram being a
hairball, which modules fit a page and which do not, the recommended scope
for steps 2 and 3 -- are on the issue and in `work/issue488/README.md`, not
repeated here. This tool does not decide any of that; it only runs the
command.

    tools/classdiagram.py goldbox/titles.py
    tools/classdiagram.py goldbox                        # whole package -- 112 classes, illegible, see the issue
    tools/classdiagram.py goldbox --pyreverse-args "--no-standalone -k"
    tools/classdiagram.py goldbox/amiga_por.py --dirty     # against the working tree, not HEAD
    tools/classdiagram.py goldbox --pyreverse /tmp/pyreverse-env/bin/pyreverse

Runs against a detached worktree at `HEAD` by default, because `goldbox/` is
renamed most nights on this project and a diagram of a half-finished rename
is a picture of nothing. `--dirty` runs against the working tree instead.

## `pylint`, which ships `pyreverse`

Not a dependency of `wish` and must not become one of `.venv` -- several
agents run tests out of that environment. If `pyreverse` cannot be found,
this prints the command to build a separate environment and stops; it does
not install anything itself.

## Two things the 2026-09-10 run found, so nobody has to find them again

* **`-m y` (`--module-names`) is a no-op for `-o mmd`.** It reorders the
  classes written to the file and changes nothing else. It does not
  disambiguate two classes sharing a bare name, which is the reason anybody
  would reach for it -- `goldbox/neutral.py`, `goldbox/c64_codec.py` and
  `goldbox/amiga_pod.py` each define a class called `Report`, and a whole-package
  run collapses all three into one Mermaid node.
* **`-c` needs a fully qualified name.** `-c goldbox.amiga_later.AmigaShape` works;
  `-c AmigaShape` produces no output and no error.

## Pixels

Measuring pixel size needs `@mermaid-js/mermaid-cli`
(`npm install -g @mermaid-js/mermaid-cli`, or pass `--mmdc` at some other
path). Without it, this reports classes and edges and says the pixel figure
needs it -- it does not fail.

## What the tests do not cover

No test here runs `pyreverse` itself -- there is none on this machine, and
the suite must not install one. `tests/test_classdiagram.py` pins the
command line `run_pyreverse` hands to it (`-o mmd`, the target, the output
directory) and the `.mmd` files it is expected to leave behind, so a wrong
flag in this file goes red. **A change in what `pyreverse` itself does with
that command line -- a new version writing a different Mermaid shape, say --
would not be caught here**, and needs a real run to notice.
"""

from __future__ import annotations

import argparse
import pathlib
import shlex
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

REPO = pathlib.Path(__file__).resolve().parent.parent

#: A file `pyreverse` writes for a module with no classes in it: the single
#: line `classDiagram` and nothing under it. Feeding that to a Mermaid
#: renderer is a parse error, not an empty diagram, so this is skipped
#: rather than measured or rendered.
EMPTY_DIAGRAM = "classDiagram"


class ClassDiagramError(Exception):
    """Raised for anything that stops a diagram being produced or read."""


def find_pyreverse(explicit: str | None) -> str:
    """The `pyreverse` executable to run, or a `ClassDiagramError` saying how
    to build one. Never installs anything."""
    if explicit:
        if shutil.which(explicit) or pathlib.Path(explicit).is_file():
            return explicit
        raise ClassDiagramError(f"no pyreverse at {explicit!r}")
    found = shutil.which("pyreverse")
    if found:
        return found
    raise ClassDiagramError(
        "pyreverse needs pylint, which is not in .venv and must not be "
        "added to it. Build one elsewhere and point at it:\n"
        "    python3 -m venv /tmp/pyreverse-env\n"
        "    /tmp/pyreverse-env/bin/pip install pylint\n"
        "    tools/classdiagram.py <target> "
        "--pyreverse /tmp/pyreverse-env/bin/pyreverse"
    )


def add_worktree(repo: pathlib.Path) -> pathlib.Path:
    """A detached worktree at `HEAD`, in its own temporary directory. If
    `git worktree add` fails -- a stale lock, permissions, disk pressure --
    the wrapping directory is removed before the error is re-raised, so a
    failed attempt leaves nothing behind either."""
    parent = pathlib.Path(tempfile.mkdtemp(prefix="classdiagram-"))
    wt = parent / "wt"
    try:
        subprocess.run(
            ["git", "worktree", "add", "-q", "--detach", str(wt), "HEAD"],
            cwd=repo, check=True,
        )
    except subprocess.CalledProcessError:
        shutil.rmtree(parent, ignore_errors=True)
        raise
    return wt


def remove_worktree(repo: pathlib.Path, wt: pathlib.Path) -> None:
    """Removes a worktree `add_worktree` made, including the temporary
    directory that wrapped it -- `git worktree remove` only deregisters
    `wt` itself and leaves that parent directory behind. Never raises --
    called from a `finally`, and a worktree left behind is one the next run
    trips over, not a reason to hide the run's real error."""
    subprocess.run(
        ["git", "worktree", "remove", str(wt), "--force"],
        cwd=repo, check=False,
    )
    shutil.rmtree(wt.parent, ignore_errors=True)


def slug_for(targets: list[str]) -> str:
    """A directory name for a run's output, built from its targets:
    `goldbox/amiga_por.py` becomes `amiga_por`, `goldbox` stays `goldbox`, and
    several targets join on `+`."""
    parts = []
    for target in targets:
        name = pathlib.PurePosixPath(target.replace("\\", "/")).stem
        parts.append(name or target)
    return "+".join(parts) or "run"


def measure_mmd(text: str) -> tuple[int, int]:
    """`(nodes, edges)` in a `pyreverse -o mmd` file: `class NAME { ... }`
    blocks count as nodes, and every other non-empty line outside a block --
    the relation arrows pyreverse writes after the class blocks -- counts as
    an edge. Works for both a `classes_*.mmd` (classes and associations) and
    a `packages_*.mmd` (modules and imports), which pyreverse writes in the
    same shape."""
    nodes = 0
    edges = 0
    depth = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line == EMPTY_DIAGRAM or line.startswith("%%"):
            continue
        if depth > 0:
            if line == "}":
                depth = 0
            continue
        if line.startswith("class "):
            nodes += 1
            if line.endswith("{"):
                depth = 1
            continue
        edges += 1
    return nodes, edges


def render_png(mmdc: str, mmd_path: pathlib.Path) -> pathlib.Path | None:
    """Renders `mmd_path` to a PNG beside it with `mmdc`, or `None` if the
    render fails -- reported, never raised, since a failed render should not
    stop the classes/edges count already in hand."""
    png_path = mmd_path.with_suffix(".png")
    try:
        subprocess.run(
            [mmdc, "-i", str(mmd_path), "-o", str(png_path)],
            check=True, capture_output=True, text=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return None
    return png_path if png_path.is_file() else None


def png_size(png_path: pathlib.Path) -> tuple[int, int] | None:
    """`(width, height)` of a rendered PNG, or `None` if Pillow cannot read
    it -- Pillow is already in `.venv` for the screenshot tools, so this is
    not a new dependency."""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(png_path) as image:
            return image.size
    except OSError:
        return None


def report_diagram(mmd_path: pathlib.Path, mmdc: str | None) -> None:
    """Prints one line: nodes, edges, and pixel size if `mmdc` is available,
    for one `.mmd` file `pyreverse` wrote."""
    kind = "modules" if mmd_path.name.startswith("packages_") else "classes"
    text = mmd_path.read_text()
    nodes, edges = measure_mmd(text)
    if nodes == 0:
        print(f"{mmd_path.name}: skipped -- no {kind}, a bare "
              f"'{EMPTY_DIAGRAM}' line is a Mermaid parse error")
        return
    if mmdc is None:
        print(f"{mmd_path.name}: {nodes} {kind}, {edges} edges "
              f"(pixel size needs @mermaid-js/mermaid-cli)")
        return
    png_path = render_png(mmdc, mmd_path)
    size = png_size(png_path) if png_path else None
    if size is None:
        print(f"{mmd_path.name}: {nodes} {kind}, {edges} edges "
              f"(render with mmdc failed)")
        return
    width, height = size
    print(f"{mmd_path.name}: {nodes} {kind}, {edges} edges, "
          f"{width}x{height} px")


def pyreverse_argv(pyreverse: str, targets: list[str], out_dir: pathlib.Path,
                    extra_args: list[str]) -> list[str]:
    """The command line `run_pyreverse` hands to `pyreverse` -- pulled out
    of `run_pyreverse` so a test can pin it without a real `pyreverse` on
    the machine. `-o mmd` is fixed: it is the one thing this tool depends
    on `pyreverse` doing, and a test that mocks the `subprocess.run` call
    away entirely never notices if it changes."""
    return [pyreverse, "-o", "mmd", "-d", str(out_dir), *extra_args, *targets]


def run_pyreverse(pyreverse: str, root: pathlib.Path, targets: list[str],
                   out_dir: pathlib.Path, extra_args: list[str]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for target in targets:
        if not (root / target).exists():
            raise ClassDiagramError(f"no {target!r} under {root}")
    subprocess.run(pyreverse_argv(pyreverse, targets, out_dir, extra_args),
                    cwd=root, check=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run pyreverse -o mmd over a package or module and "
                     "report classes, edges and pixel size.",
    )
    parser.add_argument("targets", nargs="+",
                         help="a package directory or a module file, "
                              "relative to the repository root, e.g. "
                              "'goldbox' or 'goldbox/amiga_por.py'")
    parser.add_argument("--out", type=pathlib.Path, default=None,
                         help="output directory (default: a new directory "
                              "under work/issue488/tool/)")
    parser.add_argument("--dirty", action="store_true",
                         help="run against the working tree instead of a "
                              "detached worktree at HEAD")
    parser.add_argument("--pyreverse", default=None,
                         help="path to the pyreverse executable, if it is "
                              "not on PATH")
    parser.add_argument("--mmdc", default=None,
                         help="path to the mmdc executable, if it is not "
                              "on PATH (skips PNG rendering if neither is "
                              "found)")
    parser.add_argument("--pyreverse-args", default="",
                         help="extra arguments passed straight to "
                              "pyreverse, e.g. "
                              "'--no-standalone -k -c goldbox.amiga_later.AmigaShape'")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        pyreverse = find_pyreverse(args.pyreverse)
    except ClassDiagramError as exc:
        print(exc, file=sys.stderr)
        return 2

    mmdc = args.mmdc or shutil.which("mmdc")

    out_dir = args.out or (REPO / "work" / "issue488" / "tool"
                            / slug_for(args.targets))

    root = REPO
    wt = None
    try:
        if not args.dirty:
            try:
                wt = add_worktree(REPO)
            except subprocess.CalledProcessError as exc:
                print(f"could not create a worktree at HEAD: {exc}",
                      file=sys.stderr)
                return 1
            root = wt
        try:
            run_pyreverse(pyreverse, root, args.targets, out_dir,
                          shlex.split(args.pyreverse_args))
        except (ClassDiagramError, subprocess.CalledProcessError) as exc:
            print(exc, file=sys.stderr)
            return 1
    finally:
        if wt is not None:
            remove_worktree(REPO, wt)

    mmd_files = sorted(out_dir.glob("*.mmd"))
    if not mmd_files:
        print(f"pyreverse produced nothing in {out_dir}", file=sys.stderr)
        return 1
    for mmd_path in mmd_files:
        report_diagram(mmd_path, mmdc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
