"""Pool of Radiance's creature type and turning class across its three ports."""

from __future__ import annotations

import gamedata
import pytest

from goldbox import (
    amiga_later,
    amiga_pod,
    amiga_por,
    amiga_port,
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


def test_the_pool_mapping_claims_only_the_turning_row_of_curse():
    source = CharacterRecord.blank()
    source.set("creature_type", 4)
    source.set("turn_class", 2)
    later = c64_codec.read(source, game=c64_port.CURSE_OF_THE_AZURE_BONDS)
    assert "creature_type" not in later
    assert later.get("turn_class") == 2

    raw = bytearray(dos_port.CURSE_OF_THE_AZURE_BONDS.record_size)
    raw[_CURSE_TURN] = 2
    later = dos_codec.to_neutral(dos_codec.DosCharacter(
        bytes(raw), deltas=dos_port.CURSE_OF_THE_AZURE_BONDS))
    assert "creature_type" not in later
    assert later.get("turn_class") == 2

    curse_c64 = c64_codec.field_disposition(c64_port.CURSE_OF_THE_AZURE_BONDS)
    curse_dos = dos_codec.write_field_disposition(
        dos_port.CURSE_OF_THE_AZURE_BONDS)
    assert curse_c64["creature_type"].startswith("dropped:")
    assert curse_dos["creature_type"].startswith("dropped:")
    assert not curse_c64["turn_class"].startswith("dropped:")
    assert not curse_dos["turn_class"].startswith("dropped:")

    # Silver Blades neither reads nor writes either byte.
    silver = c64_codec.read(source, game=c64_port.SECRET_OF_THE_SILVER_BLADES)
    assert "turn_class" not in silver
    for name in ("creature_type", "turn_class"):
        assert c64_codec.field_disposition(
            c64_port.SECRET_OF_THE_SILVER_BLADES)[name].startswith("dropped:")
        assert dos_codec.write_field_disposition(
            dos_port.SECRET_OF_THE_SILVER_BLADES)[name].startswith("dropped:")
    for name in ("creature_type", "turn_class"):
        assert amiga_pod.pod_write_field_disposition()[name].startswith(
            "dropped:")
        assert amiga_pod.pod_field_disposition()[name].startswith("dropped:")


_CURSE_TURN = dos_port.FIELDS_BY_NAME_FOR[
    dos_port.CURSE_OF_THE_AZURE_BONDS.key]["turn_class"].offset


def test_a_curse_turning_row_converts_between_dos_and_the_amiga():
    deltas = dos_port.CURSE_OF_THE_AZURE_BONDS
    key = "curse-of-the-azure-bonds"
    raw = bytearray(deltas.record_size)
    raw[_CURSE_TURN] = 2
    neutral_dos = dos_codec.to_neutral(
        dos_codec.DosCharacter(bytes(raw), deltas=deltas))
    assert neutral_dos.get("turn_class") == 2

    amiga, report = amiga_later.write_later(neutral_dos, key)
    amiga_offset = amiga_port.CURSE_DELTAS.offset(_CURSE_TURN)
    assert amiga.raw[amiga_offset] == 2
    assert not any(line.startswith("turn_class") for line in report.dropped)
    back = amiga_later.to_neutral_later(amiga)
    assert back.get("turn_class") == 2

    dos, _i, _s, report = dos_codec.write(back, deltas=deltas)
    assert dos[_CURSE_TURN] == 2
    assert not any(line.startswith("turn_class") for line in report.dropped)


def test_a_curse_turning_row_survives_a_round_trip_through_the_c64():
    deltas = dos_port.CURSE_OF_THE_AZURE_BONDS
    raw = bytearray(deltas.record_size)
    raw[_CURSE_TURN] = 2
    neutral_dos = dos_codec.to_neutral(
        dos_codec.DosCharacter(bytes(raw), deltas=deltas))

    c64, report = c64_codec.write(neutral_dos)
    assert c64.get("turn_class") == 2
    assert not any(line.startswith("turn_class") for line in report.dropped)

    dos, _i, _s, _r = dos_codec.write(c64_codec.read(
        c64, game=c64_port.CURSE_OF_THE_AZURE_BONDS), deltas=deltas)
    assert dos[_CURSE_TURN] == 2


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


def test_engine_written_zombie_fields_read_and_convert_with_node32():
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

    assert zombie.get("status") == "animated"
    assert control.get("status") == "dead"
    record, _itm, spc, dos_report = dos_codec.write(zombie)
    assert not dos_report.losses
    assert not any("innate_effects 32" in line for line in dos_report.dropped)
    status = dos_port.FIELDS_BY_NAME["field_10c_10f"].offset
    assert tuple(record[status:status + 4]) == (1, 1, 0, 1)
    assert bytes(spc).count(bytes((32, 0, 0, 5, 1))) == 1
    assert (record[0x09F], record[0x076]) == (4, 2)
    field = dos_port.FIELDS_BY_NAME["field_83_87"].offset
    assert (record[field + 1], record[field + 2]) == (0xB3, 1)
    _record, _itm, _spc, amiga_report = amiga_por.write_por(zombie)
    assert not amiga_report.losses
    assert not any("innate_effects 32" in line for line in amiga_report.dropped)


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
             [bytes((32, 0, 0, 5, 1)),
              bytes((effects.CHARM_ID, 0, 0, 0x21, 1))], "built here")
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


