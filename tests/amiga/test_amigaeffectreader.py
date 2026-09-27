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
from tools.amiga import amigafoundation, amigasecretsave, route_curse, route_pool
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


def test_parse_expect_refuses_a_malformed_string():
    from tools.amiga.winuaesession import RouteError
    with pytest.raises(RouteError):
        parse_expect("PHILIPPE-1-47-5")


def test_check_expect_accepts_a_matching_node():
    reading = {"effects": {"PHILIPPE": CHAIN}}
    line = check_expect(reading, ("PHILIPPE", 1, 47, 5))
    assert line == "expect PHILIPPE id 1 at 47 minutes: accepts"


def test_check_expect_refutes_a_different_minute_count_outside_tolerance():
    reading = {"effects": {"PHILIPPE": CHAIN}}
    line = check_expect(reading, ("PHILIPPE", 1, 45, 5))
    assert line.startswith("expect PHILIPPE id 1 at 45 minutes: refutes")
    assert "holds" in line


def test_check_expect_accepts_within_its_stated_tolerance():
    reading = {"effects": {"PHILIPPE": CHAIN}}
    line = check_expect(reading, ("PHILIPPE", 1, 45, 5), tolerance_minutes=2)
    assert line.endswith(": accepts")


def test_check_expect_refutes_a_character_absent_from_the_slot():
    reading = {"effects": {"PHILIPPE": CHAIN}}
    line = check_expect(reading, ("BRYTWYN", 1, 47, 5))
    assert line == "expect BRYTWYN id 1 at 47 minutes: refutes (BRYTWYN is absent from the slot)"


def test_check_expect_refutes_a_slot_with_no_effects_reading():
    assert check_expect({}, ("PHILIPPE", 1, 47, 5)).endswith(
        "refutes (the slot holds no effects reading)")


# --- amigafoundation.expect_verdict: read the fetched save disk back ---------

def test_amigafoundation_expect_verdict_reads_the_fetched_curse_disk(tmp_path):
    title = amigafoundation.CURSE
    _built, disk = _later_disk(amiga_savegame.CURSE, _bare_curse_state(), "PHILIPPE",
                               title.after_letter)
    run = tmp_path / "run"
    attempt = run / "accept1"
    attempt.mkdir(parents=True)
    disk.save(attempt / "fetched-save.adf")

    accepts = amigafoundation.expect_verdict(
        title, run / "prepare.json", "accept1", ("PHILIPPE", 1, 47, 5))
    assert accepts == "expect PHILIPPE id 1 at 47 minutes: accepts"

    refutes = amigafoundation.expect_verdict(
        title, run / "prepare.json", "accept1", ("PHILIPPE", 1, 40, 5))
    assert refutes.startswith("expect PHILIPPE id 1 at 40 minutes: refutes")


def test_amigafoundation_expect_verdict_names_a_missing_fetched_disk(tmp_path):
    title = amigafoundation.CURSE
    line = amigafoundation.expect_verdict(
        title, tmp_path / "prepare.json", "accept1", ("PHILIPPE", 1, 47, 5))
    assert line == "expect PHILIPPE id 1 at 47 minutes: refutes (no fetched save disk)"


# --- amigasecretsave.expect_verdict: Silver Blades' own camp-save slot -------

def test_amigasecretsave_expect_verdict_reads_the_fetched_boot_disk(tmp_path):
    _built, disk = _later_disk(amiga_savegame.SILVER_BLADES, _bare_silver_blades_state(),
                               "GUY DE VALOIS", amigasecretsave.CAMP_SAVE_LETTER)
    run = tmp_path / "run"
    attempt = run / "accept1"
    attempt.mkdir(parents=True)
    disk.save(attempt / "fetched-df0.adf")

    accepts = amigasecretsave.expect_verdict(
        run / "prepare.json", "accept1", ("GUY DE VALOIS", 1, 47, 5))
    assert accepts == "expect GUY DE VALOIS id 1 at 47 minutes: accepts"


def test_amigasecretsave_expect_verdict_names_a_missing_fetched_disk(tmp_path):
    line = amigasecretsave.expect_verdict(
        tmp_path / "prepare.json", "accept1", ("GUY DE VALOIS", 1, 47, 5))
    assert line == "expect GUY DE VALOIS id 1 at 47 minutes: refutes (no fetched boot disk)"
