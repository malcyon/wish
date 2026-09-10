#!/usr/bin/env python3
"""Measure the Amiga *Curse* and *Silver Blades* combat-icon art against DOS's.

`#396 (Whether an Amiga Curse or Silver Blades record's combat-icon fields
share DOS's own numbering is unmeasured)` asked whether an Amiga record's
`icon_head`, `icon_body`, `icon_dimension` and `icon_colours` mean what the
same fields mean on DOS, or whether they are DOS-shaped bytes indexing a
different set of drawings.  This is the measurement.

Three questions, three modes.

``--tables``
    The three tables the Amiga icon routine reads, out of each executable's
    data hunk at a resolved address: the sixteen-entry translation from a DOS
    pixel value to an Amiga palette entry, the six part codes the record's
    colour bytes are written through, and the size-letter table that turns
    `size` into the `S` or `T` the file name ends with.

``--art``
    Every block of `CHEAD.TLB` and `CBODY.TLB` against every block of the same
    title's DOS `CHEAD.DAX` and `CBODY.DAX`: the block ids, the dimensions,
    and each pixel through the translation table above.  A disagreement is
    printed as `(dos value, amiga colour)` with a count, because the one that
    exists is 42 pixels wide and would vanish in a percentage.

``--census``
    Every Amiga specimen's four icon fields, and whether the pair names art
    that is actually in the libraries.

    tools/amigaicons.py --tables
    tools/amigaicons.py --art
    tools/amigaicons.py --census

The `.TLB` container is `GLIB`, not the `.dax` `goldbox/amiga_dax.py` reads:
magic, a `u32` total size, a `u16` block count, a `u16`, a four-byte tag, then
`count + 1` big-endian `u32` offsets.  Block 0 is an index of `(art id, block
number)` pairs and the rest are tiles -- a `u16` height, two unused `u16`s, a
byte of width in eights and a byte, then five bitplanes stored one after
another, plane 0 being the transparency mask and planes 1-4 a four-bit colour.

Every disk and every executable is opened **read-only**; nothing is written.
"""

from __future__ import annotations

import argparse
import pathlib
import struct
import sys
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox.amiga_adf import AmigaDisk, AmigaDiskError  # noqa: E402
from goldbox.dos_savegame import dax_blocks  # noqa: E402
from tools import gamedisks  # noqa: E402

GLIB_MAGIC = b"GLIB"

#: Where each title keeps what this tool reads.  `art` is the disk volume and
#: the drawer the two `.TLB` libraries are in; `exe` is the executable on the
#: boot disk; `dos` is the game directory in the archives.  The volume names
#: are what `AmigaDisk.volume_name` reports, so a differently-named dump of
#: the same disk is found by the file names instead.
TITLES = {
    "curse-of-the-azure-bonds": {
        "art_files": ("CHEAD.TLB", "CBODY.TLB"),
        "exe": "Curse",
        "dos_dir": "CURSE",
        #: Data-hunk offsets of the three tables, named `g<offset>` the way
        #: `tools/amiga68k.py` names them in a listing.  Read out of the
        #: routine at file offset 0x24E42.
        "tables": {"colour": 0x0EE4, "parts": 0x1BB9, "letter": 0x1C11},
        "routine": 0x24E42,
    },
    "secret-of-the-silver-blades": {
        "art_files": ("CHEAD.TLB", "CBODY.TLB"),
        "exe": "Secret",
        "dos_dir": "SECRET",
        #: Read out of the routine at file offset 0x266BA.
        "tables": {"colour": 0x2374, "parts": 0x1F76, "letter": 0x2371},
        "routine": 0x266BA,
    },
}

#: How many head and body options each title's own menu offers, from the wrap
#: in the ICON menu -- Curse `0x15AE6`/`0x15A90`, Silver Blades
#: `0xBC46`/`0xBF44`, each `cmpi.b` against the last index.
HEAD_OPTIONS, BODY_OPTIONS = 14, 32

#: What the block loader adds to an art id: `0x40` for a large character (the
#: file name ends `T`) and `0x80` for the second pose.  Curse `0x34EA8` and
#: `0x34F1E`.
LARGE, POSE_TWO = 0x40, 0x80


class GlibError(ValueError):
    """This is not the `GLIB` container this reader knows how to read."""


