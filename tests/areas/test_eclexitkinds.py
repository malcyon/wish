"""`tools/areas/eclexitkinds.py`'s exit classification, on scripts built here rather
than off a disk, plus the real totals it produces from the thirty area
scripts.

The classifier -- `ongoto_index`, `mask_before`, `features`, `squares_with`
and `analyse` itself -- is pure logic once it has a `Script` and (optionally)
a `Geo`; neither needs a disk, so `FakeMachine` stands in for the real
`eclwalk.Machine`, which reads its opcode tables out of `DUNGEON`. What that
machine reads is not reproduced here -- only the operand counts this file's
own synthetic scripts need are declared, none of them copied off a disk.

`test_the_79_exits_still_break_down_the_way_the_readme_row_says` is the
precedent `tests/areas/test_questflags.py` sets for `tools/areas/eclflags.py`: the real
count, pinned, so a walk that reaches less of a script shows up here instead
of only in a doc nobody reruns. It is the count behind the corrected
`tools/README.md` row -- the old row implied every exit was `edge` or
`square`, and six kinds come out of the 79, 22 of them neither.
"""
from __future__ import annotations

import collections
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from gamedata import needs_disks  # noqa: E402

from goldbox.geo import ATTRIBUTES, GEO_SIZE, Geo  # noqa: E402
from tools.areas import eclexitkinds as EK  # noqa: E402
from tools.areas import eclwalk as W  # noqa: E402

EDGE_FLAG, ATTR = EK.EDGE_FLAG, EK.ATTR


# ---------------------------------------------------------------------------
# a tiny assembler: only what these scripts need -- fixed-address operands
# for COMPARE/AND/SAVE, and body-relative labels for GOTO/ONGOTO targets,
# which are the only operands the real engine ever treats as jumps.
# ---------------------------------------------------------------------------

class Asm:
    def __init__(self):
        self._items: list[tuple[str, object]] = []

    def label(self, name):
        self._items.append(("label", name))

    def raw(self, data: bytes):
        self._items.append(("raw", data))

    def addr(self, label):
        self._items.append(("addr", label))

    def build(self) -> bytes:
        offset, labels = 0, {}
        for kind, payload in self._items:
            if kind == "label":
                labels[payload] = offset
            elif kind == "raw":
                offset += len(payload)
            elif kind == "addr":
                offset += 3
        out = bytearray()
        for kind, payload in self._items:
            if kind == "raw":
                out += payload
            elif kind == "addr":
                out += bytes([0x02]) + (W.BASE + labels[payload]).to_bytes(2, "little")
        return bytes(out)


def op_goto(asm, label):
    asm.raw(bytes([0x01]))
    asm.addr(label)


def op_newecl(asm, area):
    asm.raw(bytes([0x20, 0x00, area & 0xFF]))


def op_ongoto(asm, arm_labels):
    asm.raw(bytes([0x25, 0x00, 0x00, 0x00, len(arm_labels)]))
    for label in arm_labels:
        asm.addr(label)


def op_exit(asm):
    asm.raw(bytes([0x00]))


def op_compare_edge(asm):
    asm.raw(bytes([0x03, 0x02]) + EDGE_FLAG.to_bytes(2, "little"))


def op_and_mask(asm, mask):
    asm.raw(bytes([0x2F, 0x02]) + ATTR.to_bytes(2, "little") + bytes([0x00, mask]))


def op_save(asm, dest_addr):
    asm.raw(bytes([0x09, 0x00, 0x00, 0x02]) + dest_addr.to_bytes(2, "little"))


def op_bare(asm, opcode):
    asm.raw(bytes([opcode]))


class FakeMachine:
    """`eclwalk.Machine`'s `operands(op)` interface, without reading a disk.

    Counts are chosen for the handful of opcodes these synthetic scripts use;
    none is read off `DUNGEON`. Every opcode below already appears in
    `eclwalk.py`'s or `eclexitkinds.py`'s own constants (`NAMES`, `MENUS`,
    `TEXT`, `POSITION`), so this names nothing the repository does not
    already have on record.
    """
    _COUNTS = {
        0x01: 1,   # GOTO: one address operand
        0x03: 1,   # COMPARE: one address operand
        0x20: 1,   # NEWECL: one immediate operand, the area
        0x09: 2,   # SAVE: destination is the second operand
        0x2F: 2,   # AND: the address masked, then the mask
    }

    def operands(self, op):
        return self._COUNTS.get(op, 0)


def make_body(active_entry: int, block) -> bytes:
    """Five entries; all but `active_entry` dead-end at a bare `EXIT`."""
    asm = Asm()
    for n in range(5):
        op_goto(asm, "LIVE" if n == active_entry else "STUB")
    asm.label("STUB")
    op_exit(asm)
    asm.label("LIVE")
    block(asm)
    return asm.build()


