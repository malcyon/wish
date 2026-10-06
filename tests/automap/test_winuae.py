"""Checks that Wish reads WinUAE's memory over a pipe it holds open, without hanging.

A fake `_winapi` plays WinUAE: it answers `DBG S "<file>" <addr> <len>` by
writing the file and the receipt, and it can split a reply, leave off the NUL,
go silent like a debugger waiting at its prompt, or report the pipe busy. Nothing
here opens a real pipe except the last test, which needs Windows.
"""

from __future__ import annotations

import os
import re
import sys

import pytest

from automap import amiga, winuae

MEMORY = bytes(range(256)) * 16


def win_error(code: int) -> OSError:
    err = OSError(0, "fake", None, code)
    if getattr(err, "winerror", None) != code:
        err.winerror = code
    return err


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class Ov:
    def __init__(self, server, chunk=None, cost=0.0):
        self.server, self.chunk, self.cost = server, chunk, cost
        self.event = self
        self.cancelled = False

    def cancel(self):
        self.cancelled = True
        self.server.cancels += 1

    def GetOverlappedResult(self, wait):
        if self.cancelled:
            return 0, winuae.ERROR_OPERATION_ABORTED
        if self.chunk is None:
            return 0, 0
        data, err = self.chunk
        return len(data), err

    def getbuffer(self):
        return self.chunk[0] if self.chunk else b""


class FakeWinuae:
    """The `_winapi` calls the transport makes, and the emulator behind them."""

    def __init__(self, clock):
        self.clock = clock
        self.busy = 0                   # CreateFile fails this many times
        self.always_busy = False
        self.missing = False
        self.silent = False             # debugger at its prompt: no reply
        self.chunk = None               # split every reply into pieces this big
        self.drop_nul = False
        self.receipt = None             # a canned reply instead of the real one
        self.memory = bytearray(MEMORY)
        self.write_receipt = None       # a canned reply to a `W`
        self.write_receipts = []        # canned replies, one per `W`, first
        self.silent_after = None        # go silent once this many messages are in
        self.write_cost = 0.0           # clock time each WriteFile takes
        self.ignore_writes = False      # receipts come, memory stays as it was
        self.unanswered: list[bytes] = []  # requests made while silent
        self.broken_read = False        # ReadFile fails as if WinUAE hung up
        self.write_hangs = False        # WriteFile never completes
        self.read_cost = 0.0            # clock time each finished read takes
        self.wait_ms: list[int] = []    # the time each wait was given
        self.creates = self.closes = self.cancels = self.waits = 0
        self.modes = []
        self.written: list[bytes] = []
        self.pending: list[tuple[bytes, int]] = []

    # -- the calls --
    open_cost = 0.0                     # how long a CreateFile takes

    def CreateFile(self, name, access, share, security, disposition, flags, template):
        self.creates += 1
        self.clock.now += self.open_cost
        assert name.startswith("\\\\.\\pipe\\")
        assert flags & winuae.FILE_FLAG_OVERLAPPED
        if self.missing:
            raise win_error(winuae.ERROR_FILE_NOT_FOUND)
        if self.always_busy or self.busy:
            self.busy = max(0, self.busy - 1)
            raise win_error(winuae.ERROR_PIPE_BUSY)
        return 7

    def WaitNamedPipe(self, name, ms):
        self.waits += 1
        if self.always_busy:
            self.clock.now += ms / 1000
            raise win_error(winuae.ERROR_SEM_TIMEOUT)

    def SetNamedPipeHandleState(self, handle, mode, a, b):
        self.modes.append(mode)

    def CloseHandle(self, handle):
        self.closes += 1

    def WriteFile(self, handle, data, overlapped=False):
        self.written.append(bytes(data))
        self.clock.now += self.write_cost
        if self.silent_after is not None and len(self.written) > self.silent_after:
            self.silent = True
        if self.silent:
            self.unanswered.append(bytes(data))
        else:
            self.pending = self._answer(bytes(data))
        if self.write_hangs:
            return Ov(self, None), winuae.ERROR_IO_PENDING
        return Ov(self, (data, 0)), winuae.ERROR_IO_PENDING

    def ReadFile(self, handle, size, overlapped=False):
        if self.broken_read:
            raise win_error(winuae.ERROR_BROKEN_PIPE)
        chunk = None if self.silent or not self.pending else self.pending.pop(0)
        return Ov(self, chunk, self.read_cost), winuae.ERROR_IO_PENDING

    def WaitForSingleObject(self, event, ms):
        """Done when the call has an answer; a starved read never finishes."""
        self.wait_ms.append(ms)
        self.clock.now += event.cost
        return 0 if event.chunk is not None else winuae.WAIT_TIMEOUT

    def resume(self):
        """The debugger lets go: every request made meanwhile is answered."""
        self.silent = False
        for message in self.unanswered:
            self.pending += self._answer(message)
        self.unanswered = []

    # -- the emulator --
    def _answer(self, message: bytes) -> list[tuple[bytes, int]]:
        text = message[3:] if message.startswith(winuae.UTF8_BOM) else message
        text = text.rstrip(b"\0").decode("utf-8")
        if text.startswith("DBG W "):
            return self._answer_write(text)
        match = re.fullmatch(r'DBG S "(.*)" ([0-9a-f]+) ([0-9a-f]+)', text)
        assert match, text
        path, addr, length = match.group(1), int(match.group(2), 16), \
            int(match.group(3), 16)
        with open(path, "wb") as out:
            out.write(self.memory[addr:addr + length])
        reply = (self.receipt.replace("{path}", path) if self.receipt is not None else
                 f"Wrote {addr:08X} - {addr + length - 1:08X} "
                 f"({length} bytes) to '{path}'.").encode("utf-8")
        reply = reply if self.drop_nul else reply + b"\0"
        size = self.chunk or len(reply)
        pieces = [reply[i:i + size] for i in range(0, len(reply), size)]
        return [(piece, winuae.ERROR_MORE_DATA if i < len(pieces) - 1 else 0)
                for i, piece in enumerate(pieces)]

    def _answer_write(self, text: str) -> list[tuple[bytes, int]]:
        words = text.split()[2:]
        addr, values = int(words[0], 16), [int(w, 16) for w in words[1:]]
        lines = []
        for i, value in enumerate(values):
            if not self.ignore_writes:
                self.memory[addr + i] = value
            lines.append(f"Wrote {value:X} ({value}) at {addr + i:08X}.B\n")
        canned = (self.write_receipts.pop(0) if self.write_receipts
                  else self.write_receipt)
        reply = (canned if canned is not None else "".join(lines)).encode("latin-1") + b"\0"
        return [(reply, 0)]


