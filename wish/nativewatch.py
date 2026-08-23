"""The raw Windows message stream around a popup that closes itself.

Three fixes for "the note popover opens empty and vanishes" were reasoned from
Linux and all three were wrong. A standalone probe on Windows then cleared the
last suspect: a dying `QToolTip` does not take a `Qt::Popup` with it, in six
variations including a genuine OS-level click.

What the application's own log says is that the popover receives a bare `Close`
while still visible and still active, with no mouse event, no `FocusOut` and no
`WindowDeactivate` before it. There is no Qt-level cause, which means the cause
arrives underneath Qt as a native message -- `WM_CANCELMODE`, a lost
`WM_CAPTURECHANGED`, a `WM_ACTIVATE` Qt is translating into a popup dismissal.
This names it instead of narrowing the suspect list further.

Nothing here runs off Windows, and nothing runs unless the debug log is on and
a popover is actually open: `nativeEventFilter` is called for every message the
application receives, so the gate is the first thing it checks.
"""

from __future__ import annotations

import ctypes
import logging
import sys

_log = logging.getLogger("wish.native").info

#: Only the messages that can plausibly dismiss a popup, plus the two that say
#: a window is going away. Everything else is noise at thousands a second.
WATCHED = {
    0x0006: "WM_ACTIVATE",
    0x0007: "WM_SETFOCUS",
    0x0008: "WM_KILLFOCUS",
    0x0010: "WM_CLOSE",
    0x001C: "WM_ACTIVATEAPP",
    0x001F: "WM_CANCELMODE",
    0x0021: "WM_MOUSEACTIVATE",
    0x0086: "WM_NCACTIVATE",
    0x0215: "WM_CAPTURECHANGED",
    0x0231: "WM_ENTERSIZEMOVE",
    0x02A1: "WM_MOUSEHOVER",
    0x02A3: "WM_MOUSELEAVE",
}


class _MSG(ctypes.Structure):
    _fields_ = [("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint),
                ("wParam", ctypes.c_size_t), ("lParam", ctypes.c_ssize_t),
                ("time", ctypes.c_uint),
                ("pt_x", ctypes.c_long), ("pt_y", ctypes.c_long)]


#: Set by whoever is being watched. False costs one attribute read per message.
watching = False


def watch(on: bool) -> None:
    """Start or stop recording. Called around the thing under suspicion."""
    global watching
    watching = on


class _Filter:
    """A `QAbstractNativeEventFilter` in all but the base class.

    The base is imported inside `install` so this module can be read, and
    tested, without Qt.
    """

    def nativeEventFilter(self, kind, message):
        if not watching:
            return False, 0
        # No `try` around the cast. Dereferencing a bad pointer faults the
        # process rather than raising, so an `except` here would be comfort
        # and not protection; what keeps this safe is that Qt only ever hands
        # us a real `MSG` for `windows_generic_MSG`, and that is checked.
        if kind != b"windows_generic_MSG" or not message:
            return False, 0
        msg = ctypes.cast(int(message), ctypes.POINTER(_MSG)).contents
        name = WATCHED.get(msg.message)
        if name is not None:
            _log("native %s hwnd=%#x wParam=%#x lParam=%#x",
                 name, msg.hwnd or 0, msg.wParam, msg.lParam)
        return False, 0


_installed = None


def install(app) -> bool:
    """Attach the filter to this application. True if it is now watching.

    Windows only, and only worth doing with the debug log on -- there is
    nowhere else for what it records to go.
    """
    global _installed
    if sys.platform != "win32" or _installed is not None:
        return _installed is not None
    from PyQt6.QtCore import QAbstractNativeEventFilter

    class Filter(QAbstractNativeEventFilter, _Filter):
        pass

    _installed = Filter()
    app.installNativeEventFilter(_installed)
    _log("native message watch installed")
    return True
