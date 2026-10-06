"""Checks the WinUAE backend's flag gate and its connection, which holds the pipe
only while a target is attached. No emulator and no Windows are involved."""

from __future__ import annotations

import re

import pytest

from automap import amiga
from automap import winuae as winuae_transport
from automap.maps import AMIGA_ONLY_TITLES
from wish import amigalocate, winuae
from wish import backends as bk

BLADES = amiga.MACHINES["secret-of-the-silver-blades"]
BASE = 0xC10000


@pytest.fixture(autouse=True)
def fresh():
    winuae.reset()
    yield
    winuae.reset()


# -- the flag ------------------------------------------------------------------

def test_the_winuae_row_is_absent_by_default(monkeypatch):
    monkeypatch.delenv(bk.AMIGA_WINUAE_ENV, raising=False)
    assert bk.amiga_winuae_enabled() is False
    assert [b.name for b in bk.backends()] == ["VICE (C64)"]


@pytest.mark.parametrize("value", ["0", "off", "false", "no", "", "junk"])
def test_a_forgotten_setting_does_not_turn_the_winuae_row_on(
        monkeypatch, value):
    monkeypatch.setenv(bk.AMIGA_WINUAE_ENV, value)
    assert bk.amiga_winuae_enabled() is False
    assert [b.name for b in bk.backends()] == ["VICE (C64)"]


@pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
def test_the_winuae_row_appears_when_the_flag_is_set(
        monkeypatch, value):
    monkeypatch.setenv(bk.AMIGA_WINUAE_ENV, value)
    assert winuae.AMIGA_WINUAE in bk.backends()


def test_the_winuae_row_is_the_approved_one():
    row = winuae.AMIGA_WINUAE
    assert row.name == "WinUAE (Amiga)"
    assert row.setup_hint == "Run the game in WinUAE on this computer."
    assert row.probe is winuae.present
    assert row.connect is winuae.connect
    assert row.default_interval_ms == 200
    assert row.disturbs is False


def test_the_two_amiga_flags_are_independent(monkeypatch):
    monkeypatch.setenv(bk.AMIGA_FSUAE_ENV, "1")
    monkeypatch.delenv(bk.AMIGA_WINUAE_ENV, raising=False)
    assert winuae.AMIGA_WINUAE not in bk.backends()
    monkeypatch.setenv(bk.AMIGA_WINUAE_ENV, "1")
    assert [b.name for b in bk.backends()] == ["VICE (C64)", "WinUAE (Amiga)",
                                               "FS-UAE (Amiga)"]


def test_each_platforms_rows_are_grouped_with_the_c64_ones_first(
        monkeypatch):
    for env in (bk.AMIGA_FSUAE_ENV, bk.AMIGA_WINUAE_ENV, bk.ULTIMATE_ENV):
        monkeypatch.setenv(env, "1")
    assert [b.name for b in bk.backends()] == [
        "VICE (C64)", "C64 Ultimate", "WinUAE (Amiga)", "FS-UAE (Amiga)"]


def test_the_pools_of_darkness_folder_is_offered_with_only_the_winuae_flag(
        monkeypatch):
    monkeypatch.delenv(bk.AMIGA_FSUAE_ENV, raising=False)
    monkeypatch.delenv(bk.AMIGA_WINUAE_ENV, raising=False)
    assert bk.amiga_only_titles() == ()
    monkeypatch.setenv(bk.AMIGA_WINUAE_ENV, "1")
    assert bk.amiga_only_titles() == AMIGA_ONLY_TITLES


# -- the probe -----------------------------------------------------------------

def test_the_probe_is_false_when_the_pipe_directory_cannot_be_listed():
    def block(_path):
        raise OSError("no pipe directory here")
    assert winuae.present(block) is False


def test_the_probe_sees_a_winuae_pipe_and_not_a_lookalike():
    assert winuae.present(lambda _p: ["WinUAE_1"]) is True
    assert winuae.present(lambda _p: ["WinUAEx", "other"]) is False


