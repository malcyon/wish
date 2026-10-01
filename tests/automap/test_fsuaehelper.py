"""`automap.fsuaehelper`: one process holds the emulator's one connection and clients read through it.

The fake fork follows the rules of the real one that matter here: it serves a
single client, answers `m` from a table (`E01` for an unreadable range), says
nothing to `vCont;c`, and when its client leaves it closes its listening socket
for good. No emulator is needed, so no pool slot.
"""

import os
import pathlib
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time

import pytest

from automap import amiga, fsuaehelper

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"),
                                reason="the helper uses AF_UNIX, flock and /proc")

GREETING = ("PacketSize=512;BreakpointCommands+;swbreak+;hwbreak+;"
            "QStartNoAckMode+;vContSupported+;")

UNREADABLE = 0x2000000


def frame(body: str) -> bytes:
    return f"${body}#{sum(body.encode()) & 0xFF:02x}".encode()


def memory_at(addr: int, length: int) -> bytes:
    return bytes((a * 7 + 3) & 0xFF for a in range(addr, addr + length))


class FakeFork:
    """The fork's GDB server: one client, then no door."""

    def __init__(self, greeting: str = GREETING):
        self.greeting = greeting
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.listener.settimeout(0.1)
        self.port = self.listener.getsockname()[1]
        self.received: list[str] = []
        self.accepted = 0
        self.client_left = threading.Event()
        self.door_closed = False
        #: Addresses whose `m` reply is held back until the event is set.
        self.holds: dict[int, threading.Event] = {}
        self.seen: dict[int, threading.Event] = {}
        self.replied: dict[int, threading.Event] = {}
        self._conn = None
        self._drop = False
        self._stop = False
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def event(self, table: dict, addr: int) -> threading.Event:
        return table.setdefault(addr, threading.Event())

    def noise(self) -> None:
        self._conn.sendall(frame("O" + b"hi".hex()))

    def drop_client(self) -> None:
        self._drop = True

    def close(self) -> None:
        self._stop = True
        self._thread.join(5)
        self.listener.close()

    def _serve(self) -> None:
        while not self._stop and self._conn is None:
            try:
                self._conn, _ = self.listener.accept()
            except OSError:
                continue
        if self._conn is None:
            return
        self.accepted += 1
        conn, buf = self._conn, b""
        conn.settimeout(0.05)
        while not self._stop and not self._drop:
            try:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf += chunk
            except socket.timeout:
                pass
            except OSError:
                break
            while buf.startswith((b"+", b"-")):
                buf = buf[1:]
            end = buf.find(b"#")
            if buf.startswith(b"$") and end != -1 and len(buf) >= end + 3:
                body = buf[1:end].decode()
                buf = buf[end + 3:]
                self._answer(conn, body)
        self.client_left.set()
        self.door_closed = True
        self.listener.close()
        conn.close()

    def _answer(self, conn, body: str) -> None:
        self.received.append(body)
        if body.startswith("qSupported"):
            conn.sendall(frame(self.greeting))
        elif body.startswith("m"):
            addr, _, length = body[1:].partition(",")
            addr, length = int(addr, 16), int(length, 16)
            self.event(self.seen, addr).set()
            hold = self.holds.get(addr)
            while hold and not hold.is_set() and not self._stop and not self._drop:
                time.sleep(0.01)
            if self._drop:
                return
            if addr >= UNREADABLE:
                conn.sendall(frame("E01"))
            else:
                conn.sendall(frame(memory_at(addr, length).hex()))
            self.event(self.replied, addr).set()


class Client:
    """A raw GDB-remote client on the helper's Unix socket."""

    def __init__(self, path, timeout: float = 2.0):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        self.sock.connect(str(path))
        self.buf = b""

    def send(self, body: str) -> None:
        self.sock.sendall(frame(body))

    def reply(self) -> str:
        while True:
            end = self.buf.find(b"#")
            if self.buf.startswith(b"$") and end != -1 and len(self.buf) >= end + 3:
                body = self.buf[1:end].decode()
                self.buf = self.buf[end + 3:]
                return body
            self.buf += self.sock.recv(4096)

    def ask(self, body: str) -> str:
        self.send(body)
        return self.reply()

    def silent(self, wait: float = 0.5) -> bool:
        self.sock.settimeout(wait)
        try:
            return self.sock.recv(4096) == b""
        except socket.timeout:
            return True
        finally:
            self.sock.settimeout(2.0)


