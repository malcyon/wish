"""`tools/amiga/tripspace.py` on script libraries, switches and scripts built here.

No game byte is needed: the `ECL.GLB` and `ecl.dax` containers, the skip
switch and the scripts are assembled from their documented formats.
"""

import datetime
import hashlib
import pathlib
import struct
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from goldbox.amiga_adf import AmigaDisk  # noqa: E402
from tools.amiga import tripspace as t  # noqa: E402

WHEN = datetime.datetime(1991, 1, 1)


def glib(blocks: list[bytes]) -> bytes:
    """A `GLIB` container of `DATA` blocks."""
    head = 16 + 4 * (len(blocks) + 1)
    offsets, at = [], head
    for block in blocks:
        offsets.append(at)
        at += len(block)
    offsets.append(at)
    return (b"GLIB" + struct.pack(">IHH", at, len(blocks), 0) + b"DATA"
            + struct.pack(f">{len(offsets)}I", *offsets) + b"".join(blocks))


def area_table(pairs: list[tuple[int, int]]) -> bytes:
    return struct.pack(">H", len(pairs)) + b"".join(
        struct.pack(">HH", area, block) for area, block in pairs)


def dax_index(entries: list[tuple[int, int]]) -> bytes:
    """An Amiga `.dax` index of `(id, unpacked size)`; the blocks are never
    read, because the loader's length is the index's own figure."""
    rows = b"".join(t.amiga_dax.ENTRY.pack(bid, 0, 0, raw)
                    for bid, raw in entries)
    return struct.pack(">H", len(rows)) + rows


# -- lengths and tiers -------------------------------------------------------

def test_glib_lengths_come_from_the_area_table_not_the_block_order():
    # Silver Blades' table is not in block order: area 17 is block 3 here.
    lib = glib([area_table([(16, 1), (32, 2), (17, 3)]),
                b"\x01" * 100, b"\x02" * 7000, b"\x03" * 7678])
    rows = t.spaces(t.DARKNESS, lib)
    assert [(s.area, s.block, s.length, s.free) for s in rows] == [
        (16, 1, 100, 0x1E00 - 100), (17, 3, 7678, 2), (32, 2, 7000, 680)]


def test_a_table_naming_a_block_the_file_lacks_is_an_error():
    lib = glib([area_table([(1, 5)]), b"\x00" * 10])
    with pytest.raises(ValueError, match="names block 5"):
        t.spaces(t.CURSE, lib)


def test_a_table_shorter_than_its_count_is_an_error():
    lib = glib([struct.pack(">H", 3) + struct.pack(">HH", 1, 1), b"x"])
    with pytest.raises(ValueError, match="cut short"):
        t.spaces(t.CURSE, lib)


def test_a_script_longer_than_the_buffer_is_an_error():
    lib = glib([area_table([(1, 1)]), b"\x00" * (t.BUFFER + 1)])
    with pytest.raises(ValueError, match="longer than the buffer"):
        t.spaces(t.SILVER_BLADES, lib)


def test_pool_lengths_drop_the_two_byte_header_the_loader_skips():
    rows = t.spaces(t.POOL, dax_index([(20, 7679), (0, 7470)]))
    assert [(s.area, s.length, s.free) for s in rows] == [
        (0, 7468, 212), (20, 7677, 3)]


@pytest.mark.parametrize("free, want", [(21, 1), (20, 2), (3, 2), (2, 3)])
def test_the_tier_turns_on_the_21_and_3_byte_trips(free, want):
    assert t.tier(t.CURSE, t.BUFFER - free) == want


def test_the_area_file_byte_costs_one_more_save():
    assert t.tier(t.CURSE, t.BUFFER - 26) == 1
    assert t.tier(t.CURSE, t.BUFFER - 26, area_file=True) == 2
    assert t.tier(t.CURSE, t.BUFFER - 27, area_file=True) == 1


def test_pool_also_needs_its_message_below_the_statements_on_a_longword():
    # 21 bytes of statements end the buffer at 0x1DEB; the message goes at
    # (0x1DEB - 52) & ~3 = 0x1DB4, so a script may run to 0x1DB4 and no
    # further.
    assert t.lowest(t.POOL, 21) == 0x1DB4
    assert t.tier(t.POOL, 0x1DB4) == 1
    assert t.tier(t.POOL, 0x1DB5) == 2
    assert t.tier(t.POOL, t.lowest(t.POOL, 3)) == 2
    assert t.tier(t.POOL, t.lowest(t.POOL, 3) + 1) == 3
    # A title with a one-key buffer has no message.
    assert t.lowest(t.CURSE, 21) == t.BUFFER - 21


