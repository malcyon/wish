"""A background process that holds a patched FS-UAE's one debugger connection.

The fork serves one client per run and closes its listening socket for good
when that client leaves, so a Wish that connected itself would end the player's
debugging when it closed. This helper connects once, keeps the connection until
the emulator goes, and lets any number of local clients read memory through a
Unix socket. Run it as `python -m automap.fsuaehelper --port P`; `start()` does
that detached from the caller.

**Not a byte pipe.** GDB-remote has no request ids and the fork serves one
packet a frame, so a client's `k` would quit the player's game and two clients'
replies would interleave. The helper parses each client's packets and forwards
only `m` reads and `M` writes. `qSupported` is answered from the greeting taken
at startup, `vCont;c` is swallowed (the game is already running), and anything
else gets the empty reply GDB reads as "not supported".

**A write is an `M` of one to `MAX_WRITE` bytes inside the machine's memory**,
forwarded as it is and answered with the fork's own `OK` or error. A client
waits for that reply before sending its next packet: a client has one
outstanding request, and a newer one replaces a queued write, which is then
dropped without a reply. It is the
one write path for every client: Wish's own actions and the test driver's
encounter switch alike. It has no compare: a client that must not overwrite
something the game changed reads first, and the game may still change it
between that read and the write. The socket is mode 0600 in a 0700 directory,
so only processes of the same user can reach it, for writes as for reads.

Only Linux is implemented, in `Posix`, which holds every operating-system
dependency (socket kind, lock, runtime directory, process check) behind
`PLATFORM`. Elsewhere `main()` exits with `EXIT_UNSUPPORTED` and `start()`
raises `OSError`, before anything platform-specific is touched. `fcntl` is
imported where it is used so the module imports on Windows.
"""

import argparse
import json
import os
import pathlib
import re
import select
import selectors
import signal
import socket
import stat
import subprocess
import sys
import time

from automap import amiga, paths
from goldbox import assets

#: `AF_UNIX` paths are limited to 108 bytes including the terminator.
SOCKET_PATH_LIMIT = 107

#: The biggest piece a window sweeps memory in. A request up to this size is
#: a poll or a piece of a sweep, so the helper waits `POLL_TIMEOUT` for it: a
#: client that gave up on one should not hold everybody else for twenty seconds.
SWEEP_CHUNK = 0x10000

#: The most one `m` request may ask for; `locate_machines` reads half a megabyte.
MAX_READ = 0x80000

#: The most one forwarded `M` may write: the packet must fit the fork's
#: 512-byte receive buffer, and the driver's pokes are a few bytes.
MAX_WRITE = 64

#: Exit codes. 0 is the emulator going away, which is how a helper normally ends.
EXIT_PATH_TOO_LONG = 2
EXIT_LOCKED = 3
EXIT_FORK_BUSY = 4
EXIT_NOT_THE_FORK = 5
EXIT_FORK_UNREACHABLE = 6
EXIT_RUNTIME_DIR = 7
EXIT_NOT_PUBLISHED = 8
EXIT_UNSUPPORTED = 9

#: `/proc/net/tcp` state column.
_ESTABLISHED = "01"
_LISTEN = "0A"

#: An Amiga address is 32 bits; a longer one is not a read of its memory.
_READ = re.compile(r"^m([0-9a-fA-F]{1,8}),([0-9a-fA-F]+)$")

#: `M<addr>,<length>:<hex bytes>`, a write.
_WRITE = re.compile(r"^M([0-9a-fA-F]{1,8}),([0-9a-fA-F]{1,8}):([0-9a-fA-F]*)$")

#: The first argument a frozen build is started with to become the helper; a
#: frozen binary has no `-m`, so its entry point hands everything after this
#: flag to `main()`.
HELPER_FLAG = "--fsuae-helper"

#: What a client receives for a packet the helper does not forward.
NOT_SUPPORTED = b"$#00"


def runtime_dir(environ=None) -> pathlib.Path:
    return PLATFORM.runtime_dir(environ)


class Paths:
    """The four files one helper owns, named by the emulator port."""

    def __init__(self, port: int, runtime):
        self.runtime = pathlib.Path(runtime)
        stem = f"fsuae-{port}"
        self.lock = self.runtime / f"{stem}.lock"
        self.sock = self.runtime / f"{stem}.sock"
        self.json = self.runtime / f"{stem}.json"
        self.log = self.runtime / f"{stem}.log"


