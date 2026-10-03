"""The DOS `no_encounters` switch on fakes: the gate before each move, `off`, the save guard, the live block.

Nothing here boots DOSBox-X.  The live check, which walks Pool of Radiance's
Slums with the switch on and then off, is `tools/dos/dosnoencounters.py live`.
"""

from __future__ import annotations

import pathlib
import sys

import pytest
from conftest import load_tools_module

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.dos import dosbox, dosboxx  # noqa: E402
from tools.dos import dosnoencounters as N  # noqa: E402

SLUMS = 0x14
GATE = 0x4A80


class FakeLive:
    """`LiveVariables` over a dict of words; entering and leaving are logged."""

    def __init__(self, words, events):
        self.words, self.events = words, events

    def __enter__(self):
        self.events.append("halt")
        return self

    def __exit__(self, *exc):
        self.events.append("run")
        return False

    def peek(self, address):
        return self.words.get(address, 0)

    def poke(self, address, value):
        self.events.append(("poke", address, value))
        self.words[address] = value


class FakeSession:
    """Enough of `dosbox.Session` for `PoolOfRadiance.move`; a key press runs
    `on_key`, which is where a fake game changes a word."""

    def __init__(self, events, on_key=lambda key: None):
        self.events, self.on_key = events, on_key

    def key(self, *keys, gap=0.35):
        for k in keys:
            self.events.append(("key", k))
            self.on_key(k)

    def settle(self):
        return None

    def wait_until_ink(self, rect, want, timeout):
        return True


def switch(words, title=N.POOL, area=SLUMS, events=None, lines=None):
    events = [] if events is None else events
    enc = N.NoEncounters.__new__(N.NoEncounters)
    enc.live = FakeLive(words, events)
    enc.live.area = lambda: area
    enc.switch = N.EncounterSwitch(title, enc.live.peek, enc.live.poke,
                                   enc.live.area,
                                   (lines if lines is not None else []).append)
    enc.writes = []
    enc.areas = {}
    return enc, events


def pool(enc, events, on_key=lambda key: None):
    por = N.SuppressedPool(FakeSession(events, on_key), enc)
    por.world_bar = "map"
    return por


def test_on_writes_the_gate_before_every_move_key_even_after_the_game_changes_it():
    words = {GATE: 4}
    enc, events = switch(words)

    def game(key):
        words[GATE] = 3          # the script lowers the counter on a step

    por = pool(enc, events, game)
    enc.on()
    por.step()
    por.turn_right()
    assert events == ["halt", ("poke", GATE, 15), "run", ("key", "Up"),
                      "halt", ("poke", GATE, 15), "run", ("key", "Right")]


def test_nothing_is_written_until_the_switch_is_on():
    words = {GATE: 4}
    enc, events = switch(words)
    pool(enc, events).step()
    assert events == [("key", "Up")]
    assert words[GATE] == 4


def test_off_restores_the_original_value():
    words = {GATE: 4}
    enc, events = switch(words)
    enc.on()
    pool(enc, events).step()
    rows = enc.off()
    assert words[GATE] == 4
    assert rows[0]["action"] == "restored"
    assert not enc.switch.active and not enc.switch.pending


def test_off_keeps_a_value_the_game_wrote_after_the_switch():
    words = {GATE: 4}
    enc, events = switch(words)
    enc.on()
    pool(enc, events).step()
    words[GATE] = 20             # the story moved on
    assert enc.off()[0]["action"] == "kept the game's value"
    assert words[GATE] == 20


def test_off_after_a_restore_brought_the_original_back_writes_nothing():
    words = {GATE: 4}
    enc, events = switch(words)
    enc.on()
    pool(enc, events).step()
    words[GATE] = 4              # a snapshot restore put the memory back
    events.clear()
    assert enc.off()[0]["action"] == "already original"
    assert not [e for e in events if isinstance(e, tuple) and e[0] == "poke"]


def test_a_save_is_stopped_while_on_and_before_any_key():
    enc, events = switch({GATE: 4})
    por = pool(enc, events)
    enc.on()
    with pytest.raises(N.SaveBlocked):
        por.save_game("D")
    assert events == []


def test_a_save_is_stopped_while_a_written_value_is_outstanding():
    enc, events = switch({GATE: 4})
    enc.on()
    pool(enc, events).step()
    enc.switch.active = False    # turned off without putting the value back
    with pytest.raises(N.SaveBlocked):
        enc.check_save()
    enc.off()
    enc.check_save()


def test_an_area_with_no_gate_is_logged_once_and_left_alone():
    lines = []
    enc, events = switch({GATE: 4}, area=0x00, lines=lines)
    por = pool(enc, events)
    enc.on()
    por.step()
    por.step()
    assert [e for e in events if isinstance(e, tuple) and e[0] == "poke"] == []
    assert lines == ["encounters are not suppressed in area $00: no gate is "
                     "known for it"]


