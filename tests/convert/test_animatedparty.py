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


def test_curse_maps_creature_type_and_turning_row_but_later_titles_do_not():
    source = CharacterRecord.blank()
    source.set("creature_type", 4)
    source.set("turn_class", 2)
    later = c64_codec.read(source, game=c64_port.CURSE_OF_THE_AZURE_BONDS)
    assert later.get("creature_type") == 4
    assert later.get("turn_class") == 2

    raw = bytearray(dos_port.CURSE_OF_THE_AZURE_BONDS.record_size)
    raw[_CURSE_TURN] = 2
    raw[0x11A] = 4
    later = dos_codec.to_neutral(dos_codec.DosCharacter(
        bytes(raw), deltas=dos_port.CURSE_OF_THE_AZURE_BONDS))
    assert later.get("creature_type") == 4
    assert later.get("turn_class") == 2

    curse_c64 = c64_codec.field_disposition(c64_port.CURSE_OF_THE_AZURE_BONDS)
    curse_dos = dos_codec.write_field_disposition(
        dos_port.CURSE_OF_THE_AZURE_BONDS)
    assert not curse_c64["creature_type"].startswith("dropped:")
    assert not curse_dos["creature_type"].startswith("dropped:")
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


def test_a_curse_companion_type_and_turning_row_convert_between_dos_and_amiga():
    deltas = dos_port.CURSE_OF_THE_AZURE_BONDS
    key = "curse-of-the-azure-bonds"
    raw = bytearray(deltas.record_size)
    raw[_CURSE_TURN] = 2
    raw[0xF7] = 0xB2
    raw[0x11A] = 4
    raw[0x11B] = 0x5A
    neutral_dos = dos_codec.to_neutral(
        dos_codec.DosCharacter(bytes(raw), deltas=deltas))
    assert (neutral_dos.get("npc_control_byte"),
            neutral_dos.get("creature_type"),
            neutral_dos.get("turn_class")) == (0xB2, 4, 2)

    amiga, report = amiga_later.write_later(neutral_dos, key)
    amiga_offset = amiga_port.CURSE_DELTAS.offset(_CURSE_TURN)
    assert (amiga.raw[amiga_port.CURSE_DELTAS.offset(0xF7)],
            amiga.raw[amiga_port.CURSE_DELTAS.offset(0x11A)],
            amiga.raw[amiga_port.CURSE_DELTAS.offset(0x11B)],
            amiga.raw[amiga_offset]) == (0xB2, 4, 0x5A, 2)
    assert not any(line.startswith(("creature_type", "turn_class"))
                   for line in report.dropped)
    back = amiga_later.to_neutral_later(amiga)
    assert (back.get("npc_control_byte"), back.get("creature_type"),
            back.get("turn_class")) == (0xB2, 4, 2)

    dos, _i, _s, report = dos_codec.write(back, deltas=deltas)
    assert (dos[0xF7], dos[0x11A], dos[0x11B], dos[_CURSE_TURN]) == (
        0xB2, 4, 0x5A, 2)
    assert not any(line.startswith(("creature_type", "turn_class"))
                   for line in report.dropped)


def test_a_curse_companion_type_and_turning_row_cross_the_c64():
    deltas = dos_port.CURSE_OF_THE_AZURE_BONDS
    raw = bytearray(deltas.record_size)
    raw[_CURSE_TURN] = 2
    raw[0xF7] = 0xB2
    raw[0x11A] = 4
    neutral_dos = dos_codec.to_neutral(
        dos_codec.DosCharacter(bytes(raw), deltas=deltas))

    c64, report = c64_codec.write(neutral_dos)
    assert (c64.get("flags_0b8"), c64.get("creature_type"),
            c64.get("turn_class")) == (0xB2, 4, 2)
    assert not any(line.startswith(("creature_type", "turn_class"))
                   for line in report.dropped)

    dos, _i, _s, _r = dos_codec.write(c64_codec.read(
        c64, game=c64_port.CURSE_OF_THE_AZURE_BONDS), deltas=deltas)
    assert (dos[0xF7], dos[0x11A], dos[_CURSE_TURN]) == (0xB2, 4, 2)


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
        game = c64_save.container_for(c64_port.POOL_OF_RADIANCE)
        slots = SaveGame0.from_bytes(source.save0, game).characters
        # The raw read: this test checks the codec's zombie form, which
        # `c64_party` no longer returns.
        chars = [dos_codec.c64_member_neutral(
                     source.save0, source.save1, c64_port.POOL_OF_RADIANCE,
                     slot.index) for slot in slots]
        raw = {slot.record.name: slot.record_bytes for slot in slots}
        return {char.get("name"): char for char in chars}, raw

    animated, animated_raw = party("por-700-animate-dead-c64")
    ordinary, plain_raw = party("por-700-animate-control-c64")
    zombie, control = animated["BRUTUS"], ordinary["BRUTUS"]
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
    # which is noted on the warnings and does not block the save.
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
def test_a_charmed_zombie_is_not_blocked_for_the_charms_side(charm):
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


@pytest.mark.parametrize("game, status", [
    (c64_port.CURSE_OF_THE_AZURE_BONDS, "animated"),
    (c64_port.SECRET_OF_THE_SILVER_BLADES, "dead"),
])
def test_a_later_roster_status_of_three_reads_as_its_engine_runs_it(
        game, status):
    char = c64_codec.read(_pool_c64(0xFF, 0x03), game=game)
    assert char.get("status") == status


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


def test_a_c64_zombie_row_of_ff_has_no_value_to_convert_and_still_blocks():
    rec, payload = _zombie_source(0xFF)
    char = c64_codec.read(rec, game=c64_port.POOL_OF_RADIANCE,
                          payload=bytes(payload), party_slot=4)
    assert 32 in char.get("innate_effects")
    _dos, _itm, _spc, report = dos_codec.write(char)
    assert any("innate_effects 32 (Animate Dead)" in line
               for line in report.dropped)


_DISPELLED = "por-700-dispel-78a7f747a5-dispel-observed-b"
_ANIMATED = "por-700-animate-dead-c64"


def _c64_image(name):
    from test_convertmatrix import _c64_specimen

    path = _c64_specimen(name)
    if path is None:
        pytest.skip(f"needs specimen WISH-SPEC-{name}.D64")
    return path


def _brutus(path):
    """`(game, save0, save1, slot)` for BRUTUS on a C64 disk image."""
    from goldbox.d64 import D64
    from goldbox.savegame import load_save

    game, sg0, sg1 = load_save(D64.open(str(path)))
    (slot,) = [s for s in sg0.characters if s.record.get("name") == "BRUTUS"]
    return (game, sg0.to_bytes(), sg1.to_bytes() if sg1 is not None else None,
            slot)


def _save_as(tmp_path, name, port):
    """Save As of specimen `name` to `port`: `(plan, party)`, the plan
    already checked to drop and lose nothing."""
    from editor import convert, roster, saveplan
    from tools.convert import convertdrops
    from tools.dos import dosbox

    party = roster.Party(str(_c64_image(name)))
    source = party.source or convert.Source.detect(party.path)
    try:
        if port == "dos":
            assets = saveplan.resolve_assets(
                source, "dos", game_files=convertdrops.game_files,
                dos_folder=dosbox.find_game("POOLRAD"))
            where = tmp_path / "dos-out"
        else:
            amiga = convertdrops.amiga_game_disks(tmp_path).get(
                c64_port.POOL_OF_RADIANCE.key)
            if amiga is None:
                pytest.skip("needs Pool of Radiance's own Amiga game disk")
            assets = saveplan.resolve_assets(
                source, "amiga", game_files=convertdrops.game_files,
                amiga_disk=amiga)
            where = tmp_path / "out.adf"
    except FileNotFoundError:
        pytest.skip("needs the DOS Pool of Radiance archives ($FR_ARCHIVES)")
    except saveplan.MissingAssets:
        pytest.skip("needs Pool of Radiance's own C64 disks")
    plan = saveplan.prepare_save_as(party, port, where, assets)
    assert plan.report.dropped == [] and saveplan.losses(plan.report) == []
    return plan, party


def _dos_brutus(plan):
    """BRUTUS's `.SAV` bytes and his `.SPC` bytes (`b""` when absent)."""
    (name,) = [n for n, d in plan.files.items()
               if n.endswith(".SAV") and d[1:7] == b"BRUTUS"]
    return plan.files[name], plan.files.get(name[:-4] + ".SPC", b"")