@pytest.fixture
def rig(tmp_path):
    clock = Clock()
    api = FakeWinuae(clock)
    pipe = winuae.WinuaeLocalPipe(directory=tmp_path / "dump", api=api,
                                  clock=clock, sleep=lambda _s: None)
    return pipe, api, clock, tmp_path / "dump"


def test_a_range_comes_back_and_only_an_s_command_is_written(rig):
    pipe, api, _clock, folder = rig
    assert pipe.read_memory(0x10, 0x20) == MEMORY[0x10:0x30]
    (message,) = api.written
    assert message.endswith(b"\0")
    assert re.fullmatch(rb'DBG S "[^"]+wish-\d+-1\.bin" 10 20\0', message)
    assert api.modes == [winuae.PIPE_READMODE_MESSAGE]
    assert list(folder.glob("wish-*.bin")) == []


@pytest.mark.parametrize("text", ["DBG qq", "DBG fs 1", "DBG g", "IPC_QUIT", "CFG x"])
def test_a_message_that_quits_or_halts_is_blocked_before_it_is_written(rig, text):
    pipe, api, _clock, _folder = rig
    with pytest.raises(ValueError):
        pipe._request(text, 1.0)
    assert api.written == []


def test_a_reply_in_several_parts_is_put_together(rig):
    pipe, api, *_ = rig
    api.chunk = 9
    assert pipe.read_memory(0, 64) == MEMORY[:64]


def test_a_complete_message_without_its_nul_is_an_error(rig):
    pipe, api, *_ = rig
    api.drop_nul = True
    with pytest.raises(amiga.PipeError, match="terminator"):
        pipe.read_memory(0, 16)
    assert pipe.lost and api.closes == 1


