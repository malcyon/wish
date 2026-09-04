from __future__ import annotations

"""`goldbox.amiga` against the offsets the character sheet actually drew.

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


import functools
import pathlib
import tempfile

import pytest

from goldbox import amiga, dos_layout
from goldbox.amiga import (
    ABILITIES,
    ALIGNMENTS,
    AMIGA_POR_NAME_SIZE,
    AMIGA_POR_RECORD_SIZE,
    AMIGA_POR_UNPLACED,
    ARMOUR_CLASS,
    CLASS_LEVEL_COUNT,
    CLASSES,
    COMBAT_BIAS,
    NAME,
    RACES,
    RECORD_LENGTH,
    AmigaPorCharacter,
    AmigaRecordError,
    PodCharacter,
    PodWriter,
    amiga_por_offset,
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
    """`gamedisks.toml`'s `pod-saves` entry (#212) -- no default candidates:
    no exported Pools of Darkness `.pc` file exists on any machine yet."""
    from tools import gamedisks
    return sorted(p for root in gamedisks.candidates("pod-saves")
                 for p in root.rglob("*.pc") if p.is_file())


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
    from goldbox.amiga import CLASS_BIT, CLASS_LEVEL_SLOT
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
    from goldbox.amiga import pc_filename
    for path in real_records():
        pc = PodCharacter.from_bytes(path.read_bytes())
        assert pc_filename(pc.name).lower() == path.name.split("_")[-1].lower()


# ---------------------------------------------------------------------------
# Anything -> Amiga, over `goldbox/neutral.py`'s record
# ---------------------------------------------------------------------------
FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def neutral_party() -> list:
    """The player's own saved game as the neutral characters the writer eats.

    Straight through `goldbox.c64_codec.read`, which is the point: the Amiga
    writer reads neutral field names and never a `CharacterRecord`, so it
    needs to know neither the C64 record layout nor which of the six titles
    wrote it -- and it never reaches for another codec to find out.
    """
    from goldbox.c64_codec import read
    from goldbox.items import items_for_slot
    from goldbox.savegame import SaveGame0, SaveGame1

    sg0 = SaveGame0((FIXTURES / "savedgame0.bin").read_bytes()[2:])
    sg1 = SaveGame1((FIXTURES / "savedgame1.bin").read_bytes()[2:])
    payload = sg0.to_bytes()
    return [read(slot.record, roster=sg1.roster(slot.index),
                 inventory=[i.raw for i in items_for_slot(payload,
                                                          slot.index)])
            for slot in sg0.characters]


def test_every_neutral_field_has_a_disposition():
    """A field `goldbox/neutral.py` declares and `field_disposition` does not name
    would be a field silently dropped, which is the one thing the conversion
    promises not to do."""
    from goldbox import neutral

    unaccounted, unknown = neutral.undeclared(neutral.FIELDS,
                                              amiga.field_disposition())
    assert unaccounted == set(), "no disposition for these"
    assert unknown == set(), "a disposition for a field the vocabulary lacks"


def test_the_c64_reader_supplies_what_the_amiga_writer_takes():
    """The other half: a neutral name the writer takes and the C64 reader
    never sets is a value that would arrive as nothing on every conversion
    off a C64 save."""
    taken = {n for n, _ in amiga.DIRECT} | {n for n, _ in amiga.TRANSFORMED}
    for char in neutral_party():
        assert taken - set(char.keys()) == set()


def test_a_converted_character_reads_back_as_the_neutral_one():
    for char in neutral_party():
        record, _ = amiga.to_pc(char)
        pc = PodCharacter.from_bytes(record)
        assert pc.name == char.get("name")[:15]
        assert pc.sex == char.get("sex")
        assert pc.alignment == char.get("alignment")
        assert pc.abilities == [char.get(k) for k in amiga.ABILITY_KEYS]
        assert pc.experience == char.get("experience")
        assert pc.age == char.get("age")
        assert pc.platinum == char.get("platinum")
        assert pc.hit_points_max == char.get("hp_max")
        assert pc.hit_points_current == char.get("hp_current")
        assert pc.saving_throws == [char.get(k) for k in amiga.SAVE_KEYS]
        assert pc.thief_skills == [char.get(k) for k in amiga.THIEF_KEYS]


def test_the_conversion_credits_every_non_zero_byte():
    """`docs/124-amiga-port.md` phase 6's acceptance: no "template" category.
    A byte of the output is a field a probe put on the character sheet, or it
    is zero."""
    for char in neutral_party():
        record, rep = amiga.to_pc(char)
        assert len(record) == RECORD_LENGTH
        assert rep.unaccounted(record) == []


def test_the_class_level_lands_in_the_slot_pods_own_code_names():
    from goldbox.games import class_table

    for char in neutral_party():
        record, _ = amiga.to_pc(char)
        pc = PodCharacter.from_bytes(record)
        bits = char.get("class_bits")
        for bit, name in class_table(char.game):
            if not bits & bit:
                continue
            slot = CLASSES.index(amiga.CLASS_LEVEL_SLOT[name])
            assert pc.class_levels[slot] == char.get("levels")[name], (
                name, pc.class_levels)


def sample(**over):
    """One neutral character, built rather than read.

    Not a slice of any game file: every value here is chosen, which is what
    lets the edge cases below be tested where no disk is present.
    """
    from goldbox.neutral import NeutralCharacter

    values = {
        "name": "AELFRIC", "sex": 1, "race": 4, "age": 33, "alignment": 8,
        "strength": 18, "exceptional_strength": 0, "intelligence": 17,
        "wisdom": 16, "dexterity": 15, "constitution": 14, "charisma": 13,
        "hp_max": 55, "hp_rolled": 40, "hp_current": 55,
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
        "class_bits": 4, "char_class": 6,
        "levels": {"thief": 7, "fighter": 0, "cleric": 0, "magic-user": 0,
                   "knight": 0, "paladin": 0, "ranger": 0},
        "experience": 10000, "inventory": [],
        "level": 7, "npc": False, "spells_memorised": [], "spells_known": [],
    }
    values.update(over)
    char = NeutralCharacter("C64")
    for name, value in values.items():
        char.set(name, value, f"a built specimen's {name}")
    return char


def test_the_probe_that_loaded_in_the_game_is_what_the_converter_emits():
    """P3 in `docs/124-amiga-port.md` sec 2.4: PoD drew `FEMALE 33 YEARS`,
    `CHAOTIC EVIL`, `HALF-ELF`, `THIEF`, `LEVEL 7`, `EXPERIENCE 10000`,
    `PLATINUM 200 GEMS 11 JEWELRY 22`, `MOVEMENT 12`."""
    record, _ = amiga.to_pc(sample())
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
    record, rep = amiga.to_pc(sample(race=6))       # half-orc
    assert PodCharacter.from_bytes(record).race_name == "HUMAN"
    assert any("half-orc" in w for w in rep.warnings), rep.warnings


def test_a_knight_arrives_as_a_fighter_and_says_so():
    """The Knight of Solamnia is Krynn's and has no Realms slot."""
    from goldbox.games import by_key

    levels = {"knight": 9, "thief": 0, "fighter": 0, "cleric": 0,
              "magic-user": 0, "paladin": 0, "ranger": 0}
    char = sample(class_bits=0x10, levels=levels, level=9)
    char.game = by_key("champions-of-krynn")
    char.set("race", 5, "a built specimen's race")       # human on Krynn
    record, rep = amiga.to_pc(char)
    pc = PodCharacter.from_bytes(record)
    assert pc.class_name == "FIGHTER"
    assert pc.class_levels[CLASSES.index("FIGHTER")] == 9
    assert any("knight" in w for w in rep.warnings), rep.warnings


def test_the_lighter_coins_are_reported_rather_than_vanishing():
    """Only platinum, gems and jewelry have a located home in the `.pc`."""
    _, rep = amiga.to_pc(sample(gold=900, silver=10, copper=7))
    assert any("917" in w for w in rep.warnings), rep.warnings


def test_hit_points_over_the_amiga_byte_are_clamped_and_reported():
    record, rep = amiga.to_pc(sample(hp_max=300))
    assert PodCharacter.from_bytes(record).hit_points_max == 255
    assert any("300" in w for w in rep.warnings), rep.warnings


