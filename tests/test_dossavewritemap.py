"""`tools/dossavewritemap.py`, which reads a title's save map off its writer.

Two halves. The synthetic one builds a `BlockWrite` chain byte by byte and
runs in CI, because the parser -- the immediate that is decimal when small and
hex when large, the counted loop whose body lands three times -- is where a
map goes quietly wrong. The archive-backed one is the finding itself: three
engines, three maps, and every one agreeing with its `DosSaveShape`. It skips
without the archives, so say in the commit that you ran it somewhere they are.
"""

import pytest

from goldbox import dos_savegame as sg
from tools import dossavewritemap as wm

# `capstone` is not a declared dependency: nine tools under `tools/` use it and
# CI installs none of them.  `tools/dossavewritemap.py` imports it lazily, so the
# module above is safe to import and it is the test bodies that need the skip.
# `tests/test_amiga68k.py` guards the same way, and passes in CI without it.
pytest.importorskip("capstone")

# --- a chain assembled here, so CI exercises the parser ----------------------


def _write_call(source: bytes, count: int) -> bytes:
    """`BlockWrite(f, source^, count, NIL)` as the compiler emits it."""
    return (source
            + b"\xb8" + count.to_bytes(2, "little") + b"\x50"   # mov ax, n
            + b"\x31\xc0\x50\x50"                               # NIL result
            + b"\x9a\x22\x22\x11\x11")                          # lcall


def _from_data(address: int) -> bytes:
    return b"\xbf" + address.to_bytes(2, "little") + b"\x1e\x57"


def _from_heap(address: int) -> bytes:
    return b"\xc4\x3e" + address.to_bytes(2, "little") + b"\x06\x57"


def _from_stack(offset: int) -> bytes:
    return b"\x8d\xbe" + (0x10000 - offset).to_bytes(2, "little") + b"\x16\x57"


def _chain(loop: bool) -> bytes:
    """A whole save routine: Pool of Radiance's shape, or Curse's."""
    body = (_write_call(_from_data(0x1000), 1)
            + _write_call(_from_heap(0x2000), 5120)
            + _write_call(_from_heap(0x2004), 7680)
            + _write_call(_from_data(0x3000), 5)
            + _write_call(_from_data(0x3100), 1)
            + _write_call(_from_data(0x3200), 1))
    if loop:
        inside = (_write_call(_from_data(0x4000), 2)
                  + _write_call(b"\x81\xc7\x02\x40\x1e\x57", 2))
        back = len(inside) + 5 + 2          # the cmp, then the jne itself
        body += (b"\xc6\x86\x37\xfe\x01"                        # counter := 1
                 + inside
                 + b"\x80\xbe\x37\xfe\x03"                      # cmp ..., 3
                 + b"\x75" + (256 - back).to_bytes(1, "little"))
    body += (_write_call(_from_stack(0x1C9), 1)
             + _write_call(_from_stack(0x148), 328))
    return b"\x90" * 128 + body + b"\x90" * 16


def test_a_synthetic_chain_reads_back_as_the_offsets_it_encodes():
    """The straight-line case: eight calls, no loop, and the widths land the
    fourth region on Pool of Radiance's own 12801."""
    regions, shape = wm.save_chain(_chain(loop=False))
    assert shape is sg.SAVE_POOL_OF_RADIANCE
    assert [(r.at, r.total) for r in regions] == [
        (0, 1), (1, 5120), (5121, 7680), (12801, 5), (12806, 1), (12807, 1),
        (12808, 1), (12809, 328)]
    assert wm.square_region(regions).at == 12801


def test_a_counted_loop_lands_its_body_once_per_trip():
    """Two calls of two bytes inside a loop that runs three times are twelve
    bytes, not four -- and every offset after them moves by that difference.

    Without this the chain would total 13141, which is no title's size, and
    the tool would report no save routine at all rather than a wrong map."""
    regions, shape = wm.save_chain(_chain(loop=True))
    assert shape is sg.SAVE_CURSE_OF_THE_AZURE_BONDS
    merged = [r for r in regions if r.times > 1]
    assert len(merged) == 1, "the loop's two calls interleave, so they are one"
    assert (merged[0].at, merged[0].width, merged[0].times) == (12808, 4, 3)
    assert [(r.at, r.total) for r in regions][-2:] == [(12820, 1), (12821, 328)]
    assert wm.square_region(regions).at == 12801


