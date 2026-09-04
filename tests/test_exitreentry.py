"""`tools/exitreentry.py`'s hand-built stack, against a fake monitor rather
than a live emulator.

The tool itself cannot be tested end to end here -- it needs a booted VICE
instance, a private display and a save on disk, and this repository's rule
is that nothing an agent runs may put a window on the maintainer's screen.
What can be tested is the one thing that would silently rebuild the wrong
stack if it were wrong: `reenter()`'s push order and its "address minus
one" convention, and `stack()`'s reading of the page back. The precedent is
`tests/test_dosoutdoorprobe.py`, whose docstring says it exactly -- "what can
be tested is everything that decides whether the run will mean anything."

Everything else in the module -- `party()`, `capture()`, the `phase_*`
functions, `wait_idle`, `answer_until_area` -- drives a live session and is
not tested here; a fake that stood in for that much of VICE would be testing
the fake rather than the tool.
"""
from __future__ import annotations

import contextlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tools import exitreentry as ER  # noqa: E402


class FakeMonitor:
    """`Session.mon()`'s binary-monitor interface, backed by a flat buffer.

    64KB of address space, so `0x0100+sp` (the stack page) and `$03BF` (the
    saved depth) are both just slices of the same array -- the same memory
    map `reenter`/`stack` themselves assume.
    """

    def __init__(self, saved_sp: int, sp: int, pc: int = 0):
        self.mem = bytearray(0x10000)
        self.mem[ER.SAVED_SP] = saved_sp
        self.sp = sp
        self.pc = pc

    def read(self, addr: int, length: int) -> bytes:
        return bytes(self.mem[addr:addr + length])

    def write(self, addr: int, data) -> None:
        data = bytes(data)
        self.mem[addr:addr + len(data)] = data

    def registers(self) -> dict[int, int]:
        return {ER.REG_PC: self.pc, ER.REG_SP: self.sp}

    def set_registers(self, regs: dict[int, int]) -> None:
        if ER.REG_PC in regs:
            self.pc = regs[ER.REG_PC]
        if ER.REG_SP in regs:
            self.sp = regs[ER.REG_SP]


class FakeSession:
    def __init__(self, monitor: FakeMonitor):
        self._m = monitor

    def mon(self, timeout: float = 5):
        return contextlib.nullcontext(self._m)


def make(saved_sp: int = 0xF0, sp: int | None = None) -> tuple[FakeSession, FakeMonitor]:
    m = FakeMonitor(saved_sp=saved_sp, sp=saved_sp if sp is None else sp)
    return FakeSession(m), m


# ---------------------------------------------------------------------------
# stack() -- reading the page, independent of reenter()
# ---------------------------------------------------------------------------

def test_stack_reads_the_saved_depth_from_03bf():
    _sess, m = make(saved_sp=0x42)
    assert ER.stack(m)["base_03BF"] == 0x42


def test_stack_reports_no_returns_with_an_empty_stack():
    """`sp == 0xFF` is nothing pushed -- the guard `stack()` uses so it does
    not read past the top of the page."""
    _sess, m = make(saved_sp=0xF0, sp=0xFF)
    result = ER.stack(m)
    assert result["raw"] == ""
    assert result["returns"] == []


def test_stack_pairs_low_byte_then_high_byte_reading_upward_from_sp_plus_one():
    """One hand-placed return address, not through `reenter()` at all: byte
    `sp+1` is the low half, `sp+2` the high half -- the 6502's own layout,
    which `stack()` has to read back the way `reenter()` writes it."""
    _sess, m = make(saved_sp=0xF0, sp=0xEE)
    m.write(0x100 + 0xEF, bytes([0x99]))          # low byte, at sp+1
    m.write(0x100 + 0xF0, bytes([0x12]))          # high byte, at sp+2
    result = ER.stack(m)
    assert result["returns"][0] == "$129A"        # 0x1299, plus 1 for RTS
    assert result["pc"] == m.pc


# ---------------------------------------------------------------------------
# reenter() -- the push itself: order, byte placement, and the depth it
# leaves the stack at
# ---------------------------------------------------------------------------

def test_reenter_pushes_the_main_loop_return_high_byte_then_low_byte():
    sess, m = make(saved_sp=0xF0)
    ER.reenter(sess, pc=0x1234, chain=())
    assert m.mem[0x100 + 0xF0] == ER.MAIN_LOOP_RETURN >> 8
    assert m.mem[0x100 + 0xEF] == ER.MAIN_LOOP_RETURN & 0xFF


def test_reenter_with_no_chain_leaves_the_stack_two_bytes_shallower():
    sess, m = make(saved_sp=0xF0)
    ER.reenter(sess, pc=0x1234, chain=())
    assert m.sp == 0xF0 - 2


def test_reenter_sets_the_pc_it_is_given():
    sess, m = make(saved_sp=0xF0)
    ER.reenter(sess, pc=0x9999, chain=())
    assert m.pc == 0x9999


def test_reenter_pushes_the_chain_after_the_main_loop_return_two_bytes_at_a_time():
    """Each of the three entries -- the main loop's own return, then the two
    chained ones -- gets its own two-byte slot, deeper to shallower in the
    order given."""
    sess, m = make(saved_sp=0xF0)
    ER.reenter(sess, pc=0x1234, chain=(0x0977, 0x0AAA))
    assert m.sp == 0xF0 - 6
    # depth 0: the main loop's own return
    assert m.mem[0x100 + 0xF0] == ER.MAIN_LOOP_RETURN >> 8
    assert m.mem[0x100 + 0xEF] == ER.MAIN_LOOP_RETURN & 0xFF
    # depth 1: chain[0]
    assert m.mem[0x100 + 0xEE] == 0x0977 >> 8
    assert m.mem[0x100 + 0xED] == 0x0977 & 0xFF
    # depth 2: chain[1]
    assert m.mem[0x100 + 0xEC] == 0x0AAA >> 8
    assert m.mem[0x100 + 0xEB] == 0x0AAA & 0xFF


def test_reenter_then_stack_recovers_the_chain_in_the_order_rts_will_pop_it():
    """RTS pops most-recently-pushed first, so the last chained address runs
    next -- `$0977` chains in front of `$0AAA` here, so `$0AAA` (the forward
    key) is what the first `RTS` reaches, exactly the way `phase_edge`
    chains `$0A4C` in front of `$0978` so the redraw runs before the key."""
    sess, m = make(saved_sp=0xF0)
    ER.reenter(sess, pc=0x1234, chain=(0x0977, 0x0AAA))
    frames = ER.stack(m)["returns"]
    assert frames[:3] == [f"${0x0AAA + 1:04X}", f"${0x0977 + 1:04X}",
                          f"${ER.MAIN_LOOP_RETURN + 1:04X}"]


def test_reenter_starts_from_the_saved_depth_not_the_live_sp():
    """The rebuild starts at `$03BF`'s recorded depth, whatever the live
    `SP` register happens to read at the moment -- that is the whole point
    of rebuilding from the saved value instead of trusting the register."""
    sess, m = make(saved_sp=0xD0, sp=0x40)
    ER.reenter(sess, pc=0x1234, chain=())
    assert m.mem[0x100 + 0xD0] == ER.MAIN_LOOP_RETURN >> 8
    assert m.sp == 0xD0 - 2


def test_reenter_reports_the_before_and_after_stacks():
    sess, m = make(saved_sp=0xF0)
    info = ER.reenter(sess, pc=0x1234, chain=(0x0977,))
    assert info["before"]["sp"] == 0xF0
    assert info["after"]["sp"] == 0xF0 - 4