def test_a_class_pools_of_darkness_cannot_express_is_refused():
    """A combination with no code is refused rather than written as another
    one, which is `yaml_io.class_code_for`'s rule in the other direction."""
    with pytest.raises(amiga.ConversionError):
        amiga.to_pc(sample(class_bits=2 | 4 | 8,
                           levels={"cleric": 3, "thief": 3, "fighter": 3,
                                   "magic-user": 0, "knight": 0,
                                   "paladin": 0, "ranger": 0}))


def test_a_field_graded_below_the_floor_is_refused_rather_than_guessed():
    """`neutral.Writer.use` is the whole of the refusal, and it is shared:
    a value the reader will not stand behind is reported, not written."""
    from goldbox.layout import Confidence

    char = sample()
    char.set("age", 99, "a value nobody measured", Confidence.UNKNOWN)
    record, rep = amiga.to_pc(char)
    assert PodCharacter.from_bytes(record).age == 0
    assert any("age" in d and "UNKNOWN" in d for d in rep.dropped), rep.dropped


def test_the_items_and_the_portraits_are_named_as_losses():
    _, rep = amiga.to_pc(sample())
    named = " ".join(rep.dropped)
    for what in ("inventory", "portrait_head", "portrait_body",
                 "spells_memorised", "copper"):
        assert what in named, what


def test_a_built_filename_is_uppercase_and_eight_characters():
    assert amiga.pc_filename("MAGIC JHONSON") == "MAGICJHO.pc"
    assert amiga.pc_filename("TRIPEL TURBO") == "TRIPELTU.pc"
    assert amiga.pc_filename("?T") == "T.pc"


def test_a_repeated_stem_gets_a_trailing_digit_rather_than_overwriting():
    """LADY KATHERINE and LADY KATHRYN both give `LADYKATH.pc` (#79); the
    second one claimed keeps the length `pc_filename` promises."""
    from goldbox.amiga import _unique_pc_filename

    used: set[str] = set()
    first = _unique_pc_filename(amiga.pc_filename("LADY KATHERINE"), used)
    used.add(first)
    second = _unique_pc_filename(amiga.pc_filename("LADY KATHRYN"), used)

    assert first == "LADYKATH.pc"
    assert second == "LADYKAT2.pc"
    assert len(second) == len(".pc") + amiga.FILENAME_LENGTH


def test_a_name_already_used_is_left_alone():
    used = {"LADYKATH.pc"}
    assert amiga._unique_pc_filename("BJORK.pc", used) == "BJORK.pc"


def _six_identical_names_disk(tmp_path) -> pathlib.Path:
    """A save disk with six occupied slots, every one the same 20-character
    name and otherwise convertible (human fighter) -- the extreme case of
    #79, where a two-way collision becomes a six-way one.

    Built from the format like `gamedata.synthetic_party`, but with a single
    class Pools of Darkness has a code for: `synthetic_party`'s all-four-class
    combination has none, which `to_pc` refuses.
    """
    import gamedata

    from goldbox import games
    from goldbox.d64 import attach_load_address
    from goldbox.encoding import COMBAT_BIAS
    from goldbox.layout import NAME_SIZE
    from goldbox.record import CharacterRecord
    from goldbox.savegame import (
        HEADER_SIZE,
        ROSTER_ARMOUR_CLASS,
        ROSTER_HP_CURRENT,
        ROSTER_MOVEMENT,
        ROSTER_SLOT_INDEX,
        ROSTER_STRIDE,
        ROSTER_THAC0,
        SLOT_STRIDE,
    )

    game = games.POOL_OF_RADIANCE
    record = CharacterRecord.blank()
    record.set("name", "W" * NAME_SIZE)
    for ability in ("strength", "intelligence", "wisdom", "dexterity",
                    "constitution", "charisma"):
        record.set(ability, 15)
    record.set("race", 7)          # human, RACES_FORGOTTEN_REALMS
    record.set("class_bits", 8)    # fighter alone -- a code PoD has
    record.set("hp_max", 20)
    head = record.to_bytes()[:SLOT_STRIDE]

    payload = bytearray(game.save_size)
    roster = bytearray(game.roster_size)
    for i in range(gamedata.PARTY_SLOTS):
        payload[HEADER_SIZE + i * SLOT_STRIDE:
                HEADER_SIZE + (i + 1) * SLOT_STRIDE] = head
        at = i * ROSTER_STRIDE
        roster[at + ROSTER_SLOT_INDEX] = i
        roster[at + ROSTER_THAC0] = COMBAT_BIAS - 10
        roster[at + ROSTER_ARMOUR_CLASS] = COMBAT_BIAS - 10
        roster[at + ROSTER_HP_CURRENT] = 20
        roster[at + ROSTER_MOVEMENT] = 12
    disk = gamedata._disk_with([
        (game.save_file, attach_load_address(game.save_load_address,
                                             bytes(payload))),
        (game.roster_file, attach_load_address(game.roster_load_address,
                                               bytes(roster))),
    ])
    out = tmp_path / "SIX_IDENTICAL.D64"
    out.write_bytes(disk)
    return out


def test_export_party_disambiguates_a_six_way_collision(tmp_path):
    """Before the fix, `export_party` returned six `(path, Report)` pairs
    that all pointed at the one file the last write left behind; only one
    `.pc` ever reached disk."""
    from goldbox.amiga import export_party

    save = _six_identical_names_disk(tmp_path)
    out_dir = tmp_path / "out"
    written = export_party(save, out_dir)

    assert len(written) == 6
    names = [path.name for path, _rep in written]
    assert len(set(names)) == 6, names
    assert sorted(out_dir.glob("*.pc")) == sorted(out_dir / n for n in names)
    assert names[0] == "WWWWWWWW.pc"
    assert names[1:] == [f"WWWWWWW{d}.pc" for d in "23456"]

    # every file actually exists and holds a real record, not a name clash
    # papered over with an empty write
    for path, _rep in written:
        assert len(path.read_bytes()) == RECORD_LENGTH

    # the rename is said, not done in silence -- first character keeps its
    # name outright and has nothing to report; the rest do
    assert written[0][1].warnings == [] or not any(
        "already used" in w for w in written[0][1].warnings)
    for path, rep in written[1:]:
        assert any("already used" in w for w in rep.warnings), rep.warnings


# -- Amiga Pool of Radiance: the 288-byte record (#27) ----------------------



def test_the_shift_map_places_the_three_regions_at_their_measured_offsets():
    """The whole claim in six numbers, checked at the seams rather than the
    middle: nothing moves below the pad, the effect pointer moves one, and
    everything from the money block moves two."""
    assert amiga_por_offset(0x000) == 0x000
    assert amiga_por_offset(0x07E) == 0x07E      # last thief skill
    assert amiga_por_offset(0x07F) == 0x080      # effect chain, past the pad
    assert amiga_por_offset(0x088) == 0x08A      # copper
    assert amiga_por_offset(0x11C) == 0x11E      # movement_current, DOS's last


def test_the_unplaced_window_refuses_rather_than_guessing():
    """The second insertion is somewhere in DOS 0x083-0x087 and 12 of the 14
    specimens are zero across it, so no offset there can be given. A map that
    answered anyway would be believed."""
    for dos_offset in AMIGA_POR_UNPLACED:
        with pytest.raises(AmigaRecordError):
            amiga_por_offset(dos_offset)


def test_the_record_size_is_the_dos_record_plus_three():
    """285 + one pad at 0x07F + one in the unplaced window + one trailing."""
    assert AMIGA_POR_RECORD_SIZE == dos_layout.RECORD_SIZE + 3


@pytest.mark.parametrize("length", [285, 287, 289, 428, 484])
def test_a_record_of_the_wrong_length_is_refused_by_name(length):
    with pytest.raises(AmigaRecordError):
        AmigaPorCharacter.from_bytes(bytes(length))