def _amiga_brutus(plan):
    from goldbox import amiga_savegame
    from goldbox.amiga_adf import AmigaDisk

    (image,) = plan.files
    disk = AmigaDisk(bytearray(plan.files[image]))
    drawer = amiga_savegame.por_save_drawer(disk)
    (char,) = [c for c in amiga_savegame.read_por_characters(disk, "A", drawer)
               if c.name == "BRUTUS"]
    return char


def _check_dos_living(record, spc):
    assert record[0x10C:0x110] == bytes((0, 1, 0, 0))
    assert record[0x11B] >= 1
    assert (record[0x6B], record[0x72], record[0x76], record[0x84],
            record[0x9F]) == (1, 12, 0, 0, 0)
    assert 32 not in [spc[i] for i in range(0, len(spc), 9)]


def _check_amiga_living(raw):
    assert raw[0x10E:0x112] == bytes((0, 1, 0, 0))
    assert raw[0x11D] >= 1
    assert (raw[0x6B], raw[0x72], raw[0x76], raw[0x85], raw[0xA1]) == (
        1, 12, 0, 0, 0)


def test_a_dispelled_zombie_save_converts_to_a_living_dos_character(
        tmp_path):
    plan, _party = _save_as(tmp_path, _DISPELLED, "dos")
    record, spc = _dos_brutus(plan)
    _check_dos_living(record, spc)


def test_a_dispelled_zombie_save_converts_to_a_living_amiga_character(
        tmp_path):
    plan, _party = _save_as(tmp_path, _DISPELLED, "amiga")
    char = _amiga_brutus(plan)
    _check_amiga_living(char.raw)
    assert 32 not in [bytes(n)[0] for n in char.effects]


def test_the_combat_cast_zombie_form_converts_to_a_living_character():
    """Dispel in combat leaves no trait and no row; he converts the same."""
    game, save0, save1, slot = _brutus(_c64_image(_DISPELLED))
    save0 = bytearray(save0)
    at = c64_save.container_for(game).slot(slot.index) + 0x0AD + 9
    assert save0[at] == 0x20
    save0[at] = 0
    party, _icons = dos_codec.c64_party(bytes(save0), save1, game)
    (char,) = [c for c in party if c.get("name") == "BRUTUS"]
    record, _itm, spc, _rep = dos_codec.write(char)
    _check_dos_living(record, bytes(spc))
    amiga, _itm, amiga_spc, _rep = amiga_por.write_por(char)
    _check_amiga_living(amiga)
    assert 32 not in [bytes(amiga_spc)[i] for i in range(0, len(amiga_spc), 9)]


def test_a_zombie_with_no_roster_block_converts_living():
    """With no `SAVEDGAME1` the status stored in the record is read, as
    `read` reads it. A real save slot stores 256 bytes, which end before
    `roster_in_use`, so only a full-size record reaches this."""
    import types

    game = c64_save.container_for(c64_port.POOL_OF_RADIANCE)
    rec, payload = _zombie_source(0, row=False)
    slot = types.SimpleNamespace(index=4, record=rec)
    raw = dos_codec._read_c64_slot(slot, None, game, bytes(payload), 0)
    assert raw.get("status") == "animated"
    char = c64_codec.living_player(raw)
    assert char.get("status") == "okay"
    assert char.get("hp_current") == 1
    assert not char.get("granted_effects")


def test_the_roster_status_falls_back_to_the_stored_record_byte():
    rec = _pool_c64(0xFE, 0x03)
    assert c64_codec.roster_status(rec, None) == 0x03


def test_a_zombie_with_his_animate_dead_row_converts_living(tmp_path):
    plan, _party = _save_as(tmp_path, _ANIMATED, "dos")
    record, spc = _dos_brutus(plan)
    _check_dos_living(record, spc)
    assert spc == b""


def test_a_zombie_row_of_any_magnitude_reads_as_a_zombie_and_converts_living():
    game, save0, save1, slot = _brutus(_c64_image(_ANIMATED))
    save0 = bytearray(save0)
    (row,) = [r for r in effects.active_effects(bytes(save0))
              if r.id == 32 and r.owner == slot.index]
    save0[effects.EFFECT_MAGNITUDE_OFFSET + row.slot] = 0xD1
    raw = dos_codec.c64_member_neutral(bytes(save0), save1, game, slot.index)
    assert raw.get("status") == "animated"
    assert [bytes(n) for n in raw.get("granted_effects")] == [
        bytes.fromhex("2000000F01")]
    party, _icons = dos_codec.c64_party(bytes(save0), save1, game)
    (char,) = [c for c in party if c.get("name") == "BRUTUS"]
    assert char.get("status") == "okay"
    assert not char.get("granted_effects")


def _return_trip(tmp_path, plan, port):
    """Save As of the converted output back to the C64: `(game, save0, save1,
    slot)` for BRUTUS."""
    from editor import convert, roster, saveplan
    from tools.convert import convertdrops

    if port == "dos":
        where = tmp_path / "dos-back"
        where.mkdir()
        for name, data in plan.files.items():
            (where / name).write_bytes(data)
    else:
        (image,) = plan.files
        where = tmp_path / "back.adf"
        where.write_bytes(plan.files[image])
    back = roster.Party(str(where))
    source = back.source or convert.Source.detect(back.path)
    assets = saveplan.resolve_assets(source, "c64",
                                     game_files=convertdrops.game_files)
    again = saveplan.prepare_save_as(back, "c64", tmp_path / "out.d64", assets)
    (image,) = again.files
    out = tmp_path / "read-back.d64"
    out.write_bytes(again.files[image])
    return _brutus(out)


@pytest.mark.parametrize("port", ["dos", "amiga"])
def test_a_dispelled_zombie_comes_back_to_the_c64_living(
        tmp_path, port):
    plan, _party = _save_as(tmp_path, _DISPELLED, port)
    game, save0, save1, slot = _return_trip(tmp_path, plan, port)
    sg1 = dos_codec._c64_save_context(save0, save1,
                                      c64_save.container_for(game))[1]
    assert sg1.roster(slot.index).roster_in_use == 0x01
    assert slot.record.get("flags_0b8") < 0x80
    assert bytes(slot.record.get_raw("item_effects"))[9] == 0
    assert not [r for r in effects.active_effects(save0)
                if r.owner == slot.index and r.id == 32]


@pytest.mark.parametrize("port", ["dos", "amiga"])
def test_a_zombie_with_his_row_comes_back_to_the_c64_living_with_no_row(
        tmp_path, port):
    plan, _party = _save_as(tmp_path, _ANIMATED, port)
    game, save0, save1, slot = _return_trip(tmp_path, plan, port)
    sg1 = dos_codec._c64_save_context(save0, save1,
                                      c64_save.container_for(game))[1]
    assert sg1.roster(slot.index).roster_in_use == 0x01
    assert slot.record.get("flags_0b8") < 0x80
    assert bytes(slot.record.get_raw("item_effects"))[9] == 0
    assert not [r for r in effects.active_effects(save0)
                if r.owner == slot.index and r.id == 32]


def test_a_dispelled_zombie_save_converts_to_the_c64_unchanged(tmp_path):
    from editor import convert, roster, saveplan
    from tools.convert import convertdrops

    disk = _c64_image(_DISPELLED)
    party = roster.Party(str(disk))
    source = party.source or convert.Source.detect(party.path)
    try:
        assets = saveplan.resolve_assets(
            source, "c64", game_files=convertdrops.game_files)
    except saveplan.MissingAssets:
        pytest.skip("needs Pool of Radiance's own C64 disks")
    plan = saveplan.prepare_save_as(party, "c64", tmp_path / "out.d64", assets)
    (image,) = plan.files
    assert plan.files[image] == disk.read_bytes()
    game, save0, save1, slot = _brutus(disk)
    block = dos_codec._c64_save_context(
        save0, save1, c64_save.container_for(game))[1].roster(slot.index)
    char = c64_codec.read(slot.record, roster=block, game=game,
                          payload=save0, party_slot=slot.index)
    assert char.get("status") == "animated"
    assert [type(n) for n in char.get("granted_effects")] == [
        c64_codec.DispelledZombieNode]


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
    # A dispelled zombie has no row and so no caster level; `read` gives the
    # level-15 node, the form the C64 writer needs.
    level = 15 if form == "trait only" else 5
    assert char.get("granted_effects") == [bytes((32, 0, 0, level, 1))]
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


