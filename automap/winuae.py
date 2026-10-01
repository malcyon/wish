"""Read an Amiga's memory out of WinUAE from Python, over its named pipe.

This is the transport for Wish and WinUAE on one Windows machine. It opens
`\\\\.\\pipe\\WinUAE` itself, with no PowerShell and no console window, and asks
for each range with the debugger's `S "<file>" <addr> <len>`, which writes the
range to a file the reply then names. `m` is never used: its output is capped
near 4 KB a reply and about 500 lines for the life of the emulator process.

**The pipe is serviced from the emulation thread, and not while the debugger
waits at its prompt.** Every read is therefore overlapped, bounded by a deadline
and cancelled when the deadline passes, so the window's thread cannot hang on
an emulator the player has stopped in F11. After a timeout the handle is
dropped (a late reply would answer the next request) and no new attempt is made
for `BACKOFF` seconds.

**One handle is held while Wish is reading,** because every connect and every
disconnect is a line in the player's WinUAE log when logging is on. WinUAE
accepts the next client once this one leaves, so `close()` is all a second tool
needs. A pipe that is busy is waited for with `WaitNamedPipe`, not skipped.

The Win32 calls go through an injected `api` (`_winapi` by default, imported
only when used), so this module imports on every platform and the tests drive
it with a fake pipe.
"""

from __future__ import annotations

import os
import pathlib
import re
import sys
import time

from . import paths
from .amiga import PipeError, _check_commands

#: Win32 values `_winapi` also exports; kept here so a fake `api` needs only the
#: calls. A Windows-only test checks them against `_winapi`.
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
PIPE_READMODE_MESSAGE = 2
ERROR_FILE_NOT_FOUND = 2
ERROR_BROKEN_PIPE = 109
ERROR_SEM_TIMEOUT = 121
ERROR_PIPE_BUSY = 231
ERROR_MORE_DATA = 234
ERROR_OPERATION_ABORTED = 995
ERROR_IO_PENDING = 997
WAIT_TIMEOUT = 258

PIPE_PREFIX = "\\\\.\\pipe\\"

#: WinUAE's reply buffer is 16384 bytes (`IPC_BUFFER_SIZE`), so one read of
#: this size takes any reply whole; `ERROR_MORE_DATA` is still handled.
READ_SIZE = 16384

#: The framing a request is sent in. 8-bit text goes through the system ANSI
#: code page, so a path that is not pure ASCII needs the UTF-8 byte-order mark.
UTF8_BOM = b"\xef\xbb\xbf"

#: The longest absolute path sent. WinUAE's name buffer is `MAX_PATH` and an
#: overflow is parsed as the address, so a longer path is refused up front.
PATH_LIMIT = 200

_NAME = re.compile(r"WinUAE(?:_(\d+))?")
_RECEIPT = re.compile(
    r"Wrote ([0-9A-Fa-f]{8}) - ([0-9A-Fa-f]{8}) \((\d+) bytes\) to '(.*)'\.?",
    re.S)


def winuae_pipes(listdir=os.listdir) -> list[str]:
    """The names in `\\\\.\\pipe\\` that WinUAE creates, in the order it tries
    them: `WinUAE`, then `WinUAE_1` and up. Opens nothing; `[]` where the
    directory cannot be listed."""
    try:
        names = listdir(PIPE_PREFIX)
    except OSError:
        return []
    found = []
    for name in names:
        match = _NAME.fullmatch(name)
        if match:
            found.append((int(match.group(1) or 0), name))
    return [name for _, name in sorted(found)]


def dump_dir() -> pathlib.Path:
    """Where the files `S` writes go: inside Wish's own data folder."""
    return paths.data_dir() / "run" / "winuae"


def _api():
    import _winapi
    return _winapi


class PipeTimeout(PipeError):
    """WinUAE did not answer in time; the machine may be slow or at its prompt."""

    timed_out = True


