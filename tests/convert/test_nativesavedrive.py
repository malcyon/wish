"""`tools/convert/nativesavedrive.py` edits through the editor's own Save."""

from __future__ import annotations

import pathlib

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


def _dos_folder(where):
    """A DOS Silver Blades save folder with two members, built from the format."""
    from support.neutralrecords import _filled

    from goldbox import c64_codec, c64_port, dos_codec, dos_port, dos_savegame
    from goldbox.layout import Confidence

    deltas = dos_port.SECRET_OF_THE_SILVER_BLADES
    where.mkdir(parents=True)
    for n in (1, 2):
        char = _filled(c64_port.by_key(deltas.key))
        char.set("name", f"HERO{n}", "made up", Confidence.CONFIRMED,
                 c64_codec.Provenance.RESHAPED)
        record, itm, spc, _report = dos_codec.write(char, deltas=deltas)
        (where / f"CHRDATA{n}.SAV").write_bytes(record)
        (where / f"CHRDATA{n}{deltas.item_suffix}").write_bytes(itm)
        (where / f"CHRDATA{n}{deltas.effect_suffix}").write_bytes(spc)
    container = dos_savegame.container_for(deltas.key)
    (where / f"SAVGAMA{container.suffix}").write_bytes(bytes(container.size))
    return where


def test_a_dos_folder_is_copied_edited_and_backed_up_inside_itself(tmp_path):
    base = _dos_folder(tmp_path / "base")
    before = {p.name: p.read_bytes() for p in base.iterdir()}
    out = tmp_path / "saves" / "edited"

    report = nativesavedrive.drive(base, out, who=1, gold=4321, strength=17,
                                   items={0: 3}, slot="A")

    assert report["ok"], report["problem"]
    assert {p.name: p.read_bytes() for p in base.iterdir()} == before
    assert report["after"]["gold"] == 4321
    assert report["after"]["strength"] == 17
    assert report["after"]["quantities"] == {"0": 3}
    assert report["backups"]
    assert all(pathlib.Path(b["path"]).parent == out / "backups"
               for b in report["backups"])
    assert all(b["equals_pre_edit"] for b in report["backups"])
    assert report["sha256"]["base"] != report["sha256"]["out"]
    changed = {n for n, data in before.items() if (out / n).read_bytes() != data}
    assert changed
    assert {pathlib.Path(b["path"]).name.rsplit(".20", 1)[0]
            for b in report["backups"]} == changed


def test_a_c64_disk_is_edited_and_backed_up_beside_itself(tmp_path):
    from gamedata import synthetic_save

    base = synthetic_save(tmp_path)
    original = base.read_bytes()
    out = tmp_path / "saves" / "edited.D64"

    report = nativesavedrive.drive(base, out, who=0, gold=4321, strength=17,
                                   items={0: 3})

    assert report["ok"], report["problem"]
    assert base.read_bytes() == original
    assert report["after"]["gold"] == 4321
    assert report["after"]["strength"] == 17
    assert report["after"]["quantities"] == {"0": 3}
    (backup,) = report["backups"]
    assert pathlib.Path(backup["path"]).parent == out.parent / "backups"
    assert backup["equals_pre_edit"]
