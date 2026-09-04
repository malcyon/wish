#!/usr/bin/env python3
"""Pull the Amiga *Pool of Radiance* character specimens out of the disks.

The twenty records `#27 (Decode the Amiga Pool of Radiance record, so a shared
title exists)` and `#105 (Write an Amiga Pool of Radiance character, not just a
Pools of Darkness one)` rest on are not loose files anywhere -- they are inside
AmigaDOS disk images:

* six the game itself wrote, in the `save/` drawer of **Pool of Radiance disk
  1**, with their `.itm` and `.spc` beside them;
* fourteen `.cha` exports staged in the `save/` drawer of the **Curse of the
  Azure Bonds save disk**, which is where nobody was looking for them.

They were once extracted into `work/`, which is gitignored and has been lost
twice, so `$AMIGA_POR_SAVES` pointed at nothing and thirty-one tests skipped on
the machine that has every byte of the corpus -- the shape of
`#211 (103 tests skip on the machine that has the game files, and the game
files are not why)`.  This is the tool that produces them again, and
`tests/test_amiga.py` calls :func:`extract` itself when the environment names
no directory, so the corpus is never only in a scratch directory again.

    tools/amigasaves.py -o work/amiga-por-saves

The disks are opened **read-only**; nothing is written anywhere but `--out`.

What counts as a specimen
-------------------------
A file of exactly `AMIGA_POR_RECORD_SIZE` (288) bytes in a `save/` drawer, on
a disk that carries one.  That is a shape test rather than a name test on
purpose: the six on disk 1 are `CHRDATA<n>.sav` and the fourteen on the Curse
disk are arbitrary `.cha` names, and neither list is a rule.  Anything else of
that size on a Gold Box disk would be a find rather than a miss, so it is
reported rather than filtered out.

Names, and why they are prefixed
--------------------------------
Two disks can hold `CHRDATA1.sav`, so each record is written as
`<volume>-<stem><suffix>` -- `poolgame-CHRDATA1.sav`, `cursesave-TIGGY.cha`.
The `.itm` and `.spc` siblings keep the same stem, because `read_amiga_por`
finds them with `Path.with_suffix`.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox.amiga import AMIGA_POR_RECORD_SIZE, POR_SAVE_DRAWER  # noqa: E402
from goldbox.amiga_adf import AmigaDisk, AmigaDiskError  # noqa: E402
from tools import gamedisks  # noqa: E402

#: The siblings a record is read with. `read_amiga_por` needs the `.itm` to
#: know what the character carries and the `.spc` for its effects, and a
#: record without them tests only a third of the reader.
SIBLINGS = (".itm", ".spc")

#: Which archives are worth opening. `$AMIGA_DISKS` points at a whole Amiga
#: ROM library here -- 1176 zips, of which 41 match this -- so an unfiltered
#: sweep would decompress Bubble Bobble a dozen times to find nothing. Loose
#: `.adf` files are opened whatever they are called; there are eight.
GOLD_BOX = re.compile(r"pool|radiance|curse|azure|silver|blade|darkness",
                      re.IGNORECASE)


def images(roots: list[pathlib.Path] | None = None):
    """Every Amiga disk image worth looking in, as `(label, bytes)`.

    `label` is where it came from, for a report that has to be checkable: a
    path for a loose `.adf`, `archive.zip!member.adf` for one inside a zip.
    """
    if roots is None:
        roots = gamedisks.candidates("amiga")
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() == ".adf":
                yield str(path), path.read_bytes()
            elif path.suffix.lower() == ".zip" and GOLD_BOX.search(path.name):
                try:
                    with zipfile.ZipFile(path) as zf:
                        for member in sorted(zf.namelist()):
                            if member.lower().endswith(".adf"):
                                yield f"{path}!{member}", zf.read(member)
                except zipfile.BadZipFile:
                    continue


def specimens(roots: list[pathlib.Path] | None = None):
    """Every 288-byte record on those disks, as `(label, volume, name, files)`.

    `files` maps a suffix -- `""` for the record itself, then `.itm`, `.spc`
    for whichever siblings the disk carries -- to its bytes.  A record with no
    siblings is still a specimen: fourteen of the twenty have none, and the
    tests that need an item file say so and skip rather than pass vacuously.
    """
    for label, data in images(roots):
        try:
            disk = AmigaDisk(data)
        except (AmigaDiskError, ValueError):
            continue
        try:
            entries = list(disk.walk())
        except AmigaDiskError:
            continue
        for path, _entry in entries:
            parts = path.strip("/").split("/")
            if len(parts) != 2 or parts[0].lower() != POR_SAVE_DRAWER:
                continue
            try:
                record = disk.read_file(path)
            except AmigaDiskError:
                continue
            if len(record) != AMIGA_POR_RECORD_SIZE:
                continue
            stem = parts[1].rsplit(".", 1)[0]
            suffix = parts[1][len(stem):]
            files = {suffix: record}
            for also in SIBLINGS:
                if also == suffix:
                    continue
                try:
                    files[also] = disk.read_file(f"/{parts[0]}/{stem}{also}")
                except AmigaDiskError:
                    pass
            yield label, disk.volume_name, stem + suffix, files


def extract(out: pathlib.Path,
            roots: list[pathlib.Path] | None = None,
            report: list[str] | None = None) -> list[pathlib.Path]:
    """Write every specimen under `out`, and return the record paths.

    The record's own path is what a caller wants: `read_amiga_por` picks the
    siblings up from beside it.  `report`, when given, collects one line per
    record naming the image it came from.
    """
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    written: list[pathlib.Path] = []
    for label, volume, name, files in specimens(roots):
        stem = name.rsplit(".", 1)[0]
        suffix = name[len(stem):]
        for also, data in files.items():
            here = out / f"{volume}-{stem}{also}"
            # Four rips of Pool of Radiance disk 1 and two copies of the
            # Curse save disk are on this machine and their save drawers are
            # byte-identical, 38 files of 38 -- so the later write is a
            # no-op. If one ever is not, that is a specimen nobody has seen
            # rather than something to overwrite quietly.
            if here.exists() and here.read_bytes() != data:
                raise SystemExit(
                    f"{here.name} differs between two images: {label} does "
                    f"not agree with what is already there. Extract them to "
                    f"separate directories and say which is which")
            here.write_bytes(data)
        written.append(out / f"{volume}-{stem}{suffix}")
        if report is not None:
            report.append(f"{volume}-{name:<24} {len(files)} file(s)   "
                          f"{label}")
    return sorted(set(written))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.
                                     RawDescriptionHelpFormatter)
    parser.add_argument("-o", "--out", required=True,
                        help="the directory the records are written to")
    parser.add_argument("--disks", action="append", default=None,
                        help="a directory of Amiga disk images; repeatable. "
                             "Defaults to gamedisks.toml's `amiga` entry")
    args = parser.parse_args(argv)

    roots = ([pathlib.Path(d).expanduser() for d in args.disks]
             if args.disks else None)
    where = roots if roots is not None else gamedisks.candidates("amiga")
    if not where:
        raise SystemExit("No Amiga disks: set $AMIGA_DISKS or pass --disks")

    lines: list[str] = []
    found = extract(pathlib.Path(args.out), roots, lines)
    for line in lines:
        print(line)
    if not found:
        raise SystemExit(
            f"No {AMIGA_POR_RECORD_SIZE}-byte records in a save/ drawer under "
            + ", ".join(str(p) for p in where))
    print(f"{len(found)} records into {args.out}; "
          f"set $AMIGA_POR_SAVES to it to un-skip the Amiga tests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
