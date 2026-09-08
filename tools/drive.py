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

**And those registers are read out of the io bank, not the default one**, or
the answer is a byte of RAM every time the game banks the chips out mid-load
-- `#336`, and the block above `BankedRead` has the measurement.
"""
from __future__ import annotations

import subprocess
import sys
import time

# The monitor client and screen reader moved into the shipping automap package;
# they are re-exported here so this file and its callers keep working.
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from automap import screen as _screen  # noqa: E402
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
    CMD_REGISTERS_SET,
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
)

MENU_HOLD, MENU_GAP = 0.10, 0.14
TEXT_HOLD, TEXT_GAP = 0.15, 0.28


# -- reading the screen when the game has banked the I/O chips out ----------
#
# `automap/screen.py` computes the screen address from `$D018` and `$DD00`
# rather than assuming `$0400`, and that arithmetic is right.  What was wrong
# is **which memory those two reads come out of**.  The binary monitor's
# default bank is whatever the CPU can see at that instant, and the game
# spends part of every load at `$01 = $30` -- RAM everywhere and no I/O at
# all.  A `$D018` read in that state is a byte of RAM, and the address
# computed from it is somewhere nothing is displaying.  The reader then
# reports on it without a word, which is `#336`: forty spaces off row 24
# while the display says `INSERT SIDE # 2, AND PRESS ANY KEY.`
#
# Measured on pool slot 0, 2026-09-07, over 1,035 polls of one driven boot.
# Four polls found `$01 = $30`, and in all four the default bank answered
# `$D018 = $0C` and `$DD00 = $70` -- the screen at `$C000` -- where the chips
# held `$79` and `$C4`, which is `$DC00`.  `$D011` was a byte of RAM with
# them, `$36` every time, and on the first of the four the chips held `$0B`:
# text mode with the display blanked, read as a bitmap, so the reading was
# thrown away rather than used.  The other 1,031 polls agreed exactly, which
# is why this is intermittent rather than broken.
#
# So every read here says which memory it means:
#
#   * the VIC and CIA registers, and colour RAM, come out of the **io** bank,
#     which is the chips whatever `$01` says;
#   * the screen matrix comes out of the **ram** bank, because the VIC always
#     fetches RAM -- in bitmap mode this game's matrix sits at `$DC00`, where
#     a default-bank read answers CIA 1 rather than the screen.

#: `MON_CMD_BANKS_AVAILABLE`'s answer, per monitor.  The ids are a property of
#: the VICE build rather than of the running machine, so this is asked once and
#: kept: on the build here it is
#: `default 0, cpu 0, ram 1, rom 2, io 3, cart 4`, and it is read rather than
#: written down because another build may number them differently.
_BANKS: dict[tuple[str, int], dict[str, int]] = {}


class ScreenUnreadable(MonitorError):
    """The screen could not be *located*, as against found and blank.

    A `MonitorError` so that every caller which already degrades on a failed
    read degrades the same way here.  The distinction it carries is the one
    `#336` is about: a caller can tell "the game is showing nothing" from "I
    do not know where the screen is", which forty spaces never let it.
    """


def bank_ids(mon: Monitor) -> dict[str, int]:
    """`{name: id}` for every bank this VICE offers, from the machine itself.

    An empty dict when the command is unsupported, which is a state
    `BankedRead` handles rather than one that raises here.
    """
    key = (mon.host, mon.port)
    if key in _BANKS:
        return _BANKS[key]
    found: dict[str, int] = {}
    try:
        resp = mon.command(CMD_BANKS_AVAILABLE)
        count = int.from_bytes(resp[:2], "little")
        off = 2
        for _ in range(count):
            size = resp[off]
            bank = int.from_bytes(resp[off + 1 : off + 3], "little")
            name_len = resp[off + 3]
            name = resp[off + 4 : off + 4 + name_len].decode("ascii", "replace")
            found[name] = bank
            off += size + 1
    except (MonitorError, IndexError, OSError):
        found = {}
    _BANKS[key] = found
    return found


#: `$01` bits 2-0 that leave the I/O chips visible to the CPU.  The other five
#: values put RAM or the character ROM at `$D000`, which is what makes a
#: default-bank register read a lie.
IO_IN = (5, 6, 7)


class BankedRead:
    """Two readers over one monitor: the chips, and the RAM the VIC sees."""

    def __init__(self, mon: Monitor):
        self.mon = mon
        ids = bank_ids(mon)
        self.io = ids.get("io")
        self.ram = ids.get("ram")
        if self.io is None or self.ram is None:
            # No named banks to ask for.  Fall back to what the CPU can see,
            # and refuse to answer when it cannot see the chips rather than
            # computing an address from RAM.
            port = mon.read(0x01, 1)[0]
            if port & 0x07 not in IO_IN:
                raise ScreenUnreadable(
                    f"this VICE offers no named banks and $01 is ${port:02X}, "
                    "so the VIC registers are not readable")
            self.io = self.ram = 0

    def io_read(self, addr: int, length: int) -> bytes:
        return self.mon.read(addr, length, bank=self.io)

    def ram_read(self, addr: int, length: int) -> bytes:
        return self.mon.read(addr, length, bank=self.ram)


def screen_address(mon: Monitor) -> int:
    return _screen.screen_address(BankedRead(mon).io_read)


def is_bitmap(mon: Monitor) -> bool:
    return _screen.is_bitmap(BankedRead(mon).io_read)


def read_screen(mon: Monitor) -> Screen:
    banked = BankedRead(mon)
    addr = _screen.screen_address(banked.io_read)
    return Screen(banked.ram_read(addr, 1000),
                  banked.io_read(COLOUR_RAM, 1000), addr)


def colour_ram(mon: Monitor, row: int | None = None) -> bytes:
    """Colour RAM, whole screen or one row, out of the chips.

    `$D800` is I/O, so a default-bank read of it answers RAM whenever the game
    has banked the chips out -- and colour is how every menu here finds the
    highlighted row.
    """
    all_of_it = bytes(c & 0x0F for c in BankedRead(mon).io_read(COLOUR_RAM, 1000))
    if row is None:
        return all_of_it
    return all_of_it[row * SCREEN_COLS : (row + 1) * SCREEN_COLS]


def grab_screen(**kw) -> Screen:
    """Open a connection, read the screen, close it again."""
    with Monitor(**kw) as mon:
        return read_screen(mon)


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
