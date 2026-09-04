"""`tools/bamsweep.py`'s byte-range comparison, on a buffer built here rather
than off a disk -- `check()` and `describe()` are pure byte matching and need
no disk image. `pytest tests/test_bamsweep.py` runs with zero skips.

`docs/10-disk-format.md` quotes "73 of 79" and "79 of 79" on this tool's word
alone; `test_the_fixed_table_matches_the_documented_layout` pins the table
those counts are measured against, so an edit that shifts a byte range shows
up here rather than only in a number nobody rechecks.

The precedent is `tests/test_recordsweep.py`, which tests
`tools/recordsweep.py`'s `hits()` and `indirect_hits()` the same way.
"""
from __future__ import annotations

from tools.bamsweep import FIXED, check, describe

# --------------------------------------------------------------------------
# describe() -- the fix for "3241" where the header means "2A"
# --------------------------------------------------------------------------

def test_describe_renders_short_ascii_bytes_as_text():
    """`b"2A"` is the literal ASCII bytes '2' and 'A' -- the DOS-type field."""
    assert describe(b"2A") == "2A"


def test_describe_falls_back_to_hex_for_a_pad_run():
    """`$A0` is PETSCII shifted space, not printable ASCII: stays hex."""
    assert describe(b"\xa0\xa0") == "a0a0"


def test_describe_falls_back_to_hex_for_bytes_outside_ascii():
    assert describe(bytes([0x00, 0xFF])) == "00ff"


def test_describe_falls_back_to_hex_past_four_bytes_even_if_printable():
    assert describe(b"HELLO") == "48454c4c4f"


# --------------------------------------------------------------------------
# the FIXED table -- pinned, so a shifted range breaks this test and not
# only a doc count nobody reruns
# --------------------------------------------------------------------------

def test_the_fixed_table_matches_the_documented_layout():
    assert FIXED == (
        ("pad", 160, 161, b"\xa0\xa0"),
        ("pad", 164, 164, b"\xa0"),
        ("dos", 165, 166, b"2A"),
        ("pad", 167, 170, b"\xa0" * 4),
        ("nulls", 171, 255, bytes(85)),
    )


def _well_formed_header() -> bytearray:
    """144-255, all of it -- the whole disk header `header()` returns.

    Byte 144 is the header's own offset 0; every FIXED range below is placed
    at `first - 144` the same way `check()` computes it.
    """
    head = bytearray(112)
    head[0:16] = b"A DISK NAME     "        # 144-159, not checked
    head[18:20] = b"01"                     # 162-163, the id, not checked
    head[160 - 144:162 - 144] = b"\xa0\xa0"
    head[164 - 144:165 - 144] = b"\xa0"
    head[165 - 144:167 - 144] = b"2A"
    head[167 - 144:171 - 144] = b"\xa0" * 4
    head[171 - 144:256 - 144] = bytes(85)
    return head


# --------------------------------------------------------------------------
# check() -- the comparison loop `main` runs per image, isolated from disk IO
# --------------------------------------------------------------------------

def test_check_agrees_on_every_range_of_a_well_formed_header():
    agree, odd = check(bytes(_well_formed_header()))
    assert odd == []
    assert agree == {(160, 161): True, (164, 164): True, (165, 166): True,
                      (167, 170): True, (171, 255): True}


def test_check_flags_the_dos_type_when_it_is_not_2a():
    head = _well_formed_header()
    head[165 - 144:167 - 144] = b"\x00\x00"
    agree, odd = check(bytes(head))
    assert agree[165, 166] is False
    assert odd == ["165-166 is 0000, not 2A"]


def test_check_reports_a_mismatch_in_ascii_when_the_bytes_are_printable():
    """The regression `describe()` exists for: a wrong-but-readable DOS type
    prints as text, not as an unreadable hex run."""
    head = _well_formed_header()
    head[165 - 144:167 - 144] = b"4A"
    agree, odd = check(bytes(head))
    assert odd == ["165-166 is 4A, not 2A"]


def test_check_flags_a_short_pad_run():
    head = _well_formed_header()
    head[167 - 144:171 - 144] = b"\xa0\xa0\xa0\x00"
    agree, odd = check(bytes(head))
    assert agree[167, 170] is False
    assert odd == ["167-170 is a0a0a000, not a0a0a0a0"]


def test_check_flags_a_stray_byte_in_the_null_run():
    head = _well_formed_header()
    head[171 - 144 + 40] = 0x01
    agree, odd = check(bytes(head))
    assert agree[171, 255] is False
    assert len(odd) == 1 and odd[0].startswith("171-255 is ")


def test_check_is_byte_range_only_and_does_not_look_at_the_label():
    """A range's own label plays no part in the comparison -- only its
    first/last bytes and the bytes `head` actually carries there."""
    head = bytes(_well_formed_header())
    fixed = (("renamed", 165, 166, b"2A"),)
    agree, odd = check(head, fixed=fixed)
    assert agree == {(165, 166): True}
    assert odd == []
