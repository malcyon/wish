#!/usr/bin/env python3
"""Where each C64 Gold Box title's COMBAT overlay keeps the message panel.

`tools/latercombat.py` holds the addresses the combat **view** needs -- the
mode byte, the map, the position table, the roster, the initiative bytes. The
combat **log** needs a different four, and this is what re-derives them from a
title's own files rather than carrying Pool of Radiance's across:

* the message printer, found by its `LDA #$0A / STA <window top>` skeleton,
  which also names the window-top and cursor-row addresses it writes;
* the four-byte text window the printer installs, found by the thunk shape
  `STA $07 / STY $08 / JMP <print> / LDA #lo / LDX #hi / JMP <copy>` -- the
  operand names the block and the four bytes after the thunk are it;
* the message delay byte, found by the `LDA <delay> / BEQ <RTS>` gate whose
  body is nothing but calls;
* the d20 store and the twelve-byte attack block, found by Pool of Radiance's
  `CMP #$01 / BEQ / CMP #$14 / BCC / LDA #$64 / STA <d20>` and the
  `CMP <needed> / BCC / INC <hit flag> / SEC / RTS` that ends the same
  routine.

    tools/combatsigs.py
    tools/combatsigs.py --title curse-of-the-azure-bonds

Every address printed is a run-time address with `LINKER`'s `$0800` as the
base, because that is where it puts an overlay it dispatches to whatever the
PRG header claims. The thunk search reads every file on a title's disks, since
in Curse and Silver Blades neither the text-window helpers **nor the attack
roll** are in `COMBAT` at all -- both are in `ECL64`, resident at `$8000`. A
search of the `COMBAT` overlays alone reports the later titles as having no
such routine, which is wrong, and is the mistake this tool exists to stop
somebody repeating.

Nothing here writes, and nothing it prints is committed: the game's bytes stay
on the player's own disks. `#39 (Combat view and combat log for Curse and
Silver Blades)` has what the numbers meant.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS.parent))

from goldbox import games  # noqa: E402
from goldbox.d64 import D64, split_load_address  # noqa: E402
from tools import gamedisks  # noqa: E402

#: `LINKER` loads every overlay it dispatches at `$0800`, whatever the header
#: says. `#334` re-confirmed it for the later titles' `COMBAT`: its internal
#: `JSR`s land on instruction boundaries only at this base.
BASE = 0x0800

TITLES = ("pool-of-radiance", "curse-of-the-azure-bonds",
          "secret-of-the-silver-blades")

#: `STX <which message> / JSR <set window> / LDA #$0A / STA <window top> /
#: JSR / JSR / JSR` -- Pool of Radiance `COMBAT $2983`, and one hit each in
#: Curse and Silver Blades.
PRINTER = (0x8E, None, None, 0x20, None, None, 0xA9, 0x0A, 0x8D, None, None,
           0x20, None, None, 0x20, None, None, 0x20, None, None)

#: `STA $07 / STY $08 / JMP <print> / LDA #lo / LDX #hi / JMP <four-byte copy>`
#: -- Pool of Radiance `COMBAT $0962`. The `LDA`/`LDX` operands name the block.
THUNK = (0x85, 0x07, 0x84, 0x08, 0x4C, None, None,
         0xA9, None, 0xA2, None, 0x4C, None, None)

#: `CMP #$01 / BEQ / CMP #$14 / BCC / LDA #$64 / STA <d20>` -- the natural 1
#: that is never stored, and the 20 that is stored as 100. Pool of Radiance
#: `COMBAT $127F`; `ECL64 $84ED` in Curse and `$84FC` in Silver Blades.
D20 = (0xC9, 0x01, 0xF0, None, 0xC9, 0x14, 0x90, 0x02, 0xA9, 0x64,
       0x8D, None, None)

#: `CMP <needed> / BCC / INC <hit flag>` -- the tail of the same routine. The
#: two operands are the block's first and last byte, eleven apart, which is
#: what says how long the block is without assuming it.
#:
#: **The `SEC` is not part of the pattern, and leaving it in cost a reading.**
#: Pool of Radiance and Curse end `INC / SEC / RTS`; Silver Blades ends
#: `INC / RTS`, one byte shorter, and a pattern demanding `38 60` reports that
#: title as not having the routine at all. The caller checks the next byte is
#: one of the two instead.
ATTACK_TAIL = (0xCD, None, None, 0x90, None, 0xEE, None, None)


def disks(key: str) -> list[pathlib.Path]:
    root = gamedisks.find(key)
    if root is None:
        return []
    return sorted(p for p in pathlib.Path(root).iterdir()
                  if p.suffix.lower() == ".d64")


def files(key: str):
    """Every named file on that title's sides, once each, first side wins."""
    seen: set[str] = set()
    for path in disks(key):
        try:
            image = D64.open(str(path))
        except Exception:
            continue
        for entry in image.iter_directory():
            name = entry.name.decode("latin1").rstrip("\xa0 ")
            if name in seen:
                continue
            seen.add(name)
            try:
                _declared, body = split_load_address(image.read_file(name))
            except Exception:
                continue
            yield name, body


