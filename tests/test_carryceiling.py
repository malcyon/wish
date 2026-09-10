"""`tools/carryceiling.py` counts what a character carries against the C64's two ceilings.

`#399 (A conversion that runs out of item or trait slots tells the player
nothing, because the pane never shows a warning)` turns on one number: does
any real character come near sixteen items or ten trait slots?  Everything
below is about the ways a sweep can answer that question wrongly and look
right -- a record graded by whichever copy of it sorted first, an Amiga saved
game read through the wrong title's record shape, a `running` spell counted
as an item's grant, and a C64 title whose disks are on the machine and not in
the registry.

Nothing here reads a game file.  The records are built from the documented
shapes, so the tests run on a machine with no game on it.
"""

from __future__ import annotations

import pathlib

import pytest

from goldbox import amiga, dos, traits
from goldbox import items as c64items
from tools import carryceiling as cc

# -- the ceilings themselves ------------------------------------------------

def test_the_two_ceilings_are_the_ones_the_layouts_declare():
    """The report prints sixteen and ten; both come from the layout.

    A tool that hard-coded either would keep printing it after the layout
    moved, and the whole ticket rests on the distance between these two
    numbers and what a character carries.
    """
    names = {name: value for name, value, _why in cc.CEILINGS}
    assert names["items"] == c64items.ITEMS_PER_CHARACTER == 16
    assert names["trait slots"] == traits.SLOTS == 10
    # Sixteen is not a constant somebody typed: it is the item page divided
    # by the item, and the trait block is ten bytes at 0x0AD.
    assert (c64items.ITEM_BLOCK_STRIDE // c64items.ITEM_SIZE
            == c64items.ITEMS_PER_CHARACTER)
    assert traits.FIRST == 0x0AD


# -- what counts against the ten slots --------------------------------------

def _dos_node(effect_id: int, duration: int) -> bytes:
    """A nine-byte `.SPC` record: id, `u16le` duration, then payload."""
    return bytes((effect_id,)) + duration.to_bytes(2, "little") + bytes(6)


def _amiga_node(effect_id: int, duration: int) -> bytes:
    """The same node with the Amiga's pad byte at offset 1, big-endian."""
    return (bytes((effect_id, 0)) + duration.to_bytes(2, "big") + bytes(6))


def test_a_spell_counting_down_is_not_an_item_grant():
    """A running spell must not be counted against the ten slots.

    `goldbox/dos.py` crosses only the records at duration zero, and Donald
    ruled on 2026-08-27 that a Bless with four rounds left is not a loss
    anybody can see.  Counting it would inflate every trait figure this
    ticket rests on.
    """
    innate_id = sorted(dos.INNATE_EFFECTS)[0]
    nodes = [_dos_node(innate_id, 0),      # racial: innate
             _dos_node(200, 0),            # never expires: an item's grant
             _dos_node(201, 5)]            # counting down: neither
    assert cc._split_effects(nodes, dos.INNATE_EFFECTS) == (1, 1, 1)


def test_the_amiga_duration_word_is_read_past_its_pad_byte():
    """The Amiga node is DOS's nine bytes with one pad inserted at offset 1.

    Reading the duration at DOS's offset would take the pad and the high half
    of the word, so a running spell at duration 5 would read as 0x0005 shifted
    -- and a `granted` count is what decides whether the ten slots overflow.
    """
    nodes = [_amiga_node(200, 0), _amiga_node(201, 5)]
    assert cc._split_effects(nodes, dos.INNATE_EFFECTS, pad=1) == (0, 1, 1)
    # Read with DOS's offsets instead and the two swap places, which is the
    # failure this pad argument exists to prevent.
    assert cc._split_effects(nodes, dos.INNATE_EFFECTS, pad=0) != (0, 1, 1)


def test_trait_demand_is_the_slots_on_the_c64_and_the_two_halves_elsewhere():
    c64 = cc.Carried(port="c64", title="t", grade="found", where="w",
                     who="who", items=3, traits=4, innate=9, granted=9)
    assert c64.trait_demand == 4          # the record's own occupied slots
    off = cc.Carried(port="dos", title="t", grade="found", where="w",
                     who="who", items=3, innate=4, granted=1, running=7)
    assert off.trait_demand == 5          # running is excluded


# -- grading, and the copy that sorted first --------------------------------

def test_a_specimens_provenance_beats_a_copy_left_in_work():
    """The same record in `work/` and in the specimen tree is a specimen.

    `tools/dostailcensus.py` deduplicates on the record's bytes and keeps
    every path it saw.  Grading the first of them called THRENDER GRONE --
    the one record on this machine wanting five trait slots -- `ours`, purely
    because a run directory sorted before the tree, which would have thrown
    away the only engine-written measurement in the census.
    """
    spec = "/home/x/wish-specimens/por-dos/WISH-SPEC-a/CHRDATD1.SAV"
    grades = {spec: "engine"}
    paths = [pathlib.Path("/home/x/src/wish/work/issue232b/CHRDATD1.SAV"),
             pathlib.Path(spec)]
    assert cc._grade_over(paths, grades) == "engine"
    assert cc._grade_over(list(reversed(paths)), grades) == "engine"


