"""`tools/iconproposal.py` reads its three tables from YAML, not Python (#130).

`#130 (A converted DOS party arrives with six identical combat figures, not
its own)`'s proposal used to live as three Python literals inside
`tools/iconproposal.py`. Donald asked for a YAML file he can edit by hand
instead, with `tools/iconproposal.py` reading it and `--markdown` generating
the judged document from it -- so `tools/iconproposal.yaml` is now the single
source, and this is where that is checked.

The numbers below are the proposal exactly as it stood in Python before the
move, copied here once as an independent oracle. If `tools/iconproposal.yaml`
or `load_tables` silently drops or renumbers a row, this is what catches it --
these tests fail without the YAML file being read correctly, which is the
"prove it fails" half of moving the data.
"""

from __future__ import annotations

import contextlib
import io
import pathlib
import sys
import tempfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))

import iconproposal as ip  # noqa: E402

# The proposal as it stood in Python, before the move to YAML (#130).
OLD_WEAPONS = {
    0: 0, 1: 26, 2: 5, 3: 23, 4: 24, 5: 21, 6: 27, 7: 1, 8: 25, 9: 8,
    10: 10, 11: 23, 12: 27, 13: 27, 14: 15, 15: 7, 16: 28, 17: 14, 18: 11,
    19: 13, 20: 17, 21: 6, 22: 9, 23: 12, 24: 3, 25: 22, 26: 12, 27: 32,
    28: 31, 29: 34, 30: 29, 31: 30,
}

OLD_WEAPON_ALTERNATIVES = {
    2: (27,), 5: (14,), 6: (5,), 8: (19,), 11: (25,), 12: (5,), 13: (5,),
    14: (10,), 15: (11,), 17: (2,), 18: (13,), 19: (4,), 20: (12,),
    21: (20,), 23: (24,), 25: (24,), 26: (17,), 27: (34,), 29: (32,),
}

OLD_HEADS = {
    0: 7, 1: 11, 2: 16, 3: 3, 4: 8, 5: 5, 6: 14, 7: 11, 8: 17, 9: 12,
    10: 10, 11: 6, 12: 0, 13: 13,
}

OLD_HEAD_ALTERNATIVES = {
    0: (1,), 1: (3,), 2: (15, 22), 3: (15,), 4: (21, 0), 6: (2, 9),
    8: (12,), 9: (17,), 10: (15,), 12: (2,), 13: (16,),
}

OLD_EGA_TO_C64 = (0, 6, 5, 3, 2, 4, 7, 1, 0, 6, 5, 3, 2, 4, 7, 1)


def test_the_yaml_file_exists_beside_the_tool():
    assert ip.TABLE_PATH.name == "iconproposal.yaml"
    assert ip.TABLE_PATH.is_file()


def test_every_weapon_row_and_alternative_came_across_unchanged():
    weapons, alternatives, _, _, _ = ip.load_tables()
    assert len(weapons) == 32 == len(OLD_WEAPONS)
    assert weapons == OLD_WEAPONS
    assert len(alternatives) == 19 == len(OLD_WEAPON_ALTERNATIVES)
    assert alternatives == OLD_WEAPON_ALTERNATIVES


def test_every_head_row_and_alternative_came_across_unchanged():
    _, _, heads, alternatives, _ = ip.load_tables()
    assert len(heads) == 14 == len(OLD_HEADS)
    assert heads == OLD_HEADS
    assert len(alternatives) == 11 == len(OLD_HEAD_ALTERNATIVES)
    assert alternatives == OLD_HEAD_ALTERNATIVES


def test_all_sixteen_colours_came_across_unchanged():
    _, _, _, _, ega_to_c64 = ip.load_tables()
    assert len(ega_to_c64) == 16 == len(OLD_EGA_TO_C64)
    assert ega_to_c64 == OLD_EGA_TO_C64


def test_forty_six_rows_total_between_weapons_and_heads():
    weapons, _, heads, _, _ = ip.load_tables()
    assert len(weapons) + len(heads) == 46


def test_the_module_level_tables_are_what_load_tables_returns():
    """`WEAPONS` etc. are loaded once at import time, from the same file."""
    weapons, weapon_alt, heads, head_alt, ega = ip.load_tables()
    assert ip.WEAPONS == weapons
    assert ip.WEAPON_ALTERNATIVES == weapon_alt
    assert ip.HEADS == heads
    assert ip.HEAD_ALTERNATIVES == head_alt
    assert ip.EGA_TO_C64 == ega


def test_from_markdown_is_gone():
    """The round trip this replaces must not come back (#130)."""
    assert not hasattr(ip, "read_markdown")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.suppress(SystemExit):
        ip.main(["--help"])
    assert "--from-markdown" not in buf.getvalue()


def test_a_malformed_yaml_row_is_caught_by_the_type():
    """A non-dict row (a bare number, the old Python shape) fails loudly."""
    bad = pathlib.Path(tempfile.mkstemp(suffix=".yaml")[1])
    try:
        bad.write_text("weapons:\n  0: 5\nheads:\n  0: {c64: 7}\ncolours:\n"
                       + "\n".join(f"  {i}: {{c64: 0}}" for i in range(16)))
        with pytest.raises(TypeError):
            ip.load_tables(bad)
    finally:
        bad.unlink()
