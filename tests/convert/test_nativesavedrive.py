"""`tools/convert/nativesavedrive.py` edits through the editor's own Save."""

from __future__ import annotations

from conftest import load_tools_module
from support.amigasavegame import synthetic_curse

from goldbox import amiga_savegame

nativesavedrive = load_tools_module("nativesavedrive")


def test_the_edits_read_back_and_the_backup_is_the_original(tmp_path):
    base = tmp_path / "base.adf"
    amiga_savegame.make_save_disk(
        amiga_savegame.CURSE, "A", synthetic_curse(("ALPHA", "BRAVO"))
    ).save(base)
    original = base.read_bytes()
    out = tmp_path / "saves" / "edited.adf"

    report = nativesavedrive.drive(base, out, who=1, gold=4321, strength=17,
                                   items={0: 3})

    assert base.read_bytes() == original
    assert report["after"]["gold"] == 4321
    assert report["after"]["strength"] == 17
    assert report["after"]["quantities"] == {"0": 3}
    assert report["before"] != report["after"]
    assert out.read_bytes() != original
    (backup,) = report["backups"]
    assert backup["equals_pre_edit"]
    assert report["sha256"]["base"] == backup["sha256"]
    assert report["sha256"]["out"] != report["sha256"]["base"]


def test_a_save_that_writes_nothing_exits_non_zero(tmp_path, monkeypatch, capsys):
    from editor.window import EditorBinding

    base = tmp_path / "base.adf"
    amiga_savegame.make_save_disk(
        amiga_savegame.CURSE, "A", synthetic_curse(("ALPHA", "BRAVO"))
    ).save(base)
    monkeypatch.setattr(EditorBinding, "save", lambda self, interactive=True: "failed")

    status = nativesavedrive.main([
        "--base", str(base), "--out", str(tmp_path / "out.adf"),
        "--who", "0", "--gold", "10", "--strength", "12", "--item", "0=1"])

    assert status == 1
    assert "failed" in capsys.readouterr().err


def test_slot_edits_that_slot_and_leaves_the_other(tmp_path):
    disk = amiga_savegame.make_save_disk(
        amiga_savegame.CURSE, "A", synthetic_curse(("ALPHA", "BRAVO")))
    disk.write_file(amiga_savegame.slot_path(amiga_savegame.CURSE, "B"),
                    synthetic_curse(("CHARLIE", "DELTA")))
    base = tmp_path / "base.adf"
    disk.save(base)
    out = tmp_path / "saves" / "edited.adf"

    report = nativesavedrive.drive(base, out, who=1, gold=777, strength=16,
                                   items={0: 2}, slot="B")

    assert report["ok"]
    assert report["after"]["gold"] == 777
    assert report["after"]["quantities"] == {"0": 2}
    from editor.convert import Source
    from editor.roster import Party
    other = Party(Source.detect(str(out), slot="A")).members[1]
    assert other.record.get("gold") != 777
    assert Party(Source.detect(str(out), slot="B")).members[1].name == "DELTA"
