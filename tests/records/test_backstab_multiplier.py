"""The backstab multiplier `goldbox.backstab` computes, pinned per title and port.

No game data is read: each expectation is the arithmetic the engine does,
written out per level, so a title given another title's rule fails here.
"""

from __future__ import annotations

import pytest

from goldbox import backstab, titles
from goldbox.neutral import NeutralCharacter

LEVELS = (1, 4, 5, 8, 9, 12, 13, 16, 17, 20)

#: Levels 1, 4, 5, 8, 9, 12, 13, 16, 17, 20 for each arithmetic.
_NO_SUBTRACT = (2, 3, 3, 4, 4, 5, 5, 6, 6, 7)
_STANDARD = (2, 2, 3, 3, 4, 4, 5, 5, 6, 6)
_CAPPED = (2, 2, 3, 3, 4, 4, 5, 5, 5, 5)

EXPECTED = {
    ("pool-of-radiance", "DOS"): _NO_SUBTRACT,
    ("curse-of-the-azure-bonds", "DOS"): _STANDARD,
    ("secret-of-the-silver-blades", "DOS"): _STANDARD,
    ("pools-of-darkness", "DOS"): _CAPPED,
    ("pool-of-radiance", "C64"): _STANDARD,
    ("curse-of-the-azure-bonds", "C64"): _STANDARD,
    ("secret-of-the-silver-blades", "C64"): _CAPPED,
    ("gateway-to-the-savage-frontier", "C64"): _STANDARD,
    ("champions-of-krynn", "C64"): _STANDARD,
    ("death-knights-of-krynn", "C64"): _CAPPED,
    ("pool-of-radiance", "Amiga"): _NO_SUBTRACT,
    ("curse-of-the-azure-bonds", "Amiga"): _STANDARD,
    ("secret-of-the-silver-blades", "Amiga"): _STANDARD,
    ("pools-of-darkness", "Amiga"): _CAPPED,
}

HUMAN = {t.key: next(code for code, name in t.races if name == "human")
         for t in titles.TITLES}
NOT_HUMAN = 1  # dwarf or elf in every title's table but Silver Blades' (elf)

SUMMING = [("curse-of-the-azure-bonds", "DOS"),
           ("secret-of-the-silver-blades", "DOS"),
           ("curse-of-the-azure-bonds", "Amiga"),
           ("secret-of-the-silver-blades", "Amiga")]
LARGEST = [("pools-of-darkness", "DOS"), ("pools-of-darkness", "Amiga")]


def character(key: str, port: str, levels: dict, former: dict | None = None,
              race: int | None = None) -> NeutralCharacter:
    char = NeutralCharacter(port, game=key)
    char.set("levels", levels, "test")
    char.set("former_levels", former or {}, "test")
    char.set("race", HUMAN[key] if race is None else race, "test")
    return char


def test_every_measured_pair_has_a_table() -> None:
    assert set(backstab.RULES) == set(EXPECTED)


@pytest.mark.parametrize("key,port", sorted(EXPECTED))
def test_table_per_level(key: str, port: str) -> None:
    got = tuple(
        backstab.backstab_multiplier(
            character(key, port, {"thief": level}))
        for level in LEVELS)
    assert got == EXPECTED[(key, port)]


@pytest.mark.parametrize("key,port", sorted(EXPECTED))
def test_a_fighter_thief_uses_the_thief_slot(key: str, port: str) -> None:
    char = character(key, port, {"fighter": 9, "thief": 5})
    assert backstab.backstab_multiplier(char) == EXPECTED[(key, port)][2]


@pytest.mark.parametrize("key,port", sorted(EXPECTED))
def test_no_thief_level_is_no_backstab(key: str, port: str) -> None:
    char = character(key, port, {"fighter": 9})
    assert backstab.backstab_multiplier(char) is None
    assert backstab.effective_thief_level(char) == 0


def test_the_level_cap_edge_in_the_two_capped_c64_titles() -> None:
    for key in ("secret-of-the-silver-blades", "death-knights-of-krynn"):
        got = [backstab.backstab_multiplier(
            character(key, "C64", {"thief": lv})) for lv in (12, 13, 14, 15, 40)]
        assert got == [4, 5, 5, 5, 5]
        assert backstab.effective_thief_level(
            character(key, "C64", {"thief": 40})) == 14


