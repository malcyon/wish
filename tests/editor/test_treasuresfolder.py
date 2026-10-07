"""A Treasures of the Savage Frontier save folder is not opened as Pools of
Darkness, whose 510-byte records it shares."""

import pytest
from support.editorwindow import make_root

from editor.convert import Source
from goldbox import dos_codec, dos_port, titles


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


SENTENCE = "Treasures of the Savage Frontier saves are not supported."


def _save(folder, launcher=None, config=None):
    """A synthetic save folder; `launcher` and `config` go in its parent."""
    save = folder / "SAVE"
    save.mkdir(parents=True)
    for name in (launcher, config):
        if name:
            (folder / name).write_bytes(b"")
    (save / "CHRDATA1.SAV").write_bytes(
        bytes(dos_port.POOLS_OF_DARKNESS.record_size))
    (save / "SAVGAMA.PTY").write_bytes(b"")
    return save


def _treasures(tmp_path):
    return _save(tmp_path / "TREASURE", "STARTUP.EXE", "TREASURE.CFG")


def _snapshot(folder):
    return {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}


def _open(save, monkeypatch):
    import editor.window as ew
    said = []
    monkeypatch.setattr(ew.QMessageBox, "critical",
                        lambda *a, **k: said.append((a[1], a[2])))
    ew.EditorBinding(make_root()).load(str(save))
    return said


@pytest.mark.parametrize("flag", ["", "1"])
@pytest.mark.parametrize("pick", ["folder", "file"])
def test_a_treasures_save_folder_opens_to_the_treasures_sentence(
        app, tmp_path, monkeypatch, pick, flag):
    monkeypatch.setenv("WISH_EXPERIMENTAL_POD_CONVERT", flag)
    save = _treasures(tmp_path)
    before = _snapshot(save)
    target = save if pick == "folder" else save / "SAVGAMA.PTY"
    assert _open(target, monkeypatch) == [("Cannot open", SENTENCE)]
    assert _snapshot(save) == before


def test_a_treasures_folder_never_detects_as_pools_of_darkness(tmp_path):
    with pytest.raises(dos_codec.WrongTitleError) as blocked:
        Source.detect(_treasures(tmp_path))
    assert blocked.value.title == titles.TREASURES_OF_THE_SAVAGE_FRONTIER_TITLE


def test_saves_kept_in_the_treasures_game_folder_are_caught(tmp_path):
    game = tmp_path / "TREASURE"
    game.mkdir()
    for name in ("STARTUP.EXE", "TREASURE.CFG", "SAVGAMA.PTY"):
        (game / name).write_bytes(b"")
    (game / "CHRDATA1.SAV").write_bytes(
        bytes(dos_port.POOLS_OF_DARKNESS.record_size))
    with pytest.raises(dos_codec.WrongTitleError):
        Source.detect(game)


@pytest.mark.parametrize("launcher, config", [
    ("START.BAT", "POOL4.CFG"), (None, None)])
def test_a_pools_of_darkness_folder_still_opens(tmp_path, launcher, config):
    save = _save(tmp_path / "GAME", launcher, config)
    assert Source.detect(save).title.key == "pools-of-darkness"


def test_a_pools_of_darkness_save_under_a_treasures_named_parent_still_opens(
        tmp_path):
    save = _save(tmp_path / "TREASURE", "START.BAT", "POOL4.CFG")
    assert Source.detect(save).title.key == "pools-of-darkness"


def test_the_default_folder_table_does_not_name_treasures(tmp_path):
    save = _treasures(tmp_path)
    assert titles.dos_folder_title(save.parent) is None
    assert titles.dos_folder_title(
        save.parent, table=titles.DOS_UNREAD_FOLDER_FILES) \
        == titles.TREASURES_OF_THE_SAVAGE_FRONTIER_KEY
