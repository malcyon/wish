"""Helpers `test_curse` shares with the test files that reuse them."""
from __future__ import annotations

import re

import gamedata
import pytest

from goldbox import geo
from goldbox.d64 import D64, split_load_address


def _stem(name: bytes) -> str:
    """A filename up to its first digit: `GEO45` and `GEO01` are both `GEO`."""
    text = bytes(name).decode("latin1")
    cut = re.search(r"[0-9]", text)
    return text[:cut.start()] if cut else text


def _stems(disks) -> set[str]:
    return {_stem(entry.name) for disk in disks for entry in disk.directory()}


def _names(disks) -> set[bytes]:
    return {bytes(entry.name) for disk in disks for entry in disk.directory()}


def _pool_disks():
    """Every readable Pool of Radiance game side, as the inventory control."""
    where = gamedata.disk_dir()
    if where is None:
        pytest.skip("needs the game disks; set POR_DISKS to where they are")
    out = []
    for path in sorted(where.glob("POOL*.[dD]64")):
        try:
            out.append(D64.open(str(path)))
        except Exception:
            continue
    if not out:
        pytest.skip("no readable Pool of Radiance disk here")
    return out


def _geo_ids(disks) -> list[int]:
    """Every `GEOnn` id on a set of sides, as numbers, sorted and unique."""
    out = set()
    for disk in disks:
        for entry in disk.directory():
            name = bytes(entry.name)
            if len(name) == 5 and name.startswith(b"GEO"):
                try:
                    out.add(int(name[3:], 16))
                except ValueError:
                    continue
    return sorted(out)


#: PETSCII as a name may use it: space through `_`, upper case only. `F/T` is a
#: real Curse character name, so punctuation is in and lower case is out.
_NAME_BYTES = frozenset(range(0x20, 0x60))


def _sane_name(raw: bytes) -> None:
    """The name reads to its NUL, and every byte of it is printable PETSCII.

    **Not NUL-padded, and asserting that it is fails on real specimens.** The
    field is 20 bytes and the game terminates at the first NUL without clearing
    what follows: `MALCYON\\x00N` and `SILAS\\x00S` in Pool of Radiance are
    characters renamed shorter, and Curse's `PALADIN` carries `\\x01\\x01` in
    its last two bytes where Silver Blades' `GUY DE VALOIS` carries
    `\\x02\\x01`. The residue is stale, not name.
    """
    text = raw.split(b"\x00")[0]
    assert text, "a character with no name"
    assert set(text) <= _NAME_BYTES, f"{raw!r} is not printable PETSCII"
    assert len(raw) == 20


def _sane_character(rec) -> None:
    """Things a person would recognise, not merely bytes that parsed."""
    _sane_name(rec.get_raw("name"))
    for score in (rec.strength, rec.intelligence, rec.wisdom, rec.dexterity,
                  rec.constitution, rec.charisma):
        assert 3 <= score <= 18, f"ability score {score} is not 3-18"
    assert 0 <= rec.exceptional_strength <= 100
    assert 1 <= rec.race <= 7
    assert 1 <= rec.level <= 40
    assert 0 < rec.hp_max <= 999
    assert rec.hp_rolled <= rec.hp_max
    for save in (rec.save_paralysis, rec.save_petrification, rec.save_wands,
                 rec.save_breath, rec.save_spell):
        assert 1 <= save <= 20, f"saving throw {save} out of range"
    assert 1 <= rec.movement <= 24
    # 10 for every player character: the `60 - value` encoding intact.
    assert rec.armour_class_base_value == 10

    # `class_bits` is the field to read, and it is one bit per non-zero slot of
    # the eight-wide level array at `0x0C9`. Curse fills slots 6 and 7 --
    # paladin and ranger -- which is why the array is eight and not four.
    levels = rec.slice(0x0C9, 8)
    assert rec.get("class_bits") == sum(
        1 << i for i, lv in enumerate(levels) if lv), (
        f"class_bits {rec.get('class_bits'):#04x} against {list(levels)}")
    assert max(levels) <= rec.level