def _tcp_rows(proc: str):
    """`(local_port, state)` for every row of `/proc/net/tcp` and `tcp6`."""
    for name in ("tcp", "tcp6"):
        try:
            with open(os.path.join(proc, "net", name), encoding="ascii") as table:
                next(table, None)               # the column headings
                for row in table:
                    fields = row.split()
                    if len(fields) >= 4:
                        yield int(fields[1].rpartition(":")[2], 16), fields[3]
        except OSError:
            continue


class Posix:
    """Everything that is specific to the operating system, in one place.

    The forwarding logic uses only these methods, so another platform (a
    loopback TCP port with a lock file, a named pipe) is another class with the
    same methods and not a change to the loop. `proc` is where `/proc` is, so a
    test can point it at a synthetic one.
    """

    def __init__(self, proc: str = "/proc"):
        self.proc = proc

    def supported(self) -> bool:
        """Is this the platform `Posix` is written for? Only Linux is."""
        return sys.platform.startswith("linux")

    def runtime_dir(self, environ=None) -> pathlib.Path:
        """`$XDG_RUNTIME_DIR/wish`, or the data directory's `run` where it is unset."""
        environ = os.environ if environ is None else environ
        base = environ.get("XDG_RUNTIME_DIR")
        return pathlib.Path(base) / "wish" if base else paths.data_dir() / "run"

    def secure_dir(self, runtime: pathlib.Path) -> None:
        """Create the runtime directory readable by this user alone.

        Creates the directory with mode 0700 when it is missing. One that
        already exists is accepted only if it is a real directory (not a
        symlink) owned by this user and not writable by group or others, and
        its mode is left alone; anything else raises `OSError`.
        """
        try:
            runtime.mkdir(mode=0o700, parents=True)
            created = True
        except FileExistsError:
            created = False
        found = os.lstat(runtime)
        if not stat.S_ISDIR(found.st_mode):
            raise OSError(f"{runtime} is not a directory")
        if found.st_uid != os.getuid():
            raise OSError(f"{runtime} belongs to another user")
        if created:
            runtime.chmod(0o700)
        elif found.st_mode & 0o022:
            raise OSError(f"{runtime} is writable by other users")

    def endpoint_error(self, files: "Paths") -> str | None:
        """Why `files.sock` cannot be bound, or None."""
        if len(os.fsencode(files.sock)) > SOCKET_PATH_LIMIT:
            return (f"the socket path {files.sock} is too long for AF_UNIX "
                    f"({SOCKET_PATH_LIMIT} bytes at most)")
        return None

    def take_lock(self, path):
        """An open handle holding an exclusive lock on `path` until the process ends, or None."""
        import fcntl
        handle = open(path, "a")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return None
        return handle

    def fork_state(self, port: int) -> tuple[bool, bool]:
        """`(something listens on port, a connection to it is already open)`."""
        rows = list(_tcp_rows(self.proc))
        return ((port, _LISTEN) in rows, (port, _ESTABLISHED) in rows)

    def listen(self, files: "Paths"):
        """A listening, non-blocking socket for clients, replacing a stale one."""
        files.sock.unlink(missing_ok=True)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(files.sock))
        os.chmod(files.sock, 0o600)
        listener.listen(16)
        listener.setblocking(False)
        return listener

    def endpoint(self, files: "Paths") -> str:
        """What a client connects to, as written in the JSON."""
        return str(files.sock)

    def remove_endpoint(self, files: "Paths") -> None:
        files.sock.unlink(missing_ok=True)

    def connect(self, info: dict, timeout: float | None = None):
        """A connected client socket for the helper `info` describes.

        `timeout` bounds the connect, which waits when the helper's backlog is
        full; expiry raises `OSError`.
        """
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect(info["socket"])
        except OSError:
            sock.close()
            raise
        return sock

    def command_line(self, pid: int) -> list[str] | None:
        """The arguments of process `pid`, or None if there is no such process."""
        try:
            with open(os.path.join(self.proc, str(pid), "cmdline"), "rb") as handle:
                return handle.read().decode("latin-1").split("\0")
        except OSError:
            return None

    def endpoint_exists(self, info: dict) -> bool:
        return os.path.exists(info["socket"])

    def popen_options(self) -> dict:
        """Keyword arguments that detach a child from this process and its terminal."""
        return {"start_new_session": True, "close_fds": True}

    def ignore_hangups(self) -> None:
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)


#: The platform in use. Replaced as a whole, never patched piecemeal.
PLATFORM = Posix()


