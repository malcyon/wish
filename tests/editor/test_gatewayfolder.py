"""A Gateway save folder is not opened as Curse, whose 422-byte records it
shares."""

import pytest
from support.editorwindow import make_root

from editor.convert import Source
from goldbox import dos_codec, dos_port, titles


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


SENTENCE = "Gateway to the Savage Frontier saves are not yet supported."


def _save(folder, launcher=None, config=None):
    """A synthetic save folder; `launcher` and `config` go in its parent."""
    save = folder / "SAVE"
    save.mkdir(parents=True)
    for name in (launcher, config):
        if name:
            (folder / name).write_bytes(b"")
    (save / "CHRDATA1.SAV").write_bytes(
        bytes(dos_port.CURSE_OF_THE_AZURE_BONDS.record_size))
    (save / "SAVGAMA.DAT").write_bytes(b"")
    return save


def _gateway(tmp_path):
    return _save(tmp_path / "GATEWAY", "START1.EXE", "GAME.CFG")


def _snapshot(folder):
    return {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}


def _open(save, monkeypatch):
    import editor.window as ew
    said = []
    monkeypatch.setattr(ew.QMessageBox, "critical",
                        lambda *a, **k: said.append((a[1], a[2])))
    ew.EditorBinding(make_root()).load(str(save))
    return said


@pytest.mark.parametrize("pick", ["folder", "file"])
def test_a_gateway_save_folder_opens_to_the_gateway_sentence(
        app, tmp_path, monkeypatch, pick):
    save = _gateway(tmp_path)
    before = _snapshot(save)
    target = save if pick == "folder" else save / "SAVGAMA.DAT"
    assert _open(target, monkeypatch) == [("Cannot open", SENTENCE)]
    assert _snapshot(save) == before


def test_saves_kept_in_the_gateway_game_folder_are_caught(tmp_path):
    game = tmp_path / "GATEWAY"
    game.mkdir()
    (game / "START1.EXE").write_bytes(b"")
    (game / "GAME.CFG").write_bytes(b"")
    (game / "CHRDATA1.SAV").write_bytes(
        bytes(dos_port.CURSE_OF_THE_AZURE_BONDS.record_size))
    (game / "SAVGAMA.DAT").write_bytes(b"")
    with pytest.raises(dos_codec.WrongTitleError) as blocked:
        Source.detect(game)
    assert blocked.value.title == titles.GATEWAY_TO_THE_SAVAGE_FRONTIER.title


@pytest.mark.parametrize("launcher, config", [
    ("START.EXE", "CURSE.CFG"), (None, None)])
def test_a_curse_folder_still_opens_as_curse(tmp_path, launcher, config):
    save = _save(tmp_path / "GAME", launcher, config)
    assert Source.detect(save).title.key == "curse-of-the-azure-bonds"


def test_the_default_folder_table_does_not_name_gateway(tmp_path):
    save = _gateway(tmp_path)
    assert titles.dos_folder_title(save.parent) is None
    assert titles.dos_folder_title(
        save.parent, table=titles.DOS_UNREAD_FOLDER_FILES) \
        == titles.GATEWAY_TO_THE_SAVAGE_FRONTIER.key


def test_a_folder_holding_both_sets_of_files_opens_as_curse(tmp_path):
    save = _gateway(tmp_path)
    for name in ("START.EXE", "CURSE.CFG"):
        (save.parent / name).write_bytes(b"")
    assert Source.detect(save).title.key == "curse-of-the-azure-bonds"


def test_a_curse_save_under_a_gateway_named_parent_opens_as_curse(tmp_path):
    save = _save(tmp_path / "GATEWAY", "START.EXE", "CURSE.CFG")
    assert Source.detect(save).title.key == "curse-of-the-azure-bonds"