def analyse_one(active_entry: int, block, geo=None):
    body = make_body(active_entry, block)
    script, rows = EK.analyse(FakeMachine(), "TEST", "SIDE", body, geo)
    assert len(rows) == 1, "each case is built with exactly one NEWECL"
    return rows[0]


# ---------------------------------------------------------------------------
# analyse() -- the six kinds, one synthetic script each
# ---------------------------------------------------------------------------

def test_entry0_gated_on_the_edge_flag_with_no_ongoto_is_edge():
    def block(asm):
        op_compare_edge(asm)
        op_newecl(asm, 1)
    row = analyse_one(0, block)
    assert row["kind"] == "edge"
    assert row["entries"] == [0]
    assert row["index"] is None
    assert row["target"] == 1


def test_entry1s_ongoto_is_square():
    def block(asm):
        op_ongoto(asm, ["ARM0"])
        op_exit(asm)
        asm.label("ARM0")
        op_newecl(asm, 2)
    row = analyse_one(1, block)
    assert row["kind"] == "square"
    assert row["index"] == 0
    assert row["entries"] == [1]


def test_entry0_gated_and_carrying_an_ongoto_is_edge_plus_square():
    def block(asm):
        op_compare_edge(asm)
        op_ongoto(asm, ["ARM0"])
        op_exit(asm)
        asm.label("ARM0")
        op_newecl(asm, 3)
    row = analyse_one(0, block)
    assert row["kind"] == "edge+square"
    assert row["index"] == 0


def test_entry0s_ongoto_with_no_gate_is_square_via_entry0():
    def block(asm):
        op_ongoto(asm, ["ARM0"])
        op_exit(asm)
        asm.label("ARM0")
        op_newecl(asm, 4)
    row = analyse_one(0, block)
    assert row["kind"] == "square-via-entry0"
    assert row["index"] == 0


class TableMachine(FakeMachine):
    """`FakeMachine`, with the operand counts a table-driven step entry needs:
    `COMPARE` of two operands, the `AND` with its destination, `$2A`'s three,
    `$14`'s four and `ADD`'s three. None is read off `DUNGEON`."""
    _COUNTS = {**FakeMachine._COUNTS, 0x03: 2, 0x2F: 3, 0x2A: 3, 0x14: 4,
               0x04: 3}


def _addr(value):
    return bytes([0x02]) + value.to_bytes(2, "little")


def _imm(value):
    return bytes([0x00, value])


def op_table(asm, table, index, dest):
    asm.raw(bytes([0x2A]))
    asm.addr(table)
    asm.raw(_addr(index) + _addr(dest))


def op_compare(asm, var, literal):
    asm.raw(bytes([0x03]) + _addr(var) + _imm(literal))


def table_entry0(asm):
    """Two rows on square id 3, facing S then E, both action 0; arm 0
    leaves only for row 0, the way `ECL07`'s stairs arm does."""
    counter, sid, row_id, row_facing = 0x6E79, 0x6E7A, 0x6E7B, 0x6E7C
    asm.raw(bytes([0x09]) + _imm(0) + _addr(counter))
    asm.raw(bytes([0x2F]) + _addr(ATTR) + _imm(127) + _addr(sid))
    asm.label("LOOP")
    op_table(asm, "IDS", counter, row_id)
    op_table(asm, "FACINGS", counter, row_facing)
    asm.raw(bytes([0x14]) + _addr(sid) + _addr(row_id) + _addr(row_facing)
            + _addr(0xC04D))
    op_bare(asm, 0x16)
    op_goto(asm, "MATCH")
    asm.raw(bytes([0x04]) + _imm(1) + _addr(counter) + _addr(counter))
    op_compare(asm, counter, 2)
    op_bare(asm, 0x18)
    op_goto(asm, "LOOP")
    op_exit(asm)
    asm.label("MATCH")
    op_table(asm, "ACTIONS", counter, row_id)
    asm.raw(bytes([0x25]) + _addr(row_id) + _imm(2))
    asm.addr("ARM0")
    asm.addr("ARM1")
    op_exit(asm)
    asm.label("ARM0")
    op_compare(asm, counter, 0)
    op_bare(asm, 0x16)
    op_goto(asm, "LEAVE")
    op_exit(asm)
    asm.label("LEAVE")
    op_newecl(asm, 9)
    asm.label("ARM1")
    op_exit(asm)
    asm.label("IDS")
    asm.raw(bytes([3, 3]))
    asm.label("FACINGS")
    asm.raw(bytes([2, 1]))
    asm.label("ACTIONS")
    asm.raw(bytes([0, 0]))


