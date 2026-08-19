"""Tests for por.savegame.

The slot model was corrected once already: it is **8 slots of $100**, not 6 of
$400. The decisive fixture is `party6_savedgame0.bin`, a real save holding a
full six-character party — with only two characters the two models are
indistinguishable, which is how the wrong one survived.
"""

import pathlib

import pytest

from por.record import CharacterRecord, RECORD_SIZE
from por.savegame import (
    HEADER_SIZE,
    ICON_SIZE,
    ICON_TABLE_BASE,
    SAVE0_LOAD_ADDRESS,
    SAVE0_SIZE,
    SAVE1_SIZE,
    SLOT_AREA_BASE,
    SLOT_AREA_END,
    SLOT_COUNT,
    SLOT_STRIDE,
    SaveGame0,
    SaveGame1,
    SaveGameError,
    looks_occupied,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
PARTY = ["MALCYON", "LADY KATHERINE", "ROLAND", "SILAS", "MAGNUS", "BRUTUS"]


@pytest.fixture
def party6() -> SaveGame0:
    """A real save with a full six-character party."""
    return SaveGame0.from_prg((FIXTURES / "party6_savedgame0.bin").read_bytes())


@pytest.fixture
def save0() -> SaveGame0:
    """The earlier single-character save."""
    return SaveGame0.from_prg((FIXTURES / "savedgame0.bin").read_bytes())


class TestSlotGeometry:
    def test_eight_slots_of_256_bytes(self):
        assert (SLOT_COUNT, SLOT_STRIDE) == (8, 0x100)

    def test_slot_area_runs_4d00_to_54ff(self):
        assert SLOT_AREA_BASE == 0x4D00
        assert SLOT_AREA_END == 0x5500

    def test_icon_table_ends_exactly_where_slot_0_begins(self):
        """8 icons of 36 bytes at $4BE0 -> $4D00. The count matching the slot
        count is what first suggested 8 slots."""
        assert ICON_TABLE_BASE + 8 * ICON_SIZE == SLOT_AREA_BASE

    def test_slot_addresses(self, party6):
        assert [s.address for s in party6.slots] == [
            0x4D00, 0x4E00, 0x4F00, 0x5000, 0x5100, 0x5200, 0x5300, 0x5400
        ]


class TestFullParty:
    def test_all_six_characters_are_found(self, party6):
        assert [s.record.name for s in party6.characters] == PARTY

    def test_they_occupy_consecutive_slots(self, party6):
        assert [s.index for s in party6.characters] == [0, 1, 2, 3, 4, 5]

    @pytest.mark.parametrize("name,fixture", [
        ("MALCYON", "malcyon.chr"),
        ("LADY KATHERINE", "lady_katherine.chr"),
        ("BRUTUS", "brutus.chr"),
    ])
    def test_slot_matches_the_exported_file_exactly(self, party6, name, fixture):
        """A slot stores the first 256 bytes of the record, byte for byte.

        This is what disproved the $400 model: under it these bytes would have
        overlapped the neighbouring character.
        """
        slot = next(s for s in party6.characters if s.record.name == name)
        export = CharacterRecord.from_prg((FIXTURES / fixture).read_bytes())
        assert slot.record_bytes == export.to_bytes()[:SLOT_STRIDE]

    def test_decoded_fields_survive_the_256_byte_truncation(self, party6):
        malcyon = party6.slot(0).record
        assert (malcyon.name, malcyon.race, malcyon.char_class) == ("MALCYON", 2, 5)
        assert malcyon.age == 176                       # elf
        katherine = party6.slot(1).record
        assert (katherine.race, katherine.char_class) == (4, 16)   # half-elf multi-class

    def test_class_five_is_magic_user_by_its_saving_throws(self, party6):
        """AD&D 1e L1 magic-user table. This is what showed class 5 is
        magic-user, not monk as the creation-menu ordering suggested."""
        r = party6.slot(0).record
        assert [r.save_paralysis, r.save_petrification, r.save_wands,
                r.save_breath, r.save_spell] == [14, 13, 11, 15, 12]

    def test_dwarf_saving_throws_carry_the_racial_bonus(self, party6):
        """MAGNUS is a dwarf fighter with CON 13. His saves are the fighter
        table minus floor(13/3.5) = 3, so saves are stored already adjusted for
        race as well as class."""
        magnus = next(s.record for s in party6.characters if s.record.name == "MAGNUS")
        fighter = [14, 15, 16, 17, 17]
        assert [magnus.save_paralysis, magnus.save_petrification, magnus.save_wands,
                magnus.save_breath, magnus.save_spell] == [v - 3 for v in fighter]

    def test_item_area_is_empty_before_anything_is_bought(self, party6):
        data = party6.to_bytes()
        item_area = data[SLOT_AREA_END - SAVE0_LOAD_ADDRESS:]
        assert set(item_area) == {0}


class TestSingleCharacterSave:
    def test_only_slot_zero_is_live(self, save0):
        """The stale BRUTUS copy at $5500 sits outside the slot area entirely."""
        assert [s.index for s in save0.characters] == [0]
        assert save0.slot(0).record.name == "BRUTUS"


class TestRoundTrip:
    def test_prg_round_trip_is_byte_exact(self, party6):
        raw = (FIXTURES / "party6_savedgame0.bin").read_bytes()
        assert party6.to_prg() == raw

    def test_save1_is_opaque_but_survives(self):
        raw = (FIXTURES / "savedgame1.bin").read_bytes()
        s1 = SaveGame1.from_prg(raw)
        assert len(s1.to_bytes()) == SAVE1_SIZE
        assert s1.to_prg() == raw


class TestWriteRecord:
    def test_editing_one_field_changes_exactly_one_byte(self, party6):
        before = party6.to_bytes()
        rec = party6.slot(2).record
        rec.strength = 9
        party6.write_record(2, rec)
        changed = [i for i, (a, b) in enumerate(zip(before, party6.to_bytes())) if a != b]
        assert changed == [HEADER_SIZE + 2 * SLOT_STRIDE + 0x14]

    def test_write_does_not_spill_into_the_next_slot(self, party6):
        """A full 580-byte record is longer than a slot; the tail must be
        dropped rather than overwriting the neighbour."""
        neighbour = party6.slot(3).window
        rec = party6.slot(2).record
        rec.name = "ZZZ"
        party6.write_record(2, rec)
        assert party6.slot(3).window == neighbour

    def test_write_back_unchanged_is_a_no_op(self, party6):
        before = party6.to_bytes()
        for s in party6.characters:
            party6.write_record(s.index, s.record)
        assert party6.to_bytes() == before

    def test_accepts_a_bare_256_byte_slot_image(self, party6):
        before = party6.to_bytes()
        party6.write_record(0, party6.slot(0).record_bytes)
        assert party6.to_bytes() == before

    def test_wrong_size_raises(self, party6):
        with pytest.raises(SaveGameError):
            party6.write_record(0, b"\x00" * 99)

    def test_out_of_range_slot_raises(self, party6):
        with pytest.raises(IndexError):
            party6.write_record(SLOT_COUNT, party6.slot(0).record)


class TestValidation:
    def test_wrong_payload_size_raises(self):
        with pytest.raises(SaveGameError):
            SaveGame0(b"\x00" * 100)

    def test_wrong_load_address_raises(self):
        bad = (0x1234).to_bytes(2, "little") + b"\x00" * SAVE0_SIZE
        with pytest.raises(SaveGameError):
            SaveGame0.from_prg(bad)


class TestOccupancyHeuristic:
    def test_all_zero_window_is_empty(self):
        assert not looks_occupied(bytes(SLOT_STRIDE))

    def test_needs_plausible_ability_scores(self, party6):
        w = bytearray(party6.slot(0).window)
        w[0x14] = 200
        assert not looks_occupied(bytes(w))

    def test_needs_a_letter_for_the_first_name_byte(self, party6):
        w = bytearray(party6.slot(0).window)
        w[0] = 0
        assert not looks_occupied(bytes(w))

    def test_stale_slots_are_rejected(self, party6):
        """Slots 6 and 7 hold leftover bytes from an earlier save with the
        first name byte zeroed; they must not read as live characters."""
        for i in (6, 7):
            assert not party6.slot(i).occupied
            assert any(party6.slot(i).window)


# --- SAVEDGAME1 roster blocks ------------------------------------------------

class TestRosterBlocks:
    """The first page of SAVEDGAME1 is eight 32-byte per-character blocks. This
    is where the game caches what it derives -- armour class, THAC0, current hit
    points -- none of which is in the character record."""

    def _save1(self):
        import pathlib
        p = pathlib.Path("/mnt/media/roms/c64/Pool of Radiance Disks/PORSAVE2.D64")
        if not p.exists():
            pytest.skip("needs a real save disk")
        from por.d64 import D64
        return SaveGame1.from_prg(D64.open(str(p)).read_file(b"SAVEDGAME1"))

    def test_the_roster_is_exactly_one_page(self):
        from por.savegame import (ROSTER_AREA_END, ROSTER_COUNT, ROSTER_STRIDE,
                                  SAVE1_LOAD_ADDRESS)
        assert ROSTER_COUNT * ROSTER_STRIDE == 0x100
        assert SAVE1_LOAD_ADDRESS == 0x8300 and ROSTER_AREA_END == 0x8400

    def test_occupancy_matches_the_party(self):
        sg1 = self._save1()
        assert [b.occupied for b in sg1.roster_blocks] == [True] * 6 + [False] * 2

    def test_the_index_byte_matches_the_slot(self):
        sg1 = self._save1()
        assert [b.slot_index for b in sg1.roster_blocks[:6]] == list(range(6))

    def test_values_match_the_character_sheet(self):
        """MALCYON's sheet reads AC 8, THACO 20, HITPOINTS 4."""
        b = self._save1().roster(0)
        assert (b.armour_class, b.thac0, b.hit_points) == (8, 20, 4)

    def test_combat_numbers_are_stored_biased(self):
        b = self._save1().roster(0)
        assert b.raw[0x0F] == 60 - b.armour_class
        assert b.raw[0x0E] == 60 - b.thac0

    def test_writes_touch_only_their_own_byte(self):
        sg1 = self._save1()
        before = sg1.to_bytes()
        sg1.roster(3).armour_class = 5
        after = sg1.to_bytes()
        assert [i for i in range(len(before)) if before[i] != after[i]] == [3 * 0x20 + 0x0F]

    def test_round_trip_is_byte_exact(self):
        sg1 = self._save1()
        assert SaveGame1(sg1.to_bytes()).to_bytes() == sg1.to_bytes()

    def test_a_value_that_cannot_be_stored_is_refused(self):
        sg1 = self._save1()
        with pytest.raises(SaveGameError):
            sg1.roster(0).armour_class = 999
        with pytest.raises(SaveGameError):
            sg1.roster(0).spells_memorised = (1, 2)