#: Measured over Curse's sixteen maps: barrier mean 0.984, worst 0.935; art
#: mean 0.994, worst 0.919. Pool of Radiance is barrier 0.991/0.940 and art
#: 0.960/0.646. A wrong parse scores about 0.3-0.5.
BARRIER_FLOOR = 0.92
ART_FLOOR = 0.90
MEAN_FLOOR = 0.97
MANGLED_ART_CEILING = 0.70


def _geo_payloads(disks) -> dict[str, bytes]:
    out = {}
    for disk in disks:
        for entry in disk.directory():
            if not entry.name.startswith(b"GEO"):
                continue
            data = disk.read_file(entry)
            load, payload = split_load_address(data)
            assert len(payload) == geo.GEO_SIZE, (
                f"{entry.name!r} is {len(payload)} bytes, not a GEO")
            out[bytes(entry.name).decode("latin1")] = payload
    return out


def _barrier_reciprocity(payload: bytes) -> float:
    agree, total = geo.Geo(payload).reciprocity()
    return agree / total


def _art_reciprocity(payload: bytes) -> float:
    """Does an edge carry wall art read from both of the squares it divides?

    Deliberately presence, not value: the art *index* differs between the two
    sides of a one-way wall, and Curse indexes a different `WALLDEF` set than
    Pool of Radiance does. What must agree is that a wall is drawn at all.
    """
    grid = geo.Geo(payload)
    ok = total = 0
    for y in range(geo.GRID):
        for x in range(geo.GRID):
            for direction in (geo.EAST, geo.SOUTH):
                dx, dy = geo.STEP[direction]
                nx, ny = x + dx, y + dy
                if not (0 <= nx < geo.GRID and 0 <= ny < geo.GRID):
                    continue
                total += 1
                ok += bool(grid.wall(x, y, direction)) == bool(
                    grid.wall(nx, ny, geo.OPPOSITE[direction]))
    return ok / total


def _swap_art_planes(payload: bytes) -> bytes:
    """`$000` and `$100` exchanged: north/east art read as south/west."""
    out = bytearray(payload)
    out[0x000:0x100], out[0x100:0x200] = out[0x100:0x200], out[0x000:0x100]
    return bytes(out)


def _swap_art_nibbles(payload: bytes) -> bytes:
    """High and low nibble exchanged in both art planes."""
    out = bytearray(payload)
    for i in range(0x200):
        out[i] = ((out[i] & 0x0F) << 4) | (out[i] >> 4)
    return bytes(out)


# The cleric's spell grant, read out of `GEN` rather than guessed from the
# names. The routine is `LDX <cleric level> / BEQ out / LDY levels,X /
# LDX offsets,Y / LDA masks,Y / ORA record,X / STA record,X / DEY / BPL`, and
# the `BEQ` target is the `RTS` that the level table's own index 0 sits on --
# which is what fixes the overlay's base without fitting anything.
# The noncapturing optional gap recognises Y-clamping instructions; matching it
# does not execute them.
_GRANT_LOOP = re.compile(
    rb"\xAE(.)\x7C\xF0(.)\xBC(..)(?:.{0,12}?)\xBE(..)\xB9(..)\x1D\x00\x7C\x9D\x00\x7C"
    rb"\x88\x10\xF1\x60", re.DOTALL)


def _cleric_grant_table(payload: bytes):
    """(level -> set of spell ids) from Curse's cleric grant routine.

    The starting-book routine also has a grant-loop shape, but clamps its row
    index after `LDY`; these ten raw level rows are only the cleric's table.
    """
    for match in _GRANT_LOOP.finditer(payload):
        if match.group(1)[0] != 0xCA:
            continue
        levels, offsets, masks = (
            g[0] | g[1] << 8 for g in match.group(3, 4, 5))
        rts = match.end() - 1                        # file offset of the RTS
        base = levels - rts                          # the overlay's load address
        assert base == 0x0800, f"${base:04X} is not the overlay base"
        out, granted = {}, set()
        for level in range(1, 11):
            top = payload[levels - base + level]
            granted = set()
            for y in range(top + 1):
                byte = payload[offsets - base + y]
                mask = payload[masks - base + y]
                assert 0x078 <= byte <= 0x087, f"${byte:02X} is not the mask"
                granted |= {(byte - 0x078) * 8 + bit
                            for bit in range(8) if mask & (1 << bit)}
            out[level] = granted
        return out
    pytest.skip("GEN carries no cleric grant loop")