def test_entry0s_table_names_the_square_and_facing_not_the_arm_number():
    data = bytearray(GEO_SIZE)
    data[ATTRIBUTES + 0x52] = 3          # square id 3 at (2, 5) only
    data[ATTRIBUTES + 0x00] = 1          # id 1, the arm number + 1, at (0, 0)
    body = make_body(0, table_entry0)
    _script, rows = EK.analyse(TableMachine(), "TEST", "SIDE", body,
                               Geo(bytes(data)))
    row, = rows
    assert row["kind"] == "square-via-entry0"
    assert row["table"] == [(0, 3, 2, 0)]   # row 1 fails arm 0's counter test
    assert row["squares"] == [(2, 5, 2)]


def grid_entry0(asm):
    """Leave east off column 15, heading 1 or 2, the way the travel-grid
    windows' seams do."""
    op_compare(asm, 0x49C3, 15)
    op_bare(asm, 0x16)
    op_goto(asm, "EAST")
    op_exit(asm)
    asm.label("EAST")
    asm.raw(bytes([0x25]) + _addr(0x033D) + _imm(3))
    asm.addr("STAY")
    asm.addr("LEAVE")
    asm.addr("LEAVE")
    asm.label("STAY")
    op_exit(asm)
    asm.label("LEAVE")
    op_newecl(asm, 26)


def test_entry0s_ongoto_on_the_travel_heading_names_no_geo_square():
    body = make_body(0, grid_entry0)
    _script, rows = EK.analyse(TableMachine(), "TEST", "SIDE", body,
                               Geo(bytes(GEO_SIZE)))
    row, = rows
    assert row["kind"] == "square-via-entry0"
    assert row["squares"] is None
    assert row["headings"] == [1, 2]
    assert row["grid"] == [(0x49C3, "=", 15)]


def test_entry1_with_neither_a_gate_nor_an_ongoto_is_entry1_unconditional():
    def block(asm):
        op_newecl(asm, 5)
    row = analyse_one(1, block)
    assert row["kind"] == "entry1-unconditional"


def test_entry0_with_neither_a_gate_nor_an_ongoto_is_entry0_unconditional():
    def block(asm):
        op_newecl(asm, 6)
    row = analyse_one(0, block)
    assert row["kind"] == "entry0-unconditional"


def test_an_exit_only_a_later_entry_reaches_is_named_after_that_entry():
    """`ECL0B`'s `$A20F` is this case on the real disks: only entry 3."""
    def block(asm):
        op_newecl(asm, 7)
    row = analyse_one(2, block)
    assert row["kind"] == "entry2"
    assert row["entries"] == [2]


def test_the_second_ongoto_arm_gets_index_one():
    def block(asm):
        op_ongoto(asm, ["ARM0", "ARM1"])
        op_exit(asm)
        asm.label("ARM0")
        op_newecl(asm, 8)
        asm.label("ARM1")
        op_newecl(asm, 9)
    body = make_body(1, block)
    _script, rows = EK.analyse(FakeMachine(), "TEST", "SIDE", body, None)
    by_area = {r["target"]: r for r in rows}
    assert by_area[8]["index"] == 0
    assert by_area[9]["index"] == 1


# ---------------------------------------------------------------------------
# features() -- what a player would notice on the route
# ---------------------------------------------------------------------------

def test_features_tags_loadchar_call_and_combat():
    def block(asm):
        op_bare(asm, 0x0A)             # LOADCHAR
        op_bare(asm, 0x2D)             # CALL
        op_bare(asm, 0x24)             # COMBAT
        op_newecl(asm, 1)
    row = analyse_one(1, block)
    assert row["features"] == ["call", "combat", "loadchar"]


def test_features_tags_a_menu_and_text_opcode():
    def block(asm):
        op_bare(asm, 0x29)             # a MENUS opcode
        op_bare(asm, 0x0E)             # a TEXT opcode
        op_newecl(asm, 1)
    row = analyse_one(1, block)
    assert row["features"] == ["menu", "text"]


def test_features_classifies_a_save_by_its_destination():
    def block(asm):
        op_save(asm, 0xC04B)           # POSITION
        op_save(asm, 0x4A20)           # FLAGS
        op_save(asm, 0x6B00)           # MEMBERSHIP
        op_newecl(asm, 1)
    row = analyse_one(1, block)
    assert row["features"] == ["flag", "membership", "position"]


