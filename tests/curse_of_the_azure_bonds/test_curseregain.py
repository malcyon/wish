"""`tools/curse_of_the_azure_bonds/curseregain.py`'s offline half, for `#649`.

The driven half needs an emulator and is not tested here.  What is tested is
`stage_record`'s new `platinum` input, which follows `--xp`'s existing
pattern, and `save_slot_key`, which the D3 boot's `#649` comment found
missing -- `--after`'s save-slot keypress was the literal `k`, ignoring
`--save-to` entirely, so Curse always saved to slot A regardless of what was
asked for.

No game data is read: each fake character record here is built out of
zeroes, which is what a DOS Curse record is before anything writes it.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from goldbox import dos_codec  # noqa: E402
from tools.curse_of_the_azure_bonds import curseregain as cr  # noqa: E402

#: A Curse character record's length (`goldbox/dos_port.py`'s
#: `record_size=422`), which is what `dos_codec.read_character` uses to tell
#: a Curse record from the other three titles.
CURSE_RECORD_SIZE = 422


def _blank_record(path: pathlib.Path) -> None:
    path.write_bytes(bytes(CURSE_RECORD_SIZE))


class TestStagePlatinum:
    def test_platinum_is_unset_by_default(self, tmp_path):
        rec = tmp_path / "CHRDATJ1.SAV"
        _blank_record(rec)
        changed = cr.stage_record(rec, set_level=None, xp=None, platinum=None)
        assert "platinum" not in changed
        assert dos_codec.read_character(rec).get("platinum") == 0

    def test_platinum_writes_the_staged_value(self, tmp_path):
        rec = tmp_path / "CHRDATJ1.SAV"
        _blank_record(rec)
        changed = cr.stage_record(rec, set_level=None, xp=None, platinum=300)
        assert changed["platinum"] == 300
        assert dos_codec.read_character(rec).get("platinum") == 300

    def test_platinum_stages_beside_xp_like_the_existing_option(self, tmp_path):
        rec = tmp_path / "CHRDATJ1.SAV"
        _blank_record(rec)
        changed = cr.stage_record(rec, set_level=None, xp=45001, platinum=300)
        assert changed == {"experience": 45001, "platinum": 300}
        c = dos_codec.read_character(rec)
        assert c.get("experience") == 45001
        assert c.get("platinum") == 300


class TestSaveSlotKey:
    @pytest.mark.parametrize("letter,key", [
        ("F", "f"), ("f", "f"), ("A", "a"), ("J", "j"),
    ])
    def test_a_letter_a_to_j_presses_its_own_key(self, letter, key):
        assert cr.save_slot_key(letter) == key

    @pytest.mark.parametrize("letter", ["K", "k", "Z", "", "AB", "1"])
    def test_a_letter_outside_a_to_j_is_rejected(self, letter):
        with pytest.raises(SystemExit):
            cr.save_slot_key(letter)
