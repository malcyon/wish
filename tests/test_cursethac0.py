"""What Curse's own overlays do with the stored THAC0, and what the tool stages.

`#368 (Does the C64 Curse engine read thac0_current in a fight, since the
training hall overwrites it with the base and loses the strength bonus?)`.
The answer rests on three instructions in `LIBRARY` and on an absence in
`COMBAT`, and both halves are read off the player's own disks here rather
than remembered from a document -- a citation nobody re-derives is a citation
that rots.

`docs/205-the-c64-thac0-rebuild.md` is the write-up.
"""
from __future__ import annotations

import sys

import pytest

sys.path.insert(0, ".")

from goldbox.d64 import split_load_address  # noqa: E402
from tests import gamedata  # noqa: E402
from tools import cursethac0  # noqa: E402
from tools.recordsweep import hits  # noqa: E402

#: `LINKER` puts an overlay's payload at `$0800` and `LIBRARY`'s at `$2DC8`
#: in Curse and Silver Blades alike (`docs/40-memory-map.md`).  The PRG
#: header says `$1220` and `$3000` respectively and is a family stamp.
LIBRARY_BASE = 0x2DC8
OVERLAY_BASE = 0x0800


def library() -> bytes:
    """Curse's `LIBRARY` payload, header off, off whichever side carries it."""
    _, body = split_load_address(gamedata.curse_file("LIBRARY"))
    return body


def at(body: bytes, address: int, length: int, base: int = LIBRARY_BASE):
    return body[address - base:address - base + length]


def test_the_roster_rebuild_starts_from_thac0_base():
    """`LIBRARY $393C` puts `thac0_base` straight over `thac0_current`.

    Two instructions -- `LDA $7C71` then `STA $7D0E` -- and they are the
    whole answer to the ticket: record `0x071` is the input and record
    `0x10E` is the output, so nothing the training hall left in `0x10E` can
    reach an attack roll.
    """
    assert at(library(), 0x393C, 6) == bytes.fromhex("AD717C 8D0E7D".replace(" ", ""))


def test_the_strength_gate_decides_which_row_of_the_tables_is_read():
    """`LIBRARY $394B`: `LDX $7CE3 / BEQ +3 / LDX $7CE2`.

    With `strength_bonus_flag` at `0x0E3` clear the branch is taken and the
    index stays 0, which is the zero row of both tables.  That is
    `#277 (A DOS character converted to the C64 loses the strength bonus to
    hit and damage, because 0x0E3 is written zero)` in three instructions.
    """
    assert at(library(), 0x394B, 8) == bytes.fromhex("AEE37C F003 AEE27C".replace(" ", ""))


@pytest.mark.parametrize("index, to_hit, damage", [
    (0, 0, 0),        # the row a clear gate lands on
    (17, 1, 1),       # strength 17
    (18, 1, 2),       # strength 18
    (20, 2, 3),       # 18(51-75)
    (23, 3, 6),       # 18(00)
])
def test_the_strength_tables_are_the_players_handbook_rows(index, to_hit, damage):
    """`$3840` to hit and `$385F` damage, indexed by `strength_index`.

    Only five of the thirty-one rows are read back, and they are the ones
    this issue's party lands on plus the zero row -- a whole table copied
    into a test would be the game's data under a new name.
    """
    body = library()

    def signed(table: int) -> int:
        byte = at(body, table + index, 1)[0]
        return byte - 256 if byte > 127 else byte

    assert (signed(0x3840), signed(0x385F)) == (to_hit, damage)


@pytest.mark.parametrize("overlay", ["COMBAT", "COMBAT2", "COM.PREP"])
def test_no_combat_overlay_names_the_stored_thac0(overlay):
    """The fight never mentions `$7D0E` -- the absence the ticket turns on.

    An overlay that read the stored byte would hold an absolute-mode
    instruction naming it, wherever the file runs, because an absolute
    operand carries its own target.  All three hold none, against fourteen
    in `LIBRARY`.
    """
    _, body = split_load_address(gamedata.curse_file(overlay))
    assert list(hits(body, {0x7D0E})) == []


def test_library_is_the_only_overlay_that_writes_the_stored_thac0():
    """And it writes it far more often than it reads it.

    Fourteen references, one of them the sheet's `LDA $7D0E` at `$3758`; the
    rest are the two rebuilds.  The count is asserted rather than the list,
    because the list is the game's code and the count is a measurement.
    """
    found = list(hits(library(), {0x7D0E}))
    assert len(found) == 14
    assert sum(1 for _, mnemonic, _, _ in found if mnemonic == "STA") == 7


