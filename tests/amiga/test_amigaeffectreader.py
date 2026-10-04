"""Effect-node reading for the Amiga acceptance drivers, and the `--expect` check (#661).

Nothing here holds game bytes: every save is built from `support.amigarecords`
by-hand characters, following the pattern `tests/amiga/test_savegamelosses.py`
and `tests/convert/test_runningeffects.py` already use. The reader offsets
(record 0x0F2 for Curse, 0x096 for Silver Blades, per #661's comment of
2026-09-27T09:43:18Z) are exercised directly below, and again through
`amiga_savegame.CURSE`/`SILVER_BLADES` whose own asserted `party_at` values
(`goldbox/amiga_savegame.py`) put each character's record, and so its chain
head, at a known byte.
"""

from __future__ import annotations

import pytest
from support.amigarecords import sample, synthetic_savegame

from goldbox import amiga_savegame, areas, c64_save, dos_codec, world_state
from tests.amiga.test_savegamelosses import _bare_silver_blades_state
from tools.amiga import (
    acceptance,
    route_curse,
    route_pool,
    route_silver_blades,
)
from tools.amiga.route import check_expect, effect_fields, parse_expect
from tools.amiga.route_silver_blades import _slot_reading as _ssb_slot_reading

NULL = dos_codec.EFFECT_NEXT_NULL
#: id 1 (Bless), 47 minutes, data 5, flag 0, in the DOS byte order `write_later`
#: and `write_por` both take.
RUNNING = bytes((1, 0x2F, 0x00, 0x05, 0x00)) + NULL
#: A never-expiring node: duration 0, so it never ages, with a different id
#: and flag so the two nodes cannot be told apart by accident.
GRANTED = bytes((61, 0x00, 0x00, 0x05, 0x01)) + NULL
CHAIN = [[61, 0, 5, 1], [1, 47, 5, 0]]


def _bare_curse_state() -> world_state.WorldState:
    """A Curse party that has not set out: `new_savegame` needs no `ECL.GLB` for one."""
    later_first, later_size = dos_codec.LATER_HEADER_COPIED
    header = {dos_codec.SAVE0_BASE + later_first + i: 0 for i in range(later_size)}
    flags_width = c64_save.container_for("curse-of-the-azure-bonds").quest_flags[1]
    return world_state.WorldState(
        title=areas.CURSE_OF_THE_AZURE_BONDS, area=0, geo=0, x=0, y=0, facing=0,
        clock=(0,) * 6, wallset=(0, 0, 0), flags=(0,) * flags_width,
        scratch={addr: 0 for addr in dos_codec.SHARED_SCRATCH},
        outdoors=False, travel=(0, 0), set_out=False, header=header)


def _later_disk(container, state, name: str, slot: str = "B"):
    """A one-character save disk for a later title, the character carrying `CHAIN`."""
    char = sample(name=name, running_effects=[RUNNING], granted_effects=[GRANTED])
    built, report = amiga_savegame.new_savegame(state, [char], slot)
    assert report.unwritten == []
    return built, amiga_savegame.make_save_disk(container, slot, built)


# --- the reader walks the chain, at the title's own record offset ------------

def test_curse_read_slot_gives_the_chain_at_record_offset_0x0f2():
    built, disk = _later_disk(amiga_savegame.CURSE, _bare_curse_state(), "PHILIPPE")
    at = amiga_savegame.CURSE.party_at + 0xF2
    assert int.from_bytes(built[at:at + 4], "big") != 0, "the chain head at 0x0F2 is unset"

    reading = route_curse._curse_read_slot(disk, "B")
    assert reading["effects"] == {"PHILIPPE": CHAIN}


def test_silver_blades_read_slot_gives_the_chain_at_record_offset_0x096():
    built, disk = _later_disk(amiga_savegame.SILVER_BLADES, _bare_silver_blades_state(),
                              "GUY DE VALOIS")
    at = amiga_savegame.SILVER_BLADES.party_at + 0x96
    assert int.from_bytes(built[at:at + 4], "big") != 0, "the chain head at 0x096 is unset"

    reading = _ssb_slot_reading(disk, "B")
    assert reading["effects"] == {"GUY DE VALOIS": CHAIN}


def _raise_on_effect(node):
    raise ValueError("malformed effect node")