def _round_trip_to_c64(rec, payload):
    char = c64_codec.read(rec, game=c64_port.POOL_OF_RADIANCE,
                          payload=bytes(payload), party_slot=4)
    dos, _itm, spc, _rep = dos_codec.write(char)
    dos_char = dos_codec.DosCharacter(dos, effects=_nodes(spc))
    out = bytearray(0x1C00)
    back, rep = c64_codec.write(dos_codec.to_neutral(dos_char), payload=out,
                                party_slot=4, clock_minutes=0)
    return back, out, rep


def _direct_to_c64(rec, payload):
    char = c64_codec.read(rec, game=c64_port.POOL_OF_RADIANCE,
                          payload=bytes(payload), party_slot=4)
    out = bytearray(0x1C00)
    back, rep = c64_codec.write(char, payload=out, party_slot=4,
                                clock_minutes=0)
    return back, out, rep


@pytest.mark.parametrize("side", [0, 1])
def test_a_dispelled_c64_zombie_comes_back_with_no_row_and_the_trait(side):
    rec, payload = _zombie_source(0, side, row=False)
    back, out, rep = _direct_to_c64(rec, payload)
    assert not [r for r in effects.active_effects(bytes(out)) if r.id == 32]
    assert bytes(back.get_raw("item_effects"))[9] == 32
    assert back.get("combat_side") == rec.get("combat_side")
    assert back.get("flags_0b8") == rec.get("flags_0b8")
    assert not rep.losses


@pytest.mark.parametrize("level", [0, 14, 5])
def test_any_other_id_32_node_still_writes_its_row(level):
    rec, payload = _zombie_source(level)
    _back, out, _rep = _round_trip_to_c64(rec, payload)
    rows = [r for r in effects.active_effects(bytes(out)) if r.id == 32]
    assert [r.magnitude for r in rows] == [level]


@pytest.mark.parametrize("magnitude", [15, 0xF5])
def test_a_c64_zombie_row_of_magnitude_fifteen_or_more_keeps_its_row(
        magnitude):
    rec, payload = _zombie_source(magnitude)
    _back, out, _rep = _round_trip_to_c64(rec, payload)
    rows = [r for r in effects.active_effects(bytes(out)) if r.id == 32]
    assert [r.magnitude for r in rows] == [15]


# --- One policy: every zombie player character converts living ---------------

_ORDINARY_DEAD = "por-700-animate-control-c64"


def _forms_party(form, companion=False):
    """BRUTUS on the zombie specimen, edited into one of the five C64 zombie
    forms: `(game, save0, save1, slot)`. A companion has the NPC control byte
    `$B2` in 0x0B8 where a player character has `$FE` or above."""
    game, save0, save1, slot = _brutus(_c64_image(_ANIMATED))
    save0 = bytearray(save0)
    base = c64_save.container_for(game).slot(slot.index)
    (row,) = [r for r in effects.active_effects(bytes(save0))
              if r.id == 32 and r.owner == slot.index]
    magnitude = {"row5": 5, "rowD1": 0xD1, "rowFF": 0xFF}.get(form)
    if magnitude is not None:
        save0[effects.EFFECT_MAGNITUDE_OFFSET + row.slot] = magnitude
    else:
        save0[effects.EFFECT_ID_OFFSET + row.slot] = 0
    if form == "neither":
        save0[base + 0x0AD + 9] = 0
    if companion:
        save0[base + 0x0B8] = 0xB2
    return game, bytes(save0), save1, slot


_ZOMBIE_FORMS = ["row5", "rowD1", "rowFF", "trait_only", "neither"]


def _form_character(form, companion=False):
    game, save0, save1, slot = _forms_party(form, companion)
    party, _icons = dos_codec.c64_party(save0, save1, game)
    (char,) = [c for c in party if c.get("name") == "BRUTUS"]
    return char


@pytest.mark.parametrize("form", _ZOMBIE_FORMS)
def test_every_c64_zombie_player_form_converts_living(form):
    char = _form_character(form)
    assert char.get("status") == "okay"
    assert 32 not in [bytes(n)[0] for n in char.get("granted_effects") or ()]
    record, _itm, spc, dos_report = dos_codec.write(char)
    _check_dos_living(record, bytes(spc))
    assert not dos_report.losses
    assert not any("innate_effects 32" in line for line in dos_report.dropped)
    raw, _itm, amiga_spc, amiga_report = amiga_por.write_por(char)
    _check_amiga_living(raw)
    assert not amiga_report.losses
    assert 32 not in [bytes(amiga_spc)[i]
                      for i in range(0, len(amiga_spc), 9)]


@pytest.mark.parametrize("form", _ZOMBIE_FORMS)
def test_a_zombie_npc_stays_a_zombie_npc_in_every_form(form):
    char = _form_character(form, companion=True)
    assert char.get("status") == "animated"
    assert char.get("npc_control_byte") == 0xB2
    record, _itm, _spc, _rep = dos_codec.write(char)
    assert record[0x10C] == 1
    assert record[0x84] == 0xB2


@pytest.mark.parametrize("hp, kept", [(0, 1), (7, 7)])
def test_a_zombie_player_with_no_hit_points_arrives_with_one(hp, kept):
    char = _dos_zombie(0, 0xB3, True)
    char.set("hp_current", hp, "built here")
    assert c64_codec.living_player(char).get("hp_current") == kept


def test_living_player_returns_a_zombie_npc_and_a_living_member_unchanged():
    assert c64_codec.living_player(_dos_zombie(0, 0xB2, True)) is not None
    npc = _dos_zombie(0, 0xB2, True)
    assert c64_codec.living_player(npc) is npc
    ordinary = _pool_dos_character("okay", False, 0)
    assert c64_codec.living_player(ordinary) is ordinary


def test_living_player_keeps_memorised_spells_and_other_effects():
    bless = bytes((1, 4, 0, 0x11, 0))
    for memorised in ([], [3, 5]):
        char = _dos_zombie(0, 0xB3, True)
        char.set("spells_memorised", list(memorised), "built here")
        char.set("running_effects", [bless], "built here")
        char.set("innate_effects", [0, 32], "built here")
        living = c64_codec.living_player(char)
        assert living.get("spells_memorised") == memorised
        assert [bytes(n) for n in living.get("running_effects")] == [bless]
        assert living.get("innate_effects") == [0]
        assert not living.get("granted_effects")
        assert living.get("turn_power") is None
        assert (living.get("npc"), living.get("npc_control_byte")) == (
            False, None)
        assert char.get("status") == "animated"


def test_a_charmed_zombie_player_keeps_his_charm():
    charm = bytes((effects.CHARM_ID, 0, 0, 0x21, 1))
    char = _dos_zombie(0, 0xB3, True)
    char.set("granted_effects", [bytes((32, 0, 0, 5, 1)), charm], "built here")
    living = c64_codec.living_player(char)
    assert living.get("status") == "okay"
    assert [bytes(n) for n in living.get("granted_effects")] == [charm]
    assert (living.get("npc"), living.get("npc_control_byte")) == (True, 0xB3)
    assert (living.get("hostile"), living.get("quickfight")) == (
        char.get("hostile"), char.get("quickfight"))


def _fixture_zombie(flag):
    """A fixture party member made a zombie player character, with the
    fixture payload and state to write him into."""
    import pathlib

    from goldbox import world_state
    from goldbox.savegame import SaveGame0

    fixtures = pathlib.Path(__file__).resolve().parents[1] / "fixtures"
    payload = bytearray(SaveGame0.from_prg(
        (fixtures / "savedgame0.bin").read_bytes()).to_bytes())
    state = world_state.from_c64(bytes(payload), game=c64_port.POOL_OF_RADIANCE)
    party, _ = dos_codec.c64_party(bytes(payload), None,
                                   game=c64_port.POOL_OF_RADIANCE)
    char = party[0]
    for name, value in (("status", "animated"), ("npc", True),
                        ("npc_control_byte", 0xB3), ("hp_current", 0),
                        ("treasure_share", flag)):
        char.set(name, value, "built here")
    char.set("granted_effects", [bytes((32, 0, 0, 5, 1))], "built here")
    return char, payload, state


