"""`por.amiga` against the offsets the character sheet actually drew.

Two probe shapes did the work and both are rebuilt here. The **ramp** -- a
`.pc` whose byte at every offset is that offset -- makes a number the sheet
prints name where it came from, and found the numeric fields. The **plausible**
payload puts a chosen legal value in a chosen byte, which is the only way to
find an enum: a wrong index draws unrelated game text rather than a number.
`docs/124-amiga-port.md` records the runs and the screenshots.

A second set of tests reads the player's own `Save/*.pc` files when
`$POD_SAVES` names a directory holding them, and skips otherwise. No game
data lives in this repository.
"""

from __future__ import annotations

import os
import pathlib

import pytest

from por import amiga
from por.amiga import (
    ABILITIES,
    ALIGNMENTS,
    ARMOUR_CLASS,
    CLASS_LEVEL_COUNT,
    CLASSES,
    COMBAT_BIAS,
    NAME,
    RACES,
    RECORD_LENGTH,
    PodCharacter,
    PodWriter,
)

RECORD = 582            # the C64 export PoD accepts, load address included


def ramp(name: str = "PROBE", size: int = RECORD) -> bytes:
    """The probe payload: every byte holds its own offset, name at 0x060."""
    data = bytearray(i & 0xFF for i in range(size))
    data[NAME:NAME + 15] = name.encode("ascii")[:15].ljust(15, b"\0")
    data[NAME + 15] = 0
    return bytes(data)


def test_the_name_is_fifteen_characters_nul_terminated():
    assert PodCharacter.from_bytes(ramp("BASELINE")).name == "BASELINE"


def test_a_short_buffer_is_refused_rather_than_read_past():
    with pytest.raises(ValueError):
        PodCharacter.from_bytes(bytes(ARMOUR_CLASS))


def test_the_abilities_are_the_second_byte_of_six_pairs():
    """`INT 40  WIS 2` came off a record whose 0x073 was 40 and 0x075 was 2."""
    got = PodCharacter.from_bytes(ramp()).abilities
    assert got == [ABILITIES + 1 + 2 * i for i in range(6)]


def test_hit_points_maximum_is_one_byte_at_0x081():
    """Probe R2 ramped 0x07E-0x0A2 and the sheet said `HIT POINTS 0/129`."""
    assert PodCharacter.from_bytes(ramp()).hit_points_max == 0x81


def test_movement_is_one_byte_at_0x088():
    """Same probe: `MOVEMENT 136`."""
    assert PodCharacter.from_bytes(ramp()).movement == 0x88


def test_seven_class_levels_run_from_0x09d():
    """A written record with 1..7 there drew `LEVEL 1/2/3/4/5/6/7`.

    The array is seven wide, not six: the seventh slot is the thief's, and it
    is where `?T.pc` -- a 16th-level thief -- keeps its only level.
    """
    assert PodCharacter.from_bytes(ramp()).class_levels == [
        0x9D + i for i in range(CLASS_LEVEL_COUNT)]


def test_the_damage_triple_is_three_pairs_two_apart():
    """Probe R3 ramped 0x0A3-0x0B5 and the sheet said `173D175-79`."""
    assert PodCharacter.from_bytes(ramp()).damage == (0xAD, 0xAF, 0xB1)


def test_armour_class_carries_the_family_60_minus_value_bias():
    """Same probe: `ARMOR CLASS -119`, and 60 - 0xB3 is -119."""
    assert PodCharacter.from_bytes(ramp()).armour_class == COMBAT_BIAS - 0xB3


def test_experience_is_a_big_endian_longword_at_0x044():
    """Probe R5 ramped 0x030-0x05F and the sheet said `EXPERIENCE 1145390663`."""
    assert PodCharacter.from_bytes(ramp()).experience == 0x44454647


def test_the_three_money_fields_are_big_endian_words():
    """Same probe: `PLATINUM 19533  GEMS 20047  JEWELRY 20561`."""
    pc = PodCharacter.from_bytes(ramp())
    assert (pc.platinum, pc.gems, pc.jewelry) == (0x4C4D, 0x4E4F, 0x5051)


def test_age_is_a_big_endian_word_at_0x052():
    """Same probe: `21075 YEARS`. Ramping 0x054-0x05F left it at 0."""
    assert PodCharacter.from_bytes(ramp()).age == 0x5253


