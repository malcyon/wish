#!/usr/bin/env python3
"""Which of a C64 title's files name an address in a window, and where.

`tools/recordsweep.py` asks this of the character record and takes its window
as a record offset; this asks it of **any** address window, which is what a
saved-game header wants. `#192 (Convert a Curse of the Azure Bonds DOS save
into a C64 one, which the importer refuses today)` step 0e is the ticket: the
converter has to write every header byte something reads, and zero the rest on
evidence rather than by analogy with Pool of Radiance's `HEADER_ZEROED`.

    absrefsweep.py curse-of-the-azure-bonds 4B00 4EFF
    absrefsweep.py curse-of-the-azure-bonds 4B00 4EFF --sites 4BEA
    absrefsweep.py pool-of-radiance 4900 4CFF          the control

The output is one row per address: how many absolute-mode operands name it and
which files they are in. **A hit is a claim about bytes and not proof they are
code** -- a bitmap holds every byte pair sooner or later, and the way to tell is
that real code clusters in the overlays (`DUNGEON`, `CAMP`, `GEN`, `COMBAT`,
`LIBRARY`) while noise turns up once each in `PIC*`, `BODY*` and `WALLDEF*`.
`--sites` disassembles around each hit so the reader can judge.

The address is absolute, so no load address is needed and none is assumed: an
absolute operand carries its own target wherever the overlay runs.
"""

from __future__ import annotations

import argparse
import collections
import os
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from automap.paths import disk_globs, find_disks  # noqa: E402
from goldbox import games  # noqa: E402
from goldbox.d64 import D64  # noqa: E402
from tools import d6502, gamedisks  # noqa: E402

#: Where an overlay runs, for the disassembly `--sites` prints. `LINKER` puts
#: every overlay read so far at `$0800` whatever its own header claims
#: (`docs/118-debug-mode.md`), and the addresses printed beside a hit are only
#: as right as that.
OVERLAY_BASE = 0x0800

#: 6502 opcodes with a two-byte absolute operand, and how to print them.
ABSOLUTE = {
    0x0D: "ORA", 0x0E: "ASL", 0x2C: "BIT", 0x2D: "AND", 0x2E: "ROL",
    0x4D: "EOR", 0x4E: "LSR", 0x6D: "ADC", 0x6E: "ROR", 0x8C: "STY",
    0x8D: "STA", 0x8E: "STX", 0xAC: "LDY", 0xAD: "LDA", 0xAE: "LDX",
    0xCC: "CPY", 0xCD: "CMP", 0xCE: "DEC", 0xEC: "CPX", 0xED: "SBC",
    0xEE: "INC", 0x20: "JSR", 0x4C: "JMP",
    0x1D: "ORA,X", 0x1E: "ASL,X", 0x3D: "AND,X", 0x3E: "ROL,X",
    0x5D: "EOR,X", 0x5E: "LSR,X", 0x7D: "ADC,X", 0x7E: "ROR,X",
    0x9D: "STA,X", 0xBC: "LDY,X", 0xBD: "LDA,X", 0xDD: "CMP,X",
    0xDE: "DEC,X", 0xFD: "SBC,X", 0xFE: "INC,X",
    0x19: "ORA,Y", 0x39: "AND,Y", 0x59: "EOR,Y", 0x79: "ADC,Y",
    0x99: "STA,Y", 0xB9: "LDA,Y", 0xBE: "LDX,Y", 0xD9: "CMP,Y",
    0xF9: "SBC,Y",
}

#: File-name prefixes that are art rather than code. A hit in one of these is
#: almost certainly a byte pair inside a bitmap; they are counted separately
#: rather than dropped, because "almost certainly" is not a reading.
ART_PREFIXES = ("PIC", "COMPIC", "BODY", "HEAD", "SPRITE", "WALLSET",
                "WALLDEF", "TITLEPG", "CHARSET", "MON", "ITEMFILE",
                "SOUNDFX", "SKY", "BIGPIC")


#: `ECL<id>` is the script VM's own bytecode, not 6502, so a two-byte operand
#: in one is a *script* variable and not an instruction naming an address --
#: `tools/eclcensus.py` is what reads those. `ECL64` and `ECL65` are ordinary
#: overlays despite the name, which is why the test is on the id and not on the
#: prefix.
SCRIPT_IDS_EXCEPT = ("64", "65")


