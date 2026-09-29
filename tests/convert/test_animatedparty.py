"""Pool of Radiance's creature type and turning class across its three ports."""

from __future__ import annotations

import gamedata
import pytest

from goldbox import (
    amiga_pod,
    amiga_por,
    c64_codec,
    c64_port,
    c64_save,
    dos_codec,
    dos_port,
    effects,
    neutral,
)
from goldbox.record import CharacterRecord
from goldbox.savegame import SaveGame0


@pytest.mark.parametrize("creature_type,turn_class", [(0, 0), (4, 2)])
def test_pool_fields_cross_c64_dos_and_amiga_without_becoming_turn_power(
        creature_type, turn_class):
    source = CharacterRecord.blank()
    source.set("creature_type", creature_type)
    source.set("turn_class", turn_class)
    source.set("turn_power", 7)

    char = c64_codec.read(source, game=c64_port.POOL_OF_RADIANCE)
    assert (char.get("creature_type"), char.get("turn_class"),
            char.get("turn_power")) == (creature_type, turn_class, 7)

    c64, _ = c64_codec.write(char)
    assert (c64.get("creature_type"), c64.get("turn_class")) == (
        creature_type, turn_class)

    dos, _itm, _spc, _ = dos_codec.write(char)
    assert (dos[0x09F], dos[0x076]) == (creature_type, turn_class)
    back = dos_codec.to_neutral(dos_codec.DosCharacter(dos))
    assert (back.get("creature_type"), back.get("turn_class")) == (
        creature_type, turn_class)

    amiga, _itm, _spc, _ = amiga_por.write_por(char)
    assert (amiga[0x0A1], amiga[0x076]) == (creature_type, turn_class)
    back = amiga_por.to_neutral(amiga_por.AmigaPorCharacter.from_bytes(amiga))
    assert (back.get("creature_type"), back.get("turn_class")) == (
        creature_type, turn_class)


def test_pool_writer_dispositions_account_for_both_fields_as_copies():
    for name in ("creature_type", "turn_class"):
        assert name in neutral.FIELDS
        assert c64_codec.field_disposition()[name].startswith("copied")
        assert dos_codec.field_disposition()[name].startswith("copied")
        assert dos_codec.write_field_disposition()[name].startswith("copied")
        assert dos_codec.write_targets()[name].startswith("from neutral")


def test_the_pool_mapping_does_not_claim_a_later_title():
    source = CharacterRecord.blank()
    source.set("creature_type", 4)
    source.set("turn_class", 2)
    later = c64_codec.read(source, game=c64_port.CURSE_OF_THE_AZURE_BONDS)
    assert "creature_type" not in later
    assert "turn_class" not in later

    raw = bytes(dos_port.CURSE_OF_THE_AZURE_BONDS.record_size)
    later = dos_codec.to_neutral(dos_codec.DosCharacter(
        raw, deltas=dos_port.CURSE_OF_THE_AZURE_BONDS))
    assert "creature_type" not in later
    assert "turn_class" not in later
    for name in ("creature_type", "turn_class"):
        assert c64_codec.field_disposition(
            c64_port.CURSE_OF_THE_AZURE_BONDS)[name].startswith("dropped:")
        assert dos_codec.write_field_disposition(
            dos_port.CURSE_OF_THE_AZURE_BONDS)[name].startswith("dropped:")
        assert amiga_pod.pod_write_field_disposition()[name].startswith(
            "dropped:")
        assert amiga_pod.pod_field_disposition()[name].startswith("dropped:")


def _pool_c64(control: int, status: int) -> CharacterRecord:
    rec = CharacterRecord.blank()
    rec.set("name", b"BRUTUS")
    rec.set("flags_0b8", control)
    rec.set("roster_in_use", status)
    return rec


def _pool_dos_character(status, npc, control, share=None):
    char = neutral.NeutralCharacter("DOS", source="built here",
                                    game=c64_port.POOL_OF_RADIANCE)
    char.set("name", "BRUTUS", "built here")
    if status is not None:
        char.set("status", status, "built here")
    char.set("npc", npc, "built here")
    char.set("npc_control_byte", control, "built here")
    if share is not None:
        char.set("treasure_share", share, "built here")
    return char


@pytest.mark.parametrize("stored, flag", [(0xFE, 0), (0xFF, 1)])
def test_a_c64_zombie_reads_as_a_taken_over_player_character(stored, flag):
    char = c64_codec.read(_pool_c64(stored, 0x03),
                          game=c64_port.POOL_OF_RADIANCE)
    assert char.get("npc") is True
    assert char.get("npc_control_byte") == c64_codec.DOS_PC_TAKEN_OVER
    assert char.get("treasure_share") == flag

    dos, _itm, _spc, _rep = dos_codec.write(char)
    control, share = dos_port.FIELDS_BY_NAME["field_83_87"].offset + 1, \
        dos_port.FIELDS_BY_NAME["field_83_87"].offset + 2
    assert (dos[control], dos[share]) == (0xB3, flag)


