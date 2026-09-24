"""A scratch boot disk must hide its own SAVE drawer without losing game files."""

from __future__ import annotations

from hashlib import sha256

import pytest

from automap import gamedisks
from goldbox.amiga_adf import BLOCK_SIZE, AmigaDisk, AmigaDiskError
from tools.amiga import amigaacceptance


def _disk(tmp_path, *, blocks: int = 920, drawer: str = "SAVE"):
    source = tmp_path / "source.adf"
    disk = AmigaDisk.blank("Secret 1", blocks=blocks)
    disk.make_dir(f"/{drawer}")
    disk.write_file("/Secret", b"synthetic executable")
    disk.write_file(f"/{drawer}/savgamA.sav", b"synthetic party")
    disk.write_file(f"/{drawer}/spindisk", b"synthetic spinner")
    disk.write_file("/game.data", b"unchanged game file")
    disk.save(source)
    assert disk.verify() == []
    return source


def _stage(source, out):
    return amigaacceptance.stage_boot_disk(
        source, out,
        expected_source_sha256=sha256(source.read_bytes()).hexdigest(),
        expected_secret_sha256=sha256(b"synthetic executable").hexdigest(),
    )


def test_stage_hides_only_the_boot_disk_drawer_and_preserves_its_contents(tmp_path):
    source = _disk(tmp_path)
    before = source.read_bytes()
    out = tmp_path / "boot-no-save.adf"

    manifest = _stage(source, out)

    after = out.read_bytes()
    staged = AmigaDisk.open(out)
    assert source.read_bytes() == before
    assert before[:1024] == after[:1024]
    assert staged.verify() == []
    with pytest.raises(AmigaDiskError, match="SAVE"):
        staged.lookup("/SAVE")
    assert staged.lookup("/SAVE_OFF_40").block == 919
    assert staged.read_file("/SAVE_OFF_40/savgamA.sav") == b"synthetic party"
    assert staged.read_file("/SAVE_OFF_40/spindisk") == b"synthetic spinner"
    assert staged.read_file("/Secret") == b"synthetic executable"
    assert staged.read_file("/game.data") == b"unchanged game file"
    assert [i for i in range(len(before) // BLOCK_SIZE)
            if before[i * BLOCK_SIZE:(i + 1) * BLOCK_SIZE]
            != after[i * BLOCK_SIZE:(i + 1) * BLOCK_SIZE]] == [919]
    assert manifest["changed_blocks"] == [919]
    assert manifest["source_sha256"] == sha256(before).hexdigest()
    assert manifest["staged_sha256"] == sha256(after).hexdigest()


def test_stage_refuses_a_different_save_drawer_block_without_writing(tmp_path):
    source = _disk(tmp_path, blocks=922)
    before = source.read_bytes()
    out = tmp_path / "must-not-exist.adf"

    with pytest.raises(amigaacceptance.StageError, match="block 919"):
        _stage(source, out)

    assert source.read_bytes() == before
    assert not out.exists()


def test_stage_refuses_a_missing_or_renamed_save_drawer(tmp_path):
    source = _disk(tmp_path, drawer="SAUR")
    out = tmp_path / "must-not-exist.adf"

    with pytest.raises(amigaacceptance.StageError, match="/SAVE"):
        _stage(source, out)

    assert not out.exists()


def test_stage_refuses_a_name_with_the_wrong_hash_bucket(tmp_path, monkeypatch):
    source = _disk(tmp_path)
    out = tmp_path / "must-not-exist.adf"
    monkeypatch.setattr(amigaacceptance, "HIDDEN_NAME", "SAVE_OFF_41")

    with pytest.raises(amigaacceptance.StageError, match="hash bucket"):
        _stage(source, out)

    assert not out.exists()


def test_stage_refuses_a_source_hash_mismatch(tmp_path):
    source = _disk(tmp_path)
    before = source.read_bytes()
    out = tmp_path / "must-not-exist.adf"

    with pytest.raises(amigaacceptance.StageError, match="source SHA-256 differs"):
        amigaacceptance.stage_boot_disk(
            source, out,
            expected_source_sha256="0" * 64,
            expected_secret_sha256=sha256(b"synthetic executable").hexdigest(),
        )

    assert source.read_bytes() == before
    assert not out.exists()


def test_stage_refuses_a_secret_hash_mismatch(tmp_path):
    source = _disk(tmp_path)
    before = source.read_bytes()
    out = tmp_path / "must-not-exist.adf"

    with pytest.raises(amigaacceptance.StageError, match="/Secret SHA-256 differs"):
        amigaacceptance.stage_boot_disk(
            source, out,
            expected_source_sha256=sha256(before).hexdigest(),
            expected_secret_sha256="0" * 64,
        )

    assert source.read_bytes() == before
    assert not out.exists()


def test_stage_refuses_to_replace_an_existing_output(tmp_path):
    source = _disk(tmp_path)
    out = tmp_path / "existing.adf"
    out.write_bytes(b"keep this file")

    with pytest.raises(amigaacceptance.StageError, match="output already exists"):
        _stage(source, out)

    assert out.read_bytes() == b"keep this file"


def test_registered_side_a_stage_keeps_the_original_read_only(tmp_path):
    root = gamedisks.find("amiga")
    if root is None:
        pytest.skip("registered Amiga disks are unavailable")
    source = root / "Secret_Of_The_Silver_Blades" / "SecretOfTheSilverBlades_A.adf"
    if not source.is_file():
        pytest.skip("registered Silver Blades Amiga side A is unavailable")
    before = source.read_bytes()
    out = tmp_path / "boot-no-save.adf"

    manifest = amigaacceptance.stage_boot_disk(source, out)

    staged = AmigaDisk.open(out)
    assert source.read_bytes() == before
    assert staged.verify() == []
    assert staged.lookup("/SAVE_OFF_40").block == 919
    assert staged.read_file("/Secret") == AmigaDisk.open(source).read_file("/Secret")
    assert manifest["changed_blocks"] == [919]
