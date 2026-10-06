"""Item names off DOS game folders and Amiga disks, `goldbox/item_names.py`.

The synthetic tests build each table form from its documented layout -- a DOS
data segment of `String[20]` slots and the `GAME.OVR` code that indexes it with
an item's name word, and the three Amiga forms -- so CI checks the parsing with
no game data. The disk-backed tests read the player's own games, skip where
the registry has none, and check every port names the same item under the same
id; where two ports' text differs the ids are listed here as numbers, so a
table read one slot out fails rather than passes.

No game bytes are committed: every name is read at run time.
"""

from __future__ import annotations

import hashlib
import pathlib
import struct

import pytest

from goldbox import amiga_hunks, item_names, spell_names
from tests.support.hunks import hunk_file

TITLES = ("pool-of-radiance", "curse-of-the-azure-bonds",
          "secret-of-the-silver-blades", "pools-of-darkness")


# --- DOS -----------------------------------------------------------------------

DS = 0x10                       # the data segment's paragraph in the image


def _pascal(text: str, stride: int = 21) -> bytes:
    raw = text.encode()
    return bytes((len(raw),)) + raw + bytes(stride - 1 - len(raw))


def _dos_index(base: int, stride: int = 21, word_load: bool = True) -> bytes:
    """`mov al, es:[di+2Eh] / xor ah, ah`, then `mov dx, stride / mul dx /
    mov di, ax / add di, base / push ds / push di`."""
    load = b"\x26\x8A\x45\x2E\x30\xE4" if word_load else b"\x8A\x46\xFE\x30\xE4"
    return (load + b"\xBA" + bytes((stride, 0)) + b"\xF7\xE2\x8B\xF8\x81\xC7"
            + struct.pack("<H", base) + b"\x1E\x57")


def _dos_image(tables: dict[int, list[str]]) -> tuple[bytes, int]:
    """An image whose entry far-calls an initialiser that loads `DS`, and whose
    data segment holds each `{base: names}` table from id 1, slot 0 being the
    tail of whatever precedes it, followed by a byte that ends the run."""
    image = bytearray(0x800)
    image[0:5] = b"\x9A" + struct.pack("<HH", 0x20, 0)         # call far 0000:0020
    image[0x20:0x25] = b"\xBA" + struct.pack("<H", DS) + b"\x8E\xDA"
    for base, names in tables.items():
        at = DS * 16 + base
        image[at:at + 3] = b"ed\x00"                            # not a slot
        at += 21
        for text in names:
            image[at:at + 21] = _pascal(text)
            at += 21
        image[at:at + 2] = b"\x00\x01"                          # not a slot
    return bytes(image), 0


def test_dos_names_are_keyed_from_id_one_and_leave_out_empty_slots():
    image, entry = _dos_image({0x40: ["Battle Axe", "", "Mail"]})
    names = item_names.dos_item_names(image, entry, [_dos_index(0x40)])
    assert names == {1: "Battle Axe", 3: "Mail"}


def test_dos_table_indexed_without_an_item_name_word_is_not_taken():
    image, entry = _dos_image({0x40: ["Battle Axe", "Mail"]})
    with pytest.raises(item_names.ItemNameError):
        item_names.dos_item_names(image, entry, [_dos_index(0x40, word_load=False)])


def test_dos_two_item_name_tables_raise_rather_than_guess():
    image, entry = _dos_image({0x40: ["Battle Axe"], 0x200: ["Club"]})
    with pytest.raises(item_names.ItemNameError):
        item_names.dos_item_names(image, entry, [_dos_index(0x40), _dos_index(0x200)])


def test_dos_folder_without_a_launcher_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        item_names.load_dos_item_names(tmp_path)


# --- Amiga ---------------------------------------------------------------------

def _cstrings(texts: list[str]) -> tuple[bytes, list[int]]:
    blob, offsets = bytearray(), []
    for text in texts:
        offsets.append(len(blob))
        blob += text.encode("latin1") + b"\x00"
    return bytes(blob + bytes(-len(blob) % 4)), offsets