@pytest.mark.parametrize("flag, stored", [(0, 0xFE), (1, 0xFF)])
def test_a_dos_zombie_writes_to_the_c64_as_the_engine_stores_it(flag, stored):
    char = _pool_dos_character("animated", True, 0xB3, flag)
    rec, rep = c64_codec.write(char)
    assert rec.get("flags_0b8") == stored
    assert rec.get("treasure_share") == 0
    assert not [d for d in rep.dropped + rep.losses
                if "treasure_share" in d or "npc" in d]


@pytest.mark.parametrize("stored, status", [(0xFF, 0x01), (0xFE, 0x83)])
def test_a_companion_byte_off_the_zombie_status_stays_a_companion(
        stored, status):
    char = c64_codec.read(_pool_c64(stored, status),
                          game=c64_port.POOL_OF_RADIANCE)
    assert char.get("npc_control_byte") == stored
    rec, _rep = c64_codec.write(char)
    assert rec.get("flags_0b8") == stored


def test_a_companion_zombie_control_crosses_whole_both_ways():
    char = c64_codec.read(_pool_c64(0xB2, 0x03),
                          game=c64_port.POOL_OF_RADIANCE)
    assert char.get("npc_control_byte") == 0xB2
    assert c64_codec.write(char)[0].get("flags_0b8") == 0xB2
    rec, _rep = c64_codec.write(_pool_dos_character("animated", True, 0xB2, 2))
    assert rec.get("flags_0b8") == 0xB2


def test_engine_written_zombie_fields_read_and_node32_stays_protected():
    from editor import convert
    from tools.registry import specimens

    def party(name):
        root = gamedata.specimen_root()
        if root is None:
            pytest.skip("needs the registered C64 Pool specimens")
        image = root / "por-c64" / f"WISH-SPEC-{name}.D64"
        manifest = image.with_suffix(".provenance.toml")
        if not image.is_file() or not manifest.is_file():
            pytest.skip(f"needs registered specimen {name}")
        recorded = specimens.read_provenance(manifest)["sha256"][image.name]
        assert specimens.sha256_file(image) == recorded
        source = convert.Source.detect(image)
        chars, _ = dos_codec.c64_party(source.save0, source.save1,
                                       game=c64_port.POOL_OF_RADIANCE)
        game = c64_save.container_for(c64_port.POOL_OF_RADIANCE)
        slots = SaveGame0.from_bytes(source.save0, game).characters
        raw = {slot.record.name: slot.record_bytes for slot in slots}
        return {char.get("name"): char for char in chars}, raw

    animated, animated_raw = party("por-700-animate-dead-c64")
    plain, plain_raw = party("por-700-animate-control-c64")
    zombie, control = animated["BRUTUS"], plain["BRUTUS"]
    assert (animated_raw["BRUTUS"][0x0D7], animated_raw["BRUTUS"][0x0A3]) \
        == (4, 2)
    assert (plain_raw["BRUTUS"][0x0D7], plain_raw["BRUTUS"][0x0A3]) \
        == (0, 0)
    assert (zombie.get("creature_type"), zombie.get("turn_class")) == (4, 2)
    assert (zombie.get("npc"), zombie.get("npc_control_byte"),
            zombie.get("treasure_share")) == (True, 0xB3, 1)
    assert (control.get("creature_type"), control.get("turn_class")) == (0, 0)

    _record, _itm, _spc, dos_report = dos_codec.write(zombie)
    _record, _itm, _spc, amiga_report = amiga_por.write_por(zombie)
    for report in (dos_report, amiga_report):
        assert any("innate_effects 32 (Animate Dead)" in line
                   for line in report.dropped)


@pytest.mark.xfail(strict=True, reason=(
    "A C64 zombie reads as neutral status dead, while the write's zombie arm "
    "keys on animated, so the write takes the companion arm and stores $B3; "
    "the neutral status step settles which status a C64 zombie reads as"))
@pytest.mark.parametrize("stored", [0xFE, 0xFF])
def test_a_c64_zombie_survives_a_c64_read_and_write_unchanged(stored):
    rec = _pool_c64(stored, 0x03)
    char = c64_codec.read(rec, game=c64_port.POOL_OF_RADIANCE)
    back, _rep = c64_codec.write(char)
    assert (back.get("flags_0b8"), back.get("treasure_share")) == (
        rec.get("flags_0b8"), rec.get("treasure_share"))


