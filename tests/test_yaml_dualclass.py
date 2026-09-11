"""The YAML half of a dual-classed character's former class (#256).

Donald's decision, 2026-09-07: `former_levels` -- goldbox/neutral.py's field
for the class and level a dual-classed human left behind -- appears in the
YAML export as a full field like any other, shown and editable. The hazard is
that the game reads exactly the C64's `dual_class_slot`/`dual_class_level`
pair to decide whether a character may ever change class again, and gives no
message a player would see if the pair disagrees with what actually happened
in the game -- so `goldbox/yaml_io.py`'s importer refuses a value it cannot
trust rather than writing it. This file is the regression test for the export
and for each of the importer's refusals.

Specimen-backed: `WISH-SPEC-curse-dual-classed` is PHILIPPE, a Curse of the
Azure Bonds magic-user 6 who dual-classed into fighter at the game's own
training hall, watched being written (`#18`, `#234`). Skips without the
specimen tree. `WISH-SPEC-por-c64-hall-resave` is an ordinary Pool of
Radiance party, which has no former-class field at all.
"""

from __future__ import annotations

import pathlib

import gamedata
import pytest

from goldbox import c64_codec
from goldbox.d64 import D64
from goldbox.savegame import load_save
from goldbox.yaml_io import ValueError_, export_save, import_into


def _specimen_disk(name: str) -> pathlib.Path:
    """A single-file `WISH-SPEC-*.D64` specimen, hash-checked.

    `gamedata.specimen()` is for the directory-shaped kind; this family is
    one file plus one `.provenance.toml` beside it, the same shape
    `tests/test_dualclass_c64.py` already reads.
    """
    from tools import specimens

    root = gamedata.specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py")
    found = sorted((root / "por-c64").glob(f"WISH-SPEC-{name}.[dD]64"))
    if not found:
        pytest.skip(f"needs specimen WISH-SPEC-{name}")
    path = found[0]
    prov = path.with_suffix(".provenance.toml")
    recorded = specimens.read_provenance(prov).get("sha256", {})
    actual = specimens.sha256_file(path)
    if recorded.get(path.name) not in (None, actual):
        pytest.fail(f"WISH-SPEC-{name}: {path.name} has changed since it was "
                    f"recorded; run tools/specimens.py check")
    return path


def CURSE_DUAL_CLASSED() -> str:
    return str(_specimen_disk("curse-dual-classed"))


def POOL_ORDINARY() -> str:
    return str(_specimen_disk("por-c64-hall-resave"))


# --- export ------------------------------------------------------------

def test_a_dual_classed_character_exports_the_former_class():
    data = export_save(CURSE_DUAL_CLASSED())
    philippe = next(e for e in data["party"] if e["name"] == "PHILIPPE")
    assert philippe["former_levels"] == {"magic-user": 6}
    assert philippe["classes"] == ["fighter"]


def test_an_ordinary_character_on_a_title_with_the_field_exports_it_empty():
    data = export_save(CURSE_DUAL_CLASSED())
    shara = next(e for e in data["party"] if e["name"] == "SHARA")
    assert shara["former_levels"] == {}


def test_pool_of_radiance_has_no_field_and_the_key_is_absent():
    data = export_save(POOL_ORDINARY())
    for e in data["party"]:
        assert "former_levels" not in e


def test_the_yaml_document_names_the_field():
    from goldbox.yaml_io import to_yaml
    data = export_save(CURSE_DUAL_CLASSED())
    text = to_yaml(data)
    assert "    former_levels: {magic-user: 6}" in text
    assert "    former_levels: {}" in text  # the other five characters


def test_the_yaml_round_trips_through_yaml_safe_load():
    import yaml

    from goldbox.yaml_io import strip_annotations, to_yaml
    data = export_save(CURSE_DUAL_CLASSED())
    assert yaml.safe_load(to_yaml(data)) == strip_annotations(data)


# --- round trip: the property this module exists for -------------------

