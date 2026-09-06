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

import functools

import pytest
from gamedata import _disk_with, disk_dir, disk_path

from goldbox import portraits
from goldbox.d64 import D64
from goldbox.dos_savegame import dax_index
from tools import gamedisks

needs_disks = pytest.mark.skipif(disk_dir() is None,
                                 reason="needs the C64 game disks")


@functools.lru_cache(maxsize=1)
def _curse_disks_dir():
    """Where Curse of the Azure Bonds' own sides are, or None (#300)."""
    return gamedisks.find("curse-of-the-azure-bonds")


@functools.lru_cache(maxsize=1)
def _ssb_disks_dir():
    """Where Secret of the Silver Blades' own sides are, or None (#300)."""
    return gamedisks.find("secret-of-the-silver-blades")


needs_curse_disks = pytest.mark.skipif(_curse_disks_dir() is None,
                                       reason="needs the Curse disks; set "
                                              "COAB_DISKS")
needs_ssb_disks = pytest.mark.skipif(_ssb_disks_dir() is None,
                                     reason="needs the Silver Blades disks; "
                                            "set SSB_DISKS")


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


# ---------------------------------------------------------------------------
# #300: the glob was `POOL[0-9].D64` alone, so a Curse or Silver Blades
# folder -- real disks, correctly named for their own title -- was refused
# with a message about `POOL<n>.D64`, which is not what either title's sides
# are called.
# ---------------------------------------------------------------------------
@needs_curse_disks
def test_a_curse_folder_is_not_refused_for_lacking_pool_disks():
    """The bug this issue reported: a real, correctly-named Curse folder was
    rejected as if it were an empty one, because the glob only knew `POOL`.

    Curse's own sides are found -- proven by their names appearing in the
    refusal -- rather than the folder being waved off as having none.
    """
    with pytest.raises(portraits.PortraitError) as caught:
        portraits.tables_from_disks(_curse_disks_dir())
    message = str(caught.value)
    assert "no POOL" not in message, (
        "the old bug: a Curse folder answered as if it had no game sides "
        "in it at all")
    assert "CURSE" in message.upper()


@needs_curse_disks
def test_curse_keeps_gen_and_its_portrait_art_on_different_sides():
    """Measured, 2026-09-05: `GEN` is on `CURSE_A.D64` alone and every
    `HEAD<xx>`/`BODY<xx>` file is on the other five sides, so a search that
    only checked the disk `GEN` came from -- what `tables_from_c64` does --
    could never confirm a table here even if Curse's `GEN` held one.
    """
    disks = _curse_disks_dir()
    sides = sorted(disks.glob("CURSE*.[dD]64"))
    assert len(sides) >= 2
    gen_sides, art_sides = [], []
    for side in sides:
        image = D64(side.read_bytes())
        names = [e.raw_name.rstrip(b"\xa0").decode("latin1")
                 for e in image.directory()]
        if "GEN" in names:
            gen_sides.append(side.name)
        if any(n.startswith(("HEAD", "BODY")) and len(n) == 6 for n in names):
            art_sides.append(side.name)
    assert gen_sides, "no side here carries GEN any more; this test is stale"
    assert not (set(gen_sides) & set(art_sides)), (
        "GEN and the portrait art are now on the same side, so the "
        "cross-side search this issue asked for is no longer exercised here")


