"""The Amiga `no_encounters` switch under WinUAE, through a fake debugger pipe.

The pipe answers `S` and `W` the way `automap.amiga.WinuaePipe.batch` does, on
an in-memory Amiga whose script statements are synthetic: no game data.  Each
test builds the title's data hunk, its script buffers and the anchor the
target sweeps for, and runs the real `AmigaTarget` over the fake.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from automap import amiga
from tools.amiga import noencounters as ne

#: A synthetic roll statement, opcode `RANDOM` first, standing in for each gate.
STATEMENT = bytes([ne.RANDOM, 0x13, 0x00, 0x6E, 0x79, 0x00])
TITLES = sorted({row.title for row in ne.ROWS})
DATA_BASE = 0x10000
POOL_ANCHOR_BASE = 0x8000
BUFFERS = (0x30000, 0x50000)


class FakePipe:
    """`WinuaePipe`'s `batch` and `drives`, over chip and slow memory held here."""

    halts_machine = False

    def __init__(self):
        self.memory = {base: bytearray(size) for base, size in amiga.MEMORY}
        self.batches: list[list[str]] = []
        self.lanes: list[str] = []

    def _at(self, address, n):
        for base, buf in self.memory.items():
            if base <= address and address + n <= base + len(buf):
                return buf, address - base
        raise AssertionError(f"{address:#x}+{n} is outside the fake memory")

    def get(self, address, n):
        buf, at = self._at(address, n)
        return bytes(buf[at:at + n])

    def put(self, address, data):
        buf, at = self._at(address, len(data))
        buf[at:at + len(data)] = data

    def batch(self, lines, fetch=None):
        self.batches.append(list(lines))
        files = {}
        for line in lines:
            words = line.split()
            if words[0] == "S":
                files[words[1]] = self.get(int(words[2], 16), int(words[3], 16))
            elif words[0] == "W":
                self.put(int(words[1], 16), bytes(int(w, 16) for w in words[2:]))
            else:
                raise AssertionError(f"the switch sent {line!r}")
        text = "\n".join(f"--- {line}" for line in lines)
        return text, {name: files.get(path) for name, path in (fetch or [])}

    def drives(self, holder):
        self.lanes.append(holder)

    def writes(self):
        return [line for lines in self.batches for line in lines if line.startswith("W")]

    def sweeps(self):
        return sum(1 for lines in self.batches for line in lines
                   if line.startswith("S") and int(line.split()[3], 16) >= 0x40000)


@pytest.fixture(autouse=True)
def synthetic_digests(monkeypatch):
    """Every gate is recognised by the synthetic statement's hash."""
    monkeypatch.setattr(ne, "ROWS", tuple(
        dataclasses.replace(r, digest=ne.digest(STATEMENT)) if r.kind == ne.GATE else r
        for r in ne.ROWS))