def test_a_debugger_at_its_prompt_times_out_cancels_and_is_left_alone(rig):
    pipe, api, clock, folder = rig
    pipe.read_memory(0, 8)
    api.silent = True
    with pytest.raises(amiga.PipeError, match="prompt"):
        pipe.read_memory(0, 16)
    assert api.cancels == 1 and api.closes == 1 and pipe.lost
    assert list(folder.glob("wish-*.bin")) == []
    creates = api.creates
    with pytest.raises(amiga.PipeError, match="not asking again"):
        pipe.read_memory(0, 16)
    assert api.creates == creates                   # no new attempt in the quiet time
    clock.now += pipe.BACKOFF + 1
    api.silent = False
    assert pipe.read_memory(0, 16) == MEMORY[:16]
    assert not pipe.lost


def test_a_slow_reopen_is_not_counted_as_a_slow_answer(rig):
    pipe, api, clock, _folder = rig
    api.open_cost = 0.45
    assert pipe.read_memory(0, 8, timeout=0.2) == MEMORY[:8]
    assert pipe.lost is False


def test_a_busy_pipe_is_waited_for_and_then_opened(rig):
    pipe, api, *_ = rig
    api.busy = 2
    assert pipe.read_memory(0, 4) == MEMORY[:4]
    assert api.waits == 2


def test_a_pipe_that_stays_busy_gives_up_with_a_pipe_error(rig):
    pipe, api, *_ = rig
    api.always_busy = True
    with pytest.raises(amiga.PipeError, match="Another program holds"):
        pipe.read_memory(0, 4)
    assert isinstance(amiga.PipeError("x"), amiga.NotConnected)


def test_no_pipe_is_a_pipe_error(rig):
    pipe, api, *_ = rig
    api.missing = True
    with pytest.raises(amiga.PipeError, match="no WinUAE pipe"):
        pipe.read_memory(0, 4)


def test_one_handle_serves_every_read_until_it_is_closed(rig):
    pipe, api, *_ = rig
    for _ in range(3):
        pipe.read_memory(0, 8)
    assert (api.creates, api.closes) == (1, 0)
    pipe.close()
    pipe.close()
    assert api.closes == 1
    pipe.read_memory(0, 8)
    assert api.creates == 2


def test_a_path_with_spaces_is_quoted(tmp_path):
    clock = Clock()
    api = FakeWinuae(clock)
    pipe = winuae.WinuaeLocalPipe(directory=tmp_path / "A Player" / "run",
                                  api=api, clock=clock)
    assert pipe.read_memory(0, 8) == MEMORY[:8]
    assert b'"' + str(tmp_path / "A Player").encode() in api.written[0]


def test_a_plain_path_is_sent_as_8_bit_text(rig):
    pipe, api, *_ = rig
    pipe.read_memory(0, 8)
    assert not api.written[0].startswith(winuae.UTF8_BOM)


def test_a_path_outside_ascii_goes_in_the_utf8_framing(tmp_path):
    clock = Clock()
    api = FakeWinuae(clock)
    folder = tmp_path / "José 山"
    pipe = winuae.WinuaeLocalPipe(directory=folder, api=api, clock=clock)
    assert pipe.read_memory(0, 8) == MEMORY[:8]
    message = api.written[0]
    assert message.startswith(winuae.UTF8_BOM)
    assert "José 山".encode("utf-8") in message
    assert message.endswith(b"\0")


def test_this_processs_leftover_dumps_are_cleared_at_connect_and_at_close(rig):
    pipe, _api, _clock, folder = rig
    folder.mkdir()
    mine = folder / f"wish-{os.getpid()}-99.bin"
    other = folder / f"wish-{os.getpid() + 1}-1.bin"
    mine.write_bytes(b"old")
    other.write_bytes(b"another Wish's")
    (folder / "keep.txt").write_bytes(b"mine")
    pipe.read_memory(0, 8)
    assert not mine.exists()
    assert other.exists() and (folder / "keep.txt").exists()
    mine.write_bytes(b"late")                   # WinUAE wrote it after we gave up
    pipe.close()
    assert not mine.exists() and other.exists()


