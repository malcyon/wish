# PyInstaller spec for the `wish` window.
#
#     pyinstaller wish.spec
#
# A one-folder build, not a one-file one: one-file unpacks itself to a temporary
# directory at every start, which for a Qt application is a visible pause and
# buys nothing that a .tar.gz or a .zip does not already give.
#
# There are no data files to carry. `editor/character.ui` is compiled ahead of
# time into `editor/ui_character.py`, and `wish/__main__.py` skips the Designer
# recompile when `tools.genui` is not importable, which it is not here. The map
# notes and settings live in the user's own directories at run time
# (`automap/paths.py`), never beside the executable.

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = (
    collect_submodules("por")
    + collect_submodules("editor")
    + collect_submodules("automap")
    + collect_submodules("wish")
)

a = Analysis(
    ["packaging/wish_main.py"],
    pathex=["."],
    hiddenimports=hiddenimports,
    excludes=[
        # Nothing here draws a chart, opens a notebook or trains anything;
        # PyInstaller picks them up from the environment if they are installed.
        "tkinter", "matplotlib", "numpy", "IPython", "pytest",
        # The Qt bindings this project does not use. PyQt6 is the one.
        "PyQt5", "PySide2", "PySide6",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="wish",
    console=False,
    disable_windowed_traceback=False,
    strip=False,
    upx=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="wish",
)