def _frame(body: str) -> bytes:
    return f"${body}#{sum(body.encode()) & 0xFF:02x}".encode()


def _split_packets(buf: bytes) -> tuple[list[str], bytes]:
    """Complete packet bodies in `buf` and the unfinished rest.

    Acks are dropped. A bare `\\x03` is the interrupt byte and comes back as
    the body `"\\x03"`. A bad checksum raises `ValueError`.
    """
    bodies: list[str] = []
    while buf:
        head = buf[:1]
        if head in (b"+", b"-"):
            buf = buf[1:]
        elif head == b"\x03":
            bodies.append("\x03")
            buf = buf[1:]
        elif head == b"$":
            end = buf.find(b"#")
            if end == -1 or len(buf) < end + 3:
                break
            body = buf[1:end]
            if int(buf[end + 1:end + 3], 16) != sum(body) & 0xFF:
                raise ValueError("bad checksum")
            bodies.append(body.decode("latin-1"))
            buf = buf[end + 3:]
        else:
            buf = buf[1:]
    return bodies, buf


class _Client:
    def __init__(self, sock):
        self.sock = sock
        self.buf = b""
        #: The one outstanding request, `(packet, short)`, where `short` says
        #: it waits `POLL_TIMEOUT` and not the full timeout. A newer one
        #: replaces it.
        self.pending: tuple[str, bool] | None = None
        self.closed = False


