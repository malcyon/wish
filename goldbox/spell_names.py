"""Spell names for every title on every platform it shipped on, read off the
player's own game files.

`spells.load_spell_names` reads the C64's tables. This module adds the DOS and
Amiga ports and one entry point, `spell_names(game, platform, where)`, that
answers `{spell id: name}` for any of them. Nothing is stored here: every
table is found at run time from the instruction that indexes it, so a build
whose data sits elsewhere still reads, and a file that holds no such table
raises `SpellNameError` rather than answering from the wrong bytes.

| | DOS | Amiga |
|---|---|---|
| file | `START.EXE` (Pools of Darkness: `GAME.EXE`), EXEPACK-packed | `/program`, `/Curse`, `/Secret`, `/Pools of Darkness`, decrunched first if StoneCracker-crunched |
| indexed by | `mov dx, stride / mul dx / mov di, ax / add di, base` in `GAME.OVR` | Pool of Radiance: `moveq #stride, d1 / jsr mul / lea abs.l, a0 / adda.l d0, a0`; the others: `asl.l #2, d0 / lea d16(a4), a0 / move.l (a0, d0.l), -(a7)` |
| form | `String[stride - 1]` at `DS:base + stride * id` | Pool of Radiance: NUL-padded `char[41]` at `base + 41 * id`; the others: a pointer an id, to a C string, ISO 8859-1 |

**The id is the index on every port**: slot 0 of each table is the id-0 slot
no spell uses, so no port numbers its spells differently from the C64. What
differs is the text, and only in three ways: case (the C64 and Amiga Silver
Blades are upper case), abbreviation (Amiga Pools of Darkness' `Prot. From
Evil, 10' Radius`), and what the non-spell ids hold -- empty, `spell N`, an
item that casts it, or (Amiga Silver Blades) the engine's own internal name.
`spells.SpellTable.not_a_spell` says which ids those are. A translated build
names its spells in its own language under the same ids: the German Amiga
Pools of Darkness is read as it stands, umlauts included.

`docs/86-spell-table.md` has the per-title offsets, the counts and the
evidence.
"""

from __future__ import annotations

import pathlib
import re
import struct
from collections.abc import Iterable

from . import amiga_hunks, exepack, spells, stonecracker, titles

PLATFORMS = ("c64", "dos", "amiga")

#: The Amiga program file that holds each title's names, by title key.
AMIGA_PROGRAMS = {
    "pool-of-radiance": "program",
    "curse-of-the-azure-bonds": "Curse",
    "secret-of-the-silver-blades": "Secret",
    "pools-of-darkness": "Pools of Darkness",
}

#: The DOS executables that may carry the table, tried in this order.
DOS_EXECUTABLES = ("START.EXE", "GAME.EXE")

#: SAS/Lattice's small-data base: `a4` points this far into the data hunk.
SMALL_DATA_BIAS = 0x7FFE

#: Longest name accepted through an Amiga pointer, NUL included.
_POINTER_LIMIT = 64


class SpellNameError(ValueError):
    """The file holds no spell-name table this module can read for the title."""


def _table(game) -> spells.SpellTable:
    """The title's `SpellTable`, never Pool of Radiance's by default."""
    if isinstance(game, spells.SpellTable):
        return game
    key = getattr(game, "key", game)
    table = spells.BY_KEY.get(key)
    if table is None:
        raise SpellNameError(f"{game!r} is not a title with spells")
    return table


def _printable(text: bytes) -> bool:
    return all(0x20 <= c < 0x7F for c in text)


def _choose(candidates: dict, table: spells.SpellTable) -> list[str]:
    """The one candidate run that is this title's spell names.

    A run qualifies when it reaches the title's last spell and names every id
    that `spells.spell_group` calls a spell. Of those, one that **stops** at
    the last spell wins; failing that, a single qualifier does. Measured on
    every build here: the names stop at the last spell on all four DOS builds
    and on Amiga Pool of Radiance, Curse and Silver Blades, and Amiga Pools of
    Darkness' pointers run on into eleven item names but are the only run
    with no empty spell id. A tie raises rather than guessing.
    """
    def names_every_spell(names):
        return all(names[i - 1] for i in range(1, table.last_spell + 1)
                   if spells.spell_group(i, table))
    qualified = [names for names in candidates.values()
                 if len(names) >= table.last_spell and names_every_spell(names)]
    exact = [names for names in qualified if len(names) == table.last_spell]
    chosen = exact if exact else qualified
    if len(chosen) != 1:
        raise SpellNameError(
            f"{len(chosen)} string tables could be {table.title}'s "
            f"{table.last_spell} spell names; expected exactly one")
    return chosen[0][:table.last_spell]


