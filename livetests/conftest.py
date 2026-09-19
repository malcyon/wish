"""Environment for the tests that start an emulator or talk to a device.

`tests/conftest.py` is not loaded here, and none of what these tests import
needs its fixtures, so the two things they do need are set up again: the
repository root on `sys.path`, and no real window on whoever is logged in.
"""

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

# Forced rather than defaulted, as in `tests/conftest.py`: a desktop session
# exports its own `QT_QPA_PLATFORM`, and a default would leave it in place.
# `WISH_TEST_PLATFORM` is the one way to mean something else.
os.environ["QT_QPA_PLATFORM"] = os.environ.get("WISH_TEST_PLATFORM", "offscreen")