@pytest.mark.parametrize("flag", [0, 1])
@pytest.mark.parametrize("as_dos", [False, True])
def test_a_dos_zombie_player_converts_living_to_the_c64(flag, as_dos):
    from goldbox.savegame import SaveGame0

    char, payload, state = _fixture_zombie(flag)
    zombie = char
    if as_dos:
        record, _itm, spc, _rep = dos_codec.write(char)
        zombie = dos_codec.DosCharacter(
            record, effects=[bytes(spc)[i:i + 9]
                             for i in range(0, len(spc), 9)])
        assert dos_codec.to_neutral(zombie).get("status") == "animated"
    out = bytearray(payload)
    dos_codec.write_c64_save(out, None, state, [zombie],
                             game=c64_port.POOL_OF_RADIANCE)
    game = c64_save.container_for(c64_port.POOL_OF_RADIANCE)
    (slot,) = SaveGame0.from_bytes(bytes(out), game).characters
    rec = slot.record
    assert rec.get("flags_0b8") < 0x80
    assert 32 not in rec.get_raw("item_effects")
    assert not [r for r in effects.active_effects(bytes(out)) if r.id == 32]


def test_the_ordinary_dead_control_still_converts_dead(tmp_path):
    plan, _party = _save_as(tmp_path, _ORDINARY_DEAD, "dos")
    record, _spc = _dos_brutus(plan)
    assert record[0x10C] == 6


def _prepare_save_as(path, port, tmp_path):
    """Save As of the save at `path` to `port`, checked to drop and lose
    nothing; skips when this machine lacks the destination's game files."""
    from editor import convert, roster, saveplan
    from tools.convert import convertdrops
    from tools.dos import dosbox

    party = roster.Party(str(path))
    source = party.source or convert.Source.detect(party.path)
    try:
        if port == "c64":
            assets = saveplan.resolve_assets(
                source, "c64", game_files=convertdrops.game_files)
            where = tmp_path / "out.d64"
        elif port == "dos":
            assets = saveplan.resolve_assets(
                source, "dos", game_files=convertdrops.game_files,
                dos_folder=dosbox.find_game("POOLRAD"))
            where = tmp_path / "dos-out"
        else:
            amiga = convertdrops.amiga_game_disks(tmp_path).get(
                c64_port.POOL_OF_RADIANCE.key)
            if amiga is None:
                pytest.skip("needs Pool of Radiance's own Amiga game disk")
            assets = saveplan.resolve_assets(
                source, "amiga", game_files=convertdrops.game_files,
                amiga_disk=amiga)
            where = tmp_path / "out.adf"
    except FileNotFoundError:
        pytest.skip("needs the DOS Pool of Radiance archives ($FR_ARCHIVES)")
    except saveplan.MissingAssets:
        pytest.skip("needs Pool of Radiance's own game files")
    plan = saveplan.prepare_save_as(party, port, where, assets)
    assert plan.report.dropped == [] and saveplan.losses(plan.report) == []
    return plan


def _zombie_source_path(name):
    from gamedata import specimen

    if name in (_DISPELLED, _ANIMATED):
        return _c64_image(name)
    if name == "wish-plane-303-pool-meys2tbs-gm":
        return specimen(name, "amiga") / "fetched-save.adf"
    save = "SAVGAMC.DAT" if name == "wish303-dos-l2-slotc-resave" else "SAVGAMD.DAT"
    return specimen(name) / save


@pytest.mark.parametrize("name, port", [
    (_DISPELLED, "dos"), (_DISPELLED, "amiga"),
    (_ANIMATED, "dos"), (_ANIMATED, "amiga"),
    ("pool-700-animate-dead-camp-cast-resave", "c64"),
    ("pool-700-animate-dead-camp-cast-resave", "amiga"),
    ("wish303-dos-l2-slotc-resave", "c64"),
    ("wish303-dos-l2-slotc-resave", "amiga"),
    ("wish-plane-303-pool-meys2tbs-gm", "c64"),
    ("wish-plane-303-pool-meys2tbs-gm", "dos"),
])
def test_save_as_converts_every_zombie_specimen_living(tmp_path, name, port):
    """All six cross-port pairs: Save As raises no `SaveAsError`, so the
    read-back check accepts the living form, and no zombie reaches the
    destination."""
    plan = _prepare_save_as(_zombie_source_path(name), port, tmp_path)
    if port == "dos":
        for fname, data in plan.files.items():
            if fname.endswith(".SAV") and len(data) > 0x112:
                assert data[0x10C] != 1, fname
    elif port == "amiga":
        (image,) = plan.files
        from goldbox import amiga_savegame
        from goldbox.amiga_adf import AmigaDisk

        disk = AmigaDisk(bytearray(plan.files[image]))
        drawer = amiga_savegame.por_save_drawer(disk)
        chars = amiga_savegame.read_por_characters(
            disk, plan.destination.slot or "A", drawer)
        assert chars
        for char in chars:
            assert char.raw[0x10E] != 1, char.name
    else:
        (image,) = plan.files
        out = tmp_path / "read-back.d64"
        out.write_bytes(plan.files[image])
        from goldbox.d64 import D64
        from goldbox.savegame import load_save

        game, sg0, sg1 = load_save(D64.open(str(out)))
        for slot in sg0.characters:
            block = sg1.roster(slot.index)
            assert block.roster_in_use != 0x03, slot.record.get("name")
            assert slot.record.get("flags_0b8") < 0xFE


# -- the later titles -------------------------------------------------------

_LATER_CURSE = "curse-of-the-azure-bonds"
_LATER_SSB = "secret-of-the-silver-blades"
_LATER_POD = "pools-of-darkness"

# status, active, side, quickfight, turn class, attack level, movement,
# control, creature type, hit points: the offsets of each title's DOS record.
_LATER_OFFSETS = {
    _LATER_CURSE: dict(status=0x195, active=0x196, side=0x197, quick=0x198,
                       turn=0xE9, atk=0xDD, move=0xE4, ctl=0xF7, mtype=0x11A,
                       hp=0x1A4),
    _LATER_SSB: dict(status=0x1A6, active=0x1A7, side=0x1A8, quick=0x1A9,
                     turn=0xF2, atk=0xE6, move=0xED, ctl=0xFF, hp=0x1B5),
    _LATER_POD: dict(status=0x1ED, active=0x1EE, side=0x1EF, quick=0x1F0,
                     turn=0x13A, move=0x137, ctl=0x147, hp=0x1FC),
}
_CAST = dict(status=1, active=1, side=0, quick=1, turn=2, atk=0, move=6,
             ctl=0xB3, mtype=4)
_ANIMATE_DEAD_NODE = bytes((0x20, 0, 0, 0x05, 1, 0, 0, 0, 0))


def _later_party(key):
    """`(party, deltas)` of the specimen a later title's tests stage on."""
    import gamedata

    if key == _LATER_POD:
        root = gamedata.specimen_root()
        where = (root / "pod-dos" / "WISH-SPEC-dos-pod-foundation-walked"
                 if root else None)
        if where is None or not where.is_dir():
            pytest.skip("needs specimen WISH-SPEC-dos-pod-foundation-walked")
        folder, letter = where, "D"
    elif key == _LATER_CURSE:
        folder, letter = gamedata.specimen("amigatodos-curse-resave"), "A"
    else:
        folder, letter = gamedata.specimen("amigatodos-ssb-resave"), "A"
    return dos_codec.read_party(folder, letter)


def _later_zombie(key, control=0xB3, hp=None):
    """The first member of the title's specimen with the bytes the cast
    writes staged onto him, as the DOS record."""
    first = _later_party(key)[0]
    raw = bytearray(first.to_bytes())
    offsets = _LATER_OFFSETS[key]
    for name, value in _CAST.items():
        if name in offsets:
            raw[offsets[name]] = value
    raw[offsets["ctl"]] = control
    if hp is not None:
        raw[offsets["hp"]] = hp
    return dos_codec.DosCharacter(
        bytes(raw), first.items, tuple(first.effects) + (_ANIMATE_DEAD_NODE,),
        source="staged", deltas=first.deltas)


def _later_plain(key):
    return dos_codec.to_neutral(_later_party(key)[0])