# -- the connection ------------------------------------------------------------

class FakeTransport:
    halts_machine = False

    def __init__(self, pipe="WinUAE", memory=None):
        self.pipe = pipe
        self.memory = memory if memory is not None else {}
        self.closed = 0

    def read_memory(self, addr, length, timeout=None):
        out = bytearray(length)
        for base, blob in self.memory.items():
            lo, hi = max(addr, base), min(addr + length, base + len(blob))
            if lo < hi:
                out[lo - addr:hi - addr] = blob[lo - base:hi - base]
        return bytes(out)

    def close(self):
        self.closed += 1


def loaded() -> dict[int, bytes]:
    data = bytearray(0x8000)
    data[BLADES.anchor_offset:BLADES.anchor_offset + len(BLADES.anchor)] = \
        BLADES.anchor
    return {BASE: bytes(data)}


def test_a_loaded_title_gives_a_target_that_releases_the_pipe_on_close():
    transport = FakeTransport(memory=loaded())
    target = winuae.connect(pipes=lambda: ["WinUAE"],
                            factory=lambda pipe: transport)
    assert target.data_base == BASE and target.layout is BLADES
    assert target.halts_on_read is False
    target.close()
    assert transport.closed == 1


def test_a_failed_connect_releases_the_pipe_and_the_next_try_works():
    transport = FakeTransport()
    now = [0.0]
    locator = amigalocate.Locator(clock=lambda: now[0])
    kwargs = dict(pipes=lambda: ["WinUAE"], factory=lambda pipe: transport,
                  locator=locator)
    with pytest.raises(amiga.NotConnected):
        winuae.connect(**kwargs)
    assert transport.closed == 1
    transport.memory = loaded()
    now[0] += locator.SWEEP_EVERY
    assert winuae.connect(**kwargs).data_base == BASE


def test_no_pipe_is_a_not_connected():
    with pytest.raises(amiga.NotConnected):
        winuae.connect(pipes=lambda: [])


def test_the_first_pipe_is_used_and_a_different_one_replaces_it():
    first = FakeTransport("WinUAE", loaded())
    second = FakeTransport("WinUAE_1", loaded())
    made = iter([first, second])
    winuae.connect(pipes=lambda: ["WinUAE", "WinUAE_1"],
                   factory=lambda pipe: next(made))
    winuae.connect(pipes=lambda: ["WinUAE_1"], factory=lambda pipe: next(made))
    assert first.closed == 1


class _Done:
    """An overlapped call that has finished with `data`."""

    def __init__(self, data=b"", err=0, finished=True):
        self.data, self.err, self.finished = data, err, finished
        self.event = self

    def GetOverlappedResult(self, wait):
        return len(self.data), self.err

    def getbuffer(self):
        return self.data

    def cancel(self):
        pass


class PipeApi:
    """The `_winapi` calls a `WinuaeLocalPipe` makes, answering `DBG S` from
    `memory` unless `silent`."""

    def __init__(self, memory):
        self.memory = memory
        self.creates = self.closes = 0
        self.silent = False
        self.reply = None

    def CreateFile(self, *args):
        self.creates += 1
        return 7

    def SetNamedPipeHandleState(self, *args):
        pass

    def CloseHandle(self, handle):
        self.closes += 1

    def WriteFile(self, handle, data, overlapped=False):
        text = bytes(data).rstrip(b"\0").decode()
        if not self.silent:
            path, addr, length = re.fullmatch(
                r'DBG S "(.*)" ([0-9a-f]+) ([0-9a-f]+)', text).groups()
            addr, length = int(addr, 16), int(length, 16)
            out = bytearray(length)
            for base, blob in self.memory.items():
                lo, hi = max(addr, base), min(addr + length, base + len(blob))
                if lo < hi:
                    out[lo - addr:hi - addr] = blob[lo - base:hi - base]
            with open(path, "wb") as f:
                f.write(out)
            self.reply = (f"Wrote {addr:08X} - {addr + length - 1:08X} "
                          f"({length} bytes) to '{path}'.").encode() + b"\0"
        return _Done(data), winuae_transport.ERROR_IO_PENDING

    def ReadFile(self, handle, size, overlapped=False):
        reply = None if self.silent else self.reply
        return (_Done(reply or b"", 0, reply is not None),
                winuae_transport.ERROR_IO_PENDING)

    def WaitForSingleObject(self, event, ms):
        return 0 if event.finished else winuae_transport.WAIT_TIMEOUT


