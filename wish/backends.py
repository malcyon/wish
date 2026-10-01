"""Which live backends exist, and how to find one that is there.

Discovery used to be one hard-coded TCP probe of `127.0.0.1:6502`, which is
VICE and nothing else. A `Backend` is that knowledge made into data: how to
tell whether one is present, how to attach, what to say when it is not, and how
often it is reasonable to poll it -- the last because a network device on the
end of a cable cannot be asked sixty times a second the way a loopback socket
can.

**A backend that cannot be probed is not offered.** `probe()` is called on a
timer with no emulator running, most of the time, so it must be cheap and it
must never raise: a broken or absent backend disappears from the list rather
than taking the window down with it.

**The Ultimate backend is behind `WISH_EXPERIMENTAL_C64_ULTIMATE`.** It is not
an unfinished feature waiting to be built out -- it works, and it hangs the
game it is reading, because the device stops the 6510 for the length of every
`readmem` and a stop landing inside a disk load loses the transfer beyond
recovery. Donald reproduced it on his own hardware, read the machine over the
REST API while it sat hung, and found the interrupt handler alive and the
game's main loop stopped, almost certainly waiting on a byte the drive will
never send. `automap.busguard`'s guard narrows the window and cannot close it
-- its own stated limit. See `#375 (Wish has to work around the Ultimate
freezing the C64 mid-load, which hangs the game while the automapper follows
along)`.

**Comes off when a player can drive Pool of Radiance on the Ultimate, with the
automapper following, through a disk load, without the main loop stopping.**
Not "when the guard is in place" -- the guard is already in place and this is
what the guard was found not to be enough. `#375` is where that gets settled.

With the flag unset, `backends()` never includes it: no menu entry, no probe,
no delay and no error for somebody with no Ultimate on the network, and the
application behaves as though the device is not there at all. This does not
touch `tools/c64/c64u*.py`, which are how the hang itself gets investigated and
stay unaffected by the flag.

**The Amiga backend is behind `WISH_EXPERIMENTAL_AMIGA_FSUAE`**, and with it
unset it is absent in the same way: no entry, no probe, no import of
`wish.fsuae`. `docs/96-live-memory-automapper.md` says what it reads and what
the fork needs.

**The WinUAE backend is behind `WISH_EXPERIMENTAL_AMIGA_WINUAE`** and is absent
the same way, with `wish.winuae.AMIGA_WINUAE` as its row.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from automap.paths import vice_settings_hint
from automap.target import Target, ViceTarget, monitor_listening

from . import debuglog

#: `WISH_EXPERIMENTAL_C64_ULTIMATE`: see the module docstring for what this
#: gates and the condition that removes it.
ULTIMATE_ENV = "WISH_EXPERIMENTAL_C64_ULTIMATE"

#: Anything else -- an empty string, `0`, `off` -- is off, matching
#: `wish/debugmode.py`. A variable somebody exported once and forgot must not
#: put a backend that hangs the game in front of them.
TRUE = ("1", "true", "yes", "on")


#: `WISH_EXPERIMENTAL_AMIGA_FSUAE`: the Amiga row that reads a patched FS-UAE.
#: Same truthiness rule as `TRUE` above.
#:
#: **Comes off when closing Wish no longer costs the player their game -- the
#: fork shuts its listening socket when a client disconnects, so a background
#: helper (`automap.fsuaehelper`) holds the connection and Wish reads through it
#: -- and when a party
#: has been walked under the window on each title that has a row in
#: `automap.amiga.MACHINES`, which is the check `#34 (Validate the live
#: automapper tab per title)` asks for.** `#37 (Automap the Amiga version, not
#: just the C64)` is where that gets settled.
#:
#: The flag also decides whether Wish names Pools of Darkness from its Amiga
#: disks and offers its folder row.
AMIGA_FSUAE_ENV = "WISH_EXPERIMENTAL_AMIGA_FSUAE"

#: `WISH_EXPERIMENTAL_AMIGA_WINUAE`: the Amiga row that reads WinUAE on the same
#: Windows machine, through its named pipe. Same truthiness rule as `TRUE`.
#:
#: **Comes off when a party has been walked under the window with WinUAE on
#: Windows on each title that has a row in `automap.amiga.MACHINES`, which is
#: the check `#34 (Validate the live automapper tab per title)` asks for.**
#: `#37 (Automap the Amiga version, not just the C64)` is where that gets
#: settled. Like the FS-UAE flag it also decides whether Wish names Pools of
#: Darkness from its Amiga disks and offers its folder row.
AMIGA_WINUAE_ENV = "WISH_EXPERIMENTAL_AMIGA_WINUAE"


def ultimate_enabled() -> bool:
    """Is the Ultimate backend offered in this run?"""
    return os.environ.get(ULTIMATE_ENV, "").strip().lower() in TRUE


@dataclass(frozen=True)
class Backend:
    """One way to read a running machine."""

    name: str
    probe: Callable[[], bool]
    connect: Callable[[], Target]
    setup_hint: str
    default_interval_ms: int = 200
    # Reading through this backend disturbs the machine. True for VICE, whose
    # monitor stops the CPU and hands it ~14.3 ms of extra emulated time per
    # resume; the interval is therefore a speed dial and not just a cost.
    disturbs: bool = True
    verified: bool = True

    def present(self) -> bool:
        """`probe()`, with anything it throws treated as "not there"."""
        try:
            return bool(self.probe())
        except Exception as exc:
            # Probed on every tick while nothing is attached, so one line and
            # no traceback: a backend that is not there says so five times a
            # second and would otherwise bury the log.
            debuglog.debug("%s did not answer the probe: %s", self.name, exc)
            return False


VICE = Backend(
    name="VICE (C64)",
    probe=monitor_listening,
    connect=ViceTarget,
    setup_hint=("start VICE with its binary monitor enabled -- "
                f"see {vice_settings_hint()}, or launch with "
                "-binarymonitor -binarymonitoraddress 127.0.0.1:6502"),
    default_interval_ms=200,
)


def _ultimate() -> list[Backend]:
    """The Commodore 64 Ultimate, if `WISH_EXPERIMENTAL_C64_ULTIMATE` says so
    and its module imports.

    Kept behind a function so a missing dependency or a syntax error in an
    unverified backend cannot stop the verified one from being offered.
    """
    if not ultimate_enabled():
        return []
    try:
        from .ultimate import ULTIMATE
    except Exception as exc:                # pragma: no cover - defensive
        # Also on the per-tick path, through `available()`.
        debuglog.debug("the Ultimate backend did not import: %s", exc)
        return []
    return [ULTIMATE]


def amiga_winuae_enabled() -> bool:
    """Is the WinUAE backend offered in this run?"""
    return os.environ.get(AMIGA_WINUAE_ENV, "").strip().lower() in TRUE


def amiga_enabled() -> bool:
    """Is either Amiga backend on?"""
    return amiga_fsuae_enabled() or amiga_winuae_enabled()


def amiga_fsuae_enabled() -> bool:
    """Is the Amiga backend offered in this run?"""
    return os.environ.get(AMIGA_FSUAE_ENV, "").strip().lower() in TRUE


def amiga_only_titles() -> tuple:
    """The titles that have Amiga disks and no C64 container, while the Amiga
    backend is on; nothing otherwise, so the flag off changes no lookup."""
    if not amiga_enabled():
        return ()
    from automap.maps import AMIGA_ONLY_TITLES
    return AMIGA_ONLY_TITLES


def _amiga_fsuae() -> list[Backend]:
    """The patched FS-UAE, if `WISH_EXPERIMENTAL_AMIGA_FSUAE` says so and its
    module imports.

    Kept behind a function for the same reason as `_ultimate()`: the flag being
    off must cost nothing, and a broken module must not stop VICE being offered.
    """
    if not amiga_fsuae_enabled():
        return []
    try:
        from .fsuae import AMIGA_FSUAE
    except Exception as exc:                # pragma: no cover - defensive
        debuglog.debug("the Amiga backend did not import: %s", exc)
        return []
    return [AMIGA_FSUAE]


def _amiga_winuae() -> list[Backend]:
    """WinUAE on this machine, if `WISH_EXPERIMENTAL_AMIGA_WINUAE` says so and
    its module imports.

    Built like `_amiga_fsuae()`.
    """
    if not amiga_winuae_enabled():
        return []
    try:
        from .winuae import AMIGA_WINUAE
    except Exception as exc:
        debuglog.debug("the WinUAE backend is not available: %s", exc)
        return []
    return [AMIGA_WINUAE]


def backends() -> list[Backend]:
    """Every backend, in the order they are tried: each platform's rows
    together, the C64 ones first."""
    return [VICE] + _ultimate() + _amiga_winuae() + _amiga_fsuae()


def available() -> list[Backend]:
    """The ones answering right now. Empty is the ordinary case."""
    return [b for b in backends() if b.present()]


#: Names a backend was saved under before it carried its machine, by lower-cased
#: old name. The chosen backend is saved by name in `Settings.backend`, so a
#: player's choice made under an old name has to keep naming the same backend.
RENAMED = {
    "vice": "VICE (C64)",
    "ultimate": "C64 Ultimate",
    "amiga (fs-uae)": "FS-UAE (Amiga)",
}


def current_name(saved: str | None) -> str:
    """The name a backend is called now, for a name saved under an older one.

    Any other name, including an empty one, comes back unchanged.
    """
    saved = saved or ""
    return RENAMED.get(saved.strip().lower(), saved)


def find(preferred: str | None = None) -> Backend | None:
    """The backend to attach to, or None if nothing answers.

    `preferred` settles a tie for somebody who has both a running emulator and
    a device on the desk; it is a name, matched case-insensitively, and it is
    ignored if that backend is not answering. A name saved before the
    backends were renamed still finds its backend (`current_name`).
    """
    here = available()
    if not here:
        return None
    if preferred:
        preferred = current_name(preferred)
        for b in here:
            if b.name.lower() == preferred.lower():
                return b
    return here[0]


def setup_hints() -> str:
    """What to tell someone with nothing running."""
    return "\n".join(f"{b.name}: {b.setup_hint}" for b in backends())
