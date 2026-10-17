"""WinUAE on this Windows machine as a window backend: a probe and one connection.

**The probe lists the pipe directory and opens nothing.** WinUAE accepts one
client at a time, so a probing connect would take the door from a player's other
tool. `connect()` reads through `automap.winuae.WinuaeLocalPipe`, which holds
its handle only while a tab is reading: the target it returns releases the
pipe when the window detaches or when no tab is reading, and a failed connect
releases it too. The target, the cached title and the sweep time survive that,
because the next read opens the pipe again.

`AMIGA_WINUAE` is the row `wish.backends` offers on Windows.
"""

from __future__ import annotations

import os

from automap import amiga, winuae

from .amigalocate import Locator
from .backends import Backend

_transport: winuae.WinuaeLocalPipe | None = None
_locator = Locator()


def present(listdir=None) -> bool:
    """Is a WinUAE pipe listed? Never raises, never opens the pipe."""
    try:
        return winuae.present(listdir)
    except Exception:
        return False


class WinuaeTarget(amiga.AmigaTarget):
    """An Amiga target whose `close()` also lets go of the pipe."""

    def close(self) -> None:
        super().close()
        self.debugger.close()

    def release(self) -> None:
        """Let go of the pipe and keep the target, so another tool can connect.

        The next read opens the pipe again. A handle still owed a reply is kept,
        as in `close()`.
        """
        self.debugger.close()


def reset() -> None:
    """Release the pipe and forget the title found."""
    global _transport
    if _transport is not None:
        _transport.close()
    _transport = None
    _locator.forget()


#: Names the WinUAE pipe Wish opens, for test runs where another lane's emulator
#: may own the lowest name. A permanent test switch like `WISH_DEBUG`, not a
#: feature flag; its value is a pipe name, so the truthiness rule does not apply.
PIPE_ENV = "WISH_WINUAE_PIPE"

#: Names the run receipt of the lane whose emulator Wish follows, so a restart that
#: takes another pipe name is still found and another run's emulator never is. A
#: permanent test switch like `PIPE_ENV`, and it wins over it; its value is a path.
RUN_ENV = "WISH_WINUAE_LANE_RECEIPT"


def _lane_pipe(path: str, alive) -> str | None:
    """The pipe a lane's run receipt names, or None while it names no live emulator.

    The receipt is written in two steps and deleted on stop, so a missing file, a
    final line without its line ending, no `pipe`, or a dead `pid` all mean the
    emulator is not there yet or any more.
    """
    try:
        with open(path, encoding="utf-8", newline="") as handle:
            text = handle.read()
    except (OSError, UnicodeError):
        return None
    lines = text.split("\n")
    lines.pop()  # whatever follows the last line ending is a write in progress
    fields = {}
    for line in lines:
        key, found, value = line.rstrip("\r").partition("=")
        if found:
            fields[key] = value
    pid, pipe = fields.get("pid", ""), fields.get("pipe", "")
    if not pid.isdecimal() or "started" not in fields:
        return None
    if not winuae._NAME.fullmatch(pipe) or not alive(int(pid)):
        return None
    return pipe


def connect(pipes=winuae.winuae_pipes, factory=winuae.WinuaeLocalPipe,
            locator: Locator | None = None, alive=None) -> WinuaeTarget:
    """A target on the running Amiga, or a `NotConnected` saying what is missing.

    Uses the first pipe WinUAE created, the one `WISH_WINUAE_PIPE` names, or the one the run receipt named by
    `WISH_WINUAE_LANE_RECEIPT` records, which wins. Raises `amiga.PipeError` when there is
    none, when WinUAE does not answer, and when no known title is loaded yet.
    """
    global _transport
    names = pipes()
    if not names:
        raise amiga.PipeError("There is no WinUAE pipe.")
    receipt = os.environ.get(RUN_ENV, "").strip()
    name = os.environ.get(PIPE_ENV, "").strip()
    if receipt:
        if alive is None:
            from automap.amigatrip import _windows_alive as alive
        name = _lane_pipe(receipt, alive)
        if name is None:
            raise amiga.PipeError("There is no WinUAE pipe.")
        if name not in names:
            raise amiga.PipeError(f"There is no WinUAE pipe called {name}.")
    elif name:
        if not winuae._NAME.fullmatch(name) or name not in names:
            raise amiga.PipeError(f"There is no WinUAE pipe called {name}.")
    else:
        name = names[0]
    if _transport is None or _transport.pipe != name:
        reset()
        _transport = factory(pipe=name)
    locator = locator or _locator
    try:
        return locator.target(_transport.read_memory, _transport,
                              factory=WinuaeTarget)
    except locator.paused:
        # The sweep goes on at the next tick; closing would reopen the pipe
        # (and write its log lines) once per tick for nothing.
        raise
    except Exception:
        _transport.close()
        raise


#: The row `wish.backends._amiga_winuae()` offers on Windows. The probe
#: lists the pipe directory and never opens the pipe, and a read is one debugger
#: command run between two emulated instructions (`WinuaeLocalPipe.halts_machine`
#: is False), hence `disturbs` False and the same 200 ms as VICE and FS-UAE.
#: `verified` is True because WinUAE's reads were confirmed on a live emulator
#: (`#37 (Automap the Amiga version, not just the C64)`).
AMIGA_WINUAE = Backend(
    name="WinUAE (Amiga)",
    short_name="WinUAE",
    probe=present,
    connect=connect,
    setup_hint="Run the game in WinUAE on this computer.",
    default_interval_ms=200,
    disturbs=False,
    verified=True,
)