def test_a_chain_whose_widths_are_no_titles_size_is_refused():
    """A misread loop or a missed call must produce nothing, because a map
    that is nearly right is the one somebody would build on."""
    broken = _chain(loop=False).replace(b"\xb8\x05\x00\x50", b"\xb8\x06\x00\x50")
    regions, shape = wm.save_chain(broken)
    assert shape is None and regions == []


# --- and against the engines themselves --------------------------------------


def _overlay(stem: str):
    from tools import dosbox
    try:
        path = dosbox.find_game(stem) / "GAME.OVR"
    except FileNotFoundError:
        pytest.skip(f"needs the DOS {stem} archive; set FR_ARCHIVES")
    if not path.is_file():
        pytest.skip(f"no GAME.OVR beside DOS {stem}")
    return path.read_bytes()


ENGINES = pytest.mark.parametrize("stem,key", [
    ("POOLRAD", "pool-of-radiance"),
    ("CURSE", "curse-of-the-azure-bonds"),
    ("SECRET", "secret-of-the-silver-blades")])


@ENGINES
def test_the_engine_writes_the_square_where_its_shape_says(stem, key):
    """#253. The square block's first byte is x, and the writer's own chain
    puts it at 12801 in Pool of Radiance and Curse alike and at 5121 in Silver
    Blades -- the first byte after the variable array and the staged script.

    This is the evidence a saved game cannot give: an editor changes what a
    field holds and never where the engine puts it, and none of the saved
    games on this machine has a chain of custody
    (`.claude/rules/testing.md`). Reverting `DosSaveShape.square` to the
    arithmetic it had before #253 makes the two later titles fail here by
    exactly twelve.
    """
    shape = sg.save_shape_for(key)
    regions, found = wm.save_chain(_overlay(stem))
    assert found is shape, f"the chain totals no {shape.title} container"
    assert wm.square_region(regions).at == shape.pos_x
    assert wm.square_region(regions).width == 5, "x, y, facing and two more"


@ENGINES
def test_the_engine_writes_the_party_size_and_table_where_the_shape_says(
        stem, key):
    """The other end of the block, which #253 must not have moved: the count
    of character files is the last byte before the table in every title."""
    shape = sg.save_shape_for(key)
    regions, found = wm.save_chain(_overlay(stem))
    assert found is shape
    assert regions[-1].at == shape.party_table
    assert regions[-1].total == sg.NAME_SLOTS * sg.PARTY_ENTRY
    assert regions[-2].at == shape.party_table - 1


@ENGINES
def test_the_regions_tile_the_container_with_nothing_left_over(stem, key):
    """Every byte of the file comes from one `BlockWrite`, so the widths add
    up to the size exactly -- which is what identifies the chain as the save
    routine in the first place."""
    shape = sg.save_shape_for(key)
    regions, found = wm.save_chain(_overlay(stem))
    assert found is shape
    assert sum(r.total for r in regions) == shape.size
    running = 0
    for r in regions:
        assert r.at == running
        running += r.total


def test_the_twelve_extra_bytes_are_inside_the_block_not_in_front_of_it():
    """#220 read Curse's twelve as sitting between the script buffer and the
    square, which is what moved x twelve bytes late. The writer puts them
    after the block's seventh byte and before the party-size byte, in both
    titles that have them."""
    for stem, key in (("CURSE", "curse-of-the-azure-bonds"),
                      ("SECRET", "secret-of-the-silver-blades")):
        shape = sg.save_shape_for(key)
        regions, found = wm.save_chain(_overlay(stem))
        assert found is shape
        extra = [r for r in regions if r.total == shape.unnamed == 12]
        assert len(extra) == 1, key
        assert extra[0].at == shape.pos_x + 7, key
        assert extra[0].at + 12 == shape.party_table - 1, key


def test_the_command_line_check_passes_against_every_engine_here():
    """`--check` is the whole tool as one exit code, and a subagent running
    it should get a `0` rather than a map to read."""
    from tools import dosbox
    if not dosbox.ARCHIVES.is_dir():
        pytest.skip("needs the DOS archives; set FR_ARCHIVES")
    assert wm.main(["--check"]) == 0
