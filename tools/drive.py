#!/usr/bin/env python3
"""Drive Pool of Radiance running under VICE.

Discovery scaffolding, not part of the packaged library: it talks to a live
emulator and to an X server, so it belongs beside the other tools.

Three things it provides.

**A binary-monitor client** that obeys the two rules the protocol imposes.
Responses are matched by request id, because VICE interleaves unsolicited
events (type ``0x62``, ``rid=0xFFFFFFFF``) into the same stream and a client
that reads one response per request silently returns the *previous* request's
data.  And a connection is opened, used and closed for each burst of work,
because an open connection stops the machine -- nothing advances while the
socket is up.

**Key sending** through XTEST on the nested display.  The game polls the CIA
keyboard matrix directly, so the KERNAL buffer is useless and a press/release
pair faster than the poll interval is missed entirely.  Every key goes down,
holds, comes up, then a gap.

**Screen reading** as screen codes.  The game runs in text mode with its own
character set, so no OCR is needed -- but the screen address moves ($0400 at
boot, $CC00 in game), so it is recomputed from the VIC registers on every
read.  Menu highlighting is a *colour*: the selected row is white (1) against
green (5), and colour RAM is at $D800 whatever the VIC bank.
"""
from __future__ import annotations

import subprocess
import sys
import time

# The monitor client and screen reader moved into the shipping automap package;
# they are re-exported here so this file and its callers keep working.
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from automap.vice import (  # noqa: E402,F401
    CMD_BANKS_AVAILABLE,
    CMD_CHECKPOINT_DELETE,
    CMD_CHECKPOINT_GET,
    CMD_CHECKPOINT_LIST,
    CMD_CHECKPOINT_SET,
    CMD_DUMP,
    CMD_EXIT,
    CMD_MEM_GET,
    CMD_MEM_SET,
    CMD_PING,
    CMD_QUIT,
    CMD_REGISTERS_GET,
    CMD_RESET,
    CMD_UNDUMP,
    COLOUR_RAM,
    MON_HOST,
    MON_PORT,
    RESP_CHECKPOINT,
    SCREEN_COLS,
    SCREEN_ROWS,
    Monitor,
    MonitorError,
    Screen,
    codes_to_text,
    grab_screen,
    is_bitmap,
    read_screen,
    screen_address,
)

MENU_HOLD, MENU_GAP = 0.10, 0.14
TEXT_HOLD, TEXT_GAP = 0.15, 0.28


class Keyboard:
    """XTEST key delivery to the VICE window on the nested display."""

    def __init__(self, display: str = ":7"):
        self.display = display

    def _xdo(self, *args: str) -> None:
        subprocess.run(
            ["xdotool", *args],
            env={"DISPLAY": self.display, "PATH": "/usr/bin:/bin"},
            check=False,
            capture_output=True,
        )

    def key(self, name: str, hold: float = MENU_HOLD, gap: float = MENU_GAP) -> None:
        self._xdo("keydown", name)
        time.sleep(hold)
        self._xdo("keyup", name)
        time.sleep(gap)

    def keys(self, names, hold: float = MENU_HOLD, gap: float = MENU_GAP) -> None:
        for n in names:
            self.key(n, hold, gap)

    def text(self, s: str, hold: float = TEXT_HOLD, gap: float = TEXT_GAP) -> None:
        """Type a string.

        **Lowercased first, and that is not cosmetic.** `xdotool key W` sends
        Shift+w, which the C64 delivers as PETSCII `$D7`; the name-entry
        routine rejects any byte `>= $5B` and silently restarts the prompt.
        That single detail was the whole character-creation dead end.
        """
        for ch in s.lower():
            name = {" ": "space", "-": "minus", "'": "apostrophe", ".": "period"}.get(
                ch, ch
            )
            self.key(name, hold, gap)

    def screenshot(self, path: str) -> bool:
        r = subprocess.run(
            ["import", "-window", "root", path],
            env={"DISPLAY": self.display, "PATH": "/usr/bin:/bin"},
            capture_output=True,
        )
        return r.returncode == 0


# -- waiting ----------------------------------------------------------------


def wait_for(predicate, timeout: float = 30.0, interval: float = 0.5, **kw):
    """Poll the screen until *predicate* likes it.

    Every input burst after a screen change may be swallowed -- the game is
    not reading yet -- so nothing should be sent on the strength of a single
    read.  Returns the Screen that satisfied the predicate, or None.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            scr = grab_screen(**kw)
        except (OSError, MonitorError):
            time.sleep(interval)
            continue
        if predicate(scr):
            return scr
        time.sleep(interval)
    return None


def wait_for_text(needle: str, timeout: float = 30.0, **kw):
    return wait_for(lambda s: s.contains(needle), timeout=timeout, **kw)


def select_by_colour(kbd: Keyboard, target_row: int, timeout: float = 10.0) -> bool:
    """Move the menu highlight onto *target_row* and press Return.

    Driven by where the white row actually is, not by counting presses from
    an assumed starting point.
    """
    for _ in range(30):
        scr = grab_screen()
        hot = scr.highlighted_rows()
        if not hot:
            return False
        cur = hot[0]
        if cur == target_row:
            kbd.key("Return")
            return True
        kbd.key("Down" if cur < target_row else "Up")
    return False


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "screen":
        with Monitor() as m:
            if is_bitmap(m):
                print("(bitmap mode -- not readable as text)")
            s = read_screen(m)
        print(f"screen at ${s.address:04X}")
        for r, line in enumerate(s.rows()):
            print(f"{r:2d} {s.row_colour(r):2d} |{line}|")
    elif len(sys.argv) > 1 and sys.argv[1] == "clear-checkpoints":
        with Monitor() as m:
            print("deleted", m.checkpoints_clear())
    else:
        print(__doc__)