def test_a_record_in_the_played_dos_directory_is_graded_edited():
    """Every record there has been through Gold Box Companion's editor.

    Donald, 2026-09-04, of his own played DOS save directory: *"Assume all
    character records in [~/dos_por_play/SAVE] were edited."*  His literal
    path is not spelled out here -- `test_no_hardcoded_user_paths` bans one
    in a string literal, and it catches a quotation as readily as a constant.
    Graded, never dropped: an edited record still says what the container
    will hold.
    """
    played = pathlib.Path("/home/x/dos_por_play/SAVE/CHRDATA1.SAV")
    assert cc._grade_over([played], {}) == "edited"
    assert cc._grade_over([pathlib.Path("/mnt/roms/c64/PORSAVE.D64")], {}) \
        == "found"
    assert cc._grade_over([pathlib.Path("/home/x/src/wish/work/a/b.d64")], {}) \
        == "ours"


# -- the Amiga: the wrong shape reads plausible rubbish ----------------------

def _silver_blades_savegame() -> bytes:
    """A saved game with one Silver Blades record where its header ends.

    Long enough that Curse's 428-byte record would also fit at that offset,
    and far too short for Curse's own party to be where `detect` looks for
    it -- which is the whole of what tells the two apart.
    """
    from tools import amigasavegame
    at = amigasavegame.SILVER_BLADES.party_at
    shape = amiga.SILVER_BLADES_DELTAS
    record = bytearray(shape.record_size)
    record[0:6] = b"MALACH"
    for i in range(6):                    # six equal (current, maximum) pairs
        record[0x10 + 2 * i] = record[0x11 + 2 * i] = 12
    data = bytearray(at + 700)
    data[at:at + shape.record_size] = record
    return bytes(data)


def test_a_silver_blades_saved_game_is_not_read_as_curse():
    """The signature matches under both shapes; only `detect` separates them.

    `party_in_savegame` trusts whatever shape it is handed, so trying each in
    turn read Silver Blades' `savgamA.sav` as two Curse characters on the
    first run of this sweep -- with an `item_count` taken from an offset 84
    bytes away from the real one.
    """
    data = _silver_blades_savegame()
    problems: list[str] = []
    found = list(cc._amiga_later_characters(data, "savegame", "synthetic",
                                            problems))
    assert problems == []
    assert [c.deltas for c in found] == [amiga.SILVER_BLADES_DELTAS]
    # The trap is real: handed Curse's shape, the same bytes parse anyway.
    assert amiga.party_in_savegame(data, amiga.CURSE_DELTAS)


# -- coverage: the titles the registry does not name ------------------------

def test_the_c64_sweep_reaches_a_title_with_no_registry_entry(tmp_path,
                                                              monkeypatch):
    """Three of Wish's six C64 titles have no `gamedisks.toml` entry.

    Champions of Krynn, Death Knights of Krynn and Gateway to the Savage
    Frontier sit beside the three that do, so the sweep takes each registered
    directory's parent as well.  Without that, half the titles are missing
    from a census that reports itself as covering the machine.
    """
    registered = tmp_path / "Pool of Radiance Disks"
    registered.mkdir()
    (registered / "POOL1.D64").write_bytes(b"")
    other = tmp_path / "Champions of Krynn (SSI)"
    other.mkdir()
    (other / "Champions of Krynn (A).d64").write_bytes(b"")
    monkeypatch.setattr(cc.gamedisks, "find",
                        lambda key: registered if key == "pool-of-radiance"
                        else None)
    monkeypatch.setattr(cc, "_specimen_root", lambda: None)
    names = {p.name for p in cc.c64_disks()}
    assert "POOL1.D64" in names
    assert "Champions of Krynn (A).d64" in names


def test_an_extra_disk_named_on_the_command_line_is_swept(tmp_path,
                                                          monkeypatch):
    monkeypatch.setattr(cc.gamedisks, "find", lambda key: None)
    monkeypatch.setattr(cc, "_specimen_root", lambda: None)
    loose = tmp_path / "SOMEWHERE.D64"
    loose.write_bytes(b"")
    assert loose in cc.c64_disks([loose])


# -- the census itself, off the player's own disks --------------------------

def test_no_character_on_this_machine_needs_more_than_ten_trait_slots():
    """The finding, re-taken.  Skips on a machine with no game files.

    A character wanting eleven trait slots is what `#399`'s trait sentence is
    for, and 950 records over three ports produced a maximum of five.  This
    fails the day one turns up, which is the day the sentence is needed.
    """
    problems: list[str] = []
    rows = cc.census(problems)
    if not rows:
        pytest.skip("no game disks, archives or specimens on this machine")
    worst = max(rows, key=lambda r: r.trait_demand)
    assert worst.trait_demand < traits.SLOTS, (
        f"{worst.who} ({worst.port}, {worst.grade}) wants "
        f"{worst.trait_demand} of {traits.SLOTS} trait slots: "
        f"{worst.sources}")