def test_a_record_with_a_former_class_round_trips_byte_identical(tmp_path):
    save = CURSE_DUAL_CLASSED()
    data = export_save(save)
    out = tmp_path / "rt.d64"
    changes = import_into(save, data, str(out))
    assert changes == []
    assert out.read_bytes() == pathlib.Path(save).read_bytes()


def test_a_record_with_no_former_class_round_trips_byte_identical(tmp_path):
    save = POOL_ORDINARY()
    data = export_save(save)
    out = tmp_path / "rt.d64"
    changes = import_into(save, data, str(out))
    assert changes == []
    assert out.read_bytes() == pathlib.Path(save).read_bytes()


# --- portrait_head/portrait_body: the sibling of former_levels above ---
#
# `#503 (A C64 character with no sheet portrait arrives in DOS or on the
# Amiga wearing the menu's first head)` made `goldbox.c64_codec.read` leave
# `portrait_head`/`portrait_body` unset -- not `0` -- for a record whose
# body byte is `0x00`, the same way this title leaves `former_levels`
# unset rather than `{}` when a title has no such field. `entry_for` has
# to answer the same way former_levels does: omit the key rather than
# write `null`, or the importer is handed a value `Record.set` cannot
# encode. `CURSE_DUAL_CLASSED`'s whole party has no portrait; `POOL_
# ORDINARY`'s does.

def test_a_character_with_no_portrait_exports_with_the_pair_absent():
    data = export_save(CURSE_DUAL_CLASSED())
    for e in data["party"]:
        assert "portrait_head" not in e, e["name"]
        assert "portrait_body" not in e, e["name"]


def test_a_character_with_a_real_portrait_exports_the_pair():
    data = export_save(POOL_ORDINARY())
    for e in data["party"]:
        assert e["portrait_head"] == 0x00
        assert e["portrait_body"] == 0x01


def test_a_record_with_no_portrait_round_trips_and_stays_unset(tmp_path):
    """The direct regression test: importing the unedited export of a
    no-portrait party must not crash, and the pair must still read as
    unset afterwards rather than reappearing as the menu's first head."""
    save = CURSE_DUAL_CLASSED()
    data = export_save(save)
    out = tmp_path / "rt.d64"
    changes = import_into(save, data, str(out))
    assert changes == []
    assert out.read_bytes() == pathlib.Path(save).read_bytes()

    game, sg, _sg1 = load_save(D64.open(str(out)))
    for slot in sg.characters:
        read_back = c64_codec.read(slot.record, game=game)
        assert "portrait_head" not in read_back, slot.record.name
        assert "portrait_body" not in read_back, slot.record.name


# --- the importer refuses rather than writing what it is given ---------

def _edited(mutate):
    data = export_save(CURSE_DUAL_CLASSED())
    mutate(data)
    return data


def _shara(data):
    return next(e for e in data["party"] if e["name"] == "SHARA")


def test_an_unknown_class_name_is_refused(tmp_path):
    data = _edited(lambda d: (_shara(d).update(
        classes=["fighter"], former_levels={"wizard": 3})))
    with pytest.raises(ValueError_, match="not a class"):
        import_into(CURSE_DUAL_CLASSED(), data, str(tmp_path / "o.d64"))


def test_a_level_outside_the_byte_is_refused(tmp_path):
    data = _edited(lambda d: (_shara(d).update(
        classes=["fighter"], former_levels={"cleric": 999})))
    with pytest.raises(ValueError_, match="outside what a class can reach"):
        import_into(CURSE_DUAL_CLASSED(), data, str(tmp_path / "o.d64"))


def test_a_zero_level_is_refused_as_half_written(tmp_path):
    """The hand-edited-file case: a class named with no real level. Zero is
    the neutral field's own 'not dual-classed' sentinel, so a zero entry is
    not a value for 'never left this class', it is a mistake."""
    data = _edited(lambda d: (_shara(d).update(
        classes=["fighter"], former_levels={"cleric": 0})))
    with pytest.raises(ValueError_, match="half-written"):
        import_into(CURSE_DUAL_CLASSED(), data, str(tmp_path / "o.d64"))


