"""Item names for the DOS and Amiga ports, read off the player's own game files.

`items.load_item_names` reads the C64's `ITEMNAMES`. This module reads the same
table from a DOS game folder or from Amiga disks and returns the same mapping:
`{name word: text}`, keyed by the value an item record stores in its three
name words, with 0 and empty slots left out. **The name word indexes every
port's table the same way**: id 1 is `Battle Axe` and id 48 (Silver Blades and
Pools of Darkness: 47) is `Mail` on each, and the DOS and Amiga item nodes hold
the C64's three words unchanged (`dos_port` `name1`-`name3`, C64 +1 to +3).

Every table is found from the code that turns an item's name words into text,
so nothing here is a stored offset:

| | form | found from |
|---|---|---|
| DOS, all four | `String[20]` at `DS:base + 21 * id`, in the launcher's data segment (`START.EXE`, Pools of Darkness `GAME.EXE`) | `mov al, es:[di+2Eh] / xor ah, ah / mov dx, 21 / mul dx / mov di, ax / add di, base` |
| Amiga Pool of Radiance | NUL-padded `char[21]` at `base + 21 * id` in a data hunk of `/program` | `move.b $2E(An,Dn), d0 / moveq #21, d1 / jsr mul / lea abs.l, a0 / adda.l d0, a0` |
| Amiga Silver Blades, Pools of Darkness | one pointer an id, to a C string, in the small-data hunk | `move.b $2F(An,Dn.w), Dk / asl.l #2, Dk / lea d16(a4), Am / move.l (Am,Dk.l), -(a7)` |
| Amiga Curse | one block an id of the `TEXT` library `STRINGS.GLB`, block `offset + id` | `move.b $2F(An,Dn.w), Dk / move.w Dk, -(a7) / jsr d16(a4)` to a stub that adds `offset` |

The text is what that port prints: mixed case (`Mage Scroll 3 Spells` where
the C64 has `MAGE SCROLL 3 SPELLS`), with each port's own spellings, and
ISO 8859-1 on the Amiga. `docs/85-item-tables.md` has the per-title evidence.
"""

from __future__ import annotations

import pathlib
import re
import struct

from . import amiga_hunks, exepack, spell_names, stonecracker

#: The highest id a name word can hold.
LAST_ID = 0xFF

#: The DOS table's `String[20]`: the longest name any port's item table holds.
NAME_LIMIT = 20

#: The Amiga Curse text library that holds the names, on disk A.
STRINGS_GLB = "STRINGS.GLB"


class ItemNameError(ValueError):
    """The files hold no item-name table this module can read."""


class StringsNeeded(ItemNameError):
    """The program names items from `STRINGS.GLB`, which was not given."""


def _names(texts: list[str]) -> dict[int, str]:
    """`{id: text}` for a run read from id 1, leaving out empty slots."""
    return {i: text for i, text in enumerate(texts[:LAST_ID], start=1) if text}


def _one(found: dict, what: str) -> list[str]:
    if len(found) != 1:
        raise ItemNameError(
            f"{len(found)} item-name tables are indexed in {what}; "
            f"expected exactly one")
    return next(iter(found.values()))


# --- DOS ---------------------------------------------------------------------

#: `mov al, es:[di+2Eh] / xor ah, ah`, the item's name word (`di` is the item
#: plus the word counter, 3 down to 1), then the fixed-width index of
#: `spell_names._DOS_INDEX`.
_DOS_ITEM_INDEX = re.compile(
    rb"\x26\x8A\x45\x2E\x30\xE4\xBA(.)\x00\xF7\xE2\x8B\xF8\x81\xC7(..)\x1E\x57",
    re.S)


