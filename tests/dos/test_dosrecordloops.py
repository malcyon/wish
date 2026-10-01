"""`tools/dos/dosrecordloops.py`, promoted from `issue516/loopwalk.py` (scratch, deleted) for
`#516 (Generate boundary characters and check every writer's field widths,
since no real save reaches a limit and the corpus cannot find a wrong one)`'s
slice 3.

Covers the one gap named while promoting it: a `shl ax, N` between the byte
index and `add di, ax` scales the index, so the loop's entry count and the
byte span it covers are not the same number unless that is accounted for.
"""

import pytest

pytest.importorskip("capstone")

from tools.dos import dosarraywidth, dosrecordloops  # noqa: E402


def test_a_a_word_stride_doubles_the_span_not_the_entry_count():
    """Built rather than read off an overlay, so the case does not depend
    on where a `shl` happens to sit in a real file.

    `for i := 0 to 6` over a word array: `shl ax, 1` before `add di, ax`,
    then the access.  Seven entries, and the last one is 12 bytes past the
    first -- half that, `+6`, is the answer a stride-blind reading gives.
    """
    data = (b"\xc6\x46\xfb\x00"      # mov byte [bp-5], 0        (init 0)
            + b"\xeb\x03"            # jmp bottom
            + b"\xfe\x46\xfb"        # top: inc byte [bp-5]
            + b"\x8a\x46\xfb"        # bottom: mov al, [bp-5]
            + b"\x98"                # cwde
            + b"\xd1\xe0"            # shl ax, 1
            + b"\xc4\x7e\xfc"        # les di, [bp-4]
            + b"\x03\xf8"            # add di, ax
            + b"\x26\x8b\x85\x88\x00"  # mov ax, es:[di+0x88]
            + b"\x80\x7e\xfb\x06"    # cmp byte [bp-5], 6
            + b"\x75\xf1")           # jne top
    sites = dosarraywidth.accesses(data, 0x88)
    assert len(sites) == 1
    at = sites[0][0]
    result = dosrecordloops.analyse(data, at)
    assert result["indexed"] is True
    assert result["stride"] == 2
    assert result["bound"] == 6
    assert result["init"] == 0


def test_b_the_real_seven_coin_purses_come_back_as_seven_not_fourteen():
    """The specimen the gap was found against: Pool of Radiance's
    `copper`-through-`jewelry` block, seven `word` purses walked by
    `for i := 0 to 6` with `shl ax, 1` at file offset `0x005618`."""
    try:
        overlay = dosarraywidth.find_overlay("pool-of-radiance")
    except FileNotFoundError as exc:
        pytest.skip(f"needs the DOS Pool of Radiance archives: {exc}")
    data = overlay.read_bytes()
    at = 0x561F
    sites = dosarraywidth.accesses(data, 0x88)
    assert (at, "mov ax, word ptr es:[di + 0x88]") in sites
    result = dosrecordloops.analyse(data, at)
    assert result["indexed"] is True
    assert result["slot"] == "[bp - 5]"
    assert result["stride"] == 2
    assert result["init"] == 0
    assert result["bound"] == 6
    entries = result["bound"] + 1 - result["init"]
    assert entries == 7
    span = result["bound"] * result["stride"]
    assert span == 12  # 0x088 to 0x094, i.e. 7 words minus the last word's width


def test_c_a_loop_with_no_init_move_still_prints_its_line(tmp_path, capsys):
    """A compare and a backjump on the index slot but no `mov byte [bp-n], imm`
    before the access: the per-site line used to format a missing init address
    with `#08x` and raise `TypeError`."""
    data = (b"\xeb\x03"                # jmp bottom
            + b"\xfe\x46\xfb"          # top: inc byte [bp-5]
            + b"\x8a\x46\xfb"          # bottom: mov al, [bp-5]
            + b"\x98"                  # cwde
            + b"\xc4\x7e\xfc"          # les di, [bp-4]
            + b"\x03\xf8"              # add di, ax
            + b"\x26\x8a\x85\x88\x00"  # mov al, es:[di+0x88]
            + b"\x80\x7e\xfb\x06"      # cmp byte [bp-5], 6
            + b"\x75\xf3")             # jne top
    overlay = tmp_path / "GAME.OVR"
    overlay.write_bytes(data)
    assert dosrecordloops.analyse(
        data, dosarraywidth.accesses(data, 0x88)[0][0])["initat"] is None
    assert dosrecordloops.main(["t", "88", "--overlay", str(overlay)]) == 0
    out = capsys.readouterr().out
    assert "init ? @?" in out
    assert "cmp 0x06" in out