@functools.lru_cache(maxsize=1)
def _extracted_records() -> tuple[pathlib.Path, ...]:
    """The twenty specimens, pulled out of the Amiga disks themselves.

    They are not loose files on any machine: six live in the `save/` drawer of
    Pool of Radiance disk 1 and fourteen in the Curse of the Azure Bonds save
    disk.  They were once extracted into `work/`, which is gitignored and has
    been lost, so `$AMIGA_POR_SAVES` named nothing and thirty-one tests here
    skipped on the machine that holds every byte of the corpus -- the shape of
    #211.  `tools/amigasaves.py` finds them again from `gamedisks.toml`'s
    `amiga` entry, and this unpacks them into a directory that lives as long
    as the test process.
    """
    from tools import amigasaves, gamedisks
    if not gamedisks.candidates("amiga"):
        return ()
    tmp = tempfile.TemporaryDirectory(prefix="amiga-por-saves-")
    _KEEP.append(tmp)                       # deleted when the process exits
    return tuple(amigasaves.extract(pathlib.Path(tmp.name)))


#: Temporary directories held open for the life of the test process, so that
#: `_extracted_records`'s paths stay readable after it returns.
_KEEP: list[tempfile.TemporaryDirectory] = []


def amiga_por_records() -> list[pathlib.Path]:
    """`gamedisks.toml`'s `amiga-por-saves` entry (#212), or the disks.

    `$AMIGA_POR_SAVES` still wins, because a run that wants a hand-picked
    corpus -- one character, or a set nobody has shipped -- has to be able to
    say so.  With nothing set, the specimens come out of the game's own disk
    images instead of the tests skipping.
    """
    from tools import gamedisks
    where = gamedisks.candidates("amiga-por-saves")
    found = sorted(p for root in where for p in root.rglob("*")
                   if p.is_file() and p.suffix.lower() in (".cha", ".sav")
                   and p.stat().st_size == AMIGA_POR_RECORD_SIZE)
    if not found:
        found = list(_extracted_records())
    if not found:
        pytest.skip(
            "no Amiga Pool of Radiance records: set $AMIGA_POR_SAVES, or "
            "$AMIGA_DISKS at disks tools/amigasaves.py can read them out of")
    return found


def test_every_specimen_decodes_to_a_coherent_character():
    """The cross-checks that would fail on a wrong offset or byte order.

    Each is arithmetic between two fields rather than a restatement of one:
    the class bitmask has to decompose to the class byte, a level-1 character
    has to hold no experience, and every ability has to be in 3-18. A shift
    off by one puts a heap pointer in an ability and this fails.
    """
    for path in amiga_por_records():
        c = AmigaPorCharacter.from_bytes(path.read_bytes(), str(path))
        assert c.name and c.name.isprintable(), path
        # 19 is reachable: a racial adjustment takes a rolled 18 one past
        # the human cap, and the shipped party has a dwarf on CON 19 and an
        # elf on DEX 19. A ceiling of 18 here would have failed on them.
        assert all(3 <= a <= 19 for a in c.abilities), (path, c.abilities)
        assert c.get("movement") == 12, path
        assert 1 <= c.get("level") <= 9, path
        assert c.get("race") < len(dos_layout.RACE_NUMBERS), path
        if c.get("level") == 1:
            # Not "zero": the party shipped on disk 1 is level 1 with 17
            # experience apiece, having fought something. The invariant is
            # the level-2 threshold, and 1250 is the lowest of them (thief).
            # A byte-swapped read of 17 is 285212672 and fails this.
            assert c.experience < 1250, (path, c.experience)


def test_exceptional_strength_appears_only_on_an_eighteen_strength_fighter():
    """A cross-field identity AD&D guarantees, and a byte-order canary: the
    percentile roll is only made for a fighter with STR 18."""
    for path in amiga_por_records():
        c = AmigaPorCharacter.from_bytes(path.read_bytes(), str(path))
        if c.get("exceptional_strength"):
            assert c.abilities[0] == 18, path
            assert c.get("class_bits") & 0x08, path


def test_the_class_bitmask_decomposes_to_the_class_byte():
    for path in amiga_por_records():
        c = AmigaPorCharacter.from_bytes(path.read_bytes(), str(path))
        name = dos_layout.CLASS_NUMBERS[c.get("char_class")]
        bits = c.get("class_bits")
        wanted = {"mage": 1, "cleric": 2, "thief": 4, "fighter": 8}
        expected = sum(wanted[part] for part in name.split("/") if part in wanted)
        if expected:
            assert bits == expected, (path, name, bits)


def test_the_effect_pointer_is_set_exactly_when_a_spc_chain_exists():
    """Nonzero for the characters with effects and zero for the rest -- the
    field is a big-endian u32 where DOS keeps an offset word and a segment
    word, so a little-endian read gives a wild address here."""
    for path in amiga_por_records():
        c = AmigaPorCharacter.from_bytes(path.read_bytes(), str(path))
        if c.effect_chain:
            assert 0x100 < c.effect_chain < 0x1000000, (path, c.effect_chain)


#: What Amiga Pool of Radiance itself drew for the party shipped on disk 1,
#: read off the screen under WinUAE on 2026-08-26 (#27,
#: `work/amiga/p27/shots/m6.png` and `v1.png`). The roster gave AC and HP for
#: all six; GARWAN's sheet gave the rest. These are the instrument, and the
#: reader has to agree with them -- not with itself.
AMIGA_POR_ON_SCREEN = {
    "GARWAN":     {"armour_class": 1, "hp_max": 14},
    "STONEBEARD": {"armour_class": 2, "hp_max": 14},
    "GOLDLEAF":   {"armour_class": 3, "hp_max": 8},
    "LAURANN":    {"armour_class": 3, "hp_max": 10},
    "CONLY":      {"armour_class": 4, "hp_max": 8},
    "MELCAR":     {"armour_class": 7, "hp_max": 6},
}
GARWAN_ON_SCREEN = {
    "age": 18, "sex": 0, "alignment": 6, "level": 1, "hp_max": 14,
    "exceptional_strength": 100, "encumbrance": 543, "movement_current": 9,
}


def test_the_reader_agrees_with_what_the_game_drew_for_the_shipped_party():
    """Armour class off the roster, for as many of the six as are present.

    Armour class is stored biased -- `60 - value` -- so this fails both ways
    round: a reader that forgot the bias reports 59 where the game drew 1.
    """
    seen = 0
    for path in amiga_por_records():
        c = AmigaPorCharacter.from_bytes(path.read_bytes(), str(path))
        want = AMIGA_POR_ON_SCREEN.get(c.name)
        if want is None:
            continue
        seen += 1
        assert 60 - c.get("armour_class") == want["armour_class"], path
        assert c.get("hp_max") == want["hp_max"], path
    if not seen:
        pytest.skip("none of the shipped disk-1 party is in $AMIGA_POR_SAVES")


def test_garwans_sheet_matches_field_for_field():
    """The one character whose whole sheet was photographed.

    `movement_current` is 9 against a base movement of 12: the game draws the
    encumbered figure and the record stores both, which is why DOS's byte at
    `0x11C` is that field and not the class group a third-party note claims.
    """
    for path in amiga_por_records():
        c = AmigaPorCharacter.from_bytes(path.read_bytes(), str(path))
        if c.name != "GARWAN":
            continue
        for name, value in GARWAN_ON_SCREEN.items():
            assert c.get(name) == value, (name, c.get(name), value)
        assert c.abilities == [18, 9, 11, 16, 18, 16]
        assert c.experience == 17
        assert c.money["platinum"] == 8
        assert c.money["gold"] == 1
        assert c.money["silver"] == 24
        return
    pytest.skip("GARWAN is not in $AMIGA_POR_SAVES")


# ---------------------------------------------------------------------------
# The item file, the effect file, and the neutral bridge (#27)
# ---------------------------------------------------------------------------
def amiga_por_with_items() -> list[pathlib.Path]:
    """The specimens that have a `.itm` beside them.

    Six of the twenty: the party shipped on Amiga disk 1.  The fourteen
    staged on the Curse save disk carry no item file, so a run whose
    `$AMIGA_POR_SAVES` holds only those skips rather than passing vacuously.
    """
    found = [p for p in amiga_por_records()
             if p.with_suffix(".itm").exists()]
    if not found:
        pytest.skip("no .itm beside any record under $AMIGA_POR_SAVES")
    return found


def test_the_item_file_is_a_whole_number_of_sixty_five_byte_nodes():
    for path in amiga_por_with_items():
        size = path.with_suffix(".itm").stat().st_size
        assert size % amiga.AMIGA_POR_ITEM_SIZE == 0, (path, size)


