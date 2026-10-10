"""The DOS `no_encounters` switch for Pools of Darkness: the script rows against the player's `ECL1.DAX`, the switch on fakes, and `--no-encounters --title darkness`.

Nothing here boots DOSBox-X.  The tests that read `ECL1.DAX` (and, for the
scan, the Amiga executable) skip without the player's disks; no game bytes are
in the repository, only the short hashes `SCRIPT_GATES` names its rows by.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.dos import acceptance as da  # noqa: E402
from tools.dos import dosboxx  # noqa: E402
from tools.dos import dosnoencounters as N  # noqa: E402

ROWS = N.SCRIPT_GATES[N.DARKNESS]


def constant_rows():
    """The rows `scan` lists: `RANDOM n` compared with a constant."""
    return [r for r in ROWS if r.form == N.CONSTANT]


@pytest.fixture(scope="module")
def scripts() -> dict[int, bytes]:
    try:
        return N.darkness_scripts()
    except FileNotFoundError:
        pytest.skip("needs the player's DOS Pools of Darkness archive")


# -- the rows against the scripts on the player's disks -----------------------

#: Operand counts of the statements a row's roll runs through, from the script
#: format: `RANDOM`, `SAVE` and `COMPARE` take two operands, `ADD` three,
#: `GOTO` one, `IF` and `EXIT` none.
MODEL = [(0, False)] * 0x100
MODEL[N.RANDOM] = MODEL[N.SAVE] = MODEL[0x03] = (2, False)
MODEL[0x04] = (3, False)
MODEL[0x01] = (1, False)


def test_each_row_is_one_area_s_roll_and_its_change_takes_the_exit(scripts):
    from tools.amiga import tripspace as ts

    assert len(scripts) == 56
    for row in constant_rows():
        at = row.address - N.SCRIPT_BASE
        hits = sorted(area for area, body in scripts.items()
                      if N.digest(body[at:at + N.GUARD_BYTES]) == row.guard)
        assert hits == [row.area], f"${row.address:04X}"
        body = scripts[row.area]
        limit, exits, end = N.roll_exit(MODEL, body, at)
        assert end - at == N.GUARD_BYTES
        changed = bytearray(body[at:at + N.GUARD_BYTES])
        for offset, value in row.changes:
            changed[offset] = value
        saved = ts.decode(MODEL, bytes(changed), 0)
        assert changed[0] == N.SAVE and saved.operands[0][0] == 0
        assert exits(saved.operands[0][1]), f"${row.address:04X} misses the EXIT"
        assert not all(exits(r) for r in range(limit + 1)), "the roll never fights"


def test_the_rows_are_every_step_entry_roll_with_a_fight_behind_it(scripts):
    try:
        found = N.scan_darkness()
    except N.SwitchError as e:
        pytest.skip(f"needs the player's Amiga Pools of Darkness executable: {e}")
    fights = {(f["area"], f["address"], f["guard"]) for f in found if f["combat"]}
    assert fights == {(r.area, r.address, r.guard) for r in constant_rows()}
    assert all(f["save"] is not None for f in found if f["combat"])


def test_every_area_has_a_row_or_makes_no_roll(scripts):
    rowed = {r.area for r in ROWS}
    assert not rowed & N.DARKNESS_NO_ROLL
    assert set(scripts) == rowed | N.DARKNESS_NO_ROLL
    for row in ROWS:
        at = row.address - N.SCRIPT_BASE
        hits = sorted(area for area, body in scripts.items()
                      if N.digest(body[at:at + N.GUARD_BYTES]) == row.guard)
        assert hits == [row.area], f"${row.address:04X}"


def test_the_rows_are_the_amiga_switch_s_rows_for_the_same_scripts():
    """The Amiga `becddc5926af` library's rows, area for area, with the same
    change; area 33's DOS roll sits eight bytes on and was found live."""
    from tools.amiga import noencounters as A

    amiga = {(area, at): changes for at, _s, _e, changes, area, library, _w
             in A._DARKNESS_GATES if library in ("becddc", "both") and area != 33}
    dos = {(r.area, r.address): r.changes for r in ROWS if r.area != 33}
    assert dos == amiga
    assert N.DARKNESS_NO_ROLL == {area for _e, area, _l, _b in A._DARKNESS_NONE}


