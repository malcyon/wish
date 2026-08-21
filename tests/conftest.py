"""Make Qt's garbage collection happen between tests, not during one.

The suite built windows in roughly a hundred tests and segfaulted about one run
in three, always inside `findChild` in a constructor. That is the classic PyQt
failure: a widget from an earlier test becomes unreachable, CPython collects it
at whatever moment it likes, and the C++ object goes away while Qt is walking
the object tree for somebody else.

Collecting after every test makes the moment predictable. It does not make the
suite slower in any way worth measuring, and it turns an intermittent crash into
no crash at all.
"""

from __future__ import annotations

import gc

import pytest


@pytest.fixture(autouse=True)
def _collect_between_tests():
    yield
    gc.collect()
