"""Save As to DOS stops, before anything is written, when the DOS game folder
is another title's: the writer takes the area's `ECL<n>.DAX` number from the
folder, and another title's number is one this title's game cannot load."""

from __future__ import annotations

import pathlib
import shutil

import pytest
from gamedata import specimen_root, synthetic_save

from editor import convert, saveplan
from editor.roster import Party
from goldbox import c64_port, titles

LAUNCHERS = {"pool-of-radiance": ("START.EXE", "POOL.CFG"),
             "curse-of-the-azure-bonds": ("START.EXE", "CURSE.CFG"),
             "secret-of-the-silver-blades": ("START.EXE", "BLADES.CFG"),
             "pools-of-darkness": ("START.BAT", "POOL4.CFG")}

SPECIMEN = ("ssb-c64/WISH-SPEC-ssb-wish8-strength-twice-dos-to-c64-"
            "engine-save.D64")


def folder_of(where, key, name=None):
    """An empty stand-in for `key`'s DOS game folder: its launcher and its
    configuration file, which is what the title is recognised by."""
    folder = pathlib.Path(where) / (name or key)
    folder.mkdir(parents=True)
    for held in LAUNCHERS[key]:
        (folder / held).write_bytes(b"")
    return folder


def c64_party(tmp_path, key):
    path = synthetic_save(tmp_path, game=c64_port.by_key(key))
    return Party(str(path))


def save_as(party, folder, out):
    source = convert.Source.detect(party.path)
    assets = saveplan.Assets(dos_folder=folder)
    return saveplan.prepare_save_as(party, "dos", out, assets), source


def test_a_silver_blades_save_stops_on_the_pool_of_radiance_folder(tmp_path):
    party = c64_party(tmp_path, "secret-of-the-silver-blades")
    folder = folder_of(tmp_path, "pool-of-radiance")
    out = tmp_path / "out"
    with pytest.raises(saveplan.WrongGameFolder) as stopped:
        save_as(party, folder, out)
    assert stopped.value.folder_title == "pool-of-radiance"
    assert stopped.value.save_title == "secret-of-the-silver-blades"
    assert not out.exists()


def test_a_pool_save_stops_on_the_curse_folder_not_in_the_writer(tmp_path):
    party = c64_party(tmp_path, "pool-of-radiance")
    folder = folder_of(tmp_path, "curse-of-the-azure-bonds")
    with pytest.raises(saveplan.WrongGameFolder):
        save_as(party, folder, tmp_path / "out")


def test_the_stop_is_one_the_window_reports_as_a_conversion_blocked(tmp_path):
    """`editor.window` answers a `DroppedFields` with its existing sentence."""
    assert issubclass(saveplan.WrongGameFolder, saveplan.DroppedFields)


def test_a_folder_is_known_by_its_files_whatever_it_is_called(tmp_path):
    party = c64_party(tmp_path, "secret-of-the-silver-blades")
    folder = folder_of(tmp_path, "pool-of-radiance", name="Games")
    with pytest.raises(saveplan.WrongGameFolder):
        save_as(party, folder, tmp_path / "out")


def test_a_folder_that_names_no_title_is_not_stopped_here(tmp_path):
    """It behaves as before: the check says nothing and the route goes on to
    whatever it needed, here the missing source disks."""
    party = c64_party(tmp_path, "secret-of-the-silver-blades")
    unknown = tmp_path / "somewhere"
    unknown.mkdir()
    assert titles.dos_folder_title(unknown) is None
    with pytest.raises(saveplan.MissingAssets):
        save_as(party, unknown, tmp_path / "out")


def test_the_save_titles_own_folder_passes_the_check(tmp_path):
    party = c64_party(tmp_path, "secret-of-the-silver-blades")
    folder = folder_of(tmp_path, "secret-of-the-silver-blades")
    source = convert.Source.detect(party.path)
    saveplan.check_dos_folder(source, "dos", saveplan.Assets(dos_folder=folder))


