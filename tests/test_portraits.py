"""The creation menu's portrait tables, read off the player's own files (#57).

`goldbox/portraits.py` claims three things, and each has a test here:

* the fourteen heads and twelve bodies are a table in the game's own binary,
  findable by the shape of the run rather than by a file offset;
* **both ports carry the same table, in the same order** -- so the DOS
  record's menu position and the C64 record's art id are two spellings of one
  choice;
* the art ids are the same numbers on both sides: a `HEAD<xx>` file on
  `POOL<n>.D64` and a block of `HEAD<n>.DAX` are the same portrait.

The last of those is the measurement the whole conversion rests on, and it is
asserted over all sixteen containers rather than on one.

**The disks and the DOS archives are Donald's**, so every test here skips
cleanly without them -- `tests/gamedata.py` for the C64 side and
`tests/test_dossave.py`'s `_save_dir` for the DOS side.
"""

from __future__ import annotations

import pytest
from gamedata import disk_dir, disk_path

from goldbox import portraits
from goldbox.d64 import D64
from goldbox.dos_savegame import dax_index

needs_disks = pytest.mark.skipif(disk_dir() is None,
                                 reason="needs the C64 game disks")


def _dos_game():
    """The DOS game directory -- the one with `START.EXE` in it -- or skip."""
    from test_dossave import _save_dir

    where = _save_dir()
    if where is None:
        pytest.skip("needs the DOS archives; set FR_ARCHIVES")
    for root in (where, *where.parents):
        if (root / "START.EXE").exists() and list(root.glob("HEAD[0-9].DAX")):
            return root
    pytest.skip("the DOS saves here are not beside the game's own files")


def _c64_ids(path, stem: str) -> set[int]:
    """Every `HEAD<xx>`/`BODY<xx>` id on one C64 disk, from its directory."""
    image = D64(path.read_bytes())
    out = set()
    for entry in image.directory():
        name = entry.raw_name.rstrip(b"\xa0").decode("latin1")
        if name.startswith(stem) and len(name) == len(stem) + 2:
            out.add(int(name[len(stem):], 16))
    return out


def _dos_ids(game, stem: str, disk: int) -> set[int]:
    path = game / f"{stem}{disk}.DAX"
    return {block for block, *_ in dax_index(path.read_bytes(), path.name)}


@needs_disks
def test_the_two_ports_carry_the_same_creation_menu():
    """The finding this issue turned on: the same 26 bytes in both binaries.

    Fourteen head ids then twelve body ids in DOS `START.EXE`; the same
    twelve bodies then the same fourteen heads in the C64's `GEN` on `POOL3`,
    which is the only difference between them.  Because the order agrees, the
    DOS record's one-based menu position and the C64 record's art id are the
    same choice written two ways, and the conversion is a lookup rather than
    a judgement.
    """
    dos_tables = portraits.tables_from_dos(_dos_game())
    c64_tables = portraits.tables_from_c64(disk_path("POOL3"))
    assert dos_tables.heads == c64_tables.heads
    assert dos_tables.bodies == c64_tables.bodies
    assert dos_tables.agrees_with(c64_tables)
    assert len(dos_tables.heads) == portraits.HEAD_COUNT
    assert len(dos_tables.bodies) == portraits.BODY_COUNT


@needs_disks
def test_every_portrait_the_menu_offers_is_art_that_exists_on_both_ports():
    """A table naming a file nobody ships would be a table found by accident.

    Each of the fourteen heads is a `HEAD<xx>` file on some `POOL<n>.D64` and
    a block of the matching `HEAD<n>.DAX`, and the same for the twelve
    bodies.
    """
    game = _dos_game()
    tables = portraits.tables_from_dos(game)
    for stem, wanted in (("HEAD", tables.heads), ("BODY", tables.bodies)):
        c64 = set()
        dos = set()
        for disk in range(1, 9):
            path = disk_path(f"POOL{disk}")
            if path is not None:
                c64 |= _c64_ids(path, stem)
            dos |= _dos_ids(game, stem, disk)
        assert set(wanted) <= dos, stem
        assert set(wanted) <= c64, stem