# --- DOS ---------------------------------------------------------------------

#: `mov dx, stride / mul dx / mov di, ax / add di, base / push ds / push di`:
#: how every DOS engine indexes a table of fixed-width Pascal strings.
_DOS_INDEX = re.compile(rb"\xBA(.)\x00\xF7\xE2\x8B\xF8\x81\xC7(..)\x1E\x57", re.S)


def _pascal_slot(blob: bytes, at: int, stride: int) -> str | None:
    """The `String[stride - 1]` at `at`, or None if the slot is not one.

    A slot is a length byte below `stride`, that many printable characters,
    and zeros to the end of the stride.
    """
    if at < 0 or at + stride > len(blob):
        return None
    n = blob[at]
    text = blob[at + 1:at + 1 + n]
    if n >= stride or not _printable(text) or any(blob[at + 1 + n:at + stride]):
        return None
    return text.decode("latin1")


def _run(slot, first: int = 1) -> list[str]:
    """Consecutive readable slots from `first` up, until one is not."""
    out = []
    index = first
    while (text := slot(index)) is not None:
        out.append(text)
        index += 1
    return out


def dos_spell_names(image: bytes, entry: int, code: Iterable[bytes],
                    game) -> dict[int, str]:
    """`{id: name}` out of an expanded DOS image.

    `entry` is the image's entry point (`exepack.load_image`), from which the
    data segment is found; `code` is every blob to search for the indexing
    instruction -- `GAME.OVR` and the image itself. `_choose` says which of
    the tables so indexed is the spell names: on all four titles they run
    from id 1 to the last spell and the next slot is the start of the
    class-and-level table that follows.
    """
    table = _table(game)
    try:
        ds = exepack.data_segment(image, entry)
    except (ValueError, struct.error) as error:
        raise SpellNameError(f"no data segment: {error}") from None
    found = {}
    for blob in code:
        for m in _DOS_INDEX.finditer(blob):
            stride = m.group(1)[0]
            base = ds * 16 + struct.unpack("<H", m.group(2))[0]
            if (stride, base) in found or stride < 2:
                continue
            found[(stride, base)] = _run(
                lambda i, b=base, s=stride: _pascal_slot(image, b + s * i, s))
    names = _choose(found, table)
    return {i: text for i, text in enumerate(names, start=1) if text}


def dos_executable(folder: str | pathlib.Path) -> pathlib.Path | None:
    """The launcher in a DOS game folder that holds the tables, or None."""
    folder = pathlib.Path(folder)
    try:
        held = {p.name.upper(): p for p in folder.iterdir() if p.is_file()}
    except OSError:
        return None
    for name in DOS_EXECUTABLES:
        if name in held:
            return held[name]
    return None


def _overlay(folder: pathlib.Path) -> pathlib.Path | None:
    for p in folder.iterdir():
        if p.is_file() and p.name.upper() == "GAME.OVR":
            return p
    return None


def load_dos_spell_names(folder: str | pathlib.Path, game) -> dict[int, str]:
    """`{id: name}` from an installed DOS game folder.

    `folder` is the directory holding the launcher and `GAME.OVR`, or its
    `SAVE` directory. Raises `FileNotFoundError` when neither is there.
    """
    folder = pathlib.Path(folder).expanduser()
    for where in (folder, folder.parent):
        exe = dos_executable(where)
        overlay = _overlay(where) if exe is not None else None
        if exe is not None and overlay is not None:
            break
    else:
        raise FileNotFoundError(f"no DOS launcher and GAME.OVR in {folder}")
    try:
        image, entry = exepack.load_image(exe.read_bytes())
    except ValueError as error:
        raise SpellNameError(f"{exe.name}: {error}") from None
    return dos_spell_names(image, entry, (overlay.read_bytes(), image), game)