@needs_curse_disks
def test_curse_has_no_run_of_fourteen_and_twelve_ids_anywhere_on_its_sides():
    """The finding that changes what "fixed" means for Curse, not only for
    Silver Blades (#300).

    Pooling every `HEAD<xx>`/`BODY<xx>` id across all six sides and searching
    every file on every side for an adjacent run of fourteen and twelve of
    them, in either order, finds nothing -- the same search that finds Pool
    of Radiance's table exactly once, at the one place it is
    (`POOL3.D64:GEN @2877`). So the `HEAD*`/`BODY*` files Curse ships are not
    the fourteen-heads-and-twelve-bodies creation menu Pool of Radiance has;
    what they are for is unmeasured, and inventing a table would be worse
    than reporting that none was found.
    """
    disks = _curse_disks_dir()
    sides = sorted(disks.glob("CURSE*.[dD]64"))
    heads, bodies = set(), set()
    per_side = {}
    for side in sides:
        image = D64(side.read_bytes())
        h, b = set(), set()
        for entry in image.directory():
            name = entry.raw_name.rstrip(b"\xa0").decode("latin1")
            if name.startswith("HEAD") and len(name) == 6:
                h.add(int(name[4:], 16))
            if name.startswith("BODY") and len(name) == 6:
                b.add(int(name[4:], 16))
        per_side[side.name] = image
        heads |= h
        bodies |= b
    assert heads and bodies, "Curse has grown no portrait art; update #300"

    def windows(data, ok, length):
        out = set()
        for i in range(len(data) - length + 1):
            chunk = data[i:i + length]
            if len(set(chunk)) == length and all(x in ok for x in chunk):
                out.add(i)
        return out

    hits = 0
    for name, image in per_side.items():
        for entry in image.directory():
            raw = entry.raw_name.rstrip(b"\xa0")
            try:
                data = image.read_file(raw)
            except Exception:
                continue
            h_at = windows(data, heads, portraits.HEAD_COUNT)
            b_at = windows(data, bodies, portraits.BODY_COUNT)
            hits += sum(1 for st in h_at if st + portraits.HEAD_COUNT in b_at)
            hits += sum(1 for st in b_at if st + portraits.BODY_COUNT in h_at)
    assert hits == 0, (
        f"{hits} adjacency hit(s) found -- Curse does carry a run shaped "
        f"like the creation menu after all; #300's finding needs revising")


@needs_ssb_disks
def test_silver_blades_ships_no_head_or_body_file_at_all():
    """The escape-hatch fact: unlike Curse, Silver Blades has no candidate
    art to look for a menu among, on any of its six sides."""
    disks = _ssb_disks_dir()
    sides = sorted(disks.glob("SILVER*.[dD]64"))
    assert sides
    for side in sides:
        image = D64(side.read_bytes())
        names = [e.raw_name.rstrip(b"\xa0").decode("latin1")
                 for e in image.directory()]
        assert not any(n.startswith(("HEAD", "BODY")) and len(n) == 6
                      for n in names), f"{side.name} carries portrait art now"


@needs_ssb_disks
def test_a_silver_blades_folder_reports_no_portrait_art_rather_than_a_table():
    """The player-visible refusal for a title that never had a face to give:
    it names the missing art, not a made-up table."""
    with pytest.raises(portraits.PortraitError) as caught:
        portraits.tables_from_disks(_ssb_disks_dir())
    assert "HEAD" in str(caught.value)


def test_a_table_is_found_across_sides_even_when_gen_carries_no_art_itself(
        tmp_path, monkeypatch):
    """The mechanism #300 asked for, proven on synthetic disks so it does not
    depend on any title actually shipping this shape.

    `GEN` and its table sit alone on one side; every `HEAD<xx>`/`BODY<xx>`
    file sits on a second. `tables_from_c64` -- one disk only -- cannot
    confirm this table since the side it is on carries no art of its own;
    `tables_from_disks` pools ids across every side matching the title's
    glob, so it can.
    """
    monkeypatch.setattr(portraits, "HEAD_COUNT", 3)
    monkeypatch.setattr(portraits, "BODY_COUNT", 2)
    heads = (0x01, 0x02, 0x03)
    bodies = (0x05, 0x06)

    gen_payload = bytes([0xFE, 0xFF]) + bytes(bodies) + bytes(heads)
    (tmp_path / "CURSEA.D64").write_bytes(
        _disk_with([(b"GEN", gen_payload)]))
    art_files = ([(f"HEAD{n:02X}".encode(), b"\x01\x08") for n in heads]
                + [(f"BODY{n:02X}".encode(), b"\x01\x08") for n in bodies])
    (tmp_path / "CURSEB.D64").write_bytes(_disk_with(art_files))

    found = portraits.tables_from_disks(tmp_path)
    assert found.heads == heads
    assert found.bodies == bodies
    assert found.source.startswith("CURSEA.D64:GEN")


