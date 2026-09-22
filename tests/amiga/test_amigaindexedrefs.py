"""`tools/amiga/amigaindexedrefs.py` finds the two ways an Amiga executable
reaches a record byte that `tools/amiga/amigarecordrefs.py`'s displacement
search cannot see: the indexed form `d8(An,Xn)` and a base register set by
`lea`.  A wrong `BACK` offset or a wrong `INDEXED` pattern would mis-scan
every executable unseen, so this pins both against hand-built instructions
rather than a disk.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

# `tools.amiga.amigaindexedrefs` imports capstone at module scope, and
# capstone is not a declared dependency: this skip has to come before that
# import.
pytest.importorskip("capstone")

from support.hunks import hunk_file, pad4  # noqa: E402

from tools.amiga import amiga68k, amigaindexedrefs  # noqa: E402

RTS = b"\x4e\x75"

#: `move.b $44(a3, d0.w), d1`: a brief extension word, D/A=0 (Dn), index
#: register D0, size word, displacement byte 0x44.  Kept below 0x80 so the
#: displacement decodes as a positive byte rather than a negative one -- a
#: displacement of 0x84 disassembles as `-$7c(...)`, which the tool's own
#: `INDEXED` pattern never matches, so no site above 0x7f can ever be found.
INDEXED_44 = bytes.fromhex("12330044")

#: The same indexed form at a different displacement: a decoy that must be
#: found when searched for on its own and never found under 0x44's search.
INDEXED_50 = bytes.fromhex("12330050")

#: `lea $8c(a3), a4`.
LEA_8C = bytes.fromhex("49EB008C")

#: `lea $88(a3), a4`: a base 0x10 below 0x98, kept out of a `--reach 4`
#: search that reaches only as far as 0x8C.
LEA_88 = bytes.fromhex("49EB0088")


def code_hunk() -> bytes:
    """One CODE hunk: an indexed read at 0x44, a decoy at 0x50, and two
    `lea` bases below 0x90, one within a reach of 4 and one outside it."""
    body = pad4(RTS + INDEXED_44 + INDEXED_50 + LEA_8C + LEA_88 + RTS)
    return hunk_file([(amiga68k.HUNK_CODE, body, [])])


def _file_offset(data: bytes) -> int:
    return amiga68k.Executable.parse(data).by_number(0).file_offset


def test_the_indexed_site_at_its_own_displacement_is_found():
    data = code_hunk()
    fo = _file_offset(data)
    assert amigaindexedrefs.indexed_sites(data, 0x44) == \
        [(fo + 2, 0, "move.b $44(a3, d0.w), d1")]


def test_a_different_displacement_is_not_matched_by_the_wrong_search():
    data = code_hunk()
    fo = _file_offset(data)
    # The decoy is a real indexed site, just not one at 0x44 -- searched on
    # its own displacement it is found.
    assert amigaindexedrefs.indexed_sites(data, 0x50) == \
        [(fo + 6, 0, "move.b $50(a3, d0.w), d1")]
    # Searched at 0x44, only the 0x44 site comes back.
    found = amigaindexedrefs.indexed_sites(data, 0x44)
    assert len(found) == 1
    assert found[0][2] == "move.b $44(a3, d0.w), d1"


def test_a_lea_base_within_reach_is_found_and_further_below_is_not():
    data = code_hunk()
    fo = _file_offset(data)
    assert amigaindexedrefs.lea_bases(data, 0x90, reach=4) == \
        [(fo + 10, 0, 0x8C, "lea.l $8c(a3), a4")]


def test_widening_the_reach_picks_up_the_base_that_was_out_of_range():
    data = code_hunk()
    fo = _file_offset(data)
    bases = amigaindexedrefs.lea_bases(data, 0x90, reach=8)
    assert bases == [(fo + 10, 0, 0x8C, "lea.l $8c(a3), a4"),
                      (fo + 14, 0, 0x88, "lea.l $88(a3), a4")]
