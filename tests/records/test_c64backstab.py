"""Every C64 title's backstab path, read off the player's own disks.

The tests use the player's overlays at run time and skip cleanly without them.
No game bytes are fixtures in this repository.
"""

from __future__ import annotations

import pytest

from tools.c64 import backstab

#: Everything the instruction read settles, one row a title.
EXPECTED = {
    "pool-of-radiance": {
        "record": 0x6B00,
        "multiplier": "((thief level - 1) // 4) + 2",
        "cap": None,
        "formula": 0x06A8,
        "multiplier_store": 0x06B4,
        "predicate_success": 0x06DD,
        "predicate_failure": 0x06DF,
        "predicate_call": 0x068B,
        "multiplier_address": 0x2B7C,
        "to_hit_adjustment": 0x11F9,
        "to_hit_number": 0xA4F0,
        "damage_application": 0x06E1,
        "damage_roll": 0xA4F7,
        "damage_clamp": None,
        "multiply_routine": 0x2E30,
        "regain": None,
        "class_mask_table": None,
        "class_masks": (),
    },
    "curse-of-the-azure-bonds": {
        "record": 0x7C00,
        "multiplier": "((thief level - 1) // 4) + 2",
        "cap": None,
        "formula": 0xF832,
        "multiplier_store": 0xF83E,
        "predicate_success": 0xF86B,
        "predicate_failure": 0xF86D,
        "predicate_call": 0x8164,
        "multiplier_address": 0xA981,
        "to_hit_adjustment": 0x83E1,
        "to_hit_number": 0x9458,
        "damage_application": 0x86B7,
        "damage_roll": 0x945F,
        "damage_clamp": None,
        "multiply_routine": 0x2FB9,
        "regain": 0x20A3,
        "class_mask_table": 0x0B82,
        "class_masks": (1, 2, 4, 8, 16, 32, 64, 128),
    },
    "secret-of-the-silver-blades": {
        "record": 0x7C00,
        "multiplier": "((min(thief level, 14) - 1) // 4) + 2",
        "cap": 14,
        "formula": 0xF4B2,
        "multiplier_store": 0xF4C4,
        "predicate_success": 0xF4F1,
        "predicate_failure": 0xF4F3,
        "predicate_call": 0x8167,
        "multiplier_address": 0xA980,
        "to_hit_adjustment": 0x83F0,
        "to_hit_number": 0x9458,
        "damage_application": 0x86CC,
        "damage_roll": 0x945F,
        "damage_clamp": 0xF0,
        "multiply_routine": 0x2E6F,
        "regain": 0x154F,
        "class_mask_table": 0x46E5,
        "class_masks": (1, 2, 4, 8, 16, 32, 64, 128),
    },
    "gateway-to-the-savage-frontier": {
        "record": 0x7C00,
        "multiplier": "((thief level - 1) // 4) + 2",
        "cap": None,
        "formula": 0xF81B,
        "multiplier_store": 0xF827,
        "predicate_success": 0xF854,
        "predicate_failure": 0xF856,
        "predicate_call": 0x8164,
        "multiplier_address": 0xA981,
        "to_hit_adjustment": 0x83E5,
        "to_hit_number": 0x9458,
        "damage_application": 0x86BB,
        "damage_roll": 0x945F,
        "damage_clamp": None,
        "multiply_routine": 0x2FB9,
        "regain": 0x20A4,
        "class_mask_table": 0x0B82,
        "class_masks": (1, 2, 4, 8, 16, 32, 64, 128),
    },
    "champions-of-krynn": {
        "record": 0x7C00,
        "multiplier": "((thief level - 1) // 4) + 2",
        "cap": None,
        "formula": 0xF41B,
        "multiplier_store": 0xF427,
        "predicate_success": 0xF458,
        "predicate_failure": 0xF45A,
        "predicate_call": 0x8167,
        "multiplier_address": 0xA980,
        "to_hit_adjustment": 0x83E8,
        "to_hit_number": 0x9458,
        "damage_application": 0x86DB,
        "damage_roll": 0x945F,
        "damage_clamp": None,
        "multiply_routine": 0x3007,
        "regain": None,
        "class_mask_table": None,
        "class_masks": (),
    },
    "death-knights-of-krynn": {
        "record": 0x7C00,
        "multiplier": "((min(thief level, 14) - 1) // 4) + 2",
        "cap": 14,
        "formula": 0xF47C,
        "multiplier_store": 0xF48E,
        "predicate_success": 0xF4BF,
        "predicate_failure": 0xF4C1,
        "predicate_call": 0x8167,
        "multiplier_address": 0xA840,
        "to_hit_adjustment": 0x83E8,
        "to_hit_number": 0x9458,
        "damage_application": 0x86D9,
        "damage_roll": 0x945F,
        "damage_clamp": 0xF0,
        "multiply_routine": 0x2FB0,
        "regain": None,
        "class_mask_table": None,
        "class_masks": (),
    },
}