@pytest.mark.parametrize("flag, stored", [(0, 0xFE), (1, 0xFF)])
def test_a_charmed_dos_zombie_still_writes_the_zombie_byte_and_the_charm_row(
        flag, stored):
    char = _pool_dos_character("animated", True, 0xB3, flag)
    char.set("granted_effects",
             [bytes((effects.CHARM_ID, 0, 0, 0x21, 1))], "built here")
    payload = bytearray(0x1C00)
    rec, rep = c64_codec.write(char, payload=payload, party_slot=2,
                               clock_minutes=0)
    ids = payload[effects.EFFECT_ID_OFFSET:
                  effects.EFFECT_ID_OFFSET + effects.EFFECT_SLOTS]
    assert list(ids).count(effects.CHARM_ID) == 1
    assert rec.get("flags_0b8") == stored
    assert rec.get("treasure_share") == 0
    # Count 1 with a party charmer is the one-level Dispel Magic difference,
    # which is noted on the warnings and does not refuse the save.
    assert not rep.losses
    assert len([w for w in rep.warnings if "low bit" in w]) == 1


def _dos_zombie(flag, control, active, side=0):
    char = _pool_dos_character("animated", True, control, flag)
    char.set("creature_type", 4, "built here")
    char.set("turn_class", 2, "built here")
    char.set("movement", 6, "built here")
    char.set("hostile", False, "built here")
    char.set("quickfight", True, "built here")
    char.set("levels", {"cleric": 6}, "built here")
    if active is not None:
        char.set("active", active, "built here")
    char.set("granted_effects",
             [bytes((32, 0, 0, 5 | side << 4, 1))], "built here")
    return char


def _rows(payload, ident):
    ids = payload[effects.EFFECT_ID_OFFSET:
                  effects.EFFECT_ID_OFFSET + effects.EFFECT_SLOTS]
    return [i for i, v in enumerate(ids) if v == ident]


@pytest.mark.parametrize("active", [None, False, True])
@pytest.mark.parametrize("flag, control, stored",
                         [(0, 0xB3, 0xFE), (1, 0xB3, 0xFF), (0, 0xB2, 0xB2)])
def test_a_dos_zombie_is_written_as_the_c64s_own_animate_dead_writes_it(
        flag, control, stored, active):
    char = _dos_zombie(flag, control, active)
    payload = bytearray(0x1C00)
    rec, rep = c64_codec.write(char, payload=payload, party_slot=4,
                               clock_minutes=0)
    assert rec.get("roster_in_use") == 0x03
    assert rec.get("flags_0b8") == stored
    assert rec.get("item_effects")[9] == 32
    rows = _rows(payload, 32)
    assert len(rows) == 1
    row = rows[0]
    assert payload[effects.EFFECT_OWNER_OFFSET + row] == 4
    assert payload[effects.EFFECT_DURATION_OFFSET + row] == 0
    assert payload[effects.EFFECT_MAGNITUDE_OFFSET + row] == 5
    assert (rec.get("creature_type"), rec.get("turn_class"),
            rec.get("movement"), rec.get("combat_side")) == (4, 2, 6, 0x80)
    assert rec.get("turn_power") == 0
    assert not [d for d in rep.dropped if "Animated by a spell" in d]
    assert not rep.losses


def test_a_zombie_that_was_dead_is_not_written_with_a_row():
    char = _pool_dos_character("dead", False, 0)
    payload = bytearray(0x1C00)
    rec, _rep = c64_codec.write(char, payload=payload, party_slot=4,
                                clock_minutes=0)
    assert rec.get("roster_in_use") == 0x83
    assert not _rows(payload, 32)


def test_a_living_cleric_still_gets_a_derived_turn_power():
    char = _pool_dos_character("okay", False, 0)
    char.set("levels", {"cleric": 6}, "built here")
    rec, _rep = c64_codec.write(char)
    assert rec.get("turn_power") != 0


def test_a_later_title_animated_status_still_carries_the_drop_line():
    char = neutral.NeutralCharacter(
        "DOS", source="built here", game=c64_port.CURSE_OF_THE_AZURE_BONDS)
    char.set("name", "BRUTUS", "built here")
    char.set("status", "animated", "built here")
    _rec, rep = c64_codec.write(char)
    assert any("Animated by a spell" in d for d in rep.dropped)


def test_a_zombie_with_no_payload_or_the_wrong_side_reports_the_loss():
    _rec, rep = c64_codec.write(_dos_zombie(0, 0xB3, None))
    assert any("effect 32" in line for line in rep.losses)
    payload = bytearray(0x1C00)
    _rec, rep = c64_codec.write(_dos_zombie(0, 0xB3, None, side=1),
                                payload=payload, party_slot=4,
                                clock_minutes=0)
    assert any("side" in line for line in rep.losses)
