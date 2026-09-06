#!/usr/bin/env python3
"""Does a DOS Curse or Silver Blades record number its combat art the way a
DOS Pool of Radiance record does?  (`#330`.)

The conversion composes a C64 combat figure out of a DOS record's `icon_head`
and `icon_body` through one correspondence table, `tools/iconproposal.yaml`,
which was read off Pool of Radiance's art.  `IconParts.dos_icon` takes no
title, so the same table serves Curse of the Azure Bonds and Secret of the
Silver Blades.  A wrong-but-in-range row there is invisible: the figure that
comes out is a complete, plausible character who is simply not the one the
player made.

This asks the question two ways and prints both.

**The art.**  `CHEAD.DAX` and `CBODY.DAX` hold one image block per option per
size per pose, at block id `option + (64 if size 2) + (128 if pose 2)`
(`docs/168-dos-dax-and-combat-icons.md`).  `--art`, the default, unpacks every
block of every title and compares each id against the reference title's, so
"the same art in the same order" is a count rather than an impression.  A
block that differs is reported as the option, size and pose it draws, with how
many of its 4-bit pixels changed and which part values each side uses -- a
description of the difference rather than a copy of it.

**The code.**  `--code` reads each title's `GAME.OVR` for the two things that
say the numbering is the engine's and not ours: the ICON menu's own wrap
constants at that title's record displacement (13 heads, 31 bodies in Pool of
Radiance), and the importer that reads the *previous* title's record and
writes this one's.  A straight copy there is the shipped game asserting that
the two numbering schemes are the same.  The record displacements come from
`goldbox.dos_layout`, so a wrong offset in our own table shows up here as a
missing scan rather than as a silent pass.

    tools/dosicontitles.py                       # art, all four DOS titles
    tools/dosicontitles.py --code
    tools/dosicontitles.py --json work/issue330/icontitles.json

The game folders are found under `$FR_ARCHIVES`, then `gamedisks.toml`'s
`dos-archives` entry.  Everything is read and nothing is written except what
`--json` names, which belongs under `work/`.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import struct
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT))

from goldbox import dos_layout  # noqa: E402
from goldbox.dos_savegame import DaxError, dax_index, dax_unpack  # noqa: E402
from tools import gamedisks  # noqa: E402

#: The four DOS Gold Box titles this project reads, and the directory name the
#: archives give each.  Keyed by `goldbox.dos_layout` shape key so the record
#: displacements below come from one place.
TITLES: tuple[tuple[str, str], ...] = (
    ("pool-of-radiance", "POOLRAD"),
    ("curse-of-the-azure-bonds", "CURSE"),
    ("secret-of-the-silver-blades", "SECRET"),
    ("pools-of-darkness", "DARKNESS"),
)

FILES = ("CHEAD.DAX", "CBODY.DAX")
IMAGE_HEADER = 17

#: What a 4-bit pixel means in `CHEAD` and `CBODY`.  The recolour lookup the
#: engine builds only ever touches 1-4, 6 and 7 and their +8 highlights, so a
#: block using values the record cannot repaint is drawing something fixed.
PART_VALUES = {0: "transparent", 1: "body", 2: "arm", 3: "leg", 4: "hair",
               5: "cap", 6: "shield", 7: "weapon", 8: "outline",
               9: "body+", 10: "arm+", 11: "leg+", 12: "face", 13: "cap+",
               14: "shield+", 15: "weapon+"}

#: The nine bytes at block offset 8.  Every block SSI packed for these two
#: files carries this; a block carrying zeroes there was rebuilt by something
#: else, which is a second, independent way to spot a re-drawn option.
SSI_HEADER = bytes.fromhex("011222222303333233")


# -- the containers ----------------------------------------------------------
def blocks(path: pathlib.Path) -> dict[int, bytes]:
    """Every block of a `.DAX`, unpacked, by id."""
    data = path.read_bytes()
    base = 2 + struct.unpack_from("<H", data, 0)[0]
    out = {}
    for bid, off, raw, packed in dax_index(data, path.name):
        out[bid] = dax_unpack(data[base + off:base + off + packed], raw,
                              f"{path.name}:{bid}")
    return out


def option_of(bid: int) -> tuple[int, str, int]:
    """`(option, size, pose)` for a block id.

    The loader adds `0x40` when the record's `size` byte is 2 and loads
    `id + 0x80` as the second pose (`GAME.OVR:0x31CAE` in Pool of Radiance),
    so the id is three fields and this is their inverse.
    """
    pose = 2 if bid >= 0x80 else 1
    within = bid & 0x7F
    return within & 0x3F, ("large" if within >= 0x40 else "small"), pose


def four_bit_image(block: bytes) -> bool:
    """Whether this block is the 4-bit image every Pool of Radiance one is.

    The test is the length identity `tools/daxls.py` uses: the 17-byte header
    plus `rows * width_in_eights * 4`.  Pools of Darkness fails it -- its
    `CHEAD` blocks are 422 bytes where 10 rows of 24 pixels would be 137 --
    so its art is a different encoding and nothing below may read it as this
    one.  What that encoding is has not been decoded (`#330`).
    """
    if len(block) < IMAGE_HEADER:
        return False
    rows, eights = block[0], block[2]
    return bool(rows and eights and
                len(block) == IMAGE_HEADER + rows * eights * 4)


def pixels(block: bytes) -> list[list[int]]:
    """An image block's 4-bit values, `[row][column]`, high nibble first."""
    rows, width = block[0], block[2] * 8
    stride = width // 2
    return [[v for b in block[IMAGE_HEADER + y * stride:
                              IMAGE_HEADER + (y + 1) * stride]
             for v in (b >> 4, b & 0x0F)]
            for y in range(rows)]