# -- the staging half, which is ours and needs no disks ---------------------

def a_payload() -> bytearray:
    """A `SAVEAZURE`-shaped block of our own bytes, two slots filled in."""
    body = bytearray(0x1D00)
    for slot, (name, base, index, gate, roster) in enumerate(
            [(b"MARK", 44, 20, 0, 46), (b"MATHEW", 45, 23, 0, 47)]):
        rec = cursethac0.SLOT0 + slot * cursethac0.SLOT_STRIDE
        body[rec + cursethac0.THAC0_BASE] = base
        body[rec + cursethac0.STRENGTH_INDEX] = index
        body[rec + cursethac0.STRENGTH_GATE_BYTE] = gate
        body[cursethac0.NAMES_AT + slot * cursethac0.NAME_SIZE:
             cursethac0.NAMES_AT + slot * cursethac0.NAME_SIZE + len(name)] = name
        ros = cursethac0.ROSTER_AT + slot * cursethac0.ROSTER_STRIDE
        body[ros + cursethac0.ROSTER_THAC0] = roster
    return body


def test_the_names_come_off_curses_own_sixteen_byte_table():
    """Not `goldbox.layout.NAME_SIZE`, which is the record head's twenty.

    The first run of this tool read slot 1 as `A` and put MATHEW's spoiled
    byte in MARK's block, because it used the record's width for the name
    table's.
    """
    assert cursethac0.slot_names(a_payload())[:2] == ["MARK", "MATHEW"]


def test_spoiling_changes_the_roster_byte_and_leaves_the_record_alone():
    body = a_payload()
    before = bytes(body)
    outcome = cursethac0.spoil(body, 1)
    assert outcome["before"]["roster_thac0"] == 47
    assert outcome["after"]["roster_thac0"] == cursethac0.SPOIL_THAC0
    differ = [i for i, (a, b) in enumerate(zip(before, body)) if a != b]
    assert differ == [cursethac0.ROSTER_AT + cursethac0.ROSTER_STRIDE
                      + cursethac0.ROSTER_THAC0]


def test_forcing_the_gate_is_a_second_byte_and_a_second_slot():
    body = a_payload()
    before = bytes(body)
    cursethac0.spoil(body, 0, gate=1)
    differ = [i for i, (a, b) in enumerate(zip(before, body)) if a != b]
    assert differ == [cursethac0.SLOT0 + cursethac0.STRENGTH_GATE_BYTE,
                      cursethac0.ROSTER_AT + cursethac0.ROSTER_THAC0]
    assert cursethac0.read_block(body, 0)["strength_gate"] == 1


def test_the_spoiled_value_is_outside_anything_the_engine_can_compute():
    """THAC0 50 against a table whose worst row is 39 less a penalty of 3.

    A staged value inside the range the engine can produce proves nothing,
    because the reader cannot tell it from the engine's own answer.
    """
    assert cursethac0.SPOIL_THAC0 < 36
    assert cursethac0.COMBAT_BIAS - cursethac0.SPOIL_THAC0 == 50


@pytest.mark.parametrize("text, want", [
    ("MATHEW", ("MATHEW", None, None)),
    ("MARK:gate=1", ("MARK", 1, None)),
    ("MARK:gate=0", ("MARK", 0, None)),
    ("MARK:gate=1,xp=46000", ("MARK", 1, 46000)),
])
def test_the_spoil_argument_parses(text, want):
    assert cursethac0.parse_spoil(text) == want


def test_staging_experience_is_a_third_byte_range_and_nothing_else():
    """The hall refuses a character who cannot advance, so the training half
    of the question needs an experience total as an input.  It has to move
    three bytes and no others."""
    body = a_payload()
    before = bytes(body)
    cursethac0.spoil(body, 0, gate=1, xp=46000)
    differ = [i for i, (a, b) in enumerate(zip(before, body)) if a != b]
    at = cursethac0.SLOT0 + cursethac0.EXPERIENCE
    assert differ == [cursethac0.SLOT0 + cursethac0.STRENGTH_GATE_BYTE,
                      at, at + 1,
                      cursethac0.ROSTER_AT + cursethac0.ROSTER_THAC0]
    assert int.from_bytes(body[at:at + 3], "little") == 46000
