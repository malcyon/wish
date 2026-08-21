"""PyInstaller's entry script.

A frozen build needs a plain script to start from, not a `-m` module, and the
relative imports in `wish/__main__.py` only work when it is imported as part of
its package. This is that one line of indirection, and the stream repair below.
"""

import os
import sys

# A windowed build has no console, and since PyInstaller 5.7 that means
# `sys.stdout` and `sys.stderr` are **None** rather than sinks -- deliberately,
# to match `pythonw.exe`. `print` tolerates None and quietly does nothing;
# argparse does not. `_print_message` falls back from a None `file` to a None
# `sys.stderr` and calls `.write` on it, so on Windows `wish.exe --version` and
# every mistyped option died in `AttributeError: 'NoneType' has no attribute
# 'write'` -- shown to the user as PyInstaller's traceback box. Give them
# somewhere harmless to go before anything can write.
for _name in ("stdout", "stderr"):
    if getattr(sys, _name, None) is None:
        setattr(sys, _name, open(os.devnull, "w", encoding="utf-8"))

from wish.__main__ import main  # noqa: E402 - after the streams exist

if __name__ == "__main__":
    sys.exit(main())
