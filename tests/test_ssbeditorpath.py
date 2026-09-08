from __future__ import annotations

"""Secret of the Silver Blades through the editor's write-back path.

`#33 (One Silver Blades session, for the whole editor path)` steps 2, 3 and 4,
which are `docs/139-per-title-validation.md` rows A17, A18 and A19 -- the three
cells that document calls the thinnest part of the README promise. Curse has
each of them in `tests/test_curse.py` and Silver Blades had none until this
file, because the only Silver Blades party the suite could reach was SSI's
shipped demo one.

**Everything here reads a save the game itself wrote.**
`WISH-SPEC-ssb-d-engine-resave` is the C64 engine's own `ENCAMP > SAVE`, made
in VICE on 2026-09-05 for `#193 (Convert a Secret of the Silver Blades DOS save
into a C64 one, which the importer refuses today)`. A round trip proven on a
disk this project wrote would be a round trip proven against our own beliefs;
`.claude/rules/testing.md` is the reason it is that specimen and not another.

Step 5 -- an edited field read off the game's own screens -- cannot be a test,
because it needs the running game. `tools/ssbedit.py` is that run and `#33`
carries what it saw: `BRIGHID`, `STR 12` and `GOLD 4321` on the sheet, on VICE
pool slot 3, 2026-09-08. What is asserted here is the half of that run a
machine with no emulator can check: that the three edits land in the record the
game then read.

Every test skips without the specimen tree, which CI has none of.
"""

import pathlib
import shutil

import pytest
import yaml

from goldbox import c64_save, games
from goldbox.d64 import D64, split_load_address
from goldbox.savegame import load_save
from goldbox.yaml_io import ValueError_, export_save, import_into, to_yaml
from tests import gamedata

SSB = games.SECRET_OF_THE_SILVER_BLADES

#: The engine-written Silver Blades save every test here reads.
SPECIMEN = "ssb-d-engine-resave"


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def make_root():
    from PyQt6.QtWidgets import QMainWindow

    from wish.ui_window import Ui_WishWindow
    root = QMainWindow()
    Ui_WishWindow().setupUi(root)
    return root


def _specimen_disk(name: str = SPECIMEN) -> pathlib.Path:
    """A single-file C64 specimen, checked against its own recorded hash.

    `tests.gamedata.specimen` takes a specimen that is a *directory*; the C64
    ones are a `.D64` beside a `.provenance.toml`, so the hash check is done
    here rather than skipped -- a specimen somebody has edited is no longer
    evidence, which is the whole of `#246`.
    """
    from tools import specimens

    root = gamedata.specimen_root()
    if root is None:
        pytest.skip("needs the specimen tree; see tools/specimens.py and "
                    "$WISH_SPECIMENS")
    found = sorted(root.glob(f"*-c64/WISH-SPEC-{name}.[dD]64"))
    if not found:
        pytest.skip(f"needs the C64 specimen WISH-SPEC-{name}")
    disk = found[0]
    prov = disk.with_suffix("").with_suffix(".provenance.toml")
    if not prov.is_file():
        prov = disk.parent / f"WISH-SPEC-{name}.provenance.toml"
    if not prov.is_file():
        pytest.fail(f"{disk}: no provenance.toml -- not a specimen")
    recorded = specimens.read_provenance(prov).get("sha256", {})
    for filename, expected in recorded.items():
        actual = specimens.sha256_file(disk.parent / filename)
        if actual != expected:
            pytest.fail(f"WISH-SPEC-{name}: {filename} has changed -- recorded "
                        f"{expected[:12]}, now {actual[:12]}; it is no longer "
                        f"evidence. Run tools/specimens.py check")
    return disk


def _copy(path, tmp_path) -> str:
    """The specimen tree is read-only; every test works on its own copy."""
    out = tmp_path / pathlib.Path(path).name
    shutil.copy(path, out)
    out.chmod(0o644)
    return str(out)


def _name_table(path) -> list[bytes]:
    from tools import ssbedit
    return ssbedit.name_table(path)


# --- the specimen is what it claims to be ------------------------------------

