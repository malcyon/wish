"""`tools/dosarraywidth.py`'s `LOOKBACK` window, and the one field it settled.

`#516 (Generate boundary characters and check every writer's field widths,
since no real save reaches a limit and the corpus cannot find a wrong one)`'s
slice 3 found the flat 90-byte lookback crossing a `retf` into a different
subroutine: Pool of Radiance's `spells_castable_cleric` read "8" because the
guard the tool tallied, `cmp byte [bp-1], 7` at `0x02ac08`, belongs to the
function that ends `retf 4` at `0x02ac33`, not the one at the measured site,
`0x02ac52`.
"""

import pytest

from tools import dosarraywidth


def test_a_retf_between_the_guard_and_the_site_is_excluded():
    """Two guards ahead of one access, a `retf` between them: only the one
    on the near side of the `retf` should count.

    Built rather than read off an overlay so the case does not depend on
    where in a real file such a boundary happens to sit -- `guards()` finds
    both `cmp` immediates in the flat 90-byte window with no truncation, so
    this is what the fix actually changes.
    """
    data = (b"\x80\x7e\xff\x09"      # cmp byte [bp-1], 9  -- wrong function
            + b"\xcb"                # retf
            + b"\x55"                # push bp (next function's prologue)
            + b"\x80\x7e\xff\x02"    # cmp byte [bp-1], 2  -- the real guard
            + b"\x90" * 5
            + b"\x26\x8a\x85\x99\x00")  # mov al, es:[di+0x99]
    at = 15
    assert dosarraywidth.accesses(data, 0x99) == [
        (at, "mov al, byte ptr es:[di + 0x99]")]
    assert dosarraywidth._window_start(data, at) == 5
    assert dosarraywidth.guards(data, at) == [(6, "bp-1", 2)]
    assert dosarraywidth.width(data, 0x99) == 3


def test_b_with_no_retf_in_range_the_window_is_unchanged():
    """The ordinary case -- no boundary in the lookback -- still finds the
    guard exactly as the flat window would."""
    data = b"\x80\x7e\xff\x02" + b"\x90" * 5 + b"\x26\x8a\x85\x99\x00"
    at = len(data) - 5
    assert dosarraywidth._window_start(data, at) == 0
    assert dosarraywidth.width(data, 0x99) == 3


pytest.importorskip("capstone")

from goldbox import dos_port  # noqa: E402


def test_c_pool_of_radiances_spells_castable_cleric_is_no_longer_eight():
    """The real specimen the finding came from.  Pre-fix this read `8`
    (`_pick` chose the wrong function's `cmp byte [bp-1], 7`, off by one);
    the loop that genuinely bounds this array is 1-based, which
    `dosarraywidth` cannot see at the field's own offset at all -- so the
    fixed answer is `None`, not a number to disagree with, exactly as
    `#516`'s slice-3 comment describes.
    """
    try:
        overlay = dosarraywidth.find_overlay("pool-of-radiance")
    except FileNotFoundError as exc:
        pytest.skip(f"needs the DOS Pool of Radiance archives: {exc}")
    f = dos_port.FIELDS_BY_NAME_FOR["pool-of-radiance"]["spells_castable_cleric"]
    got = dosarraywidth.width(overlay.read_bytes(), f.offset)
    assert got != 8, got
    assert got is None, got
