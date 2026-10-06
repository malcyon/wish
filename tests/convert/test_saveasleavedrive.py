"""`saveasdrive.save_as(leave_ticks=...)` answers the real left-behind window
for an overflowing party, and `--leave` reaches it from the command line.

The party is the made-up one `tests/editor/test_leavebehind.py` builds: a DOS
Silver Blades member whose pack needs seventeen of the C64's sixteen slots.
"""
from __future__ import annotations

import pytest
from conftest import load_tools_module
from support import packoverflow
from support.editorwindow import make_root

from editor import leavebehind
from editor.dosimport import GameFiles
from editor.window import EditorBinding
from goldbox import c64_codec, c64_port, dos_codec, dos_port, dos_savegame
from goldbox.layout import Confidence

saveasdrive = load_tools_module("saveasdrive")


def dos_folder(path):
    """A DOS Silver Blades save folder of two made-up members, slot A."""
    from support.neutralrecords import _filled

    deltas = dos_port.SECRET_OF_THE_SILVER_BLADES
    path.mkdir(parents=True)
    for n in (1, 2):
        char = _filled(c64_port.by_key(deltas.key))
        char.set("name", f"HERO{n}", "made up", Confidence.CONFIRMED,
                 c64_codec.Provenance.RESHAPED)
        record, itm, spc, _report = dos_codec.write(char, deltas=deltas)
        (path / f"CHRDATA{n}.SAV").write_bytes(record)
        (path / f"CHRDATA{n}{deltas.item_suffix}").write_bytes(itm)
        (path / f"CHRDATA{n}{deltas.effect_suffix}").write_bytes(spc)
    container = dos_savegame.container_for(deltas.key)
    (path / f"SAVGAMA{container.suffix}").write_bytes(bytes(container.size))
    return path


@pytest.fixture(params=[1])
def window(tmp_path, request):
    from PyQt6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    folder = dos_folder(tmp_path / "save")
    extra = [packoverflow.scroll(5)] * (request.param - 1)
    packoverflow.crowd_dos_member(
        folder, 1, 15, packoverflow.scroll(5), packoverflow.scroll(6, 7),
        *extra, name="HERO1")
    binding = EditorBinding(make_root(), str(folder))
    binding.game_files_for = lambda _title: GameFiles(
        icon=bytes(36), animate=bytes(852))
    return binding, folder / "SAVGAMA.DAT"


def _run(window, tmp_path, ticks):
    binding, source = window
    return saveasdrive.save_as(binding, source, "c64", tmp_path / "out",
                               leave_ticks=ticks)


def test_a_party_over_the_limit_is_blocked_without_a_choice(window, tmp_path):
    report = _run(window, tmp_path, None)
    assert report["stopped"][0] == "JoinedScrollsDoNotFit"


def test_auto_ticks_rows_until_the_window_reads_zero_and_publishes(
        window, tmp_path):
    report = _run(window, tmp_path, ["auto"])

    assert "stopped" not in report, report
    dialog = report["leave_dialog"]
    assert dialog["label_before"] == leavebehind.ITEMS_REMAINING.format(n=1)
    assert dialog["label_after"] == leavebehind.ITEMS_REMAINING.format(n=0)
    assert dialog["ok_enabled"] is True
    assert len(dialog["ticked"]) == 1 and dialog["ticked"][0]["text"]
    assert len(report["left_behind"]) == 1
    assert report["written"]


def test_a_named_row_is_ticked_by_the_text_it_shows(window, tmp_path):
    first = _run(window, tmp_path, ["auto"])["leave_dialog"]["ticked"][0]["text"]
    report = _run(window, tmp_path, [first])

    assert report["leave_dialog"]["ticked"][0]["text"] == first
    assert report["leave_dialog"]["ok_enabled"] is True
    assert "stopped" not in report


def test_a_row_the_window_does_not_show_stops_the_run(window, tmp_path):
    report = _run(window, tmp_path, ["NO SUCH ITEM"])

    assert report["stopped"][0] == "LeaveChoiceError"
    assert "NO SUCH ITEM" in report["stopped"][1]
    assert "written" not in report


@pytest.mark.parametrize("window", [2], indirect=True)
def test_ok_staying_disabled_stops_the_run(window, tmp_path):
    """Two items over, one row ticked: the window still reads 1."""
    report = _run(window, tmp_path, ["auto"])
    first = report["leave_dialog"]["ticked"][0]["text"]
    report = _run(window, tmp_path, [first])

    assert report["stopped"][0] == "LeaveChoiceError"
    assert "OK is disabled" in report["stopped"][1]


