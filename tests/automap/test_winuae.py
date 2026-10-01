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
    def __init__(self, server, chunk=None):
        self.server, self.chunk = server, chunk
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
        if not self.silent:
            self.pending = self._answer(bytes(data))
        return Ov(self, (data, 0)), winuae.ERROR_IO_PENDING

    def ReadFile(self, handle, size, overlapped=False):
        chunk = None if self.silent or not self.pending else self.pending.pop(0)
        return Ov(self, chunk), winuae.ERROR_IO_PENDING

    def WaitForSingleObject(self, event, ms):
        """Done when the call has an answer; a starved read never finishes."""
        return 0 if event.chunk is not None else winuae.WAIT_TIMEOUT

    # -- the emulator --
    def _answer(self, message: bytes) -> list[tuple[bytes, int]]:
        text = message[3:] if message.startswith(winuae.UTF8_BOM) else message
        text = text.rstrip(b"\0").decode("utf-8")
        match = re.fullmatch(r'DBG S "(.*)" ([0-9a-f]+) ([0-9a-f]+)', text)
        assert match, text
        path, addr, length = match.group(1), int(match.group(2), 16), \
            int(match.group(3), 16)
        with open(path, "wb") as out:
            out.write(MEMORY[addr:addr + length])
        reply = (self.receipt.replace("{path}", path) if self.receipt is not None else
                 f"Wrote {addr:08X} - {addr + length - 1:08X} "
                 f"({length} bytes) to '{path}'.").encode("utf-8")
        reply = reply if self.drop_nul else reply + b"\0"
        size = self.chunk or len(reply)
        pieces = [reply[i:i + size] for i in range(0, len(reply), size)]
        return [(piece, winuae.ERROR_MORE_DATA if i < len(pieces) - 1 else 0)
                for i, piece in enumerate(pieces)]


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



def test_a_receipt_for_another_request_is_refused_and_the_pipe_kept(rig):
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


def test_a_dump_path_too_long_for_winuae_is_refused_before_sending(tmp_path):
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
    def refuse(_path):
        raise OSError("nope")
    assert winuae.winuae_pipes(refuse) == []
    assert winuae.present(refuse) is False


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
    import threading
    import uuid

    name = f"wish-test-{uuid.uuid4().hex}"
    server = _winapi.CreateNamedPipe(
        "\\\\.\\pipe\\" + name, _winapi.PIPE_ACCESS_DUPLEX,
        _winapi.PIPE_TYPE_MESSAGE | _winapi.PIPE_READMODE_MESSAGE
        | _winapi.PIPE_WAIT, 1, 16384, 16384, 0, 0)
    requests = []

    def serve():
        for _ in range(2):
            _winapi.ConnectNamedPipe(server, overlapped=False)
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
            _winapi.DisconnectNamedPipe(server)

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
        thread.join(timeout=10)
        _winapi.CloseHandle(server)
    assert len(requests) == 4
