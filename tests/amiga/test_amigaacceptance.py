"""A scratch boot disk must hide its own SAVE drawer without losing game files."""

from __future__ import annotations

import os
from hashlib import sha256

import pytest

from automap import gamedisks
from goldbox.amiga_adf import BLOCK_SIZE, AmigaDisk, AmigaDiskError
from tools.amiga import amigaacceptance

POSIX_STAGING = pytest.mark.skipif(
    not amigaacceptance._POSIX_OUTPUT_SUPPORTED,
    reason="staging requires POSIX no-follow directory operations",
)


@pytest.fixture(autouse=True)
def _isolated_acceptance_roots(tmp_path, monkeypatch):
    temp_base = tmp_path / "temp"
    home_base = tmp_path / "home"
    temp_base.mkdir()
    home_base.mkdir()
    monkeypatch.setattr(
        amigaacceptance.scratch, "scratch_dir",
        lambda tool: temp_base / "wish" / tool,
    )
    monkeypatch.setattr(
        amigaacceptance.scratch, "cache_dir",
        lambda tool: home_base / ".cache" / "wish" / tool,
    )


def _out(name="boot-no-save.adf"):
    return amigaacceptance.scratch.scratch_dir("amigaacceptance") / name


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


def test_unsupported_platform_refuses_before_read_or_write(tmp_path, monkeypatch):
    source = tmp_path / "missing-source.adf"
    out = _out()
    monkeypatch.setattr(amigaacceptance, "_POSIX_OUTPUT_SUPPORTED", False)

    with pytest.raises(amigaacceptance.StageError, match="requires POSIX"):
        amigaacceptance.stage_boot_disk(source, out)

    assert not out.exists()
    assert not out.parent.exists()


@POSIX_STAGING
def test_stage_hides_only_the_boot_disk_drawer_and_preserves_its_contents(tmp_path):
    source = _disk(tmp_path)
    before = source.read_bytes()
    out = _out()

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


@POSIX_STAGING
def test_stage_refuses_a_different_save_drawer_block_without_writing(tmp_path):
    source = _disk(tmp_path, blocks=922)
    before = source.read_bytes()
    out = _out("must-not-exist.adf")

    with pytest.raises(amigaacceptance.StageError, match="block 919"):
        _stage(source, out)

    assert source.read_bytes() == before
    assert not out.exists()


@POSIX_STAGING
def test_stage_refuses_a_missing_or_renamed_save_drawer(tmp_path):
    source = _disk(tmp_path, drawer="SAUR")
    out = _out("must-not-exist.adf")

    with pytest.raises(amigaacceptance.StageError, match="/SAVE"):
        _stage(source, out)

    assert not out.exists()


@POSIX_STAGING
def test_stage_refuses_a_name_with_the_wrong_hash_bucket(tmp_path, monkeypatch):
    source = _disk(tmp_path)
    out = _out("must-not-exist.adf")
    monkeypatch.setattr(amigaacceptance, "HIDDEN_NAME", "SAVE_OFF_41")

    with pytest.raises(amigaacceptance.StageError, match="hash bucket"):
        _stage(source, out)

    assert not out.exists()


@POSIX_STAGING
def test_stage_refuses_a_source_hash_mismatch(tmp_path):
    source = _disk(tmp_path)
    before = source.read_bytes()
    out = _out("must-not-exist.adf")

    with pytest.raises(amigaacceptance.StageError, match="source SHA-256 differs"):
        amigaacceptance.stage_boot_disk(
            source, out,
            expected_source_sha256="0" * 64,
            expected_secret_sha256=sha256(b"synthetic executable").hexdigest(),
        )

    assert source.read_bytes() == before
    assert not out.exists()


@POSIX_STAGING
def test_stage_refuses_a_secret_hash_mismatch(tmp_path):
    source = _disk(tmp_path)
    before = source.read_bytes()
    out = _out("must-not-exist.adf")

    with pytest.raises(amigaacceptance.StageError, match="/Secret SHA-256 differs"):
        amigaacceptance.stage_boot_disk(
            source, out,
            expected_source_sha256=sha256(before).hexdigest(),
            expected_secret_sha256="0" * 64,
        )

    assert source.read_bytes() == before
    assert not out.exists()


@POSIX_STAGING
def test_stage_refuses_to_replace_an_existing_output(tmp_path):
    source = _disk(tmp_path)
    out = _out("existing.adf")
    out.parent.mkdir(parents=True)
    out.write_bytes(b"keep this file")

    with pytest.raises(amigaacceptance.StageError, match="output already exists"):
        _stage(source, out)

    assert out.read_bytes() == b"keep this file"


@POSIX_STAGING
def test_stage_refuses_an_output_outside_acceptance_roots(tmp_path):
    source = _disk(tmp_path)
    out = tmp_path / "players-disks" / "must-not-exist.adf"

    with pytest.raises(amigaacceptance.StageError, match="scratch or cache"):
        _stage(source, out)

    assert not out.exists()
    assert not out.parent.exists()


@POSIX_STAGING
def test_stage_accepts_the_dedicated_acceptance_cache(tmp_path):
    source = _disk(tmp_path)
    out = amigaacceptance.scratch.cache_dir("amigaacceptance") / "boot.adf"

    manifest = _stage(source, out)

    assert AmigaDisk.open(out).verify() == []
    assert manifest["staged_sha256"] == sha256(out.read_bytes()).hexdigest()