def test_a_non_numeric_level_is_refused_as_half_written(tmp_path):
    data = _edited(lambda d: (_shara(d).update(
        classes=["fighter"], former_levels={"cleric": "five"})))
    with pytest.raises(ValueError_, match="half-written"):
        import_into(CURSE_DUAL_CLASSED(), data, str(tmp_path / "o.d64"))


def test_the_former_class_cannot_equal_the_only_current_class(tmp_path):
    data = _edited(lambda d: _shara(d).update(former_levels={"cleric": 5}))
    with pytest.raises(ValueError_, match="only current class"):
        import_into(CURSE_DUAL_CLASSED(), data, str(tmp_path / "o.d64"))


def test_a_former_class_with_no_class_change_is_refused(tmp_path):
    data = _edited(lambda d: _shara(d).update(former_levels={"fighter": 3}))
    with pytest.raises(ValueError_, match="no change to classes"):
        import_into(CURSE_DUAL_CLASSED(), data, str(tmp_path / "o.d64"))


def test_two_former_classes_are_refused(tmp_path):
    data = _edited(lambda d: (_shara(d).update(
        classes=["magic-user"],
        former_levels={"fighter": 3, "thief": 2})))
    with pytest.raises(ValueError_, match="hold only one"):
        import_into(CURSE_DUAL_CLASSED(), data, str(tmp_path / "o.d64"))


def test_former_levels_must_be_a_mapping(tmp_path):
    data = _edited(lambda d: (_shara(d).update(
        classes=["fighter"], former_levels=["cleric"])))
    with pytest.raises(ValueError_, match="mapping"):
        import_into(CURSE_DUAL_CLASSED(), data, str(tmp_path / "o.d64"))


def test_a_title_with_no_field_refuses_a_hand_added_one(tmp_path):
    save = POOL_ORDINARY()
    data = export_save(save)
    data["party"][0]["classes"] = ["magic-user"]
    data["party"][0]["former_levels"] = {"fighter": 3}
    with pytest.raises(ValueError_, match="has no field"):
        import_into(save, data, str(tmp_path / "o.d64"))


# --- a legitimate edit writes the pair, and the record reads it back ----

def test_a_justified_edit_writes_the_pair_and_reads_back(tmp_path):
    save = CURSE_DUAL_CLASSED()
    data = export_save(save)
    _shara(data).update(classes=["fighter"], levels={"fighter": 1},
                        former_levels={"cleric": 6})
    out = tmp_path / "o.d64"
    changes = import_into(save, data, str(out))
    assert any("former_levels" in c for c in changes)

    img = D64.open(str(out))
    game, sg, _sg1 = load_save(img)
    rec = sg.slot(1).record
    assert rec.name == "SHARA"
    assert rec.get("dual_class_slot") == 1          # cleric's slot
    assert rec.get("dual_class_level") == 6
    read_back = c64_codec.read(rec, game=game)
    assert read_back.get("former_levels") == {"cleric": 6}


def test_clearing_a_former_class_writes_the_sentinel(tmp_path):
    """The reverse edit: the character regains no history, so the pair goes
    back to the sentinel the game itself uses (`dual_class_level == 0`)."""
    save = CURSE_DUAL_CLASSED()
    data = export_save(save)
    philippe = next(e for e in data["party"] if e["name"] == "PHILIPPE")
    philippe["classes"] = ["magic-user"]           # a class change to justify it
    philippe["levels"] = {"magic-user": 6}
    philippe["former_levels"] = {}
    out = tmp_path / "o.d64"
    import_into(save, data, str(out))
    img = D64.open(str(out))
    _game, sg, _sg1 = load_save(img)
    rec = sg.slot(0).record
    assert rec.get("dual_class_slot") == 0
    assert rec.get("dual_class_level") == 0
