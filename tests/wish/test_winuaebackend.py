"""Checks the WinUAE backend's flag gate and its connection, which holds the pipe
only while a target is attached. No emulator and no Windows are involved."""

from __future__ import annotations

import pytest

from automap import amiga
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


@pytest.fixture
def stand_in(monkeypatch):
    """A row for the flag to offer: the real one waits for approved wording."""
    row = bk.Backend(name="Test row", probe=winuae.present,
                     connect=winuae.connect, setup_hint="test")
    monkeypatch.setattr(winuae, "AMIGA_WINUAE", row, raising=False)
    return row


# -- the flag ------------------------------------------------------------------

def test_the_winuae_row_is_absent_by_default(monkeypatch, stand_in):
    monkeypatch.delenv(bk.AMIGA_WINUAE_ENV, raising=False)
    assert bk.amiga_winuae_enabled() is False
    assert [b.name for b in bk.backends()] == ["VICE"]


@pytest.mark.parametrize("value", ["0", "off", "false", "no", "", "junk"])
def test_a_forgotten_setting_does_not_turn_the_winuae_row_on(
        monkeypatch, stand_in, value):
    monkeypatch.setenv(bk.AMIGA_WINUAE_ENV, value)
    assert bk.amiga_winuae_enabled() is False
    assert [b.name for b in bk.backends()] == ["VICE"]


@pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
def test_the_winuae_row_appears_when_the_flag_is_set(
        monkeypatch, stand_in, value):
    monkeypatch.setenv(bk.AMIGA_WINUAE_ENV, value)
    assert bk.backends()[-1] is stand_in


def test_the_flag_alone_offers_nothing_until_the_row_exists(monkeypatch):
    monkeypatch.setenv(bk.AMIGA_WINUAE_ENV, "1")
    monkeypatch.delattr(winuae, "AMIGA_WINUAE", raising=False)
    assert [b.name for b in bk.backends()] == ["VICE"]


def test_the_two_amiga_flags_are_independent(monkeypatch, stand_in):
    monkeypatch.setenv(bk.AMIGA_FSUAE_ENV, "1")
    monkeypatch.delenv(bk.AMIGA_WINUAE_ENV, raising=False)
    assert stand_in not in bk.backends()
    monkeypatch.setenv(bk.AMIGA_WINUAE_ENV, "1")
    assert [b.name for b in bk.backends()] == ["VICE", "Amiga (FS-UAE)",
                                               "Test row"]


def test_the_pools_of_darkness_folder_is_offered_with_only_the_winuae_flag(
        monkeypatch):
    monkeypatch.delenv(bk.AMIGA_FSUAE_ENV, raising=False)
    monkeypatch.delenv(bk.AMIGA_WINUAE_ENV, raising=False)
    assert bk.amiga_only_titles() == ()
    monkeypatch.setenv(bk.AMIGA_WINUAE_ENV, "1")
    assert bk.amiga_only_titles() == AMIGA_ONLY_TITLES


# -- the probe -----------------------------------------------------------------

def test_the_probe_is_false_when_the_pipe_directory_cannot_be_listed():
    def refuse(_path):
        raise OSError("no pipe directory here")
    assert winuae.present(refuse) is False


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