def test_no_message_a_player_could_see_holds_a_path_or_starts_lowercase(
        rig, tmp_path):
    pipe, api, clock, folder = rig
    messages = []

    def fail(setup, undo=lambda: None):
        setup()
        with pytest.raises(amiga.PipeError) as caught:
            pipe.read_memory(0, 16)
        messages.append(str(caught.value))
        undo()
        pipe.close()
        clock.now += 100

    fail(lambda: setattr(api, "missing", True),
         lambda: setattr(api, "missing", False))
    fail(lambda: setattr(api, "always_busy", True),
         lambda: setattr(api, "always_busy", False))
    fail(lambda: setattr(api, "silent", True),
         lambda: setattr(api, "silent", False))
    fail(lambda: setattr(api, "drop_nul", True),
         lambda: setattr(api, "drop_nul", False))
    fail(lambda: setattr(api, "receipt", "Couldn't open file '{path}'."),
         lambda: setattr(api, "receipt", None))
    fail(lambda: setattr(api, "receipt", "Wrote 00000001 - 00000008 (8 bytes) to 'x'."))
    for message in messages:
        assert message[:1].isupper(), message
        assert str(tmp_path) not in message, message
        assert "0x" not in message, message



def test_a_receipt_for_another_request_is_blocked_and_the_pipe_kept(rig):
    pipe, api, *_ = rig
    api.receipt = "Wrote 00000001 - 00000008 (8 bytes) to 'elsewhere.bin'."
    with pytest.raises(amiga.PipeError, match="another request"):
        pipe.read_memory(0, 8)
    assert api.closes == 0


def test_a_reply_that_is_not_a_receipt_is_an_error(rig):
    pipe, api, *_ = rig
    api.receipt = "Couldn't open file 'x'."
    with pytest.raises(amiga.PipeError, match="did not write"):
        pipe.read_memory(0, 8)


def test_a_dump_path_too_long_for_winuae_is_blocked_before_sending(tmp_path):
    api = FakeWinuae(Clock())
    pipe = winuae.WinuaeLocalPipe(directory=tmp_path / ("d" * 220), api=api)
    with pytest.raises(amiga.PipeError, match="characters"):
        pipe.read_memory(0, 8)
    assert api.written == []


def test_the_pipe_names_are_the_ones_winuae_creates_in_order():
    listing = ["WinUAE_2", "WinUAEx", "other", "WinUAE", "WinUAE_10", "WinUAE_1"]
    assert winuae.winuae_pipes(lambda _p: listing) == [
        "WinUAE", "WinUAE_1", "WinUAE_2", "WinUAE_10"]


def test_an_unlistable_pipe_directory_is_no_pipes():
    def block(_path):
        raise OSError("nope")
    assert winuae.winuae_pipes(block) == []
    assert winuae.present(block) is False


windows = pytest.mark.skipif(sys.platform != "win32",
                             reason="needs real Windows named pipes")


@windows
def test_the_constants_are_the_ones_winapi_uses():
    import _winapi
    for name in ("GENERIC_READ", "GENERIC_WRITE", "OPEN_EXISTING",
                 "FILE_FLAG_OVERLAPPED", "PIPE_READMODE_MESSAGE",
                 "ERROR_BROKEN_PIPE", "ERROR_SEM_TIMEOUT", "ERROR_PIPE_BUSY",
                 "ERROR_MORE_DATA", "ERROR_OPERATION_ABORTED",
                 "ERROR_IO_PENDING"):
        assert getattr(winuae, name) == getattr(_winapi, name), name
    assert winuae.WAIT_TIMEOUT == _winapi.WAIT_TIMEOUT