def test_the_driver_passes_leave_on_and_exits_nonzero_with_one_line(
        tmp_path, capsys, monkeypatch):
    from tools.convert import saveasdrive as driven

    seen = {}

    def stopped(window, source, port, folder, **kwargs):
        seen.update(kwargs)
        return {"stopped": ["LeaveChoiceError", "no row shows 'NOPE'"]}

    monkeypatch.setattr(driven, "save_as", stopped)
    drive = load_tools_module("convertdialogdrive")
    specimen = tmp_path / "SAVGAMA.DAT"
    specimen.write_bytes(b"x")
    disk = tmp_path / "x.adf"
    disk.write_bytes(b"")
    status = drive.main(["--specimen", str(specimen), "--amiga-disk2", str(disk),
                         "--out-dir", str(tmp_path / "o"),
                         "--leave", "NOPE", "--leave", "TWO"])

    assert status == 1
    assert seen["leave_ticks"] == ["NOPE", "TWO"]
    assert capsys.readouterr().err.strip().splitlines() == [
        "no row shows 'NOPE'"]


def test_the_window_gets_the_label_the_real_save_as_uses(window, tmp_path):
    binding, _source = window
    report = _run(window, tmp_path, ["auto"])

    assert report["leave_dialog"]["accept_label"] == binding._save_as_label()
    assert report["leave_dialog"]["accept_label"] not in ("", "OK")


def test_no_overflow_is_recorded_as_nothing_ticked(tmp_path):
    from PyQt6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    folder = dos_folder(tmp_path / "save")
    binding = EditorBinding(make_root(), str(folder))
    binding.game_files_for = lambda _title: GameFiles(
        icon=bytes(36), animate=bytes(852))
    report = saveasdrive.save_as(binding, folder / "SAVGAMA.DAT", "c64",
                                 tmp_path / "out", leave_ticks=["auto", "X"])

    assert "stopped" not in report, report
    assert report["leave_dialog"] == {"overflow": False, "ticked": []}


def test_an_auto_that_ticks_nothing_is_recorded(window, tmp_path, monkeypatch):
    original = leavebehind.LeaveBehindDialog.__init__

    def already_zero(self, *args, **kwargs):
        original(self, *args, **kwargs)
        self.ui.items_remaining_label.setText(
            leavebehind.ITEMS_REMAINING.format(n=0))
        self.buttons.button(
            leavebehind.QDialogButtonBox.StandardButton.Ok).setEnabled(False)

    monkeypatch.setattr(leavebehind.LeaveBehindDialog, "__init__",
                        already_zero)
    report = _run(window, tmp_path, ["auto"])

    assert report["stopped"][0] == "LeaveChoiceError"
    assert report["leave_dialog"]["overflow"] is True
    assert report["leave_dialog"]["ticked"] == []


def test_the_amiga_party_window_is_ticked_and_the_run_repeated(
        tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QApplication

    from editor import saveplan
    from goldbox import amiga_savegame
    QApplication.instance() or QApplication([])

    folder = dos_folder(tmp_path / "save")
    binding = EditorBinding(make_root(), str(folder))
    # The party-wide overflow of specimen L's pack, as test_leavebehind builds it.
    inventory, bundles = packoverflow.specimen_l_pack()
    first = packoverflow.member("PAINE", 0)
    first.set("inventory", inventory, "made up")
    first.set("scroll_bundles", bundles, "made up")
    other = packoverflow.member("OTHER", 2, packoverflow.scroll(5),
                                packoverflow.scroll(6))
    (over,) = dos_codec.pack_overflow([first, other], "amiga")
    seen = {}

    def prepare(party, port, path, assets, **kwargs):
        seen.update(kwargs)
        if not kwargs.get("leave"):
            raise amiga_savegame.AmigaJoinedScrollsDoNotFit(over, "SB")
        raise RuntimeError("stop after the choice")

    monkeypatch.setattr(saveplan, "resolve_assets", lambda *a, **k: object())
    monkeypatch.setattr(saveplan, "prepare_save_as", prepare)
    report = saveasdrive.save_as(binding, folder / "SAVGAMA.DAT", "amiga",
                                 tmp_path / "out", leave_ticks=["auto"])

    assert seen["leave"], seen
    assert report["leave_dialog"]["overflow"] is True
    assert report["leave_dialog"]["ticked"]
    assert report["stopped"] == ["RuntimeError", "stop after the choice"]


def test_a_stop_after_the_windows_choice_prints_one_line_on_stderr(
        tmp_path, capsys, monkeypatch):
    from tools.convert import saveasdrive as driven

    def stopped(window, source, port, folder, **kwargs):
        return {"stopped": ["MissingAssets", "no disk"],
                "leave_dialog": {"overflow": True, "ticked": []}}

    monkeypatch.setattr(driven, "save_as", stopped)
    drive = load_tools_module("convertdialogdrive")
    specimen = tmp_path / "SAVGAMA.DAT"
    specimen.write_bytes(b"x")
    disk = tmp_path / "x.adf"
    disk.write_bytes(b"")
    status = drive.main(["--specimen", str(specimen), "--amiga-disk2", str(disk),
                         "--out-dir", str(tmp_path / "o"), "--leave", "auto"])

    assert status == 1
    assert capsys.readouterr().err.strip().splitlines() == ["no disk"]
