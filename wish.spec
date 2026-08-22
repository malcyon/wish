# PyInstaller spec for the `wish` window, and on Linux for `wish-cli` beside it.
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

import sys

from PyInstaller.utils.hooks import collect_submodules

# Which executables this platform ships. A decision, not an oversight --
# Donald: "Windows users don't need a cli. They're point and click heroes.
# Let's just ship the cli to Linux users." So the Linux .tar.gz carries `wish`
# and `wish-cli`; the Windows .zip carries `wish.exe` and nothing else.
SHIP_CLI = sys.platform != "win32"

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
        collect_submodules("por")
        + collect_submodules("editor")
        + collect_submodules("automap")
        + collect_submodules("wish")
    ),
    excludes=COMMON_EXCLUDES,
    noarchive=False,
)

window_exe = EXE(
    PYZ(window.pure),
    window.scripts,
    [],
    exclude_binaries=True,
    name="wish",
    console=False,
    disable_windowed_traceback=False,
    strip=False,
    upx=False,
)

# The pieces COLLECT is given: the window always, the CLI only where it ships.
parts = [window_exe, window.binaries, window.datas]

if SHIP_CLI:
    # `wish-cli` is `por`, PyYAML and `automap.paths`: no widget, no socket,
    # no Qt. It gets no `collect_submodules` beyond `por` -- whatever it really
    # imports is what it carries.
    cli = Analysis(
        ["packaging/wish_cli_main.py"],
        pathex=["."],
        hiddenimports=collect_submodules("por"),
        excludes=COMMON_EXCLUDES,
        noarchive=False,
    )
    # Asserted rather than excluded. `excludes=["PyQt6"]` would turn a GUI
    # import in the CLI into a ModuleNotFoundError at run time, on a user's
    # machine; this stops the build here, and names what dragged Qt in.
    qt = sorted({name.split(".")[0] for name, *_ in cli.pure
                 if name.split(".")[0].startswith(("PyQt", "PySide"))})
    if qt:
        raise SystemExit(f"wish-cli must not import Qt, but imports {qt}")
    cli_exe = EXE(
        PYZ(cli.pure),
        cli.scripts,
        [],
        exclude_binaries=True,
        name="wish-cli",
        console=True,
        strip=False,
        upx=False,
    )
    # Into the *same* COLLECT, so the folder holds one copy of Qt and one copy
    # of libpython. Two COLLECTs would ship a second 150 MB of Qt to a program
    # that does not import it.
    parts += [cli_exe, cli.binaries, cli.datas]

coll = COLLECT(*parts, strip=False, upx=False, name="wish")