def test_features_ignores_an_immediate_save_operand():
    """`SAVE n, k` with `k` an immediate is not a write anywhere interesting;
    `features()` only tags a `SAVE` whose destination is an address."""
    def block(asm):
        asm.raw(bytes([0x09, 0x00, 0x00, 0x00, 0x05]))   # both operands immediate
        op_newecl(asm, 1)
    row = analyse_one(1, block)
    assert row["features"] == []


# ---------------------------------------------------------------------------
# ongoto_index() and mask_before() -- against hand-built statements, with no
# `Script`/`decode` machinery at all
# ---------------------------------------------------------------------------

class FakeScript:
    def __init__(self, statements):
        self.statements = {s.at: s for s in statements}


def test_ongoto_index_finds_the_arm_that_lands_on_b():
    ongoto = W.Statement(0, 8, W.ONGOTO,
                         [(0x00, 0), (0x00, 2),
                          (0x02, W.BASE + 50), (0x02, W.BASE + 100)])
    script = FakeScript([ongoto])
    st, k = EK.ongoto_index(script, [0, 100])
    assert st is ongoto and k == 1


def test_ongoto_index_is_none_when_the_path_has_no_ongoto():
    compare = W.Statement(0, 4, 0x03, [(0x02, EDGE_FLAG)])
    script = FakeScript([compare])
    st, k = EK.ongoto_index(script, [0, 50])
    assert (st, k) == (None, None)


def test_mask_before_reads_the_and_immediate_against_attr():
    and_stmt = W.Statement(0, 6, 0x2F, [(0x02, ATTR), (0x00, 0x1F)])
    script = FakeScript([and_stmt])
    assert EK.mask_before(script, [0]) == (0x1F, None)


def test_mask_before_also_names_the_variable_the_id_was_written_to():
    and_stmt = W.Statement(0, 8, 0x2F,
                           [(0x00, 0x1F), (0x02, ATTR), (0x02, 0x6E82)])
    script = FakeScript([and_stmt])
    assert EK.mask_before(script, [0]) == (0x1F, 0x6E82)


def test_mask_before_ignores_an_and_on_a_different_address():
    and_stmt = W.Statement(0, 6, 0x2F, [(0x02, 0x1234), (0x00, 0x1F)])
    script = FakeScript([and_stmt])
    assert EK.mask_before(script, [0]) == (0x7F, None)


def test_mask_before_defaults_to_7f_with_no_and_on_the_route():
    compare = W.Statement(0, 4, 0x03, [(0x02, EDGE_FLAG)])
    script = FakeScript([compare])
    assert EK.mask_before(script, [0]) == (0x7F, None)


# ---------------------------------------------------------------------------
# squares_with() -- against a synthetic Geo, generated here, not copied
# ---------------------------------------------------------------------------

def _synthetic_geo(marked: list[tuple[int, int]], marked_id: int,
                   background_id: int) -> Geo:
    planes = bytearray(4 * 0x100)
    for i in range(0x100):
        planes[0x200 + i] = background_id
    for x, y in marked:
        planes[0x200 + y * 16 + x] = marked_id
    return Geo.from_bytes(bytes(planes))


def test_squares_with_finds_exactly_the_squares_carrying_the_id():
    marked = [(2, 3), (5, 5), (9, 9)]
    geo = _synthetic_geo(marked, marked_id=0, background_id=9)
    assert EK.squares_with(geo, 0x7F, 0) == marked


def test_squares_with_respects_the_mask():
    """`$20` reads as id 32 under `$7F` and id 0 under `$1F` -- the same
    square, two different ids, so `mask_before`'s result has to reach here
    for the right squares to come back."""
    geo = _synthetic_geo([(4, 4)], marked_id=0x20, background_id=5)
    assert EK.squares_with(geo, 0x7F, 0x20) == [(4, 4)]
    assert EK.squares_with(geo, 0x1F, 0x00) == [(4, 4)]


def test_squares_with_is_none_without_a_geo():
    assert EK.squares_with(None, 0x7F, 0) is None


def test_analyse_reports_the_squares_a_square_exit_fires_on():
    marked = [(1, 1), (2, 2)]
    geo = _synthetic_geo(marked, marked_id=0, background_id=5)
    sid = 0x6E82

    def block(asm):
        asm.raw(bytes([0x2F]) + _addr(ATTR) + _imm(127) + _addr(sid))
        asm.raw(bytes([0x25]) + _addr(sid) + _imm(1))
        asm.addr("ARM0")
        op_exit(asm)
        asm.label("ARM0")
        op_newecl(asm, 1)
    body = make_body(1, block)
    _script, (row,) = EK.analyse(TableMachine(), "TEST", "SIDE", body, geo)
    assert row["selector"] == "id"
    assert row["squares"] == marked


