"""The imported test modules are frozen out of the per-test collection.

`tests/conftest.py`'s `pytest_collection_finish` hook does the freezing. The
interpreter starts with a few hundred objects already in the permanent
generation, so `gc.get_freeze_count() > 0` holds without the hook; the tests
ask instead where a collected module and an object built during a test each
are.
"""
from __future__ import annotations

import gc
import sys
import weakref


def test_a_collected_test_module_is_out_of_the_collectors_walk():
    """`gc.get_objects()` leaves the permanent generation out."""
    assert sys.modules[__name__] not in gc.get_objects()


def test_an_object_built_during_a_test_is_in_the_collectors_walk():
    """The contrast that makes the first test mean something."""

    class Built:
        pass

    built = Built()
    assert built in gc.get_objects()


def test_a_cycle_built_after_the_freeze_is_still_collected():
    """The per-test `gc.collect()` still reaches what a test builds."""

    class Node:
        pass

    a, b = Node(), Node()
    a.other, b.other = b, a
    ref = weakref.ref(a)
    del a, b
    gc.collect()
    assert ref() is None
