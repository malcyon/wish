"""`tools/dosfigures.py` asks `IconParts.size_for` for the large-list
promotion rule, rather than keeping a third copy of its arithmetic.

`#328 (A third copy of the large-list promotion rule sits in
tools/dosfigures.py, which is the defect #325 was)`: `mixed_png`'s
`big = (option >= (small_heads if kind == "head" else small_weapons))` was a
hand-written copy of `goldbox.iconparts.IconParts.size_for`'s own rule --
`#325 (The small head sheet will not draw at all, because two of its rows
use a head the small list does not have)`'s crash, one copy earlier, was
`tools/iconproposal.py` writing the same arithmetic and forgetting the head
half of it. `mixed_rows` is the promotion decision pulled out of `mixed_png`
so it can be checked directly, without drawing anything.
"""

from __future__ import annotations

import pathlib
import sys

import pytest
from gamedata import disk_dir

from goldbox.iconparts import IconParts, dos_icon_tables

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))

import dosfigures as df  # noqa: E402

needs_disks = pytest.mark.skipif(disk_dir() is None,
                                 reason="needs the game disks")


@pytest.fixture(scope="module")
def parts() -> IconParts:
    """The option tables, off whichever disk carries `SPELLE64`/`SPELLN64`."""
    return df.parts_from(disk_dir())


@needs_disks
def test_every_mixed_row_agrees_with_a_fresh_size_for_call(parts):
    """Each row's `weapon_size`/`head_size` is what `size_for` says now,
    checked against a second, independent call rather than trusted."""
    tables = dos_icon_tables()
    rows = df.mixed_rows(parts, tables)
    assert rows, "no large-list-only rows found to compare"
    for row in rows:
        assert row["weapon_size"] == parts.size_for(
            "small", "weapon", row["weapon_option"]), row
        assert row["head_size"] == parts.size_for(
            "small", "head", row["head_option"]), row
    print(f"{len(rows)} large-list-only rows agree with IconParts.size_for")


@needs_disks
def test_mixed_rows_calls_size_for_rather_than_recomputing_it(parts, monkeypatch):
    """Proves `mixed_rows` is wired through `IconParts.size_for` and does not
    keep its own copy of the threshold.

    Patched to answer "large" for every call, `size_for` would still never be
    seen by a hand-written copy of the rule: the two baseline options this
    function always asks about -- weapon 8 on a head row, head 0 on a weapon
    row -- sit inside the small list on every disk this project has read, so
    the third copy `#328` found always called them "small" without asking
    `size_for` at all. Only a real call reports them "large" here, which is
    what distinguishes this from #328's arithmetic reproducing the same
    answer by coincidence.
    """
    monkeypatch.setattr(IconParts, "size_for",
                        lambda self, size, kind, option: "large")
    tables = dos_icon_tables()
    rows = df.mixed_rows(parts, tables)
    assert rows
    for row in rows:
        assert row["weapon_size"] == "large", row
        assert row["head_size"] == "large", row