def test_an_animated_pool_character_with_no_node_reports_the_missing_row():
    char = _dos_zombie(0, 0xB3, None)
    char.set("granted_effects", [], "built here")
    payload = bytearray(0x1C00)
    rec, rep = c64_codec.write(char, payload=payload, party_slot=4,
                               clock_minutes=0)
    assert rec.get("roster_in_use") == 0x03
    assert not _rows(payload, 32)
    assert any("no Animate Dead node" in line for line in rep.losses)


def test_a_full_effect_table_keeps_the_trait_slot_and_reports_the_lost_row():
    payload = bytearray(0x1C00)
    for slot in range(effects.EFFECT_SLOTS):
        effects.write_effect(payload, slot, 1, 9, 5, 1)
    rec, rep = c64_codec.write(_dos_zombie(0, 0xB3, None), payload=payload,
                               party_slot=4, clock_minutes=0)
    assert rec.get("item_effects")[9] == 32
    assert not _rows(payload, 32)
    assert any("Animate Dead row is not written" in line
               for line in rep.losses)


@pytest.mark.parametrize("charm", [0x21, 0x20, 0x61, 0x60])
def test_a_charmed_zombie_is_not_refused_for_the_charms_side(charm):
    char = _dos_zombie(0, 0xB3, None)
    char.set("granted_effects",
             [bytes((32, 0, 0, 5, 1)),
              bytes((effects.CHARM_ID, 0, 0, charm, 1))], "built here")
    _rec, rep = c64_codec.write(char, payload=bytearray(0x1C00),
                                party_slot=2, clock_minutes=0)
    assert not rep.losses


def test_a_pool_death_with_bit_seven_set_still_reads_dead():
    char = c64_codec.read(_pool_c64(0xFF, 0x83),
                          game=c64_port.POOL_OF_RADIANCE)
    assert char.get("status") == "dead"


def test_a_curse_roster_status_of_three_still_reads_dead():
    char = c64_codec.read(_pool_c64(0xFF, 0x03),
                          game=c64_port.CURSE_OF_THE_AZURE_BONDS)
    assert char.get("status") == "dead"


def _zombie_source(magnitude, side=1, row=True):
    rec = _pool_c64(0xFE, 0x03)
    rec.set("combat_side", side)
    slots = bytearray(rec.get_raw("item_effects"))
    slots[9] = 32
    rec.set("item_effects", bytes(slots))
    payload = bytearray(0x1C00)
    if row:
        effects.write_effect(payload, 3, 32, 4, 0, magnitude)
    return rec, payload


@pytest.mark.parametrize("side", [0, 1])
def test_a_c64_zombie_row_becomes_the_node_dos_writes_with_flag_one(side):
    rec, payload = _zombie_source(0xF5, side)
    char = c64_codec.read(rec, game=c64_port.POOL_OF_RADIANCE,
                          payload=bytes(payload), party_slot=4)
    assert 32 not in char.get("innate_effects")
    assert char.get("granted_effects") == [bytes((32, 0, 0, side << 4 | 15, 1))]
    _dos, _itm, spc, report = dos_codec.write(char)
    assert bytes((32, 0, 0, side << 4 | 15, 1)) in bytes(spc)
    assert not any("innate_effects 32" in line for line in report.dropped)


