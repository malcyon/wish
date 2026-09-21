from __future__ import annotations

"""The two Amiga THAC0 loops, checked against the player's executables."""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import capstone  # noqa: E402
import gamedata  # noqa: E402

from goldbox.amiga_later import party_in_savegame  # noqa: E402
from goldbox.amiga_port import CURSE_DELTAS, SILVER_BLADES_DELTAS  # noqa: E402
from tools.amiga import amigathac0  # noqa: E402
from tools.registry import specimens  # noqa: E402


def _executable(key: str) -> tuple[amigathac0.Title, bytes]:
    title = amigathac0.TITLES[key]
    raw = amigathac0.executable(title)
    if raw is None:
        pytest.skip("needs the player's Amiga disks; set the registry's amiga entry")
    return title, raw


@pytest.mark.parametrize("key", amigathac0.TITLES)
def test_both_recompute_loops_are_still_the_measured_code(key):
    title, raw = _executable(key)
    assert amigathac0.check(raw, title) == []


@pytest.mark.parametrize("key", amigathac0.TITLES)
def test_every_pinned_loop_instruction_is_checked_in_the_executable(key):
    """Changing any behavior-bearing instruction must invalidate the proof."""
    title, raw = _executable(key)
    md = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_M68K_000)
    for loop in (title.guarded, title.unguarded):
        for expected in loop.proof:
            instruction = next(md.disasm(raw[expected.at:], expected.at,
                                         count=1))
            changed = bytearray(raw)
            changed[expected.at + instruction.size - 1] ^= 1
            errors = amigathac0.check(bytes(changed), title)
            assert any(error.startswith(f"{expected.at:#x}:")
                       for error in errors), expected


@pytest.mark.parametrize("key,at,replacement", [
    ("curse-of-the-azure-bonds", 0x38A72, bytes.fromhex("4a03 6f7c")),
    ("secret-of-the-silver-blades", 0x3C822, bytes.fromhex("4a03 6f74")),
])
def test_an_inserted_zero_level_guard_invalidates_the_unguarded_proof(
        key, at, replacement):
    """A level test and branch cannot hide in the index calculation."""
    title, raw = _executable(key)
    changed = bytearray(raw)
    changed[at:at + len(replacement)] = replacement
    mnemonic, operands = amigathac0._instruction(bytes(changed), at + 2)
    assert mnemonic == "ble.b"
    assert operands in ("$38af2", "$3c89a")
    assert any(error.startswith(f"{at:#x}:")
               for error in amigathac0.check(bytes(changed), title))


def test_direct_pc_relative_callers_are_included():
    """The caller scan accepts both PC-relative jsr and bsr encodings."""
    raw = bytes.fromhex("4eba000e 6100000a 4e71 4e71 4e71 4e71 4e75")
    assert amigathac0.direct_callers(raw, 0x10, 0, len(raw)) == [0, 4]


@pytest.mark.parametrize("key", amigathac0.TITLES)
def test_an_unguarded_recompute_floors_a_low_level_magic_user_at_forty(key):
    """The guarded loop writes 39; the import/training loop writes 40."""
    title, raw = _executable(key)
    rows = amigathac0.attack_table(raw, title)
    assert rows["magic-user"][:6] == [39] * 6
    for level in range(1, 6):
        levels = {"magic-user": level}
        assert amigathac0.recompute(rows, levels, guarded=True) == 39
        assert amigathac0.recompute(rows, levels, guarded=False) == 40


@pytest.mark.parametrize("key,folder,specimen,filename,deltas,expected", [
    ("curse-of-the-azure-bonds", "coab-amiga",
     "WISH-SPEC-coab-amiga-converted-resave", "savgamC.dat",
     CURSE_DELTAS, {"MATHEW": (1, 39), "PHILIPPE": (5, 39)}),
    ("secret-of-the-silver-blades", "ssb-amiga",
     "WISH-SPEC-ssb-amiga-adventuring", "savgamB.sav",
     SILVER_BLADES_DELTAS, {"MORGAINE": (9, 41)}),
])
def test_engine_written_records_say_when_the_base_was_not_recomputed(
        key, folder, specimen, filename, deltas, expected):
    """Load/save preserves the base; these records delimit the code claim.

    The Curse file was written by the engine after Wish supplied 39 for its
    two low-level mages. Both stayed 39, so the unguarded base rebuild does
    not run on an ordinary Amiga load/save. Silver Blades' engine-written
    level-9 mage holds its row's 41. The executable, not either specimen,
    establishes what the unguarded recompute does at levels 1--5.
    """
    _executable(key)
    root = gamedata.specimen_root()
    if root is None:
        pytest.skip("needs the verified Amiga specimen tree")
    path = root / folder / specimen / filename
    if not path.is_file():
        pytest.skip(f"needs {specimen}/{filename}")
    provenance = specimens.read_provenance(path.parent / "provenance.toml")
    expected_hash = provenance.get("sha256", {}).get(filename)
    assert expected_hash is not None
    assert specimens.sha256_file(path) == expected_hash
    chars = party_in_savegame(path.read_bytes(), deltas)
    got = {}
    for char in chars:
        levels = char.get("class_levels")
        if sum(bool(level) for level in levels) == 1 and levels[5]:
            got[char.name.strip()] = (levels[5], char.get("thac0_base"))
    assert got == expected