def _later_from(key, character, port):
    """`character`, written to `port` and read back, as that port's source."""
    n = dos_codec.to_neutral(character)
    if port == "dos":
        return n
    if key == _LATER_POD:
        written, _rep = amiga_pod.write_pod(n)
        return amiga_pod.pod_to_neutral(written.to_bytes())
    written, _rep = amiga_later.write_later(n, key)
    return amiga_later.to_neutral_later(written)


def _later_drops(key, member, deltas):
    """The drop lines every writer reports for `member`."""
    out = {"dos": dos_codec.write(member, deltas=deltas)[3].dropped}
    if key == _LATER_POD:
        out["amiga"] = amiga_pod.write_pod(member)[1].dropped
    else:
        out["amiga"] = amiga_later.write_later(member, key)[1].dropped
        out["c64"] = c64_codec.write(member)[1].dropped
    return out


_LATER_TITLES = [_LATER_CURSE, _LATER_SSB, _LATER_POD]


@pytest.mark.parametrize("port", ["dos", "amiga"])
@pytest.mark.parametrize("key", _LATER_TITLES)
def test_a_later_zombie_player_converts_living(key, port):
    zombie = _later_zombie(key, hp=0)
    source = _later_from(key, zombie, port)
    assert c64_codec.zombie_player(source)
    living = c64_codec.living_player(source)
    assert (living.get("status"), living.get("active")) == ("okay", True)
    assert living.get("hp_current") == 1
    record, _itm, spc, _rep = dos_codec.write(living, deltas=zombie.deltas)
    o = _LATER_OFFSETS[key]
    assert [record[o[n]] for n in
            ("status", "side", "quick", "ctl", "move")] == [0, 0, 0, 0, 12]
    assert record[o["active"]] == 1
    ids = {bytes(spc)[i] for i in range(0, len(spc), 9)}
    if key == _LATER_CURSE:
        assert record[o["turn"]] == 0 and record[o["mtype"]] == 0
        assert 32 not in ids
    back = (amiga_pod.pod_to_neutral(amiga_pod.write_pod(living)[0].to_bytes())
            if key == _LATER_POD else
            amiga_later.to_neutral_later(amiga_later.write_later(living, key)[0]))
    assert not c64_codec.zombie_player(back)
    assert (back.get("status"), back.get("active")) == ("okay", True)
    assert back.get("npc_control_byte") in (None, 0)
    assert back.get("movement") == 12
    assert (_later_drops(key, living, zombie.deltas)
            == _later_drops(key, _later_from(key, _later_party(key)[0], port),
                            zombie.deltas))


@pytest.mark.parametrize("key", _LATER_TITLES)
def test_a_later_zombie_companion_is_left_alone(key):
    companion = dos_codec.to_neutral(_later_zombie(key, control=0xB2))
    assert not c64_codec.zombie_player(companion)
    assert c64_codec.living_player(companion) is companion


def test_a_curse_zombie_companion_keeps_the_status_c64_curse_runs():
    companion = dos_codec.to_neutral(_later_zombie(_LATER_CURSE, control=0xB2))
    rec, rep = c64_codec.write(companion)
    assert rec.get("roster_in_use") == c64_codec.ZOMBIE_STATUS
    assert (rec.get("flags_0b8"), rec.get("combat_side")) == (0xB2, 0x80)
    assert not [d for d in rep.dropped if d.startswith("Animated by a spell")]
    back = c64_codec.read(rec, game=c64_port.CURSE_OF_THE_AZURE_BONDS)
    assert (back.get("status"), back.get("active"), back.get("npc"),
            back.get("npc_control_byte")) == ("animated", True, True, 0xB2)


def test_the_amiga_curse_zombie_companion_writes_as_a_c64_zombie():
    from editor.convert import Source
    from goldbox import amiga_savegame

    adf = (gamedata.specimen("wish-plane-303-curse-evoker-add", "amiga")
           / "fetched-save.adf")
    save = amiga_savegame.read_slot(Source.detect(adf).amiga_disk(), "D",
                                    _LATER_CURSE)
    party = [c64_codec.living_player(amiga_later.to_neutral_later(c))
             for c in save.characters]
    evoker = next(c for c in party if c.get("name") == "EVOKER")
    rec, rep = c64_codec.write(evoker)
    assert (rec.get("roster_in_use"), rec.get("flags_0b8")) == (0x03, 0xB2)
    assert not [d for d in rep.dropped if d.startswith("Animated by a spell")]
    back = c64_codec.read(rec, game=c64_port.CURSE_OF_THE_AZURE_BONDS)
    assert (back.get("status"), back.get("npc_control_byte")) == (
        "animated", 0xB2)


def test_a_curse_zombie_byte_on_a_player_character_converts_living():
    char = c64_codec.read(_pool_c64(0x00, 0x03),
                          game=c64_port.CURSE_OF_THE_AZURE_BONDS)
    assert c64_codec.zombie_player(char)
    living = c64_codec.living_player(char)
    assert (living.get("status"), living.get("active")) == ("okay", True)
    rec, rep = c64_codec.write(living)
    assert (rec.get("roster_in_use"), rec.get("flags_0b8")) == (0x01, 0x00)
    assert not [d for d in rep.dropped if d.startswith("Animated by a spell")]


def test_a_c64_curse_zombie_companion_stays_one_on_dos_and_the_amiga():
    char = c64_codec.read(_pool_c64(0xB2, 0x03),
                          game=c64_port.CURSE_OF_THE_AZURE_BONDS)
    assert c64_codec.living_player(char) is char
    curse = dos_port.CURSE_OF_THE_AZURE_BONDS
    dos, _itm, _spc, _rep = dos_codec.write(char, deltas=curse)
    offsets = _LATER_OFFSETS[_LATER_CURSE]
    assert (dos[offsets["status"]], dos[offsets["ctl"]]) == (1, 0xB2)
    back = dos_codec.to_neutral(dos_codec.DosCharacter(dos, deltas=curse))
    amiga = amiga_later.to_neutral_later(
        amiga_later.write_later(char, _LATER_CURSE)[0])
    for other in (back, amiga):
        assert (other.get("status"), other.get("npc_control_byte")) == (
            "animated", 0xB2)
        nodes = (other.get("granted_effects") or []) + (
            other.get("running_effects") or [])
        assert 32 not in [bytes(n)[0] for n in nodes]


def test_living_player_keeps_silver_blades_effect_32():
    zombie = dos_codec.to_neutral(_later_zombie(_LATER_SSB))
    assert 32 in [bytes(n)[0] for n in zombie.get("granted_effects")]
    living = c64_codec.living_player(zombie)
    assert 32 in [bytes(n)[0] for n in living.get("granted_effects")]


def test_living_player_runs_on_pools_of_darkness():
    zombie = dos_codec.to_neutral(_later_zombie(_LATER_POD))
    assert c64_codec.pool_charmed_player(zombie) is False
    assert c64_codec.living_player(zombie).get("status") == "okay"


@pytest.mark.parametrize("key", [_LATER_CURSE, _LATER_SSB])
def test_a_converted_later_zombie_keeps_his_attack_level_on_the_c64(key):
    zombie = dos_codec.to_neutral(_later_zombie(key))
    assert zombie.get("attack_level") == 0
    kept = c64_codec.write(c64_codec.living_player(zombie))[0]
    plain = c64_codec.write(_later_plain(key))[0]
    assert kept.get("attack_level") == plain.get("attack_level") >= 1


def _staged_curse_save(tmp_path, staged):
    import shutil

    import gamedata

    stage = tmp_path / "src"
    shutil.copytree(gamedata.specimen("amigatodos-curse-resave"), stage)
    stage.chmod(0o755)
    for one in stage.iterdir():
        one.chmod(0o644)
    if staged:
        first = stage / "CHRDATA1.SAV"
        raw = bytearray(first.read_bytes())
        o = _LATER_OFFSETS[_LATER_CURSE]
        for name, value in _CAST.items():
            raw[o[name]] = value
        first.write_bytes(bytes(raw))
    return stage / "SAVGAMA.DAT"


