"""The File menu's own copies of the split Open and Save actions, and
`Ctrl+Shift+S` (#511, docs/227-editor-open-save-as.md, decision 1 on the
issue's stage-3 comment 5769421923: it pops the Save button's own menu, at
the button, rather than picking a platform for the player).
"""
from __future__ import annotations

import pytest


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def window(app, save=None, maps={}, **kw):
    """A window with no emulator and nothing modal, matching
    `tests/wish/test_gamefolders.py`'s own helper of the same name."""
    from wish.session import Session
    from wish.window import WishWindow
    win = WishWindow(save, maps=maps, session=Session(find=lambda pref=None: None),
                     **kw)
    win.announce = lambda title, text: None
    return win


def _file_menu(win):
    return next(a.menu() for a in win.menuBar().actions()
               if a.text() == "&File")


def test_the_file_menu_carries_the_five_approved_mnemonics_in_order(app):
    win = window(app)
    texts = [a.text() for a in _file_menu(win).actions() if a.text()]
    assert texts[:5] == ["&Open…", "Open &DOS folder…", "&Save",
                         "Save &As…", "&Preview changes…"]
    # Convert stays for now (stage 4 retires it), Preferences and Quit
    # follow it, unchanged.
    assert "&Convert…" in texts
    assert "&Preferences…" in texts
    assert "&Quit" in texts


def test_save_as_carries_ctrl_shift_s_and_nothing_else_does(app):
    from PyQt6.QtGui import QKeySequence
    win = window(app)
    save_as = next(a for a in _file_menu(win).actions()
                   if a.text() == "Save &As…")
    assert save_as.shortcut() == QKeySequence("Ctrl+Shift+S")
    others = [a.shortcut() for a in _file_menu(win).actions()
             if a is not save_as and not a.shortcut().isEmpty()]
    assert QKeySequence("Ctrl+Shift+S") not in others


def test_ctrl_shift_s_pops_the_save_buttons_own_menu_rather_than_saving(
        app, tmp_path, monkeypatch):
    from gamedata import synthetic_save

    path = synthetic_save(tmp_path)
    win = window(app, str(path))
    save_as = next(a for a in _file_menu(win).actions()
                   if a.text() == "Save &As…")
    button = win.editor._child("button_save")
    shown = []
    monkeypatch.setattr(button, "showMenu", lambda: shown.append(True))
    saved = []
    monkeypatch.setattr(win.editor, "save", lambda *a, **k: saved.append(True))
    save_as.trigger()
    assert shown == [True]
    assert saved == []


def test_save_as_is_enabled_whenever_a_save_is_open(app, tmp_path):
    from gamedata import synthetic_save

    path = synthetic_save(tmp_path)
    win = window(app, str(path))
    save_as = next(a for a in _file_menu(win).actions()
                   if a.text() == "Save &As…")
    assert save_as.isEnabled()


def test_save_as_is_disabled_with_nothing_open(app):
    win = window(app)
    save_as = next(a for a in _file_menu(win).actions()
                   if a.text() == "Save &As…")
    assert not save_as.isEnabled()
