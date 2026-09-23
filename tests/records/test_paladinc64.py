"""A paladin's cure-disease and lay-on-hands rows in the C64 save's own
64-slot effect arrays, written and read through `goldbox.c64_codec.write`
and `read`'s three keyword arguments (#600, #626, #628).

`tests/records/test_layonhandsconvert.py` is the DOS/Amiga side of the same
neutral fields; this file is the C64 side, where the spent state is a row
rather than a node.
"""

from __future__ import annotations

import pytest

from goldbox import c64_codec, effects, neutral
from goldbox.c64_port import CURSE_OF_THE_AZURE_BONDS, SECRET_OF_THE_SILVER_BLADES
from goldbox.record import CharacterRecord

CLOCK = 222
PAYLOAD_SIZE = 0x1C00


def _char(port: str, game, *, level: int = 11, cures: int = 3,
         heal_minutes: int | None = None,
         running_effects: list | None = None) -> neutral.NeutralCharacter:
    char = neutral.NeutralCharacter(port, source="built here", game=game)
    fields = {
        "name": "GALAHAD", "level": level, "levels": {"paladin": level},
        "class_bits": 0x40, "paladin_cures": cures,
    }
    if heal_minutes is not None:
        fields["lay_on_hands_minutes"] = heal_minutes
    if running_effects is not None:
        fields["running_effects"] = running_effects
    for name, value in fields.items():
        char.set(name, value, "built here")
    return char


def test_a_full_paladin_with_no_node_writes_the_bytes_and_no_lines():
    char = _char("DOS", CURSE_OF_THE_AZURE_BONDS, level=11, cures=3)
    payload = bytearray(PAYLOAD_SIZE)
    rec, rep = c64_codec.write(char, payload=payload, party_slot=2,
                              clock_minutes=CLOCK)
    assert (rec.get("paladin_cures"), rec.get("lay_on_hands_uses")) == (3, 1)
    assert effects.active_effects(bytes(payload)) == ()
    for name in ("paladin_cures", "lay_on_hands_minutes", "running_effects"):
        assert not any(name in d for d in rep.dropped)
        assert not any(name in w for w in rep.losses)


def test_a_spent_lay_on_hands_writes_a_row_in_the_highest_free_slot():
    char = _char("DOS", CURSE_OF_THE_AZURE_BONDS, level=11, cures=3,
                heal_minutes=1000)
    payload = bytearray(PAYLOAD_SIZE)
    rec, rep = c64_codec.write(char, payload=payload, party_slot=2,
                              clock_minutes=CLOCK)
    assert rec.get("lay_on_hands_uses") == 0
    duration = effects.closest_duration(1000, CLOCK)
    assert duration == 0x91
    assert (payload[63], payload[0x040 + 63], payload[0x080 + 63],
            payload[0x280 + 63]) == (140, 2, duration, 0xC1)
    assert not any("lay_on_hands_minutes" in d for d in rep.dropped)


def test_silver_blades_writes_its_own_lay_on_hands_id():
    char = _char("DOS", SECRET_OF_THE_SILVER_BLADES, level=11, cures=3,
                heal_minutes=1000)
    payload = bytearray(PAYLOAD_SIZE)
    rec, _ = c64_codec.write(char, payload=payload, party_slot=2,
                             clock_minutes=CLOCK)
    assert payload[63] == 109


def test_a_cure_node_becomes_a_row_and_the_rest_of_running_effects_drops():
    node = effects.RunningEffect(141, 4000, 0, 1).to_record()
    bless = effects.RunningEffect(1, 500, 0, 1).to_record()
    char = _char("DOS", CURSE_OF_THE_AZURE_BONDS, level=11, cures=3,
                running_effects=[node, bless])
    payload = bytearray(PAYLOAD_SIZE)
    rec, rep = c64_codec.write(char, payload=payload, party_slot=2,
                              clock_minutes=CLOCK)
    assert rec.get("paladin_cures") == 3
    rows = [(payload[i], payload[0x040 + i], payload[0x080 + i],
            payload[0x280 + i]) for i in range(0x40) if payload[i]]
    assert rows == [(141, 2, 0xC3, 0xC7)]
    running_lines = [d for d in rep.dropped if d.startswith("running_effects")]
    assert len(running_lines) == 1


