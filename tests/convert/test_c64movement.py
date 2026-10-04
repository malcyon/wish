"""A Pool of Radiance character's C64 movement is computed, not copied.

The C64's encounter menu FLEE reads roster `+0x1B` before any fight rebuilds
it, so a stale source value has to be replaced by what the C64 roster rebuild
(`LIBRARY $3729`) would store: `goldbox.derive.expected_movement`. Without the
ITEMS type table the copy stays, and every other title keeps it.
"""

from __future__ import annotations

from goldbox import c64_codec, derive
from goldbox.items import TYPE_LOCATION, ItemType
from goldbox.neutral import NeutralCharacter


def _char(game=None, gold: int = 600, inventory=None) -> NeutralCharacter:
    """Strength 10 (allowance 0), base movement 12 and a stale stored 12."""
    if game is None:
        char = NeutralCharacter("test", source="a made-up character")
    else:
        char = NeutralCharacter("test", source="a made-up character",
                                game=game)
    char.set("levels", {"fighter": 3}, "made up")
    char.set("strength", 10, "made up")
    char.set("exceptional_strength", 0, "made up")
    char.set("thac0_base", 8, "made up")
    char.set("movement", 12, "made up")
    char.set("movement_current", 12, "made up: the source's stale byte")
    char.set("gold", gold, "made up")
    if inventory is not None:
        char.set("inventory", inventory, "made up")
    return char


def _armour_types() -> dict[int, ItemType]:
    raw = bytearray(16)
    raw[TYPE_LOCATION] = 2
    return {5: ItemType(5, bytes(raw))}


def _plate() -> bytes:
    """Type 5, readied (+6 bit 7), 450 weight, no plus."""
    raw = bytearray(16)
    raw[0] = 5
    raw[6] = 0x80
    raw[8], raw[9] = 450 & 0xFF, 450 >> 8
    return bytes(raw)


def test_a_table_makes_movement_the_rules_value_not_the_stale_copy():
    """600 coins over an allowance of 0 is 512 or more excess: the band 9."""
    rec, rep = c64_codec.write(_char(), item_types={})
    assert rec.get("roster_movement") == 9
    assert "C64 roster rebuild" in rep.sources[0x11B]
    assert not any("movement_current: copied" in w for w in rep.warnings)


def test_no_table_keeps_the_copy_and_says_so():
    rec, rep = c64_codec.write(_char())
    assert rec.get("roster_movement") == 12
    assert "no item-type table" in rep.sources[0x11B]
    assert not any("movement_current: copied" in w for w in rep.warnings)


def test_readied_plate_armour_sets_movement_six():
    rec, _ = c64_codec.write(_char(gold=0, inventory=[_plate()]),
                             item_types=_armour_types())
    assert rec.get("roster_movement") == 6


def test_another_title_keeps_the_copy_even_with_a_table():
    char = _char(game="curse-of-the-azure-bonds")
    rec, _ = c64_codec.write(char, item_types={})
    assert rec.get("roster_movement") == 12


def test_the_field_disposition_no_longer_says_copied():
    assert not c64_codec.field_disposition()["movement_current"] \
        .startswith("copied")


def test_a_rule_that_blocks_falls_back_to_the_copy_and_warns(monkeypatch):
    def block(*_args):
        raise ValueError("an item's type is not in the table")
    monkeypatch.setattr(derive, "expected_movement", block)
    rec, rep = c64_codec.write(_char(), item_types={})
    assert rec.get("roster_movement") == 12
    assert "copied rather than recomputed" in rep.sources[0x11B]
    assert ("movement_current: copied, an item's type is not in the table"
            in rep.warnings)


def test_a_pool_character_with_no_movement_current_gets_no_computed_byte():
    """The rule runs only when the source has a `movement_current` to replace,
    so the byte stays zero and the report says it had no source."""
    char = _char()
    del char.fields["movement_current"]
    rec, rep = c64_codec.write(char, item_types={})
    assert rec.get("roster_movement") == 0
    assert "no test source" in rep.sources[0x11B]
