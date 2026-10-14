"""`RELOAD_GATES`: the gates a snapshot reload holds let the area's roll draw
and stop only the fight, so the generator moves past the encounter's draw."""

from __future__ import annotations

import pytest

from goldbox import c64_port as G
from tools.c64 import session as S

SLUMS = 0x14
LIMIT = S.POOL_SLUMS_ROLL_AT + S.POOL_SLUMS_ROLL_LIMIT


class _Mon:
    def __init__(self, mem):
        self.mem = mem

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, addr, n, **kw):
        return bytes(self.mem.get(addr + i, 0) for i in range(n))

    def write(self, addr, data, **kw):
        for i, b in enumerate(data):
            self.mem[addr + i] = b

    def resume(self):
        pass


class _Pool(S.Session):
    game = G.POOL_OF_RADIANCE

    def __init__(self, area=SLUMS, script=S.POOL_SLUMS_ROLL):
        self.mem = {S.AREA_BYTE[self.game.key].addr: area, 0x4A80: 1}
        for i, b in enumerate(script):
            self.mem[S.POOL_SLUMS_ROLL_AT + i] = b
        self.lines = []
        self.no_encounters = True
        self._restored_unattached = False

    def mon(self, timeout=5.0):
        return _Mon(self.mem)

    def log(self, *a):
        self.lines.append(" ".join(map(str, a)))


def test_the_slums_reload_gate_patches_the_compare_and_leaves_the_cap_alone():
    s = _Pool()
    s.draw_keeping_gates = True
    s.suppress_encounters()
    assert s.mem[LIMIT] == 0xFF and s.mem[0x4A80] == 1
    rows = s.restore_encounter_gates()
    assert s.mem[LIMIT] == 0x0C
    assert [(r["address"], r["original"], r["written"], r["verified"]) for r in rows] == [
        (f"${LIMIT:04X}", 0x0C, 0xFF, True)]


def test_without_the_reload_table_the_slums_still_get_the_cap():
    s = _Pool()
    s.suppress_encounters()
    assert s.mem[0x4A80] == 15 and s.mem[LIMIT] == 0x0C


def test_the_slums_reload_gate_writes_nothing_over_another_script():
    s = _Pool(script=bytes(len(S.POOL_SLUMS_ROLL)))
    s.draw_keeping_gates = True
    s.suppress_encounters()
    assert s.mem[LIMIT] == 0 and s.mem[0x4A80] == 1


def test_an_area_with_only_a_draw_skipping_gate_has_no_reload_gate():
    s = _Pool(area=0x06)
    s.draw_keeping_gates = True
    assert s.encounter_gate(0x06) is None
    assert S.ENCOUNTER_GATES[(G.POOL_OF_RADIANCE.key, 0x06)] is not None
    s.suppress_encounters()
    assert any("not suppressed" in line for line in s.lines)


def test_every_reload_gate_is_a_script_gate_with_its_pokes_inside_its_guards():
    for key, gate in S.RELOAD_GATES.items():
        assert gate.guards, key
        for addr, _value in gate.pokes:
            at, want = gate.guard_at(addr)
            assert at <= addr < at + len(want), key


def test_the_slums_guard_is_the_scripts_roll_and_the_cap_exits_before_it():
    from automap import gamedisks
    if not gamedisks.find(G.POOL_OF_RADIANCE.key):
        pytest.skip("needs the Pool of Radiance C64 disks")
    from tools.areas import ecllist
    from tools.areas.eclsweep import decode
    _game, _root, machine, base, bodies = ecllist.load(G.POOL_OF_RADIANCE.key)
    body = bodies["ECL14"]
    off = S.POOL_SLUMS_ROLL_AT - base
    assert body[off:off + len(S.POOL_SLUMS_ROLL)] == S.POOL_SLUMS_ROLL
    # The cap: COMPARE [$4A80], #15 / IF>= / EXIT, then the RANDOM.
    cap = decode(machine, body, off - 8)
    assert cap.op == ecllist.COMPARE and (0x01, 0x4A80) in cap.operands
    assert decode(machine, body, decode(machine, body, cap.end).end).op == ecllist.EXIT
    random = decode(machine, body, off)
    assert random.op == 0x08 and random.operands[0][1] == 13
    # The last compare: its immediate is the poked byte, and with 255 the
    # IF<= takes the EXIT for every roll plus both bonuses.
    st = random
    while st.op != ecllist.COMPARE or st.end != off + len(S.POOL_SLUMS_ROLL) - 2:
        st = decode(machine, body, st.end)
    test = decode(machine, body, st.end)
    assert body[S.POOL_SLUMS_ROLL_LIMIT + off] == 12
    assert decode(machine, body, test.end).op == ecllist.EXIT
    assert all(ecllist.TESTS[test.op](roll, 255) for roll in range(13 + 4 + 5 + 1))
    assert not ecllist.TESTS[test.op](13, 12)