def dos_item_names(image: bytes, entry: int, code) -> dict[int, str]:
    """`{id: name}` out of an expanded DOS launcher image.

    `entry` is the image's entry point (`exepack.load_image`), from which the
    data segment is found; `code` is every blob to search for the indexing
    instruction -- `GAME.OVR` and the image itself. Slot 0 is not a name (it
    overlaps whatever precedes the table), so the run is read from id 1 until
    a slot is not a Pascal string: 255 names in Pool of Radiance and Curse,
    123 in Silver Blades, 125 in Pools of Darkness, each table ending where the
    next begins.
    """
    try:
        ds = exepack.data_segment(image, entry)
    except (ValueError, struct.error) as error:
        raise ItemNameError(f"no data segment: {error}") from None
    found = {}
    for blob in code:
        for m in _DOS_ITEM_INDEX.finditer(blob):
            stride = m.group(1)[0]
            base = ds * 16 + struct.unpack("<H", m.group(2))[0]
            if stride >= 2 and (stride, base) not in found:
                found[(stride, base)] = spell_names._run(
                    lambda i, b=base, s=stride:
                    spell_names._pascal_slot(image, b + s * i, s))
    names = _names(_one(found, "this DOS game"))
    if not names:
        raise ItemNameError("the DOS item-name table is empty")
    return names


def load_dos_item_names(folder: str | pathlib.Path) -> dict[int, str]:
    """`{id: name}` from an installed DOS game folder.

    `folder` is the directory holding the launcher and `GAME.OVR`, or its
    `SAVE` directory. Raises `FileNotFoundError` when neither is there.
    """
    folder = pathlib.Path(folder).expanduser()
    for where in (folder, folder.parent):
        exe = spell_names.dos_executable(where)
        overlay = spell_names._overlay(where) if exe is not None else None
        if exe is not None and overlay is not None:
            break
    else:
        raise FileNotFoundError(f"no DOS launcher and GAME.OVR in {folder}")
    try:
        image, entry = exepack.load_image(exe.read_bytes())
    except ValueError as error:
        raise ItemNameError(f"{exe.name}: {error}") from None
    return dos_item_names(image, entry, (overlay.read_bytes(), image))


# --- Amiga -------------------------------------------------------------------

#: `move.b $2E(An,Xn), Dk`: the name word, the counter running 3 down to 1.
_AMIGA_WORD_2E = rb"[\x10\x12\x14\x16\x18\x1A\x1C\x1E][\x30-\x37].\x2E"

#: Pool of Radiance: the word, then `moveq #stride, d1 / jsr mul(pc) /
#: lea abs.l, a0 / adda.l d0, a0`, the `abs.l` relocated into a data hunk.
_AMIGA_CELL_INDEX = re.compile(
    _AMIGA_WORD_2E + rb"\x72(.)\x4E\xBA..\x41\xF9(....)\xD1\xC0", re.S)

#: `move.b $2F(An,Dn.w), Dk`: the name word, the counter running 0 to 2.
_AMIGA_WORD_2F = (rb"[\x10\x12\x14\x16\x18\x1A\x1C\x1E][\x30-\x37]"
                  rb"[\x00\x10\x20\x30\x40\x50\x60\x70]\x2F")

#: Silver Blades, Pools of Darkness: the word, then `asl.l #2, Dk /
#: lea d16(a4), Am / move.l (Am,Dk.l), -(a7)`.
_AMIGA_POINTER_INDEX = re.compile(
    _AMIGA_WORD_2F + rb"\xE5[\x80-\x87][\x41\x43\x45\x47\x49\x4B\x4D]\xEC(..)"
    rb"\x2F[\x30-\x37][\x08\x18\x28\x38\x48\x58\x68\x78]\x00", re.S)

#: Curse: the word, then `move.w Dk, -(a7) / jsr d16(a4)`, a jump-table slot.
_AMIGA_STUB_CALL = re.compile(_AMIGA_WORD_2F + rb"\x3F[\x00-\x07]\x4E\xAC(..)",
                              re.S)

