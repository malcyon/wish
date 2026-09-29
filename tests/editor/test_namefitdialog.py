"""The window that asks for shorter character names (#619).

Every row is built from the `(position, name)` entries a `NamesDoNotFit`
carries, so no game data is needed. No test calls a real `exec()`: each one
builds the dialog and inspects it, or patches `NameFitDialog.exec`, so a modal
cannot open under CI.
"""
from __future__ import annotations

import pytest
from gamedata import synthetic_save
from PyQt6.QtGui import QFont, QValidator
from PyQt6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLineEdit
from support.editorwindow import make_root

import editor.window as ew
from editor import namefit
from editor.namefit import NameFitDialog

LONG = "ABCDEFGHIJKLMNOPQR"
OTHER = "STUVWXYZ0123456789"
WIDTH = 15
ACCEPT = "Accept label from the caller"


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _dialog(app, unfit=((0, LONG), (1, LONG)), width=WIDTH, accept=ACCEPT):
    return NameFitDialog(unfit, width, accept)


def _boxes(dialog):
    return [dialog.table.cellWidget(row, namefit.BOX_COLUMN)
            for row in range(dialog.table.rowCount())]


def _ok(dialog):
    return dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)


def test_the_window_carries_the_approved_title_and_sentence(app):
    dialog = _dialog(app)
    assert dialog.windowTitle() == "Shorten character names"
    assert dialog.ui.explanation_label.text() == (
        "The target platform cannot store character names this long. "
        "Please shorten them to 15 characters.")


def test_the_sentence_names_the_width_it_was_given(app):
    dialog = _dialog(app, width=12)
    assert dialog.ui.explanation_label.text().endswith(
        "shorten them to 12 characters.")


def test_two_characters_sharing_a_name_get_a_row_each(app):
    dialog = _dialog(app)
    assert dialog.table.rowCount() == 2
    assert len(_boxes(dialog)) == 2
    assert all(isinstance(box, QLineEdit) for box in _boxes(dialog))


def test_each_row_shows_the_full_original_name_beside_its_box(app):
    dialog = _dialog(app, ((0, LONG), (3, OTHER)))
    shown = [dialog.table.item(row, namefit.ORIGINAL_COLUMN).text()
             for row in range(dialog.table.rowCount())]
    assert shown == [LONG, OTHER]


def test_each_box_starts_with_the_name_cut_to_fit_and_selected(app):
    dialog = _dialog(app, ((0, LONG), (1, OTHER)))
    for box, name in zip(_boxes(dialog), (LONG, OTHER)):
        assert box.text() == name[:WIDTH]
        assert box.selectedText() == box.text()


def test_a_cut_that_ends_in_a_space_drops_it(app):
    dialog = _dialog(app, ((0, "ABCDEFGHIJKLMN OPQR"),))
    assert _boxes(dialog)[0].text() == "ABCDEFGHIJKLMN"


def test_the_first_box_takes_the_focus(app):
    dialog = _dialog(app)
    assert dialog.focusWidget() is _boxes(dialog)[0]


def test_a_box_holds_no_more_than_the_width_and_refuses_what_a_name_cannot_be(app):
    dialog = _dialog(app)
    for box in _boxes(dialog):
        assert box.maxLength() == WIDTH
        validator = box.validator()
        assert validator.validate("É", 1)[0] == QValidator.State.Invalid
        assert validator.validate("Renamed 1", 9)[0] == \
            QValidator.State.Acceptable


def _at_offset(app, offset):
    """The application font `offset` points above this machine's own."""
    base = app.font()
    bigger = QFont(base)
    bigger.setPointSizeF(base.pointSizeF() + offset)
    app.setFont(bigger)
    return base


@pytest.mark.parametrize("offset", range(0, 11))
def test_a_full_party_of_long_names_needs_no_scrolling_at_any_font(app, offset):
    """Six characters at the widest name: every row and every box is on show,
    and each box holds the whole of its name."""
    base = _at_offset(app, offset)
    try:
        dialog = _dialog(app, tuple((n, LONG) for n in range(6)))
        dialog.show()
        app.processEvents()
        assert dialog.table.verticalScrollBar().maximum() == 0
        for box in _boxes(dialog):
            assert box.contentsRect().width() >= box.fontMetrics(
                ).horizontalAdvance(box.text())
        dialog.close()
    finally:
        app.setFont(base)


def test_the_column_of_full_names_shows_each_name_whole(app):
    """A width, so at the base font only."""
    dialog = _dialog(app)
    dialog.show()
    app.processEvents()
    assert dialog.table.columnWidth(namefit.ORIGINAL_COLUMN) >= \
        dialog.table.sizeHintForColumn(namefit.ORIGINAL_COLUMN)
    dialog.close()


def test_the_accept_button_carries_the_callers_label(app):
    assert _ok(_dialog(app)).text() == ACCEPT


def test_the_cancel_button_is_the_standard_one(app):
    dialog = _dialog(app)
    assert dialog.buttons.button(
        QDialogButtonBox.StandardButton.Cancel) is not None


def test_a_box_left_empty_disables_accept_until_it_holds_a_name_again(app):
    dialog = _dialog(app)
    assert _ok(dialog).isEnabled()
    first = _boxes(dialog)[0]
    first.setText("")
    assert not _ok(dialog).isEnabled()
    first.setText("A")
    assert _ok(dialog).isEnabled()


def test_a_name_the_writer_would_refuse_disables_accept(app):
    """`fit_names` takes printable ASCII only, so a starting cut holding
    anything else must not be handed to it."""
    dialog = _dialog(app, ((0, "CAFÉ" + "X" * 14),))
    assert not _ok(dialog).isEnabled()
    _boxes(dialog)[0].setText("CAFE")
    assert _ok(dialog).isEnabled()


def test_duplicate_names_are_allowed(app):
    dialog = _dialog(app)
    for box in _boxes(dialog):
        box.setText("SAME")
    assert _ok(dialog).isEnabled()
    assert dialog.chosen() == {0: "SAME", 1: "SAME"}


def test_chosen_is_keyed_by_position_and_holds_the_edited_names(app):
    dialog = _dialog(app, ((2, LONG), (5, OTHER)))
    assert dialog.chosen() == {2: LONG[:WIDTH], 5: OTHER[:WIDTH]}
    _boxes(dialog)[1].setText("Edited")
    assert dialog.chosen() == {2: LONG[:WIDTH], 5: "Edited"}


def test_choose_names_gives_none_when_rejected_and_the_names_when_accepted(
        app, tmp_path, monkeypatch):
    binding = ew.EditorBinding(make_root(), str(synthetic_save(tmp_path)))
    seen = {}

    def exec_(dialog):
        seen["label"] = _ok(dialog).text()
        seen["title"] = dialog.windowTitle()
        _boxes(dialog)[0].setText("FIRST")
        return seen["result"]

    monkeypatch.setattr(NameFitDialog, "exec", exec_)
    unfit = ((0, LONG), (1, LONG))
    seen["result"] = QDialog.DialogCode.Rejected
    assert binding._choose_names(unfit, WIDTH, ACCEPT) is None
    seen["result"] = QDialog.DialogCode.Accepted
    assert binding._choose_names(unfit, WIDTH, ACCEPT) == {
        0: "FIRST", 1: LONG[:WIDTH]}
    assert seen["label"] == ACCEPT
    assert seen["title"] == namefit.TITLE