@pytest.mark.parametrize("magnitude, row", [(0xFF, True), (0, False)])
def test_a_c64_zombie_with_no_row_value_to_convert_still_refuses(
        magnitude, row):
    rec, payload = _zombie_source(magnitude, row=row)
    char = c64_codec.read(rec, game=c64_port.POOL_OF_RADIANCE,
                          payload=bytes(payload), party_slot=4)
    assert 32 in char.get("innate_effects")
    _dos, _itm, _spc, report = dos_codec.write(char)
    assert any("innate_effects 32 (Animate Dead)" in line
               for line in report.dropped)


@pytest.mark.parametrize("status", [0x0B, 0x13, 0x23, 0x43, 0x7B, 0x83])
def test_a_pool_status_with_bits_three_to_six_set_is_not_a_zombie(status):
    char = c64_codec.read(_pool_c64(0xFF, status),
                          game=c64_port.POOL_OF_RADIANCE)
    assert char.get("status") == "dead"


@pytest.mark.parametrize("level, stored", [(9, 9), (15, 15), (16, 15),
                                           (20, 15)])
def test_a_caster_level_past_the_node_nibble_is_clamped_not_wrapped(
        level, stored):
    rec, payload = _zombie_source(level)
    char = c64_codec.read(rec, game=c64_port.POOL_OF_RADIANCE,
                          payload=bytes(payload), party_slot=4)
    assert char.get("granted_effects") == [bytes((32, 0, 0, 16 | stored, 1))]


def test_a_c64_zombie_survives_the_round_trip_through_dos():
    rec, payload = _zombie_source(5)
    char = c64_codec.read(rec, game=c64_port.POOL_OF_RADIANCE,
                          payload=bytes(payload), party_slot=4)
    dos, _itm, spc, dos_rep = dos_codec.write(char)
    assert not dos_rep.losses
    assert not [line for line in dos_rep.dropped
                if "Animate" in line or "innate_effects" in line]
    nodes = bytes(spc)
    assert nodes.count(bytes((32, 0, 0, 0x15, 1))) == 1
    dos_char = dos_codec.DosCharacter(
        dos, effects=[nodes[i:i + 9] for i in range(0, len(nodes), 9)])
    back_char = dos_codec.to_neutral(dos_char)
    assert back_char.get("status") == "animated"

    out_payload = bytearray(0x1C00)
    back, rep = c64_codec.write(back_char, payload=out_payload, party_slot=4,
                                clock_minutes=0)
    assert back.get("roster_in_use") == 0x03
    assert back.get("flags_0b8") == 0xFE
    rows = [r for r in effects.active_effects(bytes(out_payload))
            if r.id == 32]
    assert len(rows) == 1
    assert (rows[0].owner, rows[0].duration, rows[0].magnitude) == (4, 0, 5)
    assert not rep.losses
    assert not [line for line in rep.dropped
                if "Animate" in line or "innate_effects" in line]


@pytest.mark.parametrize("deltas", (
    dos_port.POOL_OF_RADIANCE,
    dos_port.CURSE_OF_THE_AZURE_BONDS,
    dos_port.SECRET_OF_THE_SILVER_BLADES,
    dos_port.POOLS_OF_DARKNESS,
), ids=lambda deltas: deltas.key)
def test_every_dos_account_of_turn_class_follows_the_one_gate(deltas):
    measured = "turn_class" in dict(c64_codec.undead_direct(deltas.key))
    read = dos_codec.field_disposition(deltas)["turn_class"]
    write = dos_codec.write_field_disposition(deltas)["turn_class"]
    target = dos_codec.write_targets(deltas)["turn_class"]
    assert (not read.startswith("dropped:")) is measured
    assert (not write.startswith("dropped:")) is measured
    assert target.startswith("from neutral") is measured


# --- Animate Dead's marker on a raised, living character --------------------
#
# The temple raise leaves trait slot 9 = 32 and a never-expiring id-32 row on a
# character who is no longer a zombie.  It is recorded as accounted for
# (`c64_codec.READ_INERT`), so it converts to no node 32 in either port.

_RAISED = "por-700-raised-zombie-c64-save"
_RAISED_CONTROL = "por-700-raised-control-c64-save"
_DOS_WORDS = ("field_10c_10f", "field_83_87")