def test_a_mage_gets_zero_and_zero_no_rows_no_lines():
    char = neutral.NeutralCharacter("DOS", source="built here",
                                    game=CURSE_OF_THE_AZURE_BONDS)
    for name, value in {
        "name": "MERLIN", "level": 5, "levels": {"magic-user": 5},
        "class_bits": 0x04, "paladin_cures": 0,
        "lay_on_hands_minutes": 0,
    }.items():
        char.set(name, value, "built here")
    payload = bytearray(PAYLOAD_SIZE)
    rec, rep = c64_codec.write(char, payload=payload, party_slot=2,
                              clock_minutes=CLOCK)
    assert (rec.get("paladin_cures"), rec.get("lay_on_hands_uses")) == (0, 0)
    assert effects.active_effects(bytes(payload)) == ()
    for name in ("paladin_cures", "lay_on_hands_minutes", "running_effects"):
        assert not any(name in d for d in rep.dropped)
        assert not any(name in w for w in rep.losses)


def test_with_no_payload_a_spent_lay_on_hands_is_one_loss_and_stays_may_heal():
    char = _char("DOS", CURSE_OF_THE_AZURE_BONDS, level=11, cures=3,
                heal_minutes=1000)
    rec, rep = c64_codec.write(char)
    assert rec.get("lay_on_hands_uses") == 1
    assert len(rep.losses) == 1


def test_clock_minutes_reads_the_worldstate_digit_order():
    assert effects.clock_minutes((0, 2, 4, 3, 0, 0)) == 222


def test_reading_a_lay_on_hands_row_gives_the_minutes_left_for_its_own_slot():
    payload = bytearray(PAYLOAD_SIZE)
    effects.write_effect(payload, 63, 140, 2, 0xC1, 0xC1)
    rec = CharacterRecord.blank()
    mine = c64_codec.read(rec, game=CURSE_OF_THE_AZURE_BONDS, payload=payload,
                          party_slot=2, clock_minutes=CLOCK)
    assert mine.get("lay_on_hands_minutes") == effects.remaining_minutes(
        0xC1, CLOCK)
    other = c64_codec.read(rec, game=CURSE_OF_THE_AZURE_BONDS, payload=payload,
                           party_slot=3, clock_minutes=CLOCK)
    assert other.get("lay_on_hands_minutes") == 0


def test_reading_a_cure_row_gives_one_running_effects_entry():
    payload = bytearray(PAYLOAD_SIZE)
    effects.write_effect(payload, 62, 141, 2, 0xC7, 0xC7)
    rec = CharacterRecord.blank()
    out = c64_codec.read(rec, game=CURSE_OF_THE_AZURE_BONDS, payload=payload,
                         party_slot=2, clock_minutes=CLOCK)
    minutes = effects.remaining_minutes(0xC7, CLOCK)
    assert out.get("running_effects") == [
        effects.RunningEffect(141, minutes, 0, 1).to_record()]


def test_the_specimen_paladins_cure_row_reads_back_as_a_running_effect():
    """`WISH-SPEC-curse-600-paladin6-cured`: PALADIN holds 1 cure and one row,
    id 141, duration and magnitude `$C7` (`tests/records/test_curedisease.py::
    test_the_game_writes_the_cure_row_the_writer_is_asked_for`).  Before this fix
    `c64_party` gives `running_effects` None and drops "Lay on hands"."""
    import gamedata

    from goldbox import c64_port, dos_codec

    root = gamedata.specimen_root()
    path = None if root is None else (
        root / "coab-c64" / "WISH-SPEC-curse-600-paladin6-cured.D64")
    if path is None or not path.is_file():
        pytest.skip("needs the specimen WISH-SPEC-curse-600-paladin6-cured")
    from goldbox.d64 import D64
    from goldbox.savegame import load_save
    _, save, _ = load_save(D64.from_bytes(path.read_bytes()))
    payload = save.to_bytes()
    clock = effects.clock_minutes(tuple(payload[0xC6:0xCC]))
    party, _icons = dos_codec.c64_party(
        payload, None, game=c64_port.CURSE_OF_THE_AZURE_BONDS)
    paladin = next(c for c in party if c.get("name", "").strip() == "PALADIN")
    assert paladin.get("running_effects") == [
        effects.RunningEffect(141, effects.remaining_minutes(0xC7, clock), 0,
                              1).to_record()]
    assert not any("Lay on hands" in d for d in paladin.dropped)