@needs_disks
def test_the_two_ports_number_the_portrait_art_identically():
    """Sixteen containers, 41 head ids and 21 body ids, and no exception.

    The C64 loads a portrait as a **file** whose name is the record byte in
    hex -- `$2D` is `HEAD2D` -- and DOS keeps the same art as numbered blocks
    in one `.DAX` per disk.  The two id sets are equal, and equal disk by
    disk: `HEAD2D` is on `POOL3` and block 45 is in `HEAD3.DAX`.  That is
    what makes the menu tables mean the same thing on both sides.
    """
    game = _dos_game()
    compared = 0
    for stem in ("HEAD", "BODY"):
        for disk in range(1, 9):
            path = disk_path(f"POOL{disk}")
            if path is None:
                continue
            assert _c64_ids(path, stem) == _dos_ids(game, stem, disk), \
                f"{stem} on disk {disk}"
            compared += 1
    assert compared == 16, f"{compared} of 16 containers compared"


@needs_disks
def test_a_position_and_an_id_are_inverses():
    """What the writer and the reader each do, asserted on the real table."""
    tables = portraits.tables_from_dos(_dos_game())
    for position in range(1, portraits.HEAD_COUNT + 1):
        assert tables.head_position(tables.head_art(position)) == position
    for position in range(1, portraits.BODY_COUNT + 1):
        assert tables.body_position(tables.body_art(position)) == position


@needs_disks
def test_nothing_outside_the_menu_gets_an_answer():
    """The refusal the conversion depends on: no nearest match, no default.

    Zero is the DOS record's own "no position" and is not a menu entry; 15 is
    past the fourteenth head; and `$67` is a real C64 portrait id that the
    creation menu does not offer, which is the case a converted NPC could
    reach.
    """
    tables = portraits.tables_from_dos(_dos_game())
    assert tables.head_art(0) is None
    assert tables.head_art(portraits.HEAD_COUNT + 1) is None
    assert tables.body_art(portraits.BODY_COUNT + 1) is None
    assert 0x67 not in tables.heads
    assert tables.head_position(0x67) is None


def test_a_directory_that_is_not_the_game_says_so(tmp_path):
    """The failure a player could actually cause: pointing at the wrong
    folder.  It names what is missing rather than raising `FileNotFoundError`
    out of a comprehension."""
    with pytest.raises(portraits.PortraitError) as caught:
        portraits.tables_from_dos(tmp_path)
    assert "HEAD" in str(caught.value)


@needs_disks
def test_the_import_finds_the_menu_without_being_told_which_side():
    """What the **import** direction has in its hand is a disk *directory*.

    A DOS save becoming a `.d64` has to turn the DOS record's menu position
    into the art id the C64 record stores, and the only thing the import path
    already holds is the folder of `POOL<n>.D64` it reads the combat icon and
    `ANIMATE00` out of.  So the tables have to be findable from that folder
    alone -- not from a named side, because which side carries `GEN` is the
    game's business.
    """
    found = portraits.tables_from_disks(disk_dir())
    assert len(found.heads) == portraits.HEAD_COUNT
    assert len(found.bodies) == portraits.BODY_COUNT
    named = portraits.tables_from_c64(disk_path("POOL3"))
    assert found.agrees_with(named), (
        f"{found.source} and {named.source} disagree, so which side the "
        f"tables were read off changes the answer")


@needs_disks
def test_the_menu_found_from_the_disks_is_the_one_dos_offers():
    """The import's table and the export's are one table.

    `tables_from_disks` reads the C64's `GEN`; `tables_from_dos` reads DOS's
    `START.EXE`.  A converted party's faces are only its own if those two
    agree, and this is the assertion that makes the import's shortcut -- read
    the destination port's own binary rather than the source's -- safe.
    """
    assert portraits.tables_from_disks(disk_dir()).agrees_with(
        portraits.tables_from_dos(_dos_game()))


def test_a_folder_with_no_game_sides_in_it_says_so(tmp_path):
    """The failure a player causes by pointing the import at the wrong
    folder: it names what is missing rather than raising out of a glob."""
    with pytest.raises(portraits.PortraitError) as caught:
        portraits.tables_from_disks(tmp_path)
    assert "POOL" in str(caught.value)


@needs_disks
def test_a_folder_of_sides_that_carry_no_menu_says_which_it_tried(tmp_path):
    """A directory of real `POOL<n>.D64` that happen not to carry `GEN`.

    Built by copying one side that has no `HEAD*` on it, so the refusal is
    reached the way a wrong-but-plausible folder would reach it rather than
    by handing the function a broken image.
    """
    import shutil

    for n in (1, 2):
        shutil.copy(disk_path("POOL4"), tmp_path / f"POOL{n}.D64")
    try:
        portraits.tables_from_disks(tmp_path)
    except portraits.PortraitError as e:
        assert "none of the 2 sides" in str(e)
    else:  # pragma: no cover - POOL4 carries HEAD00, so this would be news
        pytest.skip("POOL4 answers for the menu on this set of disks")