def _curse_save_as(tmp_path, staged, port):
    from editor import convert, roster, saveplan
    from tools.convert import convertdrops

    path = _staged_curse_save(tmp_path / ("staged" if staged else "plain"),
                              staged)
    party = roster.Party(str(path))
    source = party.source or convert.Source.detect(party.path)
    where = tmp_path / f"{'staged' if staged else 'plain'}-out"
    where.mkdir()
    try:
        if port == "c64":
            assets = saveplan.resolve_assets(
                source, "c64", game_files=convertdrops.game_files)
            target = where / "out.d64"
        else:
            amiga = convertdrops.amiga_game_disks(where).get(_LATER_CURSE)
            one = convertdrops.amiga_disks_one(where).get(_LATER_CURSE)
            if amiga is None:
                pytest.skip("needs Curse's own Amiga game disk")
            assets = saveplan.resolve_assets(
                source, "amiga", game_files=convertdrops.game_files,
                amiga_disk=amiga, amiga_disk_one=one)
            target = where / "out.adf"
    except (FileNotFoundError, saveplan.MissingAssets):
        pytest.skip("needs Curse's own game files")
    return saveplan.prepare_save_as(party, port, target, assets), saveplan


@pytest.mark.parametrize("port", ["c64", "amiga"])
def test_save_as_converts_a_staged_curse_zombie_living(tmp_path, port):
    plan, saveplan = _curse_save_as(tmp_path, True, port)
    control, _ = _curse_save_as(tmp_path, False, port)
    assert plan.report.dropped == control.report.dropped
    assert saveplan.losses(plan.report) == saveplan.losses(control.report)
    if port == "c64":
        from goldbox.d64 import D64
        from goldbox.savegame import load_save

        (image,) = plan.files
        out = tmp_path / "read-back.d64"
        out.write_bytes(plan.files[image])
        _game, sg0, sg1 = load_save(D64.open(str(out)))
        first = sg0.characters[0]
        assert sg1.roster(first.index).roster_in_use != 0x03
        assert first.record.get("flags_0b8") < 0xFE


def test_pools_of_darkness_amiga_to_dos_writes_a_staged_zombie_living(
        tmp_path, monkeypatch):
    """A zombie the Amiga save holds arrives living through the Amiga to DOS
    route."""
    import shutil

    from test_podsave import _amiga_source, _dos_source, _synthetic_disk_three

    from editor import convert
    from goldbox import amiga_savegame
    from goldbox.amiga_adf import AmigaDisk

    stage = tmp_path / "pod"
    shutil.copytree(_later_party_folder(), stage)
    stage.chmod(0o755)
    for one in stage.iterdir():
        one.chmod(0o644)
    letter = "D"
    first = stage / "CHRDATD1.SAV"
    first.write_bytes(_later_zombie(_LATER_POD).to_bytes())
    disk = _synthetic_disk_three(letter)

    def amiga_party(image):
        return [amiga_pod.pod_to_neutral(b) for b in amiga_savegame.pod_parse(
            amiga_savegame.pod_read_slot(
                AmigaDisk(image), letter)).blocks]

    # Keep the zombie as the Amiga writer stores him, to feed the route.
    with monkeypatch.context() as patch:
        patch.setattr(c64_codec, "living_player", lambda char: char)
        kept = convert.PodDosToAmiga().rehearse(
            _dos_source(stage, letter), letter, None, disk_three=disk,
            replace=True)
    assert c64_codec.zombie_player(amiga_party(kept.disk)[0])

    back = convert.PodAmigaToDos().rehearse(
        _amiga_source(kept.disk, letter), letter, None)
    chars = [dos_codec.to_neutral(c)
             for c in _read_back_party(back, tmp_path / "back", letter)]
    assert not c64_codec.zombie_player(chars[0])
    assert chars[0].get("status") == "okay"


def _later_party_folder():
    import gamedata

    root = gamedata.specimen_root()
    where = (root / "pod-dos" / "WISH-SPEC-dos-pod-foundation-walked"
             if root else None)
    if where is None or not where.is_dir():
        pytest.skip("needs specimen WISH-SPEC-dos-pod-foundation-walked")
    return where


def _read_back_party(rehearsal, folder, letter):
    folder.mkdir()
    for name, data in rehearsal.files.items():
        (folder / name).write_bytes(data)
    return dos_codec.read_party(folder, letter)



def _editor_tests():
    """`tests/editor` on the import path, so its synthetic Pools of Darkness
    folder and disk helpers load when this file runs alone."""
    import pathlib
    import sys

    here = str(pathlib.Path(__file__).resolve().parents[1] / "editor")
    if here not in sys.path:
        sys.path.append(here)


def _pod_zombie_folder(root, control, cast=True, marked=True, down=False):
    """A synthetic Pools of Darkness DOS folder whose one character holds the
    bytes the cast writes (unless `cast` is false, which leaves the turning
    class a companion keeps), with marker bytes in the `field_83_87` window
    the engine never reads."""
    _editor_tests()
    from test_saveplan_pod import _dos_folder, _record

    folder = _dos_folder(root)
    raw = bytearray(_record().to_bytes())
    o = _LATER_OFFSETS[_LATER_POD]
    for name, value in _CAST.items():
        if name in o and (cast or name != "turn"):
            raw[o[name]] = value
    raw[o["ctl"]] = control
    if down:
        # A zombie the cast left with no hit points and not active.
        raw[o["hp"]] = raw[o["active"]] = 0
    if marked:
        raw[o["ctl"] + 2], raw[o["ctl"] + 3] = 0x11, 0x22
    (folder / "CHRDATA1.SAV").write_bytes(bytes(raw))
    return folder


def _pod_save_as_amiga(monkeypatch, tmp_path, control, cast=True, down=False):
    _editor_tests()
    from test_saveplan_pod import _disk_file, _disk_three, _to_amiga

    from editor import convert
    from editor.roster import Party
    from goldbox import amiga_savegame
    from goldbox.amiga_adf import AmigaDisk

    folder = _pod_zombie_folder(tmp_path, control, cast, down=down)
    party = Party(convert.Source.detect(folder, slot="A"))
    plan = _to_amiga(party, tmp_path,
                     _disk_file(tmp_path, _disk_three("A")))
    [image] = plan.files.values()
    blocks = amiga_savegame.pod_parse(amiga_savegame.pod_read_slot(
        AmigaDisk(bytearray(image)), "A")).blocks
    source = dos_codec.to_neutral(dos_codec.read_party(folder, "A")[0])
    return source, amiga_pod.pod_to_neutral(blocks[0]), plan


def test_a_pools_of_darkness_dos_zombie_player_converts_living_to_the_amiga(
        monkeypatch, tmp_path):
    source, arrived, plan = _pod_save_as_amiga(monkeypatch, tmp_path, 0xB3)
    assert c64_codec.zombie_player(source)
    assert not c64_codec.zombie_player(arrived)
    assert arrived.get("status") == "okay"
    assert arrived.get("npc_control_byte") is None
    assert dos_codec.window_source(arrived)[2:] \
        == dos_codec.window_source(source)[2:] == bytes((0x11, 0x22))
    assert plan.report.losses == []


def test_a_pools_of_darkness_dos_zombie_companion_stays_a_zombie_on_the_amiga(
        monkeypatch, tmp_path):
    source, arrived, _plan = _pod_save_as_amiga(
        monkeypatch, tmp_path, 0xB2, cast=False)
    assert not c64_codec.zombie_player(source)
    assert arrived.get("status") == "animated"
    assert arrived.get("npc_control_byte") == 0xB2


def test_a_pools_of_darkness_amiga_zombie_player_reads_back_living_on_dos(
        monkeypatch, tmp_path):
    """The Amiga to DOS Save As does not report the zombie's conversion to a
    living character as a loss."""
    import shutil

    from test_podsave import _dos_source, _synthetic_disk_three

    from editor import convert, podsheet, saveplan
    from editor.roster import Party

    (tmp_path / "src").mkdir()
    stage = tmp_path / "stage"
    shutil.copytree(_pod_zombie_folder(tmp_path / "src", 0xB3), stage)
    disk = _synthetic_disk_three("A")
    with monkeypatch.context() as patch:
        patch.setattr(c64_codec, "living_player", lambda char: char)
        kept = convert.PodDosToAmiga().rehearse(
            _dos_source(stage, "A"), "A", None, disk_three=disk, replace=True)
    image = tmp_path / "kept.adf"
    image.write_bytes(kept.disk)
    party = Party(convert.Source.detect(image, slot="A"))
    plan = saveplan.prepare_save_as(party, "dos", tmp_path / "dos-out")
    window = podsheet.TABLE["field_83_87"].offset
    assert plan.files["CHRDATA1.SAV"][window:window + 4] \
        == bytes((0, 0, 0x11, 0x22))