def test_current_hit_points_are_a_big_endian_word_at_0x190():
    """A written record with 55 there and 77 at 0x081 drew `HIT POINTS 55/77`."""
    pc = PodCharacter.from_bytes(PodWriter(
        name="HP", hit_points_max=77, hit_points_current=55).to_bytes())
    assert (pc.hit_points_current, pc.hit_points_max) == (55, 77)


# -- the four enums, each of which a probe put on screen ------------------

def test_the_four_enums_read_back_the_words_the_sheet_drew():
    """One probe wrote 1/6/1/8 and drew `FEMALE`, `HALF-ELF`, `THIEF`,
    `CHAOTIC EVIL`; a second wrote 2/2/0/0 and drew `MALE`, `DWARF`,
    `FIGHTER`, `LAWFUL GOOD`."""
    for race, klass, sex, align, words in (
            (1, 6, 1, 8, ("HALF-ELF", "THIEF", "FEMALE", "CHAOTIC EVIL")),
            (2, 2, 0, 0, ("DWARF", "FIGHTER", "MALE", "LAWFUL GOOD"))):
        pc = PodCharacter.from_bytes(PodWriter(
            name="ENUM", race=race, character_class=klass, sex=sex,
            alignment=align).to_bytes())
        assert (pc.race_name, pc.class_name, pc.sex_name,
                pc.alignment_name) == words


def test_alignment_is_law_times_three_plus_morality():
    assert ALIGNMENTS[0] == "LAWFUL GOOD"
    assert ALIGNMENTS[8] == "CHAOTIC EVIL"
    assert len(ALIGNMENTS) == 9


# -- the writer -----------------------------------------------------------

def written() -> PodWriter:
    """The record FS-UAE accepted: it drew every field back correctly."""
    return PodWriter(
        name="WRITTEN", race=1, character_class=6, sex=1, alignment=8,
        age=33, experience=10000, platinum=200, gems=11, jewelry=22,
        abilities=(18, 17, 16, 15, 14, 13), hit_points_max=77,
        hit_points_current=55, movement=12, class_levels=(0,) * 6 + (7,),
        damage=(1, 6, 2), armour_class=10)


def test_the_writer_emits_the_length_of_the_shortest_genuine_record():
    assert len(written().to_bytes()) == RECORD_LENGTH == 484


def test_the_writer_round_trips_through_the_reader():
    pc = PodCharacter.from_bytes(written().to_bytes())
    assert pc.name == "WRITTEN"
    assert (pc.race_name, pc.class_name, pc.sex_name, pc.alignment_name) == (
        "HALF-ELF", "THIEF", "FEMALE", "CHAOTIC EVIL")
    assert (pc.age, pc.experience) == (33, 10000)
    assert (pc.platinum, pc.gems, pc.jewelry) == (200, 11, 22)
    assert pc.abilities == [18, 17, 16, 15, 14, 13]
    assert (pc.hit_points_current, pc.hit_points_max) == (55, 77)
    assert pc.class_levels == [0, 0, 0, 0, 0, 0, 7]
    assert pc.damage == (1, 6, 2)
    assert pc.armour_class == 10


def test_the_writer_leaves_the_heap_pointers_and_the_item_region_zero():
    """Both are don't-care on load, and zero is what the accepted payloads had."""
    raw = written().to_bytes()
    assert raw[0x00:0x44] == bytes(0x44)
    assert raw[0x0B6:0x190] == bytes(0x190 - 0x0B6)


def test_every_non_zero_byte_the_writer_emits_is_credited_to_a_field():
    """No 'template' category: a byte is a field the sheet showed us, or zero."""
    w = written()
    raw = w.to_bytes()
    credited = w.provenance()
    assert all(o in credited for o, b in enumerate(raw) if b)


def test_the_writer_refuses_an_index_no_table_has():
    for kwargs in ({"race": len(RACES)}, {"character_class": len(CLASSES)},
                   {"sex": 2}, {"alignment": 9}):
        with pytest.raises(ValueError):
            PodWriter(name="BAD", **kwargs).to_bytes()


# -- the player's own files, when they have them -------------------------

def pc_files() -> list[pathlib.Path]:
    where = os.environ.get("POD_SAVES")
    if not where:
        return []
    root = pathlib.Path(where)
    return sorted(p for p in root.rglob("*.pc") if p.is_file())