@pytest.fixture
def fork():
    fake = FakeFork()
    yield fake
    fake.close()


@pytest.fixture
def runtime():
    # An AF_UNIX path is limited to 107 bytes; pytest's tmp_path can exceed it.
    path = pathlib.Path(tempfile.mkdtemp(prefix="wh"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def running(fork, runtime):
    """An in-process helper serving the fake fork, on a thread."""
    helper = fsuaehelper.Helper(fork.port, runtime, upstream_timeout=0.4)
    assert helper.startup() == 0
    result = []
    thread = threading.Thread(target=lambda: result.append(helper.run()))
    thread.start()
    helper.result = result
    yield helper
    helper.stopping = True
    thread.join(5)
    assert not thread.is_alive()


def sock_path(helper):
    return helper.paths.sock


def processes_naming(text: str) -> list[int]:
    found = []
    for entry in os.listdir("/proc"):
        if entry.isdigit() and int(entry) != os.getpid():
            try:
                with open(f"/proc/{entry}/cmdline", "rb") as handle:
                    if text.encode() in handle.read():
                        found.append(int(entry))
            except OSError:
                pass
    return found


@pytest.fixture
def procs(fork, runtime):
    """Helper subprocesses; none may be left once the test is over."""
    started: list[subprocess.Popen] = []
    yield started
    fork.close()
    leaked = []
    for proc in started:
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.send_signal(signal.SIGKILL)
            proc.wait(5)
            leaked.append(proc.pid)
    assert not leaked, f"helpers outlived their emulator: {leaked}"
    assert not processes_naming(str(runtime))


def wait_for(predicate, seconds: float = 10.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("timed out waiting")


def started_helper(procs, fork, runtime):
    proc = fsuaehelper.start(fork.port, runtime)
    procs.append(proc)
    wait_for(lambda: fsuaehelper.find(fork.port, runtime) or proc.poll() is not None)
    return proc


# -- what is forwarded ---------------------------------------------------------

def test_the_greeting_is_answered_from_the_cache_and_the_resume_is_swallowed(
        running, fork):
    for _ in range(3):
        client = Client(sock_path(running))
        assert client.ask("qSupported:multiprocess+") == GREETING
        client.send("vCont;c")
        assert client.ask("m100,2") == memory_at(0x100, 2).hex()
    assert fork.received.count("vCont;c") == 1
    assert [p for p in fork.received if p.startswith("qSupported")] == ["qSupported"]


ALLOWED = re.compile(r"^(m[0-9a-f]{1,8},[0-9a-f]+|qSupported|vCont;c)$")


@pytest.mark.parametrize("body", ["k", "D", "Mc00000,2:0102", "s", "S05",
                                  "vCont;s", "vCont;t", "?", "g", "vKill",
                                  "mc10000", "m,4", "mc10000,0", "m1ffffffff,4"])
def test_only_the_three_allowed_packets_ever_reach_the_emulator(
        running, fork, body):
    client = Client(sock_path(running))
    client.send(body)
    assert client.reply() == ""
    assert client.ask("m10,4") == memory_at(0x10, 4).hex()
    assert all(ALLOWED.match(p) for p in fork.received), fork.received


def test_the_client_socket_is_for_its_owner_alone(running):
    assert (sock_path(running).stat().st_mode & 0o777) == 0o600


@pytest.mark.parametrize("body", ["k", "D", "Mc00000,2:0102", "s", "S05",
                                  "vCont;s", "vCont;t", "\x03", "?", "g"])
def test_anything_but_a_read_is_refused_and_never_reaches_the_emulator(
        running, fork, body):
    client = Client(sock_path(running))
    if body == "\x03":
        client.sock.sendall(b"\x03")
    else:
        client.send(body)
    assert client.reply() == ""
    assert client.ask("m10,4") == memory_at(0x10, 4).hex()
    assert all(not p.startswith(("k", "D", "M", "s", "S", "vCont;s", "vCont;t",
                                 "?", "g")) for p in fork.received[2:])
    assert "\x03" not in fork.received


def test_a_read_is_relayed_byte_for_byte_and_so_is_a_refusal(running):
    client = Client(sock_path(running))
    assert client.ask("mc10000,40") == memory_at(0xC10000, 0x40).hex()
    assert client.ask(f"m{UNREADABLE:x},4") == "E01"


def test_two_clients_interleaved_each_get_their_own_reply(running):
    a, b = Client(sock_path(running)), Client(sock_path(running))
    for step in range(5):
        a.send(f"m{0x1000 + step:x},8")
        b.send(f"m{0x2000 + step:x},8")
        assert a.reply() == memory_at(0x1000 + step, 8).hex()
        assert b.reply() == memory_at(0x2000 + step, 8).hex()


def test_an_upstream_timeout_gives_the_client_nothing_and_the_late_reply_is_not_reused(
        running, fork):
    fork.holds[0x500] = threading.Event()
    client = Client(sock_path(running))
    client.send("m500,4")
    assert client.silent(1.0)               # upstream gave up after 0.4 s
    fork.holds[0x500].set()
    fork.event(fork.replied, 0x500).wait(2)
    time.sleep(0.1)
    # Same length, other address: a stale answer would read as plausible bytes.
    assert client.ask("m600,4") == memory_at(0x600, 4).hex()


def test_a_second_request_replaces_the_first_and_only_it_is_answered(running, fork):
    fork.holds[0x700] = threading.Event()
    client = Client(sock_path(running))
    client.send("m700,4")
    fork.event(fork.seen, 0x700).wait(2)    # the first is now upstream
    client.send("m800,4")
    fork.holds[0x700].set()
    assert client.reply() == memory_at(0x800, 4).hex()
    assert client.silent(0.3)


def test_console_output_while_idle_is_discarded(running, fork):
    client = Client(sock_path(running))
    assert client.ask("m10,2") == memory_at(0x10, 2).hex()
    fork.noise()
    time.sleep(0.4)
    assert client.ask("m20,2") == memory_at(0x20, 2).hex()


def test_a_bad_checksum_closes_that_client_only(running):
    bad, good = Client(sock_path(running)), Client(sock_path(running))
    bad.sock.sendall(b"$m10,2#00")
    assert bad.silent(1.0)
    assert good.ask("m10,2") == memory_at(0x10, 2).hex()


# -- lifetime ------------------------------------------------------------------

def test_the_helper_exits_when_the_emulator_closes_while_idle(fork, runtime, procs):
    proc = started_helper(procs, fork, runtime)
    info = fsuaehelper.find(fork.port, runtime)
    client = Client(info["socket"])
    assert client.ask("m10,2") == memory_at(0x10, 2).hex()
    fork.drop_client()
    assert proc.wait(10) == 0
    assert client.silent(1.0)
    files = fsuaehelper.Paths(fork.port, runtime)
    assert not files.sock.exists() and not files.json.exists()


def test_the_helper_exits_when_the_emulator_closes_mid_request(fork, runtime, procs):
    fork.holds[0x900] = threading.Event()
    proc = started_helper(procs, fork, runtime)
    client = Client(fsuaehelper.find(fork.port, runtime)["socket"])
    client.send("m900,4")
    fork.event(fork.seen, 0x900).wait(5)
    fork.drop_client()
    assert proc.wait(10) == 0
    files = fsuaehelper.Paths(fork.port, runtime)
    assert not files.sock.exists() and not files.json.exists()


def test_a_client_leaving_does_not_end_the_emulators_connection(fork, runtime, procs):
    proc = started_helper(procs, fork, runtime)
    path = fsuaehelper.find(fork.port, runtime)["socket"]
    Client(path).sock.close()
    time.sleep(0.5)
    assert proc.poll() is None and not fork.client_left.is_set()
    assert Client(path).ask("m10,2") == memory_at(0x10, 2).hex()
    assert fork.accepted == 1


def test_two_helpers_started_together_give_one_helper_and_one_refusal(
        fork, runtime, procs):
    first = fsuaehelper.start(fork.port, runtime)
    second = fsuaehelper.start(fork.port, runtime)
    procs.extend([first, second])
    wait_for(lambda: first.poll() is not None or second.poll() is not None)
    finished = [p for p in (first, second) if p.poll() is not None]
    assert len(finished) == 1 and finished[0].returncode == 3
    survivor = wait_for(lambda: fsuaehelper.find(fork.port, runtime))
    assert survivor["pid"] in (first.pid, second.pid)
    for _ in range(2):
        assert Client(survivor["socket"]).ask("m10,2") == memory_at(0x10, 2).hex()
    assert fork.accepted == 1


def test_a_stale_json_and_socket_from_a_dead_helper_are_ignored_and_replaced(
        fork, runtime, procs):
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    files = fsuaehelper.Paths(fork.port, runtime)
    stale = socket.socket(socket.AF_UNIX)
    stale.bind(str(files.sock))
    stale.close()                           # the file stays, nobody listens
    files.json.write_text('{"version": 1, "pid": %d, "port": %d, "socket": "%s"}'
                          % (dead.pid, fork.port, files.sock))
    assert fsuaehelper.find(fork.port, runtime) is None
    started_helper(procs, fork, runtime)
    info = fsuaehelper.find(fork.port, runtime)
    assert info and info["pid"] != dead.pid
    assert Client(info["socket"]).ask("m10,2") == memory_at(0x10, 2).hex()


def test_a_live_pid_with_another_command_line_is_not_a_helper(fork, runtime):
    files = fsuaehelper.Paths(fork.port, runtime)
    files.runtime.mkdir(exist_ok=True)
    files.sock.write_text("")
    files.json.write_text('{"pid": %d, "socket": "%s"}' % (os.getpid(), files.sock))
    assert fsuaehelper.find(fork.port, runtime) is None


# -- refusals at startup -------------------------------------------------------

def synthetic_proc(path: pathlib.Path, port: int, *states: str) -> pathlib.Path:
    (path / "net").mkdir(parents=True)
    rows = "".join(
        f"   {i}: 0100007F:{port:04X} 00000000:0000 {state} 0:0 0 0 0 0 0\n"
        for i, state in enumerate(states))
    (path / "net" / "tcp").write_text("  sl  local_address rem_address st\n" + rows)
    return path


def test_a_connection_already_open_on_the_port_exits_4_without_connecting(
        fork, runtime, tmp_path):
    proc = synthetic_proc(tmp_path / "proc", fork.port, "0A", "01")
    helper = fsuaehelper.Helper(fork.port, runtime, fsuaehelper.Posix(str(proc)))
    assert helper.startup() == 4
    helper._cleanup()
    assert fork.accepted == 0


def test_a_port_nobody_listens_on_exits_without_connecting(fork, runtime, tmp_path):
    proc = synthetic_proc(tmp_path / "proc", fork.port, "01")
    helper = fsuaehelper.Helper(fork.port, runtime, fsuaehelper.Posix(str(proc)))
    assert helper.startup() == 6
    helper._cleanup()
    assert fork.accepted == 0


def test_a_greeting_without_continue_support_exits_5(runtime):
    other = FakeFork(greeting="PacketSize=512;")
    try:
        helper = fsuaehelper.Helper(other.port, runtime)
        assert helper.startup() == 5
        helper._cleanup()
        assert not fsuaehelper.Paths(other.port, runtime).json.exists()
        # Not the fork, so it was not told to run the machine.
        assert "vCont;c" not in other.received
    finally:
        other.close()


def test_a_second_helper_for_the_same_port_refuses_to_start(running, fork, runtime):
    second = fsuaehelper.Helper(fork.port, runtime)
    assert second.startup() == 3
    second._cleanup()
    assert fsuaehelper.Paths(fork.port, runtime).json.exists()   # not deleted by the loser


def test_a_socket_path_over_the_limit_is_a_log_line_not_a_traceback(runtime):
    deep = runtime / ("d" * 120)
    result = subprocess.run(
        [sys.executable, "-m", "automap.fsuaehelper", "--port", "1",
         "--runtime", str(deep)],
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "PYTHONPATH": str(pathlib.Path(amiga.__file__).parent.parent)})
    assert result.returncode == 2
    assert "too long" in result.stderr and "Traceback" not in result.stderr
    assert processes_naming(str(runtime)) == []


def test_the_runtime_directory_is_private(fork, runtime):
    target = runtime / "sub"
    helper = fsuaehelper.Helper(fork.port, target)
    assert helper.startup() == 0
    try:
        assert (target.stat().st_mode & 0o777) == 0o700
    finally:
        helper._cleanup()


def test_the_runtime_directory_prefers_xdg_and_falls_back_to_the_data_directory(
        tmp_path):
    assert fsuaehelper.PLATFORM.runtime_dir({"XDG_RUNTIME_DIR": "/run/user/7"}) == \
        pathlib.Path("/run/user/7/wish")
    assert fsuaehelper.PLATFORM.runtime_dir({}).name == "run"


def test_a_source_run_starts_the_helper_with_dash_m(monkeypatch, tmp_path):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert fsuaehelper.command(7, tmp_path) == [
        sys.executable, "-m", "automap.fsuaehelper", "--port", "7",
        "--runtime", str(tmp_path)]


def test_a_frozen_build_starts_the_helper_with_the_flag_not_dash_m(
        monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert fsuaehelper.command(7, tmp_path) == [
        sys.executable, fsuaehelper.HELPER_FLAG, "--port", "7",
        "--runtime", str(tmp_path)]


def test_the_flag_is_dropped_before_the_arguments_are_parsed(runtime):
    # The frozen entry point passes its own argv on unchanged; a long path
    # makes main() return at once, before it touches the network.
    deep = runtime / ("d" * 120)
    assert fsuaehelper.main([fsuaehelper.HELPER_FLAG, "--port", "1",
                             "--runtime", str(deep)]) == 2


def test_a_frozen_helpers_command_line_is_recognised(fork, runtime):
    files = fsuaehelper.Paths(fork.port, runtime)
    files.sock.write_text("")
    files.json.write_text('{"pid": %d, "socket": "%s"}' % (os.getpid(), files.sock))
    fake = fsuaehelper.Posix()
    fake.command_line = lambda pid: [
        "wish", fsuaehelper.HELPER_FLAG, "--port", str(fork.port)]
    assert fsuaehelper.find(fork.port, runtime, fake) is not None


def test_a_failure_to_set_up_the_client_socket_comes_before_the_emulator_is_touched(
        fork, runtime):
    files = fsuaehelper.Paths(fork.port, runtime)
    runtime.mkdir(exist_ok=True)
    files.sock.mkdir()                       # cannot be replaced by a socket
    helper = fsuaehelper.Helper(fork.port, runtime)
    assert helper.startup() == fsuaehelper.EXIT_NOT_PUBLISHED
    helper._cleanup()
    assert fork.accepted == 0 and not fork.door_closed


def test_a_symlinked_runtime_directory_is_not_used(fork, runtime):
    real = runtime / "real"
    real.mkdir(mode=0o700)
    link = runtime / "link"
    link.symlink_to(real)
    helper = fsuaehelper.Helper(fork.port, link)
    assert helper.startup() == fsuaehelper.EXIT_RUNTIME_DIR
    helper._cleanup()
    assert fork.accepted == 0


def test_a_directory_that_was_there_already_keeps_its_mode(fork, runtime):
    target = runtime / "mine"
    target.mkdir(mode=0o750)
    target.chmod(0o750)
    fsuaehelper.PLATFORM.secure_dir(target)
    assert (target.stat().st_mode & 0o777) == 0o750


def test_a_directory_others_can_write_to_is_not_used(runtime):
    target = runtime / "open"
    target.mkdir()
    target.chmod(0o777)
    with pytest.raises(OSError):
        fsuaehelper.PLATFORM.secure_dir(target)


def test_a_new_start_does_not_erase_the_log_of_a_running_helper(runtime, monkeypatch):
    files = fsuaehelper.Paths(5, runtime)
    runtime.chmod(0o700)
    files.log.write_text("the first helper's line\n")
    monkeypatch.setattr(fsuaehelper, "command",
                        lambda port, rt: [sys.executable, "-c", "print('second')"])
    fsuaehelper.start(5, runtime).wait(10)
    text = files.log.read_text()
    assert "the first helper's line" in text and "second" in text


class _Stream:
    """A socket holding the bytes of a half-read console packet, then a reply."""

    def __init__(self, chunks):
        self.chunks = list(chunks)

    def settimeout(self, _s): pass

    def sendall(self, _data): pass

    def close(self): pass

    def recv(self, _n):
        if not self.chunks:
            raise socket.timeout()
        return self.chunks.pop(0)


def test_a_half_drained_console_packet_does_not_swallow_the_next_reply():
    gdb = amiga.FsuaeGdb(opener=lambda: _Stream(
        [frame(GREETING)]), resume=False)
    gdb._buf = b"6869#ab"                    # the tail of an "O" packet
    gdb.sock.chunks.append(frame("0102"))
    assert gdb.ask("m0,2") == "0102"


CHILD = """
import sys, time
from wish import fsuae
from automap import amiga
port, mode = int(sys.argv[1]), sys.argv[2]
deadline = time.time() + 25
while time.time() < deadline:
    try:
        fsuae.connect(port=port)
    except amiga.FsuaeError as exc:
        if mode == "once":
            print("listening", fsuae.listening(port))
            print("transport", fsuae._transport is not None)
            sys.exit(0)
        if fsuae._transport is not None:
            print(fsuae._transport.read_memory(0x10, 2).hex())
            sys.exit(0)
        time.sleep(0.2)
sys.exit(3)
"""


def wish_process(fork, runtime, mode="until"):
    """A separate Python process standing in for one run of Wish."""
    root = str(pathlib.Path(amiga.__file__).resolve().parent.parent)
    return subprocess.run(
        [sys.executable, "-c", CHILD, str(fork.port), mode],
        capture_output=True, text=True, timeout=60,
        env={**os.environ, "PYTHONPATH": root, "XDG_RUNTIME_DIR": str(runtime)})


def test_a_second_wish_finds_the_helper_the_first_started_and_the_fork_never_notices(
        fork, runtime):
    # `fsuae.connect` runs in other processes; the runtime directory is theirs.
    first = wish_process(fork, runtime)
    try:
        assert first.returncode == 0, first.stderr
        assert first.stdout.strip() == memory_at(0x10, 2).hex()
        info = wait_for(lambda: fsuaehelper.find(fork.port, runtime / "wish"))
        pid = info["pid"]
        second = wish_process(fork, runtime)
        assert second.returncode == 0, second.stderr
        assert second.stdout.strip() == memory_at(0x10, 2).hex()
        assert fsuaehelper.find(fork.port, runtime / "wish")["pid"] == pid
        assert fork.accepted == 1 and not fork.client_left.is_set()

        os.kill(pid, signal.SIGKILL)
        wait_for(lambda: fork.client_left.is_set() and fork.door_closed)
        third = wish_process(fork, runtime, "once")
        assert third.returncode == 0, third.stderr
        assert third.stdout.split() == ["listening", "False", "transport", "False"]
    finally:
        fork.close()
        wait_for(lambda: not processes_naming(str(runtime)), 10)