#: The stub the slot jumps to: `pea d16(a4) / move.w 8(a7), d0 /
#: addi.w #offset, d0 / move.w d0, -(a7) / move.w #library, -(a7)`.
_AMIGA_STRING_STUB = re.compile(
    rb"\x48\x6C..\x30\x2F\x00\x08\x06\x40(..)\x3F\x00\x3F\x3C..", re.S)


def glib_strings(data: bytes) -> list[str]:
    """Every string of an Amiga `GLIB` text library, in block order.

    The header is `GLIB`, a `u32` size, a `u16` block count, a `u16`, the tag
    `TEXT`, then `count + 1` big-endian `u32` offsets; block *i* is
    `[off[i], off[i + 1])`, one string, NUL-terminated or not.
    """
    if data[:4] != b"GLIB" or data[12:16] != b"TEXT":
        raise ItemNameError("not a GLIB text library")
    count = struct.unpack_from(">H", data, 8)[0]
    try:
        offsets = struct.unpack_from(f">{count + 1}I", data, 16)
    except struct.error:
        raise ItemNameError("the GLIB text library's block table is cut short") from None
    if list(offsets) != sorted(offsets) or offsets[-1] > len(data):
        raise ItemNameError("the GLIB text library's block offsets are out of order")
    return [data[offsets[i]:offsets[i + 1]].split(b"\x00", 1)[0].decode("latin1")
            for i in range(count)]


def _string_offsets(program: bytes, hunks, relocs) -> set[int]:
    """Curse's `offset`s: the stubs the name-word calls reach."""
    by_number = {h.number: h for h in hunks}
    datas = [h for h in hunks if h.kind == "DATA" and h.file_offset is not None]
    out = set()
    if len(datas) != 1:
        return out
    data = datas[0]
    for code in (h for h in hunks if h.kind == "CODE" and h.file_offset is not None):
        body = program[code.file_offset:code.file_offset + code.size]
        for m in _AMIGA_STUB_CALL.finditer(body):
            if m.start() % 2:
                continue
            slot = spell_names.SMALL_DATA_BIAS + struct.unpack(">h", m.group(1))[0]
            at = data.file_offset + slot
            if slot < 0 or slot + 6 > data.size or program[at:at + 2] != b"\x4E\xF9":
                continue                            # not `jmp abs.l`
            target = by_number.get(relocs.get((data.number, slot + 2)))
            if target is None or target.kind != "CODE" or target.file_offset is None:
                continue
            stub = target.file_offset + struct.unpack(">I", program[at + 2:at + 6])[0]
            hit = _AMIGA_STRING_STUB.match(program, stub)
            if hit:
                out.add(struct.unpack(">H", hit.group(1))[0])
    return out