def real_records() -> list[pathlib.Path]:
    found = pc_files()
    if not found:
        pytest.skip("no Pools of Darkness .pc files; set $POD_SAVES")
    return found


def test_every_real_record_has_a_printable_name():
    for path in real_records():
        pc = PodCharacter.from_bytes(path.read_bytes())
        assert pc.name, path
        assert pc.name.isprintable(), (path, pc.name)


def test_every_real_record_decodes_to_legal_ability_scores():
    """PoD runs to 25 with magic; nothing legal is 0 or above 25."""
    for path in real_records():
        pc = PodCharacter.from_bytes(path.read_bytes())
        assert all(1 <= score <= 25 for score in pc.abilities), (path,
                                                                 pc.abilities)


def test_every_real_record_has_legal_class_levels():
    """One non-zero slot for a single-classed character, three for a triple.

    `T.pc` is somebody's abandoned scratch character and the picker draws its
    name as `?T`; its one level is in the thief slot, which is how the seventh
    slot was found.
    """
    for path in real_records():
        pc = PodCharacter.from_bytes(path.read_bytes())
        assert all(0 <= level <= 60 for level in pc.class_levels), path
        assert sum(1 for level in pc.class_levels if level) <= 3, path


def test_every_real_record_reads_the_same_unequipped_defaults():
    """Armour class 10 and 1d2 damage on all twelve: these are *base* values.
    The sheet's numbers are derived -- a written record with base AC 10 and a
    dexterity of 15 drew `ARMOR CLASS 9`, and base damage 1d6+2 with a
    strength of 18 drew `1D6+4`."""
    for path in real_records():
        pc = PodCharacter.from_bytes(path.read_bytes())
        assert pc.armour_class == 10, path
        assert pc.damage == (1, 2, 0), path


def test_every_real_record_names_a_race_a_class_and_an_alignment():
    for path in real_records():
        pc = PodCharacter.from_bytes(path.read_bytes())
        assert pc.race < len(RACES), (path, pc.race)
        assert pc.character_class < len(CLASSES), (path, pc.character_class)
        assert pc.alignment < len(ALIGNMENTS), (path, pc.alignment)
        assert pc.sex in (0, 1), (path, pc.sex)


def test_a_single_classed_record_keeps_its_level_in_its_class_slot():
    """The seven level slots are indexed by the single-class code, and that is
    how they were identified: every single-classed specimen on disk 3 puts its
    one level in the slot its class code names."""
    for path in real_records():
        pc = PodCharacter.from_bytes(path.read_bytes())
        if pc.character_class >= CLASS_LEVEL_COUNT:
            continue                       # multi-classed: several slots
        filled = [i for i, lv in enumerate(pc.class_levels) if lv]
        assert filled in ([], [pc.character_class]), (path, filled)


def test_a_real_record_agrees_with_what_the_game_displayed():
    """TROND was added to the party in FS-UAE and the roster said `HP 138`."""
    trond = [p for p in real_records() if p.stem.endswith("TROND")]
    if not trond:
        pytest.skip("no TROND.pc among the .pc files")
    assert PodCharacter.from_bytes(trond[0].read_bytes()).hit_points_max == 138


def test_the_level_byte_is_the_highest_class_level_not_their_sum():
    """`TRIPEL TURBO` is 6/6/12 and reads 12 at 0x089, not 24."""
    for path in real_records():
        pc = PodCharacter.from_bytes(path.read_bytes())
        assert pc.level == max(pc.class_levels), (path, pc.level)


def test_a_real_record_carries_the_class_bit_the_converter_writes():
    """1 magic-user, 2 cleric, 4 thief, 8 fighter -- the C64's own numbering
    for the four base classes -- but **64 for the paladin and the ranger
    alike**, where the C64 gives them 0x40 and 0x80 separately."""
    from por.amiga import CLASS_BIT, CLASS_LEVEL_SLOT
    by_pod_name = {CLASS_LEVEL_SLOT[c64]: bit for c64, bit in CLASS_BIT.items()}
    for path in real_records():
        pc = PodCharacter.from_bytes(path.read_bytes())
        if pc.character_class >= CLASS_LEVEL_COUNT:
            continue
        want = by_pod_name.get(CLASSES[pc.character_class])
        if want is None:
            continue                      # druid: no C64 class to come from
        assert pc.class_bits == want, (path, pc.class_name, pc.class_bits)


