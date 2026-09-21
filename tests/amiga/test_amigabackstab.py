"""Every Amiga title's backstab multiplier, read off the player's disks.

The executables come from `gamedisks.yaml`'s `amiga` entry at run time and
everything here skips without them, which is what CI does. No game bytes are
fixtures in this repository.
"""

from __future__ import annotations

import pytest

from tools.amiga import amigabackstab

#: What the instruction read settles, one row a title. `record_reads` are the
#: record displacements the arithmetic itself loads, former slot first.
EXPECTED = {
    "pool-of-radiance": {
        "form": "divide",
        "formula": 0xB8DE,
        "predicate": 0xD704,
        "predicate_call": 0xB8CC,
        "predicate_callers": [0xB8CC, 0xC906, 0xC992],
        "record_reads": [0x09E],
        "regain_call": None,
        "regain_multiply": None,
        "regain_add": None,
        "current_thief": 0x09E,
        "former_thief": None,
        "clamp": None,
        "damage": "$14da.l",
        "effective_level": "class_levels[thief]",
        "multiplier": "(effective thief level // 4) + 2",
    },
    "curse-of-the-azure-bonds": {
        "form": "inline",
        "formula": 0x6FA4,
        "predicate": 0x8DE2,
        "predicate_call": 0x6F82,
        "predicate_callers": [0x6F82, 0x7F0C, 0x7F8C],
        "record_reads": [0x118, 0x110],
        "regain_call": 0x6F8E,
        "regain_multiply": 0x6F9A,
        "regain_add": 0x6FA2,
        "current_thief": 0x110,
        "former_thief": 0x118,
        "clamp": None,
        "damage": "-$32c0(a4)",
        "effective_level": (
            "class_levels[thief] + former_class_levels[thief] * regained"),
        "multiplier": "((effective thief level - 1) // 4) + 2",
    },
    "secret-of-the-silver-blades": {
        "form": "inline",
        "formula": 0x7FD0,
        "predicate": 0x9E26,
        "predicate_call": 0x7FA2,
        "predicate_callers": [0x7FA2, 0x8DAC, 0x8E4A],
        "record_reads": [0x0B9, 0x0B2],
        "regain_call": 0x7FB2,
        "regain_multiply": 0x7FC2,
        "regain_add": 0x7FCE,
        "current_thief": 0x0B2,
        "former_thief": 0x0B9,
        "clamp": None,
        "damage": "-$1a39(a4)",
        "effective_level": (
            "class_levels[thief] + former_class_levels[thief] * regained"),
        "multiplier": "((effective thief level - 1) // 4) + 2",
    },
    "pools-of-darkness": {
        "form": "helper",
        "formula": 0x7FD8,
        "predicate": 0x9F4C,
        "predicate_call": 0x7FBC,
        "predicate_callers": [0x7FBC, 0x905E, 0x90FC],
        "record_reads": [],
        "regain_call": None,
        "regain_multiply": None,
        "regain_add": None,
        "current_thief": None,
        "former_thief": None,
        "clamp": 5,
        "damage": "-$152e(a4)",
        "effective_level": "the shared class-level routine for class 6",
        "multiplier": "min(((effective thief level - 1) // 4) + 2, 5)",
    },
}


#: Reading every disk image for a title takes seconds, so each executable is
#: read once per process and every test below works on that copy.
_RAW: dict[str, bytes | None] = {}


def _executable(key: str) -> bytes:
    if key not in _RAW:
        _RAW[key] = amigabackstab.executable(amigabackstab.TITLES[key])
    raw = _RAW[key]
    if raw is None:
        pytest.skip(f"No Amiga {amigabackstab.TITLES[key].title} executable "
                    f"on any disk here.")
    return raw


def _finding(key: str) -> dict:
    return amigabackstab.inspect(_executable(key), amigabackstab.TITLES[key])


def test_every_amiga_title_is_read():
    """All four Amiga ports, which is every one the editor opens."""
    assert sorted(amigabackstab.TITLES) == sorted(EXPECTED)


@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_the_amiga_engine_computes_backstab_from_the_thief_level(key):
    """No Amiga title stores a bonus; each divides a thief level for one.

    The arithmetic is the only run of its kind in the executable, the call
    before it is tested and branched on, and the factor reaches the damage
    byte the same instructions read it from.
    """
    finding = _finding(key)
    for name, value in EXPECTED[key].items():
        assert finding[name] == value, name


@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_the_predicate_serves_three_call_sites(key):
    """Damage, the to-hit adjustment and the message share one gate."""
    finding = _finding(key)
    assert len(finding["predicate_callers"]) == 3
    assert finding["predicate_call"] in finding["predicate_callers"]


def test_pool_of_radiance_alone_does_not_subtract_a_level_first():
    """Its steps fall at 4, 8 and 12 where the later titles' fall at 5, 9, 13.

    That is the same difference `docs/221-thief-abilities-in-dos-pool-of-
    radiance.md` reads out of the DOS build of the same title.
    """
    assert _finding("pool-of-radiance")["form"] == "divide"
    for key in ("curse-of-the-azure-bonds", "secret-of-the-silver-blades",
                "pools-of-darkness"):
        assert _finding(key)["form"] != "divide"


def _with_nops(key: str, at: int, size: int) -> bytes:
    """A copy of the executable with `size` bytes at `at` turned into `nop`s."""
    raw = bytearray(_executable(key))
    raw[at:at + size] = b"\x4e\x71" * (size // 2)
    return bytes(raw)


@pytest.mark.parametrize("key", ["curse-of-the-azure-bonds",
                                 "secret-of-the-silver-blades"])
@pytest.mark.parametrize("step, size", [("regain_call", 4),
                                        ("regain_multiply", 2),
                                        ("regain_add", 2)])
def test_the_regain_arithmetic_is_read_and_not_assumed(key, step, size):
    """Erasing the regain call, the multiply or the add is refused.

    The engine adds the former thief slot times the regain call's result to
    the current slot before it subtracts one; each of the three instructions
    is what makes that sentence true.
    """
    at = _finding(key)[step]
    title = amigabackstab.TITLES[key]
    with pytest.raises(ValueError):
        amigabackstab.inspect(_with_nops(key, at, size), title)


def test_a_missing_title_is_reported_and_check_controls_the_exit_status(
        monkeypatch, capsys):
    """A title with no executable is a report unless ``--check`` is asked."""
    monkeypatch.setattr(amigabackstab, "builds", lambda title: {})
    assert amigabackstab.main(["--title", "pools-of-darkness"]) == 0
    assert amigabackstab.main(
        ["--title", "pools-of-darkness", "--check"]) == 1
    assert "No Amiga Pools of Darkness executable" in capsys.readouterr().out
