#!/usr/bin/env python3
"""Check `#207`'s five re-entry addresses against the shipped `DUNGEON`.

Fast Travel now hands control back to the game's own machine before it warps:
`automap.actions.reenter` rebuilds the stack from `saved_sp`, pushes
`main_loop_return`, and sets the program counter to `after_step` or to
`redraw` chained in front of `forward_key`. Five addresses in
`automap.fasttravel.POOL_OF_RADIANCE` are the whole of that, and every one of
them was measured in a running machine rather than read off a disk.

This is the reading half. It opens the player's own `DUNGEON`, **derives** two
of the five from the bytes and checks the shape of the other three, so a wrong
address fails here instead of in an emulator slot:

* `saved_sp` and the main loop's entry are read out of `NEWECL`'s own tail --
  `LDX <saved_sp> / TXS / JMP <main loop>`. The game's transition rebuilds the
  stack exactly the way the re-entry does, which is why the re-entry is legal
  at all, and it names the address while it does it.
* the main loop's entry must save the stack pointer back to that same
  address (`TSX / STX <saved_sp>`), so the tail restores what the entry saved.
* `main_loop_return` is the address the main loop's own patched `JSR` pushes,
  found by its `$FFFF` placeholder operand rather than by counting bytes.
* `after_step` must be `JSR <redraw> / JMP <entry 1>`, which ties two of the
  three committed addresses to each other, and `forward_key` must be a `JSR`.
* the wall test the edge-exit square choice rests on -- it zeroes the
  step counter and reads the square's own wall byte before counting anything,
  so a step into a wall is not a step off the map.

    tools/reentrypoints.py
    tools/reentrypoints.py --base 0x0800 --verbose

Nothing is written anywhere and no emulator is started. Exit status is 0 when
every check passes and 1 when any fails, so it can gate a change to those five
constants.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
from typing import NamedTuple

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap import fasttravel  # noqa: E402
from goldbox.d64 import D64, load_payload  # noqa: E402

#: Where `DUNGEON` runs, whatever its PRG header declares. The header on the
#: disks here says `$1000` and the code is linked for `$0800` (`#207`, and
#: `tools/newecl.py` says the same of every title).
DUNGEON_BASE = 0x0800


class Check(NamedTuple):
    """One claim about the bytes, and what they actually said."""

    name: str
    ok: bool
    detail: str

    def line(self) -> str:
        return f"[{'ok  ' if self.ok else 'FAIL'}] {self.name}: {self.detail}"


def word(body: bytes, base: int, addr: int) -> int:
    """The little-endian word at `addr`, with `body` loaded at `base`."""
    off = addr - base
    if off < 0 or off + 2 > len(body):
        raise IndexError(f"${addr:04X} is outside the image")
    return body[off] | (body[off + 1] << 8)


def at(body: bytes, base: int, addr: int, count: int) -> bytes:
    """`count` bytes at `addr`, with `body` loaded at `base`."""
    off = addr - base
    if off < 0 or off + count > len(body):
        raise IndexError(f"${addr:04X}+{count} is outside the image")
    return body[off:off + count]


def read_tail(body: bytes, base: int, tail: int) -> tuple[int, int]:
    """`(saved_sp, main_loop)` read out of `NEWECL`'s own tail.

    The tail is `JSR abs / INC abs / LDX abs / TXS / JMP abs`. The `LDX`
    operand is where the main loop parked its stack pointer and the `JMP`
    target is the main loop. Raises `ValueError` when the shape is not that,
    because a tail that does not rebuild the stack is a different routine and
    guessing at its operands would invent an address.
    """
    block = at(body, base, tail, 13)
    shape = (block[0] == 0x20 and block[3] == 0xEE and block[6] == 0xAE
             and block[9] == 0x9A and block[10] == 0x4C)
    if not shape:
        raise ValueError(f"${tail:04X} is not JSR/INC/LDX/TXS/JMP: "
                         f"{block.hex(' ')}")
    return word(body, base, tail + 7), word(body, base, tail + 11)


def find_patched_jsr(body: bytes, base: int, start: int,
                     limit: int = 0x100) -> int:
    """The address the main loop's self-modifying `JSR` pushes.

    `JSR` pushes the address of its own last byte, so what a re-entry has to
    push is `call + 2`. The call is found by its unpatched operand -- the
    linker leaves `$FFFF` there and the bar's choice writes over it -- rather
    than by counting bytes from the entry, so moving the loop about does not
    silently return the wrong address.
    """
    off = start - base
    window = body[off:off + limit]
    hit = window.find(b"\x20\xff\xff")
    if hit < 0:
        raise ValueError(f"no JSR $FFFF within ${limit:X} bytes of "
                         f"${start:04X}")
    return start + hit + 2


def checks(body: bytes, base: int,
           addr: fasttravel.FastTravelAddresses) -> list[Check]:
    """Every claim `#207`'s re-entry rests on, against these bytes."""
    out: list[Check] = []

    def add(name, ok, detail):
        out.append(Check(name, bool(ok), detail))

    try:
        saved_sp, main_loop = read_tail(body, base, addr.tail)
    except (ValueError, IndexError) as exc:
        add("NEWECL tail rebuilds the stack", False, str(exc))
        return out
    add("NEWECL tail rebuilds the stack", True,
        f"${addr.tail:04X} restores SP from ${saved_sp:04X} and jumps to "
        f"${main_loop:04X}")
    add("saved_sp", saved_sp == addr.saved_sp,
        f"derived ${saved_sp:04X}, committed "
        f"{'$%04X' % addr.saved_sp if addr.saved_sp is not None else 'None'}")

    try:
        entry = at(body, base, main_loop, 4)
    except IndexError as exc:
        add("the main loop saves the stack pointer", False, str(exc))
        entry = b""
    if entry:
        saves = entry[0] == 0xBA and entry[1] == 0x8E
        where = word(body, base, main_loop + 2) if saves else None
        add("the main loop saves the stack pointer",
            saves and where == saved_sp,
            f"${main_loop:04X} is TSX / STX ${where:04X}" if saves
            else f"${main_loop:04X} is not TSX / STX: {entry.hex(' ')}")

    try:
        pushed = find_patched_jsr(body, base, main_loop)
        add("main_loop_return", pushed == addr.main_loop_return,
            f"derived ${pushed:04X} from the JSR at ${pushed - 2:04X}, "
            "committed "
            f"{'$%04X' % addr.main_loop_return if addr.main_loop_return is not None else 'None'}")
    except (ValueError, IndexError) as exc:
        add("main_loop_return", False, str(exc))

    if addr.after_step is not None and addr.redraw is not None:
        try:
            block = at(body, base, addr.after_step, 6)
            shaped = block[0] == 0x20 and block[3] == 0x4C
            called = word(body, base, addr.after_step + 1) if shaped else None
            went = word(body, base, addr.after_step + 4) if shaped else None
            add("after_step calls redraw then entry 1",
                shaped and called == addr.redraw,
                f"${addr.after_step:04X} is JSR ${called:04X} / JMP "
                f"${went:04X}, redraw is ${addr.redraw:04X}" if shaped
                else f"${addr.after_step:04X} is not JSR/JMP: "
                     f"{block.hex(' ')}")
        except IndexError as exc:
            add("after_step calls redraw then entry 1", False, str(exc))

    if addr.forward_key is not None:
        try:
            block = at(body, base, addr.forward_key, 3)
            add("forward_key is a call", block[0] == 0x20,
                f"${addr.forward_key:04X} is JSR "
                f"${word(body, base, addr.forward_key + 1):04X}"
                if block[0] == 0x20 else
                f"${addr.forward_key:04X} is not a JSR: {block.hex(' ')}")
        except IndexError as exc:
            add("forward_key is a call", False, str(exc))

    if addr.key_wait:
        wall = addr.key_wait[-1]
        try:
            block = at(body, base, wall, 10)
            shaped = (block[0] == 0xA9 and block[1] == 0x00
                      and block[2] == 0x8D and block[5] == 0xAD
                      and block[8] == 0xF0)
            counter = word(body, base, wall + 3) if shaped else None
            square = word(body, base, wall + 6) if shaped else None
            add("the step counter is gated on the square's wall byte", shaped,
                f"${wall:04X} zeroes ${counter:04X} then branches on "
                f"${square:04X}" if shaped
                else f"${wall:04X} is not the wall test: {block.hex(' ')}")
        except IndexError as exc:
            add("the step counter is gated on the square's wall byte",
                False, str(exc))

    return out


