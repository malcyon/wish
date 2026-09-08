"""The `+$C00` name table is a directory buffer, not a record.

`#435 (A rename in Wish leaves the C64 name table holding the old name on
Curse and Silver Blades, and nobody knows what reads it)`.  Wish edits the
256-byte save slot and leaves the second copy of the party's names alone, and
the question was what a player sees.  Nothing: `GEN` clears all 256 bytes and
refills them from the save disk's own directory before every one of its three
reads, so the bytes a save carries there are overwritten before any code looks
at them.

What is asserted here is the half a machine with no emulator can check -- the
six code sites in each title's own `GEN`, the filename prefix read off the
game rather than written down, and the three readings of a save disk that
disagree.  The running-game half is `tools/c64nametable.py run`, and `#435`
carries what it saw: on `work/issue435/ssb3`, an engine `SAVE CURRENT GAME`
stored a one-entry table naming a character who was **not** in the
five-strong party it saved.

Every test skips without the player's disks, which CI has none of.
"""

import pathlib

import pytest

from goldbox.d64 import D64
from tests import gamedata
from tools import c64nametable as nt
from tools import gamedisks

TITLES = ("curse-of-the-azure-bonds", "secret-of-the-silver-blades")


def gen_for(title: str) -> bytes:
    root = gamedisks.find(title)
    if root is None or not pathlib.Path(root).is_dir():
        pytest.skip(f"no {title} disks here; set $POR_DISKS")
    return nt.gen_body(title, None)


def specimen_disk(name: str) -> pathlib.Path:
    """A single-file C64 specimen, or a skip.  The hash check is
    `tests/test_ssbeditorpath.py`'s; this reads bytes the engine wrote and
    an edited copy would still make the point it makes."""
    root = gamedata.specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    found = sorted(root.glob(f"*-c64/WISH-SPEC-{name}.[dD]64"))
    if not found:
        pytest.skip(f"needs the C64 specimen WISH-SPEC-{name}")
    return found[0]


# --- the code sites ----------------------------------------------------------

@pytest.mark.parametrize("title", TITLES)
def test_gen_touches_the_table_in_six_places_and_no_others(title):
    """Six sites, and the four shapes they come in.

    A seventh would be a reader nobody has accounted for, which is exactly
    what would reopen `#435`.
    """
    kinds = [kind for _at, _text, kind in nt.sites(gen_for(title))]
    assert len(kinds) == 6, kinds
    assert kinds.count("clears all 256 bytes") == 1
    assert kinds.count("writes a name into an entry") == 2
    assert kinds.count("compares an entry against the record at $7C00") == 2
    assert kinds.count("copies an entry out to the text buffer at $7A00") == 1


@pytest.mark.parametrize("title,want", [("curse-of-the-azure-bonds", 0x02),
                                        ("secret-of-the-silver-blades", 0x05)])
def test_the_filename_prefix_comes_off_the_scratch_template(title, want):
    """`S0:` and then the byte `GEN` puts in front of a character's name.

    `GEN` carries a second `S0:` -- `S0:SAVEDBASH`, the save file's own
    scratch -- and taking the first match reads `$53`, the `S` of `SAVEDBASH`.
    """
    assert nt.prefix(gen_for(title)) == want


def test_pool_of_radiance_has_no_such_table():
    """The title the ticket cannot affect: `c64_save` gives it no table, so
    `table_entries` has nothing to hand back."""
    disk = gamedata.save_disk("PORSAVE")
    game, _at, entries = nt.table_entries(D64.open(str(disk)))
    assert game.key == "pool-of-radiance"
    assert entries == []


# --- the three readings of a disk --------------------------------------------

def test_curse_ships_a_save_whose_table_names_nobody_on_the_disk():
    """Four character files, six table entries, and no name in common.

    `WISH-SPEC-curse-party-with-items` is the engine's own, and it disagrees
    with itself before Wish touches anything -- which is what a buffer saved
    by accident looks like and a record would not.
    """
    disk = D64.open(str(specimen_disk("curse-party-with-items")))
    _game, _at, entries = nt.table_entries(disk)
    stored = [nt.as_name(e) for e in entries if nt.as_name(e)]
    files = nt.character_files(disk, 0x02)
    assert sorted(files) == ["ARDEN", "BRISA", "ELVYN", "KORDAN"]
    assert set(stored).isdisjoint(files)
    assert stored == nt.party(disk)


@pytest.mark.parametrize("name,prefix", [
    ("curse-h-engine-resave", 0x02),
    ("ssb-d-engine-resave", 0x05),
])
def test_an_engine_written_save_can_name_six_characters_with_no_files(
        name, prefix):
    """The table survives a save that has no character files at all.

    So a stored entry is not a claim that the file exists, and a conversion
    writing the table writes something the game will overwrite either way.
    """
    disk = D64.open(str(specimen_disk(name)))
    _game, _at, entries = nt.table_entries(disk)
    stored = [nt.as_name(e) for e in entries if nt.as_name(e)]
    assert len(stored) == 6
    assert nt.character_files(disk, prefix) == []


# --- the bar the add screen opens with ---------------------------------------

@pytest.mark.parametrize("bar,want", [
    ("ADD FROM: CURSE POOL HILLSFAR EXIT", "CURSE"),
    ("ADD FROM: SECRET CURSE EXIT", "SECRET"),
    ("MOVE VIEW CAST EXIT", ""),
])
def test_the_add_bar_names_which_game_to_read_the_disk_as(bar, want):
    """Both bars were photographed on 2026-09-08, in `work/issue435/curse3`
    and `work/issue435/ssb3`.  The word chosen is the filename prefix byte
    the directory scan then filters on, so taking the wrong one lists another
    game's characters."""
    assert nt.from_bar("\n".join(["", "", bar])) == want
