"""`tools/reentrypoints.py` -- the reading half of `#207`'s re-entry.

The five addresses `automap.actions.reenter` rests on were measured in a
running machine. This checks that the bytes on the player's own disks still
agree, which is the half that costs no emulator slot, so the pure-logic tests
here build tiny synthetic images by hand and one disk-backed test runs the
whole check against the shipped `DUNGEON`.

What is *not* tested here: `disks()` and `dungeon()`, which are a path lookup
and a directory walk, and `main()`'s printing.
"""

from __future__ import annotations

import dataclasses
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from automap import fasttravel  # noqa: E402
from tests.gamedata import disk_dir, needs_disks  # noqa: E402
from tools import reentrypoints as rp  # noqa: E402

BASE = 0x0800

#: The one row with re-entry addresses on it, and the subject of every test.
POR = fasttravel.POOL_OF_RADIANCE


def blank(size: int = 0x2400) -> bytearray:
    """An image of `size` zero bytes loaded at `BASE`."""
    return bytearray(size)


def put(image: bytearray, addr: int, data: bytes) -> None:
    image[addr - BASE:addr - BASE + len(data)] = data


def lohi(addr: int) -> bytes:
    return bytes((addr & 0xFF, addr >> 8))


def synthetic(addr=POR, main_loop: int = 0x0809,
              saved_sp: int | None = None,
              call: int | None = None,
              after_step_calls: int | None = None) -> bytes:
    """An image shaped like `DUNGEON`, with every checked site written.

    Each of the four keyword arguments is one place a wrong address can be
    planted, so a test can plant exactly one and watch exactly one check go
    red.
    """
    saved_sp = POR.saved_sp if saved_sp is None else saved_sp
    call = (POR.main_loop_return - 2) if call is None else call
    after_step_calls = (POR.redraw if after_step_calls is None
                        else after_step_calls)
    image = blank()
    # NEWECL's tail: JSR abs / INC abs / LDX saved_sp / TXS / JMP main_loop.
    put(image, addr.tail, b"\x20\x3c\x1a\xee\xdd\x6d\xae" + lohi(saved_sp)
        + b"\x9a\x4c" + lohi(main_loop))
    # The main loop's entry: TSX / STX saved_sp.
    put(image, main_loop, b"\xba\x8e" + lohi(saved_sp))
    # The self-modifying call, left unpatched by the linker.
    put(image, call, b"\x20\xff\xff")
    # after_step: JSR redraw / JMP entry 1.
    put(image, addr.after_step,
        b"\x20" + lohi(after_step_calls) + b"\x4c\xfc\x08")
    # forward_key: JSR.
    put(image, addr.forward_key, b"\x20\x8b\x09")
    # The wall test: LDA #0 / STA counter / LDA square / BEQ.
    put(image, addr.key_wait[-1],
        b"\xa9\x00\x8d\xd5\x6d\xad\x4e\xc0\xf0\x07")
    return bytes(image)


def result(checks, name: str) -> rp.Check:
    for check in checks:
        if check.name == name:
            return check
    raise AssertionError(f"no check called {name!r} in "
                         f"{[c.name for c in checks]}")


def test_word_and_at_read_through_the_base():
    image = blank()
    put(image, 0x0900, b"\x34\x12")
    assert rp.word(bytes(image), BASE, 0x0900) == 0x1234
    assert rp.at(bytes(image), BASE, 0x0900, 2) == b"\x34\x12"


def test_word_refuses_an_address_outside_the_image():
    with pytest.raises(IndexError):
        rp.word(b"\x00\x00", BASE, 0x9000)
    with pytest.raises(IndexError):
        rp.at(b"\x00\x00", BASE, BASE - 1, 1)


def test_read_tail_derives_both_addresses_from_the_bytes():
    body = synthetic()
    assert rp.read_tail(body, BASE, POR.tail) == (POR.saved_sp, 0x0809)


def test_read_tail_derives_whatever_the_bytes_say_rather_than_the_constant():
    body = synthetic(saved_sp=0x03C7, main_loop=0x0820)
    assert rp.read_tail(body, BASE, POR.tail) == (0x03C7, 0x0820)


