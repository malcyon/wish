"""`tools/dos/ssbimport.py`: the pure half of the Silver Blades import driver.

The driven half needs DOSBox and the player's archives and is proven by a run,
not here.  What is pinned: that the two inputs of the experiment differ in
exactly the Curse byte the importer reads, that the Silver Blades fields are
read at `goldbox.dos_port`'s offsets, and that a capture finds the imported
character by name and keeps only its own slot's files.  Every record here is
built in the test; the one test that reads a specimen skips without the tree.
"""

from __future__ import annotations

import pytest

from tests import gamedata
from tools.dos import ssbimport as si


def _curse(name: bytes = b"MATHEW", fill: int = 0x11) -> bytearray:
    rec = bytearray([fill]) * si.CURSE_RECORD
    rec[0] = len(name)
    rec[1:1 + len(name)] = name
    rec[si.CURSE_FORMER_CLASS] = 0
    return rec


def _ssb(name: bytes = b"MATHEW") -> bytearray:
    rec = bytearray(si.SSB_RECORD)
    rec[0] = len(name)
    rec[1:1 + len(name)] = name
    return rec


def test_the_offsets_are_the_ones_the_importer_reads():
    # docs/229: Curse 0x0F9 is copied to Silver Blades 0x101, and
    # paladin_cures is 0x6D in the 439-byte record.
    assert si.CURSE_FORMER_CLASS == 0x0F9
    assert si.SSB_FORMER_CLASS == 0x101
    assert si.SSB["paladin_cures"] == (0x6D, 1)


def test_staging_moves_only_the_former_class_byte():
    rec = bytes(_curse())
    for value in (0, 3, 4):
        staged = si.stage_guy(rec, value)
        moved = [i for i in range(si.CURSE_RECORD) if staged[i] != rec[i]]
        assert moved == ([] if value == 0 else [si.CURSE_FORMER_CLASS])
        assert staged[si.CURSE_FORMER_CLASS] == value


def test_staging_without_a_value_leaves_the_record_alone():
    rec = _curse()
    rec[si.CURSE_FORMER_CLASS] = 7
    assert si.stage_guy(bytes(rec), None) == bytes(rec)


@pytest.mark.parametrize("word", ["keep", "KEEP", " Keep "])
def test_the_former_class_flag_takes_keep_as_no_override(word):
    """`--former-class keep` parses to the same `None` `stage_guy` treats as
    "leave the record's own byte alone" -- the way a Wish-converted Curse
    character already carries the class he left (#614)."""
    assert si._former_class_arg(word) is None


def test_the_former_class_flag_still_takes_a_byte():
    assert si._former_class_arg("3") == 3
    assert si._former_class_arg("0x04") == 4


@pytest.mark.parametrize("size", [si.CURSE_RECORD - 1, si.SSB_RECORD])
def test_staging_refuses_a_record_that_is_not_curse(size):
    with pytest.raises(ValueError, match="422"):
        si.stage_guy(bytes(size), 3)


def test_staging_refuses_a_value_that_is_not_a_byte():
    with pytest.raises(ValueError):
        si.stage_guy(bytes(_curse()), 256)


@pytest.mark.parametrize("name, stem", [
    ("MATHEW", "MATHEW"),
    ("PHILIPPE THE BOLD", "PHILIPPE"),
    ("FE'THOS", "FETHOS"),
    ("'!", "GUY"),
])
def test_the_file_stem_is_a_dos_name(name, stem):
    assert si.guy_stem(name) == stem


def test_effect_nodes_split_at_nine_and_keep_a_partial_tail():
    sfx = (bytes([8, 0, 0, 0xFF, 0]) + bytes(4)
           + bytes([110, 0x60, 0x27, 0, 1]) + bytes(4) + b"\x01\x02")
    nodes = si.effect_nodes(sfx)
    assert [n.get("id") for n in nodes] == [8, 110, None]
    assert nodes[1]["minutes"] == 0x2760
    assert nodes[2] == {"partial": "0102"}