def test_the_record_item_count_matches_the_item_file_length():
    """Two independent numbers: a byte in the record and a file's size.

    They agree 6 of 6 -- 3, 3, 3, 3, 3 and 2 against 195, 195, 195, 195, 195
    and 130 bytes.  A stride of 63 or 66 fails this, and so does a count read
    at the DOS offset instead of the shifted one.
    """
    for path in amiga_por_with_items():
        c = AmigaPorCharacter.from_bytes(path.read_bytes(), str(path))
        size = path.with_suffix(".itm").stat().st_size
        assert c.get("item_count") == size // amiga.AMIGA_POR_ITEM_SIZE, path


def test_the_encumbrance_identity_balances_for_every_specimen():
    """`money + sum(weight x quantity)` equals the record's own encumbrance.

    The strongest single check in this file, because it is arithmetic across
    three structures at once: the seven money words in the record, the
    65-byte stride of the item file, the item weight and quantity offsets,
    the big-endian byte order of both, and one derived word.  It balances
    for all six characters, and GARWAN's 543 is the number the game itself
    drew beside `MOVEMENT 9`.

    A shift map that puts weight at the DOS offset gives 0 for every item
    and this fails on the first character.
    """
    for path in amiga_por_with_items():
        c = amiga.read_amiga_por(path)
        total = sum(c.money.values())
        for it in c.items:
            total += it.get("weight") * (it.get("quantity") or 1)
        assert total == c.get("encumbrance"), (path, total, c.get("encumbrance"))


def test_the_item_chain_ends_null_and_ascends():
    """A `next` read little-endian gives a wild address and fails this."""
    for path in amiga_por_with_items():
        c = amiga.read_amiga_por(path)
        pointers = [it.next_node for it in c.items]
        assert pointers[-1] == 0, (path, pointers)
        for p in pointers[:-1]:
            assert 0x100 < p < 0x1000000, (path, pointers)
        assert pointers[:-1] == sorted(pointers[:-1]), (path, pointers)


#: What the game's own item table says these weigh and cost, which is also
#: what the AD&D Players Handbook says.  Nine distinct items over seventeen
#: nodes; the value is independently checkable against the price the item's
#: own cached display line carries.
AMIGA_POR_ITEMS = {
    36: ("Long Sword", 60, 15),
    57: ("Banded Mail", 350, 90),
    59: ("Shield", 100, 15),
    35: ("Broad Sword", 75, 10),
    50: ("Leather Armor", 150, 5),
    12: ("Flail", 150, 3),
    55: ("Chain Mail", 300, 75),
    33: ("Quarter Staff", 50, 1),
    9: ("Darts", 5, 1),
}


def test_every_item_weighs_and_costs_what_the_game_says_it_does():
    seen = set()
    for path in amiga_por_with_items():
        c = amiga.read_amiga_por(path)
        for it in c.items:
            kind = it.get("type_index")
            want = AMIGA_POR_ITEMS.get(kind)
            if want is None:
                continue
            seen.add(kind)
            name, weight, value = want
            assert it.get("weight") == weight, (path, name, it.get("weight"))
            assert it.get("value") == value, (path, name, it.get("value"))
    assert seen, "no known item type in the corpus"


def test_the_readied_flag_is_the_one_the_display_line_agrees_with():
    """The flag `#55` could not confirm on Curse, where everything was
    readied.  Here the darts are not: they read 0 and draw ` No `."""
    seen = 0
    for path in amiga_por_with_items():
        for it in amiga.read_amiga_por(path).items:
            line = it.display_line
            if line.startswith(" Yes"):
                assert it.get("readied") == 1, (path, line)
                seen += 1
            elif line.startswith(" No"):
                assert it.get("readied") == 0, (path, line)
                seen += 1
    assert seen, "no item in the corpus carries the ready column"


def test_an_item_of_the_wrong_length_is_refused_by_name():
    with pytest.raises(AmigaRecordError):
        amiga.AmigaPorItem.from_bytes(bytes(dos_layout.ITEM_SIZE))
    with pytest.raises(AmigaRecordError):
        amiga.AmigaPorItem.from_bytes(bytes(66))


def test_the_effect_node_transposes_onto_the_dos_payload():
    """`goldbox/dos.py`'s `INNATE_PAYLOAD` is `00 00 FF 00` for a permanent
    effect; the Amiga writes the same four bytes one later, behind the pad
    at offset 1.  So a transposed node has to reproduce it exactly."""
    from goldbox.dos import EFFECT_NEXT_NULL, INNATE_PAYLOAD

    node = bytes((107, 0x00, 0x00, 0x00, 0xFF, 0x00, 0x00, 0xC5, 0x7C, 0x0C))
    out = amiga.amiga_por_effect_to_dos(node)
    assert len(out) == dos_layout.EFFECT_SIZE
    assert out[0] == 107
    assert out[1:5] == INNATE_PAYLOAD
    assert out[5:] == EFFECT_NEXT_NULL


def test_an_effect_node_of_the_wrong_length_is_refused():
    with pytest.raises(AmigaRecordError):
        amiga.amiga_por_effect_to_dos(bytes(dos_layout.EFFECT_SIZE))


#: The fields `to_dos_record` deliberately does not carry across, each with
#: the reason it is on this list.  A field that stopped round-tripping and is
#: not named here is a bug, which is what the test below catches.
NOT_TRANSPOSED = {
    "name_length": "re-cut from 16 NUL-padded bytes to a count and fifteen",
    "name_text": "re-cut from 16 NUL-padded bytes to a count and fifteen",
    "effect_chain": "a live Amiga heap address; written NULL",
    "field_83_87": "the unplaced window; written zero rather than guessed",
    "experience": "one u32 on the Amiga, spanning this field and gap_0af",
    "gap_0af": "experience's fourth byte on the Amiga",
}


def test_the_dos_recut_carries_every_field_it_does_not_declare_dropped():
    """Read the re-cut record back through `goldbox/dos.py` and compare.

    The two readers are independent -- one applies the shift map to the
    Amiga bytes, the other reads a DOS record straight -- so this fails if
    the re-cut loses a field, mis-orders a `u16`, or drifts by a byte.
    """
    from goldbox.dos import DosCharacter

    for path in amiga_por_records():
        a = AmigaPorCharacter.from_bytes(path.read_bytes(), str(path))
        d = DosCharacter(amiga.to_dos_record(a))
        for f in dos_layout.LAYOUT:
            if f.name in NOT_TRANSPOSED:
                continue
            assert d.get(f.name) == a.get(f.name), (path, f.name)
        assert d.name == a.name, path
        assert d.get("experience") + (d.raw("gap_0af")[0] << 24) == a.experience


def test_the_recut_refuses_to_invent_the_unplaced_window():
    """DOS holds `00 00 01 00 00` there in 24 of 24 specimens and the Amiga's
    own bytes are zero.  Copying the DOS constant in would be putting a DOS
    value into a record built from an Amiga one, which is the thing
    `.claude/rules/conversions.md` forbids -- so the re-cut writes zero and
    says so."""
    for path in amiga_por_records():
        a = AmigaPorCharacter.from_bytes(path.read_bytes(), str(path))
        record = amiga.to_dos_record(a)
        window = dos_layout.FIELDS_BY_NAME["field_83_87"]
        assert record[window.span] == bytes(window.size), path


def test_the_neutral_record_carries_the_amiga_port_and_its_items():
    for path in amiga_por_with_items():
        c = amiga.read_amiga_por(path)
        n = amiga.to_neutral(c)
        assert n.port == "Amiga"
        assert n.source == str(path)
        assert len(n.get("inventory")) == len(c.items)
        # The C64 projection puts the type index first, so a lost item file
        # or a mis-strided one shows up here as the wrong item entirely.
        assert [it[0] for it in n.get("inventory")] == \
            [it.get("type_index") for it in c.items]
        assert any("goldbox.amiga.to_dos_record" in w for w in n.warnings)