def _value(operand, env):
    kind, value = operand
    return env.get(value, 0) if kind in (0x01, 0x03) else value


def _run(body: bytes, at: int, env: dict, roll: int) -> str:
    """Run a roll from `at`: `RANDOM` stores `roll`, `SAVE` its constant, `ADD`
    its sum, each into a byte; an `IF` that fails skips the next statement.
    `"exit"` where an `EXIT` or `$23` ends it, else the opcode it went on to."""
    i, a, b = at, 0, 0
    for _ in range(12):
        s = ts_decode(body, i)
        if s.op == N.RANDOM:
            env[s.operands[1][1]] = roll & 0xFF
        elif s.op == N.SAVE:
            env[s.operands[1][1]] = _value(s.operands[0], env) & 0xFF
        elif s.op == 0x03:
            a, b = (_value(o, env) for o in s.operands)
        elif s.op == 0x04:
            env[s.operands[2][1]] = (_value(s.operands[0], env)
                                     + _value(s.operands[1], env)) & 0xFF
        elif s.op in N.CONDITIONS:
            if not N.CONDITIONS[s.op](a, b):
                i = ts_decode(body, s.end).end
                continue
        elif s.op in (0x00, 0x23):
            return "exit"
        else:
            return f"${s.op:02X}"
        i = s.end
    raise AssertionError(f"no end within twelve statements of ${at:04X}")


def ts_decode(body: bytes, i: int):
    from tools.amiga import tripspace as ts

    s = ts.decode(MODEL, body, i)
    assert s is not None, f"nothing decodes at ${N.SCRIPT_BASE + i:04X}"
    return s


#: What the variable a roll is compared with holds when the roll runs, from
#: the statements before it: `{variable: values}`.
COMPARED = {
    (53, 0x9313): {192: (5, 10)},
    (69, 0x9CE3): {193: (7, 13)},
    (70, 0x853F): {194: (1,)},
    (67, 0x8559): {163: tuple(range(255))},
}


def test_each_variable_roll_s_change_keeps_its_length_and_takes_the_exit(scripts):
    """Each row that is not a constant roll: changed, every value the compared
    variable can hold takes the `EXIT`; unchanged, some roll does not."""
    others = [r for r in ROWS if r.form != N.CONSTANT]
    assert {r.form for r in others} == set(N.FORMS) - {N.CONSTANT}
    for row in others:
        body = scripts[row.area]
        at = row.address - N.SCRIPT_BASE
        changed = bytearray(body)
        for r in ROWS:
            if r.area == row.area:
                for offset, value in r.changes:
                    changed[r.address - N.SCRIPT_BASE + offset] = value
        changed = bytes(changed)
        assert ts_decode(changed, at).end == ts_decode(body, at).end
        where = f"area {row.area} ${row.address:04X}"
        if row.form == N.CHASE_COUNTER:
            add = ts_decode(changed, at)
            assert add.op == 0x04 and add.operands[1] == add.operands[2], where
            counter = add.operands[2][1]
            chase = next(r for r in ROWS if r.area == row.area and r.form == N.CHASE)
            for start in range(255):
                env = {counter: start}
                _run(changed, chase.address - N.SCRIPT_BASE, env, 0)
                assert env[counter] == start, where
                env = {counter: start}
                _run(body, chase.address - N.SCRIPT_BASE, env, 0)
                assert env[counter] == start + 1, where
            continue
        saved = ts_decode(changed, at)
        assert saved.op == N.SAVE and saved.operands[0][0] in (0x00, 0x02), where
        compared = COMPARED.get((row.area, row.address), {0: (0,)})
        (variable, values), = compared.items()
        rolls = range(256) if row.form == N.VARIABLE_LIMIT else \
            range(ts_decode(body, at).operands[0][1] + 1)
        for value in values:
            assert _run(changed, at, {variable: value}, 0) == "exit", (where, value)
            assert any(_run(body, at, {variable: value}, r) != "exit"
                       for r in rolls), f"{where} never fights"


