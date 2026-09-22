"""What each C64 title's own code does with record byte `0x0B8`.

`tools/c64/flags0b8.py` classifies every absolute reference to the control
byte in a title's files. These pin the findings of
`docs/232-the-c64-control-byte-per-title.md` against the player's own disks,
and skip per title when the registry has none:

* only Pool of Radiance writes the trainer flag, and it writes the whole byte;
* every title reads bit 7 as "the engine drives him" and the low seven bits
  as a morale that is doubled, clamped at 100 everywhere but Pool of Radiance;
* no title hands a companion back to the player except Pool of Radiance's
  berserk cure, which keeps bit 0 and nothing else.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.c64 import flags0b8  # noqa: E402

POOL = "pool-of-radiance"
LATER = [key for key in flags0b8.RECORD if key != POOL]

TRAINER = "write, $01 (the trainer flag, whole byte)"
CLAMPED = "read, morale: & $7F, doubled, clamped at 100"
UNCLAMPED = "read, morale: & $7F, doubled, no clamp"
BERSERK_ENDS = "write, & $01 when at or above $FE (berserk ends)"

#: Writes that leave bit 7 set whatever the byte held, or that run only for a
#: character whose bit 7 is already clear.
KEEPS_CONTROL = {
    "write, bit 7 set, low bits kept (joins the party)",
    "write, script argument halved | $80 (joins with a morale)",
    "write, script argument | $80, not halved (joins with a morale)",
    "write, $00 for a player character only (import reset)",
}


def _sites(key: str):
    if not flags0b8.files(key):
        pytest.skip(f"no {key} disks here")
    return flags0b8.sites(key)


def _kinds(key: str) -> list[str]:
    return [s.kind for s in _sites(key)]


@pytest.mark.parametrize("key", list(flags0b8.RECORD))
def test_every_write_is_an_idiom_the_write_up_names(key):
    unclassified = [s for s in _sites(key) if s.kind == "write, unclassified"]
    assert unclassified == []


def test_pool_of_radiance_writes_the_trainer_flag_from_the_modify_screen():
    """`GEN` stores `$01` twice -- after an ability step and after a hit-point
    step -- and restores its saved copy twice, and it steps the ability array
    with both `INC` and `DEC`."""
    gen = [s for s in _sites(POOL) if s.file == "GEN"]
    assert [s.kind for s in gen].count(TRAINER) == 2
    assert [s.kind for s in gen].count("write, restores a saved copy") == 2
    steps = {m for name, _, m in flags0b8.trainer_steps(POOL) if name == "GEN"}
    assert steps == {"INC", "DEC"}


@pytest.mark.parametrize("key", LATER)
def test_no_later_title_writes_the_trainer_flag(key):
    kinds = _kinds(key)
    assert TRAINER not in kinds
    assert not [s for s in flags0b8.sites(key)
                if s.file == "GEN" and s.kind.startswith("write")]
    assert set(k for k in kinds if k.startswith("write")) <= KEEPS_CONTROL


def test_pool_of_radiance_doubles_the_morale_and_does_not_clamp_it():
    kinds = _kinds(POOL)
    assert kinds.count(UNCLAMPED) == 1
    assert CLAMPED not in kinds


@pytest.mark.parametrize("key", LATER)
def test_the_later_titles_double_the_morale_and_clamp_it_at_100(key):
    kinds = _kinds(key)
    assert CLAMPED in kinds
    assert UNCLAMPED not in kinds


def test_only_pool_of_radiance_hands_control_back_and_keeps_bit_0():
    ends = [s for s in _sites(POOL) if s.kind == BERSERK_ENDS]
    assert [(s.file, s.mnemonic) for s in ends] == [("SQRPACI64", "STA")]


@pytest.mark.parametrize("key", LATER)
def test_no_later_title_clears_bit_7(key):
    assert BERSERK_ENDS not in _kinds(key)


@pytest.mark.parametrize("key", LATER)
def test_the_later_titles_refuse_to_add_a_companion_from_the_roster(key):
    _sites(key)
    assert flags0b8.refuses_npcs(key)


def test_pool_of_radiance_has_no_refusal():
    _sites(POOL)
    assert flags0b8.refuses_npcs(POOL) == []


def test_morale_decodes_as_the_engine_doubles_it():
    assert flags0b8.morale(0x00) is None
    assert flags0b8.morale(0x01) is None
    assert flags0b8.morale(0x80) == 0
    assert flags0b8.morale(0xB1) == 98
    assert flags0b8.morale(0xB2) == 100
    assert flags0b8.morale(0xFF) == 254