@windows
def test_a_real_message_pipe_answers_two_clients_in_turn(tmp_path):
    import _winapi
    import ctypes
    import ctypes.wintypes
    import threading
    import uuid

    # `_winapi` has no DisconnectNamedPipe; WinUAE calls it to take the next
    # client on the same instance, so the server does too.
    disconnect = ctypes.windll.kernel32.DisconnectNamedPipe
    disconnect.argtypes = [ctypes.wintypes.HANDLE]
    disconnect.restype = ctypes.wintypes.BOOL

    name = f"wish-test-{uuid.uuid4().hex}"
    server = _winapi.CreateNamedPipe(
        "\\\\.\\pipe\\" + name, _winapi.PIPE_ACCESS_DUPLEX,
        _winapi.PIPE_TYPE_MESSAGE | _winapi.PIPE_READMODE_MESSAGE
        | _winapi.PIPE_WAIT, 1, 16384, 16384, 0, 0)
    requests = []

    def serve():
        for _ in range(2):
            try:
                _winapi.ConnectNamedPipe(server, overlapped=False)
            except OSError as e:
                # ERROR_PIPE_CONNECTED: the client got in before the server
                # reached this call, which is a connection, not a failure.
                if e.winerror != 535:
                    raise
            while True:
                try:
                    raw, err = _winapi.ReadFile(server, 16384)
                except OSError:
                    break
                text = bytes(raw).rstrip(b"\0").decode("utf-8")
                requests.append(text)
                match = re.fullmatch(r'DBG S "(.*)" ([0-9a-f]+) ([0-9a-f]+)',
                                     text)
                path, addr, length = (match.group(1), int(match.group(2), 16),
                                      int(match.group(3), 16))
                with open(path, "wb") as out:
                    out.write(MEMORY[addr:addr + length])
                receipt = (f"Wrote {addr:08X} - {addr + length - 1:08X} "
                           f"({length} bytes) to '{path}'.").encode() + b"\0"
                _winapi.WriteFile(server, receipt)
            assert disconnect(server)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        for _ in range(2):
            pipe = winuae.WinuaeLocalPipe(pipe=name,
                                          directory=tmp_path / "A Player")
            assert pipe.read_memory(0x20, 0x40) == MEMORY[0x20:0x60]
            assert pipe.read_memory(0, 5) == MEMORY[:5]
            pipe.close()
    finally:
        thread.join(timeout=60)
        _winapi.CloseHandle(server)
    assert len(requests) == 4


# -- writing ---------------------------------------------------------------


def test_a_write_is_one_w_line_of_hex_bytes_and_is_read_back(rig):
    pipe, api, *_ = rig
    pipe.write_memory(0x100, bytes([0xA5, 0x5A, 0x00]))
    assert api.written[0] == b"DBG W 100 a5 5a 00\0"
    assert re.fullmatch(rb'DBG S "[^"]+" 100 3\0', api.written[1])
    assert api.memory[0x100:0x103] == bytes([0xA5, 0x5A, 0x00])
    assert pipe.can_write is True


def test_a_long_write_goes_sixteen_bytes_a_line(rig):
    pipe, api, *_ = rig
    pipe.write_memory(0x200, bytes(range(40)))
    lines = [m for m in api.written if m.startswith(b"DBG W")]
    assert [m.split()[2] for m in lines] == [b"200", b"210", b"220"]
    assert api.memory[0x200:0x228] == bytes(range(40))


def test_a_receipt_for_another_byte_is_an_error(rig):
    pipe, api, *_ = rig
    api.write_receipt = "Wrote A4 (164) at 00000100.B\n"
    with pytest.raises(amiga.PipeError, match="not the byte sent"):
        pipe.write_memory(0x100, b"\xa5")


def test_a_receipt_for_another_address_is_an_error(rig):
    pipe, api, *_ = rig
    api.write_receipt = "Wrote A5 (165) at 00000101.B\n"
    with pytest.raises(amiga.PipeError, match="not the byte sent"):
        pipe.write_memory(0x100, b"\xa5")


def test_a_reply_with_too_few_lines_is_an_error(rig):
    pipe, api, *_ = rig
    api.write_receipt = "Wrote A5 (165) at 00000100.B\n"
    with pytest.raises(amiga.PipeError, match="1 lines"):
        pipe.write_memory(0x100, b"\xa5\x5a")


def test_a_write_that_reads_back_different_is_an_error(rig):
    pipe, api, *_ = rig
    api.ignore_writes = True
    with pytest.raises(amiga.PipeError, match="differs from the bytes written"):
        pipe.write_memory(0x100, b"\xa5")


def test_a_target_write_goes_through_the_pipe_and_is_read_back(rig):
    pipe, api, *_ = rig
    tgt = amiga.AmigaTarget(pipe, amiga.MACHINES["secret-of-the-silver-blades"])
    assert tgt.can_write is True
    tgt.write(0x100, b"\xa5\x5a")
    assert api.written[0] == b"DBG W 100 a5 5a\0"
    assert re.fullmatch(rb'DBG S "[^"]+" 100 2\0', api.written[1])
    api.ignore_writes = True
    with pytest.raises(amiga.PipeError, match="differs from the bytes written"):
        tgt.write(0x100, b"\x01")


