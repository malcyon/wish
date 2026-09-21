"""The backstab gate and multiplier in the three later DOS engines.

The proof reads ``GAME.OVR`` and each title's loader from the player's
Forgotten Realms Archives installation. It skips cleanly without those files.
No game bytes are fixtures in this repository.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.dos import backstab  # noqa: E402


def _finding(stem: str) -> dict:
    title = backstab.TITLES[stem]
    try:
        game = backstab.find_game(title)
    except FileNotFoundError as exc:
        pytest.skip(str(exc))
    needed = [game / "GAME.OVR", game / title.loader]
    if not all(path.is_file() for path in needed):
        pytest.skip(f"{stem} needs GAME.OVR and {title.loader} in the "
                    f"DOS archives")
    return backstab.inspect_dir(game, title)


@pytest.mark.parametrize(
    "stem, expected",
    [
        ("CURSE", {
            "fields": {"race": 0x074, "human_race": 7,
                       "class_levels": 0x109, "former_class_levels": 0x111,
                       "current_thief": 0x10F,
                       "former_thief": 0x117, "former_level": 0x0E6,
                       "class_bits": 0x12B},
            "formula": 0x1356C,
            "current_read": 0x13579,
            "damage_mul": 0x1358F,
            "predicate": 0x15C3F,
            "predicate_callers": [0x13554, 0x149FC, 0x14AA0],
            "current_test": 0x15C84,
            "former_test": 0x15C8F,
            "regain_calls": [0x15C9D, 0x13561],
            "regain_far": (0x00FE, 0x0052),
            "regain_helper": 0x3C031,
            "current_level_routine": 0x3BFC2,
            "former_level_cmp": 0x3C044,
        }),
        ("SECRET", {
            "fields": {"race": 0x06B, "human_race": 6,
                       "class_levels": 0x111, "former_class_levels": 0x118,
                       "current_thief": 0x117,
                       "former_thief": 0x11E, "former_level": 0x0EF,
                       "class_bits": 0x130},
            "formula": 0x150C2,
            "current_read": 0x150CF,
            "damage_mul": 0x150E8,
            "predicate": 0x1766D,
            "predicate_callers": [0x150AA, 0x1626F, 0x16314],
            "current_test": 0x176AC,
            "former_test": 0x176B7,
            "regain_calls": [0x176C5, 0x150B7],
            "regain_far": (0x0164, 0x0057),
            "regain_helper": 0x3CBB6,
            "current_level_routine": 0x3CB44,
            "former_level_cmp": 0x3CBC9,
        }),
    ],
)
def test_the_attack_path_reads_the_level_arrays_and_computes_the_multiplier(
        stem, expected):
    """The gate, damage, to-hit and message sites share one predicate.

    A current thief qualifies immediately. A former thief qualifies only
    once the regain helper returns true. The damage path multiplies by
    ``((effective level - 1) // 4) + 2``, where effective level is the current
    thief slot plus the former thief slot times that same helper's result.
    ``class_bits`` is not read by the bounded predicate routine.
    """
    finding = _finding(stem)
    for key, value in expected.items():
        assert finding[key] == value
    assert finding["fields"]["class_bits"] not in finding["predicate_fields"]
    assert finding["gate"] == (
        "class_levels[thief] > 0 or "
        "(former_class_levels[thief] > 0 and regained)")
    assert finding["effective_level"] == (
        "class_levels[thief] + former_class_levels[thief] * regained")
    assert finding["regained"] == "human and active class level > former_level"
    assert finding["multiplier"] == "((effective thief level - 1) // 4) + 2"


def test_pools_of_darkness_takes_its_thief_level_from_a_shared_helper():
    """The last DOS title computes the same multiplier by a different route.

    One class-level routine answers `max(current, regained former)` for any
    class, and the caller clamps the multiplier itself at 5 rather than
    clamping the level. The same predicate still serves damage, the to-hit
    adjustment and the backstab message, and does not read ``class_bits``.
    """
    finding = _finding("DARKNESS")
    assert finding["fields"] == {
        "race": 0x0AD, "human_race": 5,
        "class_levels": 0x151, "former_class_levels": 0x158,
        "current_thief": 0x157, "former_thief": 0x15E,
        "former_level": 0x139, "class_bits": 0x17B,
    }
    assert finding["formula"] == 0x1E86F
    assert finding["thief_level_call"] == 0x1E867
    assert finding["multiplier_clamp"] == 0x1E87B
    assert finding["clamp"] == 5
    assert finding["damage_mul"] == 0x1E88A
    assert finding["damage_word"] == 0xA7D8
    assert finding["predicate"] == 0x20D62
    assert finding["predicate_gate"] == 0x20DAA
    assert finding["predicate_callers"] == [0x1E85A, 0x1FBE1, 0x1FC86]
    assert finding["level_helper_far"] == (0x0102, 0x0048)
    assert finding["level_helper"] == 0x392EE
    assert finding["regain_helper"] == 0x38C8A
    assert finding["current_level_routine"] == 0x38C19
    assert finding["former_level_cmp"] == 0x38C9D
    assert finding["fields"]["class_bits"] not in finding["predicate_fields"]
    assert finding["gate"] == "effective thief level > 0"
    assert finding["effective_level"] == (
        "max(class_levels[thief], former_class_levels[thief] * regained)")
    assert finding["regained"] == "human and active class level > former_level"
    assert finding["multiplier"] == (
        "min(((effective thief level - 1) // 4) + 2, 5)")
