"""PyInstaller's entry script for `wish-cli`, which ships on Linux only.

The same one line of indirection as `wish_main.py`, for the same reason: a
frozen build starts from a script. No stream repair here -- this half is built
with `console=True` and, per `wish.spec`, is not built for Windows at all, so
its standard streams are always real.
"""

from __future__ import annotations

import sys

from tools.wish import main

if __name__ == "__main__":
    sys.exit(main())