@pytest.fixture
def held(tmp_path):
    """A target on a real transport over a fake pipe, plus the pipe's counters."""
    api = PipeApi(loaded())
    transport = winuae_transport.WinuaeLocalPipe(
        directory=tmp_path / "dump", api=api, sleep=lambda _s: None)
    locator = amigalocate.Locator()
    target = winuae.connect(pipes=lambda: ["WinUAE"],
                            factory=lambda pipe: transport, locator=locator)
    return target, api, locator


def test_release_closes_the_handle_and_keeps_the_target(held):
    target, api, _ = held
    assert api.creates == 1 and api.closes == 0
    target.release()
    assert api.closes == 1


def test_the_next_read_after_a_release_reopens_the_pipe_without_a_sweep(held):
    target, api, locator = held
    target.release()
    reads = []
    inner = target.debugger.read_memory

    def watching(addr, length, timeout=None):
        reads.append((addr, length))
        return inner(addr, length, timeout)

    again = locator.target(watching, target.debugger, factory=winuae.WinuaeTarget)
    assert api.creates == 2
    assert reads == [(BASE + BLADES.anchor_offset, len(BLADES.anchor))]
    assert again.data_base == BASE


def test_a_release_while_a_reply_is_owed_keeps_the_handle(held):
    target, api, _ = held
    api.silent = True
    with pytest.raises(winuae_transport.PipeTimeout):
        target.debugger.read_memory(0, 16)
    target.release()
    assert api.closes == 0


# -- the sweep, which may not hold the window ----------------------------------

def test_a_sweep_stops_at_its_deadline_and_goes_on_from_what_it_read():
    transport = FakeTransport(memory=loaded())
    reads = []
    now = [1000.0]
    inner = transport.read_memory

    def counting(addr, length, timeout=None):
        reads.append((addr, length))
        now[0] += 0.1                               # what one piece costs
        return inner(addr, length)

    locator = amigalocate.Locator(clock=lambda: now[0])
    locator.SWEEP_DEADLINE = 0.65                   # two pieces a call
    paused = 0
    for _ in range(400):
        try:
            target = locator.target(counting, transport)
            break
        except locator.paused:
            paused += 1
    else:
        pytest.fail("the sweep never finished")
    assert paused > 1 and target.data_base == BASE
    assert len(reads) == len(set(reads))            # no piece read twice
    assert max(length for _, length in reads) <= locator.SWEEP_CHUNK


def _sizes_of_next_sweep(locator, transport):
    sizes = []
    inner = transport.read_memory

    def watching(addr, length, timeout=None):
        sizes.append(length)
        return inner(addr, length)

    locator.target(watching, transport)
    return sizes


def test_a_timed_out_piece_makes_the_next_sweep_use_smaller_pieces():
    transport = FakeTransport(memory=loaded())
    now = [0.0]
    locator = amigalocate.Locator(clock=lambda: now[0])

    def timing_out(addr, length, timeout=None):
        raise winuae_transport.PipeTimeout("Timed out.")

    with pytest.raises(amiga.PipeError):
        locator.target(timing_out, transport)
    now[0] += locator.SWEEP_EVERY
    assert max(_sizes_of_next_sweep(locator, transport)) == \
        locator.SWEEP_SMALL_CHUNK