def _raised_party(name):
    from editor import convert
    from tools.registry import specimens

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
    return {char.get("name"): char for char in chars}["BRUTUS"]


def _only_art_tables(dropped):
    """No drop but the portrait and combat figure, which a test with no
    creation-disk tables to hand cannot convert for any C64 character."""
    return all(line.startswith(("portrait_", "Combat figure", "icon_"))
               or "creation menu" in line for line in dropped)


def _nodes(spc):
    data = bytes(spc)
    return [data[i:i + 9] for i in range(0, len(data), 9)]


def _living_fields(record, at=lambda offset: offset):
    """The bytes the raised character's sheet turns on, keyed by DOS offset."""
    status = dos_port.FIELDS_BY_NAME["field_10c_10f"].offset
    ctl = dos_port.FIELDS_BY_NAME["field_83_87"].offset
    return {
        "status": tuple(record[at(status + n)] for n in (0, 1, 3)),
        "control": record[at(ctl + 1)],
        "creature_type": record[at(0x09F)],
        "turn_class": record[at(0x076)],
        "movement": record[at(0x072)],
    }


def test_a_raised_zombie_converts_to_dos_and_the_amiga_with_no_node_32():
    char = _raised_party(_RAISED)
    assert char.get("status") == "okay"
    assert 32 not in char.get("innate_effects")
    assert not char.get("granted_effects")
    dos, _itm, spc, report = dos_codec.write(char)
    assert report.losses == [] and _only_art_tables(report.dropped)
    assert _living_fields(dos) == {
        "status": (0, 1, 1), "control": 0, "creature_type": 0,
        "turn_class": 2, "movement": 12}
    assert 32 not in [n[0] for n in _nodes(spc)]
    amiga, _itm, aspc, areport = amiga_por.write_por(char)
    assert areport.losses == [] and _only_art_tables(areport.dropped)
    assert _living_fields(amiga, amiga_por.amiga_por_offset) \
        == _living_fields(dos)
    assert bytes((32, 0, 0)) not in bytes(aspc)


def test_a_raised_control_converts_to_the_same_bytes_but_no_quickfight():
    zombie, control = _raised_party(_RAISED), _raised_party(_RAISED_CONTROL)
    z_dos, *_ = dos_codec.write(zombie)
    c_dos, _itm, spc, report = dos_codec.write(control)
    assert report.losses == [] and _only_art_tables(report.dropped)
    assert 32 not in [n[0] for n in _nodes(spc)]
    quick = dos_port.FIELDS_BY_NAME["field_10c_10f"].offset + 3
    assert (z_dos[quick], z_dos[0x076]) == (1, 2)
    assert (c_dos[quick], c_dos[0x076]) == (0, 0)
    # The two saves were staged differently (gold, constitution), so only the
    # living-character fields are compared, not the whole record.
    assert {**_living_fields(z_dos), "turn_class": 0, "status": (0, 1, 0)} \
        == _living_fields(c_dos)


def _residue(status, *, trait=1, row=True, second_trait=False):
    rec = _pool_c64(0x00, status)
    slots = bytearray(rec.get_raw("item_effects"))
    if trait:
        slots[9] = 32
    if second_trait:
        slots[8] = 32
    rec.set("item_effects", bytes(slots))
    payload = bytearray(0x1C00)
    if row:
        effects.write_effect(payload, 63, 32, 4, 0, 5)
    return rec, bytes(payload)


_FORMS = {
    "trait and row": {},
    "trait only": {"row": False},
    "row only": {"trait": 0},
    "two traits and row": {"second_trait": True},
    "two traits only": {"second_trait": True, "row": False},
}


@pytest.mark.parametrize("status", [0x01, 0x83])
@pytest.mark.parametrize("form", _FORMS)
def test_animate_dead_residue_on_a_pool_character_who_is_not_a_zombie_gives_no_32(
        form, status):
    rec, payload = _residue(status, **_FORMS[form])
    char = c64_codec.read(rec, game=c64_port.POOL_OF_RADIANCE,
                          payload=payload, party_slot=4)
    assert 32 not in (char.get("innate_effects") or [])
    assert not char.get("granted_effects")
    assert not any("32" in line for line in char.dropped), char.dropped
    dos, _itm, spc, report = dos_codec.write(char)
    assert not any("innate_effects" in line for line in report.dropped)
    assert 32 not in [n[0] for n in _nodes(spc)]