def build(pipe: FakePipe, title: str) -> dict[str, int]:
    """Lay the title out in `pipe`'s memory; give each gate spec's address."""
    layout = amiga.MACHINES[title]
    seg = layout.segments
    anchor_base = DATA_BASE if seg is None else POOL_ANCHOR_BASE
    pipe.put(anchor_base + layout.anchor_offset, layout.anchor)
    if seg is not None:
        pipe.put(anchor_base - 8, (seg.anchor_size + 8).to_bytes(4, "big"))
        pipe.put(anchor_base - 4, ((DATA_BASE - 4) // 4).to_bytes(4, "big"))
        pipe.put(DATA_BASE - 8, (seg.data_size + 8).to_bytes(4, "big"))
    pointers = sorted({ne.parse_spec(r.spec)[0] for r in ne.rows_for(title)})
    for pointer, buffer in zip(pointers, BUFFERS, strict=False):
        pipe.put(DATA_BASE + pointer, buffer.to_bytes(4, "big"))
    gates = {}
    for row in ne.rows_for(title):
        pointer, offset = ne.parse_spec(row.spec)
        address = BUFFERS[pointers.index(pointer)] + offset
        if row.kind == ne.GATE:
            pipe.put(address, STATEMENT)
            gates[row.spec] = address
        else:
            pipe.put(address, b"\x00\x28"[:len(row.new)] if len(row.new) == 2 else b"\x28")
    return gates


def switch(pipe, title, state, presses=None):
    target = amiga.AmigaTarget(pipe, amiga.MACHINES[title])
    return ne.WinuaeEncounters(
        title, target, state=state, lane_check=lambda: pipe.drives("wish266"),
        press=(presses.append if presses is not None else lambda name: None))


def changed(title, spec):
    row = next(r for r in ne.rows_for(title) if r.spec == spec)
    out = bytearray(STATEMENT)
    for offset, value in row.changes:
        out[offset] = value
    return bytes(out)


@pytest.fixture
def state(tmp_path):
    return ne.WinuaeState(tmp_path / "winuae.json")


@pytest.mark.parametrize("title", TITLES)
def test_on_changes_every_gate_and_records_it(title, state):
    pipe = FakePipe()
    gates = build(pipe, title)
    result = switch(pipe, title, state).on()
    for spec, address in gates.items():
        assert pipe.get(address, 6) == changed(title, spec), spec
    saved = json.loads(state.path.read_text())
    assert saved["on"] is True and saved["title"] == title
    assert sorted(r["address"] for r in saved["rows"]) == sorted(gates.values())
    assert saved["data_base"] == DATA_BASE
    assert pipe.lanes == ["wish266"]
    assert not any("error" in r or "refused" in r for r in result["rows"])


@pytest.mark.parametrize("title", TITLES)
def test_keys_write_the_gate_again_before_every_move_after_a_reload(title, state):
    pipe = FakePipe()
    gates = build(pipe, title)
    switch(pipe, title, state).on()
    seen = []

    def press(name):
        # What the game holds as the key goes in; then the step reloads the script.
        seen.append({spec: pipe.get(a, 6) for spec, a in gates.items()})
        for address in gates.values():
            pipe.put(address, STATEMENT)

    for address in gates.values():
        pipe.put(address, STATEMENT)    # reloaded between two processes
    later = switch(pipe, title, state)
    later.press = press
    result = later.keys(["NP8", "NP8", "NP2"])
    assert result["pressed"] == ["NP8", "NP8", "NP2"]
    assert seen == [{spec: changed(title, spec) for spec in gates}] * 3


@pytest.mark.parametrize("title", TITLES)
def test_off_puts_every_original_back(title, state):
    pipe = FakePipe()
    gates = build(pipe, title)
    switch(pipe, title, state).on()
    result = switch(pipe, title, state).off()
    assert "error" not in result
    for address in gates.values():
        assert pipe.get(address, 6) == STATEMENT
    saved = json.loads(state.path.read_text())
    assert saved["on"] is False and saved["rows"] == []


def test_a_save_key_is_refused_while_the_switch_is_on(state):
    pipe = FakePipe()
    build(pipe, "pool-of-radiance")
    switch(pipe, "pool-of-radiance", state).on()
    presses = []
    result = switch(pipe, "pool-of-radiance", state, presses).keys(["E", "S", "C"])
    assert "turn it off first" in result["refused"]
    assert presses == []
    switch(pipe, "pool-of-radiance", state).off()
    assert switch(pipe, "pool-of-radiance", state, presses).keys(["E", "S"])["pressed"] \
        == ["E", "S"]
    assert presses == ["E", "S"]


def test_a_save_key_is_refused_while_a_change_is_still_recorded(state):
    """An `off` that could not write leaves the switch off and the row recorded."""
    pipe = FakePipe()
    gates = build(pipe, "pool-of-radiance")
    switch(pipe, "pool-of-radiance", state).on()
    failing = switch(pipe, "pool-of-radiance", state)
    failing.memory.write = lambda address, data: {"error": "OSError: lost"}
    assert "error" in failing.off()
    saved = json.loads(state.path.read_text())
    assert saved["on"] is False and len(saved["rows"]) == len(gates)
    presses = []
    assert "refused" in switch(pipe, "pool-of-radiance", state, presses).keys(["S"])
    assert presses == []


def test_an_unreadable_state_refuses_a_save_key(state):
    state.path.write_text("{not json", encoding="utf-8")
    presses = []
    result = switch(FakePipe(), "pool-of-radiance", state, presses).keys(["S"])
    assert "cannot be read" in result["refused"] and presses == []


def test_keys_with_the_switch_never_on_write_nothing(state):
    pipe = FakePipe()
    build(pipe, "pool-of-radiance")
    presses = []
    switch(pipe, "pool-of-radiance", state, presses).keys(["NP8", "S"])
    assert presses == ["NP8", "S"]
    assert pipe.batches == [] and pipe.lanes == []


def test_a_killed_run_is_put_back_and_its_originals_are_the_game_s(state):
    """A run killed while on leaves its rows; the next `on` puts them back and
    reads the game's own bytes, so a later `off` restores the real statement."""
    pipe = FakePipe()
    gates = build(pipe, "pool-of-radiance")
    switch(pipe, "pool-of-radiance", state).on()
    switch(pipe, "pool-of-radiance", state).on()      # a second process, as after a kill
    for row in json.loads(state.path.read_text())["rows"]:
        assert bytes.fromhex(row["original"]) == STATEMENT[:len(bytes.fromhex(row["original"]))]
    switch(pipe, "pool-of-radiance", state).off()
    assert all(pipe.get(a, 6) == STATEMENT for a in gates.values())


def test_a_reloaded_script_is_left_alone_by_off(state):
    pipe = FakePipe()
    gates = build(pipe, "pool-of-radiance")
    switch(pipe, "pool-of-radiance", state).on()
    other = bytes([ne.SAVE, 0x02, 0x00, 0x11, 0x22, 0x33])
    address = next(iter(gates.values()))
    pipe.put(address, other)     # another area's script, already SAVE there
    pipe.batches.clear()
    switch(pipe, "pool-of-radiance", state).off()
    assert pipe.get(address, 6) == other
    assert not any(line.startswith(f"W {address:x}") for line in pipe.writes())


def test_the_recorded_base_saves_the_sweep_and_a_moved_game_is_found_again(state):
    pipe = FakePipe()
    build(pipe, "pool-of-radiance")
    switch(pipe, "pool-of-radiance", state).on()
    assert pipe.sweeps() >= 1
    pipe.batches.clear()
    switch(pipe, "pool-of-radiance", state).keys(["NP8"])
    assert pipe.sweeps() == 0
    saved = json.loads(state.path.read_text())
    state.save({**saved, "anchor_base": POOL_ANCHOR_BASE + 0x100})
    pipe.batches.clear()
    switch(pipe, "pool-of-radiance", state).keys(["NP8"])
    assert pipe.sweeps() >= 1


def test_a_move_with_the_switch_on_costs_one_round_trip(state):
    pipe = FakePipe()
    build(pipe, "pool-of-radiance")
    switch(pipe, "pool-of-radiance", state).on()
    held = switch(pipe, "pool-of-radiance", state)
    held.keys(["NP8"])
    pipe.batches.clear()
    held.keys(["NP8"])
    assert len(pipe.batches) == 1 and pipe.writes() == []