def test_summary_reads_cures_window_and_node_eight():
    rec = _ssb()
    rec[0x6D] = 1
    rec[si.SSB_FORMER_CLASS] = 3
    rec[0x111 + 5] = 6                  # class_levels[magic-user]
    rec[0x118 + 3] = 5                  # former_class_levels[paladin]
    rec[0x12C:0x130] = (45000).to_bytes(4, "little")
    out = si.summarise(bytes(rec), bytes([8, 0, 0, 0xFF, 0]) + bytes(4))
    assert out["name"] == "MATHEW"
    assert out["paladin_cures"] == 1
    assert out["former_class_byte"] == 3
    assert out["class_levels"][5] == 6
    assert out["former_class_levels"][3] == 5
    assert out["experience"] == 45000
    assert out["paladin_node"] is True


def test_summary_with_no_effect_file_says_so():
    out = si.summarise(bytes(_ssb()), None)
    assert out["sfx_present"] is False
    assert out["effect_ids"] == []
    assert out["paladin_node"] is False


def test_capture_finds_the_character_by_name_and_keeps_only_its_slot(tmp_path):
    save = tmp_path / "SAVE"
    save.mkdir()
    (save / "CHRDATC1.SAV").write_bytes(bytes(_ssb(b"OTHER")))
    (save / "CHRDATC2.SAV").write_bytes(bytes(_ssb()))
    (save / "CHRDATC2.SFX").write_bytes(bytes([8]) + bytes(8))
    (save / "SAVGAMC.DAT").write_bytes(bytes(5469))
    (save / "CHRDATD1.SAV").write_bytes(bytes(_ssb()))
    (save / "MATHEW.GUY").write_bytes(bytes(_curse()))
    out = si.capture(save, "C", "MATHEW", tmp_path / "out")
    assert out["record_file"] == "CHRDATC2.SAV"
    assert out["effect_ids"] == [8]
    assert out["clock_digits"] == [0] * 6
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == [
        "CHRDATC1.SAV", "CHRDATC2.SAV", "CHRDATC2.SFX", "SAVGAMC.DAT"]


def test_capture_says_when_the_character_is_missing(tmp_path):
    save = tmp_path / "SAVE"
    save.mkdir()
    (save / "CHRDATC1.SAV").write_bytes(bytes(_ssb(b"OTHER")))
    assert "error" in si.capture(save, "C", "MATHEW", tmp_path / "out")


REGAINED = "curse-408-regained-paladin"


def _regained_paladin():
    """The engine-written Curse record of MATHEW, a human magic-user 6 who
    was a paladin 5, from the specimen tree; skips without it."""
    from tools.registry import specimens

    root = gamedata.specimen_root()
    where = root and root / "coab-dos" / f"WISH-SPEC-{REGAINED}"
    if not where or not where.is_dir():
        pytest.skip(f"needs specimen WISH-SPEC-{REGAINED}; see "
                    f"tools/registry/specimens.py and $WISH_SPECIMENS")
    rec = where / "CHRDATJ1.SAV"
    recorded = specimens.read_provenance(where / "provenance.toml")["sha256"]
    if specimens.sha256_file(rec) != recorded[rec.name]:
        pytest.fail(f"WISH-SPEC-{REGAINED}/{rec.name} has changed; run "
                    f"tools/registry/specimens.py check")
    return rec.read_bytes()


def test_the_two_runs_of_the_specimen_differ_in_one_byte():
    rec = _regained_paladin()
    assert si.record_name(rec) == "MATHEW"
    assert rec[si.CURSE_FORMER_CLASS] == 0      # DOS Curse never writes it
    three = si.stage_guy(rec, 3)
    zero = si.stage_guy(rec, 0)
    assert zero == rec
    assert [i for i in range(si.CURSE_RECORD) if three[i] != zero[i]] == [
        si.CURSE_FORMER_CLASS]
