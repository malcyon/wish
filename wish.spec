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
# There are no data files to carry. `editor/character.ui` is compiled ahead of
# time into `editor/ui_character.py`, and `wish/__main__.py` skips the Designer
# recompile when `tools.genui` is not importable, which it is not here. The map
# notes and settings live in the user's own directories at run time
# (`automap/paths.py`), never beside the executable.

from PyInstaller.utils.hooks import collect_submodules

# The Qt bindings this project does not use, and the science stack PyInstaller
# would otherwise pick up from whatever environment it is run in.
COMMON_EXCLUDES = [
    "tkinter", "matplotlib", "numpy", "IPython", "pytest",
    "PyQt5", "PySide2", "PySide6",
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