def entry1_table(asm):
    """Mask the square id, read the arm out of a table indexed by it, and
    `ONGOTO` on the arm, the way `ECL16` and `ECL17` do: id 5 reads arm 1,
    which leaves; id 1, the arm number itself, reads arm 0, which does not."""
    sid, arm = 0x6E82, 0x6E7A
    asm.raw(bytes([0x2F]) + _addr(ATTR) + _imm(31) + _addr(sid))
    op_table(asm, "ARMS", sid, arm)
    asm.raw(bytes([0x25]) + _addr(arm) + _imm(2))
    asm.addr("STAY")
    asm.addr("LEAVE")
    asm.label("STAY")
    op_exit(asm)
    asm.label("LEAVE")
    op_newecl(asm, 23)
    asm.label("ARMS")
    asm.raw(bytes([0, 0, 0, 0, 0, 1, 0, 0]))


def test_entry1s_table_names_the_square_whose_id_reads_the_arm():
    data = bytearray(GEO_SIZE)
    data[ATTRIBUTES + 0x43] = 5          # square id 5 at (3, 4) only
    data[ATTRIBUTES + 0x00] = 1          # id 1, the arm number, at (0, 0)
    body = make_body(1, entry1_table)
    _script, (row,) = EK.analyse(TableMachine(), "TEST", "SIDE", body,
                                 Geo(bytes(data)))
    assert row["kind"] == "square"
    assert row["index"] == 1
    assert row["selector"] == "id-table"
    assert 5 in row["ids"] and 1 not in row["ids"]
    assert row["squares"] == [(3, 4)]


def test_entry1s_ongoto_on_a_state_variable_names_no_square():
    """`ECL11`'s Nomad Camp exit: the selector comes from area state, not
    the square, so even the square carrying the arm number is no route."""
    data = bytearray(GEO_SIZE)
    data[ATTRIBUTES + 0x00] = 1

    def block(asm):
        asm.raw(bytes([0x2F]) + _addr(ATTR) + _imm(127) + _addr(0x6E82))
        asm.raw(bytes([0x2F]) + _addr(0x4A7C) + _imm(2) + _addr(0x6E79))
        asm.raw(bytes([0x25]) + _addr(0x6E79) + _imm(2))
        asm.addr("STAY")
        asm.addr("LEAVE")
        asm.label("STAY")
        op_exit(asm)
        asm.label("LEAVE")
        op_newecl(asm, 26)
    body = make_body(1, block)
    _script, (row,) = EK.analyse(TableMachine(), "TEST", "SIDE", body,
                                 Geo(bytes(data)))
    assert row["selector"] == "state"
    assert row["squares"] is None


# ---------------------------------------------------------------------------
# compare_index() / squares_for_test() -- a square id tested by `COMPARE`
# and a conditional jump rather than an `ONGOTO` arm (#255)
# ---------------------------------------------------------------------------

def test_compare_index_reads_a_literal_first_equality_test():
    """`COMPARE 26, [var]` then `IF=` -- the literal comes first, which is
    the operand order `ECL08 $9A41`'s real exit uses."""
    var = 0x6E82
    compare = W.Statement(0, 5, 0x03, [(0x00, 26), (0x02, var)])
    test = W.Statement(5, 6, 0x16, [])          # IF=
    script = FakeScript([compare, test])
    literal, op = EK.compare_index(script, [0, 5], var)
    assert (literal, op) == (26, "=")


def test_compare_index_flips_a_literal_first_inequality():
    """`COMPARE 29, [var]` then `IF>` means `29 > id`, i.e. `id < 29` -- the
    flip a literal-first `COMPARE` needs that an equality test does not."""
    var = 0x6E79
    compare = W.Statement(0, 5, 0x03, [(0x00, 29), (0x02, var)])
    test = W.Statement(5, 6, 0x19, [])          # IF>
    script = FakeScript([compare, test])
    literal, op = EK.compare_index(script, [0, 5], var)
    assert (literal, op) == (29, "<")


def test_compare_index_reads_a_variable_first_test_unflipped():
    """`COMPARE [var], 29` then `IF>` -- the variable comes first, the case
    `ECL05 $9C25`'s real exit uses, and needs no flip."""
    var = 0x6E79
    compare = W.Statement(0, 5, 0x03, [(0x02, var), (0x00, 29)])
    test = W.Statement(5, 6, 0x19, [])          # IF>
    script = FakeScript([compare, test])
    literal, op = EK.compare_index(script, [0, 5], var)
    assert (literal, op) == (29, ">")