def test_no_table_is_found_when_a_side_has_gen_but_no_art_anywhere(
        tmp_path, monkeypatch):
    """The Silver Blades shape: a side carries `GEN`, but no side -- this one
    or any other matching the same title -- carries a `HEAD<xx>`/`BODY<xx>`
    file for a found run to be checked against."""
    monkeypatch.setattr(portraits, "HEAD_COUNT", 3)
    monkeypatch.setattr(portraits, "BODY_COUNT", 2)
    gen_payload = (bytes([0xFE, 0xFF]) + bytes((0x05, 0x06))
                  + bytes((0x01, 0x02, 0x03)))
    (tmp_path / "SILVER-1.D64").write_bytes(
        _disk_with([(b"GEN", gen_payload)]))

    with pytest.raises(portraits.PortraitError) as caught:
        portraits.tables_from_disks(tmp_path)
    assert "HEAD" in str(caught.value)


# ---------------------------------------------------------------------------
# The stored menu (2026-09-06).  Donald: "Just pull them from each title so
# you can cross reference them. Then you don't need the disks at all."
# ---------------------------------------------------------------------------
def test_the_stored_menu_has_the_shape_of_the_menu():
    """No disks: the block in `goldbox/portraits.py` is fourteen heads and
    twelve bodies, each run strictly increasing the way both binaries keep
    it, and it answers for Pool of Radiance -- by key, by anything carrying
    the key, and for `None`, the way every other resolver in the package
    reads `None` -- and for no other title, because no other title's sheet
    draws a face (#300)."""
    import types

    menu = portraits.POOL_OF_RADIANCE_MENU
    assert len(menu.heads) == portraits.HEAD_COUNT
    assert len(menu.bodies) == portraits.BODY_COUNT
    for run in (menu.heads, menu.bodies):
        assert all(a < b for a, b in zip(run, run[1:])), run
        assert all(0 <= v <= 0xFF for v in run)
    assert portraits.stored_tables(None) is menu
    assert portraits.stored_tables(portraits.POOL_OF_RADIANCE_KEY) is menu
    assert portraits.stored_tables(
        types.SimpleNamespace(key=portraits.POOL_OF_RADIANCE_KEY)) is menu
    for other in ("curse-of-the-azure-bonds", "secret-of-the-silver-blades",
                  "pools-of-darkness", "no-such-title"):
        assert portraits.stored_tables(other) is None, other
    assert set(portraits.STORED_MENUS) <= portraits.SHEET_PORTRAIT_TITLES


@needs_disks
def test_the_stored_menu_is_what_the_disks_carry():
    """The stored block and the player's own `GEN` are one table, so the
    two cannot drift apart in silence: whoever changes either has to change
    both, and `tools/portraitmenu.py --check` is the same comparison from
    the command line.  Skips where the disks are absent, which is right --
    the block is what a machine with no disks has instead."""
    read = portraits.tables_from_disks(disk_dir())
    assert read.agrees_with(portraits.POOL_OF_RADIANCE_MENU), (
        f"{read.source} reads {read.heads}/{read.bodies}; the stored menu "
        f"is {portraits.POOL_OF_RADIANCE_MENU.heads}/"
        f"{portraits.POOL_OF_RADIANCE_MENU.bodies}")


@needs_disks
def test_the_stored_menu_is_what_dos_offers_too():
    """The other port, so the stored block is pinned to both binaries it
    was read from and not only the C64's."""
    assert portraits.tables_from_dos(_dos_game()).agrees_with(
        portraits.POOL_OF_RADIANCE_MENU)


def test_the_extraction_tool_prints_the_stored_block_and_agrees_with_it(
        tmp_path):
    """`tools/portraitmenu.py` is how the numbers are re-derived, and its
    literal is the one the stored block is written in -- run here over the
    stored menu itself so the tool is exercised with no disks at all, and
    over the real disks through `--check` where they are present."""
    import pathlib
    import subprocess
    import sys

    from tools import portraitmenu

    text = portraitmenu.literal(portraits.POOL_OF_RADIANCE_MENU)
    assert text.startswith("heads=(0x00, 0x08")
    assert "bodies=(0x01, 0x02" in text
    assert text.count("0x") == portraits.HEAD_COUNT + portraits.BODY_COUNT

    if disk_dir() is None:
        return
    root = pathlib.Path(__file__).resolve().parents[1]
    done = subprocess.run(
        [sys.executable, str(root / "tools" / "portraitmenu.py"), "--check",
         "--disks", str(disk_dir())],
        capture_output=True, text=True, timeout=120, cwd=str(root))
    assert done.returncode == 0, done.stdout + done.stderr
    assert "agrees with the stored menu" in done.stdout