def test_a_piece_that_fails_for_another_reason_does_not_shrink_the_pieces():
    transport = FakeTransport(memory=loaded())
    now = [0.0]
    locator = amigalocate.Locator(clock=lambda: now[0])

    def blocking(addr, length, timeout=None):
        raise amiga.PipeError("Blocked.")

    with pytest.raises(amiga.PipeError):
        locator.target(blocking, transport)
    now[0] += locator.SWEEP_EVERY
    assert max(_sizes_of_next_sweep(locator, transport)) == locator.SWEEP_CHUNK


def test_a_finished_sweep_goes_back_to_the_big_pieces():
    transport = FakeTransport(memory=loaded())
    now = [0.0]
    locator = amigalocate.Locator(clock=lambda: now[0])

    def timing_out(addr, length, timeout=None):
        raise winuae_transport.PipeTimeout("Timed out.")

    with pytest.raises(amiga.PipeError):
        locator.target(timing_out, transport)
    now[0] += locator.SWEEP_EVERY
    locator.target(transport.read_memory, transport)        # finishes, small
    locator.machine = locator.base = None
    now[0] += locator.SWEEP_EVERY
    assert max(_sizes_of_next_sweep(locator, transport)) == locator.SWEEP_CHUNK


def test_a_slow_sweep_that_keeps_gaining_pieces_outlasts_the_age_limit():
    transport = FakeTransport(memory=loaded())
    now = [1000.0]
    locator = amigalocate.Locator(clock=lambda: now[0])
    locator.SWEEP_DEADLINE = 0.0                    # one piece a tick
    locator._piece = locator.SWEEP_SMALL_CHUNK
    ticks = 0
    while True:
        ticks += 1
        now[0] += 1.0                               # steady ticks
        try:
            locator.target(transport.read_memory, transport)
            break
        except locator.paused:
            assert ticks < 500
    assert ticks * 1.0 > locator.SWEEP_CACHE_AGE


def test_a_gap_in_the_ticks_throws_the_unfinished_sweep_away():
    transport = FakeTransport(memory=loaded())
    now = [1000.0]
    locator = amigalocate.Locator(clock=lambda: now[0])
    locator.SWEEP_DEADLINE = 0.0
    with pytest.raises(locator.paused):
        locator.target(transport.read_memory, transport)
    first = dict(locator._pieces)
    now[0] += locator.SWEEP_CACHE_AGE + 1
    with pytest.raises(locator.paused):
        locator.target(transport.read_memory, transport)
    assert len(locator._pieces) == 1 and locator._pieces != first


def test_paused_ticks_never_close_the_pipe():
    transport = FakeTransport(memory=loaded())
    now = [1000.0]
    locator = amigalocate.Locator(clock=lambda: now[0])
    locator.SWEEP_DEADLINE = 0.0
    kwargs = dict(pipes=lambda: ["WinUAE"], factory=lambda pipe: transport,
                  locator=locator)
    paused = 0
    for _ in range(500):
        now[0] += 1.0
        try:
            winuae.connect(**kwargs)
            break
        except locator.paused:
            paused += 1
            assert transport.closed == 0
    assert paused > 3 and transport.closed == 0


def test_every_piece_gets_the_full_timeout_and_a_tick_stays_inside_its_budget():
    now = [1000.0]
    given, started_with = [], []

    class Costly(FakeTransport):
        def read_memory(self, addr, length, timeout=None):
            given.append(timeout)
            started_with.append(deadline - now[0])
            now[0] += timeout                       # the worst WinUAE may take
            return super().read_memory(addr, length)

    transport = Costly(memory=loaded())
    locator = amigalocate.Locator(clock=lambda: now[0])
    started = now[0]
    deadline = started + locator.SWEEP_DEADLINE
    with pytest.raises(locator.paused):
        locator.target(transport.read_memory, transport)
    assert set(given) == {locator.PIECE_TIMEOUT}
    # Only the first piece may start with less than a full timeout left.
    assert all(left >= locator.PIECE_TIMEOUT for left in started_with)
    assert now[0] - started <= locator.SWEEP_DEADLINE