class Helper:
    """One helper's state; `main()` wraps it in a process."""

    #: How often the loop looks at `stopping` when nothing is happening.
    TICK = 0.2

    def __init__(self, port: int, runtime, platform=None,
                 upstream_timeout: float | None = None):
        self.port = port
        self.paths = Paths(port, runtime)
        self.platform = platform or PLATFORM
        self.upstream_timeout = upstream_timeout
        self.stopping = False
        #: The regions a write may land in, measured on the first write.
        self.memory: tuple[tuple[int, int], ...] | None = None
        self.gdb: amiga.FsuaeGdb | None = None
        self.listener = None
        self.clients: list[_Client] = []
        self.queue: list[_Client] = []
        self._lock_fd = None
        self._sel = selectors.DefaultSelector()

    # -- startup ---------------------------------------------------------

    def startup(self) -> int:
        """Take the lock, connect upstream, start listening. 0, or an exit code."""
        error = self.platform.endpoint_error(self.paths)
        if error:
            return self._fail(EXIT_PATH_TOO_LONG, error)
        try:
            self.platform.secure_dir(self.paths.runtime)
        except OSError as exc:
            return self._fail(EXIT_RUNTIME_DIR,
                              f"the runtime directory is unusable: {exc}")
        self._lock_fd = self.platform.take_lock(self.paths.lock)
        if self._lock_fd is None:
            return self._fail(EXIT_LOCKED,
                              f"another helper holds port {self.port}")
        listening, held = self.platform.fork_state(self.port)
        if not listening:
            return self._fail(EXIT_FORK_UNREACHABLE,
                              f"nothing is listening on port {self.port}")
        if held:
            return self._fail(EXIT_FORK_BUSY,
                              f"another client already holds port {self.port}")
        # Everything that can fail for a reason of ours is done before the
        # fork's one connection is taken: closing it again would end the
        # player's debugging for the life of the run. Holding the lock means
        # any file left here belongs to a dead helper.
        temp = self.paths.json.with_suffix(".json.tmp")
        try:
            self.listener = self.platform.listen(self.paths)
            staged = open(temp, "w")
        except OSError as exc:
            return self._fail(EXIT_NOT_PUBLISHED,
                              f"could not set up the client socket: {exc}")
        try:
            # Not resumed yet: a server that is not the fork must not be
            # told to run.
            self.gdb = amiga.FsuaeGdb(port=self.port,
                                      timeout=self.upstream_timeout,
                                      resume=False)
        except amiga.FsuaeError as exc:
            staged.close()
            temp.unlink(missing_ok=True)
            return self._fail(EXIT_FORK_UNREACHABLE,
                              f"could not connect to the emulator: {exc}")
        for needed in ("PacketSize=", "vContSupported+"):
            if needed not in self.gdb.greeting:
                staged.close()
                temp.unlink(missing_ok=True)
                self.gdb.close()
                return self._fail(
                    EXIT_NOT_THE_FORK,
                    f"port {self.port} does not look like the patched FS-UAE: "
                    f"its greeting was {self.gdb.greeting!r}")
        try:
            self.gdb.resume()
        except amiga.FsuaeError as exc:
            staged.close()
            temp.unlink(missing_ok=True)
            return self._fail(EXIT_NOT_PUBLISHED,
                              f"could not publish the helper: {exc}")
        try:
            info = {"version": 1, "pid": os.getpid(), "port": self.port,
                    "socket": self.platform.endpoint(self.paths),
                    "upstream_local_port": self.gdb.sock.getsockname()[1],
                    "writes": True, "started": time.time()}
            with staged:
                staged.write(json.dumps(info))
            os.replace(temp, self.paths.json)
        except (amiga.FsuaeError, OSError) as exc:
            staged.close()
            temp.unlink(missing_ok=True)
            return self._fail(EXIT_NOT_PUBLISHED,
                              f"could not publish the helper: {exc}")
        self._sel.register(self.listener, selectors.EVENT_READ, "listener")
        self._sel.register(self.gdb.sock, selectors.EVENT_READ, "upstream")
        return 0

    @staticmethod
    def _fail(code: int, message: str) -> int:
        print(f"fsuaehelper: {message}", file=sys.stderr, flush=True)
        return code

    # -- the loop --------------------------------------------------------

    def run(self) -> int:
        """Serve until the emulator closes its end or `stopping` is set. Exit code."""
        try:
            while not self.stopping:
                for key, _ in self._sel.select(self.TICK):
                    if key.data == "listener":
                        self._accept()
                    elif key.data == "upstream":
                        if not self.gdb.drain_idle():
                            return 0
                    else:
                        self._read_client(key.data)
                while self.queue and not self.stopping:
                    if not self._serve(self.queue.pop(0)):
                        return 0
            return 0
        finally:
            self._cleanup()

    def _accept(self) -> None:
        try:
            sock, _ = self.listener.accept()
        except (BlockingIOError, OSError):
            return
        sock.settimeout(2.0)
        client = _Client(sock)
        self.clients.append(client)
        self._sel.register(sock, selectors.EVENT_READ, client)

    def _drop(self, client: _Client) -> None:
        if client.closed:
            return
        client.closed = True
        client.pending = None
        if client in self.queue:
            self.queue.remove(client)
        if client in self.clients:
            self.clients.remove(client)
        try:
            self._sel.unregister(client.sock)
        except (KeyError, ValueError):
            pass
        client.sock.close()

    def _read_client(self, client: _Client, wait: bool = True) -> None:
        # A socket with a timeout waits for data even under MSG_DONTWAIT.
        if not wait and not select.select([client.sock], [], [], 0)[0]:
            return
        try:
            data = client.sock.recv(1 << 16)
        except socket.timeout:
            return
        except OSError:
            data = b""
        if not data:
            self._drop(client)
            return
        client.buf += data
        try:
            bodies, client.buf = _split_packets(client.buf)
        except ValueError:
            self._drop(client)
            return
        for body in bodies:
            if client.closed:
                return
            self._dispatch(client, body)
        if len(client.buf) > 1 << 16:
            self._drop(client)

    def _send(self, client: _Client, data: bytes) -> None:
        try:
            client.sock.sendall(data)
        except OSError:
            self._drop(client)

    def _dispatch(self, client: _Client, body: str) -> None:
        if body.startswith("qSupported"):
            self._send(client, _frame(self.gdb.greeting))
            return
        if body == "vCont;c":
            return                              # the game is already running
        match = _READ.match(body)
        if match:
            addr, length = int(match[1], 16), int(match[2], 16)
            if 1 <= length <= MAX_READ:
                self._queue(client, f"m{addr:x},{length:x}",
                            length <= SWEEP_CHUNK)
                return
        match = _WRITE.match(body)
        if match and _write_allowed(int(match[1], 16), int(match[2], 16),
                                    match[3], self._regions()):
            self._queue(client, body, True)
            return
        self._send(client, NOT_SUPPORTED)

    def _regions(self):
        """The machine's memory regions, measured once from Exec's list.

        The helper holds the emulator's connection, so it measures them itself
        rather than being told: a client has no packet to tell it with. An
        unreadable emulator measures nothing and is tried again next time.
        """
        if self.memory is None:
            try:
                self.memory = amiga.memory_regions(self.gdb.read_memory)
            except amiga.FsuaeError:
                return amiga.MEMORY
        return self.memory

    def _queue(self, client: _Client, packet: str, short: bool) -> None:
        # A client has one outstanding request; a newer one replaces it.
        if client in self.queue:
            self.queue.remove(client)
        client.pending = (packet, short)
        self.queue.append(client)

    def _serve(self, client: _Client) -> bool:
        """Run one client's request upstream. False once the emulator is gone."""
        if client.closed or client.pending is None:
            return True
        packet, short = client.pending
        client.pending = None
        gdb = self.gdb
        timeout = min(gdb.POLL_TIMEOUT, gdb.timeout) if short else gdb.timeout
        try:
            reply = gdb.ask(packet, timeout)
        except amiga.FsuaeError:
            # No reply at all: a made-up one could read as "not memory".
            return not gdb.lost
        # The client may have timed out and asked again while this ran; its
        # next request is then what it is waiting for, not this reply.
        self._read_client(client, wait=False)
        if not client.closed and client.pending is None:
            self._send(client, _frame(reply))
        return True

    # -- ending ----------------------------------------------------------

    def _cleanup(self) -> None:
        for client in list(self.clients):
            self._drop(client)
        if self.listener is not None:
            self.listener.close()
        if self.gdb is not None:
            self.gdb.close()
        self._sel.close()
        if self.listener is not None:
            self.platform.remove_endpoint(self.paths)
            self.paths.json.unlink(missing_ok=True)
        if self._lock_fd is not None:
            self._lock_fd.close()


