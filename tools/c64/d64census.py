#!/usr/bin/env python3
"""Census a tree of D64 images: the disk header, and the character files on it.

Written for `#553 (A Curse or Silver Blades character disk is read with Pool of
Radiance's tables, so a paladin's class shows as 64 and a dual-classed
character's former class disappears)`, which asked two questions a per-image
loop answers and nothing else does:

* **header** -- the disk name at track 18 sector 0 + `0x90` and the id at
  `+0xA2`, counted over every image. `MAKE SAVE GAME DISK` sends
  `N0:SG,Q9` in all three C64 titles, so the header never names one; what a
  save disk carries is whatever formatted it, and 44 of the images on this
  machine say `CURSE SAVE` because `tools/curserun.py` wrote them.
* **files** -- every PRG that parses as an occupied `CharacterRecord`, by its
  one-byte filename prefix (`$01` Pool of Radiance, `$02` Curse, `$05` Silver
  Blades -- `docs/216-the-c64-name-table.md`), its PRG load address, and which
  title's save file shares the disk with it.

    tools/c64/d64census.py header /mnt/media/roms/c64 ~/wish-specimens
    tools/c64/d64census.py files  /mnt/media/roms/c64 work

With no roots it sweeps what `tools/gamedisks.py` knows about.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent.parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from goldbox import c64_port  # noqa: E402
from goldbox.d64 import (  # noqa: E402
    D64,
    DIRECTORY_TRACK,
    HEADER_SECTOR,
    sector_offset,
)
from goldbox.record import CharacterRecord  # noqa: E402
from goldbox.savegame import looks_occupied  # noqa: E402

BAM = sector_offset(DIRECTORY_TRACK, HEADER_SECTOR)


def images(roots) -> list[pathlib.Path]:
    seen, out = set(), []
    for root in roots:
        r = pathlib.Path(root).expanduser()
        if not r.exists():
            continue
        for p in sorted(r.rglob("*")):
            if p.suffix.lower() != ".d64" or not p.is_file():
                continue
            rp = p.resolve()
            if rp not in seen:
                seen.add(rp)
                out.append(p)
    return out


def default_roots() -> list[str]:
    from tools import gamedisks
    return [path for _name, _var, _layer, path, ok in gamedisks.report()
            if ok] or ["."]


def show(raw: bytes) -> str:
    return "".join(chr(c) if 32 <= c < 127 else f"\\x{c:02x}" for c in raw)


def cmd_header(paths) -> int:
    counts: collections.Counter = collections.Counter()
    examples: dict[tuple, str] = {}
    for p in paths:
        try:
            with p.open("rb") as fh:
                fh.seek(BAM)
                sector = fh.read(256)
        except OSError:
            continue
        if len(sector) < 256:
            continue
        key = (bytes(sector[0x90:0xA0]).rstrip(b"\xa0"), bytes(sector[0xA2:0xA4]))
        counts[key] += 1
        examples.setdefault(key, p.name)
    print(f"images: {sum(counts.values())}\n")
    print(f"{'count':>6}  {'name':24} {'id':8} example")
    for (name, did), n in counts.most_common():
        print(f"{n:6}  {show(name):24} {show(did):8} {examples[(name, did)]}")
    return 0


def cmd_files(paths) -> int:
    counts: collections.Counter = collections.Counter()
    examples: dict[tuple, str] = {}
    parsed = 0
    for p in paths:
        try:
            disk = D64.open(str(p))
            entries = disk.directory()
        except Exception:
            continue
        game = c64_port.detect(disk)
        for entry in entries:
            if not entry.is_prg or entry.is_empty:
                continue
            try:
                raw = disk.read_file(entry)
                record = CharacterRecord.from_prg(raw, None)
            except Exception:
                continue
            if not looks_occupied(record.to_bytes()):
                continue
            parsed += 1
            name = bytes(entry.name)
            prefix = name[0] if name and name[0] < 0x20 else None
            key = (game.key if game else "-", prefix, raw[0] | (raw[1] << 8))
            counts[key] += 1
            examples.setdefault(key, f"{p.name}:{show(name)}")
    print(f"images: {len(paths)}   character files: {parsed}\n")
    print(f"{'files':>6}  {'save file on disk':30} {'prefix':7} {'load':6} example")
    for (game, prefix, load), n in counts.most_common():
        pre = f"${prefix:02X}" if prefix is not None else "none"
        print(f"{n:6}  {game:30} {pre:7} ${load:04X} "
              f"{examples[(game, prefix, load)]}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("what", choices=("header", "files"))
    ap.add_argument("roots", nargs="*", help="directories to sweep")
    args = ap.parse_args(argv)
    paths = images(args.roots or default_roots())
    return cmd_header(paths) if args.what == "header" else cmd_files(paths)


if __name__ == "__main__":
    raise SystemExit(main())
