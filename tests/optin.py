"""The one rule for the environment variables that opt a test in to an emulator
or a device.

Those tests boot DOSBox or touch a C64 Ultimate, so they stay off unless
somebody asks. `TRUE` is `wish/debugmode.py`'s tuple, copied: anything else --
an empty string, `0`, `off`, `no` -- is off, so a variable exported once and
forgotten does not start an emulator.
"""

from __future__ import annotations

import os

TRUE = ("1", "true", "yes", "on")


def opted_in(name: str) -> bool:
    """Whether the environment variable `name` asks for the opt-in test."""
    return os.environ.get(name, "").strip().lower() in TRUE