def _write_allowed(addr: int, length: int, digits: str,
                   memory=amiga.MEMORY) -> bool:
    """Is `M<addr>,<length>:<digits>` a write the helper may forward?

    One to `MAX_WRITE` bytes, as many as the length says, all inside one of
    the machine's memory regions.
    """
    return (1 <= length <= MAX_WRITE and len(digits) == 2 * length
            and any(base <= addr and addr + length <= base + size
                    for base, size in memory))


def find(port: int, runtime, platform=None) -> dict | None:
    """The JSON of a live helper for `port`, or None.

    Live means the JSON names a pid whose command line is this module with this
    port, and its endpoint exists. It connects to nothing and takes no lock.
    """
    platform = platform or PLATFORM
    try:
        info = json.loads(Paths(port, runtime).json.read_text())
        args = platform.command_line(int(info["pid"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if args is None or not ({"automap.fsuaehelper", HELPER_FLAG} & set(args)):
        return None
    if "--port" not in args or args[args.index("--port") + 1:][:1] != [str(port)]:
        return None
    if not platform.endpoint_exists(info):
        return None
    return info


def command(port: int, runtime) -> list[str]:
    """The argument list that runs a helper: `-m` from source, the flag when frozen."""
    tail = ["--port", str(port), "--runtime", str(runtime)]
    if getattr(sys, "frozen", False):
        return [sys.executable, HELPER_FLAG, *tail]
    return [sys.executable, "-m", "automap.fsuaehelper", *tail]


def start(port: int, runtime) -> subprocess.Popen:
    """Start a helper detached from this process and return without waiting."""
    if not PLATFORM.supported():
        raise OSError(f"the connection helper is not supported on {sys.platform}")
    files = Paths(port, runtime)
    PLATFORM.secure_dir(files.runtime)
    env = dict(os.environ)
    if not assets.frozen():
        # A source run is `python -m automap.fsuaehelper` and must import the
        # same code as its parent; a frozen build re-runs its own binary.
        env["PYTHONPATH"] = os.pathsep.join(
            [str(assets.root())]
            + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    # Append, so a start that loses the race for the lock does not erase the
    # log of the helper that won it.
    with open(files.log, "ab") as log:
        return subprocess.Popen(
            command(port, files.runtime),
            stdin=subprocess.DEVNULL, stdout=log, stderr=log, env=env,
            **PLATFORM.popen_options())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=amiga.FSUAE_PORT)
    parser.add_argument("--runtime", default=None)
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == [HELPER_FLAG]:
        argv = argv[1:]
    args = parser.parse_args(argv)
    if not PLATFORM.supported():
        # Before anything Posix-only (locks, AF_UNIX, /proc) is touched.
        print(f"fsuaehelper: not supported on {sys.platform}",
              file=sys.stderr, flush=True)
        return EXIT_UNSUPPORTED
    helper = Helper(args.port, args.runtime or runtime_dir())
    PLATFORM.ignore_hangups()
    signal.signal(signal.SIGTERM, lambda *_: setattr(helper, "stopping", True))
    code = helper.startup()
    if code:
        helper._cleanup()
        return code
    return helper.run()


if __name__ == "__main__":
    sys.exit(main())