def disks() -> pathlib.Path:
    """Where the player's Pool of Radiance disks are."""
    env = os.environ.get("POR_DISKS", "").strip()
    if env:
        return pathlib.Path(env)
    from automap.paths import find_disks
    where = find_disks()
    if where is None:
        raise SystemExit("no Pool of Radiance disks found; set POR_DISKS")
    return pathlib.Path(where)


def dungeon(where: pathlib.Path) -> bytes:
    """`DUNGEON`'s body off whichever side carries it, load address dropped."""
    for path in sorted(where.glob("POOL*.[dD]64")):
        try:
            image = D64.open(str(path))
        except Exception:
            continue
        for entry in image.iter_directory():
            if entry.name.decode("latin1").rstrip("\xa0 ") == "DUNGEON":
                return load_payload(image, b"DUNGEON")
    raise SystemExit(f"no POOL disk under {where} carries DUNGEON")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", type=lambda s: int(s, 0), default=DUNGEON_BASE,
                    help="where DUNGEON runs (default: $0800)")
    ap.add_argument("--disks", default="",
                    help="where the game disks are (default: $POR_DISKS, "
                         "then the player's own lookup)")
    ap.add_argument("--verbose", action="store_true",
                    help="print the bytes behind each check")
    args = ap.parse_args(argv)

    where = pathlib.Path(args.disks) if args.disks else disks()
    body = dungeon(where)
    addr = fasttravel.POOL_OF_RADIANCE
    print(f"DUNGEON: {len(body)} bytes at ${args.base:04X}-"
          f"${args.base + len(body) - 1:04X}, from {where}")
    results = checks(body, args.base, addr)
    for check in results:
        print(check.line())
    if args.verbose:
        for name, value in (("after_step", addr.after_step),
                            ("forward_key", addr.forward_key),
                            ("redraw", addr.redraw),
                            ("tail", addr.tail)):
            if value is not None:
                print(f"  ${value:04X} {name}: "
                      f"{at(body, args.base, value, 8).hex(' ')}")
    bad = [c for c in results if not c.ok]
    print(f"{len(results) - len(bad)} of {len(results)} checks pass")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