def test_the_disk_names_its_files_the_way_the_converter_would():
    """`MAGIC JHONSON` is `MAGICJHO.pc`; `TRIPEL TURBO` is `TRIPELTU.pc`."""
    from por.amiga import pc_filename
    for path in real_records():
        pc = PodCharacter.from_bytes(path.read_bytes())
        assert pc_filename(pc.name).lower() == path.name.split("_")[-1].lower()


# ---------------------------------------------------------------------------
# C64 -> Amiga, through `yaml_io.entry_for`'s neutral form
# ---------------------------------------------------------------------------
FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def neutral_party() -> list[dict]:
    """The player's own saved game as the dictionaries the converter eats.

    Straight through `yaml_io.entry_for`, which is the point: the converter
    reads named fields and never a `CharacterRecord`, so it needs to know
    neither the C64 record layout nor which of the six titles wrote it.
    """
    from por.icons import icon_for_slot
    from por.items import items_for_slot
    from por.savegame import SaveGame0, SaveGame1
    from por.yaml_io import entry_for

    sg0 = SaveGame0((FIXTURES / "savedgame0.bin").read_bytes()[2:])
    sg1 = SaveGame1((FIXTURES / "savedgame1.bin").read_bytes()[2:])
    payload = sg0.to_bytes()
    return [entry_for(slot.record, slot.index,
                      items=items_for_slot(payload, slot.index),
                      icon=icon_for_slot(payload, slot.index),
                      block=sg1.roster(slot.index))
            for slot in sg0.characters]


def test_every_neutral_form_field_has_a_disposition():
    """A field `entry_for` produces and `field_disposition` does not name
    would be a field silently dropped, which is the one thing the conversion
    promises not to do."""
    produced = {k for entry in neutral_party() for k in entry
                if not k.startswith("_")}
    declared = set(amiga.field_disposition())
    assert produced - declared == set(), "no disposition for these"
    assert declared - produced == set(), "a disposition for a field that is "\
                                         "not in the neutral form"


def test_a_converted_character_reads_back_as_the_c64_one():
    for entry in neutral_party():
        record, _ = amiga.to_pc(entry)
        pc = PodCharacter.from_bytes(record)
        assert pc.name == entry["name"][:15]
        assert pc.sex_name == entry["sex"].upper()
        assert pc.alignment_name.lower().replace("neutral neutral",
                                                 "true neutral") \
            == entry["alignment"]
        assert pc.abilities == [entry[k] for k in amiga.ABILITY_KEYS]
        assert pc.experience == entry["experience"]
        assert pc.age == entry["age"]
        assert pc.platinum == entry["platinum"]
        assert pc.hit_points_max == entry["hp_max"]
        assert pc.hit_points_current == entry["combat"]["hp_current"]
        assert pc.saving_throws == [entry[k] for k in amiga.SAVE_KEYS]
        assert pc.thief_skills == [entry[k] for k in amiga.THIEF_KEYS]


def test_the_conversion_credits_every_non_zero_byte():
    """`docs/124-amiga-port.md` phase 6's acceptance: no "template" category.
    A byte of the output is a field a probe put on the character sheet, or it
    is zero."""
    for entry in neutral_party():
        record, rep = amiga.to_pc(entry)
        assert len(record) == RECORD_LENGTH
        assert rep.unaccounted(record) == []


def test_the_class_level_lands_in_the_slot_pods_own_code_names():
    for entry in neutral_party():
        record, _ = amiga.to_pc(entry)
        pc = PodCharacter.from_bytes(record)
        for name, level in entry["levels"].items():
            slot = CLASSES.index(amiga.CLASS_LEVEL_SLOT[name])
            assert pc.class_levels[slot] == level, (name, pc.class_levels)