def test_the_specimen_is_a_silver_blades_save_the_engine_wrote(tmp_path):
    """Named first because everything below is worthless if it is not.

    Its `provenance.toml` says the C64 game's own `ENCAMP > SAVE`; what can be
    asserted from here is the title and the party, and the hash check in
    `_specimen_disk` is what says nobody has touched it since.
    """
    disk = _copy(_specimen_disk(), tmp_path)
    assert games.detect(D64.open(disk)) is SSB
    _game, sg0, _sg1 = load_save(D64.open(disk))
    assert [s.record.name for s in sg0.characters] == [
        "MORGAINE", "DOMINIC", "MALACHITE", "EPONA", "PAINE", "Guy de Valois"]


# --- A17: an unchanged save writes back byte-identically ----------------------

def test_the_editor_writes_a_silver_blades_save_back_unchanged(app, tmp_path):
    """`#33` step 2, and `docs/139` A17 for the third title.

    Curse's mirror is `test_curse.py::test_the_editor_writes_a_curse_save_
    back_unchanged`. Opening a save and saving it must be a no-op: anything
    the editor cannot round-trip shows up here as a byte that moved.
    """
    from editor.window import EditorBinding

    src = _copy(_specimen_disk(), tmp_path)
    before = pathlib.Path(src).read_bytes()
    window = EditorBinding(make_root(), src)
    assert window.save(interactive=False) == "no changes"
    assert pathlib.Path(src).read_bytes() == before


def test_the_editor_names_the_game_it_has_open(app, tmp_path):
    from editor.window import EditorBinding

    window = EditorBinding(make_root(), _copy(_specimen_disk(), tmp_path))
    assert window._game_label.text() == "Secret of the Silver Blades"


# --- A18: YAML export, re-import, byte-identical disk -------------------------

def _round_trip(src: str, out: str) -> tuple[bytes, bytes, list[str]]:
    """Export to YAML, parse it back as a person's editor would, re-import."""
    data = yaml.safe_load(to_yaml(export_save(src)))
    changes = import_into(src, data, out)
    return (pathlib.Path(src).read_bytes(), pathlib.Path(out).read_bytes(),
            changes)


def test_a_silver_blades_save_disk_survives_yaml_byte_for_byte(tmp_path):
    """`#33` step 3, and `docs/139` A18.

    The strongest single check in the file: D64, PRG, save geometry, slots,
    roster, items, icons and YAML all in one shot, asserting nothing about the
    *meaning* of any field. Curse's mirror is
    `test_curse.py::test_a_curse_save_disk_survives_yaml_byte_for_byte`.
    """
    src = _copy(_specimen_disk(), tmp_path)
    before, after, changes = _round_trip(src, str(tmp_path / "ssb-out.d64"))
    assert changes == []
    assert before == after


def test_the_yaml_says_which_game_it_came_from(tmp_path):
    src = _copy(_specimen_disk(), tmp_path)
    text = to_yaml(export_save(src))
    assert yaml.safe_load(text)["game"] == SSB.key
    assert text.startswith("# Secret of the Silver Blades")


# --- A19: a party of one title will not import into another -------------------

def test_a_silver_blades_party_will_not_import_into_a_pool_of_radiance_disk(
        tmp_path):
    """`#33` step 4, and `docs/139` A19 in the direction that would corrupt.

    The two titles number races and classes differently and lay their saves
    out differently, so a party crossing over would be written as somebody
    else. The refusal names both titles, because a message naming neither is
    a message a player cannot act on.
    """
    data = export_save(_copy(_specimen_disk(), tmp_path))
    target = _copy(gamedata.save_disk("PORSAVE11"), tmp_path)
    with pytest.raises(ValueError_) as exc:
        import_into(target, data, str(tmp_path / "crossed.d64"))
    assert "Secret of the Silver Blades" in str(exc.value)
    assert "Pool of Radiance" in str(exc.value)


def test_a_pool_of_radiance_party_will_not_import_into_a_silver_blades_disk(
        tmp_path):
    """The mirror. Both directions, because a check on one is half a check."""
    data = export_save(_copy(gamedata.save_disk("PORSAVE11"), tmp_path))
    target = _copy(_specimen_disk(), tmp_path)
    with pytest.raises(ValueError_) as exc:
        import_into(target, data, str(tmp_path / "crossed.d64"))
    assert "Pool of Radiance" in str(exc.value)
    assert "Secret of the Silver Blades" in str(exc.value)


# --- step 5's staging, which the emulator run then read off the screens -------