def test_an_unverified_write_is_not_read_back_and_its_difference_is_no_error(rig):
    pipe, api, *_ = rig
    tgt = amiga.AmigaTarget(pipe, amiga.MACHINES["secret-of-the-silver-blades"])
    api.ignore_writes = True            # as a game that has consumed the bytes
    tgt.write(0x100, b"\xa5", verify=False)
    assert api.written == [b"DBG W 100 a5\0"]


def test_an_unverified_write_still_checks_the_receipt_and_the_bounds(rig):
    pipe, api, *_ = rig
    api.write_receipt = "Wrote 00 (0) at 100.B\n"
    with pytest.raises(amiga.PipeError, match="receipt"):
        pipe.write_memory(0x100, b"\xa5", verify=False)
    with pytest.raises(ValueError):
        pipe.write_memory(0xC80000, b"\x01", verify=False)


def test_a_write_that_gets_no_answer_times_out_and_drops_the_handle(rig):
    pipe, api, *_ = rig
    pipe.read_memory(0, 8)
    api.silent = True
    with pytest.raises(amiga.PipeError, match="prompt"):
        pipe.write_memory(0x100, b"\x01")
    assert api.cancels == 1 and api.closes == 1 and pipe.lost


def test_a_first_request_with_no_answer_keeps_its_handle_until_winuae_replies(rig):
    pipe, api, clock, folder = rig
    api.silent = True
    with pytest.raises(winuae.PipeTimeout):
        pipe.read_memory(0, 16)
    assert api.closes == 0 and pipe.lost
    pipe.close()
    assert api.closes == 0
    clock.now += pipe.BACKOFF + 1
    with pytest.raises(winuae.PipeTimeout):
        pipe.read_memory(0x40, 16)
    assert len(api.written) == 1 and api.closes == 0
    api.resume()
    clock.now += pipe.BACKOFF + 1
    assert pipe.read_memory(0x40, 16) == MEMORY[0x40:0x50]
    assert len(api.written) == 2 and api.creates == 1 and not pipe.lost
    assert list(folder.glob("wish-*.bin")) == []
    pipe.close()
    assert api.closes == 1


def test_a_write_with_no_answer_on_a_fresh_handle_keeps_the_handle(rig):
    pipe, api, *_ = rig
    api.silent = True
    with pytest.raises(winuae.PipeTimeout):
        pipe.write_memory(0x100, b"\x01")
    pipe.close()
    assert api.closes == 0


def test_a_write_that_times_out_on_a_fresh_handle_keeps_the_handle(rig):
    pipe, api, *_ = rig
    api.write_hangs = True
    with pytest.raises(winuae.PipeTimeout):
        pipe.read_memory(0, 16)
    assert pipe.lost
    pipe.close()
    assert api.closes == 0


def test_a_slow_drain_and_its_request_share_the_calls_timeout(rig):
    pipe, api, clock, _folder = rig
    api.silent = True
    with pytest.raises(winuae.PipeTimeout):
        pipe.read_memory(0, 16)
    api.resume()
    api.read_cost = 1.5
    clock.now += pipe.BACKOFF + 1
    api.wait_ms.clear()
    assert pipe.read_memory(0x40, 16, timeout=2.0) == MEMORY[0x40:0x50]
    assert api.wait_ms[0] == 2000
    assert max(api.wait_ms[1:]) <= 500


def test_three_drain_timeouts_drop_the_handle_and_the_next_call_reconnects(rig):
    pipe, api, clock, _folder = rig
    api.silent = True
    with pytest.raises(winuae.PipeTimeout):
        pipe.read_memory(0, 16)
    for _ in range(pipe.DRAIN_TIMEOUTS):
        assert api.closes == 0
        clock.now += pipe.BACKOFF + 1
        with pytest.raises(winuae.PipeTimeout):
            pipe.read_memory(0, 16)
    assert api.closes == 1
    api.silent = False
    clock.now += pipe.BACKOFF + 1
    created = api.creates
    assert pipe.read_memory(0, 16) == MEMORY[:16]
    assert api.creates == created + 1


def test_a_late_reply_within_the_drain_attempts_keeps_the_handle(rig):
    pipe, api, clock, _folder = rig
    api.silent = True
    with pytest.raises(winuae.PipeTimeout):
        pipe.read_memory(0, 16)
    for _ in range(pipe.DRAIN_TIMEOUTS - 1):
        clock.now += pipe.BACKOFF + 1
        with pytest.raises(winuae.PipeTimeout):
            pipe.read_memory(0, 16)
    api.resume()
    clock.now += pipe.BACKOFF + 1
    assert pipe.read_memory(0x40, 16) == MEMORY[0x40:0x50]
    assert api.closes == 0 and api.creates == 1


