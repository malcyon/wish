"""The one live connection, and the state machine around it.

**VICE serves exactly one binary-monitor connection at a time.** It accepts a
second TCP connection and then silently ignores it, so a window whose tabs each
opened their own would hang the second one with no error to show for it. This
class owns a single `Target` for the window's lifetime and hands it to whichever
tab is visible.

Three ordinary states, none of them an error: nothing to attach to, attached,
and attached-then-gone. The session moves between them on its own -- quitting
the emulator and starting it again needs no intervention -- and says which one
it is in through `note`, which is what the status bar shows.

**Only the visible tab polls.** `set_reader` is how a tab says "read this for
me"; switching tabs changes what is read, not how often, and a tab that is not
showing costs nothing. The cost of a poll is per round trip, so this matters
more than it looks: under VICE each resume hands the emulation ~14.3 ms of
extra emulated time, and on a network device each trip is a network trip.
"""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from automap.target import MonitorBusy, NotConnected, Target

from . import backends, debuglog

# While there is nothing to attach to, probe on a slower timer than the poll:
# an absent emulator is the common case and a TCP connect per 200 ms to a port
# nobody is listening on is pure noise.
RETRY_MS = 1000

WAITING, CONNECTED, BUSY = "waiting", "connected", "busy"


class Session(QObject):
    """One `Target`, shared, with attach and reattach handled for you."""

    changed = pyqtSignal(str)          # the note changed; render from it

    def __init__(self, preferred: str | None = None,
                 interval_ms: int | None = None, parent=None,
                 find: Callable[..., object] | None = None):
        super().__init__(parent)
        self._find = find or backends.find
        self._preferred = preferred
        self._interval_override = interval_ms
        self.target: Target | None = None
        self.backend = None
        self.note = "looking for a running game"
        # Something else holds the monitor. Not "no game" and not an error --
        # the game is running, we simply cannot have it yet, and it clears on
        # its own when the other client lets go.
        self.busy = False
        self.reader: Callable[[Target], None] | None = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)

    # -- state -----------------------------------------------------------

    @property
    def state(self) -> str:
        if self.target is not None:
            return CONNECTED
        return BUSY if self.busy else WAITING

    @property
    def interval_ms(self) -> int:
        """The poll interval this backend wants, unless told otherwise.

        A device on the end of a network cable cannot be asked as often as a
        loopback socket, so the number belongs to the backend and not to the
        window. While there is nothing attached this is the retry interval
        instead -- there is nothing to poll, only something to look for.
        """
        if self.target is None:
            return RETRY_MS
        if self._interval_override:
            return self._interval_override
        return self.backend.default_interval_ms if self.backend else RETRY_MS

    def _say(self, note: str) -> None:
        if note != self.note:
            self.note = note
            # Logged here rather than at each call site: every state change
            # passes through, and a note that has not changed -- an absent
            # emulator probed once a second -- says nothing new and is not
            # written again.
            debuglog.note("session: %s", note)
            self.changed.emit(note)

    # -- the connection --------------------------------------------------

    def attach(self) -> bool:
        """Attach if something is answering. Idempotent: one target, always.

        Returns True while connected, including when it already was -- a tab
        asking twice must not open a second connection.
        """
        if self.target is not None:
            return True
        backend = self._find(self._preferred)
        if backend is None:
            self._say("waiting for a game - " + backends.setup_hints())
            return False
        try:
            self.target = backend.connect()
        except MonitorBusy as exc:
            self.busy = True
            debuglog.note("%s: monitor busy (%s)", backend.name, exc)
            self._say(str(exc))
            return False
        except NotConnected as exc:
            self.busy = False
            self._say(f"waiting for a game ({exc})")
            return False
        self.busy = False
        self.backend = backend
        self._say(f"{backend.name}: connected")
        debuglog.note("attached to %s, polling every %d ms",
                      backend.name, self.interval_ms)
        self._retime()
        return True

    def detach(self, note: str = "disconnected") -> None:
        """Drop the connection and go back to waiting. Never raises."""
        target, self.target = self.target, None
        if target is not None:
            try:
                target.close()
            except Exception:
                pass
        self._say(note)
        self._retime()

    def _retime(self) -> None:
        if self.timer.isActive():
            self.timer.start(self.interval_ms)

    # -- polling ---------------------------------------------------------

    def set_reader(self, reader: Callable[[Target], None] | None) -> None:
        """What the visible tab wants read. None means nothing is watching."""
        self.reader = reader

    def start(self) -> None:
        self.timer.start(self.interval_ms)

    def stop(self) -> None:
        self.timer.stop()

    def poll(self) -> None:
        """One tick: attach if needed, then read what the visible tab asked for.

        An error that is not `NotConnected` is reported and swallowed. The map
        has run for hours beside a game; a transient bad read is not a reason to
        take the window down, and the next tick usually fixes it.
        """
        if self.reader is None:
            # Nothing on screen wants live data -- the editor tab, say. Do not
            # even attach: VICE serves exactly one binary-monitor connection and
            # silently ignores a second, so merely opening this window while
            # something else is driving the emulator would steal the machine
            # from it. Attaching is a side effect, and side effects wait until
            # somebody asks.
            return
        if self.target is None:
            if not self.attach():
                return
        try:
            with debuglog.timed("a poll"):
                self.reader(self.target)
        except NotConnected:
            self.detach("the emulator went away - waiting for it to come back")
        except Exception as exc:                    # keep the window alive
            note = f"trouble reading the machine: {exc}"
            fresh = note != self.note
            self._say(note)
            # The traceback used to die here, and it is the most useful thing
            # in a report about a window that stayed up. Once per distinct
            # failure: a poll that fails every tick would otherwise write five
            # tracebacks a second.
            if fresh:
                debuglog.exception("the poll raised, and was swallowed")

    def close(self) -> None:
        self.stop()
        self.detach("closed")