def test_the_three_edits_the_run_read_off_the_screens_land_in_the_record(
        app, tmp_path):
    """`tools/ssbedit.py stage`, pinned against what VICE actually drew.

    The numbers are not decoration. On 2026-09-08, pool slot 3, the game drew
    `BRIGHID` on the party panel, `STR 12` and `GOLD 4321` on the sheet from a
    disk staged with exactly these arguments. If this ever writes something
    else, the run on `#33` stops being evidence about the program that ships.
    """
    from tools import ssbedit

    report = ssbedit.stage(str(_specimen_disk()),
                           str(tmp_path / "edited.D64"),
                           who="MORGAINE", new_name="BRIGHID",
                           gold=4321, strength=12)
    assert report["before"] == {"name": "MORGAINE", "gold": 0, "strength": 17}
    assert report["after"] == {"name": "BRIGHID", "gold": 4321, "strength": 12}
    assert "wrote" in report["save_said"]
    assert report["records_on_disk"][0] == "BRIGHID"


def test_a_lower_case_name_is_folded_to_capitals(app, tmp_path):
    """The C64's charset draws a lower-case letter as its code minus $40.

    A name typed as `Brighid` would come back on the panel as punctuation --
    `Guy de Valois` reads `G59 $% V!,/)3` on this very party's panel, which is
    what that looks like. So `stage` folds, and this is the assertion.
    """
    from tools import ssbedit

    report = ssbedit.stage(str(_specimen_disk()), str(tmp_path / "lower.D64"),
                           who="MORGAINE", new_name="Brighid",
                           gold=None, strength=None)
    assert report["after"]["name"] == "BRIGHID"
    assert report["after"]["gold"] == 0


# --- #435: the second copy of the names, which the editor does not move -------

def test_a_rename_leaves_the_name_table_holding_the_old_name(app, tmp_path):
    """The state `#435` describes, asserted so a fix is visible when it lands.

    Silver Blades keeps the party's names again at payload `+$C00`, sixteen
    bytes each, and `editor/window.py:_write_back` writes only the 256 bytes
    of each save slot. **This test says what is true today and not what ought
    to be true**: when `#435` is fixed it fails, and the fix is to change it
    to assert the table followed the record.

    The index is not the slot. Silver Blades sets `names_in_marching_order`,
    so slot 0 of a six-character party is table entry 5.
    """
    from tools import ssbedit

    out = str(tmp_path / "renamed.D64")
    before = _name_table(_specimen_disk())
    report = ssbedit.stage(str(_specimen_disk()), out, who="MORGAINE",
                           new_name="BRIGHID", gold=None, strength=None)
    assert report["slot"] == 0
    assert report["name_table_index"] == 5, (
        "Silver Blades indexes the name table in marching order")
    assert report["records_on_disk"][0] == "BRIGHID"
    assert report["name_table_entry"] == "MORGAINE"
    assert _name_table(out) == before, "no entry moved at all"


def test_the_container_knows_where_each_titles_name_table_is_indexed(tmp_path):
    """The control for the test above, from the containers rather than a disk.

    Pool of Radiance has no table, so its saves cannot go stale this way;
    Curse's is in slot order and Silver Blades' in marching order, which is
    why a fix has to ask `name_index` rather than assume.
    """
    pool = c64_save.CONTAINERS[games.POOL_OF_RADIANCE.key]
    curse = c64_save.CONTAINERS[games.CURSE_OF_THE_AZURE_BONDS.key]
    ssb = c64_save.CONTAINERS[SSB.key]
    assert pool.name_table is None
    assert curse.name_table == 0xC00 and ssb.name_table == 0xC00
    assert curse.name_index(0, 6) == 0 and curse.name_index(5, 6) == 5
    assert ssb.name_index(0, 6) == 5 and ssb.name_index(5, 6) == 0


def test_the_name_table_read_matches_the_bytes_in_the_file(tmp_path):
    """`ssbedit.name_table` against a hand-cut read of the same payload.

    A helper that computed the wrong offset would make every claim above about
    `+$C00` a claim about the wrong bytes, and it would look like agreement.
    """
    from tools import ssbedit

    disk = _specimen_disk()
    _load, payload = split_load_address(D64.open(str(disk)).read_file(
        SSB.save_file))
    cut = [bytes(payload[0xC00 + i * 16:0xC00 + i * 16 + 16])
           for i in range(8)]
    assert ssbedit.name_table(disk) == cut
    assert [ssbedit.table_name(e) for e in cut][:6] == [
        "Guy de Valois ", "PAINE", "EPONA", "MALACHITE", "DOMINIC", "MORGAINE"]