@pytest.mark.parametrize("form", ["trait and row", "trait only", "row only"])
def test_the_same_residue_on_a_zombie_still_gives_the_node(form):
    rec, payload = _residue(0x03, **_FORMS[form])
    rec.set("flags_0b8", 0xFE)
    rec.set("combat_side", 0)
    char = c64_codec.read(rec, game=c64_port.POOL_OF_RADIANCE,
                          payload=payload, party_slot=4)
    if form == "trait only":
        # No row means no caster level to convert, so it still refuses.
        assert 32 in char.get("innate_effects")
        return
    assert char.get("granted_effects") == [bytes((32, 0, 0, 5, 1))]
    assert 32 not in char.get("innate_effects")


def test_a_curse_record_holding_trait_32_is_left_alone():
    rec = CharacterRecord.blank()
    slots = bytearray(rec.get_raw("item_effects"))
    slots[9] = 32
    rec.set("item_effects", bytes(slots))
    char = c64_codec.read(rec, game=c64_port.CURSE_OF_THE_AZURE_BONDS)
    assert 32 in char.get("innate_effects")


def test_the_inert_entry_is_declared_and_is_not_a_drop():
    names = {name for name, *_ in c64_codec.READ_INERT}
    assert names == {"animate_dead_marker"}
    assert names.isdisjoint(dict(c64_codec.READ_DROPPED))
    assert names.isdisjoint({n for n, *_ in c64_codec.READ_DERIVED})
    for _name, why, evidence in c64_codec.READ_INERT:
        assert why and evidence


def test_trait_32_is_kept_when_the_roster_status_is_not_stored():
    rec, payload = _residue(0x03)
    slot = CharacterRecord(rec.to_bytes(), stored_size=256)
    assert not slot.is_stored("roster_in_use")
    char = c64_codec.read(slot, game=c64_port.POOL_OF_RADIANCE)
    assert 32 in char.get("innate_effects")


@pytest.mark.parametrize("trait", [1, 0])
def test_a_running_id_32_row_keeps_the_trait_beside_it(trait):
    rec, _payload = _residue(0x01, trait=trait, row=False)
    payload = bytearray(0x1C00)
    effects.write_effect(payload, 3, 32, 4, 60, 5)
    char = c64_codec.read(rec, game=c64_port.POOL_OF_RADIANCE,
                          payload=bytes(payload), party_slot=4)
    assert (32 in char.get("innate_effects")) == bool(trait)


@pytest.mark.parametrize("second_trait", [False, True])
def test_a_raised_character_round_trips_c64_dos_c64_keeping_his_behaviour(
        second_trait):
    assert set(c64_codec.INERT_MARKER_IDS) == {n for n, *_ in
                                               c64_codec.READ_INERT}
    rec, payload = _residue(0x01, second_trait=second_trait)
    # What Animate Dead leaves beside the marker.
    rec.set("turn_class", 2)
    char = c64_codec.read(rec, game=c64_port.POOL_OF_RADIANCE,
                          payload=payload, party_slot=4)
    dos, _itm, spc, report = dos_codec.write(char)
    assert report.losses == [] and _only_art_tables(report.dropped)
    dos_char = dos_codec.DosCharacter(dos, effects=_nodes(spc))
    back_payload = bytearray(0x1C00)
    back, rep = c64_codec.write(dos_codec.to_neutral(dos_char),
                                payload=back_payload, party_slot=4,
                                clock_minutes=0)
    assert not rep.losses
    # The living status, side, computer control and turning row are stored
    # apart from the marker and come back.
    for name in ("roster_in_use", "flags_0b8", "combat_side", "turn_class",
                 "creature_type"):
        assert back.get(name) == rec.get(name), name
    # The marker is not rebuilt from the turning row: DOS and the Amiga hold
    # no state for it, and a guessed one would put back what the C64 had
    # already cleared.
    assert 32 not in bytes(back.get_raw("item_effects"))
    assert not [r for r in effects.active_effects(bytes(back_payload))
                if r.id == 32]
    assert not [w for w in rep.warnings if "32" in w]
