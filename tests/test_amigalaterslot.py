"""`tools/amigalaterslot.py`, the tool that put our bytes in front of the game.

`#28 (Decode an Amiga saved game, not just a character file)` ended on a
WinUAE run: five saved games this project wrote were loaded by Amiga Curse and
Amiga Silver Blades, and each was one edit of a shipped save made here.  These
tests build synthetic disks and synthetic saved games from
`docs/165-amiga-savegame.md`'s map, so they run with no game data anywhere,
and they assert the three things a screenshot settled -- the name the panel
draws, the count word the loader trusts, and the chain head it tests.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from goldbox import amiga  # noqa: E402
from goldbox.amiga_adf import AmigaDisk  # noqa: E402
from tests.test_amigasavegame import (  # noqa: E402
    fake_record,
    synthetic_curse,
    synthetic_silver_blades,
)
from tools import amigalaterslot, amigasavegame  # noqa: E402


def disk_with(path: str, data: bytes) -> AmigaDisk:
    """A blank floppy carrying one saved game in a `SAVE` drawer."""
    disk = AmigaDisk.blank("Test")
    disk.make_dir("/SAVE")
    disk.write_file(path, data)
    return disk


@pytest.fixture
def curse_disk(tmp_path):
    disk = disk_with("/SAVE/savgamA.dat", synthetic_curse(("ALPHA", "BETA")))
    image = tmp_path / "in.adf"
    disk.save(image)
    return image


def run(*argv: str) -> int:
    return amigalaterslot.main(list(argv))


def slot(image, letter: str, suffix: str = ".dat"):
    disk = AmigaDisk.open(image)
    return amigasavegame.parse(disk.read_file(f"/SAVE/savgam{letter}{suffix}"))


# -- the name field ----------------------------------------------------------

def test_a_shorter_name_clears_what_was_under_it():
    # The Amiga name is sixteen bytes terminated and padded with NUL, so a
    # rename that only overwrote its own length would leave the tail of the
    # old name for the panel to draw -- which is how the run's proof that the
    # engine read our bytes would have become unreadable.
    char = amiga.AmigaCharacter.from_bytes(
        fake_record(amiga.CURSE_SHAPE, "IILANDA"), amiga.CURSE_SHAPE)
    shorter = amigalaterslot.rename(char, "ZEP")
    assert shorter.name == "ZEP"
    assert shorter.raw[:amiga.AMIGA_NAME_SIZE] == b"ZEP" + b"\0" * 13
    assert shorter.raw[amiga.AMIGA_NAME_SIZE:] == char.raw[
        amiga.AMIGA_NAME_SIZE:]


def test_a_name_that_would_not_fit_is_refused():
    char = amiga.AmigaCharacter.from_bytes(
        fake_record(amiga.CURSE_SHAPE, "IILANDA"), amiga.CURSE_SHAPE)
    with pytest.raises(SystemExit):
        amigalaterslot.rename(char, "A" * amiga.AMIGA_NAME_SIZE)


# -- writing a slot ----------------------------------------------------------

def test_renaming_writes_a_slot_of_the_same_size(curse_disk, tmp_path):
    out = tmp_path / "out.adf"
    assert run(str(curse_disk), "--to", "B", "--out", str(out),
               "--rename", "0=ZEPHYRA") == 0
    written = slot(out, "B")
    assert [c.name for c in written.characters] == ["ZEPHYRA", "BETA"]
    assert len(written.data) == len(slot(curse_disk, "A").data)
    assert all(ok for _, ok, _ in amigasavegame.check(written))


def test_the_slot_it_read_is_left_alone(curse_disk, tmp_path):
    out = tmp_path / "out.adf"
    run(str(curse_disk), "--to", "B", "--out", str(out), "--rename", "0=ZEP")
    assert (AmigaDisk.open(out).read_file("/SAVE/savgamA.dat")
            == AmigaDisk.open(curse_disk).read_file("/SAVE/savgamA.dat"))
    assert AmigaDisk.open(out).verify() == []


def test_a_shorter_party_moves_the_count_and_the_length(curse_disk, tmp_path):
    # The structural case: the count word and every block boundary after it
    # move, which is what a loader reading a block length wrong comes apart
    # on.  Amiga Curse drew three rows for this on 2026-09-05.
    out = tmp_path / "out.adf"
    assert run(str(curse_disk), "--to", "C", "--out", str(out),
               "--keep", "1") == 0
    written = slot(out, "C")
    assert written.count == 1
    assert written.word(0x503E) == 1
    assert len(written.data) == (len(slot(curse_disk, "A").data)
                                 - amiga.CURSE_SHAPE.record_size)


def test_stripping_items_zeroes_the_head_the_loader_tests(tmp_path):
    # The loader's only test on the item chain is `tst.l` on the head, so a
    # character with no nodes must carry zero there or the read runs into the
    # next character's block.
    item = amiga.AmigaItem.from_bytes(bytes(amiga.CURSE_SHAPE.item_size),
                                      amiga.CURSE_SHAPE)
    record = bytearray(fake_record(amiga.CURSE_SHAPE, "ALPHA"))
    at = amiga.CURSE_SHAPE.offset(
        amiga.CURSE_SHAPE.dos_field("item_count").offset)
    record[at] = 1
    char = amiga.AmigaCharacter.from_bytes(bytes(record), amiga.CURSE_SHAPE,
                                           items=(item,))
    save = amigasavegame.parse(synthetic_curse(("ALPHA", "BETA")))
    with_item = amigasavegame.rebuild(save, [char, save.characters[1]])
    disk = disk_with("/SAVE/savgamA.dat", with_item)
    image = tmp_path / "in.adf"
    disk.save(image)
    assert slot(image, "A").characters[0].item_chain != 0

    out = tmp_path / "out.adf"
    assert run(str(image), "--to", "D", "--out", str(out),
               "--strip-items", "0") == 0
    written = slot(out, "D")
    assert written.characters[0].item_chain == 0
    assert written.characters[0].get("item_count") == 0
    assert len(written.data) == len(with_item) - amiga.CURSE_SHAPE.item_size


# -- the two titles' suffixes ------------------------------------------------

def test_silver_blades_keeps_its_own_suffix(tmp_path):
    disk = disk_with("/SAVE/savgamA.sav", synthetic_silver_blades(("GAMMA",)))
    image = tmp_path / "ssb.adf"
    disk.save(image)
    out = tmp_path / "out.adf"
    assert run(str(image), "--to", "B", "--out", str(out),
               "--rename", "0=TALWYN") == 0
    assert slot(out, "B", ".sav").characters[0].name == "TALWYN"
    with pytest.raises(Exception):
        AmigaDisk.open(out).lookup("/SAVE/savgamB.dat")


def test_a_slot_the_disk_does_not_have_is_named_in_the_refusal(curse_disk,
                                                              tmp_path):
    with pytest.raises(SystemExit) as raised:
        run(str(curse_disk), "--from", "Z", "--to", "B",
            "--out", str(tmp_path / "out.adf"))
    assert "savgamZ" in str(raised.value)


def test_writing_over_the_input_is_refused(curse_disk):
    with pytest.raises(SystemExit) as raised:
        run(str(curse_disk), "--to", "B", "--out", str(curse_disk))
    assert "--out" in str(raised.value)
