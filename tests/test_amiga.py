"""`por.amiga` against the offsets the character sheet actually drew.

The ramp probe is the whole method: a `.pc` whose byte at every offset *is*
that offset, so a number the sheet prints names where it came from. These
tests rebuild that payload and assert the reader agrees with what was on
screen -- `docs/124-amiga-port.md` records the runs and the screenshots.

A second set of tests reads the player's own `Save/*.pc` files when
`$POD_SAVES` names a directory holding them, and skips otherwise. No game
data lives in this repository.
"""

from __future__ import annotations

import os
import pathlib

import pytest

from por.amiga import (
    ABILITIES,
    ARMOUR_CLASS,
    COMBAT_BIAS,
    NAME,
    PodCharacter,
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


def test_six_class_levels_run_from_0x09d():
    """Same probe: `LEVEL 157/158/159/160/161/162`."""
    assert PodCharacter.from_bytes(ramp()).class_levels == [
        0x9D, 0x9E, 0x9F, 0xA0, 0xA1, 0xA2]


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
    """One non-zero slot for a single-classed character, two for a dual.

    `T.pc` is the exception and has none at all -- it is somebody's abandoned
    scratch character, and the name the picker draws for it is `?T`.
    """
    for path in real_records():
        pc = PodCharacter.from_bytes(path.read_bytes())
        assert all(0 <= level <= 60 for level in pc.class_levels), path
        assert sum(1 for level in pc.class_levels if level) <= 2, path


def test_every_real_record_reads_the_same_unequipped_defaults():
    """Armour class 10 and 1d2 damage on all twelve: these are *base* values,
    and the derived ones the game shows are computed from equipment. TROND
    stores AC 10 here and joined the party at AC -7."""
    for path in real_records():
        pc = PodCharacter.from_bytes(path.read_bytes())
        assert pc.armour_class == 10, path
        assert pc.damage == (1, 2, 0), path


def test_a_real_record_agrees_with_what_the_game_displayed():
    """TROND was added to the party in FS-UAE and the roster said `HP 138`."""
    trond = [p for p in real_records() if p.stem.endswith("TROND")]
    if not trond:
        pytest.skip("no TROND.pc among the .pc files")
    assert PodCharacter.from_bytes(trond[0].read_bytes()).hit_points_max == 138