def test_the_neutral_record_agrees_with_what_the_game_drew_for_garwan():
    """The whole point of the bridge: the sheet's own numbers come out the
    other side of it.  Not the reader agreeing with itself -- the neutral
    record agreeing with a photograph."""
    for path in amiga_por_with_items():
        c = amiga.read_amiga_por(path)
        if c.name != "GARWAN":
            continue
        n = amiga.to_neutral(c)
        assert n.get("name") == "GARWAN"
        assert n.get("hp_max") == 14
        assert 60 - n.get("armour_class") == 1
        assert n.get("experience") == 17
        assert n.get("exceptional_strength") == 100
        assert n.get("movement_current") == 9
        # Encumbrance is derived, so `goldbox/dos.py` drops it rather than
        # carrying it -- the identity that proves the item file is decoded
        # is asserted on the reader above, not here.  It is deliberately
        # *not* in `dropped`: `#118 (Stop showing the player drops nobody
        # would notice)` put it in `goldbox.dos.UNREPORTED_DROPS` on
        # 2026-08-27, because money plus item weight is a number the
        # destination works out for itself and there is nothing for a player
        # to see go missing. This test asserted the old line until 2026-09-04
        # and never went red, because the specimen corpus had been lost with
        # `work/` and every test that reads one was skipping.
        assert n.get("encumbrance") is None
        assert "encumbrance" in dos_unreported_drops()
        assert not any("encumbrance" in d for d in n.dropped)
        assert n.get("strength") == 18
        assert n.get("age") == 18
        return
    pytest.skip("GARWAN is not in $AMIGA_POR_SAVES")


def dos_unreported_drops() -> frozenset:
    from goldbox import dos
    return dos.UNREPORTED_DROPS


def test_the_innate_effects_reach_the_neutral_record():
    """The dwarf's four racial ids and the elf's one, through the ten-byte
    Amiga node and the nine-byte DOS one that `goldbox/dos.py` filters.

    `INNATE_EFFECTS` is the filter and the ids it turns away do **not** reach
    the neutral record -- nine of the twelve specimens with a `.spc` file are
    entirely racial and cross whole, and the other three are
    `test_an_effect_the_neutral_record_cannot_hold_is_reported`'s business.
    """
    from goldbox import dos

    seen = 0
    for path in amiga_por_records():
        c = amiga.read_amiga_por(path)
        if not c.effects:
            continue
        seen += 1
        n = amiga.to_neutral(c)
        assert n.get("innate_effects") == [
            e[0] for e in c.effects if e[0] in dos.INNATE_EFFECTS], path
    if not seen:
        pytest.skip("no .spc beside any record under $AMIGA_POR_SAVES")


def test_an_effect_the_neutral_record_cannot_hold_is_reported():
    """A dropped `.spc` node has to be named, not left to a zero-byte file.

    Three of the twenty specimens carry an effect `INNATE_EFFECTS` turns away
    -- ADDERLY's extra strength (38), CONJURER's Ring of Fire Resistance (61)
    and MAGICIAN's displacement (89), all three at duration zero, so none of
    them is a spell that was going to expire anyway.  `write_por` writes them
    a zero-byte `.spc`, and until
    `#232 (An item-granted effect is dropped on the way through the neutral
    record, with no report)` closes, the least the conversion owes the player
    is a line saying which effect went.

    **The line names the effect and what it costs, and nothing else.**
    Donald's wording, 2026-09-04: no effect id, no module name, no issue
    number, because `AGENTS.md` says what a user reads in the interface
    carries no address or offset. So this asserts the effect's own name is
    in the line, which is what a player would look for, rather than an
    internal id they have no way to know.
    """
    from goldbox import dos, traits

    seen = 0
    for path in amiga_por_records():
        c = amiga.read_amiga_por(path)
        lost = [e[0] for e in c.effects if e[0] not in dos.INNATE_EFFECTS]
        if not lost:
            continue
        seen += 1
        n = amiga.to_neutral(c)
        for eid in lost:
            said = traits.describe(eid)
            named = f"{said[:1].upper()}{said[1:]}"
            assert any(d.startswith(named) for d in n.dropped), (path, eid)
            # `capitalize()` would render effect 61 as "Wearing a ring of
            # fire resistance" and take the item's own name down with it.
            assert not any("ring of fire" in d for d in n.dropped), path
            assert not any(str(eid) in d for d in n.dropped), (path, eid)
        # And it really is gone, so the line is not decoration.
        _, _, spc, _ = amiga.write_por(n)
        assert len(spc) == amiga.AMIGA_POR_EFFECT_SIZE * (
            len(c.effects) - len(lost)), path
    if not seen:
        pytest.skip("no specimen carries a non-innate effect")


# ---------------------------------------------------------------------------
# Writing an Amiga Pool of Radiance character (#105)
# ---------------------------------------------------------------------------
#
# The writer is the reader run backwards, so the tests that matter are the
# ones a wrong byte order or a wrong shift would fail: a round trip against
# genuine specimens masked by the writer's *declared* list rather than by
# whatever happened to differ, and the placement checks that a synthetic
# character can carry with no game data anywhere.


def por_write_mask() -> set[int]:
    """Offsets a round trip is allowed to differ in, and why each is there.

    Built from the **declared** tables -- `amiga.POR_WRITE_UNSOURCED` for the
    three insertions and the heap pointer, and `goldbox.dos`'s own
    `WRITE_UNSOURCED`, `WRITE_CONSTANTS`, `WRITE_DEFAULTS`, `WRITE_DERIVED`
    and computed
    fields for everything the DOS writer already says it does not carry.  Masking by the diff
    instead would make the test agree with the code by construction.
    """
    from goldbox import dos

    mask: set[int] = set()
    for first, size, _ in amiga.POR_WRITE_UNSOURCED:
        mask |= set(range(first, first + size))

    def field(name: str) -> set[int]:
        f = dos_layout.FIELDS_BY_NAME[name]
        return {amiga_por_offset(o)
                for o in range(f.offset, f.offset + f.size)
                if o not in AMIGA_POR_UNPLACED}

    for name, _ in dos.WRITE_UNSOURCED:
        mask |= field(name)
    for name, _, _ in dos.WRITE_CONSTANTS:
        mask |= field(name)
    for name, _, _, _ in dos.WRITE_DEFAULTS:
        mask |= field(name)
    for name, _ in dos.WRITE_DERIVED:
        mask |= field(name)
    # Computed rather than copied, and `goldbox.dos.WRITE_TARGETS` says so.
    mask |= field("encumbrance") | field("item_count")
    # Repacked: `goldbox.dos` reads the sixteen slots as a set and writes them
    # back from the end.  Four of the fourteen Amiga exports are not filled
    # from the end, so the positions do not survive -- #110.
    mask |= field("spells_memorised")
    # The gaps, which the DOS writer zeroes and names in its own report.
    for f in dos_layout.LAYOUT:
        if f.name.startswith("gap_"):
            mask |= field(f.name)
    return mask


def test_every_masked_field_is_one_the_declared_tables_name():
    """The mask cannot quietly grow.

    Every offset it covers has to be inside a field named in
    `amiga.POR_WRITE_UNSOURCED`, in one of `goldbox.dos`'s four declared tables,
    or in the short computed/repacked list above -- so a new difference in a
    field nobody declared fails the round trip instead of being absorbed.
    """
    from goldbox import dos

    named = {name for name, _ in dos.WRITE_UNSOURCED}
    named |= {name for name, _, _ in dos.WRITE_CONSTANTS}
    named |= {name for name, _, _, _ in dos.WRITE_DEFAULTS}
    named |= {name for name, _ in dos.WRITE_DERIVED}
    named |= {"encumbrance", "item_count", "spells_memorised"}
    named |= {f.name for f in dos_layout.LAYOUT if f.name.startswith("gap_")}
    declared = {o for first, size, _ in amiga.POR_WRITE_UNSOURCED
                for o in range(first, first + size)}
    for offset in por_write_mask() - declared:
        hit = [f.name for f in dos_layout.LAYOUT
               if f.offset not in AMIGA_POR_UNPLACED
               and amiga_por_offset(f.offset) <= offset
               < amiga_por_offset(f.offset) + f.size]
        assert hit and hit[0] in named, (hex(offset), hit)