def glib_blocks(data: bytes, name: str = "library") -> list[bytes]:
    """Every block of a `GLIB` container, in order."""
    if data[:4] != GLIB_MAGIC:
        raise GlibError(f"{name}: not a GLIB container, it opens {data[:4]!r}")
    try:
        count = struct.unpack_from(">H", data, 8)[0]
        offsets = struct.unpack_from(f">{count + 1}I", data, 16)
    except struct.error as e:
        raise GlibError(f"{name}: not a GLIB container: {e}") from e
    return [data[offsets[i]:offsets[i + 1]] for i in range(count)]


def tile_index(block: bytes, name: str = "library") -> list[tuple[int, int]]:
    """Block 0 of a `.TLB`, as `(art id, block number)` pairs.

    Pools of Darkness' disk 3 carries a `CHEAD.TLB` too and its block 0 is
    **empty**: that library is the later title's portrait art in a container
    laid out differently, and a caller that finds one wants to be told so
    rather than handed a `struct.error` out of a comprehension.
    """
    try:
        count = struct.unpack_from(">H", block, 0)[0]
        return [struct.unpack_from(">HH", block, 2 + 4 * i)
                for i in range(count)]
    except struct.error as e:
        raise GlibError(f"{name}: block 0 is not a tile index: {e}") from e


