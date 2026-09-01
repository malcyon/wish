"""Regression tests for #160: the automapper and the editor list the party
backwards.

Both `automap.live.characters()` and `editor.roster.Party._load_save` used to
walk `SaveGame0.characters`, the slot array's own ascending order, where the
C64 lists the party from the **highest** occupied slot down
(`goldbox/savegame.py`'s `marching_order`, `docs/30-savegame-layout.md`).

The gap case is built rather than found: `ALTER > DROP` can leave a hole
without packing the party down, and none of the 29 saves on this machine has
one, so a naive `reversed(range(SLOT_COUNT))` would pass every save here and
still be wrong.
"""

from automap import live
from editor.roster import Party
from goldbox.d64 import D64, attach_load_address
from goldbox.games import POOL_OF_RADIANCE
from goldbox.record import CharacterRecord
from goldbox.savegame import SaveGame0

#: A party in slots 1-4, with slot 0 and slots 5-7 left empty.
GAP_NAMES = {1: "BRUTUS", 2: "ROLAND", 3: "MAGNUS", 4: "SILAS"}
#: The order the game lists them: highest occupied slot first.
GAP_ORDER = ["SILAS", "MAGNUS", "ROLAND", "BRUTUS"]


def _record_named(name: str) -> CharacterRecord:
    record = CharacterRecord.blank()
    record.set("name", name)
    for ability in ("strength", "intelligence", "wisdom", "dexterity",
                    "constitution", "charisma"):
        record.set(ability, 10)
    return record


def _gap_save0_bytes() -> bytes:
    """A `SAVEDGAME0` payload built from the format, holding `GAP_NAMES`."""
    sg0 = SaveGame0(bytes(POOL_OF_RADIANCE.save_size))
    for index, name in GAP_NAMES.items():
        sg0.write_record(index, _record_named(name))
    return sg0.to_bytes()


def _gap_disk_bytes() -> bytes:
    """A save disk carrying the same gap party, for the editor's own loader."""
    game = POOL_OF_RADIANCE
    disk = D64.blank()
    disk.write_file(game.save_file, attach_load_address(
        game.save_load_address, _gap_save0_bytes()))
    disk.write_file(game.roster_file, attach_load_address(
        game.roster_load_address, bytes(game.roster_size)))
    return disk.to_bytes()


class TestLiveCharactersOrder:
    """`automap.live.characters()`, exercised through `snapshot_from_bytes` --
    the one entry point everything the automapper draws goes through."""

    def test_a_gap_lists_the_highest_occupied_slot_first(self):
        snap = live.snapshot_from_bytes(
            _gap_save0_bytes(), bytes(POOL_OF_RADIANCE.roster_size),
            game=POOL_OF_RADIANCE)
        assert snap is not None
        assert [c.name for c in snap.characters] == GAP_ORDER
        # `Character.slot` still carries the real slot -- `automap/panel.py`
        # sets `card.slot = who.slot` from it, so nothing downstream needed
        # to change for the display order to fix itself.
        assert [c.slot for c in snap.characters] == [4, 3, 2, 1]


class TestEditorRosterOrder:
    """`editor.roster.Party._load_save`."""

    def test_a_gap_lists_the_highest_occupied_slot_first(self, tmp_path):
        path = tmp_path / "GAP.D64"
        path.write_bytes(_gap_disk_bytes())
        party = Party(str(path))
        assert party.is_save
        assert [m.name for m in party.members] == GAP_ORDER
        # `Member.index` still carries the real slot.
        assert [m.index for m in party.members] == [4, 3, 2, 1]

    def test_a_write_still_lands_in_the_real_slot(self, tmp_path):
        """The dangerous regression: a party listed in a different order from
        the slot array must still write back into the slot it occupies, or
        the display fix would corrupt the save."""
        path = tmp_path / "GAP.D64"
        path.write_bytes(_gap_disk_bytes())
        party = Party(str(path))
        silas = next(m for m in party.members if m.name == "SILAS")
        assert silas.index == 4   # highest occupied slot -- listed first
        silas.record.set("strength", 18)
        # The real write path -- editor/window.py:1054 -- keys off
        # `m.index`, not the row a member is drawn at.
        party.save0.write_record(silas.index, silas.record)

        reread = SaveGame0.from_bytes(party.save0.to_bytes(), POOL_OF_RADIANCE)
        assert reread.slot(4).record.name == "SILAS"
        assert reread.slot(4).record.strength == 18
        # A neighbour the write did not touch stays exactly where it was.
        assert reread.slot(1).record.name == "BRUTUS"
        assert reread.slot(1).record.strength == 10