def parts_used(block: bytes) -> list[str]:
    """Which named part values this block draws, in value order."""
    if not four_bit_image(block):
        return ["not a 4-bit image block"]
    seen = {v for row in pixels(block) for v in row if v}
    return [PART_VALUES.get(v, str(v)) for v in sorted(seen)]


def differing_pixels(a: bytes, b: bytes) -> tuple[int, int]:
    """`(differing, compared)` over the rows the two blocks share.

    `(None, 0)` when either side is not a 4-bit image block, because counting
    pixels in an encoding nobody has decoded would be a number with nothing
    under it.
    """
    if not (four_bit_image(a) and four_bit_image(b)):
        return None, 0
    pa, pb = pixels(a), pixels(b)
    rows = min(len(pa), len(pb))
    width = min(len(pa[0]), len(pb[0])) if rows else 0
    return (sum(1 for y in range(rows) for x in range(width)
                if pa[y][x] != pb[y][x]),
            rows * width)


def compare_art(folders: dict[str, pathlib.Path], reference: str) -> dict:
    """One record per file per title: the ids, and how they differ."""
    out: dict[str, dict] = {}
    for name in FILES:
        ref = blocks(folders[reference] / name)
        out[name] = {"reference": reference, "titles": {}}
        for key, folder in folders.items():
            mine = blocks(folder / name)
            options = sorted({option_of(b)[0] for b in mine})
            row = {
                "blocks": len(mine),
                "options": len(options),
                "highest_option": max(options) if options else None,
                "rows": sorted({b[0] for b in mine.values()}),
                "four_bit_images": sum(1 for b in mine.values()
                                       if four_bit_image(b)),
                "rebuilt_header": sorted(b for b, v in mine.items()
                                         if v[8:IMAGE_HEADER] != SSI_HEADER),
                "identical": 0, "redrawn": [], "added": [], "missing": [],
            }
            for bid in sorted(set(ref) | set(mine)):
                if bid not in mine:
                    row["missing"].append(bid)
                elif bid not in ref:
                    row["added"].append(bid)
                elif mine[bid] == ref[bid]:
                    row["identical"] += 1
                else:
                    option, size, pose = option_of(bid)
                    changed, compared = differing_pixels(ref[bid], mine[bid])
                    row["redrawn"].append({
                        "id": bid, "option": option, "size": size, "pose": pose,
                        "rows_reference": ref[bid][0], "rows_here": mine[bid][0],
                        "changed_pixels": changed, "compared_pixels": compared,
                        "parts_reference": parts_used(ref[bid]),
                        "parts_here": parts_used(mine[bid]),
                    })
            out[name]["titles"][key] = row
    return out