def is_script(name: str) -> bool:
    if not name.startswith("ECL") or len(name) != 5:
        return False
    if name[3:] in SCRIPT_IDS_EXCEPT:
        return False
    try:
        int(name[3:], 16)
    except ValueError:
        return False
    return True


def is_art(name: str) -> bool:
    return name.startswith(ART_PREFIXES) or is_script(name)


def disks(root: str, game: games.Game) -> list[str]:
    seen: dict[str, str] = {}
    for pattern in disk_globs(game):
        for path in sorted(pathlib.Path(root).glob(pattern)):
            seen.setdefault(os.path.normcase(str(path)), str(path))
    return sorted(seen.values())


def files(root: str, game: games.Game):
    """`(disk, name, body)` for every file on every side, each name once."""
    seen: set[str] = set()
    for path in disks(root, game):
        try:
            image = D64.open(path)
        except Exception:
            continue
        disk = pathlib.Path(path).name
        for entry in image.iter_directory():
            name = entry.name.decode("latin1").rstrip("\xa0 ")
            if name in seen:
                continue
            try:
                body = image.read_file(name)[2:]
            except Exception:
                continue
            seen.add(name)
            yield disk, name, body


class Hit:
    __slots__ = ("disk", "file", "at", "op", "address")

    def __init__(self, disk, file, at, op, address):
        self.disk, self.file, self.at = disk, file, at
        self.op, self.address = op, address


def sweep(root: str, game: games.Game, lo: int, hi: int):
    hits: list[Hit] = []
    scanned = 0
    for disk, name, body in files(root, game):
        scanned += 1
        for i in range(len(body) - 2):
            op = ABSOLUTE.get(body[i])
            if op is None:
                continue
            address = body[i + 1] | (body[i + 2] << 8)
            if lo <= address <= hi:
                hits.append(Hit(disk, name, OVERLAY_BASE + i, op, address))
    return scanned, hits


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("title")
    parser.add_argument("lo", help="low address, hex")
    parser.add_argument("hi", help="high address, hex")
    parser.add_argument("--disks", help="where that title's sides are")
    parser.add_argument("--sites", nargs="+", metavar="ADDR",
                        help="disassemble around every hit on these")
    parser.add_argument("--art", action="store_true",
                        help="count art files in the per-address rows")
    args = parser.parse_args(argv)

    game = next((g for g in games.GAMES
                 if g.key == args.title or g.title == args.title), None)
    if game is None:
        raise SystemExit(f"No such title: {args.title}")
    root = args.disks or (str(gamedisks.find(game.key) or "")
                          or str(find_disks(game) or ""))
    if not root or not os.path.isdir(root):
        raise SystemExit(f"No disks for {game.title}; pass --disks.")

    lo, hi = int(args.lo, 16), int(args.hi, 16)
    scanned, hits = sweep(root, game, lo, hi)
    code = [h for h in hits if not is_art(h.file)]
    art = [h for h in hits if is_art(h.file)]
    print(f"{game.title}: ${lo:04X}-${hi:04X} over {scanned} distinct files")
    print(f"  {len(code)} references in code files, {len(art)} in art and "
          f"script files (a byte pair in a bitmap is not an instruction, and "
          f"an operand in ECL bytecode is not one either)")

    chosen = hits if args.art else code
    by_address: dict[int, list[Hit]] = {}
    for h in chosen:
        by_address.setdefault(h.address, []).append(h)
    print(f"\n  {'address':>8} {'refs':>5}  files")
    for address in sorted(by_address):
        here = by_address[address]
        who = collections.Counter(h.file for h in here)
        print(f"  ${address:04X} {len(here):>5}  "
              + ", ".join(f"{k} x{v}" for k, v in who.most_common(8)))
    print(f"\n  {len(by_address)} distinct addresses named")

    if args.sites:
        wanted = {int(v, 16) for v in args.sites}
        bodies = {name: body for _disk, name, body in files(root, game)}
        for h in sorted(chosen, key=lambda h: (h.address, h.file, h.at)):
            if h.address not in wanted:
                continue
            print(f"\n  ${h.address:04X} in {h.file} at ${h.at:04X}:")
            body = bodies[h.file]
            start = max(OVERLAY_BASE, h.at - 12)
            for line in d6502.lines(body, OVERLAY_BASE, start, 30):
                print("    " + line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