def test_read_tail_refuses_a_block_that_is_not_the_tail():
    image = bytearray(synthetic())
    put(image, POR.tail, b"\x60" * 13)
    with pytest.raises(ValueError):
        rp.read_tail(bytes(image), BASE, POR.tail)


def test_find_patched_jsr_returns_the_address_the_call_pushes():
    body = synthetic(call=0x08A4)
    assert rp.find_patched_jsr(body, BASE, 0x0809) == 0x08A6


def test_find_patched_jsr_refuses_when_no_placeholder_is_in_range():
    body = synthetic(call=0x0A00)
    with pytest.raises(ValueError):
        rp.find_patched_jsr(body, BASE, 0x0809, limit=0x40)


def test_a_well_formed_image_passes_every_check():
    checks = rp.checks(synthetic(), BASE, POR)
    assert [c.name for c in checks if not c.ok] == []
    assert len(checks) == 7


def test_a_saved_sp_that_disagrees_with_the_bytes_fails():
    body = synthetic(saved_sp=0x03C7)
    checks = rp.checks(body, BASE, POR)
    assert not result(checks, "saved_sp").ok
    assert "$03C7" in result(checks, "saved_sp").detail
    # The other four still pass: one planted address, one failed check.
    assert [c.name for c in checks if not c.ok] == ["saved_sp"]


def test_a_main_loop_that_does_not_save_the_stack_pointer_fails():
    image = bytearray(synthetic())
    put(image, 0x0809, b"\xa9\x00\xa9\x00")
    checks = rp.checks(bytes(image), BASE, POR)
    assert not result(checks, "the main loop saves the stack pointer").ok


def test_a_main_loop_return_that_moved_fails():
    body = synthetic(call=0x08B0)
    checks = rp.checks(body, BASE, POR)
    check = result(checks, "main_loop_return")
    assert not check.ok
    assert "$08B2" in check.detail


def test_after_step_must_call_the_committed_redraw():
    body = synthetic(after_step_calls=0x0A50)
    checks = rp.checks(body, BASE, POR)
    check = result(checks, "after_step calls redraw then entry 1")
    assert not check.ok
    assert "$0A50" in check.detail


def test_a_row_with_no_reentry_addresses_is_not_checked_for_them():
    """Curse and Silver Blades carry None, and that is not a failure."""
    bare = dataclasses.replace(POR, after_step=None, forward_key=None,
                               redraw=None, main_loop_return=None)
    names = [c.name for c in rp.checks(synthetic(), BASE, bare)]
    assert "after_step calls redraw then entry 1" not in names
    assert "forward_key is a call" not in names
    # The tail is every title's, so those checks stay.
    assert "NEWECL tail rebuilds the stack" in names


def test_a_truncated_image_reports_rather_than_raises():
    checks = rp.checks(synthetic()[:0x100], BASE, POR)
    assert not checks[0].ok
    assert "outside the image" in checks[0].detail


@needs_disks
def test_the_shipped_dungeon_still_agrees_with_all_five_addresses():
    body = rp.dungeon(pathlib.Path(disk_dir()))
    checks = rp.checks(body, rp.DUNGEON_BASE, POR)
    assert [c.line() for c in checks if not c.ok] == []
    assert len(checks) == 7


@needs_disks
def test_the_shipped_dungeon_derives_the_two_addresses_it_can():
    """`saved_sp` and `main_loop_return` come out of the bytes, not the row.

    This is what makes the check evidence rather than a paste comparison: the
    tail names `$03BF` itself, and the main loop's own unpatched `JSR` names
    the address a re-entry has to push.
    """
    body = rp.dungeon(pathlib.Path(disk_dir()))
    saved_sp, main_loop = rp.read_tail(body, rp.DUNGEON_BASE, POR.tail)
    assert saved_sp == POR.saved_sp
    pushed = rp.find_patched_jsr(body, rp.DUNGEON_BASE, main_loop)
    assert pushed == POR.main_loop_return
