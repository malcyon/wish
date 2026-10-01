"""WinUAE on this Windows machine as a window backend: a probe and one connection.

**The probe lists the pipe directory and opens nothing.** WinUAE accepts one
client at a time, so a probing connect would take the door from a player's other
tool. `connect()` reads through `automap.winuae.WinuaeLocalPipe`, which holds
its handle only while a target is attached: the target it returns releases the
pipe when the window detaches, and a failed connect releases it too. The cached
title and sweep time survive that, because the next read opens the pipe again.

The `Backend` row that offers this to a player is not defined here: its name and
setup hint are interface text and wait for Donald's wording. `wish.backends`
offers it once `AMIGA_WINUAE` exists, behind `WISH_EXPERIMENTAL_AMIGA_WINUAE`.
"""

from __future__ import annotations

from automap import amiga, winuae

from .amigalocate import Locator

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