class Script:
    """One loaded script buffer, read and written by ECL address."""

    def __init__(self, body: bytes):
        self.memory = bytearray(body.ljust(0x2000, b"\0"))
        self.writes = []

    def read(self, address, n):
        at = address - N.SCRIPT_BASE
        return bytes(self.memory[at:at + n])

    def write(self, address, data):
        self.writes.append(address)
        at = address - N.SCRIPT_BASE
        self.memory[at:at + len(data)] = data

    def load(self, body: bytes):
        self.memory[:] = body.ljust(0x2000, b"\0")


def script_switch(buf: Script, area=lambda: 0, lines=None):
    return N.ScriptSwitch(N.DARKNESS, buf.read, buf.write, area,
                          (lines if lines is not None else []).append)


def test_on_changes_only_the_loaded_area_s_rolls_and_off_puts_the_script_back(scripts):
    for area, body in sorted(scripts.items()):
        buf = Script(body)
        before = bytes(buf.memory)
        sw = script_switch(buf, area=lambda area=area: area)
        sw.on()
        sw.apply()
        changed = sorted(N.SCRIPT_BASE + i for i in range(len(before))
                         if buf.memory[i] != before[i])
        want = sorted({r.address + o for r in ROWS if r.area == area
                       for o, v in r.changes if body[r.address - N.SCRIPT_BASE + o] != v})
        assert changed == want, area
        sw.apply()                       # held: nothing written again
        assert len(buf.writes) == len({r.address for r in ROWS if r.area == area})
        assert all(row["action"] == "restored" for row in sw.off())
        assert bytes(buf.memory) == before, area
        assert not sw.pending


# -- the switch on a made-up script ------------------------------------------

#: A step-entry roll as the scripts write one: `RANDOM 37, [195]`, `COMPARE
#: [195], 7`, `IF>`, `EXIT`.
ROLL = bytes.fromhex("08 00 25 01 c3 00 03 01 c3 00 00 07 19 00".replace(" ", ""))
HIGH = bytes.fromhex("08 00 25 01 c3 00 03 00 0d 01 c3 00 19 00".replace(" ", ""))
ADDRESS, OTHER = 0x8100, 0x8200


@pytest.fixture
def made_up(monkeypatch):
    rows = (N.ScriptGate(1, ADDRESS, N.digest(ROLL), N._TO_SAVE, N.PROBABLE, "test"),
            N.ScriptGate(2, OTHER, N.digest(HIGH), N._TO_ZERO, N.PROBABLE, "test"))
    monkeypatch.setitem(N.SCRIPT_GATES, N.DARKNESS, rows)


def script_with(at: int, span: bytes) -> bytes:
    body = bytearray(0x400)
    body[at - N.SCRIPT_BASE:at - N.SCRIPT_BASE + len(span)] = span
    return bytes(body)


@pytest.mark.usefixtures("made_up")
def test_a_roll_becomes_save_and_one_on_the_high_side_saves_zero():
    buf = Script(script_with(ADDRESS, ROLL))
    current = [1]
    sw = script_switch(buf, area=lambda: current[0])
    assert sw.apply() == [] and buf.writes == []      # off: nothing written
    sw.on()
    done = sw.apply()
    assert buf.read(ADDRESS, 3) == bytes([N.SAVE, 0, 0x25])
    assert done == [{"area": 1, "address": "$8100", "was": "080025", "wrote": "090025"}]
    buf.load(script_with(OTHER, HIGH))
    current[0] = 2
    sw.apply()
    assert buf.read(OTHER, 3) == bytes([N.SAVE, 0, 0])
    assert ADDRESS not in sw.held


@pytest.mark.usefixtures("made_up")
def test_a_reloaded_script_is_changed_again_and_another_area_is_left_alone():
    lines = []
    buf = Script(script_with(ADDRESS, ROLL))
    current = [1]
    sw = script_switch(buf, area=lambda: current[0], lines=lines)
    sw.on()
    sw.apply()
    buf.load(script_with(ADDRESS, ROLL))              # the game reloads the area
    sw.apply()
    assert buf.read(ADDRESS, 1)[0] == N.SAVE
    buf.load(bytes(0x400))                            # an area with no row
    current[0] = 7
    assert sw.apply() == [] and not sw.pending
    sw.apply()
    assert sw.unsuppressed_moves == 2
    assert lines == ["encounters are not suppressed in area 7: no known roll "
                     "is in its script"]


