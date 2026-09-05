#!/usr/bin/env python3
"""Census: which `tools/` scripts leave `tools/` on `sys.path` after import.

    tools/pathleak.py              # the leaking scripts, one per line
    tools/pathleak.py --all        # every script, with what it did
    tools/pathleak.py --shadow     # only the ones that would capture `wish`

A script in here that wants to reach a sibling by its bare name -- `import
dosbox` rather than `from tools import dosbox` -- does it by inserting its own
directory at the front of `sys.path`, and none of them takes it off again. That
is harmless on its own and not harmless in a process that later imports
something whose name a file in `tools/` also has. `tools/wish.py` is the file
that has one, and `#259 (A cold test run intermittently loses the wish package
to tools/wish.py, and a different test fails each time)` is what it cost: a
different test failed on each cold `pytest -n auto` run, because which worker
imported which file first decided whether the name `wish` was already taken.

`tools/__init__.py` now binds the real package before any script body runs, so
the shadow cannot form via `from tools import x`. The **leak itself** is still
there. Measured at `c1bbe6f` on 2026-09-04: **34 of 119** scripts leave
`tools/` on `sys.path`, and **7 of those** capture `wish` when imported by file
with the guard out of the way -- `cursewarp`, `d6502check`, `dosdisk`,
`mapmarker`, `newecl`, `outdoorsgrep` and `overlay`. Run it again rather than
trusting those numbers; every script added since moves them.

The two modes ask different questions. Without `--shadow` a script comes in as
`tools.x`, which is how a test reaches it and which runs `tools/__init__.py`
first; with `--shadow` it comes in **by file path**, the way `python
tools/x.py` runs, where nothing has bound the name yet. `tools/wish.py` is
excluded from that count, since importing it by file under the name `wish` is
the shadow rather than a case of it.

Each script is imported in its own subprocess, so nothing here is affected by
what anything else already imported. Reads no game data and writes nothing.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent

#: Run in the child: import one script, then report what `sys.path` and the
#: name `wish` look like afterwards. `--no-guard` strips `tools/__init__.py`'s
#: binding by importing the file directly rather than through the package,
#: which is how a script run as `python tools/x.py` reaches it.
_CHILD = """
import json, sys
sys.path.insert(0, {root!r})
{importer}
{probe}left = [p for p in sys.path if p == {tools!r}]
idx = sys.path.index({tools!r}) if left else -1
root_idx = sys.path.index({root!r}) if {root!r} in sys.path else -1
w = sys.modules.get("wish")
print("PATHLEAK " + json.dumps({{
    "left": len(left), "tools_at": idx, "root_at": root_idx,
    "wish": getattr(w, "__file__", None),
    "wish_is_package": bool(w is not None and hasattr(w, "__path__")),
}}))
"""

#: Only for `--shadow`: ask for `wish` the way a poisoned process would, once
#: the script under test has had its say about `sys.path`. Under the guard the
#: name is already bound, so asking again would prove nothing.
_PROBE = """
try:
    import wish  # noqa: F401
except ImportError:
    pass
"""

_VIA_PACKAGE = "import importlib\nimportlib.import_module('tools.{name}')\n"
_VIA_FILE = """
import importlib.util
spec = importlib.util.spec_from_file_location({name!r}, {path!r})
mod = importlib.util.module_from_spec(spec)
sys.modules[{name!r}] = mod
spec.loader.exec_module(mod)
"""


def inspect(name: str, guard: bool) -> dict:
    """Import one script in a fresh interpreter and report what it left."""
    importer = (_VIA_PACKAGE.format(name=name) if guard
                else _VIA_FILE.format(name=name, path=str(TOOLS / f"{name}.py")))
    code = _CHILD.format(root=str(ROOT), tools=str(TOOLS), importer=importer,
                         probe="" if guard else _PROBE)
    proc = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT),
                          capture_output=True, text=True, timeout=300)
    for line in proc.stdout.splitlines():
        if line.startswith("PATHLEAK "):
            return json.loads(line[len("PATHLEAK "):])
    return {"error": (proc.stderr.strip().splitlines() or ["no output"])[-1]}


def scripts() -> list[str]:
    return sorted(p.stem for p in TOOLS.glob("*.py") if p.stem != "__init__")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--all", action="store_true",
                    help="every script, not only the leaking ones")
    ap.add_argument("--shadow", action="store_true",
                    help="only the scripts that capture the name `wish` when "
                         "imported by file, the way a directly-run script "
                         "reaches a sibling")
    ap.add_argument("names", nargs="*", metavar="NAME",
                    help="scripts to check (default: all of them)")
    args = ap.parse_args(argv)

    names = args.names or scripts()
    leaking = shadowing = 0
    for name in names:
        row = inspect(name, guard=not args.shadow)
        if "error" in row:
            print(f"{name}: could not import -- {row['error']}")
            continue
        leaks = bool(row["left"])
        shadows = (name != "wish" and row["wish"] is not None
                   and not row["wish_is_package"])
        leaking += leaks
        shadowing += shadows
        if args.shadow:
            if shadows:
                print(f"{name}: `wish` is {row['wish']}")
        elif leaks or args.all:
            print(f"{name}: tools/ at sys.path[{row['tools_at']}], "
                  f"root at [{row['root_at']}]"
                  + ("" if leaks else " -- clean"))
    if args.shadow:
        print(f"\n{shadowing} of {len(names)} capture the name `wish` when "
              f"imported by file (tools/wish.py itself not counted)")
    else:
        print(f"\n{leaking} of {len(names)} leave tools/ on sys.path")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
