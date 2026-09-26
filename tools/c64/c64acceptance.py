#!/usr/bin/env python3
"""Entry point of the old name; `tools/c64/acceptance.py` is the implementation.

Remove this file, and its tests, when `docs/235`, the README and the agent
memories name `acceptance.py` and no open issue's plan cites `c64acceptance.py`.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from tools.c64.acceptance import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
