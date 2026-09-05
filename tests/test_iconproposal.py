"""`tools/iconproposal.py` reads its three tables from YAML, not Python (#130).

`#130 (A converted DOS party arrives with six identical combat figures, not
its own)`'s proposal used to live as three Python literals inside
`tools/iconproposal.py`. Donald asked for a YAML file he can edit by hand
instead, with `tools/iconproposal.py` reading it and `--markdown` generating
the judged document from it -- so `tools/iconproposal.yaml` is now the single
source, and this is where that is checked.

These tests pin the **shape** of the file rather than the matches in it: every
DOS figure has a row, every row names a C64 option, and all sixteen EGA
colours map to one of the C64's eight. The matches themselves are Donald's
judgement and change whenever he edits the file, which is what it is for.
"""

from __future__ import annotations

import contextlib
import io
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))

import iconproposal as ip  # noqa: E402

#: The shape of the proposal, which does not change when Donald edits it.
#:
#: **These deliberately do not pin the values.** An earlier version of this
#: file held the whole table as it stood in Python before the move to YAML and
#: asserted the two were equal, which was the right check for the migration
#: and the wrong one to leave behind: `tools/iconproposal.yaml` exists for
#: Donald to edit, so a test demanding it still equal the old Python turns his
#: first edit into a red build. It did -- he moved DOS weapon 2 from C64 5 to
#: 10 and CI went red on the migration oracle (#130).
#:
#: What is worth pinning is the shape: every DOS figure has a row, every row
#: names a C64 option that exists, and the colour table covers all sixteen EGA
#: entries. Those stay true however he rearranges the matches.
DOS_WEAPONS = 32
DOS_HEADS = 14
EGA_COLOURS = 16
C64_COLOURS = 8


def test_the_yaml_file_exists_beside_the_tool():
    assert ip.TABLE_PATH.name == "iconproposal.yaml"
    assert ip.TABLE_PATH.is_file()


def test_every_dos_weapon_has_a_row_naming_a_real_c64_option():
    weapons, alternatives, _, _, _ = ip.load_tables()
    assert sorted(weapons) == list(range(DOS_WEAPONS))
    assert all(isinstance(v, int) and v >= 0 for v in weapons.values())
    for dos_index, alts in alternatives.items():
        assert dos_index in weapons, dos_index
        assert all(isinstance(a, int) and a >= 0 for a in alts), dos_index


def test_every_dos_head_has_a_row_naming_a_real_c64_option():
    _, _, heads, alternatives, _ = ip.load_tables()
    assert sorted(heads) == list(range(DOS_HEADS))
    assert all(isinstance(v, int) and v >= 0 for v in heads.values())
    for dos_index, alts in alternatives.items():
        assert dos_index in heads, dos_index
        assert all(isinstance(a, int) and a >= 0 for a in alts), dos_index


def test_every_ega_colour_maps_to_one_the_c64_has():
    _, _, _, _, ega_to_c64 = ip.load_tables()
    assert len(ega_to_c64) == EGA_COLOURS
    assert all(0 <= c < C64_COLOURS for c in ega_to_c64), ega_to_c64


def test_forty_six_rows_total_between_weapons_and_heads():
    weapons, _, heads, _, _ = ip.load_tables()
    assert len(weapons) + len(heads) == DOS_WEAPONS + DOS_HEADS == 46


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


def test_a_malformed_yaml_row_is_caught_by_the_type(tmp_path):
    """A non-dict row (a bare number, the old Python shape) fails loudly.

    `tmp_path` rather than `tempfile.mkstemp`: the latter hands back an open
    descriptor as well as a path, and on Windows a file already open cannot
    be opened again -- `PermissionError: [WinError 32]`, which is what this
    test did on both Windows jobs in CI and on neither Linux one.
    """
    bad = tmp_path / "malformed.yaml"
    bad.write_text("weapons:\n  0: 5\nheads:\n  0: {c64: 7}\ncolours:\n"
                   + "\n".join(f"  {i}: {{c64: 0}}" for i in range(16)))
    with pytest.raises(TypeError):
        ip.load_tables(bad)