def test_the_record_writer_is_the_readers_exact_inverse():
    """288 -> 285 -> 288, on every specimen, outside the declared list.

    This is the transposition alone -- no neutral record, so nothing is
    dropped or derived on the way through.  A wrong byte order, a wrong shift
    or a mis-cut name fails it on the first specimen.
    """
    declared = {o for first, size, _ in amiga.POR_WRITE_UNSOURCED
                for o in range(first, first + size)}
    seen = 0
    for path in amiga_por_records():
        raw = path.read_bytes()
        c = AmigaPorCharacter.from_bytes(raw, str(path))
        back = amiga.from_dos_record(amiga.to_dos_record(c))
        assert len(back) == AMIGA_POR_RECORD_SIZE
        differ = [i for i in range(AMIGA_POR_RECORD_SIZE)
                  if back[i] != raw[i] and i not in declared]
        assert not differ, (path, [hex(i) for i in differ])
        seen += 1
    assert seen


def test_a_specimen_round_trips_through_the_neutral_record():
    """Amiga -> neutral -> Amiga, byte for byte outside the declared mask.

    The full path a conversion takes, so it exercises `goldbox.dos.to_neutral`
    and `goldbox.dos.write` as well as the two transpositions.
    """
    mask = por_write_mask()
    seen = 0
    for path in amiga_por_records():
        c = amiga.read_amiga_por(path)
        record, _, _, rep = amiga.write_por(amiga.to_neutral(c))
        assert not rep.unaccounted, (path, rep.unaccounted[:8])
        differ = [i for i in range(AMIGA_POR_RECORD_SIZE)
                  if record[i] != c.raw[i] and i not in mask]
        assert not differ, (path, [hex(i) for i in differ])
        seen += 1
    assert seen


def test_the_item_nodes_round_trip_past_their_cached_line():
    """Every byte of a 65-byte item node but the display cache and `next`.

    The line is a render the game rewrites, and `next` is a live Amiga heap
    address -- both are written empty on purpose, and everything else has to
    come back identical or the item map is wrong.
    """
    nodes = 0
    for path in amiga_por_with_items():
        c = amiga.read_amiga_por(path)
        _, itm, _, _ = amiga.write_por(amiga.to_neutral(c))
        assert len(itm) == len(c.items) * amiga.AMIGA_POR_ITEM_SIZE, path
        for n, item in enumerate(c.items):
            written = itm[n * amiga.AMIGA_POR_ITEM_SIZE:
                          (n + 1) * amiga.AMIGA_POR_ITEM_SIZE]
            assert written[0x02E:] == item.raw[0x02E:], (path, n)
            assert written[:0x02E] == bytes(0x02E), (path, n)
            nodes += 1
    assert nodes


def test_the_effect_nodes_round_trip_past_their_next_pointer():
    """Every node the neutral record can hold comes back byte for byte.

    Fifteen of the eighteen nodes on the twenty specimens, and nine of the
    twelve `.spc` files whole.  The other three files lose their only node to
    `#232 (An item-granted effect is dropped on the way through the neutral
    record, with no report)`; when that closes this becomes 18 of 18 and 12 of
    12, and the counts below are what say so rather than a comment.
    """
    from goldbox import dos

    nodes = files = whole = 0
    for path in amiga_por_records():
        c = amiga.read_amiga_por(path)
        if not c.effects:
            continue
        files += 1
        kept = [e for e in c.effects if e[0] in dos.INNATE_EFFECTS]
        _, _, spc, _ = amiga.write_por(amiga.to_neutral(c))
        assert len(spc) == len(kept) * amiga.AMIGA_POR_EFFECT_SIZE, path
        if len(kept) == len(c.effects):
            whole += 1
        for n, node in enumerate(kept):
            written = spc[n * amiga.AMIGA_POR_EFFECT_SIZE:
                          (n + 1) * amiga.AMIGA_POR_EFFECT_SIZE]
            assert written[:6] == node[:6], (path, n)
            assert written[6:] == bytes(4), (path, n)
            nodes += 1
    if not files:
        pytest.skip("no .spc beside any record under $AMIGA_POR_SAVES")
    assert nodes and whole <= files


# -- the synthetic half: no game data, so these run everywhere --------------


def test_every_byte_of_a_written_record_is_accounted_for():
    record, itm, spc, rep = amiga.write_por(sample())
    assert len(record) == AMIGA_POR_RECORD_SIZE
    assert rep.total == AMIGA_POR_RECORD_SIZE + len(itm) + len(spc)
    assert rep.unaccounted == []


def test_the_name_is_sixteen_nul_padded_bytes_with_no_count():
    """The Amiga's own encoding, and the whole of the difference at `0x00`.

    A writer that copied DOS's count byte through would put a `07` in front
    of the name and the game would draw it.
    """
    record, _, _, _ = amiga.write_por(sample())
    assert record[:16] == b"AELFRIC".ljust(16, b"\0")
    assert AmigaPorCharacter.from_bytes(record).name == "AELFRIC"


def test_multi_byte_fields_are_written_big_endian():
    """A 68000 record. Little-endian here draws 51200 platinum, not 200."""
    record, _, _, _ = amiga.write_por(sample(platinum=200, age=33))
    assert record[amiga_por_offset(
        dos_layout.FIELDS_BY_NAME["platinum"].offset):][:2] == b"\x00\xc8"
    c = AmigaPorCharacter.from_bytes(record)
    assert c.money["platinum"] == 200
    assert c.get("age") == 33


def test_experience_is_one_big_endian_longword_across_dos_gap_0af():
    """DOS spends three bytes plus `gap_0af`; the Amiga spends one `u32be`.

    Tested on the transposition rather than through `write_por`, because
    `goldbox.dos.write`'s own field is three bytes wide and nothing that goes
    through it can put anything in the fourth -- #111.  A writer that
    swapped only three would put a large total's bytes in the wrong order.
    """
    record = bytearray(dos_layout.RECORD_SIZE)
    at = dos_layout.FIELDS_BY_NAME["experience"].offset
    record[at:at + 4] = b"\x04\x03\x02\x01"       # 0x01020304, little-endian
    out = amiga.from_dos_record(bytes(record))
    assert out[amiga.AMIGA_POR_EXPERIENCE:
               amiga.AMIGA_POR_EXPERIENCE + 4] == b"\x01\x02\x03\x04"
    assert AmigaPorCharacter.from_bytes(out).experience == 0x01020304


def test_a_written_experience_total_survives_the_round_trip():
    record, _, _, _ = amiga.write_por(sample(experience=123456))
    assert AmigaPorCharacter.from_bytes(record).experience == 123456


def test_the_effect_chain_is_written_null():
    """A live heap address has no business in a file we authored.

    Tested against a DOS record that **holds** one, because `goldbox.dos.write`
    already zeroes its own field: going through `write_por` alone would pass
    whether or not this writer nulled anything, and did.
    """
    record = bytearray(dos_layout.RECORD_SIZE)
    at = dos_layout.FIELDS_BY_NAME["effect_chain"].offset
    record[at:at + 4] = b"\x9f\xe0\xc6\x00"       # a genuine Amiga heap value
    out = amiga.from_dos_record(bytes(record))
    assert out[0x080:0x084] == bytes(4)
    assert AmigaPorCharacter.from_bytes(out).effect_chain == 0
    written, _, _, _ = amiga.write_por(sample())
    assert AmigaPorCharacter.from_bytes(written).effect_chain == 0


def test_the_three_insertions_hold_what_the_specimens_hold():
    """`0x07F` and `0x11F` zero, and the unplaced window's six measured bytes.

    The six are `00 00 01 00 00 00`, which every record Amiga Pool of
    Radiance itself wrote on disk 1 holds -- DOS's `field_83_87` constant
    under the `+1` shift, with the second insertion after it.
    """
    record, _, _, _ = amiga.write_por(sample())
    assert record[amiga.AMIGA_POR_PAD] == 0
    assert record[amiga.AMIGA_POR_TAIL_PAD] == 0
    at = amiga.AMIGA_POR_FIELD_83_87_AT
    assert record[at:at + 6] == b"\x00\x00\x01\x00\x00\x00"
    # The `01` lands two bytes into the window, which is where DOS's own
    # sits under the `+1` shift -- and that is what narrows the second
    # insertion to the three bytes after it rather than the three before.
    assert at + 2 == amiga.AMIGA_POR_INSERTION_AFTER
    assert all(o > amiga.AMIGA_POR_INSERTION_AFTER
               for o in amiga.AMIGA_POR_INSERTION_CANDIDATES)


