"""The C64 Curse and Silver Blades backstab paths, read off their disks.

The tests use the player's overlays at run time and skip cleanly without them.
No game bytes are fixtures in this repository.
"""

from __future__ import annotations

import pytest

from tools.c64 import backstab


def _finding(key: str) -> dict:
    try:
        return backstab.inspect_title(backstab.TITLES[key])
    except SystemExit as exc:
        pytest.skip(str(exc))


@pytest.mark.parametrize(
    "key, expected",
    [
        ("curse-of-the-azure-bonds", {
            "multiplier": "((thief level - 1) // 4) + 2",
            "cap": None,
            "formula": 0xF832,
            "multiplier_store": 0xF83E,
            "predicate_success": 0xF86B,
            "predicate_failure": 0xF86D,
            "predicate_call": 0x8164,
            "multiplier_address": 0xA981,
            "to_hit_adjustment": 0x83E1,
            "damage_application": 0x86B7,
            "multiply_routine": 0x2FB9,
            "regain": 0x20A3,
            "class_mask_table": 0x0B82,
        }),
        ("secret-of-the-silver-blades", {
            "multiplier": "((min(thief level, 14) - 1) // 4) + 2",
            "cap": 14,
            "formula": 0xF4B2,
            "multiplier_store": 0xF4C4,
            "predicate_success": 0xF4F1,
            "predicate_failure": 0xF4F3,
            "predicate_call": 0x8167,
            "multiplier_address": 0xA980,
            "to_hit_adjustment": 0x83F0,
            "damage_application": 0x86CC,
            "multiply_routine": 0x2E6F,
            "regain": 0x154F,
            "class_mask_table": 0x46E5,
        }),
    ],
)
def test_the_attack_path_computes_backstab_from_the_current_thief_slot(
        key, expected):
    """The predicate gates on level_thief and applies its result to damage.

    A fighter/thief therefore uses the same thief slot as a single-class
    thief. ``class_bits`` is absent from the bounded predicate.
    """
    finding = _finding(key)
    assert finding["fields"] == {
        "level": 0x0A0,
        "dual_class_slot": 0x0B9,
        "dual_class_level": 0x0BA,
        "class_levels": 0x0C9,
        "level_thief": 0x0CB,
        "class_bits": 0x0EB,
    }
    assert finding["gate"] == "level_thief > 0"
    assert finding["class_bits_in_predicate"] is False
    for name, value in expected.items():
        assert finding[name] == value


@pytest.mark.parametrize("key", sorted(backstab.TITLES))
def test_a_regained_former_thief_reenters_the_same_level_array(key):
    """The generic regain path restores the old level into its class slot.

    A former thief's slot is zero until the new class strictly passes the
    stored old level. Once restored, the ordinary backstab gate sees it.
    """
    finding = _finding(key)
    assert finding["regained"] == (
        "dual_class_level > 0 and level > dual_class_level restores "
        "class_levels[dual_class_slot]"
    )
    assert finding["fields"]["dual_class_slot"] == 0x0B9
    assert finding["fields"]["dual_class_level"] == 0x0BA
    assert finding["fields"]["class_levels"] + 2 \
        == finding["fields"]["level_thief"]