def find_dos_folders(root: str | pathlib.Path, game) -> list[pathlib.Path]:
    """Every installed DOS game folder under `root` that holds `game`.

    Recognised by `titles.dos_folder_title`, the same test the save browser
    uses, and only where a launcher and `GAME.OVR` sit beside each other.
    """
    key = _table(game).key
    root = pathlib.Path(root).expanduser()
    out = []
    try:
        overlays = sorted(root.rglob("*"))
    except OSError:
        return []
    for path in overlays:
        if path.name.upper() != "GAME.OVR" or not path.is_file():
            continue
        folder = path.parent
        if (dos_executable(folder) is not None
                and titles.dos_folder_title(folder) == key):
            out.append(folder)
    return out


# --- Amiga -------------------------------------------------------------------

#: `asl.l #2, d0 / lea d16(a4), a0 / move.l (a0, d0.l), -(a7)`.
_AMIGA_POINTER_INDEX = re.compile(rb"\xE5\x80\x41\xEC(..)\x2F\x30\x08\x00", re.S)

#: `moveq #stride, d1 / jsr d16(pc) / lea abs.l, a0 / adda.l d0, a0`: the
#: multiply is a library call, and the `abs.l` carries a relocation.
_AMIGA_STRIDE_INDEX = re.compile(rb"\x72(.)\x4E\xBA..\x41\xF9(....)\xD1\xC0", re.S)


def _amiga_text(text: bytes) -> bool:
    """Printable ISO 8859-1, the Amiga's character set, in which the German
    Pools of Darkness writes its umlauts and sharp s (`0xC4`-`0xFC`)."""
    return all(0x20 <= c < 0x7F or 0xA0 <= c for c in text)


def _c_slot(data: bytes, at: int, stride: int) -> str | None:
    """The NUL-terminated, NUL-padded `char[stride]` at `at`, or None."""
    if at < 0 or at + stride > len(data):
        return None
    cell = data[at:at + stride]
    end = cell.find(b"\x00")
    if end < 0 or not _amiga_text(cell[:end]) or any(cell[end:]):
        return None
    return cell[:end].decode("latin1")


def _c_string(data: bytes, at: int, limit: int) -> str | None:
    end = data.find(b"\x00", at, at + limit)
    if at < 0 or end < 0 or not _amiga_text(data[at:end]):
        return None
    return data[at:end].decode("latin1")


def amiga_spell_names(program: bytes, game) -> dict[int, str]:
    """`{id: name}` out of an Amiga Hunk executable, decrunched first if
    it is StoneCracker-crunched (`stonecracker.as_loaded`).

    Two forms, each found from the code that indexes it. Pool of Radiance
    keeps fixed-width `char[41]` cells in a data hunk and reaches them through
    a relocated `lea abs.l`; the three later titles keep one pointer an id in
    their small-data hunk and reach it as `d16(a4)`. `_choose` says which of
    the tables so indexed is the spell names; only ids up to the last spell
    are returned.
    """
    table = _table(game)
    try:
        program = stonecracker.as_loaded(program)
    except stonecracker.StoneCrackerError as error:
        raise SpellNameError(
            f"the {table.title} program is {stonecracker.NAME}-crunched and "
            f"does not decrunch: {error}") from None
    try:
        hunks, relocs = amiga_hunks.parse(program)
    except (ValueError, IndexError, struct.error) as error:
        raise SpellNameError(f"not a Hunk executable: {error}") from None
    by_number = {h.number: h for h in hunks}
    candidates: dict[tuple, list[str]] = {}

    for code in (h for h in hunks if h.kind == "CODE" and h.file_offset is not None):
        body = program[code.file_offset:code.file_offset + code.size]
        for m in _AMIGA_STRIDE_INDEX.finditer(body):
            target = relocs.get((code.number, m.start(2)))
            data = by_number.get(target)
            if data is None or data.file_offset is None:
                continue
            stride = m.group(1)[0]
            base = struct.unpack(">I", m.group(2))[0]
            key = ("cells", target, base, stride)
            if key in candidates or stride < 2:
                continue
            cells = program[data.file_offset:data.file_offset + data.size]
            candidates[key] = _run(
                lambda i, c=cells, b=base, s=stride: _c_slot(c, b + s * i, s))

    datas = [h for h in hunks if h.kind == "DATA" and h.file_offset is not None]
    if len(datas) == 1:
        data = datas[0]

        def pointer(slot_at: int) -> str | None:
            target = relocs.get((data.number, slot_at))
            hunk = by_number.get(target)
            if hunk is None or hunk.file_offset is None or slot_at + 4 > data.size:
                return None
            at = data.file_offset + slot_at
            value = struct.unpack(">I", program[at:at + 4])[0]
            if value >= hunk.size:
                return None
            return _c_string(program, hunk.file_offset + value, _POINTER_LIMIT)

        for code in (h for h in hunks if h.kind == "CODE" and h.file_offset is not None):
            body = program[code.file_offset:code.file_offset + code.size]
            for m in _AMIGA_POINTER_INDEX.finditer(body):
                if m.start() % 2:
                    continue
                d16 = struct.unpack(">h", m.group(1))[0]
                base = SMALL_DATA_BIAS + d16
                key = ("pointers", data.number, base)
                if key in candidates or base < 0:
                    continue
                candidates[key] = _run(lambda i, b=base: pointer(b + 4 * i))

    names = _choose(candidates, table)
    return {i: text for i, text in enumerate(names, start=1) if text}


