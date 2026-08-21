"""Tests for por.savegame.

The slot model was corrected once already: it is **8 slots of $100**, not 6 of
$400. The decisive fixture is `party6_savedgame0.bin`, a real save holding a
full six-character party — with only two characters the two models are
indistinguishable, which is how the wrong one survived.
"""

import pathlib

import pytest
from gamedata import disk_dir

from por.record import CharacterRecord
from por.savegame import (
    HEADER_SIZE,
    ICON_SIZE,
    ICON_TABLE_BASE,
    ITEM_AREA_BASE,
    SAVE0_LOAD_ADDRESS,
    SAVE0_SIZE,
    SAVE1_SIZE,
    SLOT_AREA_BASE,
    SLOT_AREA_END,
    SLOT_COUNT,
    SLOT_STRIDE,
    STAGING_PAGE_BASE,
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
        from por.savegame import (
            ROSTER_AREA_END,
            ROSTER_COUNT,
            ROSTER_STRIDE,
            SAVE1_LOAD_ADDRESS,
        )
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
            sg1.roster(0).unknown_03_05 = (1, 2)


class TestStagingPage:
    """$5500 holds one record in the character layout -- whatever the game last
    loaded there. See docs/50-experiments.md, "the orc left behind at $5500"."""

    DISKS = str(disk_dir() or "no-disks-here")

    @staticmethod
    def _page(save: SaveGame0) -> bytes:
        off = STAGING_PAGE_BASE - SAVE0_LOAD_ADDRESS
        return save.to_bytes()[off:off + SLOT_STRIDE]

    def test_it_is_the_page_right_after_the_slots(self):
        assert STAGING_PAGE_BASE == SLOT_AREA_END

    def test_empty_before_the_fight_and_a_monster_after(self, party6):
        after = SaveGame0.from_prg(
            (FIXTURES / "party6_after_combat.bin").read_bytes())
        assert set(self._page(party6)) == {0}
        page = self._page(after)
        assert page[:3] == b"ORC"
        assert sum(1 for b in page if b) == 79

    def test_the_single_character_save_holds_a_copy_of_slot_zero(self, save0):
        assert self._page(save0) == save0.slot(0).record_bytes

    def test_only_one_record_wide(self, party6):
        """$5600-$58FF is zero in every save we hold."""
        after = SaveGame0.from_prg(
            (FIXTURES / "party6_after_combat.bin").read_bytes())
        base = STAGING_PAGE_BASE + SLOT_STRIDE - SAVE0_LOAD_ADDRESS
        end = ITEM_AREA_BASE - SAVE0_LOAD_ADDRESS
        assert set(after.to_bytes()[base:end]) == {0}

    def test_the_monster_is_MON04_bar_two_bytes(self):
        """The game fills strength_index in from the ability score, and
        overwrites one of the NPC marker bytes."""
        import pathlib as _p
        disk = _p.Path(f"{self.DISKS}/POOL1.D64.orig")
        if not disk.exists():
            pytest.skip("needs a game disk")
        from por.d64 import D64, split_load_address
        _, mon = split_load_address(D64.open(str(disk)).read_file(b"MON04"))
        after = SaveGame0.from_prg(
            (FIXTURES / "party6_after_combat.bin").read_bytes())
        page = self._page(after)
        differing = [i for i in range(SLOT_STRIDE) if page[i] != mon[i]]
        assert differing == [0x0E2, 0x0FB]
        assert mon[0x0E2] == 0xFF and page[0x0E2] == mon[0x014] == 10  # STR


class TestRosterSpellCounts:
    """+0x03-+0x05 were read as per-level counts of the memorised list, and
    retracted. The evidence on both sides is pinned here so neither is lost.
    See docs/50-experiments.md, "the spell counts, and how thin the retraction
    was"."""

    DISKS = str(disk_dir() or "no-disks-here")

    def _pair(self, path):
        import pathlib as _p
        p = _p.Path(path)
        if not p.exists():
            pytest.skip(f"needs {p.name}")
        from por.d64 import D64
        img = D64.open(str(p))
        return (SaveGame0.from_prg(img.read_file(b"SAVEDGAME0")),
                SaveGame1.from_prg(img.read_file(b"SAVEDGAME1")))

    @staticmethod
    def _by_level(record):
        from collections import Counter

        from por.spells import spell_group
        ids = [b for b in record.get_raw("spells_memorised") if b]
        per = Counter(spell_group(i)[1] for i in ids)
        return (per.get(1, 0), per.get(2, 0), per.get(3, 0))

    def test_npc_party_agrees_level_by_level(self):
        """Eight for eight, per level -- not merely in sum, as first recorded."""
        import os
        sg0, sg1 = self._pair(os.path.expanduser("~/Downloads/npc_party.d64"))
        for slot in sg0.characters:
            assert self._by_level(slot.record) == sg1.roster(slot.index).unknown_03_05

    def test_porsave11_agrees_too(self):
        sg0, sg1 = self._pair(f"{self.DISKS}/PORSAVE11.D64")
        for slot in sg0.characters:
            assert self._by_level(slot.record) == sg1.roster(slot.index).unknown_03_05

    def test_but_porsave4_does_not(self):
        """The observation that retracted the reading. ROLAND holds three
        level-1 cleric spells and the roster reads 0/0/0."""
        sg0, sg1 = self._pair(f"{self.DISKS}/PORSAVE4.D64")
        roland = next(s for s in sg0.characters if s.record.name == "ROLAND")
        assert self._by_level(roland.record) == (3, 0, 0)
        assert sg1.roster(roland.index).unknown_03_05 == (0, 0, 0)

    def test_the_contradicting_page_is_one_observation_not_eight(self):
        """PORSAVE2-PORSAVE9 share a byte-identical roster page, so the reading
        fails on one stale cache rather than on eight independent saves."""
        pages = []
        for n in range(2, 10):
            _, sg1 = self._pair(f"{self.DISKS}/PORSAVE{n}.D64")
            pages.append(sg1.to_bytes()[:0x100])
        assert len(set(pages)) == 1


class TestShippedNpcRecords:
    """The five NPCs on npc_party.d64 are records the game itself ships, and the
    "NPC marker" is $FF in the shipped file. See docs/50-experiments.md,
    "PRINCESS FATIMA was never impossible"."""

    DISKS = str(disk_dir() or "no-disks-here")
    SHIPPED = {
        "GENHEERIS": ("POOL5.D64", b"MON58"),
        "MAD MAN": ("POOL2.D64", b"MON19"),
        "PRINCESS FATIMA": ("POOL8.D64", b"MON68"),
        "DIRTEN": ("POOL3.D64", b"MON6B"),
        "SKULLCRUSHER": ("POOL4.D64", b"MON1B"),
    }

    def _monster(self, disk, name):
        import pathlib as _p
        p = _p.Path(f"{self.DISKS}/{disk}")
        if not p.exists():
            pytest.skip("needs the game disks")
        from por.d64 import D64, split_load_address
        _, payload = split_load_address(D64.open(str(p)).read_file(name))
        return payload

    def _npc_party(self):
        import os
        import pathlib as _p
        p = _p.Path(os.path.expanduser("~/Downloads/npc_party.d64"))
        if not p.exists():
            pytest.skip("needs npc_party.d64")
        from por.d64 import D64
        return SaveGame0.from_prg(D64.open(str(p)).read_file(b"SAVEDGAME0"))

    def test_fatimas_race_is_the_one_the_game_shipped(self):
        """Race 0 was called impossible and used as proof of tampering."""
        sg = self._npc_party()
        slot = next(s for s in sg.characters
                    if s.record.name == "PRINCESS FATIMA")
        shipped = self._monster(*self.SHIPPED["PRINCESS FATIMA"])
        assert slot.record.get("race") == shipped[0x072] == 0
        same = sum(1 for i in range(SLOT_STRIDE)
                   if slot.record_bytes[i] == shipped[i])
        assert same == 252

    def test_every_npc_is_a_shipped_record_and_no_pc_is(self):
        sg = self._npc_party()
        for slot in sg.characters:
            name = slot.record.name
            if name in self.SHIPPED:
                shipped = self._monster(*self.SHIPPED[name])
                same = sum(1 for i in range(SLOT_STRIDE)
                           if slot.record_bytes[i] == shipped[i])
                assert slot.record.is_npc and same >= 230, name
            else:
                assert not slot.record.is_npc, name

    def test_the_marker_bytes_are_FF_before_any_save_exists(self):
        """So the marker is fill residue, not a flag the game sets on joining."""
        from por.record import NPC_MARKER, NPC_MARKER_OFFSETS
        for disk, name in self.SHIPPED.values():
            shipped = self._monster(disk, name)
            assert all(shipped[o] == NPC_MARKER for o in NPC_MARKER_OFFSETS), name

    def test_no_record_anywhere_uses_race_8(self):
        """MONSTER=8 is enumerated and never instantiated, like PALADIN."""
        import pathlib as _p

        from por.d64 import D64, split_load_address
        races = set()
        for n in range(1, 9):
            disk = _p.Path(f"{self.DISKS}/POOL{n}.D64"
                           if n != 1 else f"{self.DISKS}/POOL1.D64.orig")
            if not disk.exists():
                pytest.skip("needs the game disks")
            img = D64.open(str(disk))
            for e in img.directory():
                if bytes(e.name).startswith(b"MON"):
                    _, p = split_load_address(img.read_file(e))
                    races.add(p[0x072])
        assert 8 not in races
        assert 0 in races


class TestTheCacheRefreshed:
    """PORSAVE11: MALCYON's armour class finally caught up with the dexterity
    the thirteen-field edit gave him, and landed on what por.derive predicts.
    See docs/50-experiments.md, "the spell counts, and how thin the retraction
    was"."""

    DISKS = str(disk_dir() or "no-disks-here")

    def _save(self, name):
        import pathlib as _p
        p = _p.Path(f"{self.DISKS}/{name}.D64")
        if not p.exists():
            pytest.skip("needs the later save disks")
        from por.d64 import D64
        img = D64.open(str(p))
        return (SaveGame0.from_prg(img.read_file(b"SAVEDGAME0")),
                SaveGame1.from_prg(img.read_file(b"SAVEDGAME1")))

    def test_armour_class_was_stale_and_is_now_right(self):
        from por import derive
        for name, expected in (("PORSAVE9", 8), ("PORSAVE11", 6)):
            sg0, sg1 = self._save(name)
            malcyon = sg0.slot(0)
            assert malcyon.record.name == "MALCYON"
            assert malcyon.record.get("dexterity") == 18
            assert sg1.roster(0).armour_class == expected
            assert derive.expected_armour_class(malcyon.record, []) == 6

    def test_strength_index_caught_up_too(self):
        """0x0E2 sat at his pre-edit Strength of 15 for eight saves."""
        assert self._save("PORSAVE9")[0].slot(0).record.get("strength_index") == 15
        assert self._save("PORSAVE11")[0].slot(0).record.get("strength_index") == 18

    def test_eighteen_with_a_zero_percentile_is_plain_eighteen(self):
        sg0, _ = self._save("PORSAVE11")
        by_name = {s.record.name: s.record for s in sg0.characters}
        assert by_name["MALCYON"].get("exceptional_strength") == 0
        assert by_name["MALCYON"].get("strength_index") == 18
        assert by_name["SILAS"].get("strength_index") == 21    # 18/81
        assert by_name["BRUTUS"].get("strength_index") == 22   # 18/98


class TestPartyPosition:
    """Where the party stands, established by walking known distances in known
    directions. Three steps north moved y by exactly 3 and left x alone; three
    steps west did the reverse; turning on the spot moved only facing."""

    DISKS = str(disk_dir() or "no-disks-here")

    def _save(self, name):
        import pathlib
        p = pathlib.Path(f"{self.DISKS}/{name}.D64")
        if not p.exists():
            pytest.skip("needs the walk-experiment save disks")
        from por.d64 import D64
        return SaveGame0.from_prg(D64.open(str(p)).read_file(b"SAVEDGAME0"))

    def test_three_steps_north_moves_only_y(self):
        before, after = self._save("PORSAVE6").party, self._save("PORSAVE7").party
        assert (before.x, before.y) == (3, 14)
        assert (after.x, after.y) == (3, 11)          # y fell by exactly 3
        assert after.facing == before.facing          # walking does not turn you

    def test_three_steps_west_moves_only_x(self):
        before, after = self._save("PORSAVE7").party, self._save("PORSAVE8").party
        assert (before.x, before.y) == (3, 11)
        assert (after.x, after.y) == (0, 11)          # x fell by exactly 3

    def test_turning_on_the_spot_moves_only_facing(self):
        before, after = self._save("PORSAVE8").party, self._save("PORSAVE9").party
        assert (before.x, before.y) == (after.x, after.y)
        assert before.facing_name == "west" and after.facing_name == "north"

    def test_previous_square_is_one_step_back(self):
        from por.savegame import FACING_STEP
        for name in ("PORSAVE7", "PORSAVE8"):
            p = self._save(name).party
            dx, dy = FACING_STEP[p.facing]
            assert p.previous == (p.x - dx, p.y - dy)

    def test_the_clock_only_ever_rises(self):
        names = ["PORSAVE4", "PORSAVE5", "PORSAVE6", "PORSAVE7", "PORSAVE8", "PORSAVE9"]
        clocks = [self._save(n).party.clock for n in names]
        assert clocks == sorted(clocks) and clocks[0] < clocks[-1]

    def test_writes_touch_only_their_own_byte(self):
        sg = self._save("PORSAVE9")
        before = sg.to_bytes()
        sg.party.facing = "south"
        after = sg.to_bytes()
        diff = [i for i in range(len(before)) if before[i] != after[i]]
        assert diff == [0x49C2 - 0x4900]
        assert sg.party.facing_name == "south"

    def test_a_bad_facing_is_refused(self):
        sg = self._save("PORSAVE9")
        with pytest.raises(SaveGameError):
            sg.party.facing = "widdershins"


# --- the area the party is on ------------------------------------------------

def _area_of(name: str):
    import pathlib

    import pytest

    from por.d64 import D64
    from por.savegame import SaveGame0

    path = pathlib.Path(f"/home/donald/c64/Pool of Radiance Disks/{name}.D64")
    if not path.exists():
        pytest.skip(f"needs {name}.D64")
    return SaveGame0.from_prg(D64.open(str(path)).read_file(b"SAVEDGAME0"))


def test_the_boundary_pair_settles_the_area_byte():
    """One step apart across the New Phlan / slums doorway.

    PORSAVE12 stands on the west edge of New Phlan at (0,4); PORSAVE13 on the
    east edge of the slums at (15,4), the same row. $4BC2 goes $00 -> $14, and
    GEO14 is the file the wall-matching independently identified as the Slums at
    the highest score in that whole matrix.
    """
    phlan, slums = _area_of("PORSAVE12"), _area_of("PORSAVE13")
    assert (phlan.area, phlan.area_file) == (0x00, "GEO00")
    assert (slums.area, slums.area_file) == (0x14, "GEO14")
    assert (phlan.party.x, phlan.party.y) == (0, 4)
    assert (slums.party.x, slums.party.y) == (15, 4)


def test_the_older_saves_are_all_new_phlan():
    """Why the scan that once looked for this field found nothing: it compared
    these against each other, and every one of them is in the same place."""
    for name in ("PORSAVE", "PORSAVE2", "PORSAVE4", "PORSAVE5", "PORSAVE7",
                 "PORSAVE9", "PORSAVE11"):
        sg = _area_of(name)
        assert sg.area == 0x00, name


def test_a_foreign_save_reports_a_different_area():
    """npc_party.d64 is somebody else's playthrough at levels 4-8. It reads 13 --
    a fully roofed map, which is where such a party would be."""
    import pathlib

    import pytest

    from por.d64 import D64
    from por.savegame import SaveGame0

    path = pathlib.Path("/home/donald/Downloads/npc_party.d64")
    if not path.exists():
        pytest.skip("needs npc_party.d64")
    sg = SaveGame0.from_prg(D64.open(str(path)).read_file(b"SAVEDGAME0"))
    assert sg.area == 0x0D
    assert sg.area_file == "GEO0D"


def test_the_dirty_bit_is_masked_off():
    """Bit 7 is the loader's "reload me" marker, not part of the number."""
    from por.savegame import AREA, LOADED_DIRTY, SAVE0_LOAD_ADDRESS, SaveGame0

    payload = bytearray(0x1C00)
    payload[AREA - SAVE0_LOAD_ADDRESS] = 0x14 | LOADED_DIRTY
    assert SaveGame0.from_bytes(bytes(payload)).area == 0x14
