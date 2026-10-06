"""WinUAE on this Windows machine as a window backend: a probe and one connection.

**The probe lists the pipe directory and opens nothing.** WinUAE accepts one
client at a time, so a probing connect would take the door from a player's other
tool. `connect()` reads through `automap.winuae.WinuaeLocalPipe`, which holds
its handle only while a tab is reading: the target it returns releases the
pipe when the window detaches or when no tab is reading, and a failed connect
releases it too. The target, the cached title and the sweep time survive that,
because the next read opens the pipe again.

`AMIGA_WINUAE` is the row `wish.backends` offers behind
`WISH_EXPERIMENTAL_AMIGA_WINUAE`.
"""

from __future__ import annotations

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


def connect(pipes=winuae.winuae_pipes, factory=winuae.WinuaeLocalPipe,
            locator: Locator | None = None) -> WinuaeTarget:
    """A target on the running Amiga, or a `NotConnected` saying what is missing.

    Uses the first pipe WinUAE created. Raises `amiga.PipeError` when there is
    none, when WinUAE does not answer, and when no known title is loaded yet.
    """
    global _transport
    names = pipes()
    if not names:
        raise amiga.PipeError("There is no WinUAE pipe.")
    if _transport is None or _transport.pipe != names[0]:
        reset()
        _transport = factory(pipe=names[0])
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


#: The row `wish.backends._amiga_winuae()` offers behind its flag. The probe
#: lists the pipe directory and never opens the pipe, and a read is one debugger
#: command run between two emulated instructions (`WinuaeLocalPipe.halts_machine`
#: is False), hence `disturbs` False and the same 200 ms as VICE and FS-UAE.
#: `verified` is True because WinUAE's reads were confirmed on a live emulator
#: (`#37 (Automap the Amiga version, not just the C64)`); the Python pipe client
#: itself has still to be run against a real WinUAE, which is what the
#: experimental flag is for.
AMIGA_WINUAE = Backend(
    name="WinUAE (Amiga)",
    probe=present,
    connect=connect,
    setup_hint="Run the game in WinUAE on this computer.",
    default_interval_ms=200,
    disturbs=False,
    verified=True,
)