# -- the overlays ------------------------------------------------------------
#: `mov al, es:[di+disp16]` and `mov es:[di+disp16], al`, which is how a
#: Turbo Pascal build of this engine reaches a character record field.
LOAD = b"\x26\x8a\x85"
STORE = b"\x26\x88\x85"
#: `cmp byte ptr es:[di+disp16], imm8`, the ICON menu's wrap test.
COMPARE = b"\x26\x80\xbd"


def _disp(value: int) -> bytes:
    return bytes([value & 0xFF, value >> 8])


def icon_fields(key: str) -> dict[str, int]:
    """This title's `icon_head`, `icon_body` and `size` record offsets."""
    table = dos_layout.FIELDS_BY_NAME_FOR[key]
    return {n: table[n].offset for n in ("icon_head", "icon_body", "size")}


def wrap_constants(code: bytes, offset: int) -> list[int]:
    """Every immediate the overlay compares this record byte against.

    The ICON menu walks its list with `inc`/`dec` and wraps at the last
    option, so the largest constant here is one less than the number of
    options the engine offers.
    """
    return sorted({code[m.end()] for m
                   in re.finditer(re.escape(COMPARE + _disp(offset)), code)})


def importer_copies(code: bytes, source: int, destination: int,
                    window: int = 32) -> list[int]:
    """Where the overlay loads `source` and stores `destination` just after.

    A title's own importer reads the previous title's record and writes its
    own.  Copying a byte straight across is the shipped engine saying the two
    fields hold the same numbering; anything else would need a table.
    """
    store = re.escape(STORE + _disp(destination))
    return [m.start() for m in re.finditer(re.escape(LOAD + _disp(source)), code)
            if re.search(store, code[m.end():m.end() + window])]


def block_copies(code: bytes, source: int, destination: int,
                 window: int = 48) -> list[int]:
    """Where the overlay adds `source` to one pointer and `destination` to
    another just after -- a block move of the six colour bytes rather than a
    byte at a time.  `add di, imm16` is `81 C7 lo hi`.
    """
    add = b"\x81\xc7"
    later = re.escape(add + _disp(destination))
    return [m.start() for m in re.finditer(re.escape(add + _disp(source)), code)
            if re.search(later, code[m.end():m.end() + window])]


def read_code(folders: dict[str, pathlib.Path], keys: list[str]) -> dict:
    """The wrap constants, and each title's copy out of its predecessor."""
    out = {}
    for i, key in enumerate(keys):
        overlay = folders[key] / "GAME.OVR"
        code = overlay.read_bytes() if overlay.exists() else b""
        fields = icon_fields(key)
        row = {"overlay": overlay.name, "bytes": len(code), "fields": fields,
               "wraps": {n: wrap_constants(code, o) for n, o in fields.items()},
               "imports_from": None, "copies": {}}
        if i:
            before = keys[i - 1]
            row["imports_from"] = before
            theirs = icon_fields(before)
            for name in ("icon_head", "icon_body", "size"):
                row["copies"][name] = importer_copies(
                    code, theirs[name], fields[name])
            row["copies"]["icon_colours"] = block_copies(
                code, theirs["size"] + 1, fields["size"] + 1)
        out[key] = row
    return out


# -- where the games are -----------------------------------------------------
def archives(given: str | None) -> pathlib.Path:
    """`--archives`, then `$FR_ARCHIVES`, then `gamedisks.toml`."""
    if given:
        return pathlib.Path(given).expanduser()
    named = os.environ.get("FR_ARCHIVES")
    if named:
        return pathlib.Path(named).expanduser()
    found = gamedisks.find("dos-archives")
    if found is None:
        raise SystemExit("no Forgotten Realms archives; pass --archives, or "
                         "set $FR_ARCHIVES")
    return found


def find_folders(root: pathlib.Path, keys: list[str]) -> dict[str, pathlib.Path]:
    """Each title's game directory, by the `CHEAD.DAX` inside it."""
    wanted = {name: key for key, name in TITLES if key in keys}
    out: dict[str, pathlib.Path] = {}
    for path in root.rglob("CHEAD.DAX"):
        key = wanted.get(path.parent.name.upper())
        if key and key not in out:
            out[key] = path.parent
    missing = [k for k in keys if k not in out]
    if missing:
        raise SystemExit(f"no CHEAD.DAX under {root} for {', '.join(missing)}")
    return out