def test_compare_index_is_none_without_a_masked_variable():
    """`mask_before` found no `AND` on the route, so there is no variable to
    look a `COMPARE` up against."""
    compare = W.Statement(0, 5, 0x03, [(0x00, 26), (0x02, 0x6E82)])
    script = FakeScript([compare])
    assert EK.compare_index(script, [0], None) == (None, None)


def test_compare_index_ignores_a_compare_on_an_unrelated_flag():
    """`ECL13 $996E`'s exit tests a quest flag, not the masked square id, and
    must not be read as one."""
    compare = W.Statement(0, 5, 0x03, [(0x00, 128), (0x02, 0x4A87)])
    test = W.Statement(5, 6, 0x16, [])
    script = FakeScript([compare, test])
    assert EK.compare_index(script, [0, 5], 0x6E82) == (None, None)


class CompareMachine:
    """Adds a destination operand to `AND` and a second operand to
    `COMPARE`, the form #255's exits need and no other test in this file
    uses -- kept off the shared `FakeMachine` so its own tests are untouched.
    """
    _COUNTS = {0x01: 1, 0x03: 2, 0x20: 1, 0x2F: 3}

    def operands(self, op):
        return self._COUNTS.get(op, 0)


def op_and3(asm, mask, dest):
    """`AND mask, $C04F, dest` -- the masked id, with its destination named
    as a third operand, which is what `mask_before` reads `dest` from."""
    asm.raw(bytes([0x2F, 0x00, mask, 0x02]) + ATTR.to_bytes(2, "little")
            + bytes([0x02]) + dest.to_bytes(2, "little"))


def op_compare_literal_first(asm, literal, var):
    asm.raw(bytes([0x03, 0x00, literal, 0x02]) + var.to_bytes(2, "little"))


def op_if(asm, opcode):
    asm.raw(bytes([opcode]))


def test_analyse_names_a_square_exit_gated_by_compare_instead_of_ongoto():
    """`#255 (tools/areas/eclexitkinds.py misses a square exit whose id is tested
    by COMPARE rather than ONGOTO)`: this route has no `ONGOTO` at all, only
    a masked `$C04F` and a `COMPARE`/`IF=`/`GOTO`, and the squares column
    used to stay empty for it."""
    marked = [(2, 2), (6, 6)]
    geo = _synthetic_geo(marked, marked_id=5, background_id=0)

    def block(asm):
        op_and3(asm, 0x7F, 0x6E82)
        op_compare_literal_first(asm, 5, 0x6E82)
        op_if(asm, 0x16)                       # IF=
        op_goto(asm, "TARGET")
        op_exit(asm)
        asm.label("TARGET")
        op_newecl(asm, 1)

    body = make_body(1, block)
    _script, rows = EK.analyse(CompareMachine(), "TEST", "SIDE", body, geo)
    assert len(rows) == 1
    row = rows[0]
    assert row["index"] == 5
    assert row["squares"] == marked


# ---------------------------------------------------------------------------
# the real totals -- what #207 (Run an exit's own handler before Fast Travel
# warps out) rests on, and the corrected tools/README.md row
# ---------------------------------------------------------------------------

@needs_disks
def test_the_79_exits_still_break_down_the_way_the_readme_row_says():
    every = W.scripts()
    if len(every) < 30:
        pytest.skip(f"only {len(every)} area scripts reachable; needs all 30")
    machine = W.Machine()
    kinds: collections.Counter = collections.Counter()
    features: collections.Counter = collections.Counter()
    total = 0
    for name, (side, body) in every.items():
        gside, gbody = W._file("GEO" + name[3:])
        geo = None
        if gbody is not None:
            try:
                geo = Geo.from_bytes(gbody)
            except Exception:                            # noqa: BLE001
                geo = None
        _script, rows = EK.analyse(machine, name, side, body, geo)
        for row in rows:
            kinds[row["kind"]] += 1
            for feature in row["features"]:
                features[feature] += 1
            total += 1
    assert total == 79
    assert dict(kinds) == {
        "edge": 14, "square": 43, "edge+square": 11,
        "entry1-unconditional": 4, "square-via-entry0": 6, "entry3": 1,
    }
    assert dict(features) == {
        "call": 41, "flag": 17, "text": 47, "position": 31,
        "combat": 5, "loadchar": 3, "menu": 28, "membership": 1,
    }


