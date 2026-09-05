"""A `POOLSAVE` save disk, formatted from nothing (#36).

Every test here runs on a disk `goldbox.amiga_adf` formats itself, so no game
data is involved and they run wherever the suite does.

The thing being pinned is a difference of one string. Amiga Pool of Radiance
builds every save filename by sticking it on the end of whatever the player
typed at `PATH FOR SAVE`, so answering `SAVE/` opens `SAVE/save` in the game
disk's drawer and answering the prompt's own default, `POOLSAVE:`, opens
`POOLSAVE:save` in the root of a separate volume. `docs/191-the-amiga-save-
disk.md` has the run that proved it and the screens it drew.
"""

from __future__ import annotations

import pytest
from test_amiga import sample, synthetic_savegame

from goldbox import amiga
from goldbox.amiga_adf import AmigaDisk, AmigaDiskError

SLOT_FILES = ["savgamB.dat"] + [
    f"CHRDATB{n}{suffix}"
    for n in range(1, amiga.POR_PARTY_MAX + 1)
    for suffix in (".sav", ".itm", ".spc")
]


def party(count: int = 2):
    """A party built rather than read, one character per name."""
    return [sample(name=name) for name in ("AELFRIC", "BRUNHILD")[:count]]


def save_disk(slot: str = "B", count: int = 2) -> AmigaDisk:
    return amiga.make_por_save_disk(slot, party(count), synthetic_savegame())


def game_disk(slot: str = "B", count: int = 2) -> AmigaDisk:
    """The other route: a `save` drawer on a copy of the game disk."""
    disk = AmigaDisk.blank("poolgame")
    disk.make_dir("save")
    disk.write_file(amiga.POR_SLOT_LIST, amiga.slot_list_bytes(["A"]))
    amiga.write_por_slot(disk, slot, party(count), synthetic_savegame())
    return disk


def test_the_two_answers_to_the_path_prompt_give_two_layouts():
    """`SAVE/` + `save` is a drawer; `POOLSAVE:` + `save` is a root."""
    assert amiga.por_save_path("save") == "/save/save"
    assert amiga.por_save_path("savgamB.dat") == "/save/savgamB.dat"
    assert amiga.por_save_path("save", "") == "/save"
    assert amiga.por_save_path("savgamB.dat", "") == "/savgamB.dat"


def test_a_save_disk_is_a_poolsave_volume_with_the_slot_in_its_root():
    disk = save_disk()
    assert disk.volume_name == "POOLSAVE"
    assert amiga.POR_SAVE_VOLUME == "POOLSAVE"
    assert disk.verify() == []
    assert disk.read_file("/CHRDATB1.sav")
    assert disk.read_file("/savgamB.dat")
    # And there is no drawer, which is the whole difference from the other
    # route: a player pressing RETURN at the prompt reaches the root.
    with pytest.raises(AmigaDiskError):
        disk.lookup("/save/CHRDATB1.sav")
    assert [name for _, entry in disk.walk() if entry.is_dir
            for name in (entry.name,)] == []


def test_the_picker_reads_the_slot_list_from_the_root_of_a_save_disk():
    """What the player sees at `LOAD WHICH GAME`, and where it is read from.

    The second assertion is the one that catches a save disk built with the
    drawer left in by mistake: the files would all be there, `verify()` would
    be clean, and the game would offer nothing.
    """
    disk = save_disk()
    assert amiga.read_slot_list(disk, "") == ["B"]
    assert disk.read_file("/save") == b" B        "
    assert amiga.read_slot_list(disk) == []


def test_the_slot_list_on_a_save_disk_is_an_array_indexed_by_letter():
    """A second slot lands in its own byte, not appended to a list.

    The engine wrote slot `C` onto exactly this disk in the running game and
    the file came back `' BC       '` -- C in byte 2, with byte 0 still a
    space because no A was ever on it.
    """
    disk = save_disk()
    amiga.write_por_slot(disk, "C", party(), synthetic_savegame(), drawer="")
    assert disk.read_file("/save") == b" BC       "
    assert amiga.read_slot_list(disk, "") == ["B", "C"]
    assert disk.verify() == []


def test_a_save_disk_and_a_game_disk_carry_the_same_slot_byte_for_byte():
    """The disk is where the files go, not what they are.

    Eleven files in the running game, all identical between the two routes;
    here it is however many the built party has. If this ever fails, one of
    the two paths has grown a behaviour of its own.
    """
    fresh, copy = save_disk(), game_disk()
    compared = 0
    for name in SLOT_FILES:
        try:
            theirs = copy.read_file(f"/save/{name}")
        except AmigaDiskError:
            with pytest.raises(AmigaDiskError):
                fresh.lookup(f"/{name}")
            continue
        assert fresh.read_file(f"/{name}") == theirs, name
        compared += 1
    assert compared >= 3


def test_a_save_disk_ships_the_empty_character_list_the_game_disk_does():
    """`charlist.txt` is zero bytes on disk 1 and the game opens it by name.

    Without one, the first `ADD CHARACTER TO PARTY` on a save disk would meet
    `file not found,check your save path` -- which is the game's own string,
    at 122608 in `/program`.
    """
    disk = save_disk()
    assert disk.read_file(f"/{amiga.POR_CHARACTER_LIST_NAME}") == b""


def test_the_saved_game_on_a_save_disk_names_this_slots_own_files():
    """The engine loads the party the character table names, not the letter."""
    disk = save_disk()
    save = disk.read_file("/savgamB.dat")
    names = [
        save[at:at + amiga.POR_CHARACTER_TABLE_NAME]
        for at in (amiga.POR_CHARACTER_TABLE
                   + n * amiga.POR_CHARACTER_TABLE_STRIDE
                   for n in range(amiga.POR_PARTY_MAX))
    ]
    assert names == [f"CHRDATB{n}".encode("ascii") for n in range(1, 7)]


def test_a_saved_game_of_the_wrong_size_is_refused_before_anything_is_written():
    """A save disk is formatted here, so a refusal costs the caller nothing.

    It still has to be a refusal rather than a disk with a 13,000-byte
    container on it: the game reads a fixed length.
    """
    with pytest.raises(amiga.AmigaRecordError):
        amiga.make_por_save_disk("B", party(), b"\0" * 13000)