# -- the report --------------------------------------------------------------
def art_lines(art: dict) -> list[str]:
    lines = []
    for name, section in art.items():
        ref = section["reference"]
        lines.append(f"{name} -- against {ref}")
        lines.append(f"  {'title':30} {'blocks':>6} {'options':>7} "
                     f"{'4-bit':>6} {'rows':>8} {'same':>5} {'redrawn':>7} "
                     f"{'added':>5} {'gone':>5}")
        for key, row in section["titles"].items():
            lines.append(
                f"  {key:30} {row['blocks']:6} {row['options']:7} "
                f"{row['four_bit_images']:6} "
                f"{','.join(str(r) for r in row['rows']):>8} "
                f"{row['identical']:5} {len(row['redrawn']):7} "
                f"{len(row['added']):5} {len(row['missing']):5}")
        for key, row in section["titles"].items():
            other = [h for h in row["redrawn"] if h["changed_pixels"] is None]
            if other:
                lines.append(
                    f"    {key}: {len(other)} blocks are not the 4-bit image "
                    f"{ref} packs, so the art is a different encoding and is "
                    f"not compared pixel for pixel here")
            for hit in row["redrawn"]:
                if hit["changed_pixels"] is None:
                    continue
                lines.append(
                    f"    {key}: {hit['size']} option {hit['option']} pose "
                    f"{hit['pose']} (block {hit['id']}) -- "
                    f"{hit['changed_pixels']} of {hit['compared_pixels']} "
                    f"pixels differ, {hit['rows_reference']} rows there and "
                    f"{hit['rows_here']} here")
                lines.append(f"      {ref} draws "
                             f"{', '.join(hit['parts_reference'])}")
                lines.append(f"      {key} draws "
                             f"{', '.join(hit['parts_here'])}")
            if row["rebuilt_header"] and row["four_bit_images"] == row["blocks"]:
                lines.append(f"    {key}: blocks with no SSI packer header: "
                             f"{row['rebuilt_header']}")
    return lines


def code_lines(code: dict) -> list[str]:
    lines = ["the overlays"]
    for key, row in code.items():
        lines.append(f"  {key} ({row['overlay']}, {row['bytes']} bytes)")
        for name, offset in row["fields"].items():
            lines.append(f"    {name:11} at record 0x{offset:03X}; the ICON "
                         f"menu compares it against {row['wraps'][name]}")
        if row["imports_from"]:
            lines.append(f"    importer, reading a {row['imports_from']} "
                         f"record:")
            for name, hits in row["copies"].items():
                where = ", ".join(hex(h) for h in hits) or "no site"
                lines.append(f"      {name:14} copied straight across at "
                             f"{where}")
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--archives", help="the unpacked Forgotten Realms archives")
    ap.add_argument("--titles",
                    default="pool-of-radiance,curse-of-the-azure-bonds,"
                            "secret-of-the-silver-blades",
                    help="comma-separated shape keys, in importer order; add "
                         "pools-of-darkness for the fourth")
    ap.add_argument("--reference", default="pool-of-radiance",
                    help="the title every other is compared against")
    ap.add_argument("--art", action="store_true", help="compare the art (default)")
    ap.add_argument("--code", action="store_true", help="read the overlays")
    ap.add_argument("--json", help="write the whole comparison here")
    args = ap.parse_args(argv)

    keys = [k.strip() for k in args.titles.split(",") if k.strip()]
    known = {k for k, _ in TITLES}
    unknown = [k for k in keys if k not in known]
    if unknown:
        raise SystemExit(f"not a DOS title here: {', '.join(unknown)}; "
                         f"know {', '.join(sorted(known))}")
    if args.reference not in keys:
        keys.insert(0, args.reference)
    folders = find_folders(archives(args.archives), keys)

    want_art = args.art or not args.code
    report: dict = {"folders": {k: str(v) for k, v in folders.items()}}
    lines = []
    if want_art:
        try:
            report["art"] = compare_art(folders, args.reference)
        except DaxError as exc:
            raise SystemExit(f"a container would not unpack: {exc}") from exc
        lines += art_lines(report["art"])
    if args.code:
        report["code"] = read_code(folders, keys)
        lines += code_lines(report["code"])
    print("\n".join(lines))

    if args.json:
        out = pathlib.Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, sort_keys=True))
        print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