def test_a_word_that_does_not_read_back_raises():
    words = {GATE: 4}
    enc, events = switch(words)
    enc.live.poke = lambda address, value: None
    enc.switch.poke = enc.live.poke
    enc.on()
    with pytest.raises(N.SwitchError):
        enc.before_move()


def test_later_titles_index_from_their_own_base():
    assert N.word_index(N.CURSE, 0x4C2C) == 0x12C
    assert N.word_index(N.POOL, 0x4A80) == 0x180
    with pytest.raises(ValueError):
        N.word_index(N.POOL, 0x4C2C + 0x200)


def test_every_dos_gate_writes_what_the_c64_gate_writes():
    gates = load_tools_module("session").ENCOUNTER_GATES
    assert set(N.GATES) <= set(gates)
    for key, gate in N.GATES.items():
        assert gate.pokes == gates[key].pokes, key


class StubX:
    """The few `dosboxx.XSession` calls `LiveVariables` makes, over a bytearray.
    Each halt shows the next `DS` in `halts`."""

    def __init__(self, memory, halts):
        self.memory, self.halts = memory, list(halts)
        self.ds = None
        self.calls = []

    def attach(self):
        self.calls.append("attach")
        self.ds = self.halts.pop(0) if self.halts else self.ds
        return True

    def regs(self, *names):
        return {"DS": self.ds}

    def run(self):
        self.calls.append("run")

    def read(self, at, n):
        at = dosboxx.linear(at)
        return bytes(self.memory[at:at + n])

    def write(self, at, data):
        self.calls.append(("write", at, bytes(data)))
        self.memory[at:at + len(data)] = data


def saved_block(gate=4):
    words = [((i * 7) % 251) | 0x100 * (i % 3 == 0) for i in range(N.BLOCK_WORDS)]
    for k in range(6):
        words[N.CLOCK_INDEX + k] = k + 1
    words[GATE - 0x4900] = gate
    return b"".join(w.to_bytes(2, "little") for w in words)


DS = 0x2F00
BASE = 0x3_1230


def machine(block, area=SLUMS):
    """A megabyte with Pool's engine pointer and area byte at `DS` and the
    variable block at `BASE`."""
    memory = bytearray(0x100000)
    memory[BASE:BASE + len(block)] = block
    engine = N.ENGINE[N.POOL]
    ptr = dosboxx.linear((DS, engine.pointer))
    memory[ptr:ptr + 4] = (BASE & 0xF).to_bytes(2, "little") + (BASE >> 4).to_bytes(2, "little")
    memory[dosboxx.linear((DS, engine.area))] = area
    return memory


def test_the_block_and_area_come_through_the_data_segment_and_a_gate_is_a_word():
    block = saved_block()
    x = StubX(machine(block), [DS])
    live = N.LiveVariables(x, N.POOL, b"\x01" + block)
    with live:
        assert live.base == BASE
        assert live.area() == SLUMS
        assert live.peek(GATE) == 4
        live.poke(GATE, 15)
        assert live.peek(GATE) == 15
    assert ("write", BASE + 2 * 0x180, b"\x0f\x00") in x.calls
    assert x.calls[0] == "attach" and x.calls[-1] == "run"


def test_a_halt_outside_the_game_is_run_on_until_one_shows_its_data_segment():
    block = saved_block()
    x = StubX(machine(block), [0x0040, 0xF000, DS])
    live = N.LiveVariables(x, N.POOL, b"\x01" + block)
    with live:
        assert live.ds == DS
    assert x.calls.count("attach") == 3


def test_a_block_that_does_not_match_the_save_is_not_believed():
    block = saved_block()
    x = StubX(machine(block), [DS] * N.DS_TRIES)
    other = bytes(len(block))
    with pytest.raises(N.SwitchError):
        N.LiveVariables(x, N.POOL, b"\x01" + other).__enter__()


def test_a_block_whose_clock_is_not_digits_is_not_believed():
    block = bytearray(saved_block())
    block[2 * N.CLOCK_INDEX + 1] = 0x7F
    x = StubX(machine(bytes(block)), [DS] * N.DS_TRIES)
    with pytest.raises(N.SwitchError):
        N.LiveVariables(x, N.POOL).__enter__()


def test_the_data_segment_is_found_from_the_pointer_in_a_memory_image():
    memory = machine(saved_block())
    pointer = N.ENGINE[N.POOL].pointer
    assert N.find_data_segments(bytes(memory), BASE, pointer) == [DS]


def test_suppressed_pool_is_the_ordinary_driver():
    assert issubclass(N.SuppressedPool, dosbox.PoolOfRadiance)
