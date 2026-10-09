"""The Amiga `no_encounters` switch under WinUAE, through a fake debugger pipe.

The pipe answers `S` and `W` the way `automap.amiga.WinuaePipe.batch` does, on
an in-memory Amiga whose script statements are synthetic.  Each test builds
the title's data hunk, its script buffers and the anchor the target sweeps for,
and runs the real `AmigaTarget` over the fake.  The Pools of Darkness tests at
the end load each area script from the player's `Disk3/ECL.GLB` into that
buffer instead, and skip without the disks.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from automap import amiga
from tools.amiga import noencounters as ne

#: The table as shipped, before the fixture below makes every gate synthetic.
REAL_ROWS = ne.ROWS

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
    return ne.WinuaeState(tmp_path / "winuae-wish282-a.json")


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
    assert not any("error" in r or "stopped" in r for r in result["rows"])


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


@pytest.mark.parametrize("save", ["S", "s"])
def test_a_save_key_is_blocked_while_the_switch_is_on(state, save):
    pipe = FakePipe()
    build(pipe, "pool-of-radiance")
    switch(pipe, "pool-of-radiance", state).on()
    presses = []
    result = switch(pipe, "pool-of-radiance", state, presses).keys(["E", save, "C"])
    assert "turn it off first" in result["stopped"]
    assert presses == []
    switch(pipe, "pool-of-radiance", state).off()
    assert switch(pipe, "pool-of-radiance", state, presses).keys(["E", "S"])["pressed"] \
        == ["E", "S"]
    assert presses == ["E", "S"]


def test_a_save_key_is_blocked_while_a_change_is_still_recorded(state):
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
    assert "stopped" in switch(pipe, "pool-of-radiance", state, presses).keys(["S"])
    assert presses == []


def test_an_unreadable_state_blocks_a_save_key(state):
    state.path.write_text("{not json", encoding="utf-8")
    presses = []
    result = switch(FakePipe(), "pool-of-radiance", state, presses).keys(["S"])
    assert "cannot be read" in result["stopped"] and presses == []


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


def _left_recorded(pipe, state):
    """Pool switched on, then an `off` whose writes fail: off, rows still recorded."""
    build(pipe, "pool-of-radiance")
    switch(pipe, "pool-of-radiance", state).on()
    failing = switch(pipe, "pool-of-radiance", state)
    failing.memory.write = lambda address, data: {"error": "OSError: lost"}
    failing.off()


def test_off_without_the_lane_changes_nothing(state):
    """A process that does not hold the lane cannot turn the holder's switch off,
    with or without recorded rows."""
    pipe = FakePipe()
    build(pipe, "pool-of-radiance")
    switch(pipe, "pool-of-radiance", state).on()
    held = json.loads(state.path.read_text())
    for rows in (held["rows"], []):
        state.save({**held, "rows": rows})
        before = state.path.read_text()
        intruder = switch(pipe, "pool-of-radiance", state)

        def block():
            raise amiga.GuestError("fail the lane is claimed by wish266")
        intruder.lane_check = block
        with pytest.raises(amiga.GuestError):
            intruder.off()
        assert state.path.read_text() == before


def test_on_for_another_title_is_blocked_while_a_change_is_recorded(state):
    pipe = FakePipe()
    _left_recorded(pipe, state)
    with pytest.raises(ValueError, match="pool-of-radiance off"):
        switch(pipe, "secret-of-the-silver-blades", state).on()
    presses = []
    result = switch(pipe, "secret-of-the-silver-blades", state, presses).keys(["s"])
    assert "pool-of-radiance" in result["stopped"] and presses == []


def test_a_key_that_cannot_be_pressed_reports_the_keys_that_went_in(state):
    pipe = FakePipe()
    build(pipe, "pool-of-radiance")
    switch(pipe, "pool-of-radiance", state).on()
    pressed = []

    def press(name):
        if pressed:
            raise SystemExit(f"Key {name} was not pressed: fail")
        pressed.append(name)
    held = switch(pipe, "pool-of-radiance", state)
    held.press = press
    result = held.keys(["NP8", "NP4", "NP6"])
    assert result["pressed"] == ["NP8"]
    assert "NP4 was not pressed" in result["error"]


def test_a_failed_save_leaves_no_temporary_file(state, monkeypatch):
    state.save({"on": False, "rows": []})
    def broken(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(ne.os, "replace", broken)
    with pytest.raises(OSError):
        state.save({"on": True, "rows": []})
    assert sorted(p.name for p in state.path.parent.iterdir()) == ["winuae-wish282-a.json"]
    assert json.loads(state.path.read_text())["on"] is False


def test_each_holder_keeps_its_own_state_file(tmp_path, monkeypatch):
    """Two lanes each hold their own changes, so one holder's journal must not be another's."""
    monkeypatch.setattr(ne.scratch, "cache_dir", lambda *parts: tmp_path.joinpath(*parts))
    a, b = ne.winuae_state_path("wish282-a"), ne.winuae_state_path("wish282-b")
    assert a != b and a.parent == b.parent
    assert a.name == "winuae-wish282-a.json" and b.name == "winuae-wish282-b.json"


@pytest.mark.parametrize("holder", ["../x", "a b", "", "a" * 65])
def test_a_holder_that_is_not_a_file_name_has_no_state_file(holder):
    with pytest.raises(ValueError, match="holder"):
        ne.winuae_state_path(holder)


def test_the_command_line_opens_the_holders_pipe_and_state(tmp_path, monkeypatch):
    seen = {}

    class Pipe:
        def __init__(self, **kwargs):
            seen["pipe"] = kwargs

    monkeypatch.setattr(ne.scratch, "cache_dir", lambda *parts: tmp_path.joinpath(*parts))
    monkeypatch.setattr(ne.amiga, "WinuaePipe", Pipe)
    monkeypatch.setattr(ne.WinuaeEncounters, "off", lambda self: seen.setdefault("state", self.state.path) and {})
    assert ne.main(["--holder", "wish282-a", "--title", "pool-of-radiance", "off"]) == 0
    assert seen["pipe"] == {"holder": "wish282-a"}
    assert seen["state"] == tmp_path / "noencounters" / "winuae-wish282-a.json"


def test_status_needs_the_holder_because_the_state_is_the_holders(capsys):
    with pytest.raises(SystemExit):
        ne.main(["status"])


def test_an_old_per_guest_state_file_stops_the_command_line(tmp_path, monkeypatch, capsys):
    """Its originals are no longer read, so going on could leave a gate byte patched with no record."""
    monkeypatch.setattr(ne.scratch, "cache_dir", lambda *parts: tmp_path.joinpath(*parts))
    old = tmp_path / "noencounters" / "winuae.json"
    old.parent.mkdir()
    old.write_text("{}")
    assert ne.main(["--holder", "wish282-a", "--title", "pool-of-radiance", "off"]) == 1
    out = capsys.readouterr().out
    assert "winuae.json" in out and "per-holder" in out


# -- Pools of Darkness, against the player's script library -------------------

DARKNESS = "pools-of-darkness"
SCRIPT_BASE = 0x8000
SCRIPT_BUFFER = 0x1E00

#: Each `Disk3/ECL.GLB` release (sha256 prefix), the roll address of each
#: encounter gate in it, and the area whose script holds that roll.
DARKNESS_GATES = {
    "becddc5926af": {0x8BC7: 17, 0x8371: 25, 0x82EA: 32},
    "adb9afbd3eca": {0x8B88: 17, 0x838E: 25, 0x82EA: 32},
}

COMPARE, EXIT = 0x03, 0x00
CONDITIONS = {0x16: lambda a, b: a == b, 0x17: lambda a, b: a != b,
              0x18: lambda a, b: a < b, 0x19: lambda a, b: a > b,
              0x1A: lambda a, b: a <= b, 0x1B: lambda a, b: a >= b}


def darkness_libraries() -> dict[str, tuple[list[bytes], dict[int, int]]]:
    """Every distinct Pools of Darkness `ECL.GLB` on the player's Amiga disks,
    by sha256 prefix: its blocks and its area-to-block table."""
    import hashlib

    from automap.amiga import glib_blocks
    from tools.amiga import amigasaves, tripspace

    found = {}
    for _t, _label, _path, body in tripspace.disk_files(
            amigasaves.images(), {DARKNESS: "ECL.GLB"}):
        table = {s.area: s.block for s in tripspace.spaces(DARKNESS, body)}
        found[hashlib.sha256(body).hexdigest()[:12]] = (glib_blocks(body), table)
    if not found:
        pytest.skip("needs the player's Amiga Pools of Darkness disk 3")
    return found


def darkness_gates():
    return [r for r in REAL_ROWS if r.title == DARKNESS and r.kind == ne.GATE]


def test_each_darkness_gate_is_the_encounter_roll_of_one_area_and_save_takes_its_exit():
    from tools.amiga import tripspace

    # Operand counts for the three statements read here, from the script format.
    model = [(0, False)] * 0x100
    model[COMPARE] = model[ne.RANDOM] = (2, False)
    libraries = darkness_libraries()
    for key, (blocks, table) in libraries.items():
        assert key in DARKNESS_GATES, f"ECL.GLB {key} is a release with no rows"
        offsets = {ne.parse_spec(r.spec)[1] for r in darkness_gates()}
        assert set(DARKNESS_GATES[key]) <= offsets, key
        for row in darkness_gates():
            at = ne.parse_spec(row.spec)[1] - SCRIPT_BASE
            hits = sorted(area for area, block in table.items()
                          if ne.digest(blocks[block][at:at + ne.STATEMENT]) == row.digest)
            want = DARKNESS_GATES[key].get(at + SCRIPT_BASE)
            assert hits == ([want] if want is not None else []), (key, row.spec)
            if want is None:
                continue
            body = blocks[table[want]]
            roll = tripspace.decode(model, body, at)
            assert roll.op == ne.RANDOM and roll.operands[0][0] == 0, row.spec
            limit, variable = roll.operands[0][1], roll.operands[1]
            compare = tripspace.decode(model, body, roll.end)
            assert compare.op == COMPARE and variable in compare.operands, row.spec
            condition = tripspace.decode(model, body, compare.end)
            assert condition.op in CONDITIONS, row.spec
            assert body[condition.end] == EXIT, row.spec
            (ka, va), (kb, vb) = compare.operands
            a = limit if (ka, va) == variable else va
            b = limit if (kb, vb) == variable else vb
            assert CONDITIONS[condition.op](a, b), f"SAVE {limit} misses the EXIT at {row.spec}"


def test_darkness_on_changes_only_the_loaded_area_s_roll_and_off_puts_the_script_back(
        state, monkeypatch):
    monkeypatch.setattr(ne, "ROWS", REAL_ROWS)
    libraries = darkness_libraries()
    for key, (blocks, table) in libraries.items():
        pipe = FakePipe()
        build(pipe, DARKNESS)
        pointer = ne.parse_spec(darkness_gates()[0].spec)[0]
        buffer = int.from_bytes(pipe.get(DATA_BASE + pointer, 4), "big")
        for area, block in sorted(table.items()):
            script = blocks[block].ljust(SCRIPT_BUFFER, b"\0")
            pipe.put(buffer + SCRIPT_BASE, script)
            switch(pipe, DARKNESS, state).on()
            now = pipe.get(buffer + SCRIPT_BASE, SCRIPT_BUFFER)
            changed_at = [i + SCRIPT_BASE for i in range(SCRIPT_BUFFER) if now[i] != script[i]]
            want = sorted(at for at, a in DARKNESS_GATES.get(key, {}).items() if a == area)
            assert changed_at == want, (key, area)
            assert all(now[at - SCRIPT_BASE] == ne.SAVE for at in want)
            result = switch(pipe, DARKNESS, state).off()
            assert "error" not in result, (key, area)
            assert pipe.get(buffer + SCRIPT_BASE, SCRIPT_BUFFER) == script, (key, area)


def test_a_row_whose_area_is_not_loaded_is_stopped_with_that_said_and_nothing_is_written(state):
    pipe = FakePipe()
    gates = build(pipe, "pool-of-radiance")
    address = next(iter(gates.values()))
    pipe.put(address, b"\x01" * len(STATEMENT))
    result = switch(pipe, "pool-of-radiance", state).on()
    stopped = [r for r in result["rows"] if r.get("row") and "stopped" in r]
    assert any("loaded script is not this row's area" in r["stopped"] for r in stopped)
    assert pipe.get(address, len(STATEMENT)) == b"\x01" * len(STATEMENT)