@POSIX_STAGING
def test_stage_refuses_a_symlink_into_an_outside_directory(tmp_path):
    source = _disk(tmp_path)
    player_dir = tmp_path / "players-disks"
    player_dir.mkdir()
    root = amigaacceptance.scratch.scratch_dir("amigaacceptance")
    root.mkdir(parents=True)
    (root / "linked").symlink_to(player_dir, target_is_directory=True)
    out = root / "linked" / "must-not-exist.adf"

    with pytest.raises(amigaacceptance.StageError, match="scratch or cache"):
        _stage(source, out)

    assert not out.exists()
    assert list(player_dir.iterdir()) == []


@POSIX_STAGING
def test_stage_refuses_a_parent_replaced_by_a_symlink_during_write(
    tmp_path, monkeypatch,
):
    source = _disk(tmp_path)
    player_dir = tmp_path / "players-disks"
    player_dir.mkdir()
    out = _out("must-not-exist.adf")
    original_mkdir = os.mkdir
    replaced = False

    def competing_mkdir(path, mode=0o777, *, dir_fd=None):
        nonlocal replaced
        if path == "wish" and dir_fd is not None and not replaced:
            replaced = True
            os.symlink(player_dir, path, dir_fd=dir_fd)
            return None
        return original_mkdir(path, mode, dir_fd=dir_fd)

    monkeypatch.setattr(amigaacceptance.os, "mkdir", competing_mkdir)
    with pytest.raises(amigaacceptance.StageError, match="symlink"):
        _stage(source, out)

    assert replaced
    assert not out.exists()
    assert list(player_dir.iterdir()) == []


@POSIX_STAGING
def test_stage_does_not_replace_an_output_created_during_staging(
    tmp_path, monkeypatch,
):
    source = _disk(tmp_path)
    out = _out("raced.adf")
    original_open = os.open
    created = False

    def competing_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal created
        if path == out.name and flags & os.O_EXCL:
            created = True
            competitor = original_open(
                path, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o644, dir_fd=dir_fd,
            )
            try:
                os.write(competitor, b"player-owned output")
            finally:
                os.close(competitor)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(amigaacceptance.os, "open", competing_open)
    with pytest.raises(amigaacceptance.StageError, match="output already exists"):
        _stage(source, out)

    assert created
    assert out.read_bytes() == b"player-owned output"


@POSIX_STAGING
def test_registered_side_a_stage_keeps_the_original_read_only(tmp_path):
    root = gamedisks.find("amiga")
    if root is None:
        pytest.skip("registered Amiga disks are unavailable")
    source = root / "Secret_Of_The_Silver_Blades" / "SecretOfTheSilverBlades_A.adf"
    if not source.is_file():
        pytest.skip("registered Silver Blades Amiga side A is unavailable")
    before = source.read_bytes()
    out = _out()

    manifest = amigaacceptance.stage_boot_disk(source, out)

    staged = AmigaDisk.open(out)
    assert source.read_bytes() == before
    assert staged.verify() == []
    assert staged.lookup("/SAVE_OFF_40").block == 919
    assert staged.read_file("/Secret") == AmigaDisk.open(source).read_file("/Secret")
    assert manifest["changed_blocks"] == [919]


def _stage_embedded(source, slot, letter, out):
    return amigaacceptance.stage_embedded_boot_disk(
        source, slot, letter, out,
        expected_source_sha256=sha256(source.read_bytes()).hexdigest(),
        expected_secret_sha256=sha256(b"synthetic executable").hexdigest(),
    )


@POSIX_STAGING
def test_embedded_stage_adds_only_the_slot_file_and_keeps_every_other_file(tmp_path):
    source = _disk(tmp_path)
    before = source.read_bytes()
    out = _out("boot-with-slot.adf")

    manifest = _stage_embedded(source, b"wish slot bytes", "C", out)

    staged = AmigaDisk.open(out)
    original = AmigaDisk.open(source)
    assert source.read_bytes() == before
    assert staged.verify() == []
    assert staged.read_file("/SAVE/savgamC.sav") == b"wish slot bytes"
    for path, _ in original.walk():
        assert staged.read_file(path) == original.read_file(path)
    assert before[:1024] == out.read_bytes()[:1024]
    assert manifest["slot_sha256"] == sha256(b"wish slot bytes").hexdigest()
    assert manifest["staged_sha256"] == sha256(out.read_bytes()).hexdigest()


@POSIX_STAGING
def test_embedded_stage_refuses_an_occupied_letter_without_writing(tmp_path):
    source = _disk(tmp_path)
    out = _out("must-not-exist.adf")

    with pytest.raises(amigaacceptance.StageError, match="savgamA.sav"):
        _stage_embedded(source, b"wish slot bytes", "A", out)

    assert not out.exists()


@POSIX_STAGING
def test_registered_side_a_embedded_stage_keeps_the_original_read_only(tmp_path):
    root = gamedisks.find("amiga")
    if root is None:
        pytest.skip("registered Amiga disks are unavailable")
    source = root / "Secret_Of_The_Silver_Blades" / "SecretOfTheSilverBlades_A.adf"
    if not source.is_file():
        pytest.skip("registered Silver Blades Amiga side A is unavailable")
    before = source.read_bytes()
    out = _out("registered-embedded.adf")

    amigaacceptance.stage_embedded_boot_disk(source, b"composed slot", "C", out)

    staged = AmigaDisk.open(out)
    assert source.read_bytes() == before
    assert staged.verify() == []
    assert staged.read_file("/SAVE/savgamC.sav") == b"composed slot"
    assert staged.read_file("/Secret") == AmigaDisk.open(source).read_file("/Secret")