def test_the_grid_square_adds_two_saves():
    assert t.statements(grid=True) == t.FULL_BYTES + 12
    assert t.statements(square=False) == t.NEWECL_BYTES


def test_volume_names_pick_the_title():
    assert t.title_of("POOLDATA") == t.POOL
    assert t.title_of("CurseB") == t.CURSE
    assert t.title_of("Secret 2") == t.SILVER_BLADES
    assert t.title_of("POD 3") == t.DARKNESS
    assert t.title_of("Pools Of Darkness 1") == t.DARKNESS
    assert t.title_of("Lemmings") is None


def test_the_table_is_read_off_a_disk_in_a_folder(tmp_path, capsys):
    disk = AmigaDisk.blank("CurseB")
    disk.make_dir("DISKB", when=WHEN)
    lib = glib([area_table([(1, 1), (16, 2)]), b"\x00" * 7622,
                b"\x00" * 7664])
    disk.write_file("DISKB/ECL.GLB", lib, when=WHEN)
    disk.save(tmp_path / "b.adf")
    assert t.main(["--disks", str(tmp_path), "--title", t.CURSE]) == 0
    out = capsys.readouterr().out
    assert "/DISKB/ECL.GLB" in out
    assert "2 scripts; not tier 1: [16]" in out


def test_a_folder_without_the_library_says_so(tmp_path, capsys):
    AmigaDisk.blank("CurseA").save(tmp_path / "a.adf")
    assert t.main(["--disks", str(tmp_path)]) == 1
    assert "No Amiga script library" in capsys.readouterr().out


# -- the skip switch ---------------------------------------------------------

def skip_switch(cases: list[str], *, bad: bool = False) -> bytes:
    """`cmpi.w #n,d0; bcc.b; add.w d0,d0; lea table(pc),a0;
    move.w (a0,d0.w),d0; jmp (pc,d0.w)`, its table and its cases."""
    head = bytes.fromhex(f"0c40{len(cases):04x}6420d04041fa000c3030"
                         "00004efb0000")
    base = len(head) - 2
    table_at = len(head)
    bodies, offsets = b"", []
    at = table_at + 2 * len(cases)
    for kind in cases:
        offsets.append(at + len(bodies) - base)
        if kind == "step":
            body = bytes.fromhex("526c8000")
        elif kind.startswith("count"):
            body = bytes.fromhex(f"3f3c{int(kind[5:]):04x}4eba0000066cffff")
        else:
            body = bytes.fromhex(f"3f3c{int(kind):04x}4eba0000544f")
        if bad and kind == "1":
            body = b"\x4e\x71" * 4
        bodies += body + bytes.fromhex("4e75")
    # The lea's displacement is from its extension word to the table.
    head = head[:10] + struct.pack(">h", table_at - 10) + head[12:]
    return head + struct.pack(f">{len(offsets)}h", *offsets) + bodies


def test_the_skip_switch_gives_each_opcode_its_operand_count():
    code = b"\x4e\x71" * 8 + skip_switch(["step", "1", "count2", "3"])
    assert t.skip_model(code) == ((0, False), (1, False), (2, True),
                                  (3, False))


def test_a_switch_with_a_case_of_another_kind_is_not_the_skip_switch():
    assert t.skip_model(skip_switch(["step", "1"], bad=True)) is None


def test_two_candidate_switches_give_no_model():
    one = skip_switch(["step", "1"])
    assert t.skip_model(one + one) is None


# -- walking a script ----------------------------------------------------------

def model(**extra) -> tuple:
    m = [(0, False)] * 0x42
    for op, n in {0x01: 1, 0x02: 1, 0x03: 2, 0x09: 2, 0x20: 1}.items():
        m[op] = (n, False)
    m[0x25] = m[0x26] = (2, True)
    for op, v in extra.items():
        m[int(op[2:], 16)] = v
    return tuple(m)


def goto(addr: int) -> bytes:
    return bytes([0x01, 0x01, addr & 0xFF, addr >> 8])


def script(entries: list[int], body: bytes) -> bytes:
    assert len(entries) == 5
    return b"".join(goto(a) for a in entries) + body