def amiga_item_names(program: bytes, strings_glb: bytes | None = None
                     ) -> dict[int, str]:
    """`{id: name}` out of an Amiga Hunk executable, decrunched first if it is
    StoneCracker-crunched.

    Curse keeps its names in `STRINGS.GLB` rather than the program, so it
    needs `strings_glb` as well: block `offset + id`, the run stopping at the
    last block or id 255. The pointer form stops at the first slot that is not
    a pointer to a printable string of at most `NAME_LIMIT` characters: Silver
    Blades' run of 123 ends on a slot that is not a pointer, and Pools of
    Darkness' on the death message that follows its 137th name.
    """
    try:
        program = stonecracker.as_loaded(program)
    except stonecracker.StoneCrackerError as error:
        raise ItemNameError(
            f"the program is {stonecracker.NAME}-crunched and does not "
            f"decrunch: {error}") from None
    try:
        hunks, relocs = amiga_hunks.parse(program)
    except (ValueError, IndexError, struct.error) as error:
        raise ItemNameError(f"not a Hunk executable: {error}") from None
    by_number = {h.number: h for h in hunks}
    found: dict[tuple, list[str]] = {}
    codes = [h for h in hunks if h.kind == "CODE" and h.file_offset is not None]

    for code in codes:
        body = program[code.file_offset:code.file_offset + code.size]
        for m in _AMIGA_CELL_INDEX.finditer(body):
            target = by_number.get(relocs.get((code.number, m.start(2))))
            if target is None or target.file_offset is None:
                continue
            stride = m.group(1)[0]
            base = struct.unpack(">I", m.group(2))[0]
            key = ("cells", target.number, base, stride)
            if m.start() % 2 or stride < 2 or key in found:
                continue
            cells = program[target.file_offset:target.file_offset + target.size]
            found[key] = spell_names._run(
                lambda i, c=cells, b=base, s=stride: spell_names._c_slot(c, b + s * i, s))

    datas = [h for h in hunks if h.kind == "DATA" and h.file_offset is not None]
    if len(datas) == 1:
        data = datas[0]

        def pointer(slot_at: int) -> str | None:
            hunk = by_number.get(relocs.get((data.number, slot_at)))
            if hunk is None or hunk.file_offset is None or slot_at + 4 > data.size:
                return None
            at = data.file_offset + slot_at
            value = struct.unpack(">I", program[at:at + 4])[0]
            if value >= hunk.size:
                return None
            return spell_names._c_string(program, hunk.file_offset + value,
                                         NAME_LIMIT + 1)

        for code in codes:
            body = program[code.file_offset:code.file_offset + code.size]
            for m in _AMIGA_POINTER_INDEX.finditer(body):
                base = spell_names.SMALL_DATA_BIAS + struct.unpack(">h", m.group(1))[0]
                key = ("pointers", data.number, base)
                if m.start() % 2 or base < 0 or key in found:
                    continue
                found[key] = spell_names._run(lambda i, b=base: pointer(b + 4 * i))

    offsets = _string_offsets(program, hunks, relocs)
    if offsets and not found:
        if strings_glb is None:
            raise StringsNeeded(f"this program names items from {STRINGS_GLB}, "
                                f"which was not given")
        strings = glib_strings(strings_glb)
        for offset in offsets:
            found[("strings", offset)] = strings[offset + 1:offset + 1 + LAST_ID]

    names = _names(_one(found, "this Amiga program"))
    if not names:
        raise ItemNameError("the Amiga item-name table is empty")
    return names


def _amiga_file(where, name: str) -> bytes | None:
    """The first file called `name`, in any directory, on the disks."""
    for disk in spell_names._amiga_disks(where):
        try:
            entries = list(disk.walk())
        except Exception:                           # not a readable disk
            continue
        for path, _entry in entries:
            if path.rsplit("/", 1)[-1].lower() == name.lower():
                return disk.read_file(path)
    return None


def load_amiga_item_names(where, game) -> dict[int, str]:
    """`{id: name}` off the title's Amiga disks.

    `where` is what `spell_names.amiga_program` takes: a folder of `.adf`
    images, one image path, or an iterable of paths, image bytes or
    `AmigaDisk` objects. Raises `FileNotFoundError` when the program, or the
    `STRINGS.GLB` it needs, is not there.
    """
    if not isinstance(where, (str, pathlib.Path, list, tuple)):
        where = list(where)                         # read twice below
    program = spell_names.amiga_program(where, game)
    try:
        return amiga_item_names(program)
    except StringsNeeded:
        strings = _amiga_file(where, STRINGS_GLB)
        if strings is None:
            raise FileNotFoundError(f"no Amiga {STRINGS_GLB}") from None
        return amiga_item_names(program, strings)


def item_names(game, platform: str, where) -> dict[int, str]:
    """`{name word: text}` for a title's DOS game folder (`platform` "dos")
    or Amiga disks ("amiga"); the C64's is `items.load_item_names`."""
    if platform == "dos":
        return load_dos_item_names(where)
    if platform == "amiga":
        return load_amiga_item_names(where, game)
    raise ValueError(f"{platform!r} is not dos or amiga")