def test_a_character_carrying_nothing_gets_no_item_file():
    """`b""` is not an empty file: #62 is what a zero-length one did."""
    _, itm, spc, _ = amiga.write_por(sample())
    assert itm == b""
    assert spc == b""


def test_a_written_record_reads_back_as_the_character_that_was_written():
    """The end-to-end check: what the reader makes of what the writer made."""
    char = sample()
    record, _, _, _ = amiga.write_por(char)
    back = amiga.to_neutral(AmigaPorCharacter.from_bytes(record))
    for name in ("name", "strength", "intelligence", "wisdom", "dexterity",
                 "constitution", "charisma", "age", "experience", "level",
                 "hp_max", "platinum", "gems", "jewelry", "movement"):
        assert back.get(name) == char.get(name), name


@pytest.mark.parametrize("length", [284, 286, 288, 428, 484])
def test_a_dos_record_of_the_wrong_length_is_refused_by_name(length):
    with pytest.raises(AmigaRecordError):
        amiga.from_dos_record(bytes(length))


@pytest.mark.parametrize("length", [62, 64, 65, 66])
def test_a_dos_item_of_the_wrong_length_is_refused_by_name(length):
    with pytest.raises(AmigaRecordError):
        amiga.amiga_por_item_from_dos(bytes(length))


@pytest.mark.parametrize("length", [8, 10])
def test_a_dos_effect_of_the_wrong_length_is_refused_by_name(length):
    with pytest.raises(AmigaRecordError):
        amiga.amiga_por_effect_from_dos(bytes(length))


@pytest.mark.parametrize("slot,index", [("AB", 1), ("1", 1), ("A", 0),
                                        ("A", 7), ("", 1)])
def test_a_save_file_name_outside_the_scheme_is_refused(slot, index):
    with pytest.raises(AmigaRecordError):
        amiga.por_filename(slot, index)


def c64_parties():
    """Every character on every `PORSAVE*` disk the player has.

    The direction this whole issue exists for -- a C64 party reaching the
    Amiga -- had no test at all, only a hand-run conversion in a scratch
    directory that has since been deleted.  A population rather than one
    save, because the sample size is the finding.
    """
    import gamedata

    from goldbox import c64_codec, items
    from goldbox.d64 import D64
    from goldbox.savegame import load_save

    out = []
    for path in gamedata.save_disks():
        try:
            game, sg0, sg1 = load_save(D64.open(str(path)))
        except Exception:
            # A `PORSAVE*` disk need not carry a save: one of the player's
            # holds only spell stores. Skipping it is not a failure.
            continue
        save0 = sg0.to_bytes()
        for slot in sg0.characters:
            out.append(c64_codec.read(
                slot.record,
                roster=sg1.roster(slot.index) if sg1 is not None else None,
                inventory=[i.raw
                           for i in items.items_for_slot(save0, slot.index)],
                game=game, source=f"{path.name} slot {slot.index}"))
    if not out:
        pytest.skip("needs the player's PORSAVE disks; set $POR_DISKS")
    return out