def test_an_operand_past_the_end_of_the_script_is_a_tail_reference():
    # $8014: SAVE 1,[$8100]; $801A: EXIT.  The script is 0x1B bytes long.
    body = script([0x8014] * 4 + [0x801A], bytes.fromhex("090001010081 00"))
    m = model()
    found, bad = t.walk(t.CURSE, m, m, body)
    assert bad == set()
    assert t.tail_references(found, len(body)) == [(0x14, 0x09, 0x8100)]


def test_ongoto_targets_and_a_skipped_statement_are_followed():
    body = script([0x8014] * 5, bytes.fromhex(
        "25 013412 0002 012080 012480"   # $8014 ONGOTO [$1234], $8020, $8024
        "00"                             # $8020 EXIT, also the fall-through
        "000000"
        "16"                             # $8024 IF=
        "01013080"                       # $8025 GOTO $8030
        "00"                             # $8029 EXIT, reached only by a skip
        "000000000000"
        "00"))                           # $8030 EXIT
    m = model()
    found, bad = t.walk(t.CURSE, m, m, body)
    assert bad == set()
    assert {0x14, 0x20, 0x24, 0x25, 0x29, 0x30} <= set(found)
    assert 0x21 not in found


def test_pools_of_darkness_stops_after_its_23_and_curse_does_not():
    # $8014: $23, then a byte no opcode table has.
    body = script([0x8014] * 5, b"\x23\xff")
    m = model()
    assert t.walk(t.DARKNESS, m, m, body)[1] == set()
    assert t.walk(t.CURSE, m, m, body)[1] == {0x15}


def test_a_counted_statement_takes_as_many_more_as_its_count_says():
    # Three fixed operands, the third the count (2), then two more.
    stmt = bytes.fromhex("15 0001 0002 0002 010500 0007")
    s = t.decode(model(op0x15=(3, True)), stmt, 0)
    assert s is not None and s.end == len(stmt) and len(s.operands) == 5
    # A count that is not an immediate is not decoded.
    assert t.decode(model(op0x15=(3, True)),
                    bytes.fromhex("15 0001 0002 010200"), 0) is None


def test_a_string_operand_skips_its_length():
    s = t.decode(model(op0x12=(1, False)), bytes.fromhex("12800441424344"), 0)
    assert s.end == 7


#: Init at $8014: SAVE 1,[$8020], EXIT; $801B: EXIT.
INIT = "090001012080 00 00"


def test_init_bytes_no_other_entry_reaches_are_clean():
    clean = script([0x801B] * 4 + [0x8014], bytes.fromhex(INIT))
    m = model()
    assert t.init_overlap(t.DARKNESS, m, m, clean) == (0x14, [], [])


def test_an_operand_naming_the_init_bytes_is_reported():
    # Entry 0 runs SAVE 1,[$8015] at $801C, naming the init's second byte.
    named = script([0x801C] + [0x801B] * 3 + [0x8014],
                   bytes.fromhex(INIT + "090001011580 00"))
    m = model()
    assert t.init_overlap(t.DARKNESS, m, m, named) == (0x14, [], [0x1C])


def test_another_entry_running_inside_the_init_bytes_is_reported():
    shared = script([0x8015] + [0x801B] * 3 + [0x8014], bytes.fromhex(INIT))
    m = model()
    assert t.init_overlap(t.DARKNESS, m, m, shared)[1] == [0x15]


# -- Pool of Radiance ----------------------------------------------------------

#: The opcodes whose handler loads no operand, as the dispatcher at `0x2ACE2`
#: has them, and the four whose skip steps one byte over a counted run.
POOL_NO_OPERANDS = {0x00, 0x0D, 0x13, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x1B, 0x1C,
                    0x24, 0x31, 0x33, 0x3A, 0x3D}
POOL_COUNTED = {0x15, 0x25, 0x26, 0x2B}


def pool_script(entries, body: bytes) -> bytes:
    """A Pool script: five `GOTO`s from `$9900`, then `body` at offset 20."""
    head = b"".join(bytes((0x01, 0x01)) + struct.pack("<H", 0x9900 + at)
                    for at in entries)
    return head + body


