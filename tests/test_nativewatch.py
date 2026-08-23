"""The native message watch: off everywhere but Windows, and cheap when idle.

It exists because three fixes for a popup that closes itself were reasoned from
Linux and all three were wrong, and a standalone probe on Windows cleared the
last Qt-level suspect. See `wish/nativewatch.py`.
"""

from __future__ import annotations

import logging

from wish import nativewatch


def test_it_does_nothing_off_windows():
    """`install` is a no-op anywhere else, so importing it costs nothing and
    the automapper does not have to know what platform it is on."""
    assert nativewatch.install(object()) is False


def test_it_records_nothing_until_something_asks(caplog):
    """`nativeEventFilter` is called for every message the application gets,
    so the gate is the first thing it checks and the flag is off by default."""
    nativewatch.watch(False)
    filt = nativewatch._Filter()
    with caplog.at_level(logging.INFO, logger="wish.native"):
        assert filt.nativeEventFilter(b"windows_generic_MSG", 0) == (False, 0)
    assert not caplog.records


def test_it_names_a_watched_message_and_ignores_the_rest(caplog):
    """The happy path, with a real `MSG` built here rather than by Windows."""
    import ctypes

    nativewatch.watch(True)
    try:
        filt = nativewatch._Filter()
        for code, expected in ((0x001F, "WM_CANCELMODE"), (0x0200, None)):
            msg = nativewatch._MSG(hwnd=0x1234, message=code, wParam=1,
                                   lParam=2, time=0, pt_x=0, pt_y=0)
            caplog.clear()
            with caplog.at_level(logging.INFO, logger="wish.native"):
                assert filt.nativeEventFilter(
                    b"windows_generic_MSG", ctypes.addressof(msg)) == (False, 0)
            said = " ".join(r.getMessage() for r in caplog.records)
            assert (expected in said) if expected else not caplog.records
    finally:
        nativewatch.watch(False)


def test_another_platforms_event_is_left_alone(caplog):
    """Only `windows_generic_MSG` is a `MSG`. Anything else is not ours to
    read, and reading it as one would fault the process."""
    nativewatch.watch(True)
    try:
        filt = nativewatch._Filter()
        with caplog.at_level(logging.INFO, logger="wish.native"):
            assert filt.nativeEventFilter(b"xcb_generic_event_t", 1) == (False, 0)
        assert not caplog.records
    finally:
        nativewatch.watch(False)


def test_every_watched_message_has_a_name():
    """The log is read by a human; a bare number would not be."""
    assert all(isinstance(k, int) and name.startswith("WM_")
               for k, name in nativewatch.WATCHED.items())
    # The ones the theory actually turns on.
    assert {"WM_CANCELMODE", "WM_CAPTURECHANGED", "WM_ACTIVATE",
            "WM_KILLFOCUS"} <= set(nativewatch.WATCHED.values())