class WinuaeLocalPipe:
    """`read_memory` over `\\\\.\\pipe\\<pipe>`, holding one handle open."""

    #: A command runs between two emulated instructions and stops nothing.
    halts_machine = False

    #: How long to wait for a pipe another client holds. Short, because this
    #: runs on the window's thread and the window asks again on its next tick.
    CONNECT_S = 0.5

    #: How long to wait for one reply. WinUAE answers within a few frames when
    #: it answers at all; a longer wait only freezes the window.
    TIMEOUT = 2.0

    #: No new attempt for this long after a request timed out.
    BACKOFF = 5.0

    def __init__(self, pipe: str = "WinUAE", directory=None, api=None,
                 clock=time.monotonic, sleep=time.sleep):
        self.pipe = pipe
        self.directory = pathlib.Path(directory) if directory else None
        self._api = api
        self._clock = clock
        self._sleep = sleep
        self._handle = None
        self._count = 0
        self._quiet_until = 0.0
        #: True after a failure, until a handle opens again.
        self.lost = False

    # -- the handle ------------------------------------------------------

    def _win(self):
        if self._api is None:
            self._api = _api()
        return self._api

    def _open(self, deadline: float) -> None:
        win = self._win()
        name = PIPE_PREFIX + self.pipe
        while True:
            try:
                handle = win.CreateFile(
                    name, GENERIC_READ | GENERIC_WRITE, 0, 0, OPEN_EXISTING,
                    FILE_FLAG_OVERLAPPED, 0)
                break
            except OSError as exc:
                code = getattr(exc, "winerror", None)
                if code == ERROR_FILE_NOT_FOUND:
                    raise PipeError(f"There is no WinUAE pipe called {self.pipe}.") from exc
                if code != ERROR_PIPE_BUSY:
                    raise PipeError(f"Could not open the WinUAE pipe: {exc}") from exc
                left = deadline - self._clock()
                if left <= 0:
                    raise PipeError("Another program holds the WinUAE pipe.") \
                        from exc
                try:
                    win.WaitNamedPipe(name, max(1, int(left * 1000)))
                except OSError as wait:
                    if getattr(wait, "winerror", None) != ERROR_SEM_TIMEOUT:
                        raise PipeError(f"Could not wait for the WinUAE pipe: {wait}") \
                            from wait
                else:
                    self._sleep(0.005)
        try:
            win.SetNamedPipeHandleState(handle, PIPE_READMODE_MESSAGE, None,
                                        None)
        except OSError as exc:
            win.CloseHandle(handle)
            raise PipeError(f"Could not set message mode on the WinUAE pipe: {exc}") \
                from exc
        self._handle = handle
        self.lost = False
        self._clear_leftovers(create=True)

    def _clear_leftovers(self, create: bool = False) -> None:
        """Remove this process's dumps that WinUAE wrote after Wish gave up.

        Only this process's: another Wish may be reading at the same time.
        """
        folder = self._folder()
        if create:
            folder.mkdir(parents=True, exist_ok=True)
        for leftover in folder.glob(f"wish-{os.getpid()}-*.bin"):
            try:
                leftover.unlink()
            except OSError:
                pass

    def _folder(self) -> pathlib.Path:
        return (self.directory or dump_dir()).absolute()

    def close(self) -> None:
        """Let go of the pipe so the next client is accepted. Safe to repeat."""
        handle, self._handle = self._handle, None
        if handle is not None:
            try:
                self._win().CloseHandle(handle)
            except OSError:
                pass
        try:
            self._clear_leftovers()
        except OSError:
            pass

    def _drop(self) -> None:
        self.lost = True
        self.close()

    # -- one overlapped call ---------------------------------------------

    def _finish(self, ov, err: int, deadline: float, what: str):
        """Wait for an overlapped call to finish; cancel it at the deadline."""
        if err == ERROR_IO_PENDING:
            left = max(0, int((deadline - self._clock()) * 1000))
            if self._win().WaitForSingleObject(ov.event, left) == WAIT_TIMEOUT:
                ov.cancel()
                try:
                    ov.GetOverlappedResult(True)
                except OSError:
                    pass
                self._quiet_until = self._clock() + self.BACKOFF
                raise PipeTimeout(f"WinUAE did not {what} in time; it may be "
                                "waiting at the debugger's prompt.")
        return ov.GetOverlappedResult(True)

    def _write(self, data: bytes, deadline: float) -> None:
        ov, err = self._win().WriteFile(self._handle, data, overlapped=True)
        written, err = self._finish(ov, err, deadline, "take the request")
        if err != 0 or written != len(data):
            raise PipeError(f"WinUAE took {written} of {len(data)} bytes of a request.")

    def _read_reply(self, deadline: float) -> bytes:
        """One reply: every part of it, read on while WinUAE says more is coming."""
        win = self._win()
        data = b""
        while True:
            ov, err = win.ReadFile(self._handle, READ_SIZE, overlapped=True)
            _, err = self._finish(ov, err, deadline, "answer")
            data += bytes(ov.getbuffer())
            if err == ERROR_MORE_DATA:
                continue
            if err != 0:
                raise PipeError(f"Reading the reply failed with error {err}.")
            if not data.endswith(b"\0"):
                raise PipeError("The reply ended without its terminator.")
            return data[:-1]

    # -- reading ---------------------------------------------------------

    def _request(self, text: str, timeout: float) -> str:
        _check_commands([text])
        ascii_only = text.isascii()
        body = text.encode("ascii" if ascii_only else "utf-8") + b"\0"
        message = body if ascii_only else UTF8_BOM + body
        deadline = self._clock() + timeout
        if self._clock() < self._quiet_until:
            raise PipeError("WinUAE stopped answering a moment ago; not "
                            "asking again yet.")
        try:
            if self._handle is None:
                self._open(min(deadline, self._clock() + self.CONNECT_S))
            self._write(message, deadline)
            reply = self._read_reply(deadline)
        except OSError as exc:
            self._drop()
            if getattr(exc, "winerror", None) == ERROR_BROKEN_PIPE:
                raise PipeError("WinUAE closed the pipe.") from exc
            raise PipeError(f"The WinUAE pipe failed: {exc}") from exc
        except PipeError:
            self._drop()
            raise
        return reply.decode("latin-1" if ascii_only else "utf-8", "replace")

    def read_memory(self, addr: int, length: int,
                    timeout: float | None = None) -> bytes:
        """`length` bytes at `addr`, through one `S` and the file it writes."""
        if length <= 0:
            raise ValueError(f"A read of {length} bytes is not a read.")
        self._count += 1
        target = self._folder() / f"wish-{os.getpid()}-{self._count}.bin"
        path = str(target)
        if len(path) > PATH_LIMIT:
            raise PipeError(f"The dump path is {len(path)} characters; "
                            f"WinUAE reads at most {PATH_LIMIT} safely.")
        if '"' in path:
            raise PipeError("The dump path contains a double quote.")
        try:
            reply = self._request(
                f'DBG S "{path}" {addr:x} {length:x}',
                self.TIMEOUT if timeout is None else timeout)
            _check_receipt(reply, addr, length, path)
            try:
                data = target.read_bytes()
            except OSError as exc:
                raise PipeError("WinUAE reported the dump and the file is not "
                                f"there: {exc.strerror}.") from exc
            if len(data) != length:
                raise PipeError(f"A dump of {length} bytes holds {len(data)}.")
            return data
        finally:
            try:
                target.unlink()
            except OSError:
                pass


def _without(reply: str, path: str) -> str:
    """The reply with the dump's path taken out, and cut short."""
    folder = os.path.dirname(path)
    return (reply.replace(path, "the dump file").replace(folder, "the dump folder")
            .strip()[:120])


def _check_receipt(reply: str, addr: int, length: int, path: str) -> None:
    """`Wrote AAAAAAAA - BBBBBBBB (N bytes) to 'path'.` for this very request."""
    match = _RECEIPT.match(reply)
    if match is None:
        raise PipeError("WinUAE did not write the dump: "
                        + _without(reply, path))
    start, _, count, name = match.groups()
    if (int(start, 16) != addr or int(count) != length
            or name.casefold() != path.casefold()):
        raise PipeError("WinUAE's receipt is for another request: "
                        + _without(reply, path))


def present(listdir=None) -> bool:
    """Is a WinUAE pipe listed? False off Windows. Opens nothing."""
    if listdir is None:
        if sys.platform != "win32":
            return False
        listdir = os.listdir
    return bool(winuae_pipes(listdir))
