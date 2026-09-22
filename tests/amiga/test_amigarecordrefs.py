"""`tools/amiga/amigarecordrefs.py` searches every CODE hunk, not the first.

Pool of Radiance's `/program` has seventeen CODE hunks and the first is 2% of
the file, so a first-hunk search answers "nothing reaches this record byte"
for a byte the engine tests.  The synthetic executable below needs no disk;
the two disk tests read the player's own copy through the registry.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

# `tools.amiga.amigarecordrefs` imports capstone at module scope, and capstone
# is not a declared dependency: this skip has to come before that import.
pytest.importorskip("capstone")

from support.hunks import hunk_file, pad4  # noqa: E402

from automap import gamedisks  # noqa: E402
from tools.amiga import amiga68k, amigarecordrefs  # noqa: E402

#: `move.b $85(a0), d0`, and the same two displacement bytes as plain data.
READ_85 = b"\x10\x28\x00\x85"
RTS = b"\x4e\x75"


def three_hunks() -> bytes:
    """CODE, DATA, CODE, with a read of `$85(a0)` in each CODE hunk and a
    decoy in the DATA hunk that only a whole-file scan would decode."""
    first = pad4(RTS + READ_85 + RTS)
    data = pad4(b"\0\0" + READ_85)
    second = pad4(RTS + RTS + RTS + READ_85 + RTS)
    return hunk_file([(amiga68k.HUNK_CODE, first, []),
                      (amiga68k.HUNK_DATA, data, []),
                      (amiga68k.HUNK_CODE, second, [])])


def test_every_code_hunk_is_a_range_and_the_data_hunk_is_not():
    ranges = amigarecordrefs.code_ranges(three_hunks())
    assert [hunk for hunk, _start, _end in ranges] == [0, 2]
    assert amigarecordrefs.code_range(three_hunks()) == ranges[0][1:]


def test_a_read_in_the_second_code_hunk_is_found_and_the_data_decoy_is_not():
    data = three_hunks()
    exe = amiga68k.Executable.parse(data)
    first, second = exe.by_number(0), exe.by_number(2)
    found = amigarecordrefs.hunk_sites(data, 0x85)
    assert found == [(first.file_offset + 2, 0, "move.b $85(a0), d0"),
                     (second.file_offset + 6, 2, "move.b $85(a0), d0")]


def test_the_command_line_prints_each_sites_hunk(capsys, tmp_path):
    path = tmp_path / "prog"
    path.write_bytes(three_hunks())
    assert amigarecordrefs.main(["--file", str(path), "85"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "--- record +0x85"
    assert [line.split(":")[0].split()[1:] for line in lines[1:]] \
        == [["hunk", "0"], ["hunk", "2"]]


def _program() -> bytes:
    from tools.icons import amigaicons
    if not gamedisks.candidates("amiga"):
        pytest.skip("no Amiga disks; set $AMIGA_DISKS")
    found = amigaicons.find_executable("program")
    if found is None:
        pytest.skip("no /program on any Amiga disk here")
    return found[1]


def test_pool_of_radiance_program_is_searched_across_all_its_code_hunks():
    """The NPC control byte's own test is at `+0x85`, and none of it is in the
    first hunk."""
    data = _program()
    ranges = amigarecordrefs.code_ranges(data)
    assert len(ranges) == 17
    start, end = amigarecordrefs.code_range(data)
    assert amigarecordrefs.sites(data, 0x85, start, end) == []
    found = amigarecordrefs.hunk_sites(data, 0x85)
    assert len(found) > 0
    assert all(hunk != ranges[0][0] for _where, hunk, _text in found)


@pytest.mark.parametrize("name", ["Curse", "Secret"])
def test_a_one_code_hunk_executable_gives_the_first_hunk_search_unchanged(name):
    from tools.icons import amigaicons
    if not gamedisks.candidates("amiga"):
        pytest.skip("no Amiga disks; set $AMIGA_DISKS")
    found = amigaicons.find_executable(name)
    if found is None:
        pytest.skip(f"no /{name} on any Amiga disk here")
    data = found[1]
    start, end = amigarecordrefs.code_range(data)
    assert [(s, e) for _hunk, s, e in amigarecordrefs.code_ranges(data)] \
        == [(start, end)]
    for at in (0x145, 0x146):
        assert [(where, text) for where, _hunk, text
                in amigarecordrefs.hunk_sites(data, at)] \
            == amigarecordrefs.sites(data, at, start, end)
