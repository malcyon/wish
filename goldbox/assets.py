"""Where the program's own files are: the artist's SVGs, and anything else
read at run time from the checkout rather than from a Python module.

**One resolver, because the frozen build is a different tree.** In a checkout
`assets/logo/mark.svg` sits beside the packages, and a path built from
`__file__` finds it. A PyInstaller build has no checkout: the modules are
inside an archive, and the files `wish.spec` lists in `datas` are unpacked
under `sys._MEIPASS` instead. On 2026-09-06 the Windows build shipped with
neither -- no `datas`, and two readers each building their own `__file__`
path -- and `QSvgRenderer` on a file that is not there returns an empty
renderer rather than raising, so Help > About drew no picture and the
taskbar drew the icon painter's dark ground with nothing on it:
`#351 (The Windows build shows no logo in About and a black square on the
taskbar, because the artist's SVGs are not in the package)`.

So every reader asks here, and nowhere else builds a path to the checkout
root: `tests/test_assets.py` fails the build if one does. The other half of
the guarantee is in the same file -- every path a reader asks for is checked
against `wish.spec`'s `datas`, so a file this module can find in a checkout
and not in the package is a failing test rather than a black square.

This lives in `goldbox/` rather than `ui/` or `wish/` because `goldbox` is
the bottom of the import order and the next reader is there: `#315 (A frozen
Wish cannot convert a combat figure, because the table it needs lives outside
the package)` is `goldbox/iconparts.py` building the same kind of path to
`tools/iconproposal.yaml`, and it can use this once that file is in `datas`.
"""

from __future__ import annotations

import pathlib
import sys

#: The checkout: the directory the packages sit in, which is also where
#: `assets/` and `tools/` are. Only meaningful when not frozen.
CHECKOUT = pathlib.Path(__file__).resolve().parent.parent


def frozen() -> bool:
    """Is this a PyInstaller build?

    PyInstaller sets both: `sys.frozen` on any bootloader, `sys._MEIPASS` to
    the directory it unpacked `datas` into. Asking for both keeps a
    py2exe-style `frozen` with no `_MEIPASS` from sending a reader to a
    directory that does not exist.
    """
    return bool(getattr(sys, "frozen", False)) and hasattr(sys, "_MEIPASS")


def root() -> pathlib.Path:
    """The directory `assets/` is under: `sys._MEIPASS` in a frozen build,
    the checkout otherwise."""
    if frozen():
        return pathlib.Path(sys._MEIPASS)
    return CHECKOUT


def asset_path(*parts: str) -> pathlib.Path:
    """The path of a file the program reads at run time, by its place under
    the checkout root: `asset_path("assets", "logo", "mark.svg")`.

    Call it with string literals, one per path segment. `tests/test_assets.py`
    reads the calls out of the source to check each file is in `wish.spec`'s
    `datas`, and a path assembled from a variable is one it cannot see.
    """
    return root().joinpath(*parts)