def test_the_uncapped_c64_titles_keep_climbing() -> None:
    for key in ("pool-of-radiance", "curse-of-the-azure-bonds",
                "gateway-to-the-savage-frontier", "champions-of-krynn"):
        assert backstab.backstab_multiplier(
            character(key, "C64", {"thief": 21})) == 7


@pytest.mark.parametrize("port", ["DOS", "Amiga"])
def test_pools_of_darkness_clamps_the_multiplier_after_the_arithmetic(
        port: str) -> None:
    key = "pools-of-darkness"
    got = [backstab.backstab_multiplier(character(key, port, {"thief": lv}))
           for lv in (16, 17, 40)]
    assert got == [5, 5, 5]
    # The level itself is not clamped, unlike the C64 titles that cap at 14.
    assert backstab.effective_thief_level(
        character(key, port, {"thief": 40})) == 40


@pytest.mark.parametrize("key,port", SUMMING + LARGEST)
def test_a_regained_former_thief_counts_once_the_new_class_passes_it(
        key: str, port: str) -> None:
    former = {"thief": 5}
    at_level = character(key, port, {"fighter": 5}, former)
    past = character(key, port, {"fighter": 6}, former)
    assert backstab.backstab_multiplier(at_level) is None
    assert backstab.effective_thief_level(past) == 5
    assert backstab.backstab_multiplier(past) == 3


@pytest.mark.parametrize("key,port", SUMMING + LARGEST)
def test_a_non_human_never_regains_a_former_thief(key: str, port: str) -> None:
    char = character(key, port, {"fighter": 9}, {"thief": 5}, race=NOT_HUMAN)
    assert HUMAN[key] != NOT_HUMAN
    assert backstab.backstab_multiplier(char) is None


@pytest.mark.parametrize("key,port", SUMMING)
def test_a_record_with_both_slots_sums_them(key: str, port: str) -> None:
    char = character(key, port, {"fighter": 7, "thief": 6}, {"thief": 6})
    assert backstab.effective_thief_level(char) == 12
    assert backstab.backstab_multiplier(char) == 4


@pytest.mark.parametrize("key,port", LARGEST)
def test_a_record_with_both_slots_takes_the_larger(key: str, port: str) -> None:
    char = character(key, port, {"fighter": 7, "thief": 6}, {"thief": 6})
    assert backstab.effective_thief_level(char) == 6
    assert backstab.backstab_multiplier(char) == 3


@pytest.mark.parametrize("key", [k for k, p in EXPECTED if p == "C64"])
def test_the_c64_reads_the_current_slot_alone(key: str) -> None:
    former_only = character(key, "C64", {"fighter": 9}, {"thief": 5})
    assert backstab.backstab_multiplier(former_only) is None
    regained = character(key, "C64", {"fighter": 9, "thief": 5}, {"thief": 5})
    assert backstab.effective_thief_level(regained) == 5
    assert backstab.backstab_multiplier(regained) == 3


def test_pool_of_radiance_reads_no_former_slot() -> None:
    for port in ("DOS", "Amiga"):
        char = character("pool-of-radiance", port, {"fighter": 9},
                         {"thief": 5})
        assert backstab.backstab_multiplier(char) is None


def test_title_and_port_default_from_the_record_and_can_be_overridden() -> None:
    char = character("curse-of-the-azure-bonds", "C64", {"thief": 17})
    assert backstab.backstab_multiplier(char) == 6
    assert backstab.backstab_multiplier(
        char, "secret-of-the-silver-blades") == 5
    assert backstab.backstab_multiplier(char, port="Amiga") == 6


def test_a_title_object_stands_for_its_key() -> None:
    char = character("secret-of-the-silver-blades", "C64", {"thief": 17})
    assert backstab.backstab_multiplier(
        char, titles.SECRET_OF_THE_SILVER_BLADES) == 5


@pytest.mark.parametrize("key,port", [
    ("gateway-to-the-savage-frontier", "DOS"),
    ("champions-of-krynn", "Amiga"),
    ("pool-of-radiance", "Palm"),
    (None, "DOS"),
])
def test_a_pair_with_no_measured_rule_is_refused(key, port) -> None:
    char = NeutralCharacter(port, game=key)
    char.set("levels", {"thief": 5}, "test")
    with pytest.raises(ValueError, match="no backstab rule"):
        backstab.backstab_multiplier(char)
