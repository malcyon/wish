"""`tools/cursepaladin.py`'s offline half, for `#409`.

The driven half needs an emulator and is not tested here; what is tested is
everything a wrong answer would quietly poison the run with -- which record
offsets the class fields are read at, that an ability is staged into **both**
of the record's two arrays, and that `stage` writes nothing it was not asked
for.

No game data is read: the save disk each test uses is built here out of
zeroes, which is what `SAVEAZURE` is before a party is written into it.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from goldbox.d64 import D64  # noqa: E402
from tools import cursepaladin as cp  # noqa: E402

#: `SAVEAZURE`'s payload length, from `goldbox/c64_save.py` by way of
#: `tools/cursetrain.py`'s geometry: eight 256-byte slots at `$400` and the
#: name table at `$C00`.
PAYLOAD = 7424
LOAD = 0x4B00


def _blank_save(tmp_path: pathlib.Path, names: dict[int, str]) -> pathlib.Path:
    """A save disk with a zeroed `SAVEAZURE` and the named slots occupied."""
    body = bytearray(PAYLOAD)
    for slot, name in names.items():
        off = cp.SLOT0 + slot * cp.SLOT_SIZE
        body[off + 0x072] = 7                      # race: human
        body[off + 0x0A0] = 6                      # level
        body[off + 0x0CF] = 6                      # level_paladin
        body[off + 0x0EB] = 0x40                   # class_bits: paladin
        for i, ability in enumerate((15, 15, 16, 15, 15, 17)):
            body[off + cp.ABILITY_NOW + i] = ability
            body[off + cp.ABILITY_COPY + i] = ability
        blob = name.encode("ascii").ljust(16, b"\0")
        body[0xC00 + slot * 16:0xC00 + (slot + 1) * 16] = blob
    disk = D64.blank(b"CURSE SAVE")
    disk.write_file(b"SAVEAZURE", LOAD.to_bytes(2, "little") + bytes(body))
    path = tmp_path / "save.d64"
    disk.save(path)
    return path


class _Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_the_class_fields_are_read_at_the_records_own_offsets(tmp_path):
    """`class_bits` at `0x0EB` and the paladin's level at `0x0CF`."""
    path = _blank_save(tmp_path, {5: "MATHEW"})
    _, payload = cp.payload_of(path.read_bytes())
    base = cp.SLOT0 + 5 * cp.SLOT_SIZE
    fields = cp.describe(payload[base:base + cp.SLOT_SIZE])
    assert fields["class_bits"] == 0x40
    assert fields["level_paladin"] == 6
    assert fields["race"] == 7
    assert fields["cha"] == 17


def test_an_ability_is_staged_into_both_of_the_records_arrays(tmp_path):
    """`GEN $1E9C` copies `0x065` down to `0x014`, so a stage that wrote one
    of them would leave a character no roll could make."""
    path = _blank_save(tmp_path, {4: "MARK"})
    out = tmp_path / "staged.d64"
    cp.stage(_Args(base=str(path), out=str(out), give=["MARK:wis=18"],
                   repair=False))
    _, payload = cp.payload_of(out.read_bytes())
    base = cp.SLOT0 + 4 * cp.SLOT_SIZE
    assert payload[base + cp.ABILITY_NOW + 2] == 18
    assert payload[base + cp.ABILITY_COPY + 2] == 18


def test_stage_writes_nothing_it_was_not_asked_for(tmp_path):
    """One field named, one byte pair changed, and the rest byte for byte."""
    path = _blank_save(tmp_path, {4: "MARK", 5: "MATHEW"})
    out = tmp_path / "staged.d64"
    cp.stage(_Args(base=str(path), out=str(out), give=["MARK:wis=18"],
                   repair=False))
    _, before = cp.payload_of(path.read_bytes())
    _, after = cp.payload_of(out.read_bytes())
    moved = {i for i in range(len(before)) if before[i] != after[i]}
    base = cp.SLOT0 + 4 * cp.SLOT_SIZE
    assert moved == {base + cp.ABILITY_NOW + 2, base + cp.ABILITY_COPY + 2}


def test_a_name_the_disk_does_not_carry_is_refused(tmp_path):
    path = _blank_save(tmp_path, {5: "MATHEW"})
    with pytest.raises(SystemExit):
        cp.stage(_Args(base=str(path), out=str(tmp_path / "x.d64"),
                       give=["NOBODY:wis=18"], repair=False))
    with pytest.raises(SystemExit):
        cp.find_slot(str(path), "NOBODY")
    assert cp.find_slot(str(path), "mathew") == 5


def test_the_live_class_is_the_one_non_zero_level_slot():
    """What `run` reads to know which slot to stage the regain into."""
    assert cp.live_class({"level_cleric": 1}) == "cleric"
    assert cp.live_class({"level_fighter": 1, "level_paladin": 6}) is None
    assert cp.live_class({}) is None


def test_the_class_slots_match_the_bit_the_engine_ors_back():
    """`GEN $20A3` reads `$0B82,X` -- `01 02 04 08 10 20 40 80` -- with the
    same index it writes `class_levels[X]` with, so a paladin's slot 6 is the
    `$40` this ticket is about."""
    from goldbox import classcode

    for name, slot in cp.CLASS_SLOT.items():
        assert classcode.CLASS_BIT_FOR_NAME[name] == 1 << slot
