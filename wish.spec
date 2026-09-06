# PyInstaller spec for `wish` — one executable, on both platforms.
#
#     pyinstaller wish.spec
#
# A one-folder build, not a one-file one: one-file unpacks itself to a temporary
# directory at every start, which for a Qt application is a visible pause and
# buys nothing that a .tar.gz or a .zip does not already give.
#
# One `EXE` since docs/129-one-binary.md. `wish-cli` used to be built beside it
# on Linux and not on Windows, which was the last platform conditional in this
# file and the place the last packaging bug lived. `wish export` and
# `wish import` are subcommands of the window's own executable now, so the
# Windows build carries them too -- windowed, so whether their output reaches a
# `cmd` window is the console-borrowing path in packaging/wish_main.py, and
# nothing depends on it.
#
# `DATAS` is every file the window reads at run time that is not a Python
# module: the artist's two SVGs today. Each lands under `sys._MEIPASS` at the
# same relative path it has in the checkout, and `goldbox/assets.py` is the
# one place that resolves such a path, so a reader finds the file in either
# tree. This list used to be empty and the header said so -- "there are no
# data files to carry" -- which stopped being true when the artist delivered
# and nothing noticed: the Windows build shipped with no picture in Help >
# About and a black square on the taskbar (#351). `tests/test_assets.py` now
# reads every `asset_path(...)` call out of the source and fails when one
# names a file that is not here.
#
# `editor/character.ui` is not a data file: it is compiled ahead of time into
# `editor/ui_character.py`, and `wish/__main__.py` skips the Designer
# recompile when `tools.genui` is not importable, which it is not here. The
# map notes and settings live in the user's own directories at run time
# (`automap/paths.py`), never beside the executable.

from PyInstaller.utils.hooks import collect_submodules

# The Qt bindings this project does not use, and the science stack PyInstaller
# would otherwise pick up from whatever environment it is run in.
COMMON_EXCLUDES = [
    "tkinter", "matplotlib", "numpy", "IPython", "pytest",
    "PyQt5", "PySide2", "PySide6",
]

# (source in the checkout, directory it lands in under `sys._MEIPASS`).
# `tools/iconproposal.yaml` joins this list when #315 moves
# `goldbox/iconparts.py` onto `goldbox.assets`.
DATAS = [
    ("assets/logo/mark.svg", "assets/logo"),
    ("assets/logo/combo-mark-color.svg", "assets/logo"),
]

window = Analysis(
    ["packaging/wish_main.py"],
    pathex=["."],
    hiddenimports=(
        collect_submodules("goldbox")
        + collect_submodules("editor")
        + collect_submodules("automap")
        + collect_submodules("wish")
        # `tools.wish` is the body of `wish export` and `wish import`, reached
        # by an import inside `main()` that no static scan can see. Named one
        # by one and not `collect_submodules("tools")`: the rest of that
        # directory is discovery scaffolding and would drag VICE, the
        # generators and their dependencies in behind it.
        + ["tools.wish"]
    ),
    datas=DATAS,
    excludes=COMMON_EXCLUDES,
    noarchive=False,
)

# Windows takes the taskbar icon of a *pinned* shortcut, and the icon Explorer
# draws on the file, from the executable's own resource -- not from Qt. The
# running window's icon is `QApplication.setWindowIcon` in `wish/window.py`,
# from the same drawing; both are needed and neither substitutes for the other.
# PyInstaller ignores this on Linux. `tools/genicons.py` writes the file and
# `tests/test_appicon.py` fails the build if it has drifted from the glyph.
ICON = "assets/wish.ico"

exe = EXE(
    PYZ(window.pure),
    window.scripts,
    [],
    exclude_binaries=True,
    name="wish",
    icon=ICON,
    console=False,
    disable_windowed_traceback=False,
    strip=False,
    upx=False,
)

coll = COLLECT(exe, window.binaries, window.datas, strip=False, upx=False,
               name="wish")