def test_ssb_slot_reading_gives_a_clean_decode_error_for_a_malformed_effect_node(monkeypatch):
    """A bad effect node must not escape `_slot_reading` uncaught (#661 review, finding 1)."""
    _built, disk = _later_disk(amiga_savegame.SILVER_BLADES, _bare_silver_blades_state(),
                               "GUY DE VALOIS")
    monkeypatch.setattr(route_silver_blades, "effect_fields", _raise_on_effect)

    reading = route_silver_blades._slot_reading(disk, "B")

    assert reading["decode_error"] == "ValueError: malformed effect node"
    assert "place" not in reading
    assert "names" not in reading
    assert "effects" not in reading


def test_curse_read_slot_leaves_no_stale_place_when_effects_fail(monkeypatch):
    """A failure reading effects, after names/place would have succeeded, must not leave a
    stale `place` beside `decode_error` (#661 review, finding 2)."""
    _built, disk = _later_disk(amiga_savegame.CURSE, _bare_curse_state(), "PHILIPPE")
    monkeypatch.setattr(route_curse, "effect_fields", _raise_on_effect)

    reading = route_curse._curse_read_slot(disk, "B")

    assert reading["decode_error"] == "ValueError: malformed effect node"
    assert "place" not in reading
    assert "names" not in reading
    assert "effects" not in reading


def test_pool_read_slot_gives_the_chain_off_the_sibling_spc_file():
    party = [sample(name="BRUTUS", running_effects=[RUNNING], granted_effects=[GRANTED])]
    disk = amiga_savegame.make_por_save_disk("A", party, synthetic_savegame("A"))

    reading = route_pool._pool_read_slot(disk, "A")
    assert reading["effects"] == {"BRUTUS": CHAIN}


# --- effect_fields, on its own ------------------------------------------------

def test_effect_fields_reads_id_minutes_data_flag_through_the_byte_order():
    node = bytes((1, 0, 0x00, 0x2F, 0x05, 0x00)) + NULL
    assert effect_fields(node) == (1, 47, 5, 0)


# --- parse_expect and check_expect --------------------------------------------

def test_parse_expect_reads_the_four_fields():
    assert parse_expect("PHILIPPE:1:47:5") == ("PHILIPPE", 1, 47, 5)


def test_parse_expect_blocks_a_malformed_string():
    from tools.amiga.winuaesession import RouteError
    with pytest.raises(RouteError):
        parse_expect("PHILIPPE-1-47-5")


def test_check_expect_accepts_a_matching_node():
    reading = {"effects": {"PHILIPPE": CHAIN}}
    accepted, line = check_expect(reading, ("PHILIPPE", 1, 47, 5))
    assert accepted is True
    assert line == "expect PHILIPPE id 1 at 47 minutes: accepts"


def test_check_expect_refutes_a_different_minute_count():
    """A near miss refutes -- #661: a tolerance here masked whether the Amiga
    engine counts a spell down at all, since 47 minutes stored against an
    expectation of 45 passed unnoticed."""
    reading = {"effects": {"PHILIPPE": CHAIN}}
    accepted, line = check_expect(reading, ("PHILIPPE", 1, 45, 5))
    assert accepted is False
    assert line.startswith("expect PHILIPPE id 1 at 45 minutes: refutes")
    assert "holds" in line


def test_check_expect_takes_no_tolerance_argument():
    """#661: a tolerance masked the false accept -- the 47-minute Amiga read
    was closed as matching a 45-minute expectation. `check_expect` no longer
    takes a tolerance at all, so a near miss like that one cannot be waved
    through."""
    with pytest.raises(TypeError):
        check_expect({"effects": {"PHILIPPE": CHAIN}}, ("PHILIPPE", 1, 45, 5),
                     tolerance_minutes=2)


def test_check_expect_refutes_a_character_absent_from_the_slot():
    reading = {"effects": {"PHILIPPE": CHAIN}}
    accepted, line = check_expect(reading, ("BRYTWYN", 1, 47, 5))
    assert accepted is False
    assert line == "expect BRYTWYN id 1 at 47 minutes: refutes (BRYTWYN is absent from the slot)"


def test_check_expect_refutes_a_slot_with_no_effects_reading():
    accepted, line = check_expect({}, ("PHILIPPE", 1, 47, 5))
    assert accepted is False
    assert line.endswith("refutes (the slot holds no effects reading)")


# --- acceptance.expect_verdict: read the fetched save disk back -------------