def _pointer_program(texts: list[str], array_at: int = 0x10) -> bytes:
    """Silver Blades' form: `move.b $2F(a2,d0.w), d1 / asl.l #2, d1 /
    lea d16(a4), a0 / move.l (a0,d1.l), -(a7)`, then the strings; a small-data
    hunk with one relocated pointer an id from `array_at`. `texts[0]` is id 0."""
    d16 = array_at - spell_names.SMALL_DATA_BIAS
    code = (b"\x12\x32\x00\x2F\xE5\x81\x41\xEC" + struct.pack(">h", d16)
            + b"\x2F\x30\x18\x00\x4E\x75")
    strings, offsets = _cstrings(texts)
    data = bytearray(array_at + 4 * len(texts) + 4)
    for i, off in enumerate(offsets):
        struct.pack_into(">I", data, array_at + 4 * i, len(code) + off)
    data[-4:] = b"\xFF\xFF\xFF\xFF"
    relocs = [(0, [array_at + 4 * i for i in range(len(texts))])]
    return hunk_file([(amiga_hunks.HUNK_CODE, code + strings, []),
                      (amiga_hunks.HUNK_DATA, bytes(data), relocs)])


def test_amiga_pointer_form_reads_from_id_one():
    program = _pointer_program(["", "Battle Axe", "", "Mail"])
    assert item_names.amiga_item_names(program) == {1: "Battle Axe", 3: "Mail"}


def test_amiga_pointer_run_stops_at_text_longer_than_a_name():
    program = _pointer_program(["", "Battle Axe", "Mail",
                                "who is looking very old", "Club"])
    assert item_names.amiga_item_names(program) == {1: "Battle Axe", 2: "Mail"}


def _cell_program(texts: list[str], base: int = 0x20) -> bytes:
    """Pool of Radiance's form: `move.b $2E(a3,d1.l), d0 / moveq #21, d1 /
    jsr d16(pc) / lea abs.l, a0 / adda.l d0, a0`, the `abs.l` relocated into a
    data hunk of NUL-padded `char[21]` from id 0."""
    code = (b"\x10\x33\x18\x2E\x72\x15\x4E\xBA\x00\x00\x41\xF9"
            + struct.pack(">I", base) + b"\xD1\xC0\x4E\x75")
    data = bytearray(base + 21 * (len(texts) + 1))
    for i, text in enumerate(texts):
        data[base + 21 * i:base + 21 * i + len(text)] = text.encode()
    data[base + 21 * len(texts) + 1] = 7                        # not a cell
    data += bytes(-len(data) % 4)
    return hunk_file([(amiga_hunks.HUNK_CODE, code, [(1, [12])]),
                      (amiga_hunks.HUNK_DATA, bytes(data), [])])


def test_amiga_cell_form_reads_fixed_width_names():
    program = _cell_program(["", "Battle Axe", "Hand Axe"])
    assert item_names.amiga_item_names(program) == {1: "Battle Axe", 2: "Hand Axe"}


def _glib(texts: list[str]) -> bytes:
    """A `GLIB` text library, one string a block."""
    blocks = [t.encode("latin1") for t in texts]
    table = 16 + 4 * (len(blocks) + 1)
    offsets, at = [], table
    for b in blocks:
        offsets.append(at)
        at += len(b)
    offsets.append(at)
    head = (b"GLIB" + struct.pack(">IHH", at, len(blocks), 0) + b"TEXT"
            + b"".join(struct.pack(">I", o) for o in offsets))
    return head + b"".join(blocks)


