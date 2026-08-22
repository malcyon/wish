"""PyInstaller's entry script for the `wish` window.

A frozen build needs a plain script to start from, not a `-m` module, and the
relative imports in `wish/__main__.py` only work when it is imported as part of
its package. This is that one line of indirection, and the stream repair below.
"""

from __future__ import annotations

import os
import sys

# `AttachConsole(ATTACH_PARENT_PROCESS)`, and the error it returns when the
# process is already attached to one.
_ATTACH_PARENT_PROCESS = -1
_ERROR_ACCESS_DENIED = 5

# Windows' console, once attached. A name rather than a literal because no test
# here can open one: tests/test_packaging.py points it at a temporary file.
_CONSOLE_DEVICE = "CONOUT$"


def _attach_windows_console() -> bool:
    """Borrow the terminal that started us, on Windows. True if we now have one.

    A windowed build (`console=False`) is given no console of its own, so
    `wish.exe --version` typed into cmd or PowerShell had nowhere to print.
    `AttachConsole` attaches us to the parent's console when the parent has
    one; `CONOUT$` is then the file to write to. Started from Explorer there is
    no console to borrow and this fails, which is the devnull case below.
    """
    if sys.platform != "win32":
        return False
    import ctypes

    kernel32 = ctypes.windll.kernel32
    if kernel32.AttachConsole(_ATTACH_PARENT_PROCESS):
        return True
    return kernel32.GetLastError() == _ERROR_ACCESS_DENIED


def _inherited_stream(fd: int):
    """The stream on `fd` if the shell gave us one -- a pipe, or a file.

    `wish.exe --version > out.txt` and every CI runner redirect the standard
    handles, and an inherited handle is real even when the process has no
    console. `fstat` is the cheap test for one.
    """
    try:
        os.fstat(fd)
        return open(fd, "w", encoding="utf-8", buffering=1, closefd=False)
    except OSError:
        return None


def _repair_streams() -> None:
    """Give `sys.stdout` and `sys.stderr` somewhere to go before anything writes.

    Since PyInstaller 5.7 a windowed build gets **None** for both, deliberately,
    to match `pythonw.exe`. `print` tolerates None and quietly does nothing;
    argparse does not -- `_print_message` falls back from a None `file` to a
    None `sys.stderr` and calls `.write` on it, so `wish.exe --version` and
    every mistyped option died in `AttributeError: 'NoneType' object has no
    attribute 'write'`, shown to the user as PyInstaller's traceback box.

    In order of preference: the handle the shell inherited to us, because
    `wish.exe --version > out.txt` means that file and nothing else; then the
    console we can borrow, which is the terminal the user typed into; then
    devnull, which is silence but not a crash, and is what a double-click from
    Explorer gets. Redirect first is not arbitrary -- borrowing the console
    first would send a redirected run to the terminal and leave the file empty.
    """
    missing = [name for name in ("stdout", "stderr")
               if getattr(sys, name, None) is None]
    if not missing:
        return

    console = None  # None until something needs one and we try to borrow it.
    for name in missing:
        stream = _inherited_stream(1 if name == "stdout" else 2)
        if stream is None:
            if console is None:
                console = _attach_windows_console()
            if console:
                try:
                    # There is no CONERR$; both streams go to the one console.
                    stream = open(_CONSOLE_DEVICE, "w", encoding="utf-8",
                                  buffering=1)
                except OSError:
                    console = False
        if stream is None:
            stream = open(os.devnull, "w", encoding="utf-8")
        setattr(sys, name, stream)


_repair_streams()

from wish.__main__ import main  # noqa: E402 - after the streams exist

if __name__ == "__main__":
    sys.exit(main())