def test_a_c64_party_converts_to_a_coherent_amiga_record():
    """C64 -> neutral -> Amiga, on every character the player has.

    Not a round trip -- there is nothing to compare against, because no Amiga
    file this party came from exists.  So the check is the one thing an Amiga
    record has to satisfy that a wrong offset or byte order cannot fake: the
    **encumbrance identity**.  The record's own `encumbrance` word has to be
    money plus item weight times quantity, read out of the `.itm` nodes the
    same write produced, and it fixes the seven money offsets, the 65-byte
    stride, and the weight and quantity offsets and byte order together.

    78 of 78 characters over the player's PORSAVE disks, 2026-09-04.
    """
    seen = 0
    for char in c64_parties():
        record, itm, spc, rep = amiga.write_por(char)
        assert len(record) == AMIGA_POR_RECORD_SIZE, char.get("name")
        assert rep.unaccounted == [], char.get("name")
        assert len(itm) % amiga.AMIGA_POR_ITEM_SIZE == 0
        assert len(spc) % amiga.AMIGA_POR_EFFECT_SIZE == 0

        back = AmigaPorCharacter.from_bytes(record)
        assert back.name == str(char.get("name"))[:AMIGA_POR_NAME_SIZE]
        assert back.get("item_count") == len(itm) // amiga.AMIGA_POR_ITEM_SIZE

        carried = 0
        for n in range(len(itm) // amiga.AMIGA_POR_ITEM_SIZE):
            node = amiga.AmigaPorItem.from_bytes(
                itm[n * amiga.AMIGA_POR_ITEM_SIZE:
                    (n + 1) * amiga.AMIGA_POR_ITEM_SIZE])
            carried += node.get("weight") * max(1, node.get("quantity"))
        assert back.get("encumbrance") == sum(back.money.values()) + carried, \
            (char.get("name"), back.get("encumbrance"))
        seen += 1
    assert seen


def test_a_c64_name_too_long_for_the_amiga_field_is_not_silently_cut():
    """Sixteen bytes with no terminator is the Amiga's whole name field.

    The C64 allows fifteen characters and DOS a count byte plus fifteen, so
    nothing a real save holds overflows -- but a name of exactly sixteen would
    fill the field with no NUL, which is the shape the reader warns about on
    the way in.  Written here so the writer's behaviour is pinned rather than
    assumed: fifteen is the most that can arrive, and it still terminates.
    """
    record, _, _, _ = amiga.write_por(sample(name="ABCDEFGHIJKLMNO"))
    assert record[:AMIGA_POR_NAME_SIZE] == b"ABCDEFGHIJKLMNO\0"
    assert AmigaPorCharacter.from_bytes(record).name == "ABCDEFGHIJKLMNO"


def test_the_save_file_names_are_the_ones_on_the_shipped_disk():
    assert amiga.por_filename("A", 1) == "CHRDATA1.sav"
    assert amiga.por_filename("a", 6, ".itm") == "CHRDATA6.itm"
    assert amiga.por_filename("B", 3, ".spc") == "CHRDATB3.spc"


# ---------------------------------------------------------------------------
# The save slot and the list the picker reads (#109)
# ---------------------------------------------------------------------------
#
# All of these run on a disk `goldbox.amiga_adf` formats itself, so no game data is
# involved and they run wherever the suite does.


def synthetic_savegame(slot: str = "A") -> bytes:
    """A 13141-byte Amiga Pool of Radiance saved game, built not copied.

    Only the character table is filled in, because that is the only region
    `retarget_savegame` touches: six 41-byte entries at 12813 holding
    `CHRDAT<slot><n>` as eight plain bytes. `docs/124-amiga-port.md` §1.9a has
    the region map the rest of the file would follow.
    """
    save = bytearray(amiga.POR_SAVEGAME_SIZE)
    for n in range(amiga.POR_PARTY_MAX):
        at = amiga.POR_CHARACTER_TABLE + n * amiga.POR_CHARACTER_TABLE_STRIDE
        save[at:at + 8] = f"CHRDAT{slot.upper()}{n + 1}".encode("ascii")
    return bytes(save)


def save_disk_with(slots: str = "A"):
    """A blank disk carrying a `save` drawer and a slot list."""
    from goldbox.amiga_adf import AmigaDisk

    disk = AmigaDisk.blank("poolgame")
    disk.make_dir("save")
    disk.write_file(amiga.POR_SLOT_LIST, amiga.slot_list_bytes(list(slots)))
    return disk


def test_a_slot_written_onto_a_disk_is_offered_by_the_picker():
    """The whole of #109: the files are not the slot, the list is.

    Reading `save/save` back is what the game's picker does, so this asserts
    the thing a player would see rather than that a function was called.
    """
    disk = save_disk_with("A")
    written = amiga.write_por_slot(disk, "B", [sample()],
                                   savegame=synthetic_savegame())
    assert amiga.read_slot_list(disk) == ["A", "B"]
    assert disk.read_file(amiga.POR_SLOT_LIST) == b"AB        "
    assert "/save/CHRDATB1.sav" in written
    assert amiga.POR_SLOT_LIST in written
    assert disk.verify() == []


def test_the_slot_list_is_ten_bytes_and_space_padded():
    """`"A         "` is what the shipped disk holds; ten bytes, not one."""
    assert amiga.slot_list_bytes(["A"]) == b"A         "
    assert len(amiga.slot_list_bytes(list("ABCDEFGHIJ"))) == 10


def test_each_slot_letter_sits_in_its_own_byte_and_a_gap_stays_a_gap():
    """The exact ten bytes Amiga Pool of Radiance wrote for A, B and D.

    Measured 2026-09-01 (#109): one loaded party saved to `D` and then to `B`
    left `save/save` reading `"AB D      "`. The space at byte 2 is `C`, and
    it is what says the file is an array indexed by letter rather than a list
    -- sorting would have given `ABD` and appending `ADB`, and both close the
    gap. The order the letters are handed over cannot matter, so `D` first
    gives the same bytes.
    """
    assert amiga.slot_list_bytes(["A", "B", "D"]) == b"AB D      "
    assert amiga.slot_list_bytes(["D", "B", "A"]) == b"AB D      "
    assert amiga.slot_list_bytes(list("ABCDEFGHIJ")) == b"ABCDEFGHIJ"


def test_a_new_slot_does_not_take_another_slots_byte():
    """Adding `F` to a disk holding A, B and D leaves all three where they are.

    The old writer appended, so this came back `ABDF      ` -- `D` in `C`'s
    byte and `F` in `D`'s. The picker draws the same four letters either way,
    which is why this needed the game to be watched writing the file rather
    than reasoned about.
    """
    disk = save_disk_with("A")
    disk.write_file(amiga.POR_SLOT_LIST, b"AB D      ")
    amiga.write_por_slot(disk, "F", [sample()],
                         savegame=synthetic_savegame())
    assert disk.read_file(amiga.POR_SLOT_LIST) == b"AB D F    "


def test_a_slot_letter_outside_the_ten_is_refused_before_anything_is_written():
    """Refusing beats writing a slot the player cannot load.

    `K` is the eleventh letter and the list holds ten, so it can never be
    offered. The assertion that matters is the second one: the disk is
    unchanged, not merely that something was raised.
    """
    disk = save_disk_with("A")
    before = disk.to_bytes()
    with pytest.raises(AmigaRecordError):
        amiga.write_por_slot(disk, "K", [sample()],
                             savegame=synthetic_savegame())
    assert disk.to_bytes() == before


def test_a_slot_with_no_saved_game_is_refused():
    """Character files alone are a drawer full of files, not a save slot."""
    disk = save_disk_with("A")
    before = disk.to_bytes()
    with pytest.raises(AmigaRecordError):
        amiga.write_por_slot(disk, "B", [sample()])
    assert disk.to_bytes() == before


def test_a_saved_game_moved_to_another_slot_is_retargeted():
    """The engine loads the party the character table names, not the slot.

    Measured the other way round: the game's own save to B rewrote all six
    entries from `CHRDATA<n>` to `CHRDATB<n>` (#28 §1.9b). A savegame copied
    without this loads the party it came from.
    """
    disk = save_disk_with("A")
    amiga.write_por_slot(disk, "B", [sample()],
                         savegame=synthetic_savegame("A"))
    save = disk.read_file("/save/savgamB.dat")
    for n in range(amiga.POR_PARTY_MAX):
        at = amiga.POR_CHARACTER_TABLE + n * amiga.POR_CHARACTER_TABLE_STRIDE
        assert save[at:at + 8] == f"CHRDATB{n + 1}".encode()


def test_a_saved_game_that_is_not_one_is_refused_by_name():
    with pytest.raises(AmigaRecordError):
        amiga.retarget_savegame(bytes(amiga.POR_SAVEGAME_SIZE), "B")
    with pytest.raises(AmigaRecordError):
        amiga.retarget_savegame(bytes(13137), "B")


def test_a_shorter_party_does_not_leave_the_old_ones_files_behind():
    """Six characters then four must not leave slots five and six loadable."""
    disk = save_disk_with("A")
    amiga.write_por_slot(disk, "B", [sample()] * 6,
                         savegame=synthetic_savegame())
    assert disk.lookup("/save/CHRDATB6.sav")
    amiga.write_por_slot(disk, "B", [sample()] * 4,
                         savegame=synthetic_savegame())
    for n in (5, 6):
        with pytest.raises(Exception):
            disk.lookup(f"/save/CHRDATB{n}.sav")
    assert disk.verify() == []


def test_a_disk_with_no_slot_list_lists_nothing():
    """The picker reads the file; no file is no slots, whatever is in the
    drawer."""
    from goldbox.amiga_adf import AmigaDisk

    disk = AmigaDisk.blank("poolgame")
    disk.make_dir("save")
    assert amiga.read_slot_list(disk) == []


def test_the_slot_list_ignores_the_padding_and_keeps_the_letters():
    """A letter counts wherever it sits, spaces and all.

    `"ADB       "` is not a shape the game writes -- it is what our own writer
    produced before #109 measured the file -- and reading it as three slots is
    what lets the next write put all three in their proper bytes.
    """
    disk = save_disk_with("A")
    disk.write_file(amiga.POR_SLOT_LIST, b"ADB       ")
    assert amiga.read_slot_list(disk) == ["A", "D", "B"]
    disk.write_file(amiga.POR_SLOT_LIST, b"AB D      ")
    assert amiga.read_slot_list(disk) == ["A", "B", "D"]


@pytest.mark.parametrize("party", [[], [1] * 7])
def test_a_party_that_is_not_one_to_six_is_refused(party):
    disk = save_disk_with("A")
    with pytest.raises(AmigaRecordError):
        amiga.write_por_slot(disk, "B", [sample()] * len(party),
                             savegame=synthetic_savegame())


def test_the_saved_game_file_name_is_the_shipped_one():
    assert amiga.por_savegame_filename("A") == "savgamA.dat"
    assert amiga.por_savegame_filename("b") == "savgamB.dat"
    with pytest.raises(AmigaRecordError):
        amiga.por_savegame_filename("K")


def test_the_shift_map_covers_every_dos_field_the_writer_does_not_special_case():
    """A guard against `goldbox/dos_layout.py` moving under this module.

    That table belongs to the DOS side and a field there can be renamed,
    split or moved. Every field either lands somewhere in the 288 bytes or is
    one this writer handles itself; a field that does neither would be written
    nowhere, silently.
    """
    covered: set[int] = set()
    for f in dos_layout.LAYOUT:
        if amiga._por_special(f):
            continue
        at = amiga_por_offset(f.offset)
        assert at + f.size <= AMIGA_POR_RECORD_SIZE, f.name
        covered |= set(range(at, at + f.size))
    special = set(range(amiga.AMIGA_POR_NAME_SIZE))
    special |= set(range(amiga.AMIGA_POR_EXPERIENCE,
                         amiga.AMIGA_POR_EXPERIENCE + 4))
    special |= set(range(amiga.AMIGA_POR_FIELD_83_87_AT,
                         amiga.AMIGA_POR_FIELD_83_87_AT
                         + len(amiga.AMIGA_POR_FIELD_83_87)))
    special |= {amiga.AMIGA_POR_PAD, amiga.AMIGA_POR_TAIL_PAD}
    assert covered | special == set(range(AMIGA_POR_RECORD_SIZE))


def test_a_slot_that_will_not_fit_leaves_the_disk_exactly_as_it_was():
    """Half a party on a disk is worse than none.

    `AmigaDisk.write_file` allocates the replacement before freeing the
    original, so a slot that runs the disk out of blocks stops part way
    through -- which is the state `write_por_slot` exists to refuse, arrived
    at by a different route.
    """
    from goldbox.amiga_adf import AmigaDisk

    # 48 blocks fits the six records and stops on the saved game.
    disk = AmigaDisk.blank("poolgame", blocks=48)
    disk.make_dir("save")
    disk.write_file(amiga.POR_SLOT_LIST, amiga.slot_list_bytes(["A"]))
    before = disk.to_bytes()
    with pytest.raises(Exception):
        amiga.write_por_slot(disk, "B", [sample()] * 6,
                             savegame=synthetic_savegame())
    assert disk.to_bytes() == before
    assert disk.verify() == []