def _strings_program(offset: int, slot: int = 0x10) -> bytes:
    """Curse's form: `move.b $2F(a2,d0.w), d1 / move.w d1, -(a7) /
    jsr d16(a4)` into a `jmp abs.l` slot, whose stub adds `offset` to the
    word and asks for that block."""
    call = (b"\x12\x32\x00\x2F\x3F\x01\x4E\xAC"
            + struct.pack(">h", slot - spell_names.SMALL_DATA_BIAS) + b"\x4E\x75")
    stub_at = len(call)
    stub = (b"\x48\x6C\x00\x00\x30\x2F\x00\x08\x06\x40" + struct.pack(">H", offset)
            + b"\x3F\x00\x3F\x3C\x00\x13\x4E\x75")
    code = call + stub
    code += bytes(-len(code) % 4)
    data = bytearray(slot + 8)
    data[slot:slot + 6] = b"\x4E\xF9" + struct.pack(">I", stub_at)
    return hunk_file([(amiga_hunks.HUNK_CODE, code, []),
                      (amiga_hunks.HUNK_DATA, bytes(data), [(0, [slot + 2])])])


def test_amiga_strings_form_reads_blocks_past_the_stubs_offset():
    glb = _glib(["Cleric", "Dwarf", "Gone", "Battle Axe", "Hand Axe"])
    names = item_names.amiga_item_names(_strings_program(2), glb)
    assert names == {1: "Battle Axe", 2: "Hand Axe"}


def test_amiga_strings_form_without_the_library_raises():
    with pytest.raises(item_names.StringsNeeded):
        item_names.amiga_item_names(_strings_program(2))


def test_a_file_that_is_not_a_text_library_raises():
    with pytest.raises(item_names.ItemNameError):
        item_names.glib_strings(b"GLIB\x00\x00\x00\x10\x00\x00\x00\x00DATA")


def test_a_program_with_no_item_name_code_raises():
    program = hunk_file([(amiga_hunks.HUNK_CODE, b"\x4E\x75\x00\x00", []),
                         (amiga_hunks.HUNK_DATA, bytes(8), [])])
    with pytest.raises(item_names.ItemNameError):
        item_names.amiga_item_names(program)


# --- the player's own games ------------------------------------------------------

#: Ids both DOS and C64 name, where the text differs beyond case: spellings and
#: abbreviations of the same word (`QUARREL(S)` / `Quarrel`, `AC2` / `AC 2`,
#: `MU SCROLL` / `Magic User Scroll`), and Silver Blades' 77, which DOS spends on
#: its joined scroll's `Bundle of` where the C64 has `DISRUPTION`.
DOS_VS_C64 = {
    "pool-of-radiance": {28, 60, 61, 145, 146, 147, 149, 153, 154, 171, 183,
                         197, 209, 220, 221, 222, 223, 237, 240, 241},
    "curse-of-the-azure-bonds": {28, 60, 61, 84, 146, 147, 149, 153, 154, 171,
                                 175, 183, 197, 208, 213, 220, 221, 222, 223,
                                 224, 237, 240, 241},
    "secret-of-the-silver-blades": {63, 77, 84, 105},
}

#: The highest id each DOS table reaches: each ends where the next table begins.
DOS_LAST = {"pool-of-radiance": 255, "curse-of-the-azure-bonds": 255,
            "secret-of-the-silver-blades": 123, "pools-of-darkness": 125}

#: Amiga ids whose text is not DOS's: Curse's `x` where DOS has an empty slot,
#: Pools of Darkness' `blinking` and the twelve names past DOS's last id.
AMIGA_VS_DOS = {
    "pool-of-radiance": set(),
    "curse-of-the-azure-bonds": {62, 63, 144},
    "secret-of-the-silver-blades": set(),
    "pools-of-darkness": {124, *range(126, 138)},
}


def _differ(a: dict[int, str], b: dict[int, str]) -> set[int]:
    return {i for i in a.keys() & b.keys() if a[i].upper() != b[i].upper()}


@pytest.fixture(scope="module")
def dos_names():
    from automap import gamedisks
    out = {}
    root = gamedisks.find("dos-archives")
    if root is None:
        return out
    for key in TITLES:
        folders = spell_names.find_dos_folders(root, key)
        if folders:
            out[key] = item_names.load_dos_item_names(folders[0])
    return out