def find(body: bytes, pattern, base: int = BASE) -> list[int]:
    """Run-time addresses where `pattern` matches; None is a wildcard byte."""
    out, n = [], len(pattern)
    for i in range(len(body) - n + 1):
        if all(p is None or body[i + j] == p for j, p in enumerate(pattern)):
            out.append(base + i)
    return out


def word(body: bytes, at: int, base: int = BASE) -> int:
    i = at - base
    return body[i] | (body[i + 1] << 8)


def delay_gate(body: bytes, base: int = BASE) -> list[tuple[int, int]]:
    """Every `LDA abs / BEQ <RTS>` whose gate opens with a call.

    That is the shape of the message delay in all three titles -- Pool of
    Radiance jumps straight into `LIBRARY`'s busy loop at `COMBAT $28C3`, and
    the later two make three calls -- but the shape alone is **not** unique
    inside a 9K overlay, so every hit is printed and the caller says which one
    reads the save payload. Do not read a single hit as the answer.
    """
    out = []
    for i in range(len(body) - 6):
        if body[i] != 0xAD or body[i + 3] != 0xF0:
            continue
        target = i + 5 + body[i + 4]
        if target >= len(body) or body[target] != 0x60:
            continue
        if body[i + 5] not in (0x20, 0x4C):
            continue
        out.append((base + i, body[i + 1] | (body[i + 2] << 8)))
    return out


def each_file_at(key: str):
    """Every file, with the base its own `JSR`/`JMP` targets argue for.

    An overlay `LINKER` dispatches runs at `$0800`; `ECL64` does not, and its
    base is scored the way `docs/`'s overlay note says -- the base at which
    most of the file's own absolute call targets land inside it.
    """
    for name, body in files(key):
        if len(body) < 0x200:
            continue
        best = max(((self_refs(body, base), base)
                    for base in range(0x0800, 0xE000, 0x100)))
        yield name, body, best[1], best[0]


def self_refs(body: bytes, base: int) -> int:
    return sum(1 for i in range(len(body) - 2)
               if body[i] in (0x20, 0x4C)
               and base <= (body[i + 1] | (body[i + 2] << 8)) < base + len(body))


def report(key: str) -> None:
    game = next((g for g in games.GAMES if g.key == key), None)
    print(f"== {getattr(game, 'title', key)}")
    combat = None
    for name, body in files(key):
        if name == "COMBAT":
            combat = body
    if combat is None:
        print("   no COMBAT on any side -- are that title's disks here?")
        return

    for at in find(combat, PRINTER):
        print(f"   message printer   ${at:04X}   window top ${word(combat, at + 9):04X}"
              f"   (the LDA #$0A it stores is MESSAGE_TOP)")
    payload = getattr(game, "save_load_address", None)
    for at, addr in delay_gate(combat):
        mark = ("   <-- the save payload's byte $FC"
                if payload is not None and addr == payload + 0xFC else "")
        print(f"   message delay?    ${at:04X}   reads ${addr:04X}{mark}")
    for name, body in files(key):
        for at in find(body, THUNK, BASE if name == "COMBAT" else 0):
            i = at if name == "COMBAT" else at
            j = (i - BASE) if name == "COMBAT" else i
            block = body[j + 8] | (body[j + 10] << 8)
            four = tuple(body[j + 14:j + 18])
            print(f"   text window       in {name}, block ${block:04X}"
                  f"   bytes {four}  -> columns {four[0]}-{four[1] - 1}, "
                  f"rows {four[2]}-{four[3] - 1}")
    for name, body, base, hits in each_file_at(key):
        for at in find(body, D20, base):
            i = at - base
            print(f"   d20 store         in {name} (base ${base:04X}, {hits} "
                  f"self refs) ${at:04X}   stores ${body[i + 12]:02X}"
                  f"{body[i + 11]:02X}")
        for at in find(body, ATTACK_TAIL, base):
            i = at - base
            if i + 8 >= len(body) or body[i + 8] not in (0x38, 0x60):
                continue
            lo = body[i + 1] | (body[i + 2] << 8)
            hi = body[i + 6] | (body[i + 7] << 8)
            if not 0 < hi - lo < 0x40:
                continue
            print(f"   attack block      in {name} ${at:04X}   ${lo:04X}"
                  f"..${hi:04X}   {hi - lo + 1} bytes")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--title", action="append", choices=TITLES,
                    help="only this title (repeatable); default is all three")
    args = ap.parse_args(argv)
    for key in args.title or TITLES:
        report(key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