def test_a_broken_pipe_while_a_reply_is_owed_still_closes_the_handle(rig):
    pipe, api, clock, _folder = rig
    api.silent = True
    with pytest.raises(winuae.PipeTimeout):
        pipe.read_memory(0, 16)
    api.broken_read = True
    clock.now += pipe.BACKOFF + 1
    with pytest.raises(amiga.PipeError, match="closed the pipe"):
        pipe.read_memory(0, 16)
    assert api.closes == 1


@pytest.mark.parametrize("addr, size", [
    (0x100, 0), (0x100, 65), (0x80000 - 1, 2), (0x80000, 1),
    (0xBFFFFF, 1), (0xC80000, 1), (0x1000000, 1), (0xC7FFFF, 2)])
def test_a_write_outside_the_bounds_sends_nothing(rig, addr, size):
    pipe, api, *_ = rig
    with pytest.raises(ValueError):
        pipe.write_memory(addr, bytes(size))
    assert api.written == []


def test_the_ends_of_chip_and_slow_memory_are_accepted(rig):
    pipe, api, *_ = rig
    api.memory.extend(bytes(0x80000))
    pipe.write_memory(0x80000 - 64, bytes(64))
    assert sum(m.startswith(b"DBG W") for m in api.written) == 4


def test_reordered_receipt_lines_are_an_error(rig):
    pipe, api, *_ = rig
    api.write_receipt = ("Wrote 5A (90) at 00000101.B\n"
                         "Wrote A5 (165) at 00000100.B\n")
    with pytest.raises(amiga.PipeError, match="not the byte sent"):
        pipe.write_memory(0x100, b"\xa5\x5a")


def test_too_many_receipt_lines_are_an_error(rig):
    pipe, api, *_ = rig
    api.write_receipt = ("Wrote A5 (165) at 00000100.B\n"
                         "Wrote A5 (165) at 00000101.B\n")
    with pytest.raises(amiga.PipeError, match="2 lines"):
        pipe.write_memory(0x100, b"\xa5")


def test_a_bad_receipt_on_the_second_line_says_how_much_was_sent(rig):
    pipe, api, *_ = rig
    api.write_receipts = [None, "Wrote 00 (0) at 00000110.B\n"]
    with pytest.raises(amiga.PipeError, match="16 of 20 bytes were sent"):
        pipe.write_memory(0x100, bytes(range(1, 21)))


def test_a_timeout_on_the_second_line_says_how_much_was_sent(rig):
    pipe, api, *_ = rig
    api.silent_after = 1
    with pytest.raises(amiga.PipeError, match="16 of 20 bytes were sent") as err:
        pipe.write_memory(0x100, bytes(range(1, 21)))
    assert err.value.timed_out


def test_a_read_back_timeout_after_good_receipts_says_not_checked(rig):
    pipe, api, *_ = rig
    api.silent_after = 1
    with pytest.raises(amiga.PipeError, match="3 of 3 bytes were sent and not "
                                              "checked") as err:
        pipe.write_memory(0x100, b"\x01\x02\x03")
    assert err.value.timed_out
    assert api.memory[0x100:0x103] == b"\x01\x02\x03"


def test_the_timeout_is_one_budget_for_the_whole_write(rig):
    pipe, api, *_ = rig
    api.write_cost = 0.1
    with pytest.raises(amiga.PipeError, match="and not checked") as err:
        pipe.write_memory(0x100, bytes(40), timeout=0.25)
    assert err.value.timed_out


def test_a_negative_address_sends_nothing(rig):
    pipe, api, *_ = rig
    with pytest.raises(ValueError):
        pipe.write_memory(-1, b"\x01")
    assert api.written == []


def test_the_end_of_slow_memory_is_written_and_read_back(rig):
    pipe, api, *_ = rig
    api.memory.extend(bytes(0xC80000 - len(api.memory)))
    data = bytes(range(64))
    pipe.write_memory(0xC80000 - 64, data)
    assert api.memory[0xC80000 - 64:] == data
    assert re.fullmatch(rb'DBG S "[^"]+" c7ffc0 40\0', api.written[-1])