#: The titles whose `GEN` restores a dual-classed character's old level.
WITH_REGAIN = ("curse-of-the-azure-bonds", "secret-of-the-silver-blades",
               "gateway-to-the-savage-frontier")

#: The byte multiply's overlay base, derived from the call the damage path
#: makes and checked against what `tools/c64/coldread.py` established.
LIBRARY_BASE = {"pool-of-radiance": 0x2C48}
LIBRARY_BASE_LATER = 0x2DC8


def _finding(key: str) -> dict:
    try:
        return backstab.inspect_title(backstab.TITLES[key])
    except SystemExit as exc:
        pytest.skip(str(exc))


def test_every_c64_title_is_read():
    """All six C64 titles, not only the two later Realms ones."""
    assert sorted(backstab.TITLES) == sorted(EXPECTED)


@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_the_attack_path_computes_backstab_from_the_current_thief_slot(key):
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
    assert finding["thief_level_gate"] == "level_thief > 0"
    assert finding["class_bits_in_predicate"] is False
    for name, value in EXPECTED[key].items():
        assert finding[name] == value, name


@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_the_multiply_routine_lands_at_the_library_base_coldread_found(key):
    """The damage call resolves to the byte multiply in the library overlay.

    The base is derived from the call rather than assumed, so a wrong overlay
    or a wrong address chain cannot agree with the base `coldread.py` found
    for the same title by an unrelated route.
    """
    finding = _finding(key)
    library = finding["files"]["multiply"]
    assert finding["bases"][library] == LIBRARY_BASE.get(key,
                                                         LIBRARY_BASE_LATER)


@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_a_regained_former_thief_reenters_the_same_level_array(key):
    """Three titles restore the old level into its class slot; three cannot.

    Where the path exists, a former thief's slot is zero until the new class
    strictly passes the stored old level, and the ordinary thief-level gate
    then sees it. In Pool of Radiance and the two Krynn titles no instruction
    on the disks names `dual_class_level` at all, so there is no such path.
    """
    finding = _finding(key)
    if key in WITH_REGAIN:
        assert finding["regained"] == (
            "dual_class_level > 0 and level > dual_class_level restores "
            "class_levels[dual_class_slot]"
        )
        assert finding["files"]["regain"] == "GEN"
    else:
        assert finding["regained"] == (
            "no instruction anywhere names dual_class_level")
        assert finding["files"]["regain"] is None
    assert finding["fields"]["class_levels"] + 2 \
        == finding["fields"]["level_thief"]


@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_the_multiplier_byte_is_read_by_the_to_hit_and_damage_sites(key):
    """The census of the byte includes both places the finding names."""
    finding = _finding(key)
    addresses = {address for _, address, _ in finding["references"]}
    assert finding["damage_application"] in addresses
    assert finding["to_hit_adjustment"] - 5 in addresses


@pytest.mark.parametrize("check, expected", [(False, 0), (True, 1)])
def test_missing_disks_are_reported_and_check_controls_the_exit_status(
        tmp_path, capsys, check, expected):
    """A missing title is a report unless ``--check`` asks for a failure."""
    args = ["--title", "curse-of-the-azure-bonds", "--disks", str(tmp_path)]
    if check:
        args.append("--check")
    assert backstab.main(args) == expected
    assert "No readable Curse of the Azure Bonds side" in capsys.readouterr().out


def test_a_missing_title_does_not_stop_the_other_titles(monkeypatch, capsys):
    """``--check`` reports one failure after inspecting every requested title."""
    inspected = []
    printed = []

    def inspect(title, _root):
        inspected.append(title.game.key)
        if title.game.key == "curse-of-the-azure-bonds":
            raise SystemExit("no Curse disks")
        return {"title": title.game.key}

    monkeypatch.setattr(backstab, "inspect_title", inspect)
    monkeypatch.setattr(backstab, "_print", lambda finding: printed.append(
        finding["title"]))
    assert backstab.main(["--check"]) == 1
    assert inspected == list(backstab.TITLES)
    assert printed == [key for key in backstab.TITLES
                       if key != "curse-of-the-azure-bonds"]
    assert "curse-of-the-azure-bonds: no Curse disks" \
        in capsys.readouterr().out
