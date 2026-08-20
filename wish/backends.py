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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from automap.paths import vice_settings_hint
from automap.target import Target, ViceTarget, monitor_listening


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
        except Exception:
            return False


VICE = Backend(
    name="VICE",
    probe=monitor_listening,
    connect=ViceTarget,
    setup_hint=("start VICE with its binary monitor enabled -- "
                f"see {vice_settings_hint()}, or launch with "
                "-binarymonitor -binarymonitoraddress 127.0.0.1:6502"),
    default_interval_ms=200,
)


def _ultimate() -> list[Backend]:
    """The Commodore 64 Ultimate, if its module imports.

    Kept behind a function so a missing dependency or a syntax error in an
    unverified backend cannot stop the verified one from being offered.
    """
    try:
        from .ultimate import ULTIMATE
    except Exception:                       # pragma: no cover - defensive
        return []
    return [ULTIMATE]


def backends() -> list[Backend]:
    """Every backend, in the order they are tried."""
    return [VICE] + _ultimate()


def available() -> list[Backend]:
    """The ones answering right now. Empty is the ordinary case."""
    return [b for b in backends() if b.present()]


def find(preferred: str | None = None) -> Backend | None:
    """The backend to attach to, or None if nothing answers.

    `preferred` settles a tie for somebody who has both a running emulator and
    a device on the desk; it is a name, matched case-insensitively, and it is
    ignored if that backend is not answering.
    """
    here = available()
    if not here:
        return None
    if preferred:
        for b in here:
            if b.name.lower() == preferred.lower():
                return b
    return here[0]


def setup_hints() -> str:
    """What to tell someone with nothing running."""
    return "\n".join(f"{b.name}: {b.setup_hint}" for b in backends())