def test_a_pools_of_darkness_zombie_with_no_hit_points_reads_back_living(
        monkeypatch, tmp_path):
    """`living_player` gives him 1 hit point and makes him active, which the
    read-back expects instead of calling it a loss."""
    _source, arrived, _plan = _pod_save_as_amiga(
        monkeypatch, tmp_path, 0xB3, down=True)
    assert arrived.get("hp_current") == 1
    assert arrived.get("active") is True


# -- a zombie player character whose control byte an effect end lowered ------
#
# A confusion or charm end clears `$B3` to 0 and leaves the status animated
# (Amiga Curse handlers 137 and 142), so he reaches Curse's, Silver Blades'
# and Pools of Darkness' saves as an animated member under a player
# character's control byte.

def _lowered_zombie(key, hp=None):
    """The title's specimen's first member with the cast's bytes and the
    end state an effect end leaves: control 0, quickfight cleared, status
    still animated. He carries no Animate Dead node, as one imported from
    Pool does not."""
    first = _later_party(key)[0]
    raw = bytearray(first.to_bytes())
    o = _LATER_OFFSETS[key]
    for name, value in _CAST.items():
        if name in o:
            raw[o[name]] = value
    raw[o["ctl"]] = raw[o["quick"]] = 0
    if hp is not None:
        raw[o["hp"]] = hp
    return dos_codec.DosCharacter(bytes(raw), first.items,
                                  tuple(first.effects), source="staged",
                                  deltas=first.deltas)


@pytest.mark.parametrize("port", ["dos", "amiga"])
@pytest.mark.parametrize("key", _LATER_TITLES)
def test_a_lowered_zombie_player_converts_living(key, port):
    zombie = _lowered_zombie(key, hp=0)
    source = _later_from(key, zombie, port)
    assert (source.get("status"), source.get("npc")) == ("animated", False)
    assert c64_codec.zombie_player(source)
    living = c64_codec.living_player(source)
    assert (living.get("status"), living.get("active"),
            living.get("hp_current")) == ("okay", True, 1)
    assert living.get("spells_memorised") == source.get("spells_memorised")
    record = dos_codec.write(living, deltas=zombie.deltas)[0]
    o = _LATER_OFFSETS[key]
    assert [record[o[n]] for n in
            ("status", "active", "side", "quick", "ctl", "move")] \
        == [0, 1, 0, 0, 0, 12]
    if key == _LATER_CURSE:
        assert record[o["turn"]] == record[o["mtype"]] == 0
    back = (amiga_pod.pod_to_neutral(amiga_pod.write_pod(living)[0].to_bytes())
            if key == _LATER_POD else
            amiga_later.to_neutral_later(amiga_later.write_later(living, key)[0]))
    assert (back.get("status"), back.get("active"), back.get("movement")) \
        == ("okay", True, 12)
    plain = _later_from(key, _later_party(key)[0], port)
    assert (_later_drops(key, living, zombie.deltas)
            == _later_drops(key, plain, zombie.deltas))


def test_an_animated_companion_is_still_not_a_zombie_player():
    for control in (0x80, 0xB2, 0xFF):
        char = _dos_zombie(0, control, True)
        assert not c64_codec.zombie_player(char)
        assert c64_codec.living_player(char) is char


def _lowered_save_as(tmp_path, key, port):
    """Save As to `port` of the title's specimen with `_lowered_zombie` as
    its first member."""
    import shutil

    from editor import convert, roster, saveplan
    from tools.convert import convertdrops

    name = {_LATER_CURSE: "amigatodos-curse-resave",
            _LATER_SSB: "amigatodos-ssb-resave"}[key]
    stage = tmp_path / "src"
    shutil.copytree(gamedata.specimen(name), stage)
    stage.chmod(0o755)
    for one in stage.iterdir():
        one.chmod(0o644)
    (stage / "CHRDATA1.SAV").write_bytes(_lowered_zombie(key).to_bytes())
    party = roster.Party(str(stage / "SAVGAMA.DAT"))
    source = party.source or convert.Source.detect(party.path)
    where = tmp_path / "out"
    where.mkdir()
    try:
        if port == "c64":
            assets = saveplan.resolve_assets(
                source, "c64", game_files=convertdrops.game_files)
            target = where / "out.d64"
        else:
            amiga = convertdrops.amiga_game_disks(where).get(key)
            if amiga is None:
                pytest.skip(f"needs {key}'s own Amiga game disk")
            assets = saveplan.resolve_assets(
                source, "amiga", game_files=convertdrops.game_files,
                amiga_disk=amiga,
                amiga_disk_one=convertdrops.amiga_disks_one(where).get(key))
            target = where / "out.adf"
    except (FileNotFoundError, saveplan.MissingAssets):
        pytest.skip(f"needs {key}'s own game files")
    plan = saveplan.prepare_save_as(party, port, target, assets)
    assert plan.report.dropped == [] and saveplan.losses(plan.report) == []
    return plan


@pytest.mark.parametrize("port", ["c64", "amiga"])
@pytest.mark.parametrize("key", [_LATER_CURSE, _LATER_SSB])
def test_save_as_converts_a_lowered_zombie_living(tmp_path, key, port):
    plan = _lowered_save_as(tmp_path, key, port)
    (image,) = plan.files
    if port == "c64":
        from goldbox.d64 import D64
        from goldbox.savegame import load_save

        out = tmp_path / "read-back.d64"
        out.write_bytes(plan.files[image])
        _game, sg0, sg1 = load_save(D64.open(str(out)))
        assert [(sg1.roster(s.index).roster_in_use,
                 s.record.get("flags_0b8") & 0x80) for s in sg0.characters] \
            == [(0x01, 0)] * len(sg0.characters)
    else:
        from goldbox import amiga_savegame
        from goldbox.amiga_adf import AmigaDisk

        save = amiga_savegame.read_slot(
            AmigaDisk(bytearray(plan.files[image])),
            plan.destination.slot or "A", key)
        chars = [amiga_later.to_neutral_later(c) for c in save.characters]
        assert chars
        assert [(c.get("status"), c.get("npc")) for c in chars] \
            == [("okay", False)] * len(chars)


def test_a_pools_of_darkness_lowered_zombie_converts_living_to_the_amiga(
        monkeypatch, tmp_path):
    source, arrived, plan = _pod_save_as_amiga(monkeypatch, tmp_path, 0x00)
    assert (source.get("status"), source.get("npc")) == ("animated", False)
    assert c64_codec.zombie_player(source)
    assert (arrived.get("status"), arrived.get("active")) == ("okay", True)
    assert arrived.get("npc_control_byte") is None
    assert dos_codec.window_source(arrived)[2:] == bytes((0x11, 0x22))
    assert plan.report.losses == []


def test_a_pools_of_darkness_amiga_lowered_zombie_reads_back_living_on_dos(
        monkeypatch, tmp_path):
    import shutil

    from test_podsave import _dos_source, _synthetic_disk_three

    from editor import convert, podsheet, saveplan
    from editor.roster import Party

    (tmp_path / "src").mkdir()
    stage = tmp_path / "stage"
    shutil.copytree(_pod_zombie_folder(tmp_path / "src", 0x00), stage)
    disk = _synthetic_disk_three("A")
    # Keep him as the Amiga writer stores an animated member, to feed the
    # Amiga to DOS route.
    with monkeypatch.context() as patch:
        patch.setattr(c64_codec, "living_player", lambda char: char)
        kept = convert.PodDosToAmiga().rehearse(
            _dos_source(stage, "A"), "A", None, disk_three=disk, replace=True)
    image = tmp_path / "kept.adf"
    image.write_bytes(kept.disk)
    party = Party(convert.Source.detect(image, slot="A"))
    plan = saveplan.prepare_save_as(party, "dos", tmp_path / "dos-out")
    record = plan.files["CHRDATA1.SAV"]
    flags = podsheet.TABLE["field_10c_10f"].offset
    assert (record[flags], record[flags + 1]) == (0, 1)
    assert record[podsheet.TABLE["movement"].offset] == 12


def test_an_animated_record_with_no_npc_flag_is_not_a_zombie_player():
    char = neutral.NeutralCharacter("DOS", source="built here",
                                    game=c64_port.POOL_OF_RADIANCE)
    char.set("status", "animated", "built here")
    assert char.get("npc") is None
    assert not c64_codec.zombie_player(char)
    assert c64_codec.living_player(char) is char