@pytest.mark.usefixtures("made_up")
def test_off_leaves_a_script_the_game_has_since_replaced():
    buf = Script(script_with(ADDRESS, ROLL))
    sw = script_switch(buf, area=lambda: 1)
    sw.on()
    sw.apply()
    buf.load(script_with(ADDRESS, ROLL))
    assert [r["action"] for r in sw.off()] == ["already original"]
    sw.on()
    sw.apply()
    buf.load(bytes(0x400))
    writes = len(buf.writes)
    assert [r["action"] for r in sw.off()] == ["another script is loaded"]
    assert len(buf.writes) == writes


#: A roll whose limit is a variable: `RANDOM [351], [195]`, `COMPARE [195],
#: 1`, `IF>=`, `EXIT`.
WORD_ROLL = bytes.fromhex("08 01 5f 01 01 c3 00 03 01 c3 00 00 01 1b 00".replace(" ", ""))


def test_a_variable_limit_becomes_an_immediate_word_and_off_puts_four_bytes_back(monkeypatch):
    row = N.ScriptGate(1, ADDRESS, N.digest(WORD_ROLL[:N.GUARD_BYTES]),
                       N._TO_SAVE_WORD, N.PROBABLE, "test", N.VARIABLE_LIMIT)
    monkeypatch.setitem(N.SCRIPT_GATES, N.DARKNESS, (row,))
    buf = Script(script_with(ADDRESS, WORD_ROLL))
    sw = script_switch(buf, area=lambda: 1)
    sw.on()
    assert sw.apply() == [{"area": 1, "address": "$8100", "was": "08015f01",
                           "wrote": "09026300"}]
    assert buf.read(ADDRESS, 7) == bytes.fromhex("09026300 01c300".replace(" ", ""))
    assert [r["action"] for r in sw.off()] == ["restored"]
    assert buf.read(ADDRESS, len(WORD_ROLL)) == WORD_ROLL


@pytest.mark.usefixtures("made_up")
def test_a_save_is_stopped_while_on_and_while_a_change_is_in_the_script():
    buf = Script(script_with(ADDRESS, ROLL))
    sw = script_switch(buf, area=lambda: 1)
    sw.check_save()
    sw.on()
    with pytest.raises(N.SaveBlocked):
        sw.check_save()
    sw.apply()
    sw.active = False
    with pytest.raises(N.SaveBlocked):
        sw.check_save()
    sw.off()
    sw.check_save()


@pytest.mark.usefixtures("made_up")
def test_a_byte_that_does_not_read_back_raises_and_is_put_back():
    buf = Script(script_with(ADDRESS, ROLL))

    def stuck(address, data):
        buf.writes.append((address, bytes(data)))

    sw = N.ScriptSwitch(N.DARKNESS, buf.read, stuck, lambda: 1, lambda line: None)
    sw.on()
    with pytest.raises(N.SwitchError, match=r"\$8100 read back 080025"):
        sw.apply()
    assert buf.writes[-1] == (ADDRESS, ROLL[:3]) and not sw.pending


@pytest.mark.usefixtures("made_up")
def test_a_script_with_a_row_s_bytes_in_another_area_is_not_changed():
    buf = Script(script_with(ADDRESS, ROLL))
    sw = script_switch(buf, area=lambda: 9)
    sw.on()
    assert sw.apply() == [] and buf.writes == []
    assert sw.unsuppressed_moves == 1


# -- the live script and variables, through a stub debugger -------------------

DS = 0x140C
SCRIPT, VARIABLES = 0x4B2A0, 0x4AEA0


class StubX:
    """`dosboxx.XSession`'s halt, registers, read and write over a megabyte;
    each halt shows the next `DS` of `halts`."""

    def __init__(self, memory, halts):
        self.memory, self.halts, self.ds, self.calls = memory, list(halts), None, []

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


def far(base: int) -> bytes:
    return (base & 0xF).to_bytes(2, "little") + (base >> 4).to_bytes(2, "little")