def test_acceptance_expect_verdict_reads_the_fetched_curse_disk(tmp_path):
    title = acceptance.CURSE
    _built, disk = _later_disk(amiga_savegame.CURSE, _bare_curse_state(), "PHILIPPE",
                               title.after_letter)
    run = tmp_path / "run"
    attempt = run / "accept1"
    attempt.mkdir(parents=True)
    disk.save(attempt / "fetched-save.adf")

    accepted, accepts = acceptance.expect_verdict(
        title, run / "prepare.json", "accept1", ("PHILIPPE", 1, 47, 5))
    assert accepted is True
    assert accepts == "expect PHILIPPE id 1 at 47 minutes: accepts"

    blocked, refutes = acceptance.expect_verdict(
        title, run / "prepare.json", "accept1", ("PHILIPPE", 1, 40, 5))
    assert blocked is False
    assert refutes.startswith("expect PHILIPPE id 1 at 40 minutes: refutes")


def test_acceptance_expect_verdict_names_a_missing_fetched_disk(tmp_path):
    title = acceptance.CURSE
    accepted, line = acceptance.expect_verdict(
        title, tmp_path / "prepare.json", "accept1", ("PHILIPPE", 1, 47, 5))
    assert accepted is False
    assert line == "expect PHILIPPE id 1 at 47 minutes: refutes (no fetched save disk)"


# --- route_silver_blades.expect_verdict: Silver Blades' own camp-save slot -------

def test_amigaacceptance_expect_verdict_reads_the_fetched_boot_disk(tmp_path):
    _built, disk = _later_disk(amiga_savegame.SILVER_BLADES, _bare_silver_blades_state(),
                               "GUY DE VALOIS", route_silver_blades.CAMP_SAVE_LETTER)
    run = tmp_path / "run"
    attempt = run / "accept1"
    attempt.mkdir(parents=True)
    disk.save(attempt / "fetched-df0.adf")

    accepted, accepts = route_silver_blades.expect_verdict(
        run / "prepare.json", "accept1", ("GUY DE VALOIS", 1, 47, 5))
    assert accepted is True
    assert accepts == "expect GUY DE VALOIS id 1 at 47 minutes: accepts"


def test_amigaacceptance_expect_verdict_names_a_missing_fetched_disk(tmp_path):
    accepted, line = route_silver_blades.expect_verdict(
        tmp_path / "prepare.json", "accept1", ("GUY DE VALOIS", 1, 47, 5))
    assert accepted is False
    assert line == "expect GUY DE VALOIS id 1 at 47 minutes: refutes (no fetched boot disk)"


def _patterned_record(name: bytes):
    from goldbox import amiga_por

    raw = bytearray(1 + i * 7 % 251 for i in range(amiga_por.AMIGA_POR_RECORD_SIZE))
    raw[:8] = name.ljust(8, b"\0")
    return raw, amiga_por.AmigaPorCharacter.from_bytes(bytes(raw))


def test_pool_read_slot_reads_the_dos_member_keys_through_the_amiga_offsets(monkeypatch):
    """Distinct bytes everywhere, so a key read at its DOS offset instead of the Amiga one shows."""
    disk = amiga_savegame.make_por_save_disk("A", [sample(name="BRUTUS")], synthetic_savegame("A"))
    raw, record = _patterned_record(b"BRUTUS")
    monkeypatch.setattr(amiga_savegame, "read_por_characters",
                        lambda *args, **kwargs: [record])

    (member,) = route_pool._pool_read_slot(disk, "A")["members"]

    assert member == {
        "name": "BRUTUS",
        "status_bytes": list(record.get("field_10c_10f")),
        "control": record.get("field_83_87")[1],
        "treasure_share": record.get("field_83_87")[2],
        "creature_type": record.get("creature_type"),
        "turn_class": record.get("turn_class"),
        "movement": record.get("movement"),
    }
    assert member["status_bytes"] == list(raw[0x10E:0x112])
    assert member["control"] == raw[0x85]
    assert member["treasure_share"] == raw[0x86]
    assert member["creature_type"] == raw[0xA1]
    assert member["turn_class"] == raw[0x76]
    assert member["movement"] == raw[0x72]


def test_pool_read_slot_keeps_two_members_of_one_name_in_party_order(monkeypatch):
    disk = amiga_savegame.make_por_save_disk("A", [sample(name="BRUTUS")], synthetic_savegame("A"))
    first_raw, first = _patterned_record(b"BRUTUS")
    second_raw, second = _patterned_record(b"BRUTUS")
    second_raw[0x86] ^= 0xFF
    second = type(first).from_bytes(bytes(second_raw))
    monkeypatch.setattr(amiga_savegame, "read_por_characters",
                        lambda *args, **kwargs: [first, second])

    members = route_pool._pool_read_slot(disk, "A")["members"]

    assert [m["name"] for m in members] == ["BRUTUS", "BRUTUS"]
    assert [m["treasure_share"] for m in members] == [first_raw[0x86], second_raw[0x86]]