def test_a_pool_c64_zombie_byte_on_a_player_character_converts_living():
    char = c64_codec.read(_pool_c64(0x00, 0x03),
                          game=c64_port.POOL_OF_RADIANCE)
    assert (char.get("status"), char.get("npc")) == ("animated", False)
    assert c64_codec.zombie_player(char)
    living = c64_codec.living_player(char)
    assert (living.get("status"), living.get("active"),
            living.get("hp_current")) == ("okay", True, 1)
    dos = dos_codec.write(living)[0]
    assert (dos[0x10C], dos[0x10D]) == (0, 1)


# -- a zombie that got away from a fight and was saved at status okay -----------
#
# Specimen wish303-i6-curse-brutus-got-away-slot-f: Amiga Curse, driven by
# tools/amiga/cursefight.py, in which the zombie BRUTUS was confused, ran off
# the map and was saved at status okay, active, control 0, with the cast's
# creature type 4, movement 6 and turning class 2.

_GOT_AWAY = "wish303-i6-curse-brutus-got-away-slot-f"


def _got_away_disk():
    from editor.convert import Source

    adf = gamedata.specimen(_GOT_AWAY, "amiga") / "fetched-save.adf"
    return Source.detect(adf).amiga_disk(), adf


def _got_away_party():
    from goldbox import amiga_savegame

    disk, _adf = _got_away_disk()
    save = amiga_savegame.read_slot(disk, "F", _LATER_CURSE)
    return [amiga_later.to_neutral_later(c) for c in save.characters]


def _got_away_brutus(party):
    (brutus,) = [c for c in party if c.get("name") == "BRUTUS"]
    return brutus


def test_a_curse_zombie_that_got_away_reads_as_a_zombie_player():
    party = _got_away_party()
    brutus = _got_away_brutus(party)
    assert (brutus.get("status"), brutus.get("creature_type")) == ("okay", 4)
    assert (brutus.get("npc"), brutus.get("movement"),
            brutus.get("turn_class")) == (False, 6, 2)
    assert c64_codec.zombie_player(brutus)
    living = c64_codec.living_player(brutus)
    assert (living.get("creature_type"), living.get("movement"),
            living.get("turn_class"), living.get("npc")) == (0, 12, 0, False)
    others = [c for c in party if c is not brutus]
    assert len(others) == 4
    for other in others:
        assert not c64_codec.zombie_player(other)
        assert c64_codec.living_player(other) is other


def _got_away_save_as(tmp_path, port):
    from editor import convert, roster, saveplan
    from tools.convert import convertdrops
    from tools.dos import dosbox

    _disk, adf = _got_away_disk()
    party = roster.Party(convert.Source.detect(adf, slot="F"))
    source = party.source or convert.Source.detect(party.path)
    try:
        if port == "c64":
            assets = saveplan.resolve_assets(
                source, "c64", game_files=convertdrops.game_files)
            where = tmp_path / "out.d64"
        else:
            assets = saveplan.resolve_assets(
                source, "dos", game_files=convertdrops.game_files,
                dos_folder=dosbox.find_game("CURSE"))
            where = tmp_path / "dos-out"
    except (FileNotFoundError, saveplan.MissingAssets):
        pytest.skip("needs Curse's own game files")
    plan = saveplan.prepare_save_as(party, port, where, assets)
    assert plan.report.dropped == [] and saveplan.losses(plan.report) == []
    return plan


def test_save_as_converts_a_curse_zombie_that_got_away_living_to_dos(tmp_path):
    plan = _got_away_save_as(tmp_path, "dos")
    o = _LATER_OFFSETS[_LATER_CURSE]
    seen = {}
    for name, data in plan.files.items():
        if name.endswith(".SAV") and len(data) > o["hp"]:
            seen[bytes(data[1:1 + data[0]])] = data
    assert len(seen) == 5
    brutus = seen[b"BRUTUS"]
    assert [brutus[o[n]] for n in ("mtype", "move", "turn", "ctl")] \
        == [0, 12, 0, 0]
    party = _got_away_party()
    for other in (c for c in party if c.get("name") != "BRUTUS"):
        written = dos_codec.write(other, deltas=dos_port.CURSE_OF_THE_AZURE_BONDS)[0]
        assert seen[str(other.get("name")).encode()] == written


def test_save_as_converts_a_curse_zombie_that_got_away_living_to_the_c64(
        tmp_path):
    from goldbox.d64 import D64
    from goldbox.savegame import load_save

    plan = _got_away_save_as(tmp_path, "c64")
    (image,) = plan.files
    out = tmp_path / "read-back.d64"
    out.write_bytes(plan.files[image])
    game, sg0, sg1 = load_save(D64.open(str(out)))
    read = {}
    for slot in sg0.characters:
        char = c64_codec.read(slot.record, roster=sg1.roster(slot.index),
                              game=game, payload=sg0.to_bytes(),
                              party_slot=slot.index)
        read[char.get("name")] = (slot, char)
    slot, brutus = read["BRUTUS"]
    assert (sg1.roster(slot.index).roster_in_use,
            slot.record.get("flags_0b8")) == (0x01, 0)
    assert (brutus.get("creature_type"), brutus.get("movement"),
            brutus.get("turn_class")) == (0, 12, 0)
    assert len(read) == 5


def _got_away_neutral(key, control, creature_type=4, status="okay", npc=False,
                      turn_class=2):
    char = neutral.NeutralCharacter("DOS", source="built here", game=key)
    char.set("status", status, "built here")
    char.set("npc", npc, "built here")
    char.set("npc_control_byte", control, "built here")
    char.set("creature_type", creature_type, "built here")
    char.set("turn_class", turn_class, "built here")
    return char


@pytest.mark.parametrize("control", [0, 0xB3])
@pytest.mark.parametrize("game", [None, c64_port.POOL_OF_RADIANCE,
                                  c64_port.CURSE_OF_THE_AZURE_BONDS])
def test_a_pool_or_curse_zombie_saved_at_okay_is_a_zombie_player(game, control):
    char = _got_away_neutral(game, control)
    assert c64_codec.zombie_player(char)
    living = c64_codec.living_player(char)
    assert (living.get("status"), living.get("creature_type"),
            living.get("turn_class")) == ("okay", 0, 0)


@pytest.mark.parametrize("control", [0, 0xB3])
def test_a_got_away_zombie_converts_living_through_the_dos_writer(control):
    key = _LATER_CURSE
    first = _later_party(key)[0]
    raw = bytearray(first.to_bytes())
    o = _LATER_OFFSETS[key]
    for name, value in _CAST.items():
        if name in o:
            raw[o[name]] = value
    raw[o["status"]], raw[o["active"]], raw[o["quick"]] = 0, 1, 0
    raw[o["ctl"]] = control
    char = dos_codec.to_neutral(dos_codec.DosCharacter(
        bytes(raw), first.items, tuple(first.effects), source="staged",
        deltas=first.deltas))
    assert c64_codec.zombie_player(char)
    record = dos_codec.write(c64_codec.living_player(char),
                             deltas=first.deltas)[0]
    assert [record[o[n]] for n in ("status", "active", "ctl", "move", "mtype",
                                   "turn")] == [0, 1, 0, 12, 0, 0]


def test_a_companion_that_got_away_stays_a_zombie_npc():
    char = _got_away_neutral(c64_port.CURSE_OF_THE_AZURE_BONDS, 0xB2, npc=True)
    assert not c64_codec.zombie_player(char)
    assert c64_codec.living_player(char) is char


@pytest.mark.parametrize("game", [c64_port.SECRET_OF_THE_SILVER_BLADES,
                                  dos_port.POOLS_OF_DARKNESS])
def test_a_later_title_record_at_okay_with_type_four_is_not_a_zombie(game):
    char = _got_away_neutral(game, 0)
    assert not c64_codec.zombie_player(char)
    assert c64_codec.living_player(char) is char


def test_a_living_record_with_turn_class_two_alone_is_not_a_zombie():
    char = _got_away_neutral(c64_port.CURSE_OF_THE_AZURE_BONDS, 0,
                             creature_type=0)
    assert not c64_codec.zombie_player(char)
    assert c64_codec.living_player(char) is char
