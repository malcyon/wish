#!/usr/bin/env python3
"""Count the absolute-mode 6502 operands that land in a window of the C64
character record, per file, across one title's disks -- a measurement for `#192
(Convert a Curse of the Azure Bonds DOS save into a C64 one, which the importer
refuses today)`.

    .venv/bin/python tools/c64/c64recordoperandsweep.py curse 0x100 0x140

GAME is `curse`, `pool` or `ssb`; LO and HI are hex offsets into the record
(the record's C64 address is `$7C00` for `curse` and `ssb`, `$6B00` for
`pool`). Reads every `.d64` in the title's registered disk directory, scans
every file's bytes for an absolute, absolute,X or absolute,Y opcode whose
operand falls in `record+LO .. record+HI`, and prints one line per offset with
the number of hits and which files hold them. It is a byte scan and does not
follow the code, so an operand-looking byte pair in data counts too. Reads
only.
"""
from __future__ import annotations

import argparse
import collections
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from goldbox.d64 import D64  # noqa: E402
from tools.registry import gamedisks  # noqa: E402

RECORDS = {'curse': 0x7C00, 'pool': 0x6B00, 'ssb': 0x7C00}
KEYS = {'curse': 'curse-of-the-azure-bonds', 'pool': 'pool-of-radiance',
        'ssb': 'secret-of-the-silver-blades'}

# opcodes with an absolute / absolute,X / absolute,Y operand
ABS = {0x0D: 'ORA', 0x0E: 'ASL', 0x2C: 'BIT', 0x2D: 'AND', 0x2E: 'ROL',
       0x4D: 'EOR', 0x4E: 'LSR', 0x6D: 'ADC', 0x6E: 'ROR',
       0x8C: 'STY', 0x8D: 'STA', 0x8E: 'STX', 0xAC: 'LDY', 0xAD: 'LDA',
       0xAE: 'LDX', 0xCC: 'CPY', 0xCD: 'CMP', 0xCE: 'DEC',
       0xEC: 'CPX', 0xED: 'SBC', 0xEE: 'INC', 0x1D: 'ORA,X', 0x1E: 'ASL,X',
       0x3D: 'AND,X', 0x3E: 'ROL,X', 0x5D: 'EOR,X',
       0x5E: 'LSR,X', 0x7D: 'ADC,X', 0x7E: 'ROR,X', 0x9D: 'STA,X',
       0xBC: 'LDY,X', 0xBD: 'LDA,X', 0xDD: 'CMP,X', 0xDE: 'DEC,X',
       0xFD: 'SBC,X', 0xFE: 'INC,X', 0x19: 'ORA,Y', 0x39: 'AND,Y',
       0x59: 'EOR,Y', 0x79: 'ADC,Y', 0x99: 'STA,Y', 0xB9: 'LDA,Y',
       0xBE: 'LDX,Y', 0xD9: 'CMP,Y', 0xF9: 'SBC,Y'}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("game", choices=sorted(RECORDS))
    ap.add_argument("lo", help="window start, a hex offset into the record")
    ap.add_argument("hi", help="window end, a hex offset into the record")
    args = ap.parse_args(argv)
    LO, HI = int(args.lo, 16), int(args.hi, 16)
    RECORD = RECORDS[args.game]
    found = gamedisks.find(KEYS[args.game])
    if found is None:
        raise SystemExit(f"no disks for {KEYS[args.game]}: set its variable "
                         f"or add it to gamedisks.yaml")
    root = str(found)
    hits = collections.defaultdict(list)
    files = 0
    for path in sorted(os.listdir(root)):
        if not path.lower().endswith('.d64'):
            continue
        img = D64.open(os.path.join(root, path))
        for e in img.iter_directory():
            name = e.name.decode('latin1').rstrip('\xa0 ')
            try:
                body = img.read_file(name)[2:]
            except Exception:
                continue
            files += 1
            for i in range(len(body) - 2):
                op = body[i]
                if op not in ABS:
                    continue
                a = body[i + 1] | (body[i + 2] << 8)
                if RECORD + LO <= a <= RECORD + HI:
                    hits[a - RECORD].append((path, name, 0x0800 + i, ABS[op]))
    print(f'{files} files scanned, record ${RECORD:04X}, window '
          f'0x{LO:03X}-0x{HI:03X}')
    for off in sorted(hits):
        rows = hits[off]
        where = collections.Counter(r[1] for r in rows)
        print(f'  0x{off:03X}  {len(rows):>3} refs  '
              + ', '.join(f'{k}x{v}' for k, v in where.most_common(8)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
