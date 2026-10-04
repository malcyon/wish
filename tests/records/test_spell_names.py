"""Spell names on every port, `goldbox/spell_names.py`.

Two halves. The synthetic tests build each table form from its documented
layout -- an EXEPACK executable, a DOS data segment of Pascal strings and the
`GAME.OVR` instruction that indexes it, an Amiga Hunk executable with a pointer
array or fixed-width cells -- so CI checks the parsing with no game data. The
disk-backed tests read the player's own C64, DOS and Amiga games, skip where
the registry has none, and check that every port names the same spell under
the same id: the ids where two ports' text differs are listed here as numbers,
each with its reason, so a misaligned table fails rather than passes.

No game bytes are committed: every name is read at run time.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
import struct

import pytest

from goldbox import amiga_hunks, exepack, spell_names, spells
from tests.support.hunks import hunk_file

#: A three-spell title: ids 1-3 are spells, id 4 is past the last.
TINY = dataclasses.replace(
    spells.POOL_OF_RADIANCE, key="tiny", title="Tiny", last_spell=3,
    groups=((1, 3, "cleric", 1),), not_a_spell=())

#: The same, with id 2 not a spell, so an empty name there is allowed.
TINY_GAP = dataclasses.replace(TINY, groups=((1, 1, "cleric", 1), (3, 3, "cleric", 1)),
                               not_a_spell=(2,))


# --- EXEPACK -----------------------------------------------------------------

def _exepack(prefix: bytes, run: bytes, fill: int, fill_len: int,
             real_cs: int = 0, real_ip: int = 6) -> bytes:
    """An EXEPACK executable whose image is `prefix + run + fill * fill_len`.

    Commands are read backwards from the end of the packed data: the fill
    command last in the file fills the top of the image, then the copy
    command, flagged last, copies `run` below it, and `prefix` is stored as is.
    """
    packed = (prefix + run + struct.pack("<H", len(run)) + b"\xB3"
              + bytes((fill,)) + struct.pack("<H", fill_len) + b"\xB0")
    packed += b"\xFF" * (-len(packed) % 16)
    image_len = len(prefix) + len(run) + fill_len
    assert image_len % 16 == 0
    header = bytearray(32)
    header[:2] = b"MZ"
    struct.pack_into("<H", header, 8, 2)                       # header paragraphs
    struct.pack_into("<H", header, 0x16, len(packed) // 16)    # cs: the stub
    stub = struct.pack("<HHHHHHHH2s", real_ip, real_cs, 0, 0, 0, 0,
                       image_len // 16, 0, b"RB")
    return bytes(header) + packed + stub


def test_exepack_expands_a_copy_and_a_fill_and_keeps_the_plain_prefix():
    prefix, run = bytes(range(16)), b"ABCDEFGH"
    image, info = exepack.unpack(_exepack(prefix, run, 0xAA, 8))
    assert image == prefix + run + b"\xAA" * 8
    assert info["plain_prefix"] == 16


def test_load_image_gives_the_entry_from_the_exepack_header():
    image, entry = exepack.load_image(_exepack(bytes(16), b"x" * 8, 0, 8,
                                               real_cs=1, real_ip=3))
    assert entry == 1 * 16 + 3


def test_load_image_reads_a_plain_executable_after_its_header():
    header = bytearray(32)
    header[:2] = b"MZ"
    struct.pack_into("<H", header, 8, 2)
    struct.pack_into("<HH", header, 0x14, 5, 2)                # ip, cs
    image, entry = exepack.load_image(bytes(header) + b"body")
    assert (image, entry) == (b"body", 2 * 16 + 5)


def test_a_file_that_is_not_a_dos_executable_raises():
    with pytest.raises(ValueError):
        exepack.load_image(b"not an executable at all, just bytes")


# --- DOS -----------------------------------------------------------------------

DS = 0x10                       # the data segment's paragraph in the image


def _pascal(text: str, stride: int) -> bytes:
    raw = text.encode()
    return bytes((len(raw),)) + raw + bytes(stride - 1 - len(raw))


def _index(stride: int, base: int) -> bytes:
    """`mov dx, stride / mul dx / mov di, ax / add di, base / push ds / push di`."""
    return (b"\xBA" + bytes((stride, 0)) + b"\xF7\xE2\x8B\xF8\x81\xC7"
            + struct.pack("<H", base) + b"\x1E\x57")


def _dos_image(tables: dict[int, tuple[int, list[str]]]) -> tuple[bytes, int]:
    """An image whose entry far-calls an initialiser that loads `DS`, and
    whose data segment holds each `{base: (stride, slots)}` table followed
    by a byte that ends any run of slots."""
    image = bytearray(0x400)
    image[0:5] = b"\x9A" + struct.pack("<HH", 0x20, 0)         # call far 0000:0020
    image[0x20:0x25] = b"\xBA" + struct.pack("<H", DS) + b"\x8E\xDA"
    for base, (stride, slots) in tables.items():
        at = DS * 16 + base
        for text in slots:
            image[at:at + stride] = _pascal(text, stride)
            at += stride
        image[at:at + 2] = b"\x00\x01"                          # not a slot
    return bytes(image), 0


def test_dos_names_come_from_the_indexed_table_with_id_zero_at_the_base():
    image, entry = _dos_image({0x10: (9, ["", "Alpha", "Beta", "Gamma"])})
    names = spell_names.dos_spell_names(image, entry, [_index(9, 0x10)], TINY)
    assert names == {1: "Alpha", 2: "Beta", 3: "Gamma"}


def test_dos_table_that_runs_past_the_last_spell_loses_to_one_that_stops():
    image, entry = _dos_image({
        0x10: (9, ["", "Alpha", "Beta", "Gamma"]),
        0x80: (9, ["", "Ax", "By", "Cz", "Dw", "Ev"]),
    })
    code = [_index(9, 0x80), _index(9, 0x10)]
    assert spell_names.dos_spell_names(image, entry, code, TINY)[1] == "Alpha"


def test_dos_empty_name_at_a_non_spell_id_is_left_out():
    image, entry = _dos_image({0x10: (9, ["", "Alpha", "", "Gamma"])})
    names = spell_names.dos_spell_names(image, entry, [_index(9, 0x10)], TINY_GAP)
    assert names == {1: "Alpha", 3: "Gamma"}


def test_dos_two_equally_good_tables_raise_rather_than_guess():
    image, entry = _dos_image({0x10: (9, ["", "A", "B", "C"]),
                               0x80: (9, ["", "D", "E", "F"])})
    with pytest.raises(spell_names.SpellNameError):
        spell_names.dos_spell_names(
            image, entry, [_index(9, 0x10), _index(9, 0x80)], TINY)


def test_dos_with_no_indexed_table_raises():
    image, entry = _dos_image({0x10: (9, ["", "A", "B", "C"])})
    with pytest.raises(spell_names.SpellNameError):
        spell_names.dos_spell_names(image, entry, [b"no code here"], TINY)


def test_a_title_with_no_spell_table_is_not_answered_with_pool_of_radiances():
    with pytest.raises(spell_names.SpellNameError):
        spell_names.dos_spell_names(b"", 0, [], "no-such-title")


# --- Amiga ---------------------------------------------------------------------

def _cstrings(texts: list[str]) -> tuple[bytes, list[int]]:
    blob, offsets = bytearray(), []
    for text in texts:
        offsets.append(len(blob))
        blob += text.encode() + b"\x00"
    return bytes(blob + bytes(-len(blob) % 4)), offsets


def _small_data_program(texts: list[str], array_at: int = 0x10) -> bytes:
    """Code `asl.l #2, d0 / lea d16(a4), a0 / move.l (a0, d0.l), -(a7)`, then
    the strings; a small-data hunk holding one relocated pointer an id from
    `array_at`. One CODE and one DATA hunk, as the three later titles have.
    `texts[0]` is id 0."""
    d16 = array_at - spell_names.SMALL_DATA_BIAS
    code = b"\xE5\x80\x41\xEC" + struct.pack(">h", d16) + b"\x2F\x30\x08\x00\x4E\x75"
    strings, offsets = _cstrings(texts)
    data = bytearray(array_at + 4 * len(texts) + 4)
    for i, off in enumerate(offsets):
        struct.pack_into(">I", data, array_at + 4 * i, len(code) + off)
    data[-4:] = b"\xFF\xFF\xFF\xFF"
    relocs = [(0, [array_at + 4 * i for i in range(len(texts))])]
    return hunk_file([(amiga_hunks.HUNK_CODE, code + strings, []),
                      (amiga_hunks.HUNK_DATA, bytes(data), relocs)])


def test_amiga_small_data_form_indexes_from_the_id_zero_slot():
    program = _small_data_program(["", "Alpha", "Beta", "Gamma"])
    assert spell_names.amiga_spell_names(program, TINY) == {
        1: "Alpha", 2: "Beta", 3: "Gamma"}


def test_amiga_pointers_that_run_on_past_the_last_spell_are_cut_there():
    program = _small_data_program(["", "Alpha", "Beta", "Gamma", "Potion"])
    assert spell_names.amiga_spell_names(program, TINY) == {
        1: "Alpha", 2: "Beta", 3: "Gamma"}


def test_amiga_table_with_an_unnamed_spell_is_not_the_spell_table():
    program = _small_data_program(["", "Alpha", "", "Gamma"])
    with pytest.raises(spell_names.SpellNameError):
        spell_names.amiga_spell_names(program, TINY)


def _cell_program(texts: list[str], stride: int = 12, base: int = 0x20) -> bytes:
    """`moveq #stride, d1 / jsr d16(pc) / lea abs.l, a0 / adda.l d0, a0`,
    the `abs.l` relocated into a data hunk of NUL-padded `char[stride]`."""
    code = (b"\x72" + bytes((stride,)) + b"\x4E\xBA\x00\x00\x41\xF9"
            + struct.pack(">I", base) + b"\xD1\xC0\x4E\x75")
    data = bytearray(base + stride * (len(texts) + 1))
    for i, text in enumerate(texts):
        data[base + stride * i:base + stride * i + len(text)] = text.encode()
    data[base + stride * len(texts) + 1] = 7                     # not a cell
    data += bytes(-len(data) % 4)
    return hunk_file([(amiga_hunks.HUNK_CODE, code, [(1, [8])]),
                      (amiga_hunks.HUNK_DATA, bytes(data), [])])


def test_amiga_cell_form_reads_fixed_width_names():
    program = _cell_program(["", "Alpha", "Beta", "Gamma"])
    assert spell_names.amiga_spell_names(program, TINY) == {
        1: "Alpha", 2: "Beta", 3: "Gamma"}


def test_a_crunched_program_is_named_as_crunched():
    program = hunk_file([(amiga_hunks.HUNK_CODE, b"\x4E\x75\x00\x00S404" + bytes(8), [])])
    with pytest.raises(spell_names.SpellNameError, match="StoneCracker"):
        spell_names.amiga_spell_names(program, TINY)


def test_spell_names_names_the_platforms_it_knows():
    with pytest.raises(ValueError):
        spell_names.spell_names("pool-of-radiance", "atari", None)


def test_pools_of_darkness_has_no_c64_names_to_read():
    with pytest.raises(spell_names.SpellNameError):
        spell_names.load_c64_spell_names(".", "pools-of-darkness")


# --- the player's own games --------------------------------------------------

#: Ids where two ports name the same spell in different words, compared after
#: dropping case and everything but letters and digits. Each is the game's
#: own text: `goldbox.spell_names`' docstring says what kinds of difference
#: there are, and these are the ids they land on.
#:
#: * Curse and Silver Blades DOS against C64: 69, `PROTECTION FROM EVIL 10'
#:   RADIUS` where DOS drops `FROM`; 88 and Silver Blades' 112 and 116, the
#:   C64 spelling `INVULNERABLITY` and `INVISIBLITY`; and Silver Blades 109,
#:   which DOS calls `spell 109`, the form it gives every id it has no spell
#:   for, where the C64 table repeats `DEATH SPELL`.
DOS_VS_C64 = {
    "pool-of-radiance": set(),
    "curse-of-the-azure-bonds": {69, 88},
    "secret-of-the-silver-blades": {69, 88, 109, 112, 116},
}

#: * Amiga Pools of Darkness abbreviates `Prot.` at 52, 53, 54 and 69.
#: * Amiga Silver Blades prints the engine's own spell names, upper case:
#:   `CLERIC DETECT MAGIC`, `SHIELD SPELL`, `PROT NORM MISSILES`, and
#:   `RESERVED` at 109.
AMIGA_VS_DOS = {
    "pool-of-radiance": set(),
    "curse-of-the-azure-bonds": set(),
    "secret-of-the-silver-blades": {5, 6, 7, 16, 17, 19, 23, 25, 31, 35, 41, 44,
                                    45, 50, 52, 53, 54, 68, 69, 77, 81, 89, 98,
                                    109},
    "pools-of-darkness": {52, 53, 54, 69},
}

TITLES = [t.key for t in spells.TITLES]


def _norm(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def _differ(a: dict[int, str], b: dict[int, str], table) -> set[int]:
    return {i for i in range(1, table.last_spell + 1)
            if spells.spell_group(i, table) and _norm(a.get(i, "")) != _norm(b.get(i, ""))}


def _check_names(names: dict[int, str], table) -> None:
    """Every spell id named, nothing past the last spell."""
    assert set(names) <= set(range(1, table.last_spell + 1))
    unnamed = [i for i in range(1, table.last_spell + 1)
               if spells.spell_group(i, table) and not names.get(i)]
    assert unnamed == []


@pytest.fixture(scope="module")
def c64_names():
    from automap import gamedisks
    out = {}
    for key in TITLES:
        if not spells.BY_KEY[key].file:
            continue
        where = gamedisks.find(key)
        if where is not None:
            out[key] = spell_names.load_c64_spell_names(where, key)
    return out


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
            out[key] = [spell_names.load_dos_spell_names(f, key) for f in folders]
    return out


@pytest.fixture(scope="module")
def amiga_programs():
    """`{title: {sha1: program}}` for every distinct Amiga program here."""
    from automap import gamedisks
    from goldbox.amiga_adf import AmigaDisk
    from tools.amiga import amigasaves
    out: dict[str, dict[str, bytes]] = {}
    if not gamedisks.candidates("amiga"):
        return out
    for _label, data in amigasaves.images():
        try:
            disk = AmigaDisk(bytearray(data))
        except Exception:
            continue
        for key in TITLES:
            try:
                program = spell_names.amiga_program([disk], key)
            except Exception:                   # not this title's disk
                continue
            out.setdefault(key, {})[hashlib.sha1(program).hexdigest()] = program
    return out


@pytest.mark.parametrize("key", [k for k in TITLES if spells.BY_KEY[k].file])
def test_c64_names_cover_every_spell(c64_names, key):
    if key not in c64_names:
        pytest.skip(f"no C64 {key} disks")
    _check_names(c64_names[key], spells.BY_KEY[key])


@pytest.mark.parametrize("key", TITLES)
def test_dos_names_cover_every_spell_and_agree_with_the_c64_id_for_id(
        dos_names, c64_names, key):
    if key not in dos_names:
        pytest.skip(f"no DOS {key} under the archives")
    table = spells.BY_KEY[key]
    for names in dos_names[key]:
        _check_names(names, table)
        if key in c64_names:
            assert _differ(names, c64_names[key], table) == DOS_VS_C64[key]


@pytest.mark.parametrize("key", TITLES)
def test_amiga_names_cover_every_spell_and_agree_with_dos_id_for_id(
        amiga_programs, dos_names, key):
    if key not in amiga_programs:
        pytest.skip(f"no Amiga {key} disks")
    table = spells.BY_KEY[key]
    read = 0
    for program in amiga_programs[key].values():
        try:
            names = spell_names.amiga_spell_names(program, key)
        except spell_names.SpellNameError as error:
            # The one build that does not read is the crunched one, and it
            # says so; any other failure is a misread table.
            assert "crunched" in str(error)
            continue
        read += 1
        _check_names(names, table)
        if key in dos_names:
            assert _differ(names, dos_names[key][0], table) == AMIGA_VS_DOS[key]
    assert read >= 1
