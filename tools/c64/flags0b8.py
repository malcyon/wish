#!/usr/bin/env python3
"""Every instruction in the six C64 titles that touches record byte `0x0B8`, sorted by what it does.

Record byte `0x0B8` is the control byte: bit 7 set means the engine drives
the character, and for such a character the low seven bits are a morale
stored halved (`docs/195-three-dos-record-bytes-named-from-the-overlays.md`).
For a Pool of Radiance player character bit 0 is the trainer's
ability-altered flag. This asks each title's own code which of those
meanings it has, by classifying every absolute-mode reference to the byte
into the idioms the engines use:

    tools/c64/flags0b8.py                  # all six titles, summary
    tools/c64/flags0b8.py --sites          # and every site, classified
    tools/c64/flags0b8.py --title curse-of-the-azure-bonds --sites

The classes are byte patterns around the hit, not a trace, so a hit in a
graphics file decodes as an instruction like any other; those land in
`read, other` and are printed so they can be looked at rather than counted.
A write that fits no known idiom is `write, unclassified`, and
`tests/records/test_flags0b8.py` fails if one appears. An index computed at
run time leaves no trace here -- `tools/c64/recordsweep.py --indirect` is the
check for the `(pointer),Y` route, and found none for this byte.

`docs/232-the-c64-control-byte-per-title.md` is the write-up. Reads only.
"""

from __future__ import annotations

import argparse
import collections
import functools
import hashlib
import pathlib
import sys
from dataclasses import dataclass

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from automap import gamedisks  # noqa: E402
from goldbox.d64 import D64, split_load_address  # noqa: E402
from tools.c64.d6502 import M_ABS, T  # noqa: E402

#: Where each title keeps the resident character record. Pool of Radiance's
#: is `goldbox.layout.LOAD_ADDRESS`; the other five have hits at `$7CB8` and
#: none at `$6BB8`, measured with this scan.
RECORD = {
    "pool-of-radiance": 0x6B00,
    "curse-of-the-azure-bonds": 0x7C00,
    "secret-of-the-silver-blades": 0x7C00,
    "gateway-to-the-savage-frontier": 0x7C00,
    "champions-of-krynn": 0x7C00,
    "death-knights-of-krynn": 0x7C00,
}

OFFSET = 0x0B8
ABILITIES = 0x014            # the first ability array, `goldbox/layout.py`

READ_OPS = {"LDA", "LDX", "LDY", "ORA", "AND", "EOR", "ADC", "SBC", "CMP",
            "CPX", "CPY", "BIT"}
WRITE_OPS = {"STA", "STX", "STY", "INC", "DEC", "ASL", "LSR", "ROL", "ROR"}

BPL, BMI = 0x10, 0x30


@dataclass(frozen=True)
class Site:
    file: str
    offset: int              # payload offset of the instruction
    mnemonic: str
    kind: str


@functools.lru_cache(maxsize=None)
def files(key: str) -> tuple[tuple[str, bytes], ...]:
    """Every distinct PRG payload on a title's disks, as `(name, payload)`.

    Distinct by content: the same overlay on two sides is one file.
    """
    where = gamedisks.find(key)
    if where is None:
        return ()
    globs = gamedisks.entry(key).get("glob") or ["*.d64", "*.D64"]
    if isinstance(globs, str):
        globs = [globs]
    seen: dict[str, tuple[str, bytes]] = {}
    paths = sorted({p for g in globs for p in pathlib.Path(where).glob(g)})
    for path in paths:
        try:
            disk = D64.open(str(path))
        except Exception:
            continue                     # not every image in a set is readable
        for entry in disk.directory():
            if not entry.is_prg:
                continue
            try:
                payload = split_load_address(disk.read_file(entry))[1]
            except Exception:
                continue                 # a broken chain is not a candidate
            digest = hashlib.sha1(payload).hexdigest()
            name = entry.name.decode("latin-1").rstrip()
            seen.setdefault(digest, (name, payload))
    return tuple(sorted(seen.values(), key=lambda f: (f[0], len(f[1]))))


def _word(data: bytes, i: int) -> int:
    return data[i] | data[i + 1] << 8


def _before(data: bytes, i: int, pattern: bytes) -> bool:
    return i >= len(pattern) and data[i - len(pattern):i] == pattern