def test_a_tick_that_re_reads_the_anchor_and_sweeps_takes_about_two_seconds():
    now = [1000.0]

    class Costly(FakeTransport):
        def read_memory(self, addr, length, timeout=None):
            now[0] += timeout
            return super().read_memory(addr, length)

    transport = Costly(memory=loaded())
    locator = amigalocate.Locator(clock=lambda: now[0])
    locator.machine, locator.base = BLADES, BASE + 0x100   # anchor no longer there
    started = now[0]
    with pytest.raises(locator.paused):
        locator.target(transport.read_memory, transport)
    assert now[0] - started <= 2.0


def test_a_timeout_or_broken_pipe_keeps_the_title_found():
    transport = FakeTransport(memory=loaded())
    now = [1000.0]
    locator = amigalocate.Locator(clock=lambda: now[0])
    locator.target(transport.read_memory, transport)
    for error in (winuae_transport.PipeTimeout("Timed out."),
                  amiga.PipeError("The pipe closed.")):
        def failing(debugger, machine, anchor_base=None, error=error):
            raise error

        with pytest.raises(amiga.PipeError):
            locator.target(transport.read_memory, transport, factory=failing)
        assert locator.machine is BLADES and locator.base == BASE


def test_pieces_older_than_the_age_limit_are_not_searched():
    transport = FakeTransport(memory=loaded())
    now = [0.0]
    locator = amigalocate.Locator(clock=lambda: now[0])
    locator.SWEEP_DEADLINE = 0.0                    # one piece a call
    with pytest.raises(locator.paused):
        locator.target(transport.read_memory, transport)
    assert locator._pieces
    now[0] += locator.SWEEP_CACHE_AGE + 1
    with pytest.raises(locator.paused):
        locator.target(transport.read_memory, transport)
    assert len(locator._pieces) == 1                # the old piece was dropped


def test_the_target_remembers_where_the_anchor_was_found():
    transport = FakeTransport(memory=loaded())
    target = winuae.connect(pipes=lambda: ["WinUAE"],
                            factory=lambda pipe: transport)
    assert target.anchor_base == BASE


def test_a_target_that_fails_its_own_check_makes_the_next_call_sweep_afresh():
    transport = FakeTransport(memory=loaded())
    now = [1000.0]
    locator = amigalocate.Locator(clock=lambda: now[0])
    bad_guard = [True]

    def factory(debugger, machine, anchor_base=None):
        if bad_guard[0]:
            raise amiga.GuestError("The data hunk is not where it was.")
        return amiga.AmigaTarget(debugger, machine, anchor_base=anchor_base)

    with pytest.raises(amiga.GuestError):
        locator.target(transport.read_memory, transport, factory=factory)
    assert locator.machine is None
    bad_guard[0] = False
    now[0] += locator.SWEEP_EVERY
    reads = []
    inner = transport.read_memory

    def counting(addr, length, timeout=None):
        reads.append(length)
        return inner(addr, length)

    target = locator.target(counting, transport, factory=factory)
    assert len(reads) > 1 and target.anchor_base == BASE


def test_reads_made_while_a_target_is_built_are_bounded_and_the_target_keeps_the_pipe():
    transport = FakeTransport(memory=loaded())
    given = []
    inner = transport.read_memory

    def watching(addr, length, timeout=None):
        given.append(timeout)
        return inner(addr, length)

    transport.read_memory = watching
    now = [1000.0]
    locator = amigalocate.Locator(clock=lambda: now[0])

    def factory(debugger, machine, anchor_base=None):
        debugger.read_memory(0, 4)                      # a guard word
        assert debugger.halts_machine is False
        return amiga.AmigaTarget(debugger, machine, anchor_base=anchor_base)

    del given[:]
    target = locator.target(transport.read_memory, transport, factory=factory)
    assert given[-1] == locator.PIECE_TIMEOUT
    assert target.debugger is transport