@pytest.fixture(scope="module")
def c64_names():
    from automap import gamedisks
    from goldbox import c64_port, items
    out = {}
    for key in TITLES[:3]:
        where = gamedisks.find(key)
        if where is None:
            continue
        game = c64_port.by_key(key)
        for disk in sorted(pathlib.Path(where).glob(game.disk_glob)):
            try:
                names = items.load_item_names(str(disk), game)
            except Exception:                       # not the disk with ITEMNAMES
                continue
            if names:
                out[key] = names
                break
    return out


@pytest.fixture(scope="module")
def amiga_disks():
    """`{title: {program sha1: [AmigaDisk, ...]}}`: every distinct Amiga
    program, with the disks of the set it came from."""
    from automap import gamedisks
    from goldbox.amiga_adf import AmigaDisk
    from tools.amiga import amigasaves
    out: dict[str, dict[str, list]] = {}
    if not gamedisks.candidates("amiga"):
        return out
    by_folder: dict[str, list] = {}
    programs = []
    for label, data in amigasaves.images():
        try:
            disk = AmigaDisk(bytearray(data))
            entries = list(disk.walk())
        except Exception:
            continue
        folder = label.rsplit("/", 1)[0]
        by_folder.setdefault(folder, []).append(disk)
        for key in TITLES:
            name = spell_names.AMIGA_PROGRAMS[key].lower()
            for path, _entry in entries:
                if path.strip("/").lower() == name:
                    programs.append((key, disk.read_file(path), folder, disk))
    for key, program, folder, disk in programs:
        sha = hashlib.sha1(program).hexdigest()
        out.setdefault(key, {}).setdefault(
            sha, [disk] + [d for d in by_folder[folder] if d is not disk])
    return out


@pytest.mark.parametrize("key", TITLES)
def test_dos_names_run_to_the_tables_end_and_agree_with_the_c64_id_for_id(
        dos_names, c64_names, key):
    if key not in dos_names:
        pytest.skip(f"no DOS {key} under the archives")
    names = dos_names[key]
    assert max(names) == DOS_LAST[key]
    assert names[1] == "Battle Axe"
    if key in c64_names:
        assert names.keys() <= c64_names[key].keys()
        assert _differ(names, c64_names[key]) == DOS_VS_C64[key]


@pytest.mark.parametrize("key", TITLES)
def test_amiga_names_agree_with_dos_id_for_id(amiga_disks, dos_names, key):
    from goldbox import stonecracker
    if key not in amiga_disks:
        pytest.skip(f"no Amiga {key} disks")
    english = 0
    for disks in amiga_disks[key].values():
        names = item_names.load_amiga_item_names(disks, key)
        assert len(names) >= 117
        if stonecracker.is_crunched(disks[0].read_file(
                "/" + spell_names.AMIGA_PROGRAMS[key])):
            continue                    # the German build names its own items
        english += 1
        if key in dos_names:
            dos = dos_names[key]
            assert {i for i in names if dos.get(i) != names[i]} == AMIGA_VS_DOS[key]
    assert english >= 1


def _paines_first_left_behind(names: dict[int, str]) -> str:
    from gamedata import specimen

    from goldbox import dos_codec, items
    party = dos_codec.read_party(specimen("ssb-wish4-joined-l122"), "A")
    (overflow,) = dos_codec.pack_overflow(party, "amiga")
    paine = overflow.names.index("PAINE")
    return items.Item(overflow.items[paine][0], names).name


def test_specimen_l_item_is_named_from_the_dos_folder(dos_names):
    key = "secret-of-the-silver-blades"
    if key not in dos_names:
        pytest.skip(f"no DOS {key} under the archives")
    assert _paines_first_left_behind(dos_names[key]).upper() == "MAGE SCROLL 3 SPELLS"


def test_specimen_l_item_is_named_from_the_amiga_disks(amiga_disks):
    key = "secret-of-the-silver-blades"
    if key not in amiga_disks:
        pytest.skip(f"no Amiga {key} disks")
    for disks in amiga_disks[key].values():
        names = item_names.item_names(key, "amiga", disks)
        assert _paines_first_left_behind(names).upper() == "MAGE SCROLL 3 SPELLS"