@needs_disks
def test_the_six_ungated_entry0_exits_name_what_their_scripts_test():
    """`ECL07` and `ECL10` loop over `(id, facing, action)` tables and leave
    from one square and facing each; the three travel-grid scripts test the
    window column and the heading, and name no `GEO` square."""
    every = W.scripts()
    machine = W.Machine()
    found = {}
    for name in ("ECL07", "ECL10", "ECL19", "ECL1A", "ECL1B"):
        if name not in every:
            pytest.skip(f"{name} not reachable on these disks")
        side, body = every[name]
        _gside, gbody = W._file("GEO" + name[3:])
        _script, rows = EK.analyse(machine, name, side, body,
                                   Geo.from_bytes(gbody))
        for row in rows:
            if row["kind"] == "square-via-entry0":
                found[(name, row["at"])] = (
                    row["target"], row["squares"], row.get("headings"),
                    row.get("grid"))
    assert found == {
        ("ECL07", 0x9AC9): (5, [(5, 7, 3)], None, None),
        ("ECL10", 0x9CD5): (27, [(8, 15, 2)], None, None),
        ("ECL19", 0x99B0): (26, None, [1, 2, 3], [(0x49C3, "=", 15)]),
        ("ECL1A", 0x99B4): (27, None, [1, 2, 3], [(0x49C3, "=", 15)]),
        ("ECL1A", 0x99E2): (25, None, [5, 6, 7], [(0x49C3, "=", 2)]),
        ("ECL1B", 0x99CE): (26, None, [5, 6, 7], [(0x49C3, "=", 2)]),
    }


@needs_disks
def test_ecl0bs_a20f_is_the_one_entry3_exit():
    """The exit the old README row's "edge or square" implied did not
    exist: reached only through entry 3, camp interrupted."""
    every = W.scripts()
    if "ECL0B" not in every:
        pytest.skip("ECL0B not reachable on these disks")
    machine = W.Machine()
    side, body = every["ECL0B"]
    gside, gbody = W._file("GEO0B")
    geo = Geo.from_bytes(gbody) if gbody is not None else None
    _script, rows = EK.analyse(machine, "ECL0B", side, body, geo)
    entry3 = [r for r in rows if r["kind"] == "entry3"]
    assert len(entry3) == 1
    assert entry3[0]["at"] == 0xA20F
    assert entry3[0]["entries"] == [3]


@needs_disks
def test_ecl14s_east_edge_exit_to_area_0_keeps_the_party_square_and_facing():
    """`route_pool.POOL.edge_exits` says a step east off the Slums lands in area 0 on the wrapped square."""
    every = W.scripts()
    if "ECL14" not in every:
        pytest.skip("ECL14 not reachable on these disks")
    side, body = every["ECL14"]
    script = W.Script(W.Machine(), "ECL14", side, body)
    (exit_, block), = [(s, b) for s, b in script.exits() if s.operands[0] == (0, 0)]
    assert int("ECL14"[3:], 16) == 20  # the script file for area 0x14 is the Slums
    assert "COMPARE [$C04D], 1" in [str(s) for s in block]
    # Any opcode might write memory and most have no name here, so no operand of any statement
    # in the block may address the position bytes, apart from the COMPARE that only reads them.
    position = {0xC04B, 0xC04C, 0xC04D}
    touching = [str(s) for s in block if s.op != 0x03
                and any(kind not in (0x00, 0x02, 0x80) and value in position
                        for kind, value in s.operands)]
    assert touching == []


def facing_entry0(asm):
    """Leave east off the map and stay put facing any other way, the way
    `ECL02`, `ECL0E` and `ECL12` switch on `$C04D` behind the edge gate."""
    op_compare(asm, EDGE_FLAG, 0)
    op_bare(asm, 0x16)
    op_exit(asm)
    asm.raw(bytes([0x25]) + _addr(EK.FACING) + _imm(4))
    for arm in ("STAY", "LEAVE", "STAY", "STAY"):
        asm.addr(arm)
    asm.label("STAY")
    op_exit(asm)
    asm.label("LEAVE")
    op_newecl(asm, 15)


def test_an_edge_exit_on_the_facing_names_the_edge_it_leaves_not_square_id_1():
    data = bytearray(GEO_SIZE)
    data[ATTRIBUTES + 0x11] = 1          # id 1, the arm number, at (1, 1)
    body = make_body(0, facing_entry0)
    _script, rows = EK.analyse(TableMachine(), "TEST", "SIDE", body,
                               Geo(bytes(data)))
    row, = rows
    assert row["kind"] == "edge+square"
    assert row["index"] == 1
    assert row["facings"] == [1]
    assert row.get("choice") is None
    assert row["squares"] == [(15, y, 1) for y in range(16)]


def choice_entry0(asm):
    """Leave by any edge on the first answer to a menu, the way `ECL15`
    switches on `$6E79`."""
    op_compare(asm, EDGE_FLAG, 0)
    op_bare(asm, 0x16)
    op_exit(asm)
    asm.raw(bytes([0x25]) + _addr(EK.ONCHOICE) + _imm(2))
    asm.addr("LEAVE")
    asm.addr("STAY")
    asm.label("STAY")
    op_exit(asm)
    asm.label("LEAVE")
    op_newecl(asm, 0)


