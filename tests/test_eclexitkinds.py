"""`tools/eclexitkinds.py`'s exit classification, on scripts built here rather
than off a disk, plus the real totals it produces from the thirty area
scripts.

The classifier -- `ongoto_index`, `mask_before`, `features`, `squares_with`
and `analyse` itself -- is pure logic once it has a `Script` and (optionally)
a `Geo`; neither needs a disk, so `FakeMachine` stands in for the real
`eclwalk.Machine`, which reads its opcode tables out of `DUNGEON`. What that
machine reads is not reproduced here -- only the operand counts this file's
own synthetic scripts need are declared, none of them copied off a disk.

`test_the_79_exits_still_break_down_the_way_the_readme_row_says` is the
precedent `tests/test_questflags.py` sets for `tools/eclflags.py`: the real
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

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox.geo import Geo  # noqa: E402
from tests.gamedata import needs_disks  # noqa: E402
from tools import eclexitkinds as EK  # noqa: E402
from tools import eclwalk as W  # noqa: E402

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
    """`ECL0B`'s `$A20F` is this shape on the real disks: only entry 3."""
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
    assert EK.mask_before(script, [0]) == 0x1F


def test_mask_before_ignores_an_and_on_a_different_address():
    and_stmt = W.Statement(0, 6, 0x2F, [(0x02, 0x1234), (0x00, 0x1F)])
    script = FakeScript([and_stmt])
    assert EK.mask_before(script, [0]) == 0x7F


def test_mask_before_defaults_to_7f_with_no_and_on_the_route():
    compare = W.Statement(0, 4, 0x03, [(0x02, EDGE_FLAG)])
    script = FakeScript([compare])
    assert EK.mask_before(script, [0]) == 0x7F


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

    def block(asm):
        op_ongoto(asm, ["ARM0"])
        op_exit(asm)
        asm.label("ARM0")
        op_newecl(asm, 1)
    row = analyse_one(1, block, geo=geo)
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
