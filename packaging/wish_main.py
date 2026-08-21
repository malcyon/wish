"""PyInstaller's entry script.

A frozen build needs a plain script to start from, not a `-m` module, and the
relative imports in `wish/__main__.py` only work when it is imported as part of
its package. This is that one line of indirection and nothing else.
"""

import sys

from wish.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