def sample_entry(**over) -> dict:
    """One neutral-form character, built rather than read.

    Not a slice of any game file: every value here is chosen, which is what
    lets the edge cases below be tested where no disk is present.
    """
    entry = {
        "slot": 0, "name": "AELFRIC", "sex": "female", "race": "half-elf",
        "age": 33, "alignment": "chaotic evil",
        "strength": 18, "exceptional_strength": 0, "intelligence": 17,
        "wisdom": 16, "dexterity": 15, "constitution": 14, "charisma": 13,
        "hp_max": 55, "hp_rolled": 40,
        "jewelry": 22, "gems": 11, "platinum": 200, "gold": 0, "electrum": 0,
        "silver": 0, "copper": 0,
        "movement": 12, "infravision": 0,
        "save_paralysis": 13, "save_petrification": 14, "save_wands": 12,
        "save_breath": 16, "save_spell": 15,
        "thief_pick_pockets": 60, "thief_open_locks": 45,
        "thief_find_traps": 40, "thief_move_silently": 50,
        "thief_hide_in_shadows": 43, "thief_hear_noise": 20,
        "thief_climb_walls": 92, "thief_read_languages": 20,
        "portrait_head": 3, "portrait_body": 4,
        "classes": ["thief"], "class_code": 6, "levels": {"thief": 7},
        "experience": 10000, "items": [],
        "icon": {"shape": "00" * 18, "colours": "00" * 18},
        "level": 7, "npc": False, "spells": [], "spells_known": [],
    }
    entry.update(over)
    return entry


def test_the_probe_that_loaded_in_the_game_is_what_the_converter_emits():
    """P3 in `docs/124-amiga-port.md` sec 2.4: PoD drew `FEMALE 33 YEARS`,
    `CHAOTIC EVIL`, `HALF-ELF`, `THIEF`, `LEVEL 7`, `EXPERIENCE 10000`,
    `PLATINUM 200 GEMS 11 JEWELRY 22`, `MOVEMENT 12`."""
    record, _ = amiga.to_pc(sample_entry(combat={"hp_current": 55}))
    pc = PodCharacter.from_bytes(record)
    assert (pc.sex_name, pc.age) == ("FEMALE", 33)
    assert pc.alignment_name == "CHAOTIC EVIL"
    assert pc.race_name == "HALF-ELF"
    assert pc.class_name == "THIEF"
    assert pc.class_levels[CLASSES.index("THIEF")] == 7
    assert (pc.experience, pc.platinum, pc.gems, pc.jewelry) == (
        10000, 200, 11, 22)
    assert pc.movement == 12
    assert pc.hit_points_current == 55


def test_a_race_pools_of_darkness_lacks_is_substituted_and_said_out_loud():
    record, rep = amiga.to_pc(sample_entry(race="half-orc"))
    assert PodCharacter.from_bytes(record).race_name == "HUMAN"
    assert any("half-orc" in w for w in rep.warnings), rep.warnings


def test_a_knight_arrives_as_a_fighter_and_says_so():
    """The Knight of Solamnia is Krynn's and has no Realms slot."""
    record, rep = amiga.to_pc(sample_entry(
        classes=["knight"], levels={"knight": 9}, level=9))
    pc = PodCharacter.from_bytes(record)
    assert pc.class_name == "FIGHTER"
    assert pc.class_levels[CLASSES.index("FIGHTER")] == 9
    assert any("knight" in w for w in rep.warnings), rep.warnings


def test_the_lighter_coins_are_reported_rather_than_vanishing():
    """Only platinum, gems and jewelry have a located home in the `.pc`."""
    _, rep = amiga.to_pc(sample_entry(gold=900, silver=10, copper=7))
    assert any("917" in w for w in rep.warnings), rep.warnings


def test_hit_points_over_the_amiga_byte_are_clamped_and_reported():
    record, rep = amiga.to_pc(sample_entry(hp_max=300))
    assert PodCharacter.from_bytes(record).hit_points_max == 255
    assert any("300" in w for w in rep.warnings), rep.warnings


def test_a_class_pools_of_darkness_cannot_express_is_refused():
    """A combination with no code is refused rather than written as another
    one, which is `yaml_io.class_code_for`'s rule in the other direction."""
    with pytest.raises(amiga.ConversionError):
        amiga.to_pc(sample_entry(classes=["cleric", "thief", "fighter"],
                                 levels={"cleric": 3, "thief": 3,
                                         "fighter": 3}))


def test_the_items_and_the_portraits_are_named_as_losses():
    _, rep = amiga.to_pc(sample_entry())
    named = " ".join(rep.dropped)
    for what in ("items", "portrait_head", "portrait_body", "icon",
                 "spells", "copper"):
        assert what in named, what


def test_a_built_filename_is_uppercase_and_eight_characters():
    assert amiga.pc_filename("MAGIC JHONSON") == "MAGICJHO.pc"
    assert amiga.pc_filename("TRIPEL TURBO") == "TRIPELTU.pc"
    assert amiga.pc_filename("?T") == "T.pc"
