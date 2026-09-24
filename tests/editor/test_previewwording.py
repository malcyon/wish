"""Every line of the Preview report opens with a capital letter, in the
wording Donald approved for it. Built from a synthetic C64 save, so it runs
with no game data."""
from __future__ import annotations

import pytest
from gamedata import synthetic_save
from support.editorwindow import make_root

from editor.window import EditorBinding


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def opened(app, tmp_path):
    path = synthetic_save(tmp_path, "PORSAVE11.D64")
    w = EditorBinding(make_root(), str(path))
    w.roster.selectRow(0)
    return w


def _edited(w):
    w.roster.selectRow(0)
    box = w._widgets["gold"]
    box.setValue(box.value() + 1)
    return w.preview_text()


def _every_line_opens_with_a_capital(text):
    lines = [ln for ln in text.split("\n") if ln]
    assert lines
    for ln in lines:
        assert ln[0].isupper(), ln


def test_an_untouched_save_reports_no_changes_to_write(opened):
    text = opened.preview_text()
    assert text == "Preview for PORSAVE11.D64\nNo changes to write"
    _every_line_opens_with_a_capital(text)


def test_an_edit_gives_a_capitalised_row_and_pending_count(opened):
    text = _edited(opened)
    lines = text.split("\n")
    assert lines[0] == "Preview for PORSAVE11.D64"
    rows = [ln for ln in lines if ln.startswith("Slot ") and ": " in ln]
    assert len(rows) == 1 and ": gold " in rows[0]
    assert lines[-1] == "Pending changes: 1 (nothing written yet)"
    _every_line_opens_with_a_capital(text)


def test_nothing_open_opens_with_a_capital(app):
    assert EditorBinding(make_root()).preview_text() == "Nothing open"