def variables(area=16) -> bytes:
    block = bytearray((i * 13) % 7 for i in range(1024))
    block[N.POD_CLOCK - 1:N.POD_CLOCK + 6] = bytes([1, 2, 3, 4, 5, 6, 7])
    block[N.DARKNESS_AREA_VAR - 1] = area
    return bytes(block)


def running(script: bytes, block: bytes) -> bytearray:
    memory = bytearray(0x100000)
    engine = N.SCRIPT_ENGINE[N.DARKNESS]
    for offset, base in ((engine.script, SCRIPT), (engine.variables, VARIABLES)):
        at = dosboxx.linear((DS, offset))
        memory[at:at + 4] = far(base)
    memory[SCRIPT:SCRIPT + len(script)] = script
    memory[VARIABLES:VARIABLES + len(block)] = block
    return memory


ENTRIES = bytes.fromhex("0102a1a20102b1b20102c1c20102d1d20102e1e2")


def test_the_script_and_area_come_through_the_two_far_pointers():
    body = ENTRIES + bytes(0x200)
    x = StubX(running(body, variables()), [0x0040, DS])
    live = N.LiveScript(x, N.DARKNESS, variables())
    with live:
        assert live.read(0x8004, 4) == ENTRIES[4:8]
        assert live.area() == 16
        live.write(0x8100, b"\x09")
    assert ("write", SCRIPT + 0x100, b"\x09") in x.calls
    assert x.calls.count("attach") == 2 and x.calls[-1] == "run"
    assert live.found["pointer"] == "4B2A:0000" and live.found["tries"] == 2


@pytest.mark.parametrize("script, block, why", [
    (bytes(0x200), variables(), "leads to"),
    (ENTRIES + bytes(0x200), bytes([99] * 1024), "clock digits"),
])
def test_a_block_that_is_not_the_game_s_is_not_believed(script, block, why):
    x = StubX(running(script, block), [DS] * N.DS_TRIES)
    with pytest.raises(N.SwitchError, match=why):
        with N.LiveScript(x, N.DARKNESS):
            pass
    assert x.calls[-1] == "run"


def test_a_variable_block_that_does_not_match_the_save_is_not_believed():
    x = StubX(running(ENTRIES + bytes(0x200), variables()), [DS] * N.DS_TRIES)
    with pytest.raises(N.SwitchError, match="match the save"):
        with N.LiveScript(x, N.DARKNESS, bytes(range(256)) * 4):
            pass


@pytest.mark.usefixtures("made_up")
def test_no_encounters_for_darkness_changes_the_script_before_a_move_and_reports_it():
    body = ENTRIES + script_with(ADDRESS, ROLL)[20:]
    x = StubX(running(body, variables(area=1)), [DS])
    enc = N.NoEncounters(x, N.DARKNESS, variables(area=1), log=lambda line: None)
    assert isinstance(enc.switch, N.ScriptSwitch)
    assert enc.before_move() == []                    # off: no halt
    assert x.calls == []
    enc.on()
    enc.before_move()
    assert x.memory[SCRIPT + ADDRESS - N.SCRIPT_BASE] == N.SAVE
    with pytest.raises(N.SaveBlocked):
        enc.check_save()
    report = enc.report()
    assert report["writes"] == [{"area": 1, "address": "$8100",
                                 "before": "080025", "after": "090025"}]
    assert report["areas"] == {"$01": 1}
    assert [r["action"] for r in enc.off()] == ["restored"]
    assert x.memory[SCRIPT + ADDRESS - N.SCRIPT_BASE] == N.RANDOM
    enc.check_save()


# -- the acceptance driver ----------------------------------------------------

def test_no_encounters_runs_for_darkness_with_its_title(monkeypatch, tmp_path):
    assert da.NO_ENCOUNTER_TITLES["darkness"] == N.DARKNESS
    ran = []
    monkeypatch.setattr(da, "run", lambda args: ran.append(args) or 0)
    assert da.main(["--title", "darkness", "--save", str(tmp_path), "--steps",
                    "load", "--no-encounters"]) == 0
    assert ran and ran[0].no_encounters and ran[0].title == "darkness"