def test_pools_walk_counts_are_the_handlers_and_its_skip_counts_the_chains():
    model, skip = t.pool_models()
    assert len(model) == len(skip) == t.POOL_OPCODES
    # The skip steps one byte over the counted four; the handlers load a run.
    assert {op for op in range(t.POOL_OPCODES) if skip[op] == (0, False)} \
        == POOL_NO_OPERANDS | POOL_COUNTED
    assert [model[op] for op in sorted(POOL_COUNTED)] == [
        (3, True), (2, True), (2, True), (2, True)]
    # Where the handlers load more than the chain skips.
    assert (skip[0x0C], model[0x0C]) == ((2, False), (3, False))
    assert (skip[0x36], model[0x36]) == ((1, False), (2, False))
    assert skip[0x29] == model[0x29] == (14, False)
    # `$1F` has no handler, so a walk steps over no operand there.
    assert (skip[0x1F], model[0x1F]) == ((2, False), (0, False))
    assert {model[op][0] for op in range(t.POOL_OPCODES)} \
        == {0, 1, 2, 3, 4, 5, 6, 8, 14}


def test_pool_scripts_run_from_9900():
    model, skip = t.pool_models()
    body = pool_script([20] * 5, bytes.fromhex("00"))
    found, bad = t.walk(t.POOL, model, skip, body)
    assert sorted(found) == [20] and not bad


def test_a_pool_init_span_with_no_other_way_in_is_free():
    model, skip = t.pool_models()
    body = pool_script([20] * 4 + [32], b"\x00".ljust(12, b"\x00")
                       + bytes.fromhex("200005") + bytes(5))
    space = t.init_space(t.POOL, model, skip, 3, body)
    assert (space.start, space.covers, space.names) == (32, (), ())
    assert space.free and space.size == len(body) - 32
    assert space.sha1 == hashlib.sha1(body[32:]).hexdigest()


def test_pool_statements_that_cover_or_name_the_span_are_found():
    model, skip = t.pool_models()
    tail = bytes.fromhex("200005") + bytes(5)
    # Entry 0 jumps into the init entry.
    jump = pool_script([20] + [26] * 3 + [32],
                       bytes.fromhex("01012099") + bytes(6) + b"\x00"
                       + bytes(5) + tail)
    assert t.init_space(t.POOL, model, skip, 3, jump).covers == (32,)
    # Entry 0 saves into the span's second byte.
    named = pool_script([20] + [26] * 3 + [32],
                        bytes.fromhex("090001012199") + b"\x00" + bytes(5)
                        + tail)
    space = t.init_space(t.POOL, model, skip, 3, named)
    assert space.names == (20,) and not space.free


def _pool_libraries():
    for _t, _label, path, lib in t.disk_files(t.images(None),
                                              {t.POOL: t.LIBRARY[t.POOL]}):
        yield path, lib


def test_the_players_disks_give_the_init_spans_automap_records():
    from automap import amigatrip
    model, skip = t.pool_models()
    seen = 0
    for _path, lib in _pool_libraries():
        blocks = dict(t.amiga_dax.blocks(lib, t.LIBRARY[t.POOL]))
        for (key, area), room in amigatrip.INIT_ROOM.items():
            assert key == t.POOL
            body = blocks[area][t.POOL_HEADER:]
            space = t.init_space(t.POOL, model, skip, area, body)
            got = (space.start, t.BUFFER, space.size, space.sha1)
            assert got == (room.start, room.end, room.size, room.sha1), area
            # Nothing reachable from entries 0-3 covers or names the span.
            assert space.free, area
            found, bad = t.walk(t.POOL, model, skip, body)
            assert not bad and not t.tail_references(
                found, len(body), t.BASES[t.POOL]), area
            # No RANDOM statement lies in it, which `noencounters` patches.
            assert all(s.op != 0x08 for s in found.values()
                       if s.at >= room.start), area
            seen += 1
    if not seen:
        pytest.skip("needs the player's Amiga Pool of Radiance disks")


def test_the_players_disks_give_pools_statement_counts_in_every_script():
    model, skip = t.pool_models()
    counts = {}
    for _path, lib in _pool_libraries():
        for area, block in t.amiga_dax.blocks(lib, t.LIBRARY[t.POOL]):
            found, bad = t.walk(t.POOL, model, skip, block[t.POOL_HEADER:])
            if area in (1, 17, 28):
                assert not bad, area
            counts[area] = len(found)
        break
    if not counts:
        pytest.skip("needs the player's Amiga Pool of Radiance disks")
    assert (counts[1], counts[17], counts[28]) == (582, 624, 487)
    assert len(counts) == 29