def test_an_edge_exit_on_a_menu_answer_leaves_by_every_edge():
    body = make_body(0, choice_entry0)
    _script, rows = EK.analyse(TableMachine(), "TEST", "SIDE", body,
                               Geo(bytes(GEO_SIZE)))
    row, = rows
    assert row["kind"] == "edge+square"
    assert row["facings"] == [0, 1, 2, 3]
    assert row["choice"] == (EK.ONCHOICE, [0])
    assert len(row["squares"]) == 64     # 60 edge squares, corners twice
    assert all(d in EK.outward_facings(x, y) for x, y, d in row["squares"])


@needs_disks
def test_the_eleven_edge_exits_name_the_facing_or_answer_their_scripts_test():
    """`ECL02`, `ECL0E` and `ECL12` switch on the facing `$C04D` behind the
    edge gate, arm N/E/S/W, and `ECL15` on the answer `$6E79` to its menu, so
    every exit leaves from the edge its facing points off, open on that side,
    never from a square whose id is the arm number."""
    every = W.scripts()
    machine = W.Machine()
    found = {}
    for name in ("ECL02", "ECL0E", "ECL12", "ECL15"):
        if name not in every:
            pytest.skip(f"{name} not reachable on these disks")
        side, body = every[name]
        _gside, gbody = W._file("GEO" + name[3:])
        _script, rows = EK.analyse(machine, name, side, body,
                                   Geo.from_bytes(gbody))
        for row in rows:
            if row["kind"] == "edge+square":
                found[(name, row["at"])] = (
                    row["target"], row["facings"], row.get("choice"),
                    row["squares"])
    assert found == {
        ("ECL02", 0x9985): (18, [0], None, [(4, 0, 0), (11, 0, 0)]),
        ("ECL02", 0x998F): (15, [1], None,
                            [(15, 3, 1), (15, 4, 1), (15, 11, 1)]),
        ("ECL02", 0x9999): (26, [3], None, [(0, 3, 3), (0, 4, 3), (0, 11, 3)]),
        ("ECL0E", 0x9960): (26, [0], None, [(4, 0, 0), (11, 0, 0)]),
        ("ECL0E", 0x9976): (26, [1], None, [(15, 4, 1), (15, 11, 1)]),
        ("ECL0E", 0x9983): (24, [2], None, [(4, 15, 2), (11, 15, 2)]),
        ("ECL12", 0x99EC): (9, [0], None, [(4, 0, 0), (11, 0, 0)]),
        ("ECL12", 0x99F6): (29, [1], None, [(15, 4, 1), (15, 11, 1)]),
        ("ECL12", 0x9A00): (2, [2], None, [(4, 15, 2), (11, 15, 2)]),
        ("ECL12", 0x9A16): (26, [3], None, [(0, 4, 3), (0, 11, 3)]),
        ("ECL15", 0x998F): (0, [0, 1, 2, 3], (EK.ONCHOICE, [0]),
                            [(7, 15, 2), (8, 15, 2)]),
    }


def _rows(name):
    every = W.scripts()
    if name not in every:
        pytest.skip(f"{name} not reachable on these disks")
    side, body = every[name]
    _gside, gbody = W._file("GEO" + name[3:])
    _script, rows = EK.analyse(W.Machine(), name, side, body,
                               Geo.from_bytes(gbody))
    return {row["at"]: row for row in rows}


@needs_disks
def test_yarashs_pyramid_exits_stand_on_the_squares_their_tables_name():
    """`ECL16` and `ECL17` read the entry-1 arm out of a table indexed by the
    square id: the exits run from (13,15), (14,7) and (6,0), not from the
    squares carrying the arm number, (15,15), (4,10) and (2,11)."""
    upper, lower = _rows("ECL16"), _rows("ECL17")
    assert upper[0xA60F]["selector"] == "id-table"
    assert upper[0xA60F]["squares"] == [(13, 15)]
    assert upper[0xA62D]["squares"] == [(14, 7)]
    assert lower[0x9E1A]["selector"] == "id-table"
    assert lower[0x9E1A]["squares"][0] == (6, 0)
    assert (2, 11) not in lower[0x9E1A]["squares"]


@needs_disks
def test_the_nomad_camp_exit_has_no_square():
    """`ECL11` picks the arm from `$4A7C` and the hour, then a `RANDOM 3`."""
    row = _rows("ECL11")[0xA1F3]
    assert (row["target"], row["selector"], row["squares"]) == (26, "state",
                                                                None)