def classify(data: bytes, i: int, mnemonic: str, target: int) -> str:
    """What the instruction at `data[i]`, which addresses `target`, is doing."""
    lo, hi = target & 0xFF, target >> 8
    after = data[i + 3:i + 16]
    if mnemonic in WRITE_OPS:
        if _before(data, i, bytes([0xA9, 0x01])):
            return "write, $01 (the trainer flag, whole byte)"
        if _before(data, i, bytes([0xA9, 0x80, 0x0D, lo, hi])):
            return "write, bit 7 set, low bits kept (joins the party)"
        if _before(data, i, bytes([0x4A, 0x09, 0x80])):
            return "write, script argument halved | $80 (joins with a morale)"
        if (_before(data, i, bytes([0x09, 0x80])) and i >= 5
                and data[i - 5] == 0x4E):
            return "write, script argument | $80, not halved (joins with a morale)"
        if _before(data, i, bytes([0x8A, 0x09, 0xFE])):
            return "write, $B2 for a companion, old | $FE for a player (berserk)"
        if (_before(data, i, bytes([0xC9, 0xFE, 0x90, 0x05, 0x29, 0x01]))):
            return "write, & $01 when at or above $FE (berserk ends)"
        if (_before(data, i, bytes([0xAE, lo, hi, 0x30, 0x03]))
                and i >= 19 and data[i - 19:i - 17] == bytes([0xA9, 0x00])):
            return "write, $00 for a player character only (import reset)"
        if i >= 3 and data[i - 3] == 0xAD and _word(data, i - 2) != target:
            return "write, restores a saved copy"
        return "write, unclassified"
    if mnemonic == "ORA" and _before(data, i, bytes([0xA9, 0x80])):
        return "read, OR'd with $80 (joins the party)"
    if len(after) >= 1 and after[0] in (BPL, BMI):
        if after[2:5] == bytes([0x29, 0x7F, 0x0A]):
            if after[5:11] == bytes([0xC9, 0x64, 0x90, 0x02, 0xA9, 0x64]):
                return "read, morale: & $7F, doubled, clamped at 100"
            return "read, morale: & $7F, doubled, no clamp"
        return "read, bit 7 test"
    if after[:2] == bytes([0xC9, 0xFE]):
        return "read, compared with $FE (berserk ends)"
    if mnemonic == "LDA" and after[:1] == b"\x8D" and _word(after, 1) != target:
        return "read, saved to a copy"
    return "read, other"


@functools.lru_cache(maxsize=None)
def sites(key: str) -> tuple[Site, ...]:
    """Every absolute-mode reference to record byte `0x0B8`, classified."""
    target = RECORD[key] + OFFSET
    out = []
    for name, data in files(key):
        for i in range(len(data) - 2):
            op = data[i]
            if op not in T:
                continue
            mnemonic, mode = T[op]
            if mode != M_ABS or _word(data, i + 1) != target:
                continue                 # an indexed hit is somebody else's field
            out.append(Site(name, i, mnemonic, classify(data, i, mnemonic, target)))
    return tuple(out)


def trainer_steps(key: str) -> list[tuple[str, int, str]]:
    """Every `INC`/`DEC` of the first ability array, `abs,X`: the PoR trainer's step."""
    base = RECORD[key] + ABILITIES
    want = {bytes([0xFE, base & 0xFF, base >> 8]): "INC",
            bytes([0xDE, base & 0xFF, base >> 8]): "DEC"}
    out = []
    for name, data in files(key):
        for pattern, mnemonic in want.items():
            i = data.find(pattern)
            while i >= 0:
                out.append((name, i, mnemonic))
                i = data.find(pattern, i + 1)
    return out


def refuses_npcs(key: str) -> list[str]:
    """The files carrying the ADD CHARACTER refusal text `CAN'T ADD NPCS`."""
    return sorted({name for name, data in files(key) if b"CAN'T ADD NPCS" in data})


def monster_bytes(key: str) -> collections.Counter:
    """Byte `0x0B8` over the title's `MON*` monster records."""
    return collections.Counter(
        data[OFFSET] for name, data in files(key)
        if name.startswith("MON") and len(data) > OFFSET)


def morale(value: int) -> int | None:
    """The decoded morale of a control byte, or None for a player character."""
    return (value & 0x7F) * 2 if value & 0x80 else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--title", action="append", choices=sorted(RECORD),
                    help="one title; repeatable; default all six")
    ap.add_argument("--sites", action="store_true", help="print every site")
    args = ap.parse_args(argv)
    for key in args.title or list(RECORD):
        if not files(key):
            print(f"{key}: no disks here\n")
            continue
        found = sites(key)
        print(f"{key}: record at ${RECORD[key]:04X}, "
              f"{len(found)} reference(s) to ${RECORD[key] + OFFSET:04X} "
              f"in {len(files(key))} distinct files")
        for kind, n in sorted(collections.Counter(s.kind for s in found).items()):
            print(f"  {n:3d}  {kind}")
        steps = trainer_steps(key)
        print(f"  INC/DEC of ${RECORD[key] + ABILITIES:04X},X (the PoR trainer's step): "
              + (", ".join(f"{n} +0x{i:04X} {m}" for n, i, m in steps) or "none"))
        print("  CAN'T ADD NPCS in: " + (", ".join(refuses_npcs(key)) or "no file"))
        mon = monster_bytes(key)
        print(f"  MON* byte 0x0B8 ({sum(mon.values())} files): "
              + ", ".join(f"${v:02X} x{n} (morale {morale(v)})"
                          for v, n in sorted(mon.items())))
        if args.sites:
            for s in found:
                print(f"    {s.file:18s} +0x{s.offset:04X}  {s.mnemonic}  {s.kind}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
