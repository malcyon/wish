#!/usr/bin/env python3
"""Every reference to $6DE0-$6DEF in Pool of Radiance's thirty area scripts, walked and raw-scanned, for `#445 (The game's third fight outcome, THE PARTY RUNS AWAY, has never been seen on a screen)`.

    .venv/bin/python tools/areas/ecl6derefs.py

Four passes over the C64 scripts `tools/areas/eclcensus.py` loads, so the control-flow
walk's 2% blind spot cannot hide a write: (1) every walked statement with an
operand in $6DE0-$6DEF, marked WRITE or read; (2) a raw byte scan for the
little-endian address bytes, marking each hit as inside a walked statement or
NOT WALKED; (3) every SAVETABLE (opcode $35) base, flagging any within 255 of
$6DE6; (4) every SAVETABLE statement with its 16-bit index, since an indexed
store could reach $6DE6 from a base further away.

The disks come from `tools/registry/gamedisks.py`'s Pool of Radiance entry, else
`automap.paths.find_disks()`.  Reads them and writes nothing.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from automap.paths import find_disks  # noqa: E402
from goldbox import c64_port  # noqa: E402
from tools.areas import eclcensus as E  # noqa: E402

LO, HI = 0x6DE0, 0x6DEF


def main(argv=None) -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    game = next(g for g in c64_port.GAMES if g.key == "pool-of-radiance")
    root = E.registry(game.key) or str(find_disks())
    machine, base, bodies, sides, _dos = E.load_port(root, game, None)
    print(f"scripts run at ${base:04X}; {len(bodies)} bodies, "
          f"DUNGEON ${machine.base:04X}")

    # --- pass 1: the control-flow walk --------------------------------------
    print(f"\n-- walked statements naming ${LO:04X}-${HI:04X} --")
    covered = {}          # name -> set of byte offsets inside a reached statement
    walked_rows = []
    for name in sorted(bodies):
        body = bodies[name]
        found = E.walk(machine, body, base)
        covered[name] = {i for s in found.values() for i in range(s.at, s.end)}
        for at in sorted(found):
            st = found[at]
            writes = E.DESTINATIONS.get(st.op, ())
            for n, (kind, value) in enumerate(st.operands):
                if kind in (0x00, 0x80) or not LO <= value <= HI:
                    continue
                imm = [v for k, v in st.operands if k == 0x00]
                walked_rows.append((name, at, base + at, st.op, n, value,
                                    n in writes, imm))
    for name, at, addr, op, n, value, write, imm in walked_rows:
        kind = "WRITE" if write else "read "
        print(f"  {name}+${at:04X} (${addr:04X})  {kind} ${value:04X}  "
              f"op ${op:02X} {E.OPCODE_NAMES.get(op, '?')} operand {n}  "
              f"immediates {imm}")
    print(f"  {len(walked_rows)} statement/operand pairs")

    # --- pass 2: the raw byte scan ------------------------------------------
    print(f"\n-- raw byte scan for the little-endian bytes of "
          f"${LO:04X}-${HI:04X} --")
    for addr in range(LO, HI + 1):
        pat = bytes((addr & 0xFF, addr >> 8))
        for name in sorted(bodies):
            body = bodies[name]
            i = body.find(pat)
            while i >= 0:
                inside = i in covered[name] or (i - 1) in covered[name]
                print(f"  ${addr:04X}  {name}+${i:04X}  "
                      f"{'in a walked statement' if inside else 'NOT WALKED'}  "
                      f"context {body[max(0, i - 6):i + 4].hex(' ')}")
                i = body.find(pat, i + 1)

    # --- pass 3: could an indexed store (SAVETABLE, op $35) reach $6DE6? ----
    print("\n-- every SAVETABLE base in the thirty scripts --")
    bases = {}
    for name in sorted(bodies):
        body = bodies[name]
        for at, st in sorted(E.walk(machine, body, base).items()):
            if st.op != 0x35:
                continue
            kind, value = st.operands[1]
            if kind in (0x00, 0x80):
                continue
            bases.setdefault(value, []).append(f"{name}+${at:04X}")
    for value in sorted(bases):
        near = ("  <-- within 255 of $6DE6"
                if 0x6DE6 - 255 <= value <= 0x6DE6 else "")
        print(f"  base ${value:04X}  {len(bases[value])} site(s)  "
              f"{bases[value][:3]}{near}")

    # --- pass 4: the SAVETABLE sites in full, since its index is 16-bit -----
    print("\n-- every SAVETABLE statement, with the index it uses --")
    KIND = {0x00: "imm8", 0x01: "byte var", 0x02: "imm16", 0x03: "word var"}
    for name in sorted(bodies):
        body = bodies[name]
        for at, st in sorted(E.walk(machine, body, base).items()):
            if st.op != 0x35:
                continue

            def show(n, st=st):
                k, v = st.operands[n]
                return (f"#{v}" if k == 0x00 else
                        f"#{v}(w)" if k == 0x02 else
                        f"[${v:04X}]{'' if k == 0x01 else '(w)'}")
            bk, bv = st.operands[1]
            reach = bv if bk not in (0x00, 0x80) else None
            need = (0x6DE6 - reach) if reach is not None else None
            print(f"  {name}+${at:04X} (${base + at:04X})  SAVETABLE {show(0)}, "
                  f"={show(1)}, {show(2)}   index kinds "
                  f"{KIND.get(st.operands[2][0])}; index needed for $6DE6: {need}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
