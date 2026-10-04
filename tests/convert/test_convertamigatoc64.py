"""The Amiga to C64 Save As leaves a Pool party's nameless type-0 item out and says so.

The specimen is the game-written Amiga slot D of a party whose first member
held that item; `tools/convert/convertamigatoc64.py` must be able to pick the
slot, because the disk's default slot is another party.
"""

from __future__ import annotations

import json

import pytest
from gamedata import specimen
from PyQt6.QtWidgets import QApplication

from automap import gamedisks
from editor import convert, roster, saveplan
from tools.convert import convertamigatoc64

NAME = "wish16-type0-readied-pool-amiga-slots-c-d-engine-save"
LINE = "type 0, left out"


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _disk():
    return specimen(NAME, "amiga") / "fetched-save.adf"


def _c64_disks():
    where = gamedisks.find("pool-of-radiance")
    if where is None:
        pytest.skip("needs Pool of Radiance's own C64 disks, found through "
                    "automap/gamedisks.py")
    return where


def _game_files(game):
    where = gamedisks.find(game.key)
    return convert._game_files_from_folder(where, game) if where else None


def test_the_amiga_slot_reports_its_type_zero_item_as_left_out_and_nothing_else(
        app, tmp_path):
    _c64_disks()
    party = roster.Party(convert.Source.detect(_disk(), slot="D"))
    try:
        assets = saveplan.resolve_assets(party.source, "c64",
                                         game_files=_game_files)
    except saveplan.MissingAssets:
        pytest.skip("needs Pool of Radiance's own C64 disks")
    plan = saveplan.prepare_save_as(party, "c64", tmp_path / "out.d64", assets)
    lines = [w for w in plan.report.warnings if LINE in w]
    assert len(lines) == 1 and "THRENDER GRONE" in lines[0]
    assert plan.report.losses == []
    assert plan.report.dropped == []
    assert plan.report.left_behind == []


def test_the_tool_reads_the_slot_it_is_given(app, tmp_path):
    disks = _c64_disks()
    seen = {}
    for slot in ("C", "d"):
        out = tmp_path / f"out-{slot}"
        summary = tmp_path / f"summary-{slot}.json"
        convertamigatoc64.main([
            "--tree", ".", "--specimen", str(_disk()), "--disks", str(disks),
            "--source-slot", slot, "--out-dir", str(out),
            "--summary", str(summary)])
        seen[slot] = json.loads(summary.read_text())
    assert [seen[s]["source_slot"] for s in ("C", "d")] == ["C", "D"]
    assert seen["C"]["produced_sha256"] != seen["d"]["produced_sha256"]


def test_the_tool_blocks_a_slot_that_is_not_a_letter(tmp_path, capsys):
    with pytest.raises(SystemExit):
        convertamigatoc64.main([
            "--tree", ".", "--specimen", "x", "--disks", "x",
            "--source-slot", "K", "--out-dir", str(tmp_path),
            "--summary", str(tmp_path / "s.json")])
    assert "one letter" in capsys.readouterr().err
