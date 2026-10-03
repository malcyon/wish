"""The C64 packs PAINE ends up with when Silver Blades' engine-written joined
scroll specimens are converted, pinned for the live run that boots them.

Each expected pack is the DOS pack with the chosen index removed, read through
`dos_codec.pack_of`; no item bytes are typed here.  The test reads the player's
Silver Blades C64 disks and the two specimens, and skips without them.
"""

from __future__ import annotations

import pytest
from conftest import load_tools_module
from gamedata import specimen
from support.silverblades import ssb_dir

from editor.convert import Source
from editor.roster import Party
from goldbox import dos_codec

convertrun = load_tools_module("convertrun")

GUY, PAINE = 0, 1


def _dos_pack(folder, slot: str, member_file: str) -> list[bytes]:
    pack, _bundles = dos_codec.pack_of(
        dos_codec.read_character(folder / f"CHRDAT{slot}{member_file}.SAV"))
    return pack


def _c64_pack(path: str, member: int) -> list[bytes]:
    """The member's filled slots, slot 15 first: the order the pack is read in."""
    inventory = Party(Source.detect(path)).members[member].inventory
    return [raw for raw in reversed(inventory.raws) if any(raw)]


def _convert(tmp_path, folder, slot: str, leave):
    disks = ssb_dir()
    if disks is None:
        pytest.skip("needs the Silver Blades disks")
    out = tmp_path / "out"
    out.mkdir()
    report = convertrun.write_via_save_as(
        folder / f"SAVGAM{slot}.DAT", "c64", out, None, disks,
        source_slot=slot, **({"leave": leave} if leave else {}))
    assert "refused" not in report, report
    (disk,) = [p for p in report["written"] if p.endswith(".D64")]
    return disk, report


@pytest.mark.parametrize("leave_index, label",
                         [(16, "the staff"), (15, "one scroll")])
def test_the_pack_left_behind_by_one_choice(tmp_path, leave_index, label):
    folder = specimen("ssb-432-sixteen-heads")
    disk, report = _convert(tmp_path, folder, "D", {PAINE: {leave_index}})

    (line,) = report["left_behind"]
    assert f"inventory item {leave_index}" in line, label
    full = _dos_pack(folder, "D", "2")
    assert len(full) == 17
    assert _c64_pack(disk, PAINE) == full[:leave_index] + full[leave_index + 1:]
    assert _c64_pack(disk, GUY) == _dos_pack(folder, "D", "1")


def test_a_pack_that_fits_converts_whole_with_nothing_left_behind(tmp_path):
    folder = specimen("ssb-432-joined-fits")
    disk, report = _convert(tmp_path, folder, "C", None)

    assert report["left_behind"] == []
    assert _c64_pack(disk, PAINE) == _dos_pack(folder, "C", "2")