def test_a_silver_blades_save_writes_with_the_silver_blades_folder(tmp_path):
    """Against the game's own folders, as the specimen the ticket measured."""
    from tools.convert import convertdrops
    from tools.dos import dosbox

    root = specimen_root()
    where = root / SPECIMEN if root else None
    if where is None or not where.is_file():
        pytest.skip("needs the Silver Blades specimen")
    copy = tmp_path / "source.D64"
    shutil.copyfile(where, copy)
    party = Party(str(copy))
    source = convert.Source.detect(party.path)
    try:
        folder = dosbox.find_game("SECRET")
        pool = dosbox.find_game("POOLRAD")
        assets = saveplan.resolve_assets(
            source, "dos", game_files=convertdrops.game_files,
            dos_folder=folder)
    except (saveplan.MissingAssets, FileNotFoundError):
        pytest.skip("needs the game's DOS folders and Silver Blades' disks")
    out = tmp_path / "out"
    plan = saveplan.prepare_save_as(party, "dos", out, assets)
    assert isinstance(plan, saveplan.SavePlan)
    with pytest.raises(saveplan.WrongGameFolder):
        saveplan.prepare_save_as(
            party, "dos", tmp_path / "other",
            saveplan.Assets(dos_folder=pool,
                            game_files=assets.game_files,
                            source_files=assets.source_files))
    assert not (tmp_path / "other").exists()


def test_the_message_states_the_wrong_folder_and_no_field_loss(tmp_path):
    party = c64_party(tmp_path, "secret-of-the-silver-blades")
    folder = folder_of(tmp_path, "pool-of-radiance")
    with pytest.raises(saveplan.WrongGameFolder) as stopped:
        save_as(party, folder, tmp_path / "out")
    assert str(stopped.value) == (
        f"the DOS game folder {folder} holds pool-of-radiance, but the "
        f"save is secret-of-the-silver-blades")
    assert stopped.value.lost == []


def test_an_amiga_save_stops_on_another_titles_folder(tmp_path):
    from test_saveplan import amiga_disk

    path = amiga_disk(tmp_path)
    party = Party(str(path))
    source = convert.Source.detect(path)
    assert source.port == "amiga"
    folder = folder_of(tmp_path, "pool-of-radiance")
    with pytest.raises(saveplan.WrongGameFolder):
        saveplan.check_dos_folder(source, "dos",
                                  saveplan.Assets(dos_folder=folder))
    with pytest.raises(saveplan.WrongGameFolder):
        saveplan.prepare_save_as(party, "dos", tmp_path / "out",
                                 saveplan.Assets(dos_folder=folder))
    assert not (tmp_path / "out").exists()


def test_a_pools_of_darkness_destination_is_not_stopped_on_its_folder(
        tmp_path, monkeypatch):
    """Its writer reads no game folder, so which one was named is moot."""
    from test_convertrejection import _pod_disk

    monkeypatch.setenv(convert.POD_CONVERT_ENV, "1")
    path = _pod_disk(tmp_path)
    source = convert.Source.detect(path)
    assert source.key == titles.POOLS_OF_DARKNESS.key
    assert saveplan.DOS_GAME_FOLDER not in saveplan.requirements(source, "dos")
    folder = folder_of(tmp_path, "pool-of-radiance")
    saveplan.check_dos_folder(source, "dos", saveplan.Assets(dos_folder=folder))


def test_the_folder_table_agrees_with_the_acceptance_driver_stems():
    from tools.dos.acceptance import CONVERT_TITLE_KEYS, TITLES

    keys = {key: TITLES[short] for short, key in CONVERT_TITLE_KEYS.items()}
    keys[titles.POOLS_OF_DARKNESS.key] = TITLES["darkness"]
    assert set(titles.DOS_FOLDER_FILES) == set(keys)
    for key, (launcher, _config, stem) in titles.DOS_FOLDER_FILES.items():
        assert stem == keys[key].stem
        assert launcher == keys[key].exe