def tile_pixels(tile: bytes) -> tuple[int, int, list[list[int]]]:
    """One tile, as `(height, width, rows of palette entries)`.

    The five planes are stored one after another, not interleaved by row, and
    plane 0 is the transparency mask: a pixel's number here is
    `2 * colour + transparent`, which is what makes the identity in
    :func:`predicted` come out as it does.
    """
    height, _, _, in_eights, _ = struct.unpack_from(">HHHBB", tile, 0)
    body, width = tile[8:], in_eights * 8
    planes = len(body) // (height * in_eights) if height and in_eights else 0
    rows = []
    for r in range(height):
        row = []
        for x in range(width):
            value = 0
            for p in range(planes):
                byte = body[p * height * in_eights + r * in_eights + x // 8]
                value |= ((byte >> (7 - (x % 8))) & 1) << p
            row.append(value)
        rows.append(row)
    return height, width, rows


def tiles(data: bytes, name: str = "library") -> dict[int, tuple]:
    """`art id -> (height, width, rows)` for every tile of a `.TLB`."""
    blocks = glib_blocks(data, name)
    return {art: tile_pixels(blocks[block])
            for art, block in tile_index(blocks[0], name)}


def dos_tiles(path: pathlib.Path) -> dict[int, tuple]:
    """The same shape, out of a DOS `.DAX`: two 4-bit pixels a byte, high
    nibble first, after a 17-byte header whose first byte is the row count and
    whose third is the width in eights."""
    out = {}
    for art, block in dax_blocks(path.read_bytes(), path.name):
        height, width = block[0], block[2] * 8
        rows = []
        for r in range(height):
            line = block[17 + r * (width // 2):17 + (r + 1) * (width // 2)]
            row = []
            for byte in line:
                row.append(byte >> 4)
                row.append(byte & 0xF)
            rows.append(row)
        out[art] = (height, width, rows)
    return out


def predicted(dos_value: int, colour_table: bytes) -> int:
    """What an Amiga tile should hold where the DOS block holds `dos_value`.

    The engine's own table maps a DOS pixel value to a four-bit Amiga palette
    entry; the tile stores that entry in planes 1-4 with the mask in plane 0,
    and DOS's zero is the transparent one.
    """
    return colour_table[dos_value] * 2 + (1 if dos_value == 0 else 0)


# ---------------------------------------------------------------------------
# Finding the files
# ---------------------------------------------------------------------------
def _images():
    """Every Amiga disk image on this machine, as `(label, bytes)`."""
    from tools import amigasaves
    return amigasaves.images()


def find_art(art_files=("CHEAD.TLB", "CBODY.TLB")) -> dict[str, dict]:
    """`volume name -> {file name: bytes}` for every disk carrying the pair."""
    out: dict[str, dict] = {}
    for label, image in _images():
        try:
            disk = AmigaDisk(image)
            entries = list(disk.walk())
        except (AmigaDiskError, ValueError):
            continue
        found = {}
        for path, _entry in entries:
            name = path.strip("/").split("/")[-1].upper()
            if name in art_files:
                try:
                    found[name] = disk.read_file(path)
                except AmigaDiskError:
                    pass
        if len(found) == len(art_files):
            out.setdefault(f"{disk.volume_name} ({label})", found)
    return out


def find_executable(name: str) -> tuple[str, bytes] | None:
    """The named executable off whichever Amiga disk carries it."""
    for label, image in _images():
        try:
            disk = AmigaDisk(image)
            entries = list(disk.walk())
        except (AmigaDiskError, ValueError):
            continue
        for path, _entry in entries:
            if path.strip("/") == name:
                try:
                    return f"{label}:{path}", disk.read_file(path)
                except AmigaDiskError:
                    pass
    return None


def data_hunk(executable: bytes) -> int:
    """The file offset of the small-data hunk, so `g<offset>` can be read."""
    from tools.amiga68k import Executable
    exe = Executable.parse(executable)
    for hunk in exe.hunks:
        if hunk.kind == "DATA" and hunk.file_offset is not None:
            return hunk.file_offset
    raise SystemExit("no DATA hunk: this is not one of the two SAS/C builds")


def dos_directory(name: str) -> pathlib.Path | None:
    for root in gamedisks.candidates("dos-archives"):
        if not root.is_dir():
            continue
        for where in root.glob(f"*/games/{name}/GAME/{name}"):
            if (where / "CHEAD.DAX").is_file():
                return where
    return None


# ---------------------------------------------------------------------------
# The three reports
# ---------------------------------------------------------------------------
def report_tables(out) -> int:
    """The three tables, out of each executable at its own address."""
    missing = 0
    for key, where in TITLES.items():
        found = find_executable(where["exe"])
        if found is None:
            out(f"{key}: no /{where['exe']} on any disk image here")
            missing += 1
            continue
        label, data = found
        base = data_hunk(data)
        colour = data[base + where["tables"]["colour"]:][:16]
        parts = data[base + where["tables"]["parts"]:][:6]
        letter = data[base + where["tables"]["letter"]:][:3]
        out(f"{key}  ({label}, icon routine at 0x{where['routine']:05X})")
        out(f"  g{where['tables']['colour']:04x} DOS pixel value -> Amiga "
            f"palette entry: {' '.join(f'{b:2d}' for b in colour)}")
        out(f"  g{where['tables']['parts']:04x} the six recoloured parts:     "
            f"        {' '.join(f'{b:2d}' for b in parts)}")
        out(f"  g{where['tables']['letter']:04x} size letter, index 1 and 2:  "
            f"        {letter[1:3]!r}")
    return missing


def report_art(out) -> int:
    """Every Amiga block against the DOS block of the same id."""
    art = find_art()
    if not art:
        out("no Amiga disk carries CHEAD.TLB and CBODY.TLB; set $AMIGA_DISKS")
        return 1
    problems = 0
    for key, where in TITLES.items():
        found = find_executable(where["exe"])
        if found is None:
            out(f"{key}: no /{where['exe']}, so no translation table to "
                f"predict with")
            problems += 1
            continue
        data = found[1]
        colour = data[data_hunk(data) + where["tables"]["colour"]:][:16]
        dos_dir = dos_directory(where["dos_dir"])
        if dos_dir is None:
            out(f"{key}: no DOS {where['dos_dir']} directory; "
                f"set $FR_ARCHIVES")
            problems += 1
            continue
        for volume, files in sorted(art.items()):
            if not _belongs(volume, key):
                continue
            for name in where["art_files"]:
                dos = dos_tiles(dos_dir / name.replace(".TLB", ".DAX"))
                amiga = tiles(files[name], name)
                problems += _compare(out, key, volume, name, amiga, dos,
                                     colour)
    return problems


def _belongs(volume: str, key: str) -> bool:
    """Which title's art disk this is, by the volume label and the path."""
    lowered = volume.lower()
    if key == "curse-of-the-azure-bonds":
        return "curse" in lowered or "azure" in lowered
    return "secret" in lowered or "silver" in lowered


def _compare(out, key, volume, name, amiga, dos, colour) -> int:
    missing_ids = sorted(set(dos) - set(amiga))
    extra_ids = sorted(set(amiga) - set(dos))
    wrong_size, pixels, bad = 0, 0, Counter()
    for art in sorted(set(amiga) & set(dos)):
        ah, aw, arows = amiga[art]
        dh, dw, drows = dos[art]
        if (ah, aw) != (dh, dw):
            wrong_size += 1
            continue
        for r in range(dh):
            for x in range(dw):
                pixels += 1
                want = predicted(drows[r][x], colour)
                if arows[r][x] != want:
                    bad[(drows[r][x], arows[r][x])] += 1
    out(f"{key} {name} ({volume})")
    out(f"  block ids: {len(amiga)} Amiga, {len(dos)} DOS, "
        f"{len(set(amiga) & set(dos))} shared"
        + (f", missing {missing_ids}" if missing_ids else "")
        + (f", extra {extra_ids}" if extra_ids else ""))
    out(f"  pixels: {pixels - sum(bad.values())} of {pixels} are the DOS "
        f"block through the engine's own table"
        + (f", {wrong_size} blocks differ in size" if wrong_size else ""))
    for (dos_value, got), count in sorted(bad.items()):
        out(f"    DOS value {dos_value} -> Amiga {got}, not "
            f"{predicted(dos_value, colour)}: {count} pixels")
    return len(missing_ids) + len(extra_ids) + wrong_size


def report_census(out) -> int:
    """Every specimen's icon fields, against the art that is on the disks."""
    from goldbox import amiga as amiga_mod
    from tools import amigarecords
    art = find_art()
    if not art:
        out("no Amiga disk carries CHEAD.TLB and CBODY.TLB; set $AMIGA_DISKS")
        return 1
    heads, bodies = {}, {}
    for volume, files in art.items():
        for key in TITLES:
            if _belongs(volume, key):
                heads[key] = set(tiles(files["CHEAD.TLB"]))
                bodies[key] = set(tiles(files["CBODY.TLB"]))
    records = []
    import tempfile
    with tempfile.TemporaryDirectory(prefix="amigaicons-") as tmp:
        for path in amigarecords.extract(pathlib.Path(tmp)):
            if path.suffix == ".guy":
                records.append((amiga_mod.read_amiga_guy(path), path.name))
            elif path.name.startswith("CurseA-savgam"):
                for c in amiga_mod.party_in_savegame(path.read_bytes(),
                                                     amiga_mod.CURSE_DELTAS):
                    records.append((c, path.name))
            elif path.name.startswith("Secret1-savgam"):
                shape = amiga_mod.SILVER_BLADES_DELTAS
                for c in amiga_mod.party_in_savegame(path.read_bytes(), shape):
                    records.append((c, path.name))
    if not records:
        out("no Amiga Curse or Silver Blades specimens; set $AMIGA_DISKS")
        return 1
    problems = 0
    out(f"{'name':<18} {'title':<28} {'head':>4} {'body':>4} {'size':>4} "
        f"{'dim':>3}  colours")
    for char, source in records:
        key = char.shape.dos.key
        head, body = char.get("icon_head"), char.get("icon_body")
        size, dim = char.get("size"), char.get("icon_dimension")
        colours = bytes(char.get("icon_colours"))
        name = getattr(char, "name", "") or source
        out(f"{name:<18} {key:<28} {head:>4} {body:>4} {size:>4} {dim:>3}  "
            f"{colours.hex(' ')}")
        for label, value, limit, have in (
                ("icon_head", head, HEAD_OPTIONS, heads.get(key)),
                ("icon_body", body, BODY_OPTIONS, bodies.get(key))):
            if not 0 <= value < limit:
                out(f"    {label} {value} is outside 0-{limit - 1}")
                problems += 1
                continue
            if have is None:
                continue
            wanted = value + (LARGE if size == 2 else 0)
            for art_id in (wanted, wanted + POSE_TWO):
                if art_id not in have:
                    out(f"    {label} {value} at size {size} names block "
                        f"{art_id}, which no library holds")
                    problems += 1
    out(f"{len(records)} records")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tables", action="store_true",
                        help="the three tables the icon routine reads")
    parser.add_argument("--art", action="store_true",
                        help="the Amiga tiles against the DOS blocks")
    parser.add_argument("--census", action="store_true",
                        help="every specimen's four icon fields")
    args = parser.parse_args(argv)
    if not (args.tables or args.art or args.census):
        parser.error("say which measurement: --tables, --art or --census")

    def out(line: str) -> None:
        print(line)

    problems = 0
    if args.tables:
        problems += report_tables(out)
    if args.art:
        problems += report_art(out)
    if args.census:
        problems += report_census(out)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
