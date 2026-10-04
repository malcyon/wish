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