def _amiga_disks(where):
    """AmigaDisk objects for whatever `load_amiga_spell_names` was given."""
    from .amiga_adf import AmigaDisk

    if isinstance(where, (str, pathlib.Path)):
        path = pathlib.Path(where).expanduser()
        if path.is_dir():
            where = sorted(p for p in path.iterdir()
                           if p.is_file() and p.suffix.lower() == ".adf")
        else:
            where = [path]
    for item in where:
        try:
            if isinstance(item, AmigaDisk):
                yield item
            elif isinstance(item, (bytes, bytearray)):
                yield AmigaDisk(bytearray(item))
            else:
                yield AmigaDisk.open(item)
        except Exception:                           # not a readable disk
            continue


def amiga_program(where, game) -> bytes:
    """The title's Amiga program file, off the first disk that carries it,
    decrunched if it is StoneCracker-crunched, so every reader gets the
    program the game runs.

    `where` is a folder of `.adf` images, one image path, or an iterable of
    paths, image bytes or `AmigaDisk` objects. Raises `FileNotFoundError`,
    and `stonecracker.StoneCrackerError` for a crunched program that does not
    decrunch.
    """
    name = AMIGA_PROGRAMS[_table(game).key].lower()
    for disk in _amiga_disks(where):
        try:
            entries = list(disk.walk())
        except Exception:
            continue
        for path, _entry in entries:
            if path.strip("/").lower() == name:
                return stonecracker.as_loaded(disk.read_file(path))
    raise FileNotFoundError(f"no Amiga /{AMIGA_PROGRAMS[_table(game).key]}")


def load_amiga_spell_names(where, game) -> dict[int, str]:
    """`{id: name}` off the title's Amiga disks; see `amiga_program`."""
    return amiga_spell_names(amiga_program(where, game), game)


# --- every port --------------------------------------------------------------

def load_c64_spell_names(where, game) -> dict[int, str]:
    """`{id: name}` off a C64 disk image, or the first image in a folder
    that carries the title's table, ids 1 to the last spell.

    A thin wrapper on `spells.load_spell_names`, which also returns the
    message tail past the last spell. Raises `SpellNameError` for a title
    with no C64 port and `FileNotFoundError` when no image has the table.
    """
    table = _table(game)
    if not table.file:
        raise SpellNameError(f"{table.title} has no C64 port")
    path = pathlib.Path(where).expanduser() if isinstance(where, (str, pathlib.Path)) else None
    images = ([where] if path is None else
              sorted(p for p in path.iterdir() if p.suffix.lower() == ".d64")
              if path.is_dir() else [path])
    for image in images:
        try:
            names = spells.load_spell_names(
                str(image) if isinstance(image, pathlib.Path) else image, table)
        except Exception:                           # not the disk with the table
            continue
        names = {i: t for i, t in names.items() if 1 <= i <= table.last_spell}
        if names:
            return names
    raise FileNotFoundError(f"no {table.title} C64 disk with {table.file.decode()}")


def spell_names(game, platform: str, where) -> dict[int, str]:
    """`{spell id: name}` for a title on one platform.

    `where` is what that platform's loader takes: a C64 disk image or folder
    of them, a DOS game folder (or its `SAVE`), or Amiga disks. Raises
    `FileNotFoundError` when the files are not there and `SpellNameError`
    when they hold no table for the title.
    """
    loaders = {"c64": load_c64_spell_names, "dos": load_dos_spell_names,
               "amiga": load_amiga_spell_names}
    if platform not in loaders:
        raise ValueError(f"{platform!r} is not one of {', '.join(PLATFORMS)}")
    return loaders[platform](where, game)
